from unittest.mock import patch

from django.db import DatabaseError
from django.test import TestCase
from django.urls import reverse


class RootRouteTests(TestCase):
    def test_root_renders_homepage(self):
        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Hello, FamilyNotes!')
        self.assertTemplateUsed(response, 'family_notes/home.html')

    def test_admin_endpoint_is_not_exposed(self):
        response = self.client.get('/admin/')

        self.assertEqual(response.status_code, 404)


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
