"""End-to-end tests for the follow-up question step of the capture flow.

A scripted fake backend replaces the configured provider, so the real views,
forms and classification service run: capture -> question -> answer or skip
-> review -> confirm.
"""

import datetime
import logging
from unittest import mock

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from entries.classification.backends import BackendOutput, ClassificationBackendError
from entries.classification.service import MAX_FOLLOW_UP_ANSWER_LENGTH
from entries.classification.types import EntryType, SchoolItemKind, UnavailableReason
from entries.models import Entry
from family_access.models import FamilyMember

from .test_capture_views import RecordingHandler
from .test_classification_service import WRITE_PREFIXES, FamilyFixtureMixin

CAPTURE_URL = reverse('entries:capture')
ANSWER_URL = reverse('entries:answer')
CONFIRM_URL = reverse('entries:confirm')

SATURDAY = datetime.date(2026, 9, 19)
NEXT_FRIDAY = datetime.date(2026, 9, 25)
INSTRUCTION = 'Kasia ma kartkówkę z matematyki'
CONTENT = 'Kartkówka z matematyki'
ANSWER_SENTINEL = 'SENTINEL-ODPOWIEDZ-5d2b w piątek'


def output(**overrides):
    values = dict(
        entry_type=EntryType.CALENDAR_EVENT,
        content=CONTENT,
        grounded=True,
        school_item=SchoolItemKind.QUIZ,
        member_name='Kasia',
    )
    values.update(overrides)
    return BackendOutput(**values)


class ScriptedBackend:
    """Returns (or raises) one scripted item per call and records requests."""

    def __init__(self, *script):
        self.script = list(script)
        self.requests = []

    def classify(self, request):
        self.requests.append(request)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def close(self):
        pass


def as_post_data(form):
    """The values a browser would post back from an unbound form's initial data."""
    data = {}
    for name, value in form.initial.items():
        if isinstance(value, list):
            data[name] = value
        else:
            data[name] = '' if value is None else str(value)
    return data


class FollowUpViewMixin(FamilyFixtureMixin):
    def setUp(self):
        super().setUp()
        self.kasia = self._member('kasia', FamilyMember.Role.CHILD, 'Kasia')
        self.client.force_login(self.parent.user)
        self.backend = ScriptedBackend()

    def run_with_backend(self, method, url, data, *script):
        self.backend.script.extend(script)
        with mock.patch(
            'entries.views.timezone.localdate', return_value=SATURDAY
        ), mock.patch(
            'entries.classification.openai_backend.build_openai_backend',
            return_value=self.backend,
        ):
            return getattr(self.client, method)(url, data)

    def ask(self, first=None, text=INSTRUCTION):
        """Capture ``text``; the backend returns a draft missing the date."""
        response = self.run_with_backend(
            'post', CAPTURE_URL, {'text': text}, first or output()
        )
        self.assertEqual(response.context['state'], 'question')
        return response, as_post_data(response.context['follow_up_form'])

    def answer(self, data, *script, **overrides):
        return self.run_with_backend('post', ANSWER_URL, {**data, **overrides}, *script)

    def confirm_from(self, response):
        data = as_post_data(response.context['review_form'])
        return self.client.post(CONFIRM_URL, data)


class QuestionFlowTests(FollowUpViewMixin, TestCase):
    def test_question_state_shows_question_summary_and_actions(self):
        response, data = self.ask()

        self.assertNotIn('review_form', response.context)
        self.assertContains(response, 'data-state-part="question"')
        self.assertContains(response, f'action="{ANSWER_URL}"')
        self.assertContains(response, f'Kiedy odbędzie się „{CONTENT}”?')
        self.assertContains(response, f'Rozpoznano: wydarzenie „{CONTENT}”')
        self.assertContains(response, '<button type="submit">Dalej</button>', html=True)
        self.assertContains(response, 'name="action" value="skip"')
        self.assertContains(response, 'formnovalidate')
        self.assertContains(response, 'Zacznij od nowa')
        self.assertEqual(data['missing'], ['date'])
        self.assertEqual(data['assigned_member'], str(self.kasia.pk))
        self.assertFalse(Entry.objects.exists())

    def test_acceptance_answer_fills_date_and_confirm_saves_once(self):
        _, data = self.ask()

        response = self.answer(data, output(date=NEXT_FRIDAY), answer='w piątek')

        self.assertEqual(response.context['state'], 'proposal')
        request = self.backend.requests[-1]
        self.assertEqual(request.submitted_text, INSTRUCTION)
        self.assertEqual(request.follow_up_answer, 'w piątek')
        self.assertEqual(request.reference_date, SATURDAY)
        form = response.context['review_form']
        self.assertEqual(form.initial['date'], NEXT_FRIDAY)
        self.assertEqual(form.initial['assigned_member'], self.kasia.pk)
        self.assertFalse(Entry.objects.exists())

        confirmed = self.confirm_from(response)
        self.confirm_from(response)

        entry = Entry.objects.get()
        self.assertRedirects(confirmed, f'{CAPTURE_URL}?saved={entry.pk}')
        self.assertEqual(entry.date, NEXT_FRIDAY)
        self.assertEqual(entry.assigned_member, self.kasia)
        self.assertEqual(entry.content, CONTENT)
        self.assertEqual(entry.school_item, SchoolItemKind.QUIZ.value)

    def test_member_still_missing_falls_back_to_highlighted_review(self):
        _, data = self.ask(first=output(member_name=None), text='Kartkówka z matematyki')
        self.assertEqual(data['missing'], ['date', 'affected_member'])

        response = self.answer(
            data, output(date=NEXT_FRIDAY, member_name=None), answer='w piątek'
        )

        self.assertEqual(response.context['state'], 'follow_up')
        form = response.context['review_form']
        self.assertEqual(form.initial['date'], NEXT_FRIDAY)
        self.assertContains(response, 'Wybierz osobę, której dotyczy wpis.')
        self.assertIn('aria-invalid="true"', str(form['assigned_member']))
        self.assertNotIn('aria-invalid', str(form['date']))
        self.assertFalse(Entry.objects.exists())

    def test_provider_unavailable_falls_back_to_draft_with_notice(self):
        _, data = self.ask()

        response = self.answer(
            data,
            ClassificationBackendError(UnavailableReason.TIMEOUT),
            answer='w piątek',
        )

        self.assertEqual(response.context['state'], 'follow_up')
        self.assertContains(response, 'Nie udało się rozpoznać odpowiedzi. Uzupełnij brakujące pola.')
        form = response.context['review_form']
        self.assertEqual(form.initial['content'], CONTENT)
        self.assertEqual(form.initial['assigned_member'], self.kasia.pk)
        self.assertIsNone(form.initial['date'])
        self.assertIn('aria-invalid="true"', str(form['date']))
        self.assertFalse(Entry.objects.exists())

    def test_nothing_missing_after_recomputation_skips_the_backend(self):
        _, data = self.ask()
        calls = len(self.backend.requests)

        response = self.answer(data, answer='w piątek', date=NEXT_FRIDAY.isoformat())

        self.assertEqual(len(self.backend.requests), calls)
        self.assertEqual(response.context['state'], 'proposal')
        self.assertEqual(response.context['review_form'].initial['date'], NEXT_FRIDAY)

    def test_tampered_missing_values_are_dropped(self):
        # A todo has no required fields, so a posted "date" is not missing.
        _, data = self.ask()
        calls = len(self.backend.requests)

        response = self.answer(
            data, answer='jutro', entry_type=EntryType.TODO.value, school_item=''
        )

        self.assertEqual(len(self.backend.requests), calls)
        self.assertEqual(response.context['state'], 'proposal')
        self.assertEqual(response.context['review_form'].initial['entry_type'], 'todo')


class SkipTests(FollowUpViewMixin, TestCase):
    def test_skip_with_empty_answer_offers_a_note_keeping_known_values(self):
        _, data = self.ask()
        calls = len(self.backend.requests)

        response = self.answer(data, answer='', action='skip')

        self.assertEqual(len(self.backend.requests), calls)
        self.assertEqual(response.context['state'], 'skipped')
        self.assertContains(
            response, 'Brakujące dane pominięte — wpis zostanie zapisany jako notatka.'
        )
        form = response.context['review_form']
        self.assertEqual(form.initial['entry_type'], EntryType.NOTE.value)
        self.assertEqual(form.initial['content'], CONTENT)
        self.assertEqual(form.initial['assigned_member'], self.kasia.pk)
        self.assertEqual(form.initial['school_item'], '')
        self.assertFalse(Entry.objects.exists())

        self.confirm_from(response)

        entry = Entry.objects.get()
        self.assertEqual(entry.entry_type, EntryType.NOTE.value)
        self.assertEqual(entry.school_item, '')
        self.assertEqual(entry.assigned_member, self.kasia)
        self.assertEqual(entry.content, CONTENT)

    def test_skip_keeps_known_date_and_time(self):
        _, data = self.ask(
            first=output(
                member_name=None, date=NEXT_FRIDAY, time=datetime.time(8, 0)
            )
        )

        response = self.answer(data, answer='', action='skip')

        form = response.context['review_form']
        self.assertEqual(form.initial['date'], NEXT_FRIDAY)
        self.assertEqual(form.initial['time'], datetime.time(8, 0))
        self.assertIsNone(form.initial['assigned_member'])

    def test_skip_ignores_an_over_long_answer(self):
        _, data = self.ask()

        response = self.answer(
            data, answer='x' * (MAX_FOLLOW_UP_ANSWER_LENGTH + 1), action='skip'
        )

        self.assertEqual(response.context['state'], 'skipped')


class AnswerValidationTests(FollowUpViewMixin, TestCase):
    def test_empty_answer_without_skip_is_a_field_error(self):
        _, data = self.ask()
        calls = len(self.backend.requests)

        response = self.answer(data, answer='   ')

        self.assertEqual(len(self.backend.requests), calls)
        self.assertEqual(response.context['state'], 'question')
        self.assertContains(response, 'Wpisz odpowiedź albo wybierz „Pomiń”.')
        self.assertContains(response, f'Kiedy odbędzie się „{CONTENT}”?')

    def test_too_long_answer_is_a_field_error(self):
        _, data = self.ask()
        calls = len(self.backend.requests)

        response = self.answer(data, answer='x' * (MAX_FOLLOW_UP_ANSWER_LENGTH + 1))

        self.assertEqual(len(self.backend.requests), calls)
        self.assertEqual(response.context['state'], 'question')
        form = response.context['follow_up_form']
        self.assertIn('answer', form.errors)
        self.assertIn('aria-invalid="true"', str(form['answer']))
        self.assertFalse(form.has_stale_fields())

    def test_foreign_or_inactive_member_is_a_form_error(self):
        _, data = self.ask()
        calls = len(self.backend.requests)

        for member in (self.other_family_child, self.inactive_child):
            with self.subTest(member=member.display_name):
                response = self.answer(
                    data, answer='w piątek', assigned_member=str(member.pk)
                )
                self.assertEqual(response.context['state'], 'question')
                form = response.context['follow_up_form']
                self.assertIn('assigned_member', form.errors)
                self.assertContains(response, 'Nie udało się odczytać wpisu. Zacznij od nowa.')
                self.assertNotContains(response, member.display_name)
        self.assertEqual(len(self.backend.requests), calls)
        self.assertFalse(Entry.objects.exists())

    def test_empty_missing_list_is_a_form_error(self):
        _, data = self.ask()
        data.pop('missing')

        response = self.answer(data, answer='w piątek')

        self.assertEqual(response.context['state'], 'question')
        self.assertIn('missing', response.context['follow_up_form'].errors)


class AnswerAccessTests(FollowUpViewMixin, TestCase):
    def answer_data(self):
        return {
            'text': INSTRUCTION,
            'entry_type': EntryType.CALENDAR_EVENT.value,
            'content': CONTENT,
            'date': '',
            'time': '',
            'school_item': SchoolItemKind.QUIZ.value,
            'assigned_member': str(self.kasia.pk),
            'missing': ['date'],
            'answer': 'w piątek',
        }

    def test_anonymous_is_redirected_to_login(self):
        self.client.logout()

        response = self.answer(self.answer_data())

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('account_login'), response['Location'])
        self.assertEqual(self.backend.requests, [])

    def test_child_is_forbidden(self):
        self.client.force_login(self.child.user)

        response = self.answer(self.answer_data())

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.backend.requests, [])

    def test_other_family_parent_cannot_use_our_member(self):
        self.client.force_login(self.other_family_parent.user)

        response = self.answer(self.answer_data())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['state'], 'question')
        self.assertIn('assigned_member', response.context['follow_up_form'].errors)
        self.assertEqual(self.backend.requests, [])

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get(ANSWER_URL).status_code, 405)


class AnswerPrivacyTests(FollowUpViewMixin, TestCase):
    def test_answer_never_reaches_logs_and_nothing_is_written(self):
        _, data = self.ask()
        handler = RecordingHandler()
        root = logging.getLogger()
        previous_level = root.level
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)
        try:
            with CaptureQueriesContext(connection) as queries:
                self.answer(data, output(date=NEXT_FRIDAY), answer=ANSWER_SENTINEL)
                # A rejected (too long) answer also must not log the posted text.
                self.answer(
                    data, answer=ANSWER_SENTINEL + 'x' * MAX_FOLLOW_UP_ANSWER_LENGTH
                )
        finally:
            root.removeHandler(handler)
            root.setLevel(previous_level)

        for message in handler.messages:
            self.assertNotIn('SENTINEL-ODPOWIEDZ', message)
        writes = [
            query['sql']
            for query in queries.captured_queries
            if query['sql'].lstrip().upper().startswith(WRITE_PREFIXES)
            and 'django_session' not in query['sql']
        ]
        self.assertEqual(writes, [])
        self.assertFalse(Entry.objects.exists())

