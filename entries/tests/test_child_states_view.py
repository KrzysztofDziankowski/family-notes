"""S-03 child-view kitchen sink: DEBUG gating, access and synthetic-only rendering."""

import re

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from entries.models import Entry

from .test_classification_service import FamilyFixtureMixin

CHILD_STATES_URL = reverse('entries:child_states')
STATE_NAMES = (
    'upcoming',
    'past',
    'upcoming_empty',
    'past_empty',
    'detail_manual',
    'detail_eduvulcan',
    'error_forbidden',
)
# STATES_DATE is Monday 2026-10-05; each list covers every day-heading kind.
EXPECTED_DAY_HEADINGS = {
    'upcoming': ['Dziś', 'Jutro', 'Czwartek', 'Poniedziałek, 26 października', 'Bez daty'],
    'past': ['Wczoraj', 'Piątek', 'Środa', 'Sobota, 5 września'],
}


def _state_html(html, name):
    match = re.search(
        rf'<section data-kitchen-state="{name}">(.*?)</section>', html, re.DOTALL
    )
    return match.group(1) if match else ''


class ChildStatesKitchenSinkTests(FamilyFixtureMixin, TestCase):
    def test_route_is_not_shadowed_by_detail(self):
        self.assertEqual(CHILD_STATES_URL, '/entries/mine/_states/')

    @override_settings(DEBUG=False)
    def test_not_found_without_debug(self):
        self.client.force_login(self.child.user)

        self.assertEqual(self.client.get(CHILD_STATES_URL).status_code, 404)

    @override_settings(DEBUG=False)
    def test_every_method_is_not_found_without_debug(self):
        self.client.force_login(self.child.user)

        for method in ('post', 'put', 'delete'):
            with self.subTest(method=method):
                response = getattr(self.client, method)(CHILD_STATES_URL)
                self.assertEqual(response.status_code, 404)

    @override_settings(DEBUG=True)
    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(CHILD_STATES_URL)

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('account_login'), response['Location'])

    @override_settings(DEBUG=True)
    def test_user_without_active_membership_is_forbidden(self):
        unconfigured = get_user_model().objects.create_user(username='unconfigured')
        for user in (unconfigured, self.inactive_child.user):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                self.assertEqual(self.client.get(CHILD_STATES_URL).status_code, 403)

    @override_settings(DEBUG=True)
    def test_every_state_renders_from_synthetic_data_only(self):
        Entry.objects.create(
            family=self.family,
            entry_type='note',
            content='SENTINEL-REAL-ROW',
            assigned_member=self.child,
        )
        for member in (self.child, self.parent):
            with self.subTest(role=member.role):
                self.client.force_login(member.user)
                with CaptureQueriesContext(connection) as queries:
                    response = self.client.get(CHILD_STATES_URL)

                self.assertEqual(response.status_code, 200)
                for name in STATE_NAMES:
                    self.assertContains(response, f'data-kitchen-state="{name}"')
                self.assertContains(response, 'data-empty-state="upcoming"')
                self.assertContains(response, 'data-empty-state="past"')
                self.assertContains(response, 'Nie masz żadnych nadchodzących wpisów.')
                self.assertContains(response, 'Nie masz żadnych minionych wpisów.')
                self.assertContains(response, 'Bez daty')
                self.assertContains(response, 'EduVulcan')
                self.assertContains(response, 'Ręcznie')
                self.assertContains(response, 'kartkówka')
                self.assertContains(response, 'aria-current="page"')
                self.assertNotContains(response, 'SENTINEL-REAL-ROW')
                for real_name in ('Michał', 'Ania', 'Ewa'):
                    self.assertNotContains(response, real_name)
                entry_table = Entry._meta.db_table
                self.assertFalse(
                    [q['sql'] for q in queries.captured_queries if entry_table in q['sql']]
                )
        self.assertEqual(Entry.objects.count(), 1)

    @override_settings(DEBUG=True)
    def test_day_headings_and_error_state_render_per_section(self):
        self.client.force_login(self.child.user)

        html = self.client.get(CHILD_STATES_URL).content.decode()

        for name, headings in EXPECTED_DAY_HEADINGS.items():
            with self.subTest(state=name):
                self.assertEqual(
                    re.findall(r'<h2 class="fn-day-heading">(.*?)</h2>', _state_html(html, name)),
                    headings,
                )
        error = _state_html(html, 'error_forbidden')
        self.assertIn('fn-panel--danger', error)
        self.assertIn('Brak dostępu', error)
        self.assertIn('Ta strona nie jest dostępna dla Twojego konta.', error)
        self.assertIn('href="/"', error)
        eduvulcan = _state_html(html, 'detail_eduvulcan')
        self.assertIn('<dt>Przedmiot</dt>', eduvulcan)
        self.assertIn('przyroda', eduvulcan)
        self.assertNotIn('Przedmiot', _state_html(html, 'detail_manual'))
