import datetime
import logging
import uuid
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.test import TestCase, override_settings
from django.urls import reverse

from entries.classification.openai_backend import OpenAIClassificationBackend
from entries.classification.service import (
    MAX_SUBMITTED_TEXT_LENGTH,
    ParentBatchClassification,
    ParentClassification,
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
from entries.models import Entry
from family_access.models import FamilyMember

from .classification_progress_markup import (
    SCRIPT_URL as PROGRESS_SCRIPT_URL,
    assert_progress_regions,
    classification_submitters,
    progress_forms,
)
from .enter_submit_markup import SCRIPT_URL as ENTER_SCRIPT_URL
from .enter_submit_markup import assert_enter_assets
from .field_association_markup import assert_described_by
from .test_classification_acceptance import (
    PRD_CONTENT,
    PRD_INSTRUCTION,
    PRD_MONDAY,
    PRD_REFERENCE_DATE,
    model_entry_output,
)
from .test_classification_service import FamilyFixtureMixin, TwoParentFixtureMixin
from .test_openai_backend import MODEL, FakeClock, ScriptedTransport, make_client

CAPTURE_URL = reverse('entries:capture')
CONFIRM_URL = reverse('entries:confirm')
SENTINEL_TEXT = 'SENTINEL-INSTRUKCJA-7c1e Michał ma w poniedziałek sprawdzian'


class CaptureViewMixin(FamilyFixtureMixin):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.parent.user)

    def classify_with(self, result, member=None, text='Michał ma sprawdzian'):
        outcome = ParentClassification(result=result, member=member)
        batch = ParentBatchClassification(items=(outcome,))
        with mock.patch('entries.views.classify_entries_for_parent', return_value=batch) as classify:
            response = self.client.post(CAPTURE_URL, {'text': text})
        return response, classify

    def proposal(self, **overrides):
        values = dict(
            entry_type=EntryType.CALENDAR_EVENT,
            content=PRD_CONTENT,
            date=PRD_MONDAY,
            school_item=SchoolItemKind.TEST,
            member_name='michał',
            school_subject='biologia',
        )
        values.update(overrides)
        return ClassificationProposal(**values)

    def confirm_data(self, **overrides):
        data = {
            'entry_type': EntryType.CALENDAR_EVENT.value,
            'content': PRD_CONTENT,
            'date': PRD_MONDAY.isoformat(),
            'time': '',
            'assigned_member': str(self.child.pk),
            'school_item': SchoolItemKind.TEST.value,
            'school_subject': 'biologia',
            'submission_key': str(uuid.uuid4()),
        }
        data.update(overrides)
        return data


class AccessMatrixTests(CaptureViewMixin, TestCase):
    def test_anonymous_is_redirected_to_login(self):
        self.client.logout()
        with mock.patch('entries.views.classify_entries_for_parent') as classify:
            for method, url in (('get', CAPTURE_URL), ('post', CAPTURE_URL), ('post', CONFIRM_URL)):
                with self.subTest(method=method, url=url):
                    response = getattr(self.client, method)(url, {'text': 'x'})
                    self.assertEqual(response.status_code, 302)
                    self.assertIn(reverse('account_login'), response['Location'])
        classify.assert_not_called()
        self.assertFalse(Entry.objects.exists())

    def test_non_parents_get_403_on_both_views(self):
        unconfigured = get_user_model().objects.create_user(username='unconfigured')

        def inactive_parent():
            self.parent.is_active = False
            self.parent.save(update_fields=('is_active',))
            return self.parent.user

        cases = {
            'child': lambda: self.child.user,
            'no membership': lambda: unconfigured,
            'inactive parent': inactive_parent,
        }
        with mock.patch('entries.views.classify_entries_for_parent') as classify:
            for name, get_user in cases.items():
                self.client.force_login(get_user())
                for method, url, data in (
                    ('get', CAPTURE_URL, {}),
                    ('post', CAPTURE_URL, {'text': 'x'}),
                    ('post', CONFIRM_URL, self.confirm_data()),
                ):
                    with self.subTest(name, method=method, url=url):
                        response = getattr(self.client, method)(url, data)
                        self.assertEqual(response.status_code, 403)
        classify.assert_not_called()
        self.assertFalse(Entry.objects.exists())

    def test_get_confirm_is_not_allowed(self):
        self.assertEqual(self.client.get(CONFIRM_URL).status_code, 405)

    def test_parent_sees_empty_capture_form(self):
        response = self.client.get(CAPTURE_URL)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['state'], 'empty')
        self.assertContains(response, 'Co trzeba zapisać?')
        self.assertContains(response, 'Rozpoznaj')
        self.assertTemplateUsed(response, 'base.html')


class Us01AcceptanceTests(CaptureViewMixin, TestCase):
    """US-01 end to end through the real service and adapter, scripted transport."""

    def test_classify_review_confirm_and_see_saved_entry(self):
        clock = FakeClock()
        transport = ScriptedTransport(
            clock,
            [
                model_entry_output(
                    entry_type='calendar_event',
                    content=PRD_CONTENT,
                    date=PRD_MONDAY.isoformat(),
                    date_source='w poniedziałek',
                    school_item='test',
                    member_name='Michał',
                    school_subject='biologia',
                )
            ],
        )
        backend = OpenAIClassificationBackend(
            client=make_client(transport), model=MODEL, clock=clock, sleep=clock.sleep
        )

        with mock.patch(
            'entries.views.timezone.localdate', return_value=PRD_REFERENCE_DATE
        ), mock.patch(
            'entries.classification.openai_backend.build_openai_backend', return_value=backend
        ):
            review = self.client.post(CAPTURE_URL, {'text': PRD_INSTRUCTION})

        self.assertEqual(review.context['state'], 'proposal')
        self.assertIn(PRD_REFERENCE_DATE.isoformat(), transport.bodies()[0]['input'])
        form = review.context['review_form']
        self.assertEqual(form.initial['assigned_member'], self.child.pk)
        self.assertContains(review, f'<option value="{self.child.pk}" selected>Michał</option>', html=True)
        self.assertContains(review, 'value="2026-09-21"')
        self.assertContains(review, 'poniedziałek, 21 września 2026')
        self.assertContains(review, PRD_CONTENT)
        self.assertEqual(form.initial['school_subject'], 'biologia')
        self.assertContains(review, 'value="biologia"')

        data = {
            name: '' if value is None else str(value)
            for name, value in form.initial.items()
        }
        confirmed = self.client.post(CONFIRM_URL, data)

        entry = Entry.objects.get()
        self.assertRedirects(confirmed, f'{CAPTURE_URL}?saved={entry.pk}')
        self.assertEqual(entry.entry_type, 'calendar_event')
        self.assertEqual(entry.assigned_member, self.child)
        self.assertEqual(entry.date, PRD_MONDAY)
        self.assertEqual(entry.source, Entry.Source.MANUAL)

        saved = self.client.get(confirmed['Location'])
        self.assertEqual(saved.context['state'], 'saved')
        self.assertContains(saved, 'Dodano wpis')
        self.assertContains(saved, PRD_CONTENT)
        self.assertContains(saved, 'poniedziałek, 21 września 2026')
        self.assertContains(saved, 'Michał')
        self.assertContains(saved, 'Co trzeba zapisać?')


class ShortNameCaptureTests(CaptureViewMixin, TestCase):
    """PK-01 through the real view, service and adapter, scripted transport."""

    INSTRUCTION = 'Hania ma jutro dentystę'
    TOMORROW = PRD_REFERENCE_DATE + datetime.timedelta(days=1)

    def setUp(self):
        super().setUp()
        # "Ania" shares the Anna group with "Hania"; keep her out of the way.
        self.other_child.display_name = 'Ola'
        self.other_child.save(update_fields=('display_name',))
        self.hanna = self._member('hanna', FamilyMember.Role.CHILD, 'Hanna')

    def capture(self, member_name=None):
        clock = FakeClock()
        transport = ScriptedTransport(
            clock,
            [
                model_entry_output(
                    entry_type='calendar_event',
                    content='Dentysta',
                    date=self.TOMORROW.isoformat(),
                    date_source='jutro',
                    member_name=member_name,
                    member_mention='Hania',
                )
            ],
        )
        backend = OpenAIClassificationBackend(
            client=make_client(transport), model=MODEL, clock=clock, sleep=clock.sleep
        )
        with mock.patch(
            'entries.views.timezone.localdate', return_value=PRD_REFERENCE_DATE
        ), mock.patch(
            'entries.classification.openai_backend.build_openai_backend', return_value=backend
        ):
            return self.client.post(CAPTURE_URL, {'text': self.INSTRUCTION})

    def test_unique_short_name_preselects_the_member_and_confirm_saves_her(self):
        review = self.capture()

        self.assertEqual(review.context['state'], 'proposal')
        form = review.context['review_form']
        self.assertEqual(form.initial['assigned_member'], self.hanna.pk)
        self.assertContains(
            review, f'<option value="{self.hanna.pk}" selected>Hanna</option>', html=True
        )

        data = {name: '' if value is None else str(value) for name, value in form.initial.items()}
        self.client.post(CONFIRM_URL, data)

        entry = Entry.objects.get()
        self.assertEqual(entry.assigned_member, self.hanna)
        self.assertEqual(entry.date, self.TOMORROW)

    def test_ambiguous_short_name_asks_which_person_with_no_assignee(self):
        self._member('anna', FamilyMember.Role.CHILD, 'Anna')

        response = self.capture(member_name='Hanna')

        self.assertEqual(response.context['state'], 'question')
        self.assertNotIn('review_form', response.context)
        self.assertContains(response, 'Której osoby dotyczy „Dentysta”?')
        form = response.context['follow_up_form']
        self.assertIsNone(form.initial['assigned_member'])
        self.assertEqual(form.initial['missing'], ['ambiguous_member'])
        self.assertFalse(Entry.objects.exists())


class CorrectionAndValidationTests(CaptureViewMixin, TestCase):
    def test_corrected_values_are_saved(self):
        self.client.post(
            CONFIRM_URL,
            self.confirm_data(
                entry_type=EntryType.TODO.value,
                content='Poprawiony tytuł',
                date='2026-09-22',
                assigned_member=str(self.other_child.pk),
                school_item='',
                school_subject='',
            ),
        )

        entry = Entry.objects.get()
        self.assertEqual(entry.entry_type, 'todo')
        self.assertEqual(entry.content, 'Poprawiony tytuł')
        self.assertEqual(entry.date, datetime.date(2026, 9, 22))
        self.assertEqual(entry.assigned_member, self.other_child)
        self.assertEqual(entry.school_item, '')

    def test_foreign_or_inactive_member_is_a_form_error(self):
        for member in (self.other_family_child, self.inactive_child):
            with self.subTest(member=member.display_name):
                response = self.client.post(
                    CONFIRM_URL, self.confirm_data(assigned_member=str(member.pk))
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context['state'], 'invalid')
                self.assertIn('assigned_member', response.context['review_form'].errors)
        self.assertFalse(Entry.objects.exists())

    def test_calendar_event_without_date_is_an_error(self):
        response = self.client.post(CONFIRM_URL, self.confirm_data(date='', school_item=''))

        self.assertContains(response, 'Wydarzenie musi mieć datę.')
        self.assertContains(response, 'aria-invalid="true"')
        self.assertFalse(Entry.objects.exists())

    def test_school_item_without_member_is_an_error_while_type_matches(self):
        response = self.client.post(CONFIRM_URL, self.confirm_data(assigned_member=''))

        self.assertIn('assigned_member', response.context['review_form'].errors)
        self.assertFalse(Entry.objects.exists())

    def test_school_item_type_mismatch_is_an_error_not_cleared(self):
        response = self.client.post(
            CONFIRM_URL,
            self.confirm_data(entry_type=EntryType.NOTE.value, assigned_member='', date=''),
        )

        self.assertEqual(response.context['state'], 'invalid')
        self.assertContains(response, 'Ten element szkolny wymaga rodzaju „Wydarzenie”.')
        self.assertFalse(Entry.objects.exists())

    def test_clearing_the_school_item_saves_without_a_subject(self):
        self.client.post(
            CONFIRM_URL,
            self.confirm_data(school_item='', school_subject=''),
        )

        entry = Entry.objects.get()
        self.assertEqual(entry.entry_type, 'calendar_event')
        self.assertEqual(entry.school_item, '')
        self.assertEqual(entry.school_subject, '')

    def test_school_event_without_subject_is_an_error(self):
        for kind in ('homework', 'class_test', 'test', 'quiz'):
            with self.subTest(kind=kind):
                response = self.client.post(
                    CONFIRM_URL, self.confirm_data(school_item=kind, school_subject='  ')
                )

                self.assertEqual(response.context['state'], 'invalid')
                self.assertContains(response, 'Podaj przedmiot.')
                self.assertIn('school_subject', response.context['review_form'].errors)
        self.assertFalse(Entry.objects.exists())

    def test_confirm_saves_the_stripped_subject(self):
        self.client.post(CONFIRM_URL, self.confirm_data(school_subject='  Biologia  '))

        entry = Entry.objects.get()
        self.assertEqual(entry.school_subject, 'Biologia')

    def test_review_shows_visible_school_item_and_subject(self):
        response, _ = self.classify_with(
            self.proposal(school_subject='biologia'), member=self.child
        )

        self.assertContains(response, '<label for="id_school_item">Element szkolny</label>', html=True)
        self.assertContains(response, '<option value="test" selected>sprawdzian</option>', html=True)
        self.assertContains(response, '<label for="id_school_subject">Przedmiot</label>', html=True)
        self.assertContains(response, 'value="biologia"')
        self.assertNotContains(response, 'type="hidden" name="school_item"')

    def test_invalid_review_keeps_submission_key(self):
        data = self.confirm_data(date='', school_item='')

        response = self.client.post(CONFIRM_URL, data)

        self.assertContains(response, data['submission_key'])


class FollowUpAndUnavailableTests(CaptureViewMixin, TestCase):
    def test_follow_up_asks_a_question_instead_of_a_review_form(self):
        response, _ = self.classify_with(
            ClassificationFollowUp(
                missing_fields=(MissingField.DATE,),
                entry_type=EntryType.CALENDAR_EVENT,
                content=PRD_CONTENT,
                school_item=SchoolItemKind.TEST,
                member_name='michał',
            ),
            member=self.child,
        )

        self.assertEqual(response.context['state'], 'question')
        self.assertNotIn('review_form', response.context)
        self.assertContains(response, 'data-state-part="question"')
        self.assertContains(response, f'Kiedy odbędzie się „{PRD_CONTENT}”?')
        self.assertContains(response, 'Dalej')
        self.assertContains(response, 'Pomiń')
        form = response.context['follow_up_form']
        self.assertEqual(form.initial['assigned_member'], self.child.pk)
        self.assertEqual(form.initial['missing'], ['date'])
        self.assertFalse(Entry.objects.exists())

    def test_ambiguous_member_asks_which_person(self):
        response, _ = self.classify_with(
            ClassificationFollowUp(
                missing_fields=(MissingField.AMBIGUOUS_MEMBER,),
                entry_type=EntryType.CALENDAR_EVENT,
                content=PRD_CONTENT,
                date=PRD_MONDAY,
            )
        )

        self.assertEqual(response.context['state'], 'question')
        self.assertContains(response, f'Której osoby dotyczy „{PRD_CONTENT}”?')
        self.assertNotIn('review_form', response.context)

    def test_unavailable_reasons_fall_back_to_note_with_text(self):
        for reason in (
            UnavailableReason.TIMEOUT,
            UnavailableReason.DISABLED,
            UnavailableReason.UNKNOWN_MEMBER,
        ):
            with self.subTest(reason=reason):
                response, _ = self.classify_with(
                    ClassificationUnavailable(reason=reason), text='Kupić zeszyt w kratkę'
                )
                self.assertEqual(response.context['state'], 'unavailable')
                self.assertContains(response, 'Nie udało się teraz rozpoznać wpisu.')
                form = response.context['review_form']
                self.assertEqual(form.initial['entry_type'], 'note')
                self.assertEqual(form.initial['content'], 'Kupić zeszyt w kratkę')

    def test_input_too_long_is_a_capture_error_without_review_form(self):
        response, _ = self.classify_with(
            ClassificationUnavailable(reason=UnavailableReason.INPUT_TOO_LONG),
            text='Za długi tekst',
        )

        self.assertEqual(response.context['state'], 'empty')
        self.assertNotIn('review_form', response.context)
        self.assertContains(response, 'Tekst jest za długi.')
        self.assertContains(response, 'Za długi tekst')

    def test_classification_uses_local_reference_date(self):
        with mock.patch(
            'entries.views.timezone.localdate', return_value=datetime.date(2026, 9, 19)
        ):
            _, classify = self.classify_with(self.proposal(), member=self.child)

        self.assertEqual(classify.call_args.kwargs['reference_date'], datetime.date(2026, 9, 19))


class PastDateWarningTests(CaptureViewMixin, TestCase):
    WARNING = (
        'Data 18.09.2026 jest w przeszłości. Jeśli jest poprawna, zapisz wpis. '
        'Jeśli nie, popraw datę powyżej.'
    )

    def classify_on(self, today, **proposal_overrides):
        with mock.patch('entries.views.timezone.localdate', return_value=today):
            response, _ = self.classify_with(
                self.proposal(**proposal_overrides), member=self.child
            )
        return response

    def test_past_date_is_warned_and_still_saved_unchanged(self):
        past = datetime.date(2026, 9, 18)

        response = self.classify_on(PRD_REFERENCE_DATE, date=past)

        self.assertEqual(response.context['state'], 'proposal')
        self.assertContains(response, self.WARNING)
        form = response.context['review_form']
        date_input = str(form['date'])
        self.assertIn('aria-invalid="true"', date_input)
        self.assertIn('aria-describedby="id_date-hint id_date-human"', date_input)
        self.assertContains(response, 'id="id_date-hint"')
        self.assertContains(response, 'id="id_date-human"')
        self.assertNotIn('aria-invalid', str(form['content']))

        data = {name: '' if value is None else str(value) for name, value in form.initial.items()}
        confirmed = self.client.post(CONFIRM_URL, data)

        entry = Entry.objects.get()
        self.assertRedirects(confirmed, f'{CAPTURE_URL}?saved={entry.pk}')
        self.assertEqual(entry.date, past)

    def test_no_warning_for_today_future_or_no_date(self):
        cases = {
            'today': dict(date=PRD_REFERENCE_DATE),
            'future': dict(date=PRD_MONDAY),
            'no date': dict(entry_type=EntryType.NOTE, date=None, school_item=None),
        }
        for name, overrides in cases.items():
            with self.subTest(name):
                response = self.classify_on(PRD_REFERENCE_DATE, **overrides)
                self.assertEqual(response.context['state'], 'proposal')
                self.assertNotContains(response, 'jest w przeszłości')
                self.assertNotIn('aria-invalid', str(response.context['review_form']['date']))


class IdempotencyAndSavedPanelTests(CaptureViewMixin, TestCase):
    def test_repeated_confirm_creates_one_row_and_same_redirect(self):
        data = self.confirm_data()

        first = self.client.post(CONFIRM_URL, data)
        second = self.client.post(CONFIRM_URL, data)

        self.assertEqual(Entry.objects.count(), 1)
        self.assertEqual(first['Location'], second['Location'])

    def test_resubmitted_key_with_edited_date_keeps_first_values(self):
        data = self.confirm_data()
        self.client.post(CONFIRM_URL, data)

        response = self.client.post(CONFIRM_URL, {**data, 'date': '2026-09-25'}, follow=True)

        self.assertEqual(Entry.objects.get().date, PRD_MONDAY)
        self.assertContains(response, '21 września 2026')
        self.assertNotContains(response, '25 września 2026')

    def test_key_owned_by_another_family_rerenders_with_new_key(self):
        key = uuid.uuid4()
        Entry.objects.create(
            family=self.other_family,
            entry_type=EntryType.NOTE.value,
            content='SENTINEL-OBCY-WPIS',
            submission_key=key,
        )

        response = self.client.post(CONFIRM_URL, self.confirm_data(submission_key=str(key)))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['state'], 'invalid')
        self.assertContains(response, 'Nie udało się zapisać wpisu.')
        self.assertNotContains(response, 'SENTINEL-OBCY-WPIS')
        new_key = response.context['review_form']['submission_key'].value()
        self.assertNotEqual(str(new_key), str(key))
        self.assertEqual(Entry.objects.count(), 1)

    def test_saved_panel_for_other_family_entry_leaks_nothing(self):
        foreign = Entry.objects.create(
            family=self.other_family,
            entry_type=EntryType.NOTE.value,
            content='SENTINEL-OBCY-WPIS',
        )

        for value in (str(foreign.pk), '999999', 'abc'):
            with self.subTest(saved=value):
                response = self.client.get(CAPTURE_URL, {'saved': value})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context['state'], 'empty')
                self.assertNotContains(response, 'Dodano wpis')
                self.assertNotContains(response, 'SENTINEL-OBCY-WPIS')


class RecordingHandler(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.messages = []

    def emit(self, record):
        self.messages.append(self.format(record))


class PrivacyTests(CaptureViewMixin, TestCase):
    def test_instruction_text_never_reaches_logs_and_only_entry_is_written(self):
        handler = RecordingHandler()
        root = logging.getLogger()
        previous_level = root.level
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)
        try:
            response, _ = self.classify_with(
                self.proposal(content=SENTINEL_TEXT), member=self.child, text=SENTINEL_TEXT
            )
            form = response.context['review_form']
            data = {name: '' if value is None else str(value) for name, value in form.initial.items()}
            self.client.post(CONFIRM_URL, data)
            # A rejected confirm also must not log the posted text.
            self.client.post(CONFIRM_URL, {**data, 'date': '', 'submission_key': str(uuid.uuid4())})
        finally:
            root.removeHandler(handler)
            root.setLevel(previous_level)

        for message in handler.messages:
            self.assertNotIn('SENTINEL-INSTRUKCJA', message)
        self.assertEqual(Entry.objects.count(), 1)


class EnterSubmitCaptureTests(CaptureViewMixin, TestCase):
    """S-05: the capture page loads the Enter script and marks its text boxes."""

    def test_script_is_resolvable_through_the_static_finders(self):
        self.assertIsNotNone(finders.find('js/enter-submit.js'))

    def test_empty_state_opts_the_instruction_box_in(self):
        response = self.client.get(CAPTURE_URL)

        self.assertEqual(response.context['state'], 'empty')
        field = str(response.context['capture_form']['text'])
        self.assertIn('data-enter-submit=""', field)
        self.assertIn('enterkeyhint="send"', field)
        self.assertNotIn('data-enter-submitter', field)
        assert_enter_assets(self, response, ['id_text'])

    def test_question_state_opts_the_answer_box_in(self):
        response, _ = self.classify_with(
            ClassificationFollowUp(
                missing_fields=(MissingField.DATE,),
                entry_type=EntryType.CALENDAR_EVENT,
                content=PRD_CONTENT,
                school_item=SchoolItemKind.TEST,
                member_name='michał',
            ),
            member=self.child,
        )

        self.assertEqual(response.context['state'], 'question')
        field = str(response.context['follow_up_form']['answer'])
        self.assertIn('data-enter-submit=""', field)
        self.assertIn('enterkeyhint="send"', field)
        # Enter means „Dalej” (the default action), never „Pomiń”.
        self.assertNotIn('data-enter-submitter', field)
        assert_enter_assets(self, response, ['id_answer'])

    def test_proposal_state_loads_the_script_for_the_correction_box(self):
        response, _ = self.classify_with(self.proposal(), member=self.child)

        self.assertEqual(response.context['state'], 'proposal')
        assert_enter_assets(self, response, ['id_correction'])
        self.assertNotIn('data-enter-submit', str(response.context['review_form']['content']))


class ProgressIndicatorCaptureTests(CaptureViewMixin, TestCase):
    """S-06: classification forms render the progress partial and thresholds."""

    def question(self):
        response, _ = self.classify_with(
            ClassificationFollowUp(
                missing_fields=(MissingField.DATE,),
                entry_type=EntryType.CALENDAR_EVENT,
                content=PRD_CONTENT,
                school_item=SchoolItemKind.TEST,
                member_name='michał',
            ),
            member=self.child,
        )
        self.assertEqual(response.context['state'], 'question')
        return response

    def only_progress_form(self, response):
        forms = progress_forms(response.content.decode())
        self.assertEqual(len(forms), 1)
        return forms[0]

    def test_capture_and_follow_up_forms_render_hidden_states_and_default_thresholds(self):
        pages = {
            'capture': (self.client.get(CAPTURE_URL), reverse('entries:capture'), ['Rozpoznaj']),
            'question': (self.question(), reverse('entries:answer'), ['Dalej']),
        }
        for name, (response, action, submitters) in pages.items():
            with self.subTest(page=name):
                content = response.content.decode()
                self.assertEqual(assert_progress_regions(self, content), 1)
                form = self.only_progress_form(response)
                self.assertEqual(form['attrs']['action'], action)
                self.assertEqual(form['attrs'].get('data-progress-slow-after'), '10')
                self.assertEqual(form['attrs'].get('data-progress-stalled-after'), '35')
                self.assertIn('data-classification-default', form['attrs'])
                self.assertEqual(classification_submitters(form), submitters)
                self.assertContains(
                    response,
                    '<p class="fn-muted fn-progress-elapsed" data-progress-elapsed '
                    'aria-hidden="true" hidden>0 s</p>',
                    html=True,
                )

    def test_skip_is_not_a_classification_submitter(self):
        form = self.only_progress_form(self.question())

        labels = [button['text'].strip() for button in form['buttons']]
        self.assertEqual(labels, ['Dalej', 'Pomiń'])
        skip = form['buttons'][1]
        self.assertEqual(skip['attrs'].get('value'), 'skip')
        self.assertNotIn('data-classification-submit', skip['attrs'])

    @override_settings(CLASSIFICATION_DEADLINE_SECONDS=12, CLASSIFICATION_ATTEMPT_TIMEOUT_SECONDS=6)
    def test_thresholds_follow_the_provider_settings(self):
        for name, response in (('capture', self.client.get(CAPTURE_URL)), ('question', self.question())):
            with self.subTest(page=name):
                form = self.only_progress_form(response)
                self.assertEqual(form['attrs'].get('data-progress-slow-after'), '6')
                self.assertEqual(form['attrs'].get('data-progress-stalled-after'), '22')

    @override_settings(
        CLASSIFICATION_DEADLINE_SECONDS=12.2, CLASSIFICATION_ATTEMPT_TIMEOUT_SECONDS=5.5
    )
    def test_fractional_settings_round_up(self):
        form = self.only_progress_form(self.client.get(CAPTURE_URL))

        self.assertEqual(form['attrs'].get('data-progress-slow-after'), '6')
        self.assertEqual(form['attrs'].get('data-progress-stalled-after'), '23')

    def test_capture_page_loads_both_scripts_and_the_new_one_resolves(self):
        response = self.client.get(CAPTURE_URL)

        self.assertIsNotNone(finders.find('js/classification-progress.js'))
        self.assertContains(response, f'<script src="{PROGRESS_SCRIPT_URL}" defer></script>', html=True)
        self.assertContains(response, f'<script src="{ENTER_SCRIPT_URL}" defer></script>', html=True)

    def test_saved_panel_has_no_progress_partial_of_its_own(self):
        entry = Entry.objects.create(
            family=self.family,
            entry_type=EntryType.TODO.value,
            content='Kupić zeszyt',
            created_by=self.parent,
        )

        response = self.client.get(f'{CAPTURE_URL}?saved={entry.pk}')

        self.assertEqual(response.context['state'], 'saved')
        self.assertContains(response, 'Dodano wpis')
        # Only the capture form below the panel carries the indicator.
        self.assertEqual(assert_progress_regions(self, response.content.decode()), 1)
        self.assertEqual(self.only_progress_form(response)['attrs']['action'], CAPTURE_URL)

    def test_structured_create_and_edit_forms_have_no_progress_partial(self):
        entry = Entry.objects.create(
            family=self.family,
            entry_type=EntryType.TODO.value,
            content='Kupić zeszyt',
            created_by=self.parent,
        )
        for url in (reverse('entries:create'), reverse('entries:edit', args=[entry.pk])):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, 'data-classification-progress')
                self.assertNotContains(response, 'data-progress-state')
                self.assertNotContains(response, PROGRESS_SCRIPT_URL)


class TwoParentCaptureTests(TwoParentFixtureMixin, CaptureViewMixin, TestCase):
    """S-07: capture naming a parent preselects them; confirm saves the parent."""

    def capture(self, member_name, text='Paweł ma odebrać paczkę'):
        clock = FakeClock()
        transport = ScriptedTransport(
            clock,
            [
                model_entry_output(
                    entry_type='note',
                    content='Odebrać paczkę',
                    member_name=member_name,
                )
            ],
        )
        backend = OpenAIClassificationBackend(
            client=make_client(transport), model=MODEL, clock=clock, sleep=clock.sleep
        )
        with mock.patch(
            'entries.views.timezone.localdate', return_value=PRD_REFERENCE_DATE
        ), mock.patch(
            'entries.classification.openai_backend.build_openai_backend', return_value=backend
        ):
            return self.client.post(CAPTURE_URL, {'text': text})

    def test_parent_named_by_classifier_is_preselected_and_saved(self):
        for member in (self.second_parent, self.parent):
            with self.subTest(member=member.display_name):
                Entry.objects.all().delete()
                review = self.capture(member.display_name)

                self.assertEqual(review.context['state'], 'proposal')
                form = review.context['review_form']
                self.assertEqual(form.initial['assigned_member'], member.pk)
                self.assertContains(
                    review,
                    f'<option value="{member.pk}" selected>{member.display_name}</option>',
                    html=True,
                )

                data = {
                    name: '' if value is None else str(value)
                    for name, value in form.initial.items()
                }
                self.client.post(CONFIRM_URL, data)

                entry = Entry.objects.get()
                self.assertEqual(entry.assigned_member, member)
                self.assertEqual(entry.created_by, self.parent)

    def test_confirm_rejects_foreign_and_inactive_parent(self):
        for member in (self.other_family_parent, self.inactive_parent):
            with self.subTest(member=member.display_name):
                response = self.client.post(
                    CONFIRM_URL,
                    self.confirm_data(
                        entry_type=EntryType.NOTE.value,
                        date='',
                        school_item='',
                        school_subject='',
                        assigned_member=str(member.pk),
                    ),
                )
                self.assertEqual(response.context['state'], 'invalid')
                self.assertIn('assigned_member', response.context['review_form'].errors)
        self.assertFalse(Entry.objects.exists())


class FieldAssociationTests(CaptureViewMixin, TestCase):
    """Every ``aria-describedby`` ID resolves to exactly one rendered element (S-17)."""

    def test_initial_capture_describes_the_text_by_the_enter_hint(self):
        response = self.client.get(CAPTURE_URL)

        assert_described_by(self, response, 'id_text', ['id_text-enter-hint'])

    def test_empty_capture_describes_the_text_by_its_error_and_the_enter_hint(self):
        response = self.client.post(CAPTURE_URL, {'text': '   '})

        self.assertContains(response, 'aria-invalid="true"')
        assert_described_by(self, response, 'id_text', ['id_text_error', 'id_text-enter-hint'])

    def test_too_long_capture_describes_the_text_by_its_error(self):
        response = self.client.post(CAPTURE_URL, {'text': 'x' * (MAX_SUBMITTED_TEXT_LENGTH + 1)})

        assert_described_by(self, response, 'id_text', ['id_text_error', 'id_text-enter-hint'])

    def test_classified_too_long_capture_describes_the_text_by_its_error(self):
        response, _ = self.classify_with(
            ClassificationUnavailable(reason=UnavailableReason.INPUT_TOO_LONG)
        )

        self.assertEqual(response.context['state'], 'empty')
        assert_described_by(self, response, 'id_text', ['id_text_error', 'id_text-enter-hint'])

    def test_proposal_describes_the_date_by_the_readable_date(self):
        with mock.patch('entries.views.timezone.localdate', return_value=PRD_REFERENCE_DATE):
            response, _ = self.classify_with(self.proposal(), member=self.child)

        assert_described_by(self, response, 'id_date', ['id_date-human'])
        assert_described_by(self, response, 'id_correction', ['id_correction-enter-hint'])
        assert_described_by(self, response, 'id_content', [])

    def test_confirm_invalid_references_resolve(self):
        response = self.client.post(CONFIRM_URL, self.confirm_data(content='', date=''))

        self.assertEqual(response.context['state'], 'invalid')
        assert_described_by(self, response, 'id_content', ['id_content_error'])
        assert_described_by(self, response, 'id_date', ['id_date_error'])
        assert_described_by(self, response, 'id_correction', ['id_correction-enter-hint'])

    def test_unapplied_correction_lists_its_error_and_the_enter_hint(self):
        response = self.client.post(CONFIRM_URL, self.confirm_data(correction='zmień datę'))

        self.assertEqual(response.context['state'], 'invalid')
        assert_described_by(
            self, response, 'id_correction', ['id_correction_error', 'id_correction-enter-hint']
        )


class ErrorTitleTests(CaptureViewMixin, TestCase):
    """An invalid re-render is recognisable from the page title (S-17)."""

    def test_valid_renders_have_the_plain_title(self):
        self.assertContains(self.client.get(CAPTURE_URL), '<title>Dodaj wpis | FamilyNotes</title>')
        response, _ = self.classify_with(self.proposal(), member=self.child)
        self.assertContains(response, '<title>Dodaj wpis | FamilyNotes</title>')

    def test_invalid_capture_title_starts_with_error(self):
        response = self.client.post(CAPTURE_URL, {'text': ''})

        self.assertContains(response, '<title>Błąd: Dodaj wpis | FamilyNotes</title>')

    def test_confirm_invalid_title_starts_with_error(self):
        response = self.client.post(CONFIRM_URL, self.confirm_data(content=''))

        self.assertEqual(response.context['state'], 'invalid')
        self.assertContains(response, '<title>Błąd: Dodaj wpis | FamilyNotes</title>')
