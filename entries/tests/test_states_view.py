from unittest import mock

from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from entries import views
from entries.models import Entry

from .classification_progress_markup import SCRIPT_URL as PROGRESS_SCRIPT_URL
from .classification_progress_markup import (
    ANY_ONE,
    STATE_COPY,
    assert_progress_regions,
    progress_forms,
)
from .enter_submit_markup import SCRIPT_URL as ENTER_SCRIPT_URL
from .enter_submit_markup import assert_enter_assets, assert_enter_never_saves
from .test_classification_service import WRITE_PREFIXES, FamilyFixtureMixin

STATES_URL = reverse('entries:states')
STATE_NAMES = (
    'empty',
    'proposal',
    'proposal_private',
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
    'corrected',
    'correction_failed',
    'invalid',
    'saved',
    'saved_private',
    'batch',
    'batch_duplicate',
    'batch_missing',
    'batch_invalid',
    'batch_corrected',
    'batch_saved',
    'too_many',
)
PROGRESS_STATES = ('running', 'slow', 'stalled', 'offline', 'connection_lost')


class StatesKitchenSinkTests(FamilyFixtureMixin, TestCase):
    @override_settings(DEBUG=False)
    def test_not_found_without_debug(self):
        self.client.force_login(self.parent.user)

        self.assertEqual(self.client.get(STATES_URL).status_code, 404)

    @override_settings(DEBUG=True)
    def test_parent_sees_every_state_without_writes_or_backend_calls(self):
        self.client.force_login(self.parent.user)

        with (
            mock.patch('entries.views.classify_entries_for_parent') as classify,
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
        self.assertContains(response, 'Zaktualizowano: data wydarzenia.')
        self.assertContains(response, views.CORRECTION_FAILED_NOTICE)
        self.assertContains(response, 'Spotkanie z wychowawczynią')
        self.assertContains(response, 'bla bla</textarea>')
        self.assertContains(response, 'Popraw opis')
        self.assertContains(response, 'Kasia')
        # S-07: a fictional parent is offered alongside the children.
        self.assertContains(response, '<option value="s3">Marta</option>', html=True)
        self.assertContains(response, 'Sprawdź wpisy (3)')
        self.assertContains(response, 'Taki sam jak wpis 1.')
        self.assertContains(response, 'Wybierz co najmniej jeden wpis.')
        self.assertContains(response, 'Wpis 2: zaktualizowano: godzina.')
        self.assertContains(response, 'Dodano wpisy (3)')
        self.assertContains(response, views.TOO_MANY_ENTRIES_NOTICE)
        self.assertContains(response, 'id="id_e1-date-hint"')
        self.assertContains(response, 'id="e2-correct-submit"')
        for real_name in ('Michał', 'Ania', 'Ewa'):
            self.assertNotContains(response, real_name)
        classify.assert_not_called()
        classify_answer.assert_not_called()
        self.assertFalse(Entry.objects.exists())

    @override_settings(DEBUG=True)
    def test_gallery_loads_the_enter_script_and_never_saves_on_enter(self):
        self.client.force_login(self.parent.user)

        response = self.client.get(STATES_URL)

        assert_enter_assets(
            self, response, ['id_text', 'id_answer', 'id_correction', 'id_e0-correction']
        )
        self.assertGreater(assert_enter_never_saves(self, response.content.decode()), 0)

    @override_settings(DEBUG=True)
    def test_gallery_loads_both_scripts_and_every_live_region_is_rendered(self):
        self.client.force_login(self.parent.user)

        response = self.client.get(STATES_URL)

        self.assertContains(response, f'<script src="{PROGRESS_SCRIPT_URL}" defer></script>', html=True)
        self.assertContains(response, f'<script src="{ENTER_SCRIPT_URL}" defer></script>', html=True)
        self.assertContains(response, 'data-progress-slow-after="10"')
        self.assertContains(response, 'data-progress-stalled-after="35"')
        self.assertNotContains(response, 'data-progress-slow-after=""')
        self.assertGreater(
            assert_progress_regions(self, response.content.decode(), visible=ANY_ONE), 0
        )

    @override_settings(DEBUG=True)
    def test_progress_states_render_statically_without_writes(self):
        self.client.force_login(self.parent.user)

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(STATES_URL)

        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        for state in PROGRESS_STATES:
            with self.subTest(state=state):
                marker = f'data-kitchen-state="progress_{state}"'
                self.assertIn(marker, html)
                start = html.index(marker)
                section = html[start:html.index('</section>', start)]
                self.assertIn(STATE_COPY[state], section)
                self.assertEqual(assert_progress_regions(self, section, visible=state), 1)
                [form] = progress_forms(section)
                [submit] = form['buttons']
                busy = state in ('running', 'slow')
                self.assertEqual(submit['attrs'].get('aria-busy') == 'true', busy)
                elapsed_hidden = 'data-progress-elapsed aria-hidden="true" hidden' in section
                self.assertEqual(elapsed_hidden, not busy)
                self.assertIn('Kasia ma jutro sprawdzian z matematyki</textarea>', section)
        self.assertContains(
            response,
            f'<a href="{reverse("offline")}" data-kitchen-link="offline">Brak połączenia</a>',
            html=True,
        )
        writes = [
            query['sql']
            for query in queries.captured_queries
            if query['sql'].lstrip().upper().startswith(WRITE_PREFIXES)
            and 'django_session' not in query['sql']
        ]
        self.assertEqual(writes, [])
        self.assertFalse(Entry.objects.exists())

    @override_settings(DEBUG=True)
    def test_only_progress_sections_show_a_progress_state(self):
        self.client.force_login(self.parent.user)

        html = self.client.get(STATES_URL).content.decode()

        for name in STATE_NAMES:
            with self.subTest(state=name):
                marker = f'data-kitchen-state="{name}"'
                start = html.index(marker)
                section = html[start:html.index('</section>', start)]
                assert_progress_regions(self, section)
                self.assertNotIn('aria-busy', section)

    @override_settings(DEBUG=True)
    def test_child_is_forbidden_and_anonymous_is_redirected(self):
        self.client.force_login(self.child.user)
        self.assertEqual(self.client.get(STATES_URL).status_code, 403)

        self.client.logout()
        response = self.client.get(STATES_URL)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('account_login'), response['Location'])
