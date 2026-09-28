"""In-process conversion worker and post-commit intake wake-up (S-05 Phase 3).

The worker is driven one iteration at a time through ``run_once`` with a fake
monotonic clock, so nothing sleeps. Connection housekeeping is patched in
``TestCase`` tests because closing the test thread's connection would break
the surrounding test transaction. SQLite exercises the functional contract;
the PostgreSQL advisory lock is pinned by its SQL and by simulated refusal.
"""

import datetime
import io
import json
import runpy
import threading
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core.management import call_command
from django.db import DatabaseError
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from entries.eduvulcan import conversion, worker as worker_module
from entries.eduvulcan.health import HEARTBEAT_NAME
from entries.eduvulcan.worker import (
    ADVISORY_LOCK_KEY,
    LOCK_RETRY_SECONDS,
    MAINTENANCE_INTERVAL_SECONDS,
    ConversionWorker,
    conversion_lock,
    current_worker,
    enqueue_notification,
    start_worker,
    stop_worker,
)
from entries.models import ConversionWorkerHeartbeat, Entry, InboundNotification
from family_access.models import AutomationToken
from family_access.test_automation import AutomationFixtureMixin

from .test_classification_service import FamilyFixtureMixin
from .test_conversion_models import make_notification
from .test_notification_intake import sample_payload

Status = InboundNotification.Status
TEST_TITLE = 'Sprawdzian'
TEST_MESSAGE = '2 października, Biologia (biologia), Michał'
GUNICORN_CONF = Path(settings.BASE_DIR) / 'gunicorn.conf.py'


class FakeClock:
    def __init__(self, start=1000.0):
        self.value = start

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class NoProviderBackend:
    """Fixed-rule fixtures must never reach the classifier."""

    def classify(self, request):
        raise AssertionError('the worker fixtures must convert through fixed rules')


def patch_connection_housekeeping(test):
    """Patch connection recycling for the duration of ``test``; return the mocks."""
    patches = {
        'close_old': mock.patch.object(worker_module, 'close_old_connections'),
        'close_thread': mock.patch.object(worker_module, 'close_thread_connections'),
    }
    mocks = {name: patcher.start() for name, patcher in patches.items()}
    for patcher in patches.values():
        test.addCleanup(patcher.stop)
    return mocks


class WorkerTestCase(FamilyFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.connections = patch_connection_housekeeping(self)
        self.clock = FakeClock()
        self.worker = ConversionWorker(backend=NoProviderBackend(), monotonic=self.clock)

    def notification(self, index=1, **overrides):
        overrides.setdefault('content_hash', f'{index:064d}')
        return make_notification(
            self.family, index, title=TEST_TITLE, message=TEST_MESSAGE, **overrides
        )

    def status(self, row):
        row.refresh_from_db()
        return row.status


class StartupAndPeriodicSweepTests(WorkerTestCase):
    def test_first_iteration_is_the_startup_sweep(self):
        rows = [self.notification(index) for index in (1, 2)]

        with mock.patch.object(
            conversion, 'prune_raw_notifications', wraps=conversion.prune_raw_notifications
        ) as prune:
            self.worker.run_once()

        self.assertEqual([self.status(row) for row in rows], [Status.PROCESSED] * 2)
        self.assertEqual(Entry.objects.filter(source=Entry.Source.EDUVULCAN).count(), 2)
        self.assertTrue(ConversionWorkerHeartbeat.objects.filter(name=HEARTBEAT_NAME).exists())
        prune.assert_called_once()

    @override_settings(
        EDUVULCAN_CONVERSION_SWEEP_INTERVAL_SECONDS=60, EDUVULCAN_WORKER_HEARTBEAT_SECONDS=120
    )
    def test_periodic_sweep_runs_on_the_configured_interval(self):
        self.worker.run_once()
        late = self.notification(3)

        self.clock.advance(59)
        self.assertEqual(self.worker.seconds_until_due(), 1)
        self.worker.run_once()
        self.assertEqual(self.status(late), Status.PENDING)

        self.clock.advance(1)
        self.assertEqual(self.worker.seconds_until_due(), 0)
        self.worker.run_once()
        self.assertEqual(self.status(late), Status.PROCESSED)

    def test_sweep_selects_retry_due_and_stale_rows_only(self):
        now = timezone.now()
        due_retry = self.notification(1, next_attempt_at=now - datetime.timedelta(seconds=1))
        future_retry = self.notification(2, next_attempt_at=now + datetime.timedelta(hours=1))
        stale = self.notification(
            3,
            status=Status.PROCESSING,
            attempt_count=1,
            lease_expires_at=now - datetime.timedelta(seconds=1),
        )
        leased = self.notification(
            4,
            status=Status.PROCESSING,
            attempt_count=1,
            lease_expires_at=now + datetime.timedelta(minutes=2),
        )

        self.worker.run_once()

        self.assertEqual(self.status(due_retry), Status.PROCESSED)
        self.assertEqual(self.status(stale), Status.PROCESSED)
        self.assertEqual(self.status(future_retry), Status.PENDING)
        self.assertEqual(self.status(leased), Status.PROCESSING)

    @override_settings(EDUVULCAN_CONVERSION_BATCH_SIZE=2)
    def test_full_batch_schedules_an_immediate_follow_up_sweep(self):
        rows = [self.notification(index) for index in (1, 2, 3)]

        self.worker.run_once()
        self.assertEqual(self.status(rows[2]), Status.PENDING)
        self.assertEqual(self.worker.seconds_until_due(), 0)

        self.worker.run_once()
        self.assertEqual(self.status(rows[2]), Status.PROCESSED)

    def test_maintenance_prunes_hourly(self):
        with mock.patch.object(conversion, 'prune_raw_notifications', return_value=0) as prune:
            self.worker.run_once()
            self.clock.advance(MAINTENANCE_INTERVAL_SECONDS - 1)
            self.worker.run_once()
            self.assertEqual(prune.call_count, 1)
            self.clock.advance(1)
            self.worker.run_once()

        self.assertEqual(prune.call_count, 2)

    def test_woken_rows_are_converted_before_the_next_sweep(self):
        self.worker.run_once()
        row = self.notification(5)

        self.clock.advance(1)
        self.worker.run_once([row.pk, row.pk])

        self.assertEqual(self.status(row), Status.PROCESSED)
        self.assertEqual(Entry.objects.count(), 1)


class HeartbeatScheduleTests(WorkerTestCase):
    @override_settings(EDUVULCAN_WORKER_HEARTBEAT_SECONDS=30)
    def test_heartbeat_is_bounded_even_during_a_long_batch(self):
        for index in (1, 2, 3):
            self.notification(index)

        def slow_conversion(notification_id, **kwargs):
            self.clock.advance(40)

        with mock.patch.object(
            conversion, 'convert_notification', side_effect=slow_conversion
        ), mock.patch.object(worker_module, 'record_heartbeat') as heartbeat:
            self.worker.run_once()

        # Startup, then after each 40-second conversion.
        self.assertEqual(heartbeat.call_count, 4)

    @override_settings(EDUVULCAN_WORKER_HEARTBEAT_SECONDS=30)
    def test_idle_worker_beats_on_its_interval(self):
        with mock.patch.object(worker_module, 'record_heartbeat') as heartbeat:
            self.worker.run_once()
            self.clock.advance(29)
            self.worker.run_once()
            self.clock.advance(1)
            self.worker.run_once()

        self.assertEqual(heartbeat.call_count, 2)


class AdvisoryLockTests(WorkerTestCase):
    def test_refused_lock_converts_nothing_and_retries_shortly(self):
        row = self.notification()

        with mock.patch.object(worker_module, 'try_advisory_lock', return_value=False), \
                mock.patch.object(worker_module, 'release_advisory_lock') as release:
            self.worker.run_once([row.pk])

        self.assertEqual(self.status(row), Status.PENDING)
        release.assert_not_called()
        # The refused worker is still alive and says so.
        self.assertTrue(ConversionWorkerHeartbeat.objects.exists())
        self.assertEqual(self.worker.seconds_until_due(), LOCK_RETRY_SECONDS)

        self.clock.advance(LOCK_RETRY_SECONDS)
        self.worker.run_once()
        self.assertEqual(self.status(row), Status.PROCESSED)

    def test_lock_is_released_after_work_and_after_errors(self):
        with mock.patch.object(worker_module, 'try_advisory_lock', return_value=True), \
                mock.patch.object(worker_module, 'release_advisory_lock') as release:
            with conversion_lock() as acquired:
                self.assertTrue(acquired)
            self.assertEqual(release.call_count, 1)

            with self.assertRaises(RuntimeError), conversion_lock():
                raise RuntimeError
            self.assertEqual(release.call_count, 2)

    def test_non_postgresql_lock_is_always_acquired(self):
        self.assertNotEqual(worker_module.connection.vendor, 'postgresql')
        self.assertTrue(worker_module.try_advisory_lock())

    def test_postgresql_uses_a_stable_non_blocking_session_lock(self):
        fake = mock.MagicMock(vendor='postgresql')
        cursor = fake.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (False,)

        with mock.patch.object(worker_module, 'connection', fake):
            self.assertFalse(worker_module.try_advisory_lock())
            worker_module.release_advisory_lock()

        statements = [call.args for call in cursor.execute.call_args_list]
        self.assertEqual(
            statements,
            [
                ('SELECT pg_try_advisory_lock(%s)', [ADVISORY_LOCK_KEY]),
                ('SELECT pg_advisory_unlock(%s)', [ADVISORY_LOCK_KEY]),
            ],
        )
        self.assertEqual(ADVISORY_LOCK_KEY, int.from_bytes(b'FNEVCONV', 'big'))

    def test_failed_unlock_closes_the_session(self):
        fake = mock.MagicMock(vendor='postgresql')
        fake.cursor.return_value.__enter__.return_value.execute.side_effect = DatabaseError

        with mock.patch.object(worker_module, 'connection', fake):
            worker_module.release_advisory_lock()

        fake.close.assert_called_once()


class WorkerResilienceTests(WorkerTestCase):
    def test_database_failure_is_logged_safely_and_not_retried_hot(self):
        with mock.patch.object(
            conversion, 'find_due_notification_ids', side_effect=DatabaseError('SECRET-TEXT')
        ), self.assertLogs('entries.eduvulcan.worker', 'WARNING') as logs:
            self.worker.run_once()

        output = '\n'.join(logs.output)
        self.assertIn('error=DatabaseError', output)
        self.assertNotIn('SECRET-TEXT', output)
        self.connections['close_thread'].assert_called_once()
        self.assertGreater(self.worker.seconds_until_due(), 0)

    def test_each_iteration_recycles_stale_connections(self):
        self.worker.run_once()

        self.assertEqual(self.connections['close_old'].call_count, 2)
        self.connections['close_thread'].assert_not_called()


class WakeupQueueTests(SimpleTestCase):
    def test_enqueue_is_bounded_and_refused_once_stopping(self):
        worker = ConversionWorker(queue_size=2)

        self.assertTrue(worker.enqueue(1))
        self.assertTrue(worker.enqueue(2))
        self.assertFalse(worker.enqueue(3))

        worker = ConversionWorker()
        worker.stop()
        self.assertFalse(worker.enqueue(1))

    def test_wait_drains_queued_ids_and_honours_stop(self):
        clock = FakeClock()
        worker = ConversionWorker(monotonic=clock)
        worker.enqueue(7)
        worker.enqueue(8)

        self.assertEqual(worker._wait_for_wakeups(), [7, 8])

        worker.stop()
        self.assertEqual(worker._wait_for_wakeups(), [])
        self.assertTrue(worker.stopping)


class WorkerThreadTests(SimpleTestCase):
    """A real thread, with database work patched out."""

    def test_thread_closes_its_own_connections_on_exit(self):
        closed_in = []
        iterations = threading.Event()

        worker = ConversionWorker()

        def run_once(woken=()):
            # Nothing is due for an hour, so the thread blocks on its queue.
            later = worker._monotonic() + 3600
            worker._next_heartbeat = worker._next_sweep = worker._next_maintenance = later
            iterations.set()

        with mock.patch.object(worker, 'run_once', side_effect=run_once), mock.patch.object(
            worker_module,
            'close_thread_connections',
            side_effect=lambda: closed_in.append(threading.current_thread().name),
        ):
            worker.start()
            self.assertTrue(iterations.wait(5))
            worker.stop(timeout=5)

        self.assertFalse(worker.is_alive())
        self.assertEqual(closed_in, ['eduvulcan-conversion'])


class WorkerStartupGuardTests(SimpleTestCase):
    # The management commands below only read migration state.
    databases = {'default'}

    def setUp(self):
        super().setUp()
        self.addCleanup(setattr, worker_module, '_worker', None)

    def conversion_threads(self):
        return [t for t in threading.enumerate() if t.name == 'eduvulcan-conversion']

    def test_import_and_management_commands_never_start_a_worker(self):
        with override_settings(EDUVULCAN_WORKER_ENABLED=True):
            call_command('check', verbosity=0)
            call_command('makemigrations', check=True, dry_run=True, verbosity=0)
            call_command('migrate', plan=True, verbosity=0, stdout=io.StringIO())

        self.assertIsNone(current_worker())
        self.assertEqual(self.conversion_threads(), [])

    @override_settings(EDUVULCAN_WORKER_ENABLED=False)
    def test_disabled_worker_does_not_start(self):
        with mock.patch.object(ConversionWorker, 'start') as start:
            self.assertIsNone(start_worker())

        start.assert_not_called()
        self.assertIsNone(current_worker())

    @override_settings(EDUVULCAN_WORKER_ENABLED=True)
    def test_enabled_worker_starts_once_per_process_and_stops(self):
        with mock.patch.object(ConversionWorker, 'start') as start, mock.patch.object(
            ConversionWorker, 'is_alive', return_value=True
        ):
            first = start_worker()
            second = start_worker()

        self.assertIs(first, second)
        start.assert_called_once()
        self.assertIs(current_worker(), first)

        with mock.patch('entries.eduvulcan.worker.os.getpid', return_value=first.pid + 1):
            # A forked child never reuses its parent's worker.
            self.assertIsNone(current_worker())

        stop_worker()
        self.assertTrue(first.stopping)
        self.assertIsNone(current_worker())

    def test_enqueue_without_a_worker_is_a_no_op(self):
        self.assertFalse(enqueue_notification(1))


class GunicornHookTests(SimpleTestCase):
    def setUp(self):
        super().setUp()
        self.hooks = runpy.run_path(str(GUNICORN_CONF))
        self.gunicorn_worker = mock.Mock()

    def test_post_worker_init_starts_and_worker_exit_stops(self):
        with mock.patch.object(worker_module, 'start_worker') as start:
            self.hooks['post_worker_init'](self.gunicorn_worker)
        with mock.patch.object(worker_module, 'stop_worker') as stop:
            self.hooks['worker_exit'](mock.Mock(), self.gunicorn_worker)

        start.assert_called_once_with()
        stop.assert_called_once_with()

    def test_start_failure_never_prevents_the_worker_from_serving(self):
        with mock.patch.object(worker_module, 'start_worker', side_effect=RuntimeError('SECRET')):
            self.hooks['post_worker_init'](self.gunicorn_worker)

        message = self.gunicorn_worker.log.warning.call_args
        self.assertIn('RuntimeError', message.args)
        self.assertNotIn('SECRET', str(message))

    def test_config_defines_hooks_only(self):
        public = {name for name in self.hooks if not name.startswith('__')}

        self.assertEqual(public, {'post_worker_init', 'worker_exit'})


class IntakeWakeupTests(AutomationFixtureMixin, TestCase):
    URL = reverse('automation_notification_submit')

    def setUp(self):
        super().setUp()
        self.token, self.secret = AutomationToken.issue(self.parent, 'Telefon')
        self.worker = ConversionWorker()
        worker_module._worker = self.worker
        self.addCleanup(setattr, worker_module, '_worker', None)

    def post(self, payload=None):
        return self.client.post(
            self.URL,
            data=json.dumps(payload or sample_payload()),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {self.secret}',
        )

    def queued(self):
        return self.worker._wait_for_wakeups()

    @override_settings(EDUVULCAN_WORKER_ENABLED=True)
    def test_new_row_is_enqueued_after_commit(self):
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            response = self.post()

        self.assertEqual(response.status_code, 202)
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(self.queued(), [response.json()['id']])

    @override_settings(EDUVULCAN_WORKER_ENABLED=True)
    def test_request_stays_bounded_and_does_no_conversion_work(self):
        def fail_if_called(*args, **kwargs):
            raise AssertionError('conversion must not run in the intake request')

        with mock.patch.object(
            conversion, 'convert_notification', side_effect=fail_if_called
        ), mock.patch.object(
            conversion, 'claim_notification', side_effect=fail_if_called
        ), mock.patch(
            'entries.classification.service.classify_for_family', side_effect=fail_if_called
        ), self.assertNumQueries(6), self.captureOnCommitCallbacks(execute=True):
            response = self.post()

        self.assertEqual(response.status_code, 202)
        row = InboundNotification.objects.get()
        self.assertEqual((row.status, row.attempt_count), (Status.PENDING, 0))

    @override_settings(EDUVULCAN_WORKER_ENABLED=True)
    def test_queue_failure_keeps_the_durable_202(self):
        with mock.patch.object(
            ConversionWorker, 'enqueue', side_effect=RuntimeError('SECRET-TEXT')
        ), self.assertLogs('entries.eduvulcan.worker', 'WARNING') as logs, \
                self.captureOnCommitCallbacks(execute=True):
            response = self.post()

        self.assertEqual(response.status_code, 202)
        self.assertEqual(InboundNotification.objects.get().pk, response.json()['id'])
        self.assertIn('error=RuntimeError', logs.output[0])
        self.assertNotIn('SECRET-TEXT', logs.output[0])
        self.assertNotIn('Przykładowy', logs.output[0])

    @override_settings(EDUVULCAN_WORKER_ENABLED=True)
    def test_full_queue_keeps_the_durable_202(self):
        self.worker = ConversionWorker(queue_size=1)
        self.worker.enqueue(999)
        worker_module._worker = self.worker

        with self.captureOnCommitCallbacks(execute=True):
            response = self.post()

        self.assertEqual(response.status_code, 202)
        self.assertEqual(self.queued(), [999])

    @override_settings(EDUVULCAN_WORKER_ENABLED=True)
    def test_registration_failure_keeps_the_durable_202(self):
        with mock.patch(
            'entries.eduvulcan.worker.transaction.on_commit', side_effect=RuntimeError
        ), self.assertLogs('entries.eduvulcan.worker', 'WARNING'):
            response = self.post()

        self.assertEqual(response.status_code, 202)
        self.assertTrue(InboundNotification.objects.exists())

    @override_settings(EDUVULCAN_WORKER_ENABLED=False)
    def test_disabled_worker_registers_no_wakeup(self):
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            response = self.post()

        self.assertEqual(response.status_code, 202)
        self.assertEqual(callbacks, [])
        self.assertEqual(self.queued(), [])

    @override_settings(EDUVULCAN_WORKER_ENABLED=True)
    def test_duplicate_intake_neither_wakes_nor_resets_lifecycle(self):
        with self.captureOnCommitCallbacks(execute=True):
            first = self.post().json()['id']
        self.queued()
        InboundNotification.objects.filter(pk=first).update(
            status=Status.PROCESSING,
            attempt_count=1,
            lease_expires_at=timezone.now() + datetime.timedelta(minutes=2),
        )

        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            response = self.post()

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()['id'], first)
        self.assertEqual(callbacks, [])
        self.assertEqual(self.queued(), [])
        row = InboundNotification.objects.get()
        self.assertEqual((row.status, row.attempt_count), (Status.PROCESSING, 1))
        self.assertFalse(Entry.objects.exists())
