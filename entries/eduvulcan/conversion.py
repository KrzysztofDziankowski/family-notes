"""Crash-safe conversion lifecycle for stored EduVulcan notifications.

The database row is the single source of truth, so a worker may die at any
point and the next sweep recovers:

1. ``find_due_notification_ids`` lists pending rows whose retry is due and
   ``processing`` rows whose lease expired.
2. ``claim_notification`` atomically moves one due row to ``processing``,
   increments ``attempt_count``, and grants a lease. The returned ``Claim``
   is the fencing token: ``(attempt_count, lease_expires_at)``.
3. ``process_claim`` derives ordered proposals (fixed rules, then
   family-scoped classification, then a general note) and saves every entry,
   its output link, and ``status=processed`` in one transaction, but only
   while the claim still owns an unexpired lease.
4. Temporary provider unavailability and transient database contention are
   retried after a delay until ``max_attempts``; exhausted provider failures
   save a general note, exhausted or permanent infrastructure failures mark
   the row ``failed`` with a safe code. ``requeue_failed_notifications`` is
   the operator's way back.
5. ``prune_raw_notifications`` scrubs raw text of old processed rows.

Logs and stored error codes carry only row IDs, attempt numbers, and safe
category codes, never notification text, classifier payloads, or names.
Nothing here starts threads; a worker calls these functions.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, List, Optional, Sequence, Tuple

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import DatabaseError, OperationalError, transaction
from django.db.models import Q
from django.utils import timezone

from family_notes.log_safety import exception_summary

from ..classification.service import FamilyOutcome, classify_for_family
from ..models import InboundNotification, NotificationConversionOutput
from ..services import create_automated_entry
from .children import snapshot_active_children
from .rules import general_note_proposal, general_note_text, propose_entries, reference_date_for
from .types import EntryProposal, OutputKind

logger = logging.getLogger(__name__)

Status = InboundNotification.Status

# Defaults; each can be overridden by the setting named next to it.
DEFAULT_LEASE_SECONDS = 120  # EDUVULCAN_CONVERSION_LEASE_SECONDS
DEFAULT_MAX_ATTEMPTS = 3  # EDUVULCAN_CONVERSION_MAX_ATTEMPTS
# Delay before attempt 2 and attempt 3; later attempts reuse the last value.
DEFAULT_RETRY_DELAYS_SECONDS = (60, 300)  # EDUVULCAN_CONVERSION_RETRY_DELAYS_SECONDS
DEFAULT_RAW_RETENTION_DAYS = 90  # EDUVULCAN_RAW_RETENTION_DAYS
DEFAULT_BATCH_SIZE = 50  # EDUVULCAN_CONVERSION_BATCH_SIZE

# Safe error codes stored in ``last_error_code``.
ERROR_DATABASE_BUSY = 'database_busy'
ERROR_DATABASE = 'database_error'
ERROR_UNEXPECTED = 'conversion_error'
ERROR_LEASE_EXPIRED = 'lease_expired'
ERROR_ATTEMPTS_EXHAUSTED = 'attempts_exhausted'
ERROR_EMPTY_NOTIFICATION = 'empty_notification'
ERROR_INVALID_OUTPUT = 'invalid_output'
PROVIDER_ERROR_PREFIX = 'provider_'


def lease_seconds() -> int:
    return int(getattr(settings, 'EDUVULCAN_CONVERSION_LEASE_SECONDS', DEFAULT_LEASE_SECONDS))


def max_attempts() -> int:
    return int(getattr(settings, 'EDUVULCAN_CONVERSION_MAX_ATTEMPTS', DEFAULT_MAX_ATTEMPTS))


def retry_delays_seconds() -> Tuple[int, ...]:
    return tuple(
        getattr(
            settings, 'EDUVULCAN_CONVERSION_RETRY_DELAYS_SECONDS', DEFAULT_RETRY_DELAYS_SECONDS
        )
    )


def raw_retention_days() -> int:
    return int(getattr(settings, 'EDUVULCAN_RAW_RETENTION_DAYS', DEFAULT_RAW_RETENTION_DAYS))


def batch_size() -> int:
    return int(getattr(settings, 'EDUVULCAN_CONVERSION_BATCH_SIZE', DEFAULT_BATCH_SIZE))


def retry_delay_after(attempt: int) -> datetime.timedelta:
    """Delay before the attempt following ``attempt`` (1-based)."""
    delays = retry_delays_seconds()
    return datetime.timedelta(seconds=delays[min(attempt, len(delays)) - 1])


class ConversionOutcome(str, Enum):
    """How one conversion call ended; safe to log."""

    PROCESSED = 'processed'
    RETRY_SCHEDULED = 'retry_scheduled'
    FAILED = 'failed'
    LEASE_LOST = 'lease_lost'
    NOT_CLAIMED = 'not_claimed'


@dataclass(frozen=True)
class Claim:
    """Ownership of one notification attempt; also its fencing token."""

    notification_id: int
    attempt: int
    lease_expires_at: datetime.datetime


@dataclass(frozen=True)
class ConversionResult:
    notification_id: int
    outcome: ConversionOutcome
    attempt: Optional[int] = None
    error_code: str = ''
    outputs: Tuple[NotificationConversionOutput, ...] = ()


class _LeaseLost(Exception):
    """The claim no longer owns the row; nothing may be committed."""


def _now(now: Optional[datetime.datetime]) -> datetime.datetime:
    return now if now is not None else timezone.now()


def _due_q(now: datetime.datetime) -> Q:
    retry_due = Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now)
    return (Q(status=Status.PENDING) & retry_due) | Q(
        status=Status.PROCESSING, lease_expires_at__lte=now
    )


# --- Selection and claiming ---------------------------------------------------


def find_due_notification_ids(
    *, now: Optional[datetime.datetime] = None, limit: Optional[int] = None
) -> List[int]:
    """IDs of pending, retry-due, and stale-processing rows, oldest first."""
    now = _now(now)
    queryset = (
        InboundNotification.objects.filter(_due_q(now))
        .order_by('pk')
        .values_list('pk', flat=True)
    )
    return list(queryset[: limit or batch_size()])


def claim_notification(
    notification_id: int, *, now: Optional[datetime.datetime] = None
) -> Optional[Claim]:
    """Atomically take ownership of one due row, or return ``None``.

    A claim increments ``attempt_count``, clears the retry schedule, and grants
    a lease. A stale ``processing`` row whose attempts are used up is marked
    ``failed`` instead (the worker died or overran its lease every time).
    The conditional update makes concurrent claims of one row mutually
    exclusive: only one sees its expected ``(status, attempt_count)``.
    """
    now = _now(now)
    with transaction.atomic():
        row = (
            InboundNotification.objects.select_for_update()
            .filter(_due_q(now), pk=notification_id)
            .only('pk', 'status', 'attempt_count')
            .first()
        )
        if row is None:
            return None
        guard = InboundNotification.objects.filter(
            _due_q(now), pk=row.pk, status=row.status, attempt_count=row.attempt_count
        )
        if row.attempt_count >= max_attempts():
            code = (
                ERROR_LEASE_EXPIRED if row.status == Status.PROCESSING else ERROR_ATTEMPTS_EXHAUSTED
            )
            if guard.update(
                status=Status.FAILED,
                lease_expires_at=None,
                next_attempt_at=None,
                last_error_code=code,
            ):
                logger.warning(
                    'EduVulcan conversion failed: notification=%s attempt=%s code=%s',
                    row.pk, row.attempt_count, code,
                )
            return None
        attempt = row.attempt_count + 1
        lease_expires_at = now + datetime.timedelta(seconds=lease_seconds())
        if not guard.update(
            status=Status.PROCESSING,
            attempt_count=attempt,
            lease_expires_at=lease_expires_at,
            next_attempt_at=None,
        ):
            return None
    return Claim(notification_id=row.pk, attempt=attempt, lease_expires_at=lease_expires_at)


def _owned(claim: Claim, now: datetime.datetime):
    """Rows still owned by ``claim``: same attempt and lease, not yet expired."""
    return InboundNotification.objects.filter(
        pk=claim.notification_id,
        status=Status.PROCESSING,
        attempt_count=claim.attempt,
        lease_expires_at=claim.lease_expires_at,
        lease_expires_at__gt=now,
    )


# --- Conversion ---------------------------------------------------------------


def convert_notification(
    notification_id: int,
    *,
    backend=None,
    now: Optional[datetime.datetime] = None,
) -> ConversionResult:
    """Claim one due notification and convert it; the worker's unit of work."""
    claim = claim_notification(notification_id, now=now)
    if claim is None:
        return ConversionResult(notification_id, ConversionOutcome.NOT_CLAIMED)
    return process_claim(claim, backend=backend, now=now)


def convert_due_notifications(
    *,
    backend=None,
    now: Optional[datetime.datetime] = None,
    limit: Optional[int] = None,
) -> List[ConversionResult]:
    """Convert one batch of due rows sequentially (one sweep's work)."""
    return [
        convert_notification(notification_id, backend=backend, now=now)
        for notification_id in find_due_notification_ids(now=now, limit=limit)
    ]


def process_claim(
    claim: Claim, *, backend=None, now: Optional[datetime.datetime] = None
) -> ConversionResult:
    """Convert a claimed row and record its outcome.

    Transient database contention is retried; other database or unexpected
    errors fail the row with a safe code. Only a failure to record the outcome
    itself propagates. Process death, or any error that escapes, simply leaves
    the lease to expire for a later claim.
    """
    try:
        return _convert(claim, backend=backend, now=now)
    except _LeaseLost:
        return _lease_lost(claim)
    except OperationalError as exc:
        return _record_failure(
            claim, ERROR_DATABASE_BUSY, retryable=True, now=now, error=exception_summary(exc)
        )
    except DatabaseError as exc:
        return _record_failure(
            claim, ERROR_DATABASE, retryable=False, now=now, error=exception_summary(exc)
        )
    except Exception as exc:
        # Never the message: it may quote notification text.
        return _record_failure(
            claim, ERROR_UNEXPECTED, retryable=False, now=now, error=exception_summary(exc)
        )


def _convert(claim: Claim, *, backend, now) -> ConversionResult:
    row = InboundNotification.objects.select_related('family').get(pk=claim.notification_id)
    text = general_note_text(row.title, row.message)
    if not text:
        return _record_failure(claim, ERROR_EMPTY_NOTIFICATION, retryable=False, now=now)
    children = snapshot_active_children(row.family)

    rule_proposals = _propose_from_rules(claim, row, children)
    if rule_proposals is not None:
        result = _try_persist(claim, row, rule_proposals, now=now)
        if result is not None:
            return result

    classification = classify_for_family(
        text,
        reference_date=reference_date_for(row.captured_at),
        children=children,
        backend=backend,
        allow_backend_retry=False,
    )
    fallback_code = ''
    if classification.retryable:
        code = PROVIDER_ERROR_PREFIX + classification.reason.value
        if claim.attempt < max_attempts():
            return _record_failure(claim, code, retryable=True, now=now)
        fallback_code = code
    elif classification.outcome == FamilyOutcome.CLASSIFIED:
        proposal = classification.proposal
        classified = EntryProposal(
            output_index=0,
            kind=OutputKind.CLASSIFICATION,
            entry_type=proposal.entry_type,
            content=proposal.content,
            date=proposal.date,
            time=proposal.time,
            school_item=proposal.school_item,
            member=classification.member,
        )
        result = _try_persist(claim, row, (classified,), now=now)
        if result is not None:
            return result

    note = general_note_proposal(row.title, row.message)
    result = _try_persist(claim, row, (note,), now=now, error_code=fallback_code)
    if result is not None:
        return result
    return _record_failure(claim, ERROR_INVALID_OUTPUT, retryable=False, now=now)


def _propose_from_rules(claim, row, children):
    """Fixed-rule proposals, or ``None`` when the rules do not apply.

    An unexpected error inside the rules is treated like an unrecognised
    notification: it is logged by class name and the row falls through to
    classification and the general note, so a rules bug never loses it.
    """
    try:
        return propose_entries(
            row.title, row.message, captured_at=row.captured_at, children=children
        )
    except Exception as exc:
        logger.warning(
            'EduVulcan conversion rules error: notification=%s attempt=%s error=%s',
            claim.notification_id, claim.attempt, exception_summary(exc),
        )
        return None


def _try_persist(claim, row, proposals, *, now, error_code=''):
    """Persist ``proposals``; ``None`` means they failed entry validation."""
    try:
        return _persist(claim, row, proposals, now=_now(now), error_code=error_code)
    except ValidationError:
        return None


def _persist(
    claim: Claim,
    row: InboundNotification,
    proposals: Sequence[EntryProposal],
    *,
    now: datetime.datetime,
    error_code: str,
) -> ConversionResult:
    """Save all entries, links, and ``processed`` together, or nothing.

    Output indexes that already exist are kept unchanged, including
    tombstones whose entry a parent deleted, so a retry never duplicates or
    recreates an output.
    """
    with transaction.atomic():
        if not list(_owned(claim, now).select_for_update().values_list('pk', flat=True)):
            raise _LeaseLost
        existing = set(
            NotificationConversionOutput.objects.filter(notification_id=row.pk).values_list(
                'output_index', flat=True
            )
        )
        for proposal in sorted(proposals, key=lambda item: item.output_index):
            if proposal.output_index in existing:
                continue
            entry = create_automated_entry(
                row.family,
                entry_type=proposal.entry_type,
                content=proposal.content,
                date=proposal.date,
                time=proposal.time,
                assigned_member_id=proposal.assigned_member_id,
                school_item=proposal.school_item,
            )
            NotificationConversionOutput.objects.create(
                notification_id=row.pk,
                output_index=proposal.output_index,
                kind=proposal.kind.value,
                entry=entry,
            )
        updates = dict(
            status=Status.PROCESSED,
            processed_at=now,
            lease_expires_at=None,
            next_attempt_at=None,
        )
        if error_code:
            updates['last_error_code'] = error_code
        if not _owned(claim, now).update(**updates):
            raise _LeaseLost
        outputs = tuple(
            NotificationConversionOutput.objects.filter(notification_id=row.pk).order_by(
                'output_index'
            )
        )
    logger.info(
        'EduVulcan conversion processed: notification=%s attempt=%s outputs=%s',
        claim.notification_id, claim.attempt, len(outputs),
    )
    return ConversionResult(
        claim.notification_id,
        ConversionOutcome.PROCESSED,
        attempt=claim.attempt,
        error_code=error_code,
        outputs=outputs,
    )


def _record_failure(
    claim: Claim,
    code: str,
    *,
    retryable: bool,
    now: Optional[datetime.datetime],
    error: str = '',
) -> ConversionResult:
    """Schedule a retry while attempts remain, otherwise fail the row.

    ``error`` is a content-free ``exception_summary`` for the log line only;
    it is never stored.
    """
    now = _now(now)
    if retryable and claim.attempt < max_attempts():
        outcome = ConversionOutcome.RETRY_SCHEDULED
        updates = dict(
            status=Status.PENDING,
            next_attempt_at=now + retry_delay_after(claim.attempt),
        )
    else:
        outcome = ConversionOutcome.FAILED
        updates = dict(status=Status.FAILED, next_attempt_at=None)
    if not _owned(claim, now).update(lease_expires_at=None, last_error_code=code, **updates):
        return _lease_lost(claim)
    log = logger.info if outcome == ConversionOutcome.RETRY_SCHEDULED else logger.warning
    message = 'EduVulcan conversion %s: notification=%s attempt=%s code=%s'
    args = [outcome.value, claim.notification_id, claim.attempt, code]
    if error:
        message += ' error=%s'
        args.append(error)
    log(message, *args)
    return ConversionResult(
        claim.notification_id, outcome, attempt=claim.attempt, error_code=code
    )


def _lease_lost(claim: Claim) -> ConversionResult:
    logger.warning(
        'EduVulcan conversion lease lost: notification=%s attempt=%s',
        claim.notification_id, claim.attempt,
    )
    return ConversionResult(
        claim.notification_id, ConversionOutcome.LEASE_LOST, attempt=claim.attempt
    )


# --- Operator requeue and maintenance -------------------------------------------


def requeue_failed_notifications(notification_ids: Iterable[int]) -> int:
    """Return ``failed`` rows to ``pending`` with a fresh attempt budget.

    Payloads, the last error code, and existing output links are untouched.
    Rows in any other status are ignored. Returns the number requeued.
    """
    requeued = InboundNotification.objects.filter(
        pk__in=list(notification_ids), status=Status.FAILED
    ).update(
        status=Status.PENDING,
        attempt_count=0,
        next_attempt_at=None,
        lease_expires_at=None,
    )
    if requeued:
        logger.info('EduVulcan notifications requeued: count=%s', requeued)
    return requeued


def prune_raw_notifications(
    *, now: Optional[datetime.datetime] = None, limit: Optional[int] = None
) -> int:
    """Scrub raw text of processed rows received over the retention period ago.

    Sets ``title=''``, ``message=''``, ``payload={}``, and ``raw_pruned_at``.
    Identifiers, content hashes, and output links stay, so intake
    deduplication and provenance keep working. Pending, processing, and
    failed rows are never pruned; already pruned rows are skipped. Returns the
    number of rows pruned in this batch.
    """
    now = _now(now)
    cutoff = now - datetime.timedelta(days=raw_retention_days())
    ids = list(
        InboundNotification.objects.filter(
            status=Status.PROCESSED, raw_pruned_at__isnull=True, received_at__lte=cutoff
        )
        .order_by('pk')
        .values_list('pk', flat=True)[: limit or batch_size()]
    )
    if not ids:
        return 0
    pruned = InboundNotification.objects.filter(
        pk__in=ids, status=Status.PROCESSED, raw_pruned_at__isnull=True
    ).update(title='', message='', payload={}, raw_pruned_at=now)
    logger.info('EduVulcan raw notification data pruned: count=%s', pruned)
    return pruned
