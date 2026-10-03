"""Conversion-worker health and environment-backed settings (S-05 Phase 3)."""

import contextlib
import datetime
import os
import runpy
from unittest import mock

from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError, IntegrityError
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from entries.eduvulcan import conversion
from entries.eduvulcan.health import (
    STALE_HEARTBEAT_MAX_AGE_MULTIPLIER,
    conversion_health,
    process_identity,
    prune_stale_heartbeats,
    record_heartbeat,
)
from entries.models import ConversionWorkerHeartbeat
from family_notes import settings as settings_module

URL = reverse('conversion_healthz')
SECRET = 'SENTINEL-4d1f'
RELEASE = '20260929T101500Z-0123456789ab'
OLD_RELEASE = '20260921T203945Z-ea1ff26284aa'

WORKER_SETTINGS = {
    'EDUVULCAN_WORKER_ENABLED': False,
    'EDUVULCAN_CONVERSION_SWEEP_INTERVAL_SECONDS': 60,
    'EDUVULCAN_CONVERSION_BATCH_SIZE': 50,
    'EDUVULCAN_CONVERSION_LEASE_SECONDS': 120,
    'EDUVULCAN_CONVERSION_MAX_ATTEMPTS': 3,
    'EDUVULCAN_CONVERSION_RETRY_DELAYS_SECONDS': (60, 300),
    'EDUVULCAN_RAW_RETENTION_DAYS': 90,
    'EDUVULCAN_WORKER_HEARTBEAT_SECONDS': 30,
    'EDUVULCAN_WORKER_HEARTBEAT_MAX_AGE_SECONDS': 180,
}


def evaluate_settings(**environ):
    """Evaluate settings.py without a .env file and with only ``environ`` set."""
    with mock.patch('dotenv.load_dotenv'), mock.patch.dict(
        os.environ, {'DJANGO_DEBUG': 'True', **environ}, clear=True
    ):
        return runpy.run_path(settings_module.__file__)


@override_settings(FAMILY_NOTES_RELEASE_ID=RELEASE)
class ConversionHealthEndpointTests(TestCase):
    def beat(self, age_seconds, *, name='host:100', release=RELEASE):
        ConversionWorkerHeartbeat.objects.update_or_create(
            name=name,
            defaults={
                'release': release,
                'beat_at': timezone.now() - datetime.timedelta(seconds=age_seconds),
            },
        )

    def test_database_health_body_is_unchanged(self):
        with override_settings(EDUVULCAN_WORKER_ENABLED=True):
            response = self.client.get(reverse('healthz'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'{"status": "ok"}')

    @override_settings(EDUVULCAN_WORKER_ENABLED=False)
    def test_disabled_conversion_is_reported_as_healthy_disabled(self):
        self.beat(age_seconds=10_000)

        response = self.client.get(URL)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'{"status": "disabled"}')

    @override_settings(EDUVULCAN_WORKER_ENABLED=True)
    def test_missing_heartbeat_is_unavailable(self):
        response = self.client.get(URL)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.content, b'{"status": "unavailable"}')

    @override_settings(
        EDUVULCAN_WORKER_ENABLED=True, EDUVULCAN_WORKER_HEARTBEAT_MAX_AGE_SECONDS=180
    )
    def test_fresh_heartbeat_is_ok(self):
        self.beat(age_seconds=170)

        response = self.client.get(URL)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'{"status": "ok"}')

    @override_settings(
        EDUVULCAN_WORKER_ENABLED=True, EDUVULCAN_WORKER_HEARTBEAT_MAX_AGE_SECONDS=180
    )
    def test_stale_heartbeat_is_unavailable(self):
        self.beat(age_seconds=181)

        response = self.client.get(URL)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.content, b'{"status": "unavailable"}')

    @override_settings(EDUVULCAN_WORKER_ENABLED=True)
    def test_fresh_heartbeat_of_a_previous_release_does_not_count(self):
        # Right after a deploy restart the old release's workers still look
        # fresh; health must not report a release whose workers never started.
        self.beat(age_seconds=1, name='host:100', release=OLD_RELEASE)
        self.beat(age_seconds=1, name='host:101', release='')

        response = self.client.get(URL)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.content, b'{"status": "unavailable"}')

    @override_settings(
        EDUVULCAN_WORKER_ENABLED=True, EDUVULCAN_WORKER_HEARTBEAT_MAX_AGE_SECONDS=180
    )
    def test_one_fresh_current_release_process_is_enough(self):
        self.beat(age_seconds=5, name='host:100', release=OLD_RELEASE)
        self.beat(age_seconds=500, name='host:200', release=RELEASE)
        self.assertEqual(self.client.get(URL).status_code, 503)

        self.beat(age_seconds=5, name='host:201', release=RELEASE)
        response = self.client.get(URL)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'{"status": "ok"}')

    @override_settings(EDUVULCAN_WORKER_ENABLED=True)
    def test_database_failure_is_unavailable_without_details(self):
        with mock.patch.object(
            ConversionWorkerHeartbeat.objects, 'filter', side_effect=DatabaseError(SECRET)
        ):
            response = self.client.get(URL)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.content, b'{"status": "unavailable"}')

    @override_settings(EDUVULCAN_WORKER_ENABLED=True)
    def test_probe_is_read_only(self):
        self.beat(age_seconds=1)

        self.assertEqual(self.client.head(URL).status_code, 200)
        self.assertEqual(self.client.post(URL).status_code, 405)


@override_settings(FAMILY_NOTES_RELEASE_ID=RELEASE)
class HeartbeatRecordTests(TestCase):
    def test_each_process_upserts_its_own_row_with_the_release(self):
        first = timezone.now()
        record_heartbeat(identity='host:100', now=first)
        record_heartbeat(identity='host:101', now=first)
        record_heartbeat(identity='host:100', now=first + datetime.timedelta(seconds=30))

        rows = {
            row.name: (row.release, row.beat_at)
            for row in ConversionWorkerHeartbeat.objects.all()
        }
        self.assertEqual(
            rows,
            {
                'host:100': (RELEASE, first + datetime.timedelta(seconds=30)),
                'host:101': (RELEASE, first),
            },
        )

    def test_reused_identity_takes_over_the_row_for_the_new_release(self):
        now = timezone.now()
        ConversionWorkerHeartbeat.objects.create(
            name='host:100', release=OLD_RELEASE, beat_at=now - datetime.timedelta(hours=1)
        )

        record_heartbeat(identity='host:100', now=now)

        row = ConversionWorkerHeartbeat.objects.get()
        self.assertEqual((row.release, row.beat_at), (RELEASE, now))

    def test_default_identity_is_hostname_and_pid(self):
        with mock.patch('entries.eduvulcan.health.socket.gethostname', return_value='web-1'), \
                mock.patch('entries.eduvulcan.health.os.getpid', return_value=4321):
            self.assertEqual(process_identity(), 'web-1:4321')
            record_heartbeat()

        self.assertEqual(ConversionWorkerHeartbeat.objects.get().name, 'web-1:4321')

    def test_long_hostname_keeps_the_pid(self):
        with mock.patch('entries.eduvulcan.health.socket.gethostname', return_value='h' * 300):
            identity = process_identity(987654)

        self.assertLessEqual(len(identity), 64)
        self.assertTrue(identity.endswith(':987654'))

    def test_concurrent_first_heartbeat_falls_back_to_update(self):
        now = timezone.now()
        real_create = ConversionWorkerHeartbeat.objects.create

        def lose_race(**kwargs):
            # A row with this identity appears between our update and create.
            real_create(name='host:100', beat_at=now - datetime.timedelta(hours=1))
            raise IntegrityError

        # Without the savepoint the competing insert survives our failed one.
        with mock.patch.object(
            ConversionWorkerHeartbeat.objects, 'create', side_effect=lose_race
        ), mock.patch('entries.eduvulcan.health.transaction.atomic', contextlib.nullcontext):
            record_heartbeat(identity='host:100', now=now)

        row = ConversionWorkerHeartbeat.objects.get()
        self.assertEqual((row.beat_at, row.release), (now, RELEASE))

    @override_settings(EDUVULCAN_WORKER_HEARTBEAT_MAX_AGE_SECONDS=180)
    def test_prune_deletes_only_long_stale_rows_of_any_release(self):
        now = timezone.now()
        window = datetime.timedelta(seconds=180 * STALE_HEARTBEAT_MAX_AGE_MULTIPLIER)
        for name, release, age in (
            ('host:1', OLD_RELEASE, window + datetime.timedelta(seconds=1)),
            ('host:2', RELEASE, window + datetime.timedelta(seconds=1)),
            ('host:3', OLD_RELEASE, window - datetime.timedelta(seconds=1)),
            ('host:4', RELEASE, datetime.timedelta(seconds=1)),
        ):
            ConversionWorkerHeartbeat.objects.create(
                name=name, release=release, beat_at=now - age
            )

        self.assertEqual(prune_stale_heartbeats(now=now), 2)

        self.assertEqual(
            set(ConversionWorkerHeartbeat.objects.values_list('name', flat=True)),
            {'host:3', 'host:4'},
        )

    @override_settings(EDUVULCAN_WORKER_ENABLED=True)
    def test_health_follows_the_configured_release(self):
        record_heartbeat(identity='host:100')

        self.assertEqual(conversion_health(), 'ok')
        with override_settings(FAMILY_NOTES_RELEASE_ID=OLD_RELEASE):
            self.assertEqual(conversion_health(), 'unavailable')


class WorkerSettingsTests(SimpleTestCase):
    def test_defaults_are_safe_and_disabled(self):
        values = evaluate_settings()

        self.assertEqual({name: values[name] for name in WORKER_SETTINGS}, WORKER_SETTINGS)

    def test_conversion_service_reads_the_configured_values(self):
        with override_settings(
            EDUVULCAN_CONVERSION_LEASE_SECONDS=90,
            EDUVULCAN_CONVERSION_MAX_ATTEMPTS=4,
            EDUVULCAN_CONVERSION_RETRY_DELAYS_SECONDS=(30, 120, 600),
            EDUVULCAN_RAW_RETENTION_DAYS=30,
            EDUVULCAN_CONVERSION_BATCH_SIZE=10,
        ):
            self.assertEqual(conversion.lease_seconds(), 90)
            self.assertEqual(conversion.max_attempts(), 4)
            self.assertEqual(conversion.retry_delays_seconds(), (30, 120, 600))
            self.assertEqual(conversion.raw_retention_days(), 30)
            self.assertEqual(conversion.batch_size(), 10)

    def test_environment_overrides_are_parsed(self):
        values = evaluate_settings(
            EDUVULCAN_WORKER_ENABLED='true',
            EDUVULCAN_CONVERSION_SWEEP_INTERVAL_SECONDS='30',
            EDUVULCAN_CONVERSION_RETRY_DELAYS_SECONDS=' 45, 240 ',
            EDUVULCAN_WORKER_HEARTBEAT_SECONDS='15',
            EDUVULCAN_WORKER_HEARTBEAT_MAX_AGE_SECONDS='90',
        )

        self.assertTrue(values['EDUVULCAN_WORKER_ENABLED'])
        self.assertEqual(values['EDUVULCAN_CONVERSION_SWEEP_INTERVAL_SECONDS'], 30)
        self.assertEqual(values['EDUVULCAN_CONVERSION_RETRY_DELAYS_SECONDS'], (45, 240))
        self.assertEqual(values['EDUVULCAN_WORKER_HEARTBEAT_SECONDS'], 15)
        self.assertEqual(values['EDUVULCAN_WORKER_HEARTBEAT_MAX_AGE_SECONDS'], 90)

    def test_unknown_enablement_value_stays_disabled(self):
        values = evaluate_settings(EDUVULCAN_WORKER_ENABLED='maybe')

        self.assertFalse(values['EDUVULCAN_WORKER_ENABLED'])

    def test_invalid_numbers_stop_startup_naming_only_the_variable(self):
        numeric = [
            name
            for name, value in WORKER_SETTINGS.items()
            if isinstance(value, int) and not isinstance(value, bool)
        ]
        for name in numeric:
            for raw in ('abc', '0', '-5', '1.5', f'{SECRET}'):
                with self.subTest(name=name, raw=raw):
                    with self.assertRaises(ImproperlyConfigured) as caught:
                        evaluate_settings(**{name: raw})
                    self.assertIn(name, str(caught.exception))
                    self.assertNotIn(SECRET, str(caught.exception))

    def test_invalid_retry_delays_stop_startup(self):
        name = 'EDUVULCAN_CONVERSION_RETRY_DELAYS_SECONDS'
        for raw in ('60,x', '60,0', '-1', ',', f'60,{SECRET}'):
            with self.subTest(raw=raw):
                with self.assertRaises(ImproperlyConfigured) as caught:
                    evaluate_settings(**{name: raw})
                self.assertIn(name, str(caught.exception))
                self.assertNotIn(SECRET, str(caught.exception))

    def test_lease_must_exceed_the_classification_deadline_with_a_margin(self):
        # Default deadline 25 s + 30 s margin: 55 s is the smallest valid lease.
        for lease, deadline in (('54', '25'), ('25', '25'), ('120', '100')):
            with self.subTest(lease=lease, deadline=deadline):
                with self.assertRaises(ImproperlyConfigured) as caught:
                    evaluate_settings(
                        EDUVULCAN_CONVERSION_LEASE_SECONDS=lease,
                        CLASSIFICATION_DEADLINE_SECONDS=deadline,
                    )
                message = str(caught.exception)
                self.assertIn('EDUVULCAN_CONVERSION_LEASE_SECONDS', message)
                self.assertIn('CLASSIFICATION_DEADLINE_SECONDS', message)
                # Names the variables, never the configured values.
                self.assertNotIn(lease, message)

        values = evaluate_settings(
            EDUVULCAN_CONVERSION_LEASE_SECONDS='55', CLASSIFICATION_DEADLINE_SECONDS='25'
        )
        self.assertEqual(values['EDUVULCAN_CONVERSION_LEASE_SECONDS'], 55)

    def test_release_id_comes_from_the_environment_or_the_resolved_project_directory(self):
        self.assertEqual(
            evaluate_settings(FAMILY_NOTES_RELEASE_ID=f' {RELEASE} ')['FAMILY_NOTES_RELEASE_ID'],
            RELEASE,
        )
        values = evaluate_settings()
        self.assertEqual(values['FAMILY_NOTES_RELEASE_ID'], values['BASE_DIR'].name)
        self.assertEqual(values['BASE_DIR'], values['BASE_DIR'].resolve())

    def test_conversion_logs_reach_the_console_at_info(self):
        logging_config = evaluate_settings()['LOGGING']

        self.assertFalse(logging_config['disable_existing_loggers'])
        self.assertEqual(
            logging_config['loggers']['entries.eduvulcan'],
            {'handlers': ['console'], 'level': 'INFO', 'propagate': False},
        )
        self.assertEqual(
            logging_config['loggers']['entries.classification'],
            {'handlers': ['console'], 'level': 'INFO', 'propagate': True},
        )
        self.assertEqual(
            set(logging_config['loggers']), {'entries.eduvulcan', 'entries.classification'}
        )

    def test_heartbeat_freshness_must_exceed_the_interval(self):
        for max_age in ('30', '10'):
            with self.subTest(max_age=max_age), self.assertRaises(ImproperlyConfigured):
                evaluate_settings(
                    EDUVULCAN_WORKER_HEARTBEAT_SECONDS='30',
                    EDUVULCAN_WORKER_HEARTBEAT_MAX_AGE_SECONDS=max_age,
                )
