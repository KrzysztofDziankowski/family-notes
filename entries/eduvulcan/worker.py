"""In-process EduVulcan conversion worker: wake-ups, sweeps, heartbeat, pruning.

Startup mechanism (accepted implementation-time decision)
---------------------------------------------------------
The worker thread is started only by Gunicorn's ``post_worker_init`` hook in
the repository's ``gunicorn.conf.py``. That hook runs inside each worker
process after the fork and after the WSGI application (and therefore Django)
is loaded, so:

- a ``--preload`` master never owns the thread (it would be lost at fork);
- ``manage.py test``, ``migrate``, ``shell``, ``runserver``, and every other
  management command never start it, and neither does importing the
  application or ``AppConfig.ready()``;
- a restart sweeps the database immediately, without waiting for the first
  request. A lazy first-request start was rejected for exactly that reason:
  pending rows would sit unconverted after a restart until someone visited
  the site.

Each process runs one daemon thread. The database is the source of truth; the
in-memory queue only carries post-commit wake-ups, so a lost queue (restart,
full queue, stopped worker) costs latency, never data. Startup and periodic
sweeps pick up pending, retry-due, and stale-processing rows.

Each process's thread records its own heartbeat row (hostname and PID, plus
the running release) only while the thread runs; hourly maintenance deletes
rows of exited processes and old releases. See ``health.py``.

Global concurrency is one: on PostgreSQL a stable session-level advisory lock
(``pg_try_advisory_lock``) guards every conversion batch, so with two
Gunicorn processes only one converts at a time and the other retries shortly
after. Other database vendors (SQLite in development and tests) treat the
lock as always acquired; they follow the same functional contract but do not
validate cross-process locking.

The thread uses its own database connections (Django connections are
thread-local), recycles stale ones between units of work, and closes them
when it exits.

Logs carry only process IDs, notification IDs, counts, and exception class
names, never notification text, classifier payloads, tokens, or names.
"""

from __future__ import annotations

import logging
import os
import queue
import threading
import time
from contextlib import contextmanager
from typing import Callable, Iterable, List, Optional

from django.conf import settings
from django.db import DatabaseError, close_old_connections, connection, connections, transaction

from . import conversion
from .health import (
    heartbeat_seconds,
    process_identity,
    prune_stale_heartbeats,
    record_heartbeat,
    worker_enabled,
)

logger = logging.getLogger(__name__)

# Stable key shared by every process: ASCII "FNEVCONV" as a signed 64-bit int.
ADVISORY_LOCK_KEY = 0x464E4556434F4E56
# How soon a process whose lock attempt was refused tries again.
LOCK_RETRY_SECONDS = 5
# Raw-data pruning cadence (Phase 2 retention service).
MAINTENANCE_INTERVAL_SECONDS = 3600
# Wake-ups beyond this are dropped; the next sweep finds those rows anyway.
QUEUE_MAX_SIZE = 1000
# How long a Gunicorn worker waits for the thread on exit before leaving it.
STOP_TIMEOUT_SECONDS = 5.0

_STOP = object()


def sweep_interval_seconds() -> int:
    return int(getattr(settings, 'EDUVULCAN_CONVERSION_SWEEP_INTERVAL_SECONDS', 60))


def close_thread_connections() -> None:
    """Close every database connection owned by the calling thread."""
    connections.close_all()


def try_advisory_lock() -> bool:
    """Take the global conversion lock without waiting; ``True`` when held.

    A no-op that always succeeds on non-PostgreSQL databases.
    """
    if connection.vendor != 'postgresql':
        return True
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_try_advisory_lock(%s)', [ADVISORY_LOCK_KEY])
        return bool(cursor.fetchone()[0])


def release_advisory_lock() -> None:
    if connection.vendor != 'postgresql':
        return
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_unlock(%s)', [ADVISORY_LOCK_KEY])
    except DatabaseError:
        # Ending the session always releases a session-level advisory lock.
        connection.close()


@contextmanager
def conversion_lock():
    """Yield whether this process may convert now; release on exit."""
    acquired = try_advisory_lock()
    try:
        yield acquired
    finally:
        if acquired:
            release_advisory_lock()


class ConversionWorker:
    """One process's conversion loop.

    ``run_once`` is one iteration and is what tests drive directly with a
    fake ``monotonic`` clock; ``run`` is the thread body that waits on the
    wake-up queue between iterations.
    """

    def __init__(
        self,
        *,
        backend=None,
        monotonic: Callable[[], float] = time.monotonic,
        queue_size: int = QUEUE_MAX_SIZE,
    ):
        self.pid = os.getpid()
        # Constructed in the forked Gunicorn worker, so the PID is this process's.
        self.identity = process_identity(self.pid)
        self._backend = backend
        self._monotonic = monotonic
        self._queue: queue.Queue = queue.Queue(maxsize=queue_size)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        # ``None`` means due now: the first iteration is the startup sweep.
        self._next_heartbeat: Optional[float] = None
        self._next_sweep: Optional[float] = None
        self._next_maintenance: Optional[float] = None

    # --- Lifecycle -----------------------------------------------------------

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self.run, name='eduvulcan-conversion', daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = STOP_TIMEOUT_SECONDS) -> None:
        """Ask the loop to stop between units of work and wait briefly.

        A conversion still running when the process exits simply leaves its
        lease to expire; the next sweep recovers the row.
        """
        self._stop.set()
        try:
            self._queue.put_nowait(_STOP)
        except queue.Full:
            pass
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)

    @property
    def stopping(self) -> bool:
        return self._stop.is_set()

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def enqueue(self, notification_id: int) -> bool:
        """Queue a wake-up without blocking; ``False`` when it was dropped."""
        if self._stop.is_set():
            return False
        try:
            self._queue.put_nowait(int(notification_id))
        except queue.Full:
            return False
        return True

    # --- Loop ----------------------------------------------------------------

    def run(self) -> None:
        logger.info('EduVulcan conversion worker started: pid=%s', self.pid)
        try:
            while not self._stop.is_set():
                woken = self._wait_for_wakeups()
                if self._stop.is_set():
                    break
                self.run_once(woken)
        finally:
            close_thread_connections()
            logger.info('EduVulcan conversion worker stopped: pid=%s', self.pid)

    def seconds_until_due(self) -> float:
        moments = (self._next_heartbeat, self._next_sweep, self._next_maintenance)
        if any(moment is None for moment in moments):
            return 0.0
        return max(0.0, min(moments) - self._monotonic())

    def _wait_for_wakeups(self) -> List[int]:
        timeout = self.seconds_until_due()
        try:
            if timeout > 0:
                first = self._queue.get(timeout=timeout)
            else:
                first = self._queue.get_nowait()
        except queue.Empty:
            return []
        items = [first]
        while len(items) < conversion.batch_size():
            try:
                items.append(self._queue.get_nowait())
            except queue.Empty:
                break
        if any(item is _STOP for item in items):
            self._stop.set()
        return [item for item in items if item is not _STOP]

    def run_once(self, woken_ids: Iterable[int] = ()) -> None:
        """Heartbeat, woken conversions, sweep, and maintenance when due.

        Never raises: any failure is logged by class name only and the
        connection is reset, so the thread survives database outages.
        """
        woken = list(dict.fromkeys(woken_ids))
        try:
            close_old_connections()
            self._heartbeat_if_due()
            sweep_due = self._due(self._next_sweep)
            maintenance_due = self._due(self._next_maintenance)
            if woken or sweep_due or maintenance_due:
                self._convert_under_lock(woken, sweep_due, maintenance_due)
            close_old_connections()
        except Exception as exc:
            logger.warning(
                'EduVulcan conversion worker error: pid=%s error=%s',
                self.pid, type(exc).__name__,
            )
            close_thread_connections()

    def _convert_under_lock(self, woken, sweep_due, maintenance_due) -> None:
        now = self._monotonic()
        if sweep_due:
            self._next_sweep = now + sweep_interval_seconds()
        if maintenance_due:
            self._next_maintenance = now + MAINTENANCE_INTERVAL_SECONDS
        with conversion_lock() as acquired:
            if not acquired:
                # Another process is converting. Its work or our retry sweep
                # picks up these rows; the database keeps them pending.
                logger.info(
                    'EduVulcan conversion lock busy: pid=%s retry_in=%ss',
                    self.pid, LOCK_RETRY_SECONDS,
                )
                if woken or sweep_due:
                    self._schedule_sweep(now + LOCK_RETRY_SECONDS)
                if maintenance_due:
                    self._next_maintenance = now + LOCK_RETRY_SECONDS
                return
            self._convert_ids(woken)
            if sweep_due and not self._stop.is_set():
                self.sweep()
            if maintenance_due and not self._stop.is_set():
                self.maintain()

    def sweep(self) -> int:
        """Convert one bounded batch of due rows; returns rows attempted."""
        limit = conversion.batch_size()
        ids = conversion.find_due_notification_ids(limit=limit)
        attempted = self._convert_ids(ids)
        if ids:
            logger.info(
                'EduVulcan conversion sweep: pid=%s due=%s attempted=%s',
                self.pid, len(ids), attempted,
            )
        if len(ids) >= limit:
            # More may be due: sweep again on the next iteration.
            self._next_sweep = self._monotonic()
        return attempted

    def maintain(self) -> int:
        """Scrub raw data of old processed rows (bounded batch).

        Also deletes heartbeat rows left by exited processes and old releases.
        """
        prune_stale_heartbeats()
        limit = conversion.batch_size()
        pruned = conversion.prune_raw_notifications(limit=limit)
        if pruned >= limit:
            self._next_maintenance = self._monotonic()
        return pruned

    def _convert_ids(self, ids: Iterable[int]) -> int:
        attempted = 0
        for notification_id in ids:
            if self._stop.is_set():
                break
            conversion.convert_notification(notification_id, backend=self._backend)
            attempted += 1
            self._heartbeat_if_due()
        return attempted

    # --- Scheduling helpers --------------------------------------------------

    def _due(self, moment: Optional[float]) -> bool:
        return moment is None or self._monotonic() >= moment

    def _schedule_sweep(self, moment: float) -> None:
        if self._next_sweep is None or moment < self._next_sweep:
            self._next_sweep = moment

    def _heartbeat_if_due(self) -> None:
        if not self._due(self._next_heartbeat):
            return
        self._next_heartbeat = self._monotonic() + heartbeat_seconds()
        record_heartbeat(identity=self.identity)


# --- Process-wide worker ------------------------------------------------------

_worker: Optional[ConversionWorker] = None
_worker_guard = threading.Lock()


def current_worker() -> Optional[ConversionWorker]:
    """This process's running worker, if any."""
    worker = _worker
    if worker is None or worker.pid != os.getpid():
        return None
    return worker


def start_worker(**kwargs) -> Optional[ConversionWorker]:
    """Start this process's worker when enabled; idempotent per process.

    Called only from Gunicorn's ``post_worker_init`` hook.
    """
    global _worker
    if not worker_enabled():
        logger.info('EduVulcan conversion worker disabled: pid=%s', os.getpid())
        return None
    with _worker_guard:
        worker = current_worker()
        if worker is not None and worker.is_alive() and not worker.stopping:
            return worker
        worker = ConversionWorker(**kwargs)
        worker.start()
        _worker = worker
        return worker


def stop_worker(timeout: float = STOP_TIMEOUT_SECONDS) -> None:
    """Stop this process's worker, if one is running."""
    global _worker
    with _worker_guard:
        worker = current_worker()
        _worker = None
    if worker is not None:
        worker.stop(timeout)


def enqueue_notification(notification_id: int) -> bool:
    """Hand a committed row ID to this process's worker; never raises."""
    try:
        worker = current_worker()
        if worker is None:
            return False
        return worker.enqueue(notification_id)
    except Exception as exc:
        logger.warning(
            'EduVulcan conversion wake-up failed: notification=%s error=%s',
            notification_id, type(exc).__name__,
        )
        return False


def schedule_wakeup(notification_id: int) -> None:
    """Enqueue ``notification_id`` after the current transaction commits.

    Only when the worker is enabled. Never raises and never does conversion
    work itself: the row is already durable, so a failed or skipped wake-up
    only delays conversion until the next sweep.
    """
    try:
        if not worker_enabled():
            return
        transaction.on_commit(lambda: enqueue_notification(notification_id), robust=True)
    except Exception as exc:
        logger.warning(
            'EduVulcan conversion wake-up failed: notification=%s error=%s',
            notification_id, type(exc).__name__,
        )
