from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from entries.models import Entry

from .test_classification_service import FamilyFixtureMixin

STATES_URL = reverse('entries:states')
STATE_NAMES = ('empty', 'proposal', 'follow_up', 'unavailable', 'invalid', 'saved')


class StatesKitchenSinkTests(FamilyFixtureMixin, TestCase):
    @override_settings(DEBUG=False)
    def test_not_found_without_debug(self):
        self.client.force_login(self.parent.user)

        self.assertEqual(self.client.get(STATES_URL).status_code, 404)

    @override_settings(DEBUG=True)
    def test_parent_sees_every_state_without_writes_or_backend_calls(self):
        self.client.force_login(self.parent.user)

        with mock.patch('entries.views.classify_for_parent') as classify:
            response = self.client.get(STATES_URL)

        self.assertEqual(response.status_code, 200)
        for name in STATE_NAMES:
            with self.subTest(state=name):
                self.assertContains(response, f'data-kitchen-state="{name}"')
        self.assertContains(response, 'data-kitchen-state="follow_up_member"')
        self.assertContains(response, 'Dodano wpis')
        self.assertContains(response, 'Nie udało się teraz rozpoznać wpisu.')
        self.assertContains(response, 'aria-invalid="true"')
        self.assertContains(response, 'Kasia')
        for real_name in ('Michał', 'Ania', 'Ewa'):
            self.assertNotContains(response, real_name)
        classify.assert_not_called()
        self.assertFalse(Entry.objects.exists())

    @override_settings(DEBUG=True)
    def test_child_is_forbidden_and_anonymous_is_redirected(self):
        self.client.force_login(self.child.user)
        self.assertEqual(self.client.get(STATES_URL).status_code, 403)

        self.client.logout()
        response = self.client.get(STATES_URL)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('account_login'), response['Location'])
