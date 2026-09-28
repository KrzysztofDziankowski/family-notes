"""Atomic conversion lifecycle for EduVulcan notifications (S-05 Phase 2).

Tests call the service functions directly with an explicit ``now``. SQLite
exercises the functional contract (conditional claims, lease fencing,
all-or-nothing persistence); it does not validate cross-process PostgreSQL
row locking.
"""

import datetime
import logging
from unittest import mock

from django.db import OperationalError
from django.test import TestCase, override_settings

from entries.classification.backends import BackendOutput, ClassificationBackendError
from entries.classification.service import TRANSIENT_UNAVAILABLE_REASONS
from entries.classification.types import EntryType, SchoolItemKind, UnavailableReason
from entries.eduvulcan import conversion
from entries.eduvulcan.conversion import (
    ConversionOutcome,
    claim_notification,
    convert_due_notifications,
    convert_notification,
    find_due_notification_ids,
    process_claim,
    requeue_failed_notifications,
)
from entries.eduvulcan.types import ChildSnapshot, EntryProposal, OutputKind
from entries.models import Entry, InboundNotification, NotificationConversionOutput
from entries.services import delete_family_entry

from .test_classification_service import FamilyFixtureMixin
from .test_conversion_models import make_notification

T0 = datetime.datetime(2026, 9, 23, 9, 0, tzinfo=datetime.timezone.utc)
LEASE = datetime.timedelta(minutes=2)
Status = InboundNotification.Status

TEST_TITLE = 'Sprawdzian'
TEST_MESSAGE = '2 października, Biologia (biologia), Michał'
TIMETABLE_TITLE = 'Zmiana planu dla Michał'
TIMETABLE_MESSAGE = (
    'Uwaga: zmiana organizacji dnia '
    'Zastępstwo w dniu 24 września na lekcji Technika, Zawadzki Olaf (5B) '
    'Zmieniono salę w dniu 25 września na lekcji Muzyka, Kowalczyk Irena (5B)'
)
UNKNOWN_TITLE = 'Ogłoszenie'
UNKNOWN_MESSAGE = 'Wycieczka klasowa SENTINEL-TEXT-7f3a dla Michał'


class SimulatedCrash(BaseException):
    """Process death: not an ``Exception``, so nothing records an outcome."""


class ScriptedBackend:
    """Fake backend: raises or returns the next scripted step, then repeats the last."""

    def __init__(self, *steps):
        self.steps = list(steps)
        self.calls = 0

    def classify(self, request):
        step = self.steps[min(self.calls, len(self.steps) - 1)]
        self.calls += 1
        if isinstance(step, Exception):
            raise step
        return step


def note_output(member_name=None):
    return BackendOutput(
        entry_type=EntryType.NOTE,
        content='Wycieczka klasowa',
        grounded=True,
        member_name=member_name,
    )


def unavailable(reason=UnavailableReason.TIMEOUT):
    return ClassificationBackendError(reason)


class ConversionTestCase(FamilyFixtureMixin, TestCase):
    def notification(self, index=1, title=TEST_TITLE, message=TEST_MESSAGE, **overrides):
        # A distinct hash per index keeps same-text fixtures out of intake dedup.
        overrides.setdefault('content_hash', f'{index:064d}')
        return make_notification(self.family, index, title=title, message=message, **overrides)

    def reload(self, row):
        row.refresh_from_db()
        return row


class ClaimTests(ConversionTestCase):
    def test_claim_takes_a_two_minute_lease_and_counts_the_attempt(self):
        row = self.notification()

        claim = claim_notification(row.pk, now=T0)

        self.assertEqual((claim.notification_id, claim.attempt), (row.pk, 1))
        self.assertEqual(claim.lease_expires_at, T0 + LEASE)
        row = self.reload(row)
        self.assertEqual(row.status, Status.PROCESSING)
        self.assertEqual(row.attempt_count, 1)
        self.assertEqual(row.lease_expires_at, T0 + LEASE)
        self.assertIsNone(row.next_attempt_at)

    def test_a_leased_row_cannot_be_claimed_again(self):
        row = self.notification()
        claim_notification(row.pk, now=T0)

        self.assertIsNone(claim_notification(row.pk, now=T0 + LEASE - datetime.timedelta(seconds=1)))
        self.assertEqual(self.reload(row).attempt_count, 1)

    def test_a_stale_lease_is_reclaimed_as_a_new_attempt(self):
        row = self.notification()
        first = claim_notification(row.pk, now=T0)

        second = claim_notification(row.pk, now=T0 + LEASE)

        self.assertEqual(second.attempt, 2)
        self.assertEqual(second.lease_expires_at, T0 + 2 * LEASE)
        self.assertNotEqual(first, second)

    def test_a_retry_is_claimed_only_once_due(self):
        due = T0 + datetime.timedelta(minutes=1)
        row = self.notification(attempt_count=1, next_attempt_at=due)

        self.assertIsNone(claim_notification(row.pk, now=due - datetime.timedelta(seconds=1)))
        claim = claim_notification(row.pk, now=due)

        self.assertEqual(claim.attempt, 2)
        self.assertIsNone(self.reload(row).next_attempt_at)

    def test_processed_and_failed_rows_are_never_claimed(self):
        processed = self.notification(1, status=Status.PROCESSED, processed_at=T0)
        failed = self.notification(2, status=Status.FAILED, attempt_count=3)

        for row in (processed, failed):
            with self.subTest(status=row.status):
                self.assertIsNone(claim_notification(row.pk, now=T0))
                self.assertEqual(self.reload(row).attempt_count, row.attempt_count)

    def test_stale_row_without_attempts_left_fails_with_a_safe_code(self):
        row = self.notification(status=Status.PROCESSING, attempt_count=3, lease_expires_at=T0)

        self.assertIsNone(claim_notification(row.pk, now=T0))

        row = self.reload(row)
        self.assertEqual(row.status, Status.FAILED)
        self.assertEqual(row.last_error_code, conversion.ERROR_LEASE_EXPIRED)
        self.assertIsNone(row.lease_expires_at)
        self.assertEqual(row.attempt_count, 3)

    def test_find_due_selects_pending_retry_due_and_stale_rows_only(self):
        pending = self.notification(1)
        retry_due = self.notification(2, attempt_count=1, next_attempt_at=T0)
        stale = self.notification(
            3, status=Status.PROCESSING, attempt_count=1, lease_expires_at=T0
        )
        self.notification(4, attempt_count=1, next_attempt_at=T0 + LEASE)
        self.notification(5, status=Status.PROCESSING, attempt_count=1, lease_expires_at=T0 + LEASE)
        self.notification(6, status=Status.PROCESSED, processed_at=T0)
        self.notification(7, status=Status.FAILED)

        self.assertEqual(
            find_due_notification_ids(now=T0), [pending.pk, retry_due.pk, stale.pk]
        )
        self.assertEqual(find_due_notification_ids(now=T0, limit=1), [pending.pk])


class LeaseOwnershipTests(ConversionTestCase):
    def test_a_worker_that_lost_its_lease_cannot_commit(self):
        row = self.notification()
        stale = claim_notification(row.pk, now=T0)
        later = T0 + LEASE
        current = claim_notification(row.pk, now=later)

        lost = process_claim(stale, now=later)

        self.assertEqual(lost.outcome, ConversionOutcome.LEASE_LOST)
        self.assertFalse(Entry.objects.exists())
        self.assertEqual(self.reload(row).status, Status.PROCESSING)

        done = process_claim(current, now=later)
        again = process_claim(stale, now=later)

        self.assertEqual(done.outcome, ConversionOutcome.PROCESSED)
        self.assertEqual(again.outcome, ConversionOutcome.LEASE_LOST)
        self.assertEqual(Entry.objects.count(), 1)
        self.assertEqual(NotificationConversionOutput.objects.count(), 1)

    def test_an_expired_lease_cannot_commit_even_before_reclaim(self):
        row = self.notification()
        claim = claim_notification(row.pk, now=T0)

        result = process_claim(claim, now=T0 + LEASE)

        self.assertEqual(result.outcome, ConversionOutcome.LEASE_LOST)
        self.assertFalse(Entry.objects.exists())
        row = self.reload(row)
        self.assertEqual(row.status, Status.PROCESSING)
        self.assertEqual(find_due_notification_ids(now=T0 + LEASE), [row.pk])

    def test_a_worker_that_lost_its_lease_cannot_record_a_retry(self):
        row = self.notification(title=UNKNOWN_TITLE, message=UNKNOWN_MESSAGE)
        stale = claim_notification(row.pk, now=T0)
        current = claim_notification(row.pk, now=T0 + LEASE)

        result = process_claim(stale, backend=ScriptedBackend(unavailable()), now=T0 + LEASE)

        self.assertEqual(result.outcome, ConversionOutcome.LEASE_LOST)
        row = self.reload(row)
        self.assertEqual((row.status, row.attempt_count), (Status.PROCESSING, current.attempt))
        self.assertEqual(row.last_error_code, '')


class AtomicPersistenceTests(ConversionTestCase):
    def test_rule_conversion_saves_an_automated_family_entry(self):
        row = self.notification()
        backend = ScriptedBackend(AssertionError('rules must not call the provider'))

        result = convert_notification(row.pk, backend=backend, now=T0)

        self.assertEqual(result.outcome, ConversionOutcome.PROCESSED)
        self.assertEqual(backend.calls, 0)
        entry = Entry.objects.get()
        self.assertEqual(entry.family, self.family)
        self.assertEqual(entry.source, Entry.Source.EDUVULCAN)
        self.assertIsNone(entry.created_by)
        self.assertIsNone(entry.submission_key)
        self.assertEqual(entry.assigned_member, self.child)
        self.assertEqual(entry.entry_type, EntryType.CALENDAR_EVENT.value)
        self.assertEqual(entry.school_item, SchoolItemKind.TEST.value)
        self.assertEqual(entry.date, datetime.date(2026, 10, 2))
        self.assertEqual(entry.content, 'Sprawdzian: Biologia')
        output = entry.conversion_output
        self.assertEqual((output.output_index, output.kind), (0, OutputKind.RULE.value))
        self.assertEqual(result.outputs, (output,))
        row = self.reload(row)
        self.assertEqual(row.status, Status.PROCESSED)
        self.assertEqual(row.processed_at, T0)
        self.assertIsNone(row.lease_expires_at)
        self.assertIsNone(row.next_attempt_at)

    def test_fan_out_saves_ordered_outputs_with_the_remainder_last(self):
        row = self.notification(title=TIMETABLE_TITLE, message=TIMETABLE_MESSAGE)

        result = convert_notification(row.pk, now=T0)

        outputs = list(row.conversion_outputs.select_related('entry'))
        self.assertEqual(result.outputs, tuple(outputs))
        self.assertEqual([output.output_index for output in outputs], [0, 1, 2])
        self.assertEqual(
            [output.kind for output in outputs],
            [OutputKind.RULE.value, OutputKind.RULE.value, OutputKind.RULE_REMAINDER.value],
        )
        self.assertEqual(
            [output.entry.assigned_member for output in outputs],
            [self.child, self.child, None],
        )
        self.assertEqual(Entry.objects.count(), 3)

    def test_repeated_conversion_calls_create_one_entry_per_output_index(self):
        row = self.notification(title=TIMETABLE_TITLE, message=TIMETABLE_MESSAGE)

        first = convert_notification(row.pk, now=T0)
        second = convert_notification(row.pk, now=T0)
        swept = convert_due_notifications(now=T0 + LEASE)

        self.assertEqual(first.outcome, ConversionOutcome.PROCESSED)
        self.assertEqual(second.outcome, ConversionOutcome.NOT_CLAIMED)
        self.assertEqual(swept, [])
        self.assertEqual(Entry.objects.count(), 3)

    def test_rerunning_a_converted_row_returns_existing_outputs_unchanged(self):
        row = self.notification(title=TIMETABLE_TITLE, message=TIMETABLE_MESSAGE)
        first = convert_notification(row.pk, now=T0)
        before = [(output.pk, output.entry_id) for output in first.outputs]
        # Force the row back into the due set, as if its completion were lost.
        InboundNotification.objects.filter(pk=row.pk).update(status=Status.PENDING)

        again = convert_notification(row.pk, now=T0 + LEASE)

        self.assertEqual(again.outcome, ConversionOutcome.PROCESSED)
        self.assertEqual([(output.pk, output.entry_id) for output in again.outputs], before)
        self.assertEqual(Entry.objects.count(), 3)

    def test_a_deleted_entry_keeps_its_tombstone_and_is_not_recreated(self):
        row = self.notification()
        result = convert_notification(row.pk, now=T0)
        entry = result.outputs[0].entry
        delete_family_entry(self.parent.user, entry.pk)
        InboundNotification.objects.filter(pk=row.pk).update(status=Status.PENDING)

        again = convert_notification(row.pk, now=T0 + LEASE)

        self.assertEqual(again.outcome, ConversionOutcome.PROCESSED)
        self.assertFalse(Entry.objects.exists())
        tombstone = NotificationConversionOutput.objects.get()
        self.assertIsNone(tombstone.entry)
        self.assertEqual((tombstone.output_index, tombstone.kind), (0, OutputKind.RULE.value))

    def test_a_crash_before_commit_leaves_nothing_and_the_next_claim_converts(self):
        row = self.notification(title=TIMETABLE_TITLE, message=TIMETABLE_MESSAGE)
        real_create = conversion.create_automated_entry
        calls = []

        def crash_on_second(*args, **kwargs):
            calls.append(1)
            if len(calls) == 2:
                raise SimulatedCrash
            return real_create(*args, **kwargs)

        with mock.patch.object(conversion, 'create_automated_entry', crash_on_second):
            with self.assertRaises(SimulatedCrash):
                convert_notification(row.pk, now=T0)

        self.assertFalse(Entry.objects.exists())
        self.assertFalse(NotificationConversionOutput.objects.exists())
        row = self.reload(row)
        self.assertEqual((row.status, row.attempt_count), (Status.PROCESSING, 1))
        self.assertIsNone(row.processed_at)

        self.assertEqual(convert_due_notifications(now=T0 + LEASE - datetime.timedelta(seconds=1)), [])
        result = convert_notification(row.pk, now=T0 + LEASE)

        self.assertEqual((result.outcome, result.attempt), (ConversionOutcome.PROCESSED, 2))
        self.assertEqual(Entry.objects.count(), 3)
        self.assertEqual(NotificationConversionOutput.objects.count(), 3)

    def test_an_unexpected_error_fails_the_row_without_partial_output(self):
        row = self.notification(title=TIMETABLE_TITLE, message=TIMETABLE_MESSAGE)
        real_create = conversion.create_automated_entry
        calls = []

        def fail_on_second(*args, **kwargs):
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError(f'boom {TIMETABLE_MESSAGE}')
            return real_create(*args, **kwargs)

        with mock.patch.object(conversion, 'create_automated_entry', fail_on_second), \
                self.assertLogs('entries.eduvulcan.conversion', logging.INFO) as logs:
            result = convert_notification(row.pk, now=T0)

        self.assertEqual(result.outcome, ConversionOutcome.FAILED)
        self.assertFalse(Entry.objects.exists())
        self.assertFalse(NotificationConversionOutput.objects.exists())
        row = self.reload(row)
        self.assertEqual(row.status, Status.FAILED)
        self.assertEqual(row.last_error_code, conversion.ERROR_UNEXPECTED)
        self.assertIsNone(row.lease_expires_at)
        self.assertNotIn('Zawadzki', '\n'.join(logs.output))

    def test_an_invalid_rule_proposal_falls_back_to_classification(self):
        row = self.notification()
        foreign = EntryProposal(
            output_index=0,
            kind=OutputKind.RULE,
            entry_type=EntryType.NOTE,
            content='Ocena: 5, Plastyka',
            member=ChildSnapshot(pk=self.other_family_child.pk, display_name='Kuba'),
        )
        backend = ScriptedBackend(note_output(member_name='Michał'))

        with mock.patch.object(conversion, 'propose_entries', return_value=(foreign,)):
            result = convert_notification(row.pk, backend=backend, now=T0)

        self.assertEqual(result.outcome, ConversionOutcome.PROCESSED)
        self.assertEqual(backend.calls, 1)
        entry = Entry.objects.get()
        self.assertEqual(entry.assigned_member, self.child)
        self.assertEqual(entry.conversion_output.kind, OutputKind.CLASSIFICATION.value)
        self.assertFalse(Entry.objects.filter(assigned_member=self.other_family_child).exists())


class ClassificationFallbackTests(ConversionTestCase):
    def setUp(self):
        super().setUp()
        self.row = self.notification(title=UNKNOWN_TITLE, message=UNKNOWN_MESSAGE)

    def test_unknown_format_is_classified_for_the_family(self):
        backend = ScriptedBackend(note_output(member_name='Michał'))

        result = convert_notification(self.row.pk, backend=backend, now=T0)

        self.assertEqual((result.outcome, result.attempt), (ConversionOutcome.PROCESSED, 1))
        entry = Entry.objects.get()
        self.assertEqual(entry.assigned_member, self.child)
        self.assertEqual(entry.content, 'Wycieczka klasowa')
        self.assertEqual(entry.source, Entry.Source.EDUVULCAN)
        self.assertEqual(entry.conversion_output.kind, OutputKind.CLASSIFICATION.value)

    def test_automated_classification_disables_the_backend_retry(self):
        with mock.patch.object(
            conversion, 'classify_for_family', wraps=conversion.classify_for_family
        ) as spy:
            convert_notification(self.row.pk, backend=ScriptedBackend(note_output()), now=T0)

        self.assertIs(spy.call_args.kwargs['allow_backend_retry'], False)

    def test_deterministic_failures_save_a_general_note_without_retry(self):
        for index, reason in enumerate(
            (
                UnavailableReason.DISABLED,
                UnavailableReason.REFUSED,
                UnavailableReason.MALFORMED_OUTPUT,
            ),
            start=2,
        ):
            with self.subTest(reason=reason):
                row = self.notification(index, title=UNKNOWN_TITLE, message=f'{UNKNOWN_MESSAGE} {index}')
                backend = ScriptedBackend(unavailable(reason))

                result = convert_notification(row.pk, backend=backend, now=T0)

                self.assertEqual((result.outcome, result.attempt), (ConversionOutcome.PROCESSED, 1))
                self.assertEqual(backend.calls, 1)
                output = result.outputs[0]
                self.assertEqual(output.kind, OutputKind.GENERAL_NOTE.value)
                self.assertIsNone(output.entry.assigned_member)
                self.assertEqual(output.entry.content, f'{UNKNOWN_TITLE}: {UNKNOWN_MESSAGE} {index}')

    def test_disabled_classification_without_a_backend_saves_a_general_note(self):
        with override_settings(CLASSIFICATION_ENABLED=False):
            result = convert_notification(self.row.pk, now=T0)

        self.assertEqual(result.outcome, ConversionOutcome.PROCESSED)
        self.assertEqual(result.outputs[0].kind, OutputKind.GENERAL_NOTE.value)


class RetryPolicyTests(ConversionTestCase):
    def setUp(self):
        super().setUp()
        self.row = self.notification(title=UNKNOWN_TITLE, message=UNKNOWN_MESSAGE)

    def test_each_transient_provider_failure_schedules_a_retry(self):
        for index, reason in enumerate(sorted(TRANSIENT_UNAVAILABLE_REASONS), start=2):
            with self.subTest(reason=reason):
                row = self.notification(index, title=UNKNOWN_TITLE, message=f'{UNKNOWN_MESSAGE} {index}')

                result = convert_notification(
                    row.pk, backend=ScriptedBackend(unavailable(reason)), now=T0
                )

                self.assertEqual(result.outcome, ConversionOutcome.RETRY_SCHEDULED)
                row = self.reload(row)
                self.assertEqual(row.status, Status.PENDING)
                self.assertEqual(row.last_error_code, f'provider_{reason.value}')

    def test_provider_outage_makes_three_calls_then_saves_a_general_note(self):
        backend = ScriptedBackend(unavailable())
        first_retry = T0 + datetime.timedelta(minutes=1)
        second_retry = first_retry + datetime.timedelta(minutes=5)

        first = convert_notification(self.row.pk, backend=backend, now=T0)
        row = self.reload(self.row)
        self.assertEqual(first.outcome, ConversionOutcome.RETRY_SCHEDULED)
        self.assertEqual((row.status, row.attempt_count), (Status.PENDING, 1))
        self.assertEqual(row.next_attempt_at, first_retry)
        self.assertIsNone(row.lease_expires_at)
        self.assertEqual(row.last_error_code, 'provider_timeout')

        early = first_retry - datetime.timedelta(seconds=1)
        self.assertEqual(convert_notification(self.row.pk, backend=backend, now=early).outcome,
                         ConversionOutcome.NOT_CLAIMED)

        second = convert_notification(self.row.pk, backend=backend, now=first_retry)
        self.assertEqual((second.outcome, second.attempt), (ConversionOutcome.RETRY_SCHEDULED, 2))
        self.assertEqual(self.reload(self.row).next_attempt_at, second_retry)

        third = convert_notification(self.row.pk, backend=backend, now=second_retry)
        self.assertEqual((third.outcome, third.attempt), (ConversionOutcome.PROCESSED, 3))
        self.assertEqual(third.error_code, 'provider_timeout')
        self.assertEqual(third.outputs[0].kind, OutputKind.GENERAL_NOTE.value)
        self.assertIsNone(third.outputs[0].entry.assigned_member)

        later = second_retry + datetime.timedelta(hours=1)
        self.assertEqual(convert_due_notifications(backend=backend, now=later), [])
        self.assertEqual(backend.calls, 3)
        row = self.reload(self.row)
        self.assertEqual((row.status, row.attempt_count), (Status.PROCESSED, 3))
        self.assertEqual(row.last_error_code, 'provider_timeout')
        self.assertEqual(Entry.objects.count(), 1)

    def test_a_retry_recovers_once_the_provider_answers(self):
        backend = ScriptedBackend(unavailable(), note_output(member_name='Michał'))

        convert_notification(self.row.pk, backend=backend, now=T0)
        result = convert_notification(
            self.row.pk, backend=backend, now=T0 + datetime.timedelta(minutes=1)
        )

        self.assertEqual((result.outcome, result.attempt), (ConversionOutcome.PROCESSED, 2))
        self.assertEqual(backend.calls, 2)
        self.assertEqual(result.outputs[0].kind, OutputKind.CLASSIFICATION.value)

    def test_database_contention_is_retried_then_fails_when_exhausted(self):
        row = self.notification(2)
        busy = mock.patch.object(
            conversion, 'create_automated_entry', side_effect=OperationalError('database is locked')
        )
        times = (T0, T0 + datetime.timedelta(minutes=1), T0 + datetime.timedelta(minutes=6))

        with busy:
            outcomes = [convert_notification(row.pk, now=now).outcome for now in times]

        self.assertEqual(
            outcomes,
            [ConversionOutcome.RETRY_SCHEDULED, ConversionOutcome.RETRY_SCHEDULED,
             ConversionOutcome.FAILED],
        )
        row = self.reload(row)
        self.assertEqual((row.status, row.attempt_count), (Status.FAILED, 3))
        self.assertEqual(row.last_error_code, conversion.ERROR_DATABASE_BUSY)
        self.assertIsNone(row.next_attempt_at)
        self.assertFalse(Entry.objects.exists())

    def test_database_contention_recovers_on_the_next_attempt(self):
        row = self.notification(2)
        with mock.patch.object(
            conversion, 'create_automated_entry', side_effect=OperationalError('locked')
        ):
            convert_notification(row.pk, now=T0)

        result = convert_notification(row.pk, now=T0 + datetime.timedelta(minutes=1))

        self.assertEqual((result.outcome, result.attempt), (ConversionOutcome.PROCESSED, 2))
        self.assertEqual(Entry.objects.count(), 1)

    def test_persisted_codes_and_logs_contain_no_notification_text(self):
        backend = ScriptedBackend(unavailable())
        with self.assertLogs('entries.eduvulcan.conversion', logging.INFO) as logs:
            convert_notification(self.row.pk, backend=backend, now=T0)

        row = self.reload(self.row)
        diagnostics = '\n'.join(logs.output) + row.last_error_code + row.error
        for sensitive in ('SENTINEL-TEXT-7f3a', 'Wycieczka', 'Michał', UNKNOWN_TITLE, 'Our Family'):
            self.assertNotIn(sensitive, diagnostics)
        self.assertIn(f'notification={row.pk}', diagnostics)

    @override_settings(
        EDUVULCAN_CONVERSION_MAX_ATTEMPTS=2,
        EDUVULCAN_CONVERSION_RETRY_DELAYS_SECONDS=(30,),
        EDUVULCAN_CONVERSION_LEASE_SECONDS=10,
    )
    def test_policy_values_can_be_overridden_by_settings(self):
        backend = ScriptedBackend(unavailable())

        convert_notification(self.row.pk, backend=backend, now=T0)
        row = self.reload(self.row)
        self.assertEqual(row.next_attempt_at, T0 + datetime.timedelta(seconds=30))

        claim = claim_notification(self.row.pk, now=row.next_attempt_at)
        self.assertEqual(claim.lease_expires_at, row.next_attempt_at + datetime.timedelta(seconds=10))
        result = process_claim(claim, backend=backend, now=row.next_attempt_at)

        self.assertEqual((result.outcome, result.attempt), (ConversionOutcome.PROCESSED, 2))
        self.assertEqual(backend.calls, 2)


class RequeueServiceTests(ConversionTestCase):
    def test_requeue_resets_only_failed_rows_for_a_fresh_attempt_budget(self):
        failed = self.notification(
            1, status=Status.FAILED, attempt_count=3, last_error_code='database_busy'
        )
        pending = self.notification(2, attempt_count=1, next_attempt_at=T0)
        payload = dict(failed.payload)

        requeued = requeue_failed_notifications([failed.pk, pending.pk])

        self.assertEqual(requeued, 1)
        failed = self.reload(failed)
        self.assertEqual((failed.status, failed.attempt_count), (Status.PENDING, 0))
        self.assertEqual(failed.payload, payload)
        self.assertEqual(failed.title, TEST_TITLE)
        self.assertEqual(failed.last_error_code, 'database_busy')
        pending = self.reload(pending)
        self.assertEqual((pending.attempt_count, pending.next_attempt_at), (1, T0))

        result = convert_notification(failed.pk, now=T0)
        self.assertEqual((result.outcome, result.attempt), (ConversionOutcome.PROCESSED, 1))

    def test_requeue_keeps_existing_output_history(self):
        row = self.notification()
        convert_notification(row.pk, now=T0)
        output = NotificationConversionOutput.objects.get()
        InboundNotification.objects.filter(pk=row.pk).update(status=Status.FAILED)

        self.assertEqual(requeue_failed_notifications([row.pk]), 1)
        result = convert_notification(row.pk, now=T0 + LEASE)

        self.assertEqual(result.outputs, (output,))
        self.assertEqual(Entry.objects.count(), 1)
