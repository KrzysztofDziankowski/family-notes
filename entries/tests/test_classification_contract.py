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
SUBJECT_SENTINEL = 'SENTINEL-SUBJECT-9c41'
MENTION_SENTINEL = 'SENTINEL-MENTION-Hania-4e7a'


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
        school_subject='biologia',
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
        result = validate_output(make_request(), make_output(), require_school_subject=True)

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
            require_school_subject=True,
        )

        self.assertIsInstance(result, ClassificationProposal)
        self.assertIsNone(result.time)
        self.assertIsNone(result.member_name)

    def test_todo_without_date_needs_follow_up(self):
        result = validate_output(
            make_request(),
            make_output(
                entry_type=EntryType.TODO,
                school_item=None,
                date=None,
                member_name=None,
            ),
            require_school_subject=True,
        )

        self.assertIsInstance(result, ClassificationFollowUp)
        self.assertEqual(result.missing_fields, (MissingField.DATE,))
        self.assertEqual(result.entry_type, EntryType.TODO)

    def test_unrecognized_content_falls_back_to_general_note(self):
        request = make_request(text='  Pamiętać o kwiatach  ')
        result = validate_output(
            request,
            make_output(entry_type=None, content='', member_name='Unknown', grounded=False),
            require_school_subject=True,
        )

        self.assertIsInstance(result, ClassificationProposal)
        self.assertEqual(result.entry_type, EntryType.NOTE)
        self.assertEqual(result.content, 'Pamiętać o kwiatach')
        self.assertEqual(result.date, REFERENCE_DATE)
        self.assertIsNone(result.member_name)

    def test_calendar_event_without_date_needs_follow_up(self):
        result = validate_output(
            make_request(),
            make_output(school_item=None, member_name=None, date=None),
            require_school_subject=True,
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
            require_school_subject=True,
        )

        self.assertIsInstance(result, ClassificationFollowUp)
        self.assertEqual(result.missing_fields, (MissingField.AFFECTED_MEMBER,))
        self.assertEqual(result.date, MONDAY)

    def test_test_without_date_or_member_reports_both(self):
        result = validate_output(
            make_request(),
            make_output(date=None, member_name=None),
            require_school_subject=True,
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
            SchoolItemKind.SUBSTITUTION: ('zastępstwo', EntryType.CALENDAR_EVENT, date_only),
            SchoolItemKind.LATE_ARRIVAL: ('spóźnienie', EntryType.NOTE, ()),
            SchoolItemKind.ROOM_CHANGE: ('zmiana sali', EntryType.CALENDAR_EVENT, date_only),
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
        event_kinds = [k for k in SchoolItemKind if MissingField.AFFECTED_MEMBER in k.required_fields]
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
                    require_school_subject=True,
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
                    require_school_subject=True,
                )

                self.assertIsInstance(result, ClassificationProposal)
                self.assertEqual(result.entry_type, EntryType.NOTE)
                self.assertEqual(result.school_item, kind)

    def test_timetable_event_kinds_require_only_a_date(self):
        for kind in (SchoolItemKind.SUBSTITUTION, SchoolItemKind.ROOM_CHANGE):
            with self.subTest(kind=kind.value, date=None):
                result = validate_output(
                    make_request(),
                    make_output(school_item=kind, date=None, member_name=None),
                    require_school_subject=True,
                )

                self.assertIsInstance(result, ClassificationFollowUp)
                self.assertEqual(result.entry_type, EntryType.CALENDAR_EVENT)
                self.assertEqual(result.missing_fields, (MissingField.DATE,))

            with self.subTest(kind=kind.value, date=MONDAY):
                result = validate_output(
                    make_request(),
                    make_output(school_item=kind, member_name=None),
                    require_school_subject=True,
                )

                self.assertIsInstance(result, ClassificationProposal)
                self.assertEqual(result.entry_type, EntryType.CALENDAR_EVENT)
                self.assertEqual(result.date, MONDAY)

    def test_unknown_member_is_rejected(self):
        with self.assertRaises(ClassificationValidationError) as raised:
            validate_output(
                make_request(), make_output(member_name='Kasia'), require_school_subject=True
            )

        self.assertEqual(raised.exception.reason, UnavailableReason.UNKNOWN_MEMBER)

    def test_member_matching_preserves_case_and_spelling(self):
        for returned in ('michał', 'Michal', 'MICHAŁ'):
            with self.subTest(returned=returned):
                result = classify_output(
                    make_request(), make_output(member_name=returned), require_school_subject=True
                )
                self.assertEqual(
                    result,
                    ClassificationUnavailable(reason=UnavailableReason.UNKNOWN_MEMBER),
                )

    def test_member_matching_trims_unicode_whitespace(self):
        result = validate_output(
            make_request(names=('　Michał ', 'Ania')),
            make_output(member_name=' Michał '),
            require_school_subject=True,
        )

        self.assertIsInstance(result, ClassificationProposal)
        self.assertEqual(result.member_name, 'Michał')
        self.assertEqual(normalize_member_name(' Ania '), 'Ania')

    def test_duplicate_normalized_names_become_ambiguity_follow_up(self):
        result = validate_output(
            make_request(names=('Michał', ' Michał', 'Ania')),
            make_output(),
            require_school_subject=True,
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
            require_school_subject=True,
        )

        self.assertIsInstance(result, ClassificationFollowUp)
        self.assertEqual(result.missing_fields, (MissingField.AMBIGUOUS_MEMBER,))

    def test_empty_content_is_rejected(self):
        for content in ('', '   ', ' \n'):
            with self.subTest(content=content):
                result = classify_output(
                    make_request(), make_output(content=content), require_school_subject=True
                )
                self.assertEqual(
                    result,
                    ClassificationUnavailable(reason=UnavailableReason.EMPTY_CONTENT),
                )

    def test_ungrounded_output_is_rejected(self):
        result = classify_output(
            make_request(), make_output(grounded=False), require_school_subject=True
        )

        self.assertEqual(
            result,
            ClassificationUnavailable(reason=UnavailableReason.UNSUPPORTED_CONTENT),
        )

    def test_general_note_fallback_rejects_blank_submission(self):
        result = classify_output(
            make_request(text='  '), make_output(entry_type=None), require_school_subject=True
        )

        self.assertEqual(
            result,
            ClassificationUnavailable(reason=UnavailableReason.EMPTY_CONTENT),
        )

    def test_proposal_content_is_trimmed(self):
        result = validate_output(
            make_request(), make_output(content='  Test  '), require_school_subject=True
        )

        self.assertEqual(result.content, 'Test')


SCHOOL_EVENT_KINDS = (
    SchoolItemKind.HOMEWORK,
    SchoolItemKind.CLASS_TEST,
    SchoolItemKind.TEST,
    SchoolItemKind.QUIZ,
)


class SchoolSubjectValidationTests(SimpleTestCase):
    def test_missing_subject_is_a_follow_up_only_when_required(self):
        for kind in SCHOOL_EVENT_KINDS:
            for subject in (None, '', '   '):
                with self.subTest(kind=kind.value, subject=subject):
                    output = make_output(school_item=kind, school_subject=subject)

                    required = validate_output(
                        make_request(), output, require_school_subject=True
                    )
                    automated = validate_output(
                        make_request(), output, require_school_subject=False
                    )

                    self.assertIsInstance(required, ClassificationFollowUp)
                    self.assertEqual(required.missing_fields, (MissingField.SCHOOL_SUBJECT,))
                    self.assertIsInstance(automated, ClassificationProposal)
                    self.assertEqual(automated.school_item, kind)
                    self.assertEqual(automated.entry_type, EntryType.CALENDAR_EVENT)
                    self.assertIsNone(automated.school_subject)

    def test_subject_is_asked_after_date_and_member(self):
        result = validate_output(
            make_request(),
            make_output(date=None, member_name=None, school_subject=None),
            require_school_subject=True,
        )

        self.assertEqual(
            result.missing_fields,
            (MissingField.DATE, MissingField.AFFECTED_MEMBER, MissingField.SCHOOL_SUBJECT),
        )

    def test_subject_is_trimmed_and_passed_through(self):
        for required in (True, False):
            with self.subTest(required=required):
                proposal = validate_output(
                    make_request(),
                    make_output(school_subject='  matematyka \n'),
                    require_school_subject=required,
                )
                follow_up = validate_output(
                    make_request(),
                    make_output(member_name=None, school_subject=' historia '),
                    require_school_subject=required,
                )

                self.assertIsInstance(proposal, ClassificationProposal)
                self.assertEqual(proposal.school_subject, 'matematyka')
                self.assertIsInstance(follow_up, ClassificationFollowUp)
                self.assertEqual(follow_up.school_subject, 'historia')

    def test_over_long_subject_is_dropped(self):
        output = make_output(school_subject='x' * 101)

        required = validate_output(make_request(), output, require_school_subject=True)
        automated = validate_output(make_request(), output, require_school_subject=False)

        self.assertEqual(required.missing_fields, (MissingField.SCHOOL_SUBJECT,))
        self.assertIsNone(required.school_subject)
        self.assertIsInstance(automated, ClassificationProposal)
        self.assertIsNone(automated.school_subject)

    def test_subject_is_never_required_for_other_entries(self):
        cases = {
            'grade': make_output(
                entry_type=EntryType.NOTE, school_item=SchoolItemKind.GRADE, date=None
            ),
            'substitution': make_output(
                entry_type=EntryType.NOTE, school_item=SchoolItemKind.SUBSTITUTION
            ),
            'plain event': make_output(school_item=None),
            'todo': make_output(entry_type=EntryType.TODO, school_item=None),
        }
        for name, output in cases.items():
            with self.subTest(name):
                result = validate_output(
                    make_request(),
                    BackendOutput(**{**output.__dict__, 'school_subject': None}),
                    require_school_subject=True,
                )
                self.assertIsInstance(result, ClassificationProposal)

    def test_classify_output_requires_the_gate_keyword(self):
        with self.assertRaises(TypeError):
            classify_output(make_request(), make_output())
        with self.assertRaises(TypeError):
            validate_output(make_request(), make_output())


class AmbiguousMemberValidationTests(SimpleTestCase):
    """A locally detected ambiguous mention becomes the member clarification."""

    def test_school_event_asks_which_member_and_names_nobody(self):
        result = validate_output(
            make_request(),
            make_output(member_name=None, member_ambiguous=True),
            require_school_subject=True,
        )

        self.assertIsInstance(result, ClassificationFollowUp)
        self.assertEqual(
            result.missing_fields,
            (MissingField.AMBIGUOUS_MEMBER, MissingField.AFFECTED_MEMBER),
        )
        self.assertIsNone(result.member_name)

    def test_ambiguity_wins_over_a_stale_allow_listed_name(self):
        result = validate_output(
            make_request(),
            make_output(member_name='Michał', member_ambiguous=True),
            require_school_subject=True,
        )

        self.assertIsInstance(result, ClassificationFollowUp)
        self.assertIn(MissingField.AMBIGUOUS_MEMBER, result.missing_fields)
        self.assertIsNone(result.member_name)

    def test_every_recognized_entry_type_asks_for_the_member(self):
        for entry_type in EntryType:
            with self.subTest(entry_type=entry_type.value):
                result = validate_output(
                    make_request(),
                    make_output(
                        entry_type=entry_type,
                        school_item=None,
                        member_name=None,
                        member_ambiguous=True,
                    ),
                    require_school_subject=True,
                )

                self.assertIsInstance(result, ClassificationFollowUp)
                self.assertEqual(result.missing_fields, (MissingField.AMBIGUOUS_MEMBER,))
                self.assertIsNone(result.member_name)

    def test_unrecognized_entry_type_stays_a_general_note(self):
        result = validate_output(
            make_request(),
            make_output(entry_type=None, member_name=None, member_ambiguous=True),
            require_school_subject=True,
        )

        self.assertIsInstance(result, ClassificationProposal)
        self.assertEqual(result.entry_type, EntryType.NOTE)
        self.assertIsNone(result.member_name)

    def test_mention_alone_does_not_change_validation(self):
        result = validate_output(
            make_request(),
            make_output(member_mention='Misiek'),
            require_school_subject=True,
        )

        self.assertIsInstance(result, ClassificationProposal)
        self.assertEqual(result.member_name, 'Michał')


class SensitiveRepresentationTests(SimpleTestCase):
    def sensitive_request(self):
        return make_request(
            text=f'{SUBMITTED_SENTINEL} {MEMBER_SENTINEL} test',
            names=(MEMBER_SENTINEL, MEMBER_SENTINEL, 'Ania'),
        )

    def sensitive_output(self, **overrides):
        values = dict(
            content=CONTENT_SENTINEL,
            member_name=MEMBER_SENTINEL,
            school_subject=SUBJECT_SENTINEL,
            member_mention=MENTION_SENTINEL,
        )
        values.update(overrides)
        return make_output(**values)

    def assert_safe(self, text):
        for sentinel in (
            SUBMITTED_SENTINEL, CONTENT_SENTINEL, MEMBER_SENTINEL, SUBJECT_SENTINEL,
            MENTION_SENTINEL, 'Michał',
        ):
            self.assertNotIn(sentinel, text)

    def test_request_and_output_representations_are_safe(self):
        self.assert_safe(repr(self.sensitive_request()))
        self.assert_safe(str(self.sensitive_request()))
        self.assert_safe(repr(self.sensitive_output()))

    def test_result_representations_are_safe(self):
        request = make_request(names=(MEMBER_SENTINEL, 'Ania'))
        proposal = validate_output(
            request, self.sensitive_output(), require_school_subject=True
        )
        follow_up = validate_output(
            self.sensitive_request(), self.sensitive_output(), require_school_subject=True
        )
        note = validate_output(
            self.sensitive_request(), make_output(entry_type=None), require_school_subject=True
        )

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
                    validate_output(self.sensitive_request(), output, require_school_subject=True)
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


class DateMeaningTests(SimpleTestCase):
    def test_new_note_uses_writing_day_instead_of_provider_occurrence_day(self):
        result = validate_output(make_request(), make_output(entry_type=EntryType.NOTE, school_item=None), require_school_subject=True)
        self.assertEqual(result.date, REFERENCE_DATE)

    def test_type_specific_follow_up_questions(self):
        from entries.classification.follow_up import follow_up_question

        expected = {
            EntryType.CALENDAR_EVENT: 'Kiedy odbędzie się „Spotkanie”?',
            EntryType.TODO: 'Na kiedy trzeba wykonać „Spotkanie”?',
            EntryType.NOTE: 'Kiedy zapisano „Spotkanie”?',
        }
        for entry_type, question in expected.items():
            with self.subTest(entry_type=entry_type):
                draft = ClassificationFollowUp(missing_fields=(MissingField.DATE,), entry_type=entry_type, content='Spotkanie')
                self.assertEqual(follow_up_question(draft), question)
