"""Tests for the follow-up question copy and ``classify_follow_up_answer``.

A recording fake backend scripts the answer's classification so the merge
rules, authorization, and privacy guarantees are pinned without a provider.
"""

import datetime
import logging

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext

from entries.classification.backends import BackendOutput, ClassificationBackendError
from entries.classification.follow_up import follow_up_question
from entries.classification.service import (
    MAX_FOLLOW_UP_ANSWER_LENGTH,
    MAX_SUBMITTED_TEXT_LENGTH,
    classify_follow_up_answer,
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
)
from family_access.models import FamilyMember

SUBMITTED_TEXT = 'Michał ma kartkówkę z matematyki'
CONTENT = 'Kartkówka z matematyki'
FRIDAY = datetime.date(2026, 9, 18)
ANSWER = 'w piątek'
ANSWER_SENTINEL = 'SENTINEL-ANSWER-f31a07'


def make_draft(missing=(MissingField.DATE,), member_name='Michał', **overrides):
    values = dict(
        missing_fields=tuple(missing),
        entry_type=EntryType.CALENDAR_EVENT,
        content=CONTENT,
        school_item=SchoolItemKind.QUIZ,
        member_name=member_name,
    )
    values.update(overrides)
    return ClassificationFollowUp(**values)


def answer_output(**overrides):
    """What the provider returns for the instruction plus the answer."""
    values = dict(
        entry_type=EntryType.CALENDAR_EVENT,
        content=CONTENT,
        grounded=True,
        date=FRIDAY,
        school_item=SchoolItemKind.QUIZ,
        member_name=None,
    )
    values.update(overrides)
    return BackendOutput(**values)


class FollowUpQuestionTests(SimpleTestCase):
    def question(self, *missing, content=CONTENT):
        return follow_up_question(make_draft(missing, content=content))

    def test_single_missing_fields(self):
        self.assertEqual(
            self.question(MissingField.DATE), 'Kiedy odbędzie się „Kartkówka z matematyki”?'
        )
        self.assertEqual(
            self.question(MissingField.AFFECTED_MEMBER),
            'Kogo dotyczy „Kartkówka z matematyki”?',
        )
        self.assertEqual(
            self.question(MissingField.AMBIGUOUS_MEMBER),
            'Której osoby dotyczy „Kartkówka z matematyki”?',
        )

    def test_several_missing_fields_join_into_one_question(self):
        self.assertEqual(
            self.question(MissingField.DATE, MissingField.AFFECTED_MEMBER),
            'Kiedy odbędzie się „Kartkówka z matematyki” i kogo dotyczy?',
        )
        self.assertEqual(
            self.question(MissingField.DATE, MissingField.AMBIGUOUS_MEMBER),
            'Kiedy odbędzie się „Kartkówka z matematyki” i której osoby dotyczy?',
        )

    def test_order_is_deterministic(self):
        self.assertEqual(
            self.question(MissingField.AFFECTED_MEMBER, MissingField.DATE),
            self.question(MissingField.DATE, MissingField.AFFECTED_MEMBER),
        )

    def test_question_never_contains_the_member_name(self):
        question = follow_up_question(
            make_draft((MissingField.DATE,), member_name='Michał')
        )

        self.assertNotIn('Michał', question)

    def test_blank_content_uses_a_generic_subject(self):
        self.assertEqual(self.question(MissingField.DATE, content='  '), 'Na kiedy planowany jest ten wpis?')
        self.assertEqual(
            self.question(MissingField.DATE, MissingField.AFFECTED_MEMBER, content=''),
            'Na kiedy planowany jest ten wpis i kogo dotyczy?',
        )
        self.assertEqual(self.question(MissingField.AFFECTED_MEMBER, content=''), 'Kogo dotyczy ten wpis?')

    def test_no_missing_fields_is_rejected(self):
        with self.assertRaises(ValueError):
            self.question()


class FollowUpAnswerTestMixin(FamilyFixtureMixin):
    def answer(self, backend, draft=None, answer=ANSWER, user=None, member='default', text=SUBMITTED_TEXT):
        return classify_follow_up_answer(
            user if user is not None else self.parent.user,
            text,
            draft if draft is not None else make_draft(),
            answer,
            reference_date=REFERENCE_DATE,
            draft_member=self.child if member == 'default' else member,
            backend=backend,
        )


class MergeTests(FollowUpAnswerTestMixin, TestCase):
    def test_missing_date_is_filled_and_draft_values_kept(self):
        backend = RecordingBackend(answer_output())

        outcome = self.answer(backend)

        self.assertEqual(
            outcome.result,
            ClassificationProposal(
                entry_type=EntryType.CALENDAR_EVENT,
                content=CONTENT,
                date=FRIDAY,
                school_item=SchoolItemKind.QUIZ,
                member_name='Michał',
            ),
        )
        self.assertEqual(outcome.member, self.child)
        self.assertEqual(len(backend.requests), 1)

    def test_different_type_title_and_time_in_answer_result_are_ignored(self):
        backend = RecordingBackend(
            answer_output(
                entry_type=EntryType.NOTE,
                content='Zupełnie inny tytuł',
                school_item=SchoolItemKind.GRADE,
                time=datetime.time(9, 0),
            )
        )

        outcome = self.answer(backend, draft=make_draft(time=datetime.time(8, 0)))

        self.assertIsInstance(outcome.result, ClassificationProposal)
        self.assertEqual(outcome.result.entry_type, EntryType.CALENDAR_EVENT)
        self.assertEqual(outcome.result.content, CONTENT)
        self.assertEqual(outcome.result.school_item, SchoolItemKind.QUIZ)
        self.assertEqual(outcome.result.time, datetime.time(8, 0))
        self.assertEqual(outcome.result.date, FRIDAY)

    def test_none_entry_type_in_answer_result_contributes_nothing(self):
        backend = RecordingBackend(answer_output(entry_type=None, content=''))

        outcome = self.answer(backend)

        self.assertIsInstance(outcome.result, ClassificationProposal)
        self.assertEqual(outcome.result.entry_type, EntryType.CALENDAR_EVENT)
        self.assertEqual(outcome.result.date, FRIDAY)

    def test_echoed_member_with_different_spelling_does_not_veto_date(self):
        for echoed in ('michał', 'Michal', 'Bartek'):
            with self.subTest(echoed):
                backend = RecordingBackend(answer_output(member_name=echoed))

                outcome = self.answer(backend)

                self.assertIsInstance(outcome.result, ClassificationProposal)
                self.assertEqual(outcome.result.date, FRIDAY)
                self.assertEqual(outcome.member, self.child)

    def test_date_answered_member_still_missing(self):
        draft = make_draft(
            (MissingField.DATE, MissingField.AFFECTED_MEMBER), member_name=None
        )

        outcome = self.answer(RecordingBackend(answer_output()), draft=draft, member=None)

        self.assertIsInstance(outcome.result, ClassificationFollowUp)
        self.assertEqual(outcome.result.missing_fields, (MissingField.AFFECTED_MEMBER,))
        self.assertEqual(outcome.result.date, FRIDAY)
        self.assertIsNone(outcome.member)

    def test_missing_member_is_filled_from_answer(self):
        draft = make_draft(
            (MissingField.AFFECTED_MEMBER,), member_name=None, date=FRIDAY
        )
        backend = RecordingBackend(answer_output(date=None, member_name='Ania'))

        outcome = self.answer(backend, draft=draft, member=None)

        self.assertIsInstance(outcome.result, ClassificationProposal)
        self.assertEqual(outcome.result.date, FRIDAY)
        self.assertEqual(outcome.member, self.other_child)

    def test_unknown_name_is_unavailable(self):
        draft = make_draft(
            (MissingField.AFFECTED_MEMBER,), member_name=None, date=FRIDAY
        )
        for name in ('Bartek', 'Kuba', 'Zosia'):
            with self.subTest(name):
                backend = RecordingBackend(answer_output(member_name=name))

                outcome = self.answer(backend, draft=draft, member=None)

                self.assertEqual(
                    outcome.result,
                    ClassificationUnavailable(reason=UnavailableReason.UNKNOWN_MEMBER),
                )
                self.assertIsNone(outcome.member)

    def test_ambiguous_name_stays_missing(self):
        self._member('second-michal', FamilyMember.Role.CHILD, 'Michał')
        draft = make_draft(
            (MissingField.AMBIGUOUS_MEMBER,), member_name=None, date=FRIDAY
        )
        backend = RecordingBackend(answer_output(member_name='Michał'))

        outcome = self.answer(backend, draft=draft, member=None)

        self.assertIsInstance(outcome.result, ClassificationFollowUp)
        self.assertIn(MissingField.AMBIGUOUS_MEMBER, outcome.result.missing_fields)
        self.assertIsNone(outcome.member)

    def test_unanswered_date_stays_missing(self):
        outcome = self.answer(RecordingBackend(answer_output(date=None)))

        self.assertIsInstance(outcome.result, ClassificationFollowUp)
        self.assertEqual(outcome.result.missing_fields, (MissingField.DATE,))
        self.assertEqual(outcome.member, self.child)

    def test_ungrounded_answer_result_is_unavailable(self):
        outcome = self.answer(RecordingBackend(answer_output(grounded=False)))

        self.assertEqual(
            outcome.result,
            ClassificationUnavailable(reason=UnavailableReason.UNSUPPORTED_CONTENT),
        )

    def test_draft_member_outside_family_is_dropped(self):
        for member in (self.other_family_child, self.inactive_child):
            with self.subTest(member.display_name):
                outcome = self.answer(
                    RecordingBackend(answer_output()),
                    draft=make_draft(member_name=member.display_name),
                    member=member,
                )

                self.assertIsInstance(outcome.result, ClassificationFollowUp)
                self.assertEqual(
                    outcome.result.missing_fields, (MissingField.AFFECTED_MEMBER,)
                )
                self.assertIsNone(outcome.member)

    def test_draft_member_uses_current_display_name(self):
        outcome = self.answer(
            RecordingBackend(answer_output()), draft=make_draft(member_name='Stare imię')
        )

        self.assertIsInstance(outcome.result, ClassificationProposal)
        self.assertEqual(outcome.result.member_name, 'Michał')
        self.assertEqual(outcome.member, self.child)

    def test_provider_timeout_is_unavailable(self):
        backend = RecordingBackend(
            error=ClassificationBackendError(UnavailableReason.TIMEOUT)
        )

        outcome = self.answer(backend)

        self.assertEqual(
            outcome.result, ClassificationUnavailable(reason=UnavailableReason.TIMEOUT)
        )
        self.assertIsNone(outcome.member)


class RequestAndAuthorizationTests(FollowUpAnswerTestMixin, TestCase):
    def test_backend_request_carries_question_and_answer(self):
        backend = RecordingBackend(answer_output())

        self.answer(backend)

        (request,) = backend.requests
        self.assertEqual(request.submitted_text, SUBMITTED_TEXT)
        self.assertEqual(request.follow_up_question, 'Kiedy odbędzie się „Kartkówka z matematyki”?')
        self.assertEqual(request.follow_up_answer, ANSWER)
        self.assertEqual(request.allowed_member_names, ('Ewa', 'Michał', 'Ania'))
        self.assertEqual(request.reference_date, REFERENCE_DATE)
        self.assertEqual(request.locale, 'pl-PL')

    def test_unauthorized_users_are_denied_without_backend_call(self):
        outsider = get_user_model().objects.create_user(username='outsider')
        cases = {
            'anonymous': AnonymousUser(),
            'outsider without membership': outsider,
            'child': self.child.user,
            'inactive member': self.inactive_child.user,
        }
        for name, user in cases.items():
            with self.subTest(name):
                backend = RecordingBackend(answer_output())

                with self.assertRaises(PermissionDenied):
                    self.answer(backend, user=user)

                self.assertEqual(backend.requests, [])

    def test_other_family_parent_never_sees_or_keeps_our_member(self):
        backend = RecordingBackend(answer_output())

        outcome = self.answer(backend, user=self.other_family_parent.user)

        (request,) = backend.requests
        self.assertEqual(request.allowed_member_names, ('Tomek', 'Kuba'))
        self.assertIsNone(outcome.member)
        self.assertIsInstance(outcome.result, ClassificationFollowUp)
        self.assertEqual(outcome.result.missing_fields, (MissingField.AFFECTED_MEMBER,))

    def test_overlong_input_is_rejected_without_backend_call(self):
        cases = {
            'answer': dict(answer='x' * (MAX_FOLLOW_UP_ANSWER_LENGTH + 1)),
            'text': dict(text='x' * (MAX_SUBMITTED_TEXT_LENGTH + 1)),
        }
        for name, overrides in cases.items():
            with self.subTest(name):
                backend = RecordingBackend(answer_output())

                outcome = self.answer(backend, **overrides)

                self.assertEqual(
                    outcome.result,
                    ClassificationUnavailable(reason=UnavailableReason.INPUT_TOO_LONG),
                )
                self.assertEqual(backend.requests, [])

    def test_answer_at_length_limit_reaches_backend(self):
        backend = RecordingBackend(answer_output())

        self.answer(backend, answer='x' * MAX_FOLLOW_UP_ANSWER_LENGTH)

        self.assertEqual(len(backend.requests), 1)

    def test_answer_is_kept_out_of_repr_and_logs(self):
        backend = RecordingBackend(answer_output())

        with self.assertNoLogs(level=logging.DEBUG):
            outcome = self.answer(backend, answer=f'w piątek {ANSWER_SENTINEL}')

        self.assertNotIn(ANSWER_SENTINEL, repr(backend.requests[0]))
        self.assertNotIn(ANSWER_SENTINEL, repr(outcome))

    def test_no_database_writes_on_any_outcome(self):
        cases = {
            'proposal': RecordingBackend(answer_output()),
            'still missing': RecordingBackend(answer_output(date=None)),
            'unavailable': RecordingBackend(
                error=ClassificationBackendError(UnavailableReason.PROVIDER_ERROR)
            ),
        }
        for name, backend in cases.items():
            with self.subTest(name):
                counts_before = self._row_counts()

                with CaptureQueriesContext(connection) as queries:
                    self.answer(backend)

                writes = [
                    query['sql']
                    for query in queries.captured_queries
                    if query['sql'].lstrip().upper().startswith(WRITE_PREFIXES)
                ]
                self.assertEqual(writes, [])
                self.assertEqual(self._row_counts(), counts_before)

    def _row_counts(self):
        return {
            model._meta.label: model._default_manager.count()
            for model in apps.get_models()
        }
