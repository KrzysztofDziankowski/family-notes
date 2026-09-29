"""Per-process conversion-worker heartbeats and the health state derived from them.

Each active worker thread records its own heartbeat row, keyed by a stable
process identity (hostname and PID) and stamped with the running release
(``FAMILY_NOTES_RELEASE_ID``). Health is:

- ``disabled`` when ``EDUVULCAN_WORKER_ENABLED`` is false;
- ``ok`` when at least one heartbeat of the current release is younger than
  the configured max age;
- ``unavailable`` otherwise (no worker of this release, only stale or
  other-release heartbeats, or the database cannot answer).

Heartbeats of a previous release or an exited process therefore never mask a
release whose workers did not start. Stale rows are deleted by
``prune_stale_heartbeats``. The states are fixed words, never queue contents
or family data.
"""

from __future__ import annotations

import datetime
import os
import socket
from typing import Optional

from django.conf import settings
from django.db import DatabaseError, IntegrityError, transaction
from django.utils import timezone

from ..models import ConversionWorkerHeartbeat

HEALTH_DISABLED = 'disabled'
HEALTH_OK = 'ok'
HEALTH_UNAVAILABLE = 'unavailable'

# Rows older than this many max-age windows are deleted by worker maintenance.
STALE_HEARTBEAT_MAX_AGE_MULTIPLIER = 10

_NAME_MAX_LENGTH = ConversionWorkerHeartbeat._meta.get_field('name').max_length
_RELEASE_MAX_LENGTH = ConversionWorkerHeartbeat._meta.get_field('release').max_length


def worker_enabled() -> bool:
    return bool(getattr(settings, 'EDUVULCAN_WORKER_ENABLED', False))


def heartbeat_seconds() -> int:
    return int(getattr(settings, 'EDUVULCAN_WORKER_HEARTBEAT_SECONDS', 30))


def heartbeat_max_age_seconds() -> int:
    return int(getattr(settings, 'EDUVULCAN_WORKER_HEARTBEAT_MAX_AGE_SECONDS', 180))


def current_release_id() -> str:
    """The running release, shared by the web process and its worker thread."""
    return str(getattr(settings, 'FAMILY_NOTES_RELEASE_ID', ''))[:_RELEASE_MAX_LENGTH]


def process_identity(pid: Optional[int] = None) -> str:
    """Stable identity of one worker process: ``<hostname>:<pid>``."""
    pid_text = str(pid if pid is not None else os.getpid())
    host = socket.gethostname()[: _NAME_MAX_LENGTH - len(pid_text) - 1]
    return f'{host}:{pid_text}'


def record_heartbeat(
    *, identity: Optional[str] = None, now: Optional[datetime.datetime] = None
) -> None:
    """Upsert this process's heartbeat row; safe if an identity is reused."""
    identity = identity if identity is not None else process_identity()
    now = now if now is not None else timezone.now()
    values = {'beat_at': now, 'release': current_release_id()}
    rows = ConversionWorkerHeartbeat.objects.filter(name=identity)
    if rows.update(**values):
        return
    try:
        with transaction.atomic():
            ConversionWorkerHeartbeat.objects.create(name=identity, **values)
    except IntegrityError:
        # The row appeared between our update and create; refresh it instead.
        rows.update(**values)


def prune_stale_heartbeats(*, now: Optional[datetime.datetime] = None) -> int:
    """Delete heartbeats of exited processes and old releases; returns count."""
    now = now if now is not None else timezone.now()
    cutoff = now - datetime.timedelta(
        seconds=heartbeat_max_age_seconds() * STALE_HEARTBEAT_MAX_AGE_MULTIPLIER
    )
    deleted, _ = ConversionWorkerHeartbeat.objects.filter(beat_at__lt=cutoff).delete()
    return deleted


def conversion_health(*, now: Optional[datetime.datetime] = None) -> str:
    """Current conversion health state; never raises on database failure."""
    if not worker_enabled():
        return HEALTH_DISABLED
    now = now if now is not None else timezone.now()
    cutoff = now - datetime.timedelta(seconds=heartbeat_max_age_seconds())
    try:
        fresh = ConversionWorkerHeartbeat.objects.filter(
            release=current_release_id(), beat_at__gte=cutoff
        ).exists()
    except DatabaseError:
        return HEALTH_UNAVAILABLE
    return HEALTH_OK if fresh else HEALTH_UNAVAILABLE
