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
            'detail_manual': ['Ręcznie', 'Utworzono', 'Zmieniono', 'sprawdzian',
                              '<dt>Przedmiot</dt>', 'historia'],
            'detail_eduvulcan': ['EduVulcan', 'kartkówka', '<dt>Przedmiot</dt>', 'matematyka'],
            'create': ['data-state-part="create-form"', 'name="submission_key"', 'Kasia'],
            'invalid': ['aria-invalid="true"', 'Popraw zaznaczone pola.',
                        'Ten element szkolny wymaga rodzaju'],
            'edit': ['data-state-part="edit-form"', 'Zapisz zmiany', 'value="s1" selected',
                     'name="school_subject"', 'value="historia"'],
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


class ParentAssigneeGalleryTests(FamilyFixtureMixin, TestCase):
    """S-07: the gallery shows a fictional parent as an option and as an assignee."""

    @override_settings(DEBUG=True)
    def test_parent_appears_in_create_options_and_upcoming_list(self):
        self.client.force_login(self.parent.user)
        html = self.client.get(STATES_URL).content.decode()

        option = '<option value="s3">Marta</option>'
        for name in ('create', 'invalid'):
            with self.subTest(state=name):
                self.assertIn(option, state_html(html, name))
        upcoming = state_html(html, 'list_upcoming')
        self.assertIn('Odebrać paczkę z paczkomatu', upcoming)
        # S-08: the assignee is named by the row's group heading, not the row.
        group = assignee_group_of(upcoming, 'Odebrać paczkę z paczkomatu')
        self.assertIn('<h2 class="fn-manage-section-title">Marta</h2>', group)


GROUP_PATTERN = re.compile(r'data-assignee-group="([\w-]+)"')
HEADING_PATTERN = re.compile(r'<h2 class="fn-manage-section-title">([^<]*)</h2>')


def assignee_group_of(html, text):
    """The ``data-assignee-group`` block that contains ``text``."""
    position = html.index(text)
    start = html.rindex('data-assignee-group="', 0, position)
    end = html.find('data-assignee-group="', position)
    return html[start:end if end != -1 else len(html)]


class GroupedListGalleryTests(FamilyFixtureMixin, TestCase):
    """S-08: the gallery lists show assignee groups for the screenshot gate."""

    @override_settings(DEBUG=True)
    def test_upcoming_state_groups_children_then_parent_then_family(self):
        self.client.force_login(self.parent.user)
        html = self.client.get(STATES_URL).content.decode()

        upcoming = state_html(html, 'list_upcoming')
        self.assertEqual(
            GROUP_PATTERN.findall(upcoming),
            ['member-900101', 'member-900102', 'member-900103', 'family'],
        )
        self.assertEqual(
            HEADING_PATTERN.findall(upcoming), ['Kasia', 'Tymek', 'Marta', 'Cała rodzina']
        )
        for text, heading in (
            ('Sprawdzian z historii o średniowieczu', 'Kasia'),
            ('Wycieczka klasowa do muzeum techniki', 'Tymek'),
            ('Oddać książkę do biblioteki', 'Cała rodzina'),
        ):
            with self.subTest(text=text):
                group = assignee_group_of(upcoming, text)
                self.assertIn(f'<h2 class="fn-manage-section-title">{heading}</h2>', group)
        self.assertIn('<h3 class="fn-manage-subsection-title">Bez daty</h3>', upcoming)

    @override_settings(DEBUG=True)
    def test_past_and_empty_states_keep_their_shape(self):
        self.client.force_login(self.parent.user)
        html = self.client.get(STATES_URL).content.decode()

        past = state_html(html, 'list_past')
        self.assertEqual(GROUP_PATTERN.findall(past), ['family'])
        self.assertNotIn('fn-manage-subsection-title', past)
        self.assertEqual(GROUP_PATTERN.findall(state_html(html, 'list_empty')), [])
