import datetime
import logging
import uuid
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from entries.classification.openai_backend import OpenAIClassificationBackend
from entries.classification.service import ParentClassification
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

from .test_classification_acceptance import (
    PRD_CONTENT,
    PRD_INSTRUCTION,
    PRD_MONDAY,
    PRD_REFERENCE_DATE,
    model_output,
)
from .test_classification_service import FamilyFixtureMixin
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
        with mock.patch('entries.views.classify_for_parent', return_value=outcome) as classify:
            response = self.client.post(CAPTURE_URL, {'text': text})
        return response, classify

    def proposal(self, **overrides):
        values = dict(
            entry_type=EntryType.CALENDAR_EVENT,
            content=PRD_CONTENT,
            date=PRD_MONDAY,
            school_item=SchoolItemKind.TEST,
            member_name='michał',
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
            'submission_key': str(uuid.uuid4()),
        }
        data.update(overrides)
        return data


class AccessMatrixTests(CaptureViewMixin, TestCase):
    def test_anonymous_is_redirected_to_login(self):
        self.client.logout()
        with mock.patch('entries.views.classify_for_parent') as classify:
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
        with mock.patch('entries.views.classify_for_parent') as classify:
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
                model_output(
                    entry_type='calendar_event',
                    content=PRD_CONTENT,
                    date=PRD_MONDAY.isoformat(),
                    school_item='test',
                    member_name='Michał',
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


class CorrectionAndValidationTests(CaptureViewMixin, TestCase):
    def test_corrected_values_are_saved(self):
        self.client.post(
            CONFIRM_URL,
            self.confirm_data(
                entry_type=EntryType.TODO.value,
                content='Poprawiony tytuł',
                date='2026-09-22',
                assigned_member=str(self.other_child.pk),
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

    def test_school_item_is_cleared_when_type_changes(self):
        self.client.post(
            CONFIRM_URL,
            self.confirm_data(entry_type=EntryType.NOTE.value, assigned_member='', date=''),
        )

        entry = Entry.objects.get()
        self.assertEqual(entry.entry_type, 'note')
        self.assertEqual(entry.school_item, '')

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
