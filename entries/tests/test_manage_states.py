"""DEBUG-only management states in the kitchen-sink gallery (S-02 phase 3)."""

import re

from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from entries.models import Entry

from .test_classification_service import FamilyFixtureMixin

STATES_URL = reverse('entries:states')
MANAGE_STATES = (
    'list_upcoming',
    'list_past',
    'list_empty',
    'detail_manual',
    'detail_eduvulcan',
    'create',
    'invalid',
    'edit',
    'delete_open',
)
WRITE_SQL = re.compile(r'^\s*(INSERT|UPDATE|DELETE)\b', re.IGNORECASE)


def state_html(html, name):
    start = html.index(f'data-manage-state="{name}"')
    end = html.find('data-manage-state="', start + 1)
    return html[start:end if end != -1 else len(html)]


class ManageStatesGalleryTests(FamilyFixtureMixin, TestCase):
    @override_settings(DEBUG=True)
    def test_parent_sees_every_management_state_without_writes(self):
        self.client.force_login(self.parent.user)

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(STATES_URL)

        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        for name in MANAGE_STATES:
            with self.subTest(state=name):
                self.assertIn(f'data-manage-state="{name}"', html)
        writes = [q['sql'] for q in queries.captured_queries if WRITE_SQL.match(q['sql'])]
        self.assertEqual(writes, [])
        self.assertFalse(Entry.objects.exists())
        for real_name in ('Michał', 'Ania', 'Ewa', 'Zosia', 'Tomek', 'Kuba'):
            self.assertNotIn(real_name, html)

    @override_settings(DEBUG=True)
    def test_states_carry_their_expected_markers(self):
        self.client.force_login(self.parent.user)
        html = self.client.get(STATES_URL).content.decode()

        expectations = {
            'list_upcoming': ['data-list-section="dated"', 'data-list-section="undated"',
                              'aria-current="page">Nadchodzące<', 'Bez daty</span>'],
            'list_past': ['data-list-section="past"', 'aria-current="page">Minione<'],
            'list_empty': ['Nie ma nadchodzących wpisów.'],
            'detail_manual': ['Ręcznie', 'Utworzono', 'Zmieniono', 'sprawdzian'],
            'detail_eduvulcan': ['EduVulcan', 'kartkówka'],
            'create': ['data-state-part="create-form"', 'name="submission_key"', 'Kasia'],
            'invalid': ['aria-invalid="true"', 'Popraw zaznaczone pola.',
                        'Ten element szkolny wymaga rodzaju'],
            'edit': ['data-state-part="edit-form"', 'Zapisz zmiany', 'value="s1" selected'],
            'delete_open': ['data-state-part="delete" open', 'Usuń na stałe'],
        }
        for name, markers in expectations.items():
            section = state_html(html, name)
            for marker in markers:
                with self.subTest(state=name, marker=marker):
                    self.assertIn(marker, section)
        self.assertNotIn('data-state-part="delete" open', state_html(html, 'detail_manual'))
        self.assertNotIn('name="submission_key"', state_html(html, 'edit'))

    @override_settings(DEBUG=True)
    def test_capture_states_still_render(self):
        self.client.force_login(self.parent.user)
        html = self.client.get(STATES_URL).content.decode()

        for name in ('empty', 'proposal', 'follow_up', 'unavailable', 'invalid', 'saved'):
            with self.subTest(state=name):
                self.assertIn(f'data-kitchen-state="{name}"', html)

    @override_settings(DEBUG=False)
    def test_gallery_is_not_found_without_debug(self):
        self.client.force_login(self.parent.user)

        self.assertEqual(self.client.get(STATES_URL).status_code, 404)

    @override_settings(DEBUG=True)
    def test_non_parents_are_denied(self):
        self.client.force_login(self.child.user)
        self.assertEqual(self.client.get(STATES_URL).status_code, 403)

        self.client.force_login(self.other_family_child.user)
        self.assertEqual(self.client.get(STATES_URL).status_code, 403)
