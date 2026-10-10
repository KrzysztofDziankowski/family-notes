"""S-03 child-view kitchen sink: DEBUG gating, access and synthetic-only rendering."""

import datetime
import re

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from entries.listing import parent_day_heading
from entries.models import Entry
from entries.views import STATES_DATE

from .test_classification_service import FamilyFixtureMixin

CHILD_STATES_URL = reverse('entries:child_states')
STATE_NAMES = (
    'list_today',
    'list_earlier',
    'list_empty',
    'detail_manual',
    'detail_eduvulcan',
    'error_forbidden',
)
# STATES_DATE is Monday 2026-10-05; the earlier window starts 14 days before it.
EARLIER_START = STATES_DATE - datetime.timedelta(days=14)
WINDOW_STARTS = {
    'list_today': STATES_DATE,
    'list_earlier': EARLIER_START,
    'list_empty': STATES_DATE,
}
HEADING_PATTERN = re.compile(r'<h2 class="fn-day-heading"[^>]*>(.*?)</h2>')


def _state_html(html, name):
    """One gallery section, up to the next ``data-kitchen-state`` section."""
    marker = f'<section data-kitchen-state="{name}">'
    if marker not in html:
        return ''
    start = html.index(marker)
    end = html.find('<section data-kitchen-state="', start + 1)
    return html[start:end if end != -1 else len(html)]


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
        Entry.objects.create(date=datetime.date(2026, 9, 21),
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
                self.assertContains(response, 'Brak wpisów')
                self.assertContains(response, 'Szczęśliwy numerek')
                self.assertNotContains(response, 'Bez daty')
                for removed in ('Nadchodz', 'Minion', 'fn-tabs', 'view='):
                    self.assertNotContains(response, removed)
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
    def test_list_states_render_fourteen_labelled_days_without_subheadings(self):
        self.client.force_login(self.child.user)

        html = self.client.get(CHILD_STATES_URL).content.decode()

        for name, start in WINDOW_STARTS.items():
            with self.subTest(state=name):
                state = _state_html(html, name)
                days = [start + datetime.timedelta(days=n) for n in range(14)]
                self.assertEqual(
                    re.findall(r'data-day-group="([\w-]+)"', state),
                    [day.isoformat() for day in days],
                )
                self.assertEqual(
                    HEADING_PATTERN.findall(state),
                    [parent_day_heading(day, STATES_DATE) for day in days],
                )
                self.assertNotIn('<h3', state)
                # Every list is labelled by its own heading; ids are page-unique.
                ids = re.findall(r'<h2 class="fn-day-heading" id="([^"]+)"', state)
                self.assertTrue(all(i.startswith(f'{name}-day-') for i in ids))
                self.assertTrue(
                    set(re.findall(r'aria-labelledby="([^"]+)"', state)) <= set(ids)
                )
                self.assertIn(f'?start={start.isoformat()}', state)
        # Calendar and detail ids are page-unique; the capture states repeat
        # their form field ids by design, like the parent gallery.
        calendar_html = html[:html.index('<section data-kitchen-state="capture_')]
        all_ids = re.findall(r'\bid="([^"]+)"', calendar_html)
        self.assertEqual(len(all_ids), len(set(all_ids)))

        today = _state_html(html, 'list_today')
        self.assertEqual(HEADING_PATTERN.findall(today)[0], 'Dziś, poniedziałek 5 października')
        self.assertIn('Szczęśliwy numerek', today)
        self.assertIn('data-day-group="2026-10-17" data-weekend', today)
        self.assertIn('aria-current="page">Dzisiaj', today)
        earlier = _state_html(html, 'list_earlier')
        self.assertEqual(HEADING_PATTERN.findall(earlier)[-1], 'Wczoraj, niedziela 4 października')
        self.assertIn('Kartkówka z przyrody', earlier)
        self.assertNotIn('aria-current', earlier)
        empty = _state_html(html, 'list_empty')
        self.assertEqual(empty.count('>Brak wpisów</p>'), 14)
        self.assertNotIn('data-entry-row', empty)

    @override_settings(DEBUG=True)
    def test_detail_and_error_states(self):
        self.client.force_login(self.child.user)

        html = self.client.get(CHILD_STATES_URL).content.decode()

        error = _state_html(html, 'error_forbidden')
        self.assertIn('fn-panel--danger', error)
        self.assertIn('Brak dostępu', error)
        self.assertIn('Ta strona nie jest dostępna dla Twojego konta.', error)
        self.assertIn('href="/"', error)
        eduvulcan = _state_html(html, 'detail_eduvulcan')
        self.assertIn('<dt>Przedmiot</dt>', eduvulcan)
        self.assertIn('przyroda', eduvulcan)
        self.assertIn(f'href="/entries/mine/?start={EARLIER_START.isoformat()}" data-back-link', eduvulcan)
        manual = _state_html(html, 'detail_manual')
        self.assertNotIn('Przedmiot', manual)
        self.assertIn(f'href="/entries/mine/?start={STATES_DATE.isoformat()}" data-back-link', manual)



CAPTURE_STATE_NAMES = (
    'capture_empty',
    'capture_proposal',
    'capture_question',
    'capture_follow_up',
    'capture_unavailable',
    'capture_correction_failed',
    'capture_invalid',
    'capture_batch',
    'capture_saved',
    'capture_saved_private',
)


class ChildCaptureStatesTests(FamilyFixtureMixin, TestCase):
    @override_settings(DEBUG=True)
    def test_capture_states_show_child_controls_and_post_to_child_routes(self):
        child_routes = {
            reverse(f'entries:child_{name}')
            for name in ('capture', 'answer', 'correct', 'confirm', 'confirm_batch')
        }
        for member in (self.child, self.parent):
            with self.subTest(role=member.role):
                self.client.force_login(member.user)
                html = self.client.get(CHILD_STATES_URL).content.decode()
                for name in CAPTURE_STATE_NAMES:
                    with self.subTest(state=name):
                        state = _state_html(html, name)
                        self.assertTrue(state, name)
                        self.assertNotIn('name="assigned_member"', state)
                        actions = set(re.findall(r'(?:action|formaction)="([^"]*)"', state))
                        self.assertTrue(actions <= child_routes, actions - child_routes)
                for name in ('capture_proposal', 'capture_batch', 'capture_invalid'):
                    self.assertIn('is_private', _state_html(html, name))
                self.assertIn('data-saved-private', _state_html(html, 'capture_saved_private'))
                self.assertNotIn('data-saved-private', _state_html(html, 'capture_saved'))
                self.assertIn('fn-field-error', _state_html(html, 'capture_invalid'))
        self.assertFalse(Entry.objects.exists())
