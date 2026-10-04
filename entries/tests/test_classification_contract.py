import datetime
import traceback

from django.apps import apps
from django.test import SimpleTestCase

from entries.classification.backends import (
    BackendOutput,
    BackendRequest,
    ClassificationBackend,
    ClassificationBackendError,
)
from entries.classification.types import (
    ClassificationError,
    ClassificationFollowUp,
    ClassificationProposal,
    ClassificationUnavailable,
    EntryType,
    MissingField,
    SchoolItemKind,
    UnavailableReason,
)
from entries.classification.validation import (
    ClassificationValidationError,
    classify_output,
    normalize_member_name,
    validate_output,
)

REFERENCE_DATE = datetime.date(2026, 9, 17)
MONDAY = datetime.date(2026, 9, 21)
SUBMITTED_SENTINEL = 'SENTINEL-SUBMITTED-7f3a9c'
CONTENT_SENTINEL = 'SENTINEL-CONTENT-b81e44'
MEMBER_SENTINEL = 'SENTINEL-MEMBER-Michał-5d02'


def make_request(text='Michał ma sprawdzian z biologii w poniedziałek', names=('Michał', 'Ania')):
    return BackendRequest(
        submitted_text=text,
        allowed_member_names=names,
        reference_date=REFERENCE_DATE,
        locale='pl-PL',
    )


def make_output(**overrides):
    values = dict(
        entry_type=EntryType.CALENDAR_EVENT,
        content='Biology test about the skin',
        grounded=True,
        date=MONDAY,
        school_item=SchoolItemKind.TEST,
        member_name='Michał',
    )
    values.update(overrides)
    return BackendOutput(**values)


class EntriesAppTests(SimpleTestCase):
    def test_entries_app_is_installed_with_only_the_entry_model(self):
        config = apps.get_app_config('entries')

        self.assertEqual(config.name, 'entries')
        self.assertEqual(
            [model.__name__ for model in config.get_models()],
            [
                'Entry',
                'InboundNotification',
                'NotificationConversionOutput',
                'ConversionWorkerHeartbeat',
            ],
        )

    def test_entry_type_values(self):
        self.assertEqual(
            [entry_type.value for entry_type in EntryType],
            ['todo', 'calendar_event', 'note'],
        )

    def test_result_kinds_are_distinct_discriminators(self):
        proposal = ClassificationProposal(entry_type=EntryType.NOTE, content='x')
        follow_up = ClassificationFollowUp(
            missing_fields=(MissingField.DATE,),
            entry_type=EntryType.CALENDAR_EVENT,
            content='x',
        )
        unavailable = ClassificationUnavailable(reason=UnavailableReason.TIMEOUT)

        self.assertEqual(
            [proposal.kind, follow_up.kind, unavailable.kind],
            ['proposal', 'follow_up', 'unavailable'],
        )

    def test_backend_protocol_accepts_provider_neutral_fake(self):
        class FakeBackend:
            def classify(self, request):
                return make_output()

        backend = FakeBackend()

        self.assertIsInstance(backend, ClassificationBackend)
        self.assertIsInstance(backend.classify(make_request()), BackendOutput)

    def test_request_freezes_allowed_names(self):
        names = ['Michał']
        request = make_request(names=names)
        names.append('Intruder')

        self.assertEqual(request.allowed_member_names, ('Michał',))


class ValidationTests(SimpleTestCase):
    def test_complete_school_test_becomes_proposal(self):
        result = validate_output(make_request(), make_output())

        self.assertIsInstance(result, ClassificationProposal)
        self.assertEqual(result.entry_type, EntryType.CALENDAR_EVENT)
        self.assertEqual(result.content, 'Biology test about the skin')
        self.assertEqual(result.date, MONDAY)
        self.assertEqual(result.school_item, SchoolItemKind.TEST)
        self.assertEqual(result.member_name, 'Michał')

    def test_calendar_event_without_time_or_member_is_complete(self):
        result = validate_output(
            make_request(),
            make_output(school_item=None, member_name=None),
        )

        self.assertIsInstance(result, ClassificationProposal)
        self.assertIsNone(result.time)
        self.assertIsNone(result.member_name)

    def test_todo_without_date_is_complete(self):
        result = validate_output(
            make_request(),
            make_output(
                entry_type=EntryType.TODO,
                school_item=None,
                date=None,
                member_name=None,
            ),
        )

        self.assertIsInstance(result, ClassificationProposal)
        self.assertEqual(result.entry_type, EntryType.TODO)

    def test_unrecognized_content_falls_back_to_general_note(self):
        request = make_request(text='  Pamiętać o kwiatach  ')
        result = validate_output(
            request,
            make_output(entry_type=None, content='', member_name='Unknown', grounded=False),
        )

        self.assertIsInstance(result, ClassificationProposal)
        self.assertEqual(result.entry_type, EntryType.NOTE)
        self.assertEqual(result.content, 'Pamiętać o kwiatach')
        self.assertIsNone(result.date)
        self.assertIsNone(result.member_name)

    def test_calendar_event_without_date_needs_follow_up(self):
        result = validate_output(
            make_request(),
            make_output(school_item=None, member_name=None, date=None),
        )

        self.assertIsInstance(result, ClassificationFollowUp)
        self.assertEqual(result.missing_fields, (MissingField.DATE,))

    def test_homework_without_member_needs_follow_up(self):
        result = validate_output(
            make_request(),
            make_output(
                entry_type=EntryType.TODO,
                school_item=SchoolItemKind.HOMEWORK,
                member_name=None,
            ),
        )

        self.assertIsInstance(result, ClassificationFollowUp)
        self.assertEqual(result.missing_fields, (MissingField.AFFECTED_MEMBER,))
        self.assertEqual(result.date, MONDAY)

    def test_test_without_date_or_member_reports_both(self):
        result = validate_output(
            make_request(),
            make_output(date=None, member_name=None),
        )

        self.assertIsInstance(result, ClassificationFollowUp)
        self.assertEqual(
            result.missing_fields,
            (MissingField.DATE, MissingField.AFFECTED_MEMBER),
        )

    def test_school_kinds_define_labels_entry_types_and_required_fields(self):
        school_event = (
            MissingField.DATE, MissingField.AFFECTED_MEMBER, MissingField.SCHOOL_SUBJECT,
        )
        date_only = (MissingField.DATE,)
        expected = {
            SchoolItemKind.HOMEWORK: ('zadanie domowe', EntryType.CALENDAR_EVENT, school_event),
            SchoolItemKind.CLASS_TEST: ('praca klasowa', EntryType.CALENDAR_EVENT, school_event),
            SchoolItemKind.TEST: ('sprawdzian', EntryType.CALENDAR_EVENT, school_event),
            SchoolItemKind.QUIZ: ('kartkówka', EntryType.CALENDAR_EVENT, school_event),
            SchoolItemKind.LUCKY_NUMBER: ('szczęśliwy numerek', EntryType.NOTE, ()),
            SchoolItemKind.GRADE: ('ocena', EntryType.NOTE, ()),
            SchoolItemKind.SUBSTITUTION: ('zastępstwo', EntryType.NOTE, date_only),
            SchoolItemKind.LATE_ARRIVAL: ('spóźnienie', EntryType.NOTE, ()),
            SchoolItemKind.ROOM_CHANGE: ('zmiana sali', EntryType.NOTE, date_only),
        }

        self.assertEqual(set(SchoolItemKind), set(expected))
        for kind, (label, entry_type, required_fields) in expected.items():
            with self.subTest(kind=kind.value):
                self.assertEqual(kind.label, label)
                self.assertEqual(kind.entry_type, entry_type)
                self.assertEqual(kind.required_fields, required_fields)
                self.assertEqual(SchoolItemKind(kind.value), kind)

    def test_only_the_four_school_event_kinds_require_a_subject(self):
        requiring = {
            kind for kind in SchoolItemKind if MissingField.SCHOOL_SUBJECT in kind.required_fields
        }

        self.assertEqual(
            requiring,
            {
                SchoolItemKind.HOMEWORK,
                SchoolItemKind.CLASS_TEST,
                SchoolItemKind.TEST,
                SchoolItemKind.QUIZ,
            },
        )
        self.assertEqual(MissingField.SCHOOL_SUBJECT.value, 'school_subject')

    def test_event_kinds_require_date_and_member_as_calendar_events(self):
        event_kinds = [k for k in SchoolItemKind if k.entry_type == EntryType.CALENDAR_EVENT]
        for kind in event_kinds:
            with self.subTest(kind=kind.value):
                result = validate_output(
                    make_request(),
                    make_output(
                        entry_type=EntryType.TODO,
                        school_item=kind,
                        date=None,
                        member_name=None,
                    ),
                )

                self.assertIsInstance(result, ClassificationFollowUp)
                self.assertEqual(result.entry_type, EntryType.CALENDAR_EVENT)
                self.assertEqual(
                    result.missing_fields,
                    (MissingField.DATE, MissingField.AFFECTED_MEMBER),
                )

    def test_note_kinds_without_required_fields_become_notes(self):
        for kind in (
            SchoolItemKind.LUCKY_NUMBER,
            SchoolItemKind.GRADE,
            SchoolItemKind.LATE_ARRIVAL,
        ):
            with self.subTest(kind=kind.value):
                result = validate_output(
                    make_request(),
                    make_output(
                        entry_type=EntryType.CALENDAR_EVENT,
                        school_item=kind,
                        date=None,
                        member_name=None,
                    ),
                )

                self.assertIsInstance(result, ClassificationProposal)
                self.assertEqual(result.entry_type, EntryType.NOTE)
                self.assertEqual(result.school_item, kind)

    def test_dated_note_kinds_require_only_a_date(self):
        for kind in (SchoolItemKind.SUBSTITUTION, SchoolItemKind.ROOM_CHANGE):
            with self.subTest(kind=kind.value, date=None):
                result = validate_output(
                    make_request(),
                    make_output(school_item=kind, date=None, member_name=None),
                )

                self.assertIsInstance(result, ClassificationFollowUp)
                self.assertEqual(result.entry_type, EntryType.NOTE)
                self.assertEqual(result.missing_fields, (MissingField.DATE,))

            with self.subTest(kind=kind.value, date=MONDAY):
                result = validate_output(
                    make_request(),
                    make_output(school_item=kind, member_name=None),
                )

                self.assertIsInstance(result, ClassificationProposal)
                self.assertEqual(result.entry_type, EntryType.NOTE)
                self.assertEqual(result.date, MONDAY)

    def test_unknown_member_is_rejected(self):
        with self.assertRaises(ClassificationValidationError) as raised:
            validate_output(make_request(), make_output(member_name='Kasia'))

        self.assertEqual(raised.exception.reason, UnavailableReason.UNKNOWN_MEMBER)

    def test_member_matching_preserves_case_and_spelling(self):
        for returned in ('michał', 'Michal', 'MICHAŁ'):
            with self.subTest(returned=returned):
                result = classify_output(make_request(), make_output(member_name=returned))
                self.assertEqual(
                    result,
                    ClassificationUnavailable(reason=UnavailableReason.UNKNOWN_MEMBER),
                )

    def test_member_matching_trims_unicode_whitespace(self):
        result = validate_output(
            make_request(names=('　Michał ', 'Ania')),
            make_output(member_name=' Michał '),
        )

        self.assertIsInstance(result, ClassificationProposal)
        self.assertEqual(result.member_name, 'Michał')
        self.assertEqual(normalize_member_name(' Ania '), 'Ania')

    def test_duplicate_normalized_names_become_ambiguity_follow_up(self):
        result = validate_output(
            make_request(names=('Michał', ' Michał', 'Ania')),
            make_output(),
        )

        self.assertIsInstance(result, ClassificationFollowUp)
        self.assertEqual(result.missing_fields, (MissingField.AMBIGUOUS_MEMBER,))
        self.assertIsNone(result.member_name)

    def test_duplicate_names_on_note_still_do_not_resolve(self):
        result = validate_output(
            make_request(names=('Ania', 'Ania')),
            make_output(
                entry_type=EntryType.NOTE,
                school_item=None,
                date=None,
                member_name='Ania',
            ),
        )

        self.assertIsInstance(result, ClassificationFollowUp)
        self.assertEqual(result.missing_fields, (MissingField.AMBIGUOUS_MEMBER,))

    def test_empty_content_is_rejected(self):
        for content in ('', '   ', ' \n'):
            with self.subTest(content=content):
                result = classify_output(make_request(), make_output(content=content))
                self.assertEqual(
                    result,
                    ClassificationUnavailable(reason=UnavailableReason.EMPTY_CONTENT),
                )

    def test_ungrounded_output_is_rejected(self):
        result = classify_output(make_request(), make_output(grounded=False))

        self.assertEqual(
            result,
            ClassificationUnavailable(reason=UnavailableReason.UNSUPPORTED_CONTENT),
        )

    def test_general_note_fallback_rejects_blank_submission(self):
        result = classify_output(make_request(text='  '), make_output(entry_type=None))

        self.assertEqual(
            result,
            ClassificationUnavailable(reason=UnavailableReason.EMPTY_CONTENT),
        )

    def test_proposal_content_is_trimmed(self):
        result = validate_output(make_request(), make_output(content='  Test  '))

        self.assertEqual(result.content, 'Test')


class SensitiveRepresentationTests(SimpleTestCase):
    def sensitive_request(self):
        return make_request(
            text=f'{SUBMITTED_SENTINEL} {MEMBER_SENTINEL} test',
            names=(MEMBER_SENTINEL, MEMBER_SENTINEL, 'Ania'),
        )

    def sensitive_output(self, **overrides):
        values = dict(content=CONTENT_SENTINEL, member_name=MEMBER_SENTINEL)
        values.update(overrides)
        return make_output(**values)

    def assert_safe(self, text):
        for sentinel in (SUBMITTED_SENTINEL, CONTENT_SENTINEL, MEMBER_SENTINEL, 'Michał'):
            self.assertNotIn(sentinel, text)

    def test_request_and_output_representations_are_safe(self):
        self.assert_safe(repr(self.sensitive_request()))
        self.assert_safe(str(self.sensitive_request()))
        self.assert_safe(repr(self.sensitive_output()))

    def test_result_representations_are_safe(self):
        request = make_request(names=(MEMBER_SENTINEL, 'Ania'))
        proposal = validate_output(request, self.sensitive_output())
        follow_up = validate_output(self.sensitive_request(), self.sensitive_output())
        note = validate_output(self.sensitive_request(), make_output(entry_type=None))

        self.assertIsInstance(proposal, ClassificationProposal)
        self.assertIsInstance(follow_up, ClassificationFollowUp)
        self.assertEqual(note.content, f'{SUBMITTED_SENTINEL} {MEMBER_SENTINEL} test')
        for result in (proposal, follow_up, note):
            with self.subTest(kind=result.kind):
                self.assert_safe(repr(result))
                self.assert_safe(str(result))

    def test_validation_exception_representations_are_safe(self):
        failing_outputs = (
            self.sensitive_output(member_name=f'{MEMBER_SENTINEL}-unknown'),
            self.sensitive_output(grounded=False),
            self.sensitive_output(content=' '),
        )
        for output in failing_outputs:
            with self.subTest(output=output):
                with self.assertRaises(ClassificationValidationError) as raised:
                    validate_output(self.sensitive_request(), output)
                error = raised.exception
                self.assert_safe(repr(error))
                self.assert_safe(str(error))
                self.assert_safe(repr(error.args))
                self.assert_safe(''.join(traceback.format_exception_only(type(error), error)))
                self.assert_safe(repr(error.to_result()))

    def test_errors_accept_only_safe_reason_codes(self):
        payload = f'{{"output": "{SUBMITTED_SENTINEL}"}}'

        with self.assertRaises(TypeError) as raised:
            ClassificationBackendError(payload)

        self.assertNotIn(SUBMITTED_SENTINEL, str(raised.exception))
        error = ClassificationBackendError(UnavailableReason.PROVIDER_ERROR)
        self.assertIsInstance(error, ClassificationError)
        self.assertEqual(str(error), 'provider_error')
        self.assertEqual(error.args, ('provider_error',))
        self.assertEqual(
            error.to_result(),
            ClassificationUnavailable(reason=UnavailableReason.PROVIDER_ERROR),
        )

    def test_result_types_have_no_raw_payload_fields(self):
        from dataclasses import fields

        for result_type in (
            ClassificationProposal,
            ClassificationFollowUp,
            ClassificationUnavailable,
            BackendOutput,
        ):
            with self.subTest(result_type=result_type.__name__):
                names = {f.name for f in fields(result_type)}
                self.assertFalse(names & {'raw', 'payload', 'response', 'raw_response'})
