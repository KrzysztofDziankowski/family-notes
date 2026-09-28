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
from entries.eduvulcan.health import HEARTBEAT_NAME, record_heartbeat
from entries.models import ConversionWorkerHeartbeat
from family_notes import settings as settings_module

URL = reverse('conversion_healthz')
SECRET = 'SENTINEL-4d1f'

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


class ConversionHealthEndpointTests(TestCase):
    def beat(self, age_seconds):
        ConversionWorkerHeartbeat.objects.update_or_create(
            name=HEARTBEAT_NAME,
            defaults={'beat_at': timezone.now() - datetime.timedelta(seconds=age_seconds)},
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


class HeartbeatRecordTests(TestCase):
    def test_heartbeat_upserts_one_shared_row(self):
        first = timezone.now()
        record_heartbeat(now=first)
        record_heartbeat(now=first + datetime.timedelta(seconds=30))

        row = ConversionWorkerHeartbeat.objects.get()
        self.assertEqual(row.name, HEARTBEAT_NAME)
        self.assertEqual(row.beat_at, first + datetime.timedelta(seconds=30))

    def test_concurrent_first_heartbeat_falls_back_to_update(self):
        now = timezone.now()
        real_create = ConversionWorkerHeartbeat.objects.create

        def lose_race(**kwargs):
            # Another process inserts the row between our update and create.
            real_create(name=HEARTBEAT_NAME, beat_at=now - datetime.timedelta(hours=1))
            raise IntegrityError

        # Without the savepoint the competing insert survives our failed one.
        with mock.patch.object(
            ConversionWorkerHeartbeat.objects, 'create', side_effect=lose_race
        ), mock.patch('entries.eduvulcan.health.transaction.atomic', contextlib.nullcontext):
            record_heartbeat(now=now)

        self.assertEqual(ConversionWorkerHeartbeat.objects.get().beat_at, now)


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

    def test_heartbeat_freshness_must_exceed_the_interval(self):
        for max_age in ('30', '10'):
            with self.subTest(max_age=max_age), self.assertRaises(ImproperlyConfigured):
                evaluate_settings(
                    EDUVULCAN_WORKER_HEARTBEAT_SECONDS='30',
                    EDUVULCAN_WORKER_HEARTBEAT_MAX_AGE_SECONDS=max_age,
                )
