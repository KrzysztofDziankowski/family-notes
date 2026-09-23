from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import DatabaseError
from django.test import TestCase
from django.urls import reverse


class RootRouteTests(TestCase):
    def test_root_renders_homepage(self):
        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Hello, FamilyNotes!')
        self.assertTemplateUsed(response, 'family_notes/home.html')

    def test_account_status_requires_authentication(self):
        response = self.client.get(reverse('account_status'))

        self.assertRedirects(
            response,
            f"{reverse('account_login')}?next={reverse('account_status')}",
        )

    def test_admin_redirects_unauthenticated_users_to_admin_login(self):
        response = self.client.get(reverse('admin:index'))

        self.assertRedirects(response, f"{reverse('admin:login')}?next=/admin/")

    def test_active_staff_user_without_superuser_status_cannot_enter_admin(self):
        user = get_user_model().objects.create_user(
            username='staff',
            email='staff@example.test',
            password='test-password',
            is_staff=True,
        )
        self.client.force_login(user)

        response = self.client.get(reverse('admin:index'))

        self.assertRedirects(
            response,
            f"{reverse('admin:login')}?next={reverse('admin:index')}",
        )

    def test_active_superuser_can_reach_admin(self):
        user = get_user_model().objects.create_superuser(
            username='operator',
            email='operator@example.test',
            password='test-password',
        )
        self.client.force_login(user)

        response = self.client.get(reverse('admin:index'))

        self.assertEqual(response.status_code, 200)


class HealthCheckTests(TestCase):
    def test_health_check_succeeds_when_database_is_available(self):
        response = self.client.get(reverse('healthz'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'ok'})

    @patch('family_notes.views.connection.cursor', side_effect=DatabaseError)
    def test_health_check_hides_database_failure_details(self, _cursor):
        response = self.client.get(reverse('healthz'))

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {'status': 'unavailable'})
