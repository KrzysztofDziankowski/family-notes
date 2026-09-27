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
            {'submitted_text', 'allowed_member_names', 'reference_date', 'locale'},
        )
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
        # S-01 adds the confirmed Entry; classification itself stores nothing.
        models = apps.get_app_config('entries').get_models()
        self.assertEqual([model.__name__ for model in models], ['Entry'])

    def _row_counts(self):
        return {
            model._meta.label: model._default_manager.count()
            for model in apps.get_models()
        }
