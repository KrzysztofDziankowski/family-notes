"""Shared conversion-worker heartbeat and the health state derived from it.

Every active worker thread records one shared heartbeat row. Health is:

- ``disabled`` when ``EDUVULCAN_WORKER_ENABLED`` is false;
- ``ok`` when the newest heartbeat is younger than the configured max age;
- ``unavailable`` when it is missing, stale, or the database cannot answer.

The states are fixed words, never queue contents or family data.
"""

from __future__ import annotations

import datetime
from typing import Optional

from django.conf import settings
from django.db import DatabaseError, IntegrityError, transaction
from django.utils import timezone

from ..models import ConversionWorkerHeartbeat

HEARTBEAT_NAME = 'eduvulcan-conversion'

HEALTH_DISABLED = 'disabled'
HEALTH_OK = 'ok'
HEALTH_UNAVAILABLE = 'unavailable'


def worker_enabled() -> bool:
    return bool(getattr(settings, 'EDUVULCAN_WORKER_ENABLED', False))


def heartbeat_seconds() -> int:
    return int(getattr(settings, 'EDUVULCAN_WORKER_HEARTBEAT_SECONDS', 30))


def heartbeat_max_age_seconds() -> int:
    return int(getattr(settings, 'EDUVULCAN_WORKER_HEARTBEAT_MAX_AGE_SECONDS', 180))


def record_heartbeat(*, now: Optional[datetime.datetime] = None) -> None:
    """Upsert the shared heartbeat row; safe when two processes race."""
    now = now if now is not None else timezone.now()
    rows = ConversionWorkerHeartbeat.objects.filter(name=HEARTBEAT_NAME)
    if rows.update(beat_at=now):
        return
    try:
        with transaction.atomic():
            ConversionWorkerHeartbeat.objects.create(name=HEARTBEAT_NAME, beat_at=now)
    except IntegrityError:
        # Another process created it first; refresh its timestamp instead.
        rows.update(beat_at=now)


def conversion_health(*, now: Optional[datetime.datetime] = None) -> str:
    """Current conversion health state; never raises on database failure."""
    if not worker_enabled():
        return HEALTH_DISABLED
    now = now if now is not None else timezone.now()
    cutoff = now - datetime.timedelta(seconds=heartbeat_max_age_seconds())
    try:
        fresh = ConversionWorkerHeartbeat.objects.filter(
            name=HEARTBEAT_NAME, beat_at__gte=cutoff
        ).exists()
    except DatabaseError:
        return HEALTH_UNAVAILABLE
    return HEALTH_OK if fresh else HEALTH_UNAVAILABLE
