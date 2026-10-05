"""Tests for ``correct_proposal_for_parent``.

A recording fake backend scripts the correction's classification so the
preserve-unmentioned merge, grounding, authorization and privacy rules are
pinned without a provider.
"""

import datetime
import logging

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from entries.classification.backends import BackendOutput, ClassificationBackendError
from entries.classification.service import (
    MAX_CORRECTION_LENGTH,
    MAX_SUBMITTED_TEXT_LENGTH,
    CorrectionRejection,
    correct_proposal_for_parent,
)
from entries.classification.types import (
    SCHOOL_SUBJECT_MAX_LENGTH,
    ClassificationFollowUp,
    ClassificationProposal,
    EntryType,
    MissingField,
    ProposalValues,
    SchoolItemKind,
    UnavailableReason,
)
from entries.tests.test_classification_service import (
    REFERENCE_DATE,
    WRITE_PREFIXES,
    FamilyFixtureMixin,
    RecordingBackend,
    TwoParentFixtureMixin,
)
from family_access.models import FamilyMember

FRIDAY = datetime.date(2026, 9, 18)
MONDAY = datetime.date(2026, 9, 21)
CORRECTION = 'zmień datę na piątek'
CORRECTION_SENTINEL = 'SENTINEL-CORRECTION-7e21c4'
CONTENT = 'Sprawdzian'


def school_test(**overrides):
    """A complete school test proposal on screen."""
    values = dict(
        entry_type=EntryType.CALENDAR_EVENT,
        content=CONTENT,
        date=MONDAY,
        time=datetime.time(8, 0),
        school_item=SchoolItemKind.TEST,
        school_subject='matematyka',
        member_name='Michał',
    )
    values.update(overrides)
    return ProposalValues(**values)


def correction_output(changed, **overrides):
    """A correction result that copies the school test and changes ``changed``."""
    values = dict(
        entry_type=EntryType.CALENDAR_EVENT,
        content=CONTENT,
        grounded=True,
        date=MONDAY,
        time=datetime.time(8, 0),
        school_item=SchoolItemKind.TEST,
        member_name='Michał',
        school_subject='matematyka',
        changed_fields=frozenset(changed),
    )
    values.update(overrides)
    return BackendOutput(**values)


class CorrectionTestMixin(FamilyFixtureMixin):
    def correct(self, backend, current=None, correction=CORRECTION, user=None, member='default'):
        return correct_proposal_for_parent(
            user if user is not None else self.parent.user,
            current if current is not None else school_test(),
            correction,
            reference_date=REFERENCE_DATE,
            current_member=self.child if member == 'default' else member,
            backend=backend,
        )

    def assert_not_applied(self, correction, rejection=CorrectionRejection.NOT_APPLIED):
        self.assertFalse(correction.applied)
        self.assertIsNone(correction.outcome)
        self.assertEqual(correction.rejection, rejection)


class MergeTests(CorrectionTestMixin, TestCase):
    def test_date_only_change_keeps_every_other_value(self):
        backend = RecordingBackend(correction_output({'date'}, date=FRIDAY))

        correction = self.correct(backend)

        self.assertTrue(correction.applied)
        self.assertEqual(correction.changed, frozenset({'date'}))
        self.assertEqual(
            correction.outcome.result,
            ClassificationProposal(
                entry_type=EntryType.CALENDAR_EVENT,
                content=CONTENT,
                date=FRIDAY,
                time=datetime.time(8, 0),
                school_item=SchoolItemKind.TEST,
                member_name='Michał',
                school_subject='matematyka',
            ),
        )
        self.assertEqual(correction.outcome.member, self.child)
        self.assertEqual(len(backend.requests), 1)

    def test_unlisted_fields_in_the_output_are_ignored(self):
        backend = RecordingBackend(
            correction_output(
                {'date'},
                date=FRIDAY,
                content='Zupełnie inny tytuł',
                entry_type=EntryType.TODO,
                time=datetime.time(9, 30),
                school_item=SchoolItemKind.QUIZ,
                school_subject='historia',
                member_name='Ania',
            )
        )

        correction = self.correct(backend)

        result = correction.outcome.result
        self.assertEqual(result.content, CONTENT)
        self.assertEqual(result.entry_type, EntryType.CALENDAR_EVENT)
        self.assertEqual(result.time, datetime.time(8, 0))
        self.assertEqual(result.school_item, SchoolItemKind.TEST)
        self.assertEqual(result.school_subject, 'matematyka')
        self.assertEqual(result.date, FRIDAY)
        self.assertEqual(correction.outcome.member, self.child)

    def test_general_note_becomes_a_dated_todo_keeping_its_title(self):
        current = ProposalValues(entry_type=EntryType.NOTE, content='Kupić prezent dla babci')
        backend = RecordingBackend(
            BackendOutput(
                entry_type=EntryType.TODO,
                content='Zadanie na jutro',
                grounded=True,
                date=FRIDAY,
                changed_fields=frozenset({'entry_type', 'date'}),
            )
        )

        correction = self.correct(backend, current=current, member=None)

        self.assertTrue(correction.applied)
        self.assertEqual(
            correction.outcome.result,
            ClassificationProposal(
                entry_type=EntryType.TODO, content='Kupić prezent dla babci', date=FRIDAY
            ),
        )
        self.assertIsNone(correction.outcome.member)

    def test_subject_correction_fills_a_missing_subject(self):
        backend = RecordingBackend(
            correction_output({'school_subject'}, school_subject=' fizyka ')
        )

        correction = self.correct(backend, current=school_test(school_subject=None))

        self.assertIsInstance(correction.outcome.result, ClassificationProposal)
        self.assertEqual(correction.outcome.result.school_subject, 'fizyka')
        self.assertEqual(correction.outcome.result.date, MONDAY)

    def test_school_item_correction_changes_the_school_item(self):
        backend = RecordingBackend(
            correction_output({'school_item'}, school_item=SchoolItemKind.QUIZ)
        )

        correction = self.correct(backend, correction='to kartkówka, nie sprawdzian')

        self.assertTrue(correction.applied)
        self.assertEqual(correction.outcome.result.school_item, SchoolItemKind.QUIZ)
        self.assertEqual(correction.outcome.result.school_subject, 'matematyka')

    def test_school_item_that_does_not_fit_the_type_is_rejected(self):
        cases = {
            'type changed, school item kept': correction_output(
                {'entry_type'}, entry_type=EntryType.TODO
            ),
            'school item does not fit the type': correction_output(
                {'school_item'}, school_item=SchoolItemKind.GRADE
            ),
        }
        expected_item = {
            'type changed, school item kept': SchoolItemKind.TEST,
            'school item does not fit the type': SchoolItemKind.GRADE,
        }
        for name, output in cases.items():
            with self.subTest(name):
                correction = self.correct(RecordingBackend(output))

                self.assert_not_applied(correction, CorrectionRejection.SCHOOL_ITEM_MISMATCH)
                self.assertEqual(correction.school_item, expected_item[name])

    def test_overlong_corrected_subject_is_not_applied(self):
        backend = RecordingBackend(
            correction_output(
                {'school_subject'}, school_subject='x' * (SCHOOL_SUBJECT_MAX_LENGTH + 1)
            )
        )

        self.assert_not_applied(self.correct(backend))

    def test_clearing_the_date_of_an_event_asks_for_it(self):
        backend = RecordingBackend(correction_output({'date'}, date=None))

        correction = self.correct(backend, correction='usuń datę')

        self.assertTrue(correction.applied)
        self.assertIsInstance(correction.outcome.result, ClassificationFollowUp)
        self.assertEqual(correction.outcome.result.missing_fields, (MissingField.DATE,))
        self.assertEqual(correction.outcome.result.time, datetime.time(8, 0))

    def test_relative_shift_result_is_taken_as_returned(self):
        backend = RecordingBackend(
            correction_output({'date', 'time'}, date=MONDAY + datetime.timedelta(days=7), time=None)
        )

        correction = self.correct(backend, correction='przesuń o tydzień, bez godziny')

        self.assertEqual(correction.outcome.result.date, datetime.date(2026, 9, 28))
        self.assertIsNone(correction.outcome.result.time)
        self.assertEqual(correction.changed, frozenset({'date', 'time'}))

    def test_member_change_to_an_allowed_name_resolves_locally(self):
        backend = RecordingBackend(correction_output({'member_name'}, member_name='Ania'))

        correction = self.correct(backend, correction='to dla Ani')

        self.assertEqual(correction.outcome.result.member_name, 'Ania')
        self.assertEqual(correction.outcome.member, self.other_child)

    def test_member_change_to_an_unknown_name_is_not_applied(self):
        for name in ('Bartek', 'Zosia', 'Kuba'):
            with self.subTest(name):
                backend = RecordingBackend(
                    correction_output({'member_name'}, member_name=name, member_mention=name)
                )

                self.assert_not_applied(self.correct(backend, correction=f'to dla {name}'))

    def test_unknown_mention_without_a_name_is_not_applied(self):
        backend = RecordingBackend(
            correction_output({'member_name'}, member_name=None, member_mention='Bartek')
        )

        self.assert_not_applied(self.correct(backend, correction='to dla Bartka'))

    def test_member_cleared_for_the_whole_family(self):
        current = ProposalValues(
            entry_type=EntryType.TODO, content='Kupić mleko', member_name='Michał'
        )
        backend = RecordingBackend(
            BackendOutput(
                entry_type=EntryType.TODO,
                content='Kupić mleko',
                grounded=True,
                changed_fields=frozenset({'member_name'}),
            )
        )

        correction = self.correct(backend, current=current, correction='dla całej rodziny')

        self.assertTrue(correction.applied)
        self.assertIsNone(correction.outcome.member)

    def test_ungrounded_date_is_not_applied(self):
        # The adapter removes an ungrounded date from ``changed_fields``.
        backend = RecordingBackend(correction_output(set(), date=None))

        self.assert_not_applied(self.correct(backend))

    def test_ungrounded_output_is_not_applied(self):
        backend = RecordingBackend(correction_output({'date'}, date=FRIDAY, grounded=False))

        self.assert_not_applied(self.correct(backend))

    def test_empty_or_missing_changed_fields_is_not_applied(self):
        for changed in (frozenset(), None, frozenset({'polecenie'})):
            with self.subTest(changed=changed):
                backend = RecordingBackend(
                    BackendOutput(
                        entry_type=EntryType.CALENDAR_EVENT,
                        content=CONTENT,
                        grounded=True,
                        date=FRIDAY,
                        changed_fields=changed,
                    )
                )

                self.assert_not_applied(self.correct(backend))

    def test_null_type_or_blank_title_is_not_applied(self):
        cases = {
            'null type': correction_output({'entry_type'}, entry_type=None),
            'blank title': correction_output({'content'}, content='   '),
        }
        for name, output in cases.items():
            with self.subTest(name):
                self.assert_not_applied(self.correct(RecordingBackend(output)))

    def test_provider_timeout_is_not_applied(self):
        backend = RecordingBackend(error=ClassificationBackendError(UnavailableReason.TIMEOUT))

        correction = self.correct(backend)

        self.assert_not_applied(correction)
        self.assertEqual(len(backend.requests), 1)

    def test_current_member_outside_the_family_is_dropped(self):
        for member in (self.other_family_child, self.inactive_child):
            with self.subTest(member.display_name):
                backend = RecordingBackend(correction_output({'date'}, date=FRIDAY))

                correction = self.correct(
                    backend,
                    current=school_test(member_name=member.display_name),
                    member=member,
                )

                self.assertIsNone(backend.requests[0].current_proposal.member_name)
                self.assertIsInstance(correction.outcome.result, ClassificationFollowUp)
                self.assertEqual(
                    correction.outcome.result.missing_fields, (MissingField.AFFECTED_MEMBER,)
                )
                self.assertIsNone(correction.outcome.member)


class ShortNameCorrectionTests(CorrectionTestMixin, TestCase):
    """S-02 short names apply only when the correction changes the person."""

    def setUp(self):
        super().setUp()
        self.other_child.display_name = 'Ola'
        self.other_child.save(update_fields=('display_name',))
        self.hanna = self._member('hanna', FamilyMember.Role.CHILD, 'Hanna')

    def test_diminutive_resolves_through_the_mention(self):
        backend = RecordingBackend(
            correction_output({'member_name'}, member_name=None, member_mention='Hania')
        )

        correction = self.correct(backend, correction='to dla Hani')

        self.assertTrue(correction.applied)
        self.assertEqual(correction.outcome.result.member_name, 'Hanna')
        self.assertEqual(correction.outcome.member, self.hanna)

    def test_ambiguous_diminutive_highlights_the_member(self):
        self._member('anna', FamilyMember.Role.CHILD, 'Anna')
        backend = RecordingBackend(
            correction_output({'member_name'}, member_name='Hanna', member_mention='Hania')
        )

        correction = self.correct(backend, correction='to dla Hani')

        self.assertTrue(correction.applied)
        self.assertIsInstance(correction.outcome.result, ClassificationFollowUp)
        self.assertIn(MissingField.AMBIGUOUS_MEMBER, correction.outcome.result.missing_fields)
        self.assertIsNone(correction.outcome.member)

    def test_stray_mention_never_reassigns_the_current_member(self):
        backend = RecordingBackend(
            correction_output({'date'}, date=FRIDAY, member_mention='Hania')
        )

        correction = self.correct(backend, correction='Hania ma to w piątek')

        self.assertEqual(correction.outcome.result.date, FRIDAY)
        self.assertEqual(correction.outcome.member, self.child)


class RequestAndAuthorizationTests(CorrectionTestMixin, TestCase):
    def test_request_carries_current_values_and_correction_only(self):
        backend = RecordingBackend(correction_output({'date'}, date=FRIDAY))
        current = school_test(member_name='Stare imię')

        self.correct(backend, current=current)

        (request,) = backend.requests
        self.assertEqual(request.correction_text, CORRECTION)
        self.assertEqual(request.submitted_text, CORRECTION)
        self.assertEqual(request.current_proposal, school_test())
        self.assertIsNone(request.follow_up_answer)
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
                backend = RecordingBackend(correction_output({'date'}, date=FRIDAY))

                with self.assertRaises(PermissionDenied):
                    self.correct(backend, user=user)

                self.assertEqual(backend.requests, [])

    def test_other_family_parent_never_sees_or_keeps_our_member(self):
        backend = RecordingBackend(correction_output({'date'}, date=FRIDAY))

        correction = self.correct(backend, user=self.other_family_parent.user)

        (request,) = backend.requests
        self.assertEqual(request.allowed_member_names, ('Tomek', 'Kuba'))
        self.assertIsNone(request.current_proposal.member_name)
        self.assertIsNone(correction.outcome.member)

    def test_overlong_input_is_rejected_without_backend_call(self):
        cases = {
            'correction': dict(correction='x' * (MAX_CORRECTION_LENGTH + 1)),
            'title': dict(current=school_test(content='x' * (MAX_SUBMITTED_TEXT_LENGTH + 1))),
        }
        for name, overrides in cases.items():
            with self.subTest(name):
                backend = RecordingBackend(correction_output({'date'}, date=FRIDAY))

                correction = self.correct(backend, **overrides)

                self.assert_not_applied(correction, CorrectionRejection.TOO_LONG)
                self.assertEqual(backend.requests, [])

    def test_correction_at_length_limit_reaches_backend(self):
        backend = RecordingBackend(correction_output({'date'}, date=FRIDAY))

        self.correct(backend, correction='x' * MAX_CORRECTION_LENGTH)

        self.assertEqual(len(backend.requests), 1)

    def test_correction_is_kept_out_of_repr_and_logs(self):
        backend = RecordingBackend(correction_output({'date'}, date=FRIDAY))

        with self.assertNoLogs(level=logging.DEBUG):
            correction = self.correct(backend, correction=f'w piątek {CORRECTION_SENTINEL}')

        self.assertNotIn(CORRECTION_SENTINEL, repr(backend.requests[0]))
        self.assertNotIn(CORRECTION_SENTINEL, repr(correction))
        self.assertNotIn(CONTENT, repr(backend.requests[0].current_proposal))

    def test_no_database_writes_on_any_outcome(self):
        cases = {
            'applied': RecordingBackend(correction_output({'date'}, date=FRIDAY)),
            'not applied': RecordingBackend(correction_output(set())),
            'provider failure': RecordingBackend(
                error=ClassificationBackendError(UnavailableReason.PROVIDER_ERROR)
            ),
        }
        for name, backend in cases.items():
            with self.subTest(name):
                counts_before = self._row_counts()

                with CaptureQueriesContext(connection) as queries:
                    self.correct(backend)

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


class TwoParentCorrectionTests(TwoParentFixtureMixin, CorrectionTestMixin, TestCase):
    """S-07: a correction keeps or sets a parent assignee like any other member."""

    def parent_note(self, member_name):
        return school_test(
            entry_type=EntryType.TODO,
            content='Odebrać paczkę',
            date=None,
            time=None,
            school_item=None,
            school_subject=None,
            member_name=member_name,
        )

    def test_correction_not_mentioning_the_person_keeps_a_parent(self):
        for member in (self.second_parent, self.parent):
            with self.subTest(member=member.display_name):
                backend = RecordingBackend(
                    correction_output(
                        {'date'},
                        entry_type=EntryType.TODO,
                        content='Odebrać paczkę',
                        date=FRIDAY,
                        time=None,
                        school_item=None,
                        school_subject=None,
                        member_name=None,
                    )
                )

                correction = self.correct(
                    backend, current=self.parent_note(member.display_name), member=member
                )

                self.assertTrue(correction.applied)
                self.assertEqual(correction.outcome.member, member)
                self.assertEqual(correction.outcome.result.date, FRIDAY)

    def test_correction_naming_the_other_parent_reassigns_to_them(self):
        backend = RecordingBackend(correction_output({'member_name'}, member_name='Paweł'))

        correction = self.correct(backend)

        self.assertTrue(correction.applied)
        self.assertEqual(correction.outcome.member, self.second_parent)

    def test_correction_naming_a_foreign_or_inactive_parent_is_not_applied(self):
        for name in ('Tomek', 'Jolanta'):
            with self.subTest(name=name):
                backend = RecordingBackend(correction_output({'member_name'}, member_name=name))

                self.assert_not_applied(self.correct(backend))
