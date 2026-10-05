"""Batch semantics of ``classify_entries_for_parent``.

A recording fake multi-entry backend captures every request; a fake without
``classify_many`` checks that single-output backends become one-item batches.
"""

import datetime

from django.core.exceptions import PermissionDenied
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from entries.classification.backends import (
    BackendOutput,
    BackendRequest,
    ClassificationBackendError,
    MultiEntryClassificationBackend,
)
from entries.classification.service import (
    MAX_PROPOSALS_PER_INSTRUCTION,
    MAX_SUBMITTED_TEXT_LENGTH,
    ParentBatchClassification,
    classify_entries_for_parent,
)
from entries.classification.types import (
    ClassificationFollowUp,
    ClassificationProposal,
    ClassificationUnavailable,
    EntryType,
    MissingField,
    SchoolItemKind,
    UnavailableReason,
)
from entries.tests.test_classification_service import (
    REFERENCE_DATE,
    WRITE_PREFIXES,
    FamilyFixtureMixin,
    RecordingBackend,
    TwoParentFixtureMixin,
    school_test_output,
)
from family_access.models import FamilyMember

MEETINGS_TEXT = 'Spotkanie z wychowawczynią dziś, jutro i w przyszłym tygodniu w poniedziałek o 18:00'
SIX_PM = datetime.time(18, 0)
MEETING_DATES = (
    REFERENCE_DATE,
    REFERENCE_DATE + datetime.timedelta(days=1),
    datetime.date(2026, 9, 21),
)


def meeting(date, **overrides):
    values = dict(
        entry_type=EntryType.CALENDAR_EVENT,
        content='Spotkanie z wychowawczynią',
        grounded=True,
        date=date,
        time=SIX_PM,
    )
    values.update(overrides)
    return BackendOutput(**values)


class RecordingMultiBackend:
    """Fake list-returning backend that records requests."""

    def __init__(self, outputs=(), error=None):
        self.outputs = tuple(outputs)
        self.error = error
        self.requests = []
        self.single_calls = 0

    def classify(self, request: BackendRequest) -> BackendOutput:
        self.single_calls += 1
        raise AssertionError('the batch service must use classify_many')

    def classify_many(self, request: BackendRequest):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.outputs


class BatchFixtureMixin(FamilyFixtureMixin):
    def classify_batch(self, membership, backend, text=MEETINGS_TEXT):
        return classify_entries_for_parent(
            membership, text, reference_date=REFERENCE_DATE, locale='pl-PL', backend=backend
        )


class BatchSemanticsTests(BatchFixtureMixin, TestCase):
    def test_fake_satisfies_the_multi_entry_protocol(self):
        self.assertIsInstance(RecordingMultiBackend(), MultiEntryClassificationBackend)
        self.assertNotIsInstance(RecordingBackend(), MultiEntryClassificationBackend)

    def test_three_outputs_give_three_proposals_with_their_dates_and_shared_time(self):
        backend = RecordingMultiBackend([meeting(date) for date in MEETING_DATES])

        batch = self.classify_batch(self.parent, backend)

        self.assertIsInstance(batch, ParentBatchClassification)
        self.assertFalse(batch.is_single)
        self.assertEqual(len(batch.items), 3)
        self.assertEqual(len(backend.requests), 1)
        for item, date in zip(batch.items, MEETING_DATES):
            self.assertEqual(
                item.result,
                ClassificationProposal(
                    entry_type=EntryType.CALENDAR_EVENT,
                    content='Spotkanie z wychowawczynią',
                    date=date,
                    time=SIX_PM,
                ),
            )
        with self.assertRaises(ValueError):
            batch.single

    def test_single_output_backend_gives_one_item_equal_to_classify_for_parent(self):
        cases = {
            'proposal': school_test_output(),
            'follow-up': school_test_output(date=None),
            'unknown member': school_test_output(member_name='Nieznany'),
            'no type': BackendOutput(entry_type=None, content='', grounded=False),
        }
        for name, output in cases.items():
            with self.subTest(name):
                single = self.classify(self.parent, RecordingBackend(output))
                batch = self.classify_batch(
                    self.parent, RecordingBackend(output), text='Michał ma sprawdzian z biologii w poniedziałek'
                )

                self.assertTrue(batch.is_single)
                self.assertEqual(batch.single, single)

    def test_one_output_from_a_multi_backend_equals_the_single_path(self):
        output = school_test_output()

        batch = self.classify_batch(self.parent, RecordingMultiBackend([output]))
        single = self.classify(self.parent, RecordingBackend(output), text=MEETINGS_TEXT)

        self.assertEqual(batch.single, single)

    def test_missing_date_gives_a_follow_up_item_inside_the_batch(self):
        backend = RecordingMultiBackend([meeting(MEETING_DATES[0]), meeting(None)])

        batch = self.classify_batch(self.parent, backend)

        self.assertIsInstance(batch.items[0].result, ClassificationProposal)
        follow_up = batch.items[1].result
        self.assertIsInstance(follow_up, ClassificationFollowUp)
        self.assertEqual(follow_up.missing_fields, (MissingField.DATE,))

    def test_unknown_member_turns_the_whole_batch_into_the_full_text_note(self):
        backend = RecordingMultiBackend(
            [meeting(MEETING_DATES[0]), meeting(MEETING_DATES[1], member_name='Nieznany')]
        )

        batch = self.classify_batch(self.parent, backend)

        self.assertTrue(batch.is_single)
        self.assertEqual(
            batch.single.result,
            ClassificationProposal(entry_type=EntryType.NOTE, content=MEETINGS_TEXT),
        )

    def test_untyped_or_ungrounded_output_turns_the_whole_batch_into_the_note(self):
        cases = {
            'no type': BackendOutput(entry_type=None, content='', grounded=False),
            'ungrounded': meeting(MEETING_DATES[1], grounded=False),
            'empty content': meeting(MEETING_DATES[1], content='  '),
        }
        for name, bad in cases.items():
            with self.subTest(name):
                batch = self.classify_batch(
                    self.parent, RecordingMultiBackend([meeting(MEETING_DATES[0]), bad])
                )

                self.assertTrue(batch.is_single)
                self.assertEqual(batch.single.result.entry_type, EntryType.NOTE)
                self.assertEqual(batch.single.result.content, MEETINGS_TEXT)

    def test_diminutive_in_a_batch_resolves_through_the_mention(self):
        hanna = self._member('hanna', FamilyMember.Role.CHILD, 'Hanna')
        backend = RecordingMultiBackend(
            [
                meeting(date, member_name='Hanka', member_mention='Hanka')
                for date in MEETING_DATES[:2]
            ]
        )

        batch = self.classify_batch(self.parent, backend, text='Dentysta z Hanką dziś i jutro')

        self.assertEqual(len(batch.items), 2)
        for item in batch.items:
            self.assertIsInstance(item.result, ClassificationProposal)
            self.assertEqual(item.result.member_name, 'Hanna')
            self.assertEqual(item.member, hanna)

    def test_school_event_without_subject_is_a_subject_follow_up_in_a_batch(self):
        backend = RecordingMultiBackend(
            [
                meeting(MEETING_DATES[0]),
                school_test_output(school_subject=None),
            ]
        )

        batch = self.classify_batch(self.parent, backend)

        follow_up = batch.items[1].result
        self.assertIsInstance(follow_up, ClassificationFollowUp)
        self.assertEqual(follow_up.missing_fields, (MissingField.SCHOOL_SUBJECT,))
        self.assertEqual(follow_up.school_item, SchoolItemKind.TEST)
        self.assertEqual(batch.items[1].member, self.child)

    def test_more_than_the_cap_gives_too_many_entries(self):
        dates = [REFERENCE_DATE + datetime.timedelta(days=day) for day in range(11)]
        at_cap = self.classify_batch(
            self.parent,
            RecordingMultiBackend([meeting(date) for date in dates[:MAX_PROPOSALS_PER_INSTRUCTION]]),
        )
        over_cap = self.classify_batch(
            self.parent, RecordingMultiBackend([meeting(date) for date in dates])
        )

        self.assertEqual(len(at_cap.items), MAX_PROPOSALS_PER_INSTRUCTION)
        self.assertEqual(
            over_cap.single.result,
            ClassificationUnavailable(reason=UnavailableReason.TOO_MANY_ENTRIES),
        )

    def test_empty_output_list_gives_the_general_note(self):
        batch = self.classify_batch(self.parent, RecordingMultiBackend([]))

        self.assertEqual(
            batch.single.result,
            ClassificationProposal(entry_type=EntryType.NOTE, content=MEETINGS_TEXT),
        )

    def test_provider_timeout_gives_an_unavailable_result(self):
        backend = RecordingMultiBackend(
            error=ClassificationBackendError(UnavailableReason.TIMEOUT)
        )

        batch = self.classify_batch(self.parent, backend)

        self.assertEqual(
            batch.single.result, ClassificationUnavailable(reason=UnavailableReason.TIMEOUT)
        )


class BatchAuthorizationAndPrivacyTests(BatchFixtureMixin, TestCase):
    def test_non_parents_are_denied_without_backend_call(self):
        cases = {
            'no family context': None,
            'child': self.child,
            'other family child': self.other_family_child,
            'inactive member': self.inactive_child,
        }
        for name, membership in cases.items():
            with self.subTest(name):
                backend = RecordingMultiBackend([meeting(MEETING_DATES[0])])

                with self.assertRaises(PermissionDenied):
                    self.classify_batch(membership, backend)

                self.assertEqual(backend.requests, [])

    def test_outsider_parent_cannot_resolve_our_members(self):
        backend = RecordingMultiBackend(
            [meeting(date, member_name='Michał') for date in MEETING_DATES[:2]]
        )

        batch = self.classify_batch(self.other_family_parent, backend)

        # Michał is not in the other family: the whole batch is a note.
        self.assertEqual(backend.requests[0].allowed_member_names, ('Tomek', 'Kuba'))
        self.assertEqual(batch.single.result.entry_type, EntryType.NOTE)

    def test_too_long_text_makes_no_backend_call(self):
        backend = RecordingMultiBackend([meeting(MEETING_DATES[0])])

        batch = self.classify_batch(
            self.parent, backend, text='x' * (MAX_SUBMITTED_TEXT_LENGTH + 1)
        )

        self.assertEqual(backend.requests, [])
        self.assertEqual(
            batch.single.result, ClassificationUnavailable(reason=UnavailableReason.INPUT_TOO_LONG)
        )

    def test_batch_service_writes_nothing(self):
        backend = RecordingMultiBackend([meeting(date) for date in MEETING_DATES])

        with CaptureQueriesContext(connection) as queries:
            self.classify_batch(self.parent, backend)

        writes = [
            query['sql'] for query in queries.captured_queries
            if query['sql'].lstrip().upper().startswith(WRITE_PREFIXES)
        ]
        self.assertEqual(writes, [])

    def test_text_stays_out_of_the_result_repr(self):
        backend = RecordingMultiBackend([meeting(date) for date in MEETING_DATES])

        batch = self.classify_batch(self.parent, backend)

        self.assertNotIn('wychowawczynią', repr(batch))


class TwoParentBatchTests(TwoParentFixtureMixin, BatchFixtureMixin, TestCase):
    """S-07: each batch proposal resolves a parent name to that parent."""

    def test_each_proposal_resolves_its_own_parent(self):
        backend = RecordingMultiBackend(
            [
                meeting(MEETING_DATES[0], member_name='Ewa'),
                meeting(MEETING_DATES[1], member_name='Paweł'),
                meeting(MEETING_DATES[2]),
            ]
        )

        batch = self.classify_batch(self.parent, backend)

        self.assertEqual(
            [item.member for item in batch.items], [self.parent, self.second_parent, None]
        )
        self.assertIn('Paweł', backend.requests[0].allowed_member_names)

    def test_foreign_parent_in_a_batch_turns_it_into_the_note(self):
        backend = RecordingMultiBackend(
            [meeting(MEETING_DATES[0], member_name='Tomek'), meeting(MEETING_DATES[1])]
        )

        batch = self.classify_batch(self.parent, backend)

        self.assertTrue(batch.is_single)
        self.assertIsNone(batch.single.member)
        self.assertEqual(batch.single.result.entry_type, EntryType.NOTE)

    def test_batch_request_names_the_requester_and_self_reference_resolves(self):
        backend = RecordingMultiBackend(
            [meeting(date, member_name='Paweł') for date in MEETING_DATES[:2]]
        )

        batch = self.classify_batch(
            self.second_parent, backend, text='Spotkanie dla mnie dziś i jutro'
        )

        self.assertEqual(backend.requests[0].requester_name, 'Paweł')
        self.assertEqual([item.member for item in batch.items], [self.second_parent] * 2)
