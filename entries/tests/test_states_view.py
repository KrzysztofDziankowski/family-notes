from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from entries import views
from entries.models import Entry

from .test_classification_service import FamilyFixtureMixin

STATES_URL = reverse('entries:states')
STATE_NAMES = (
    'empty',
    'proposal',
    'past_date',
    'follow_up',
    'follow_up_subject',
    'unavailable',
    'question',
    'question_combined',
    'question_ambiguous_member',
    'question_subject',
    'answer_unavailable',
    'skipped',
    'invalid',
    'saved',
)


class StatesKitchenSinkTests(FamilyFixtureMixin, TestCase):
    @override_settings(DEBUG=False)
    def test_not_found_without_debug(self):
        self.client.force_login(self.parent.user)

        self.assertEqual(self.client.get(STATES_URL).status_code, 404)

    @override_settings(DEBUG=True)
    def test_parent_sees_every_state_without_writes_or_backend_calls(self):
        self.client.force_login(self.parent.user)

        with (
            mock.patch('entries.views.classify_for_parent') as classify,
            mock.patch('entries.views.classify_follow_up_answer') as classify_answer,
        ):
            response = self.client.get(STATES_URL)

        self.assertEqual(response.status_code, 200)
        for name in STATE_NAMES:
            with self.subTest(state=name):
                self.assertContains(response, f'data-kitchen-state="{name}"')
        self.assertContains(response, 'data-kitchen-state="follow_up_member"')
        self.assertContains(response, 'Dodano wpis')
        self.assertContains(response, 'Nie udało się teraz rozpoznać wpisu.')
        self.assertContains(response, views.ANSWER_UNAVAILABLE_NOTICE)
        self.assertContains(response, views.SKIPPED_NOTICE)
        self.assertContains(response, 'Kiedy odbędzie się „Wywiadówka w szkole”?')
        self.assertContains(
            response,
            'Kiedy odbędzie się „Sprawdzian z angielskiego” i której osoby dotyczy?',
        )
        self.assertContains(response, 'Z jakiego przedmiotu jest „Sprawdzian”?')
        self.assertContains(response, 'Której osoby dotyczy „Dentysta”?')
        self.assertContains(response, 'Podaj przedmiot.')
        self.assertContains(response, 'value="historia"')
        self.assertContains(response, '<label for="id_school_item">Element szkolny</label>', html=True)
        self.assertContains(response, 'aria-invalid="true"')
        self.assertContains(
            response,
            'Data 01.10.2026 jest w przeszłości. Jeśli jest poprawna, zapisz wpis. '
            'Jeśli nie, popraw datę powyżej.',
        )
        self.assertContains(response, 'Kasia')
        for real_name in ('Michał', 'Ania', 'Ewa'):
            self.assertNotContains(response, real_name)
        classify.assert_not_called()
        classify_answer.assert_not_called()
        self.assertFalse(Entry.objects.exists())

    @override_settings(DEBUG=True)
    def test_child_is_forbidden_and_anonymous_is_redirected(self):
        self.client.force_login(self.child.user)
        self.assertEqual(self.client.get(STATES_URL).status_code, 403)

        self.client.logout()
        response = self.client.get(STATES_URL)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('account_login'), response['Location'])
