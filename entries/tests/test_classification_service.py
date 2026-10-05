"""Authorized orchestration tests for ``classify_for_parent``.

A recording fake backend captures every ``BackendRequest`` so tests can
assert who reached the provider seam and exactly which names were sent.
"""

import datetime
from unittest import mock

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from entries.classification.backends import (
    BackendOutput,
    BackendRequest,
    ClassificationBackendError,
)
from entries.classification.service import (
    MAX_SUBMITTED_TEXT_LENGTH,
    ParentClassification,
    classify_for_parent,
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
from family_access.models import Family, FamilyMember

REFERENCE_DATE = datetime.date(2026, 9, 17)
MONDAY = datetime.date(2026, 9, 21)
SUBMITTED_TEXT = 'Michał ma sprawdzian z biologii w poniedziałek'
WRITE_PREFIXES = ('INSERT', 'UPDATE', 'DELETE', 'REPLACE')


def school_test_output(member_name='Michał', **overrides):
    values = dict(
        entry_type=EntryType.CALENDAR_EVENT,
        content='Sprawdzian z biologii',
        grounded=True,
        date=MONDAY,
        school_item=SchoolItemKind.TEST,
        member_name=member_name,
        school_subject='biologia',
    )
    values.update(overrides)
    return BackendOutput(**values)


class RecordingBackend:
    """Fake backend that records requests and returns or raises a script."""

    def __init__(self, output=None, error=None):
        self.output = output if output is not None else school_test_output()
        self.error = error
        self.requests = []

    def classify(self, request: BackendRequest) -> BackendOutput:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.output


class FamilyFixtureMixin:
    """Two families: ours (parent, children, inactive member) and another."""

    def setUp(self):
        super().setUp()
        self.family = Family.objects.create(name='Our Family')
        self.other_family = Family.objects.create(name='Other Family')
        self.parent = self._member('parent', FamilyMember.Role.PARENT, 'Ewa')
        self.child = self._member('child', FamilyMember.Role.CHILD, 'Michał')
        self.other_child = self._member('other-child', FamilyMember.Role.CHILD, 'Ania')
        self.inactive_child = self._member(
            'inactive-child', FamilyMember.Role.CHILD, 'Zosia', is_active=False
        )
        self.other_family_parent = self._member(
            'other-parent', FamilyMember.Role.PARENT, 'Tomek', family=self.other_family
        )
        self.other_family_child = self._member(
            'other-family-child', FamilyMember.Role.CHILD, 'Kuba', family=self.other_family
        )

    def _member(self, username, role, display_name, family=None, is_active=True):
        user = get_user_model().objects.create_user(
            username=username, email=f'{username}@example.test'
        )
        return FamilyMember.objects.create(
            user=user,
            family=family or self.family,
            role=role,
            display_name=display_name,
            is_active=is_active,
        )

    def classify(self, user, backend, text=SUBMITTED_TEXT):
        return classify_for_parent(
            user, text, reference_date=REFERENCE_DATE, locale='pl-PL', backend=backend
        )


class TwoParentFixtureMixin(FamilyFixtureMixin):
    """The shared family plus a second active parent and an inactive parent (S-07).

    ``self.parent`` (Ewa) is the author; ``self.second_parent`` (Paweł) is the
    other parent; ``self.other_family_parent`` (Tomek) is never assignable.
    """

    def setUp(self):
        super().setUp()
        self.second_parent = self._member('second-parent', FamilyMember.Role.PARENT, 'Paweł')
        self.inactive_parent = self._member(
            'inactive-parent', FamilyMember.Role.PARENT, 'Jolanta', is_active=False
        )


class TwoParentResolutionTests(TwoParentFixtureMixin, TestCase):
    """S-07: a returned parent name resolves to that parent's membership."""

    def test_both_parents_are_sent_as_allowed_names(self):
        backend = RecordingBackend()

        self.classify(self.parent.user, backend)

        self.assertEqual(
            backend.requests[0].allowed_member_names,
            ('Ewa', 'Michał', 'Ania', 'Paweł'),
        )

    def test_parent_name_resolves_to_that_parent(self):
        for member in (self.parent, self.second_parent):
            with self.subTest(member=member.display_name):
                backend = RecordingBackend(
                    BackendOutput(
                        entry_type=EntryType.NOTE,
                        content='Odebrać paczkę',
                        grounded=True,
                        member_name=member.display_name,
                    )
                )

                outcome = self.classify(self.parent.user, backend, text='Paczka')

                self.assertIsInstance(outcome.result, ClassificationProposal)
                self.assertEqual(outcome.member, member)

    def test_foreign_and_inactive_parent_names_are_unknown(self):
        for name in ('Tomek', 'Jolanta'):
            with self.subTest(name=name):
                backend = RecordingBackend(
                    BackendOutput(
                        entry_type=EntryType.NOTE,
                        content='Odebrać paczkę',
                        grounded=True,
                        member_name=name,
                    )
                )

                outcome = self.classify(self.parent.user, backend, text='Paczka')

                self.assertIsNone(outcome.member)
                self.assertEqual(
                    outcome.result,
                    ClassificationUnavailable(reason=UnavailableReason.UNKNOWN_MEMBER),
                )


class AuthorizationMatrixTests(FamilyFixtureMixin, TestCase):
    """3.1: only an active parent reaches the backend."""

    def test_active_parent_invokes_backend_once(self):
        backend = RecordingBackend()

        outcome = self.classify(self.parent.user, backend)

        self.assertEqual(len(backend.requests), 1)
        self.assertIsInstance(outcome, ParentClassification)
        self.assertIsInstance(outcome.result, ClassificationProposal)
        self.assertEqual(outcome.member, self.child)

    def test_unauthorized_users_are_denied_without_backend_call(self):
        unconfigured = get_user_model().objects.create_user(username='unconfigured')
        cases = {
            'anonymous': lambda: AnonymousUser(),
            'unconfigured user': lambda: unconfigured,
            'assigned child': lambda: self.child.user,
            'other child': lambda: self.other_child.user,
            'inactive membership': lambda: self.inactive_child.user,
            'inactive parent membership': self._deactivate_parent,
            'parent of inactive family': self._deactivate_family,
        }
        for name, get_user in cases.items():
            with self.subTest(name):
                user = get_user()
                backend = RecordingBackend()

                with self.assertRaises(PermissionDenied):
                    self.classify(user, backend)

                self.assertEqual(backend.requests, [])

    def test_unauthorized_user_never_builds_default_backend(self):
        with mock.patch(
            'entries.classification.openai_backend.build_openai_backend'
        ) as build:
            with self.assertRaises(PermissionDenied):
                classify_for_parent(
                    self.child.user, SUBMITTED_TEXT, reference_date=REFERENCE_DATE
                )

        build.assert_not_called()

    @override_settings(CLASSIFICATION_ENABLED=False)
    def test_default_backend_is_built_after_authorization_and_fails_closed(self):
        outcome = classify_for_parent(
            self.parent.user, SUBMITTED_TEXT, reference_date=REFERENCE_DATE
        )

        self.assertEqual(
            outcome.result, ClassificationUnavailable(reason=UnavailableReason.DISABLED)
        )
        self.assertIsNone(outcome.member)

    def test_default_backend_is_closed_after_classification(self):
        for error in (None, ClassificationBackendError(UnavailableReason.TIMEOUT)):
            with self.subTest(error=error):
                built = mock.Mock()
                if error is None:
                    built.classify.return_value = school_test_output()
                else:
                    built.classify.side_effect = error
                with mock.patch(
                    'entries.classification.openai_backend.build_openai_backend',
                    return_value=built,
                ):
                    classify_for_parent(
                        self.parent.user, SUBMITTED_TEXT, reference_date=REFERENCE_DATE
                    )

                built.close.assert_called_once_with()

    def test_injected_backend_is_not_closed(self):
        backend = mock.Mock()
        backend.classify.return_value = school_test_output()

        classify_for_parent(
            self.parent.user, SUBMITTED_TEXT, reference_date=REFERENCE_DATE, backend=backend
        )

        backend.close.assert_not_called()

    def test_overlong_text_is_rejected_without_backend_call(self):
        backend = RecordingBackend()

        outcome = classify_for_parent(
            self.parent.user,
            'x' * (MAX_SUBMITTED_TEXT_LENGTH + 1),
            reference_date=REFERENCE_DATE,
            backend=backend,
        )

        self.assertEqual(
            outcome.result,
            ClassificationUnavailable(reason=UnavailableReason.INPUT_TOO_LONG),
        )
        self.assertEqual(backend.requests, [])

    def test_text_at_length_limit_reaches_backend(self):
        backend = RecordingBackend()

        classify_for_parent(
            self.parent.user,
            'x' * MAX_SUBMITTED_TEXT_LENGTH,
            reference_date=REFERENCE_DATE,
            backend=backend,
        )

        self.assertEqual(len(backend.requests), 1)

    def test_reference_datetime_is_reduced_to_its_date(self):
        backend = RecordingBackend()

        classify_for_parent(
            self.parent.user,
            SUBMITTED_TEXT,
            reference_date=datetime.datetime(2026, 9, 17, 21, 30),
            backend=backend,
        )

        self.assertEqual(backend.requests[0].reference_date, REFERENCE_DATE)
        self.assertIs(type(backend.requests[0].reference_date), datetime.date)

    def _deactivate_parent(self):
        self.parent.is_active = False
        self.parent.save(update_fields=('is_active',))
        return self.parent.user

    def _deactivate_family(self):
        self.family.is_active = False
        self.family.save(update_fields=('is_active',))
        return self.parent.user


class CandidateAndResolutionTests(FamilyFixtureMixin, TestCase):
    """3.2: only active same-family names are sent; resolution is local."""

    def test_outbound_request_contains_only_active_same_family_names(self):
        backend = RecordingBackend()

        self.classify(self.parent.user, backend)

        request = backend.requests[0]
        self.assertEqual(request.allowed_member_names, ('Ewa', 'Michał', 'Ania'))
        self.assertTrue(all(isinstance(name, str) for name in request.allowed_member_names))
        for excluded in ('Zosia', 'Tomek', 'Kuba'):
            self.assertNotIn(excluded, request.allowed_member_names)
        self.assertEqual(request.submitted_text, SUBMITTED_TEXT)
        self.assertEqual(request.reference_date, REFERENCE_DATE)
        self.assertEqual(request.locale, 'pl-PL')

    def test_outbound_request_carries_no_database_ids(self):
        backend = RecordingBackend()

        self.classify(self.parent.user, backend)

        request = backend.requests[0]
        ids = {
            str(pk)
            for pk in FamilyMember.objects.values_list('pk', flat=True)
        } | {str(pk) for pk in Family.objects.values_list('pk', flat=True)}
        self.assertEqual(
            set(vars(request)),
            {
                'submitted_text',
                'allowed_member_names',
                'reference_date',
                'locale',
                'follow_up_question',
                'follow_up_answer',
                'current_proposal',
                'correction_text',
            },
        )
        self.assertIsNone(request.follow_up_question)
        self.assertIsNone(request.follow_up_answer)
        self.assertIsNone(request.current_proposal)
        self.assertIsNone(request.correction_text)
        for name in request.allowed_member_names:
            self.assertNotIn(name, ids)

    def test_unique_name_resolves_to_that_membership(self):
        outcome = self.classify(self.parent.user, RecordingBackend())

        self.assertIsInstance(outcome.result, ClassificationProposal)
        self.assertEqual(outcome.result.member_name, 'Michał')
        self.assertEqual(outcome.member, self.child)

    def test_surrounding_whitespace_is_trimmed_before_resolution(self):
        self.child.display_name = ' Michał '
        self.child.save(update_fields=('display_name',))
        backend = RecordingBackend(school_test_output(member_name=' Michał '))

        outcome = self.classify(self.parent.user, backend)

        self.assertEqual(outcome.member, self.child)

    def test_case_mismatch_does_not_resolve(self):
        outcome = self.classify(
            self.parent.user, RecordingBackend(school_test_output(member_name='michał'))
        )

        self.assertEqual(
            outcome.result,
            ClassificationUnavailable(reason=UnavailableReason.UNKNOWN_MEMBER),
        )
        self.assertIsNone(outcome.member)

    def test_duplicate_active_names_become_ambiguous_follow_up(self):
        self._member('second-michal', FamilyMember.Role.CHILD, 'Michał ')
        backend = RecordingBackend()

        outcome = self.classify(self.parent.user, backend)

        self.assertIsInstance(outcome.result, ClassificationFollowUp)
        self.assertIn(MissingField.AMBIGUOUS_MEMBER, outcome.result.missing_fields)
        self.assertIsNone(outcome.result.member_name)
        self.assertIsNone(outcome.member)

    def test_unresolvable_names_never_resolve_to_a_membership(self):
        cases = {
            'invented': 'Bartek',
            'inactive same-family member': 'Zosia',
            'other-family child': 'Kuba',
            'other-family parent': 'Tomek',
        }
        for name, returned in cases.items():
            with self.subTest(name):
                outcome = self.classify(
                    self.parent.user,
                    RecordingBackend(school_test_output(member_name=returned)),
                )

                self.assertEqual(
                    outcome.result,
                    ClassificationUnavailable(reason=UnavailableReason.UNKNOWN_MEMBER),
                )
                self.assertIsNone(outcome.member)

    def test_inactive_namesake_does_not_make_active_member_ambiguous(self):
        self._member('old-michal', FamilyMember.Role.CHILD, 'Michał', is_active=False)
        self._member(
            'foreign-michal', FamilyMember.Role.CHILD, 'Michał', family=self.other_family
        )

        outcome = self.classify(self.parent.user, RecordingBackend())

        self.assertIsInstance(outcome.result, ClassificationProposal)
        self.assertEqual(outcome.member, self.child)

    def test_no_returned_member_leaves_member_unset(self):
        backend = RecordingBackend(
            school_test_output(
                member_name=None,
                entry_type=EntryType.NOTE,
                school_item=SchoolItemKind.LUCKY_NUMBER,
                date=None,
            )
        )

        outcome = self.classify(self.parent.user, backend)

        self.assertIsInstance(outcome.result, ClassificationProposal)
        self.assertIsNone(outcome.member)

    def test_school_event_without_subject_asks_the_parent(self):
        for kind in (
            SchoolItemKind.HOMEWORK,
            SchoolItemKind.CLASS_TEST,
            SchoolItemKind.TEST,
            SchoolItemKind.QUIZ,
        ):
            with self.subTest(kind=kind.value):
                backend = RecordingBackend(school_test_output(school_item=kind, school_subject=None))

                outcome = self.classify(self.parent.user, backend)

                self.assertIsInstance(outcome.result, ClassificationFollowUp)
                self.assertEqual(outcome.result.missing_fields, (MissingField.SCHOOL_SUBJECT,))
                self.assertEqual(outcome.member, self.child)

    def test_returned_subject_is_trimmed_onto_the_proposal(self):
        backend = RecordingBackend(school_test_output(school_subject='  biologia '))

        outcome = self.classify(self.parent.user, backend)

        self.assertIsInstance(outcome.result, ClassificationProposal)
        self.assertEqual(outcome.result.school_subject, 'biologia')

    def test_backend_error_becomes_unavailable_result(self):
        backend = RecordingBackend(error=ClassificationBackendError(UnavailableReason.TIMEOUT))

        outcome = self.classify(self.parent.user, backend)

        self.assertEqual(
            outcome.result, ClassificationUnavailable(reason=UnavailableReason.TIMEOUT)
        )
        self.assertIsNone(outcome.member)

    def test_repr_does_not_expose_member_or_content(self):
        outcome = self.classify(self.parent.user, RecordingBackend())

        text = repr(outcome)
        for sensitive in ('Michał', 'Sprawdzian', SUBMITTED_TEXT):
            self.assertNotIn(sensitive, text)


class ShortNameMentionTests(FamilyFixtureMixin, TestCase):
    """PK-01: the parent's short name selects a member of their own family."""

    MENTION_SENTINEL = 'SENTINEL-MENTION-Hania-91c3'

    def setUp(self):
        super().setUp()
        # "Ania" shares the Anna group with "Hania"; rename her so each test
        # chooses its own Hania/Anna collisions.
        self.other_child.display_name = 'Ola'
        self.other_child.save(update_fields=('display_name',))

    def add_hanna(self):
        return self._member('hanna', FamilyMember.Role.CHILD, 'Hanna')

    def add_anna(self):
        return self._member('anna', FamilyMember.Role.CHILD, 'Anna')

    def test_unique_short_name_resolves_to_the_family_member(self):
        hanna = self.add_hanna()
        backend = RecordingBackend(school_test_output(member_name=None, member_mention='Hania'))

        outcome = self.classify(self.parent.user, backend, text='Hania ma sprawdzian')

        self.assertIsInstance(outcome.result, ClassificationProposal)
        self.assertEqual(outcome.result.member_name, 'Hanna')
        self.assertEqual(outcome.result.school_subject, 'biologia')
        self.assertEqual(outcome.member, hanna)

    def test_parent_mention_wins_over_the_model_pick(self):
        hanna = self.add_hanna()
        backend = RecordingBackend(school_test_output(member_name='Michał', member_mention='Hania'))

        outcome = self.classify(self.parent.user, backend)

        self.assertEqual(outcome.member, hanna)

    def test_short_name_fitting_two_members_asks_and_names_nobody(self):
        self.add_hanna()
        self.add_anna()
        backend = RecordingBackend(school_test_output(member_name='Hanna', member_mention='Hania'))

        outcome = self.classify(self.parent.user, backend)

        self.assertIsInstance(outcome.result, ClassificationFollowUp)
        self.assertEqual(
            outcome.result.missing_fields,
            (MissingField.AMBIGUOUS_MEMBER, MissingField.AFFECTED_MEMBER),
        )
        self.assertIsNone(outcome.result.member_name)
        self.assertEqual(outcome.result.school_subject, 'biologia')
        self.assertIsNone(outcome.member)

    def test_stored_diminutive_of_the_same_group_makes_a_short_name_ambiguous(self):
        # Pinned on purpose: "Hania" is also a form of Anna, so a family with
        # Hanna and a member stored as "Ania" is asked who is meant.
        self.add_hanna()
        self.other_child.display_name = 'Ania'
        self.other_child.save(update_fields=('display_name',))
        backend = RecordingBackend(school_test_output(member_name='Hanna', member_mention='Hania'))

        outcome = self.classify(self.parent.user, backend)

        self.assertIsInstance(outcome.result, ClassificationFollowUp)
        self.assertIn(MissingField.AMBIGUOUS_MEMBER, outcome.result.missing_fields)
        self.assertIsNone(outcome.member)

    def test_ambiguous_todo_asks_only_which_member(self):
        self.add_hanna()
        self.add_anna()
        backend = RecordingBackend(
            school_test_output(
                entry_type=EntryType.TODO,
                school_item=None,
                date=None,
                member_name=None,
                member_mention='Hania',
            )
        )

        outcome = self.classify(self.parent.user, backend)

        self.assertIsInstance(outcome.result, ClassificationFollowUp)
        self.assertEqual(outcome.result.missing_fields, (MissingField.AMBIGUOUS_MEMBER,))
        self.assertIsNone(outcome.member)

    def test_inactive_namesake_does_not_make_a_short_name_ambiguous(self):
        hanna = self.add_hanna()
        self._member('old-anna', FamilyMember.Role.CHILD, 'Anna', is_active=False)
        self._member('foreign-anna', FamilyMember.Role.CHILD, 'Anna', family=self.other_family)
        backend = RecordingBackend(school_test_output(member_name=None, member_mention='Hania'))

        outcome = self.classify(self.parent.user, backend)

        self.assertIsInstance(outcome.result, ClassificationProposal)
        self.assertEqual(outcome.member, hanna)

    def test_mentions_of_inactive_or_foreign_members_never_resolve(self):
        cases = {
            'inactive same-family member': ('Zosia', 'Zosia'),
            'inactive member by its full name': ('Zosia', 'Zofia'),
            'other-family child': ('Kuba', 'Kuba'),
            'other-family child by its full name': ('Kuba', 'Jakub'),
            'other-family parent': ('Tomek', 'Tomasz'),
        }
        for name, (returned, mention) in cases.items():
            with self.subTest(name):
                backend = RecordingBackend(
                    school_test_output(member_name=returned, member_mention=mention)
                )

                outcome = self.classify(self.parent.user, backend)

                self.assertEqual(
                    outcome.result,
                    ClassificationUnavailable(reason=UnavailableReason.UNKNOWN_MEMBER),
                )
                self.assertIsNone(outcome.member)

    def test_unmatched_mention_leaves_the_model_name_to_the_allow_list(self):
        backend = RecordingBackend(school_test_output(member_name='Michał', member_mention='Bożydar'))

        outcome = self.classify(self.parent.user, backend)

        self.assertIsInstance(outcome.result, ClassificationProposal)
        self.assertEqual(outcome.member, self.child)

    def test_request_payload_is_unchanged_by_mentions(self):
        self.add_hanna()
        backend = RecordingBackend(school_test_output(member_name=None, member_mention='Hania'))

        self.classify(self.parent.user, backend)

        (request,) = backend.requests
        self.assertEqual(request.allowed_member_names, ('Ewa', 'Michał', 'Ola', 'Hanna'))
        self.assertIsNone(request.follow_up_answer)

    def test_repr_never_contains_the_mention(self):
        self.add_hanna()
        self.add_anna()
        output = school_test_output(member_name=None, member_mention=self.MENTION_SENTINEL)
        ambiguous = school_test_output(member_name=None, member_mention='Hania')

        outcomes = [
            self.classify(self.parent.user, RecordingBackend(output)),
            self.classify(self.parent.user, RecordingBackend(ambiguous)),
        ]

        text = repr(output) + repr(ambiguous) + repr(outcomes)
        self.assertNotIn(self.MENTION_SENTINEL, text)
        self.assertNotIn('Hania', text)


class NoPersistenceTests(FamilyFixtureMixin, TestCase):
    """3.3: success, follow-up, and failure write nothing to the database."""

    def test_no_database_writes_on_any_outcome(self):
        cases = {
            'proposal': (RecordingBackend(), ClassificationProposal),
            'follow-up': (
                RecordingBackend(school_test_output(date=None)),
                ClassificationFollowUp,
            ),
            'backend failure': (
                RecordingBackend(
                    error=ClassificationBackendError(UnavailableReason.PROVIDER_ERROR)
                ),
                ClassificationUnavailable,
            ),
            'validation failure': (
                RecordingBackend(school_test_output(member_name='Bartek')),
                ClassificationUnavailable,
            ),
        }
        for name, (backend, expected_type) in cases.items():
            with self.subTest(name):
                counts_before = self._row_counts()

                with CaptureQueriesContext(connection) as queries:
                    outcome = self.classify(self.parent.user, backend)

                self.assertIsInstance(outcome.result, expected_type)
                writes = [
                    query['sql']
                    for query in queries.captured_queries
                    if query['sql'].lstrip().upper().startswith(WRITE_PREFIXES)
                ]
                self.assertEqual(writes, [])
                self.assertEqual(self._row_counts(), counts_before)

    def test_denied_attempt_writes_nothing(self):
        counts_before = self._row_counts()

        with CaptureQueriesContext(connection) as queries:
            with self.assertRaises(PermissionDenied):
                self.classify(self.child.user, RecordingBackend())

        self.assertFalse(
            any(
                query['sql'].lstrip().upper().startswith(WRITE_PREFIXES)
                for query in queries.captured_queries
            )
        )
        self.assertEqual(self._row_counts(), counts_before)

    def test_entries_app_models_hold_no_classification_drafts(self):
        # S-01 adds the confirmed Entry, F-04 the raw notification inbox, and
        # S-05 the non-sensitive output provenance and a timestamp-only worker
        # heartbeat; classification stores nothing.
        models = apps.get_app_config('entries').get_models()
        self.assertEqual(
            [model.__name__ for model in models],
            [
                'Entry',
                'InboundNotification',
                'NotificationConversionOutput',
                'ConversionWorkerHeartbeat',
            ],
        )

    def _row_counts(self):
        return {
            model._meta.label: model._default_manager.count()
            for model in apps.get_models()
        }
