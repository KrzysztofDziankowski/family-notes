"""Family-scoped classification fallback for automated EduVulcan conversion.

``classify_for_family`` acts for no user: it sends only the snapshot's child
names, resolves members locally, always yields a usable proposal, and tells
transient provider failures apart so the caller can retry.
"""

import datetime
import logging
import traceback
from unittest import mock

from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from entries.classification import openai_backend
from entries.classification.backends import BackendOutput, ClassificationBackendError
from entries.classification.service import (
    MAX_SUBMITTED_TEXT_LENGTH,
    TRANSIENT_UNAVAILABLE_REASONS,
    FamilyClassification,
    FamilyOutcome,
    classify_for_family,
)
from entries.classification.types import (
    ClassificationProposal,
    EntryType,
    SchoolItemKind,
    UnavailableReason,
)
from entries.eduvulcan.children import snapshot_active_children
from entries.eduvulcan.types import ChildSnapshot
from family_access.models import Family, FamilyMember

from .test_classification_service import FamilyFixtureMixin, RecordingBackend
from .test_openai_backend import (
    FULL_SETTINGS,
    TIMEOUT,
    FakeClock,
    ScriptedTransport,
    make_client,
    ok,
    response_body,
)

REFERENCE_DATE = datetime.date(2026, 9, 23)
EVENT_DATE = datetime.date(2026, 10, 2)
TEXT_SENTINEL = 'SENTINEL-NOTIFICATION-3c9e1a'
NOTIFICATION_TEXT = f'Nowe ogłoszenie: Łucja ma wycieczkę 2 października {TEXT_SENTINEL}'
LUCJA = ChildSnapshot(pk=21, display_name='Łucja')
BARTOSZ = ChildSnapshot(pk=22, display_name='Bartosz')
CHILDREN = (LUCJA, BARTOSZ)


def output(**overrides):
    values = dict(
        entry_type=EntryType.CALENDAR_EVENT,
        content='Wycieczka',
        grounded=True,
        date=EVENT_DATE,
        member_name='Łucja',
    )
    values.update(overrides)
    return BackendOutput(**values)


def classify(backend=None, *, text=NOTIFICATION_TEXT, children=CHILDREN, **options):
    return classify_for_family(
        text, reference_date=REFERENCE_DATE, children=children, backend=backend, **options
    )


class FamilyClassificationOutcomeTests(TestCase):
    def assert_general_note(self, outcome, reason=None, expected=FamilyOutcome.GENERAL_NOTE):
        self.assertIsInstance(outcome, FamilyClassification)
        self.assertEqual(outcome.outcome, expected)
        self.assertEqual(outcome.reason, reason)
        self.assertIsNone(outcome.member)
        self.assertEqual(
            outcome.proposal,
            ClassificationProposal(entry_type=EntryType.NOTE, content=NOTIFICATION_TEXT),
        )

    def test_valid_classification_resolves_a_snapshot_child(self):
        outcome = classify(RecordingBackend(output()))

        self.assertEqual(outcome.outcome, FamilyOutcome.CLASSIFIED)
        self.assertFalse(outcome.retryable)
        self.assertIsNone(outcome.reason)
        self.assertEqual(outcome.member, LUCJA)
        self.assertEqual(outcome.proposal.entry_type, EntryType.CALENDAR_EVENT)
        self.assertEqual(outcome.proposal.date, EVENT_DATE)
        self.assertEqual(outcome.proposal.content, 'Wycieczka')

    def test_classification_without_member_stays_unassigned(self):
        outcome = classify(RecordingBackend(output(member_name=None)))

        self.assertEqual(outcome.outcome, FamilyOutcome.CLASSIFIED)
        self.assertIsNone(outcome.member)

    def test_school_kind_with_its_child_is_classified(self):
        outcome = classify(
            RecordingBackend(output(school_item=SchoolItemKind.TEST, member_name='Bartosz'))
        )

        self.assertEqual(outcome.outcome, FamilyOutcome.CLASSIFIED)
        self.assertEqual(outcome.proposal.school_item, SchoolItemKind.TEST)
        self.assertEqual(outcome.member, BARTOSZ)

    def test_duplicate_snapshot_names_resolve_to_newest_child(self):
        newer = ChildSnapshot(pk=99, display_name='Łucja')
        backend = RecordingBackend(output())

        outcome = classify(backend, children=(LUCJA, newer, BARTOSZ))

        self.assertEqual(outcome.outcome, FamilyOutcome.CLASSIFIED)
        self.assertEqual(outcome.member, newer)
        self.assertEqual(backend.requests[0].allowed_member_names, ('Łucja', 'Bartosz'))

    def test_unrecognized_type_becomes_general_note(self):
        self.assert_general_note(classify(RecordingBackend(output(entry_type=None))))

    def test_follow_up_becomes_general_note(self):
        cases = {
            'event without date': output(date=None),
            'test without member': output(school_item=SchoolItemKind.TEST, member_name=None),
        }
        for name, backend_output in cases.items():
            with self.subTest(name):
                self.assert_general_note(classify(RecordingBackend(backend_output)))

    def test_invalid_output_becomes_general_note_with_reason(self):
        cases = {
            UnavailableReason.UNKNOWN_MEMBER: output(member_name='Kacper'),
            UnavailableReason.UNSUPPORTED_CONTENT: output(grounded=False),
            UnavailableReason.EMPTY_CONTENT: output(content='  '),
        }
        for reason, backend_output in cases.items():
            with self.subTest(reason=reason.value):
                outcome = classify(RecordingBackend(backend_output))

                self.assert_general_note(outcome, reason)
                self.assertFalse(outcome.retryable)

    def test_transient_provider_failures_are_retryable_with_note_ready(self):
        for reason in TRANSIENT_UNAVAILABLE_REASONS:
            with self.subTest(reason=reason.value):
                outcome = classify(
                    RecordingBackend(error=ClassificationBackendError(reason))
                )

                self.assert_general_note(
                    outcome, reason, expected=FamilyOutcome.PROVIDER_UNAVAILABLE
                )
                self.assertTrue(outcome.retryable)

    def test_final_provider_failures_become_general_note(self):
        final = set(UnavailableReason) - TRANSIENT_UNAVAILABLE_REASONS
        for reason in final:
            with self.subTest(reason=reason.value):
                outcome = classify(
                    RecordingBackend(error=ClassificationBackendError(reason))
                )

                self.assert_general_note(outcome, reason)
                self.assertFalse(outcome.retryable)

    def test_overlong_text_becomes_general_note_without_provider_call(self):
        backend = RecordingBackend()
        text = 'x' * (MAX_SUBMITTED_TEXT_LENGTH + 1)

        outcome = classify(backend, text=text)

        self.assertEqual(backend.requests, [])
        self.assertEqual(outcome.outcome, FamilyOutcome.GENERAL_NOTE)
        self.assertEqual(outcome.reason, UnavailableReason.INPUT_TOO_LONG)
        self.assertEqual(outcome.proposal.content, text)

    def test_blank_text_is_a_caller_error(self):
        for text in ('', '   '):
            with self.subTest(text=text), self.assertRaises(ValueError):
                classify(RecordingBackend(), text=text)

    @override_settings(CLASSIFICATION_ENABLED=False)
    def test_disabled_classification_becomes_general_note(self):
        outcome = classify()

        self.assert_general_note(outcome, UnavailableReason.DISABLED)
        self.assertFalse(outcome.retryable)


class FamilyScopeAndRequestTests(FamilyFixtureMixin, TestCase):
    def test_only_active_child_names_of_the_family_reach_the_backend(self):
        backend = RecordingBackend(output(member_name=self.child.display_name))

        outcome = classify(backend, children=snapshot_active_children(self.family))

        (request,) = backend.requests
        # Parent, inactive child, and the other family's members are excluded.
        self.assertEqual(
            request.allowed_member_names,
            (self.child.display_name, self.other_child.display_name),
        )
        self.assertEqual(request.submitted_text, NOTIFICATION_TEXT)
        self.assertEqual(request.reference_date, REFERENCE_DATE)
        self.assertEqual(request.locale, 'pl-PL')
        self.assertEqual(outcome.member.pk, self.child.pk)

    def test_names_outside_the_snapshot_never_resolve(self):
        for name in ('Ewa', 'Zosia', 'Kuba', 'Tomek'):
            with self.subTest(name=name):
                outcome = classify(
                    RecordingBackend(output(member_name=name)),
                    children=snapshot_active_children(self.family),
                )

                self.assertEqual(outcome.outcome, FamilyOutcome.GENERAL_NOTE)
                self.assertEqual(outcome.reason, UnavailableReason.UNKNOWN_MEMBER)
                self.assertIsNone(outcome.member)

    def test_inactive_family_sends_no_names(self):
        self.family.is_active = False
        self.family.save(update_fields=('is_active',))
        backend = RecordingBackend(output(member_name=None))

        classify(backend, children=snapshot_active_children(self.family))

        self.assertEqual(backend.requests[0].allowed_member_names, ())

    def test_request_carries_no_database_ids(self):
        backend = RecordingBackend(output(member_name=self.child.display_name))

        classify(backend, children=snapshot_active_children(self.family))

        request = backend.requests[0]
        self.assertEqual(
            set(vars(request)),
            {
                'submitted_text',
                'allowed_member_names',
                'reference_date',
                'locale',
                'follow_up_question',
                'follow_up_answer',
            },
        )
        self.assertIsNone(request.follow_up_answer)
        ids = {str(pk) for pk in FamilyMember.objects.values_list('pk', flat=True)}
        ids |= {str(pk) for pk in Family.objects.values_list('pk', flat=True)}
        self.assertFalse(ids & set(request.allowed_member_names))

    def test_classification_writes_nothing(self):
        children = snapshot_active_children(self.family)
        for backend in (
            RecordingBackend(output(member_name=self.child.display_name)),
            RecordingBackend(output(date=None)),
            RecordingBackend(error=ClassificationBackendError(UnavailableReason.TIMEOUT)),
        ):
            with self.subTest(backend=backend.output), CaptureQueriesContext(connection) as queries:
                classify(backend, children=children)

            self.assertEqual(queries.captured_queries, [])

    def test_reference_datetime_is_reduced_to_its_date(self):
        backend = RecordingBackend(output(member_name=None))

        classify_for_family(
            NOTIFICATION_TEXT,
            reference_date=datetime.datetime(2026, 9, 23, 21, 0),
            children=CHILDREN,
            backend=backend,
        )

        self.assertIs(type(backend.requests[0].reference_date), datetime.date)


class BackendRetryControlTests(TestCase):
    def build_with(self, allow):
        built = mock.Mock()
        built.classify.return_value = output()
        with mock.patch(
            'entries.classification.openai_backend.build_openai_backend', return_value=built
        ) as build:
            classify(allow_backend_retry=allow)
        return build, built

    def test_retry_can_be_disabled_for_the_configured_backend(self):
        build, built = self.build_with(False)

        build.assert_called_once_with(max_retries=0)
        built.close.assert_called_once_with()

    def test_configured_retry_is_kept_by_default(self):
        build, _ = self.build_with(True)

        build.assert_called_once_with(max_retries=None)

    @override_settings(**FULL_SETTINGS)
    def test_disabled_retry_makes_exactly_one_provider_call(self):
        clock = FakeClock()
        transport = ScriptedTransport(clock, [(10.0, TIMEOUT), (1.0, ok())])
        real_build = openai_backend.build_openai_backend

        def build(**options):
            return real_build(
                client=make_client(transport), clock=clock, sleep=clock.sleep, **options
            )

        with mock.patch(
            'entries.classification.openai_backend.build_openai_backend', side_effect=build
        ):
            outcome = classify(allow_backend_retry=False)

        self.assertEqual(len(transport.requests), 1)
        self.assertEqual(outcome.outcome, FamilyOutcome.PROVIDER_UNAVAILABLE)
        self.assertEqual(outcome.reason, UnavailableReason.TIMEOUT)


class FamilyClassificationPrivacyTests(TestCase):
    SENSITIVE = (TEXT_SENTINEL, 'Łucja', 'Bartosz', 'Wycieczka')

    def test_results_hide_text_and_names(self):
        outcomes = [
            classify(RecordingBackend(output())),
            classify(RecordingBackend(output(entry_type=None))),
            classify(RecordingBackend(error=ClassificationBackendError(UnavailableReason.TIMEOUT))),
        ]

        text = repr(outcomes) + str(outcomes)
        for sensitive in self.SENSITIVE:
            self.assertNotIn(sensitive, text)

    @override_settings(**FULL_SETTINGS)
    def test_logs_hold_only_safe_operational_fields(self):
        clock = FakeClock()
        body = response_body(
            '{"entry_type": "note", "content": "Wycieczka %s", "grounded": true, '
            '"date": null, "time": null, "school_item": null, "member_name": "Łucja"}'
            % TEXT_SENTINEL
        )
        transport = ScriptedTransport(clock, [(1.0, ok(body))])
        real_build = openai_backend.build_openai_backend

        def build(**options):
            return real_build(
                client=make_client(transport), clock=clock, sleep=clock.sleep, **options
            )

        with mock.patch(
            'entries.classification.openai_backend.build_openai_backend', side_effect=build
        ), self.assertLogs(level=logging.DEBUG) as captured:
            outcome = classify(allow_backend_retry=False)

        self.assertEqual(outcome.outcome, FamilyOutcome.CLASSIFIED)
        rendered = '\n'.join(record.getMessage() for record in captured.records)
        rendered += ''.join(
            ''.join(traceback.format_exception(*record.exc_info))
            for record in captured.records
            if record.exc_info
        )
        for sensitive in self.SENSITIVE:
            self.assertNotIn(sensitive, rendered)
        (body_sent,) = transport.bodies()
        self.assertIs(body_sent['store'], False)
