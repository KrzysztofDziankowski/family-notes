"""Accessibility audit (S-17): the helper's rules and the project-wide pages.

The flow pages (capture, management, child view) are audited in
``entries.tests.test_accessibility``.
"""

import json

from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from entries.tests.test_classification_service import FamilyFixtureMixin
from family_notes.a11y_audit import assert_accessible, audit_page


def page(body, *, lang='pl', title='Strona', head=''):
    """A minimal page around ``body``: skip link, one <main id="main"> and one h1 unless given."""
    return (
        f'<!doctype html><html lang="{lang}"><head><title>{title}</title>{head}</head><body>'
        f'<a class="fn-skip-link" href="#main">Przejdź do treści</a>'
        f'<main id="main">{body}</main></body></html>'
    )


H1 = '<h1>Nagłówek</h1>'


class AuditRuleTests(SimpleTestCase):
    """One passing and one failing snippet per rule."""

    def assert_passes(self, html):
        self.assertEqual(audit_page(html), [])

    def assert_fails(self, html, fragment):
        violations = audit_page(html)
        self.assertTrue(
            any(fragment in violation for violation in violations),
            f'{fragment!r} not in {violations}',
        )

    def test_language(self):
        self.assert_passes(page(H1))
        self.assert_fails(page(H1, lang='en'), 'lang="pl"')

    def test_title(self):
        self.assert_passes(page(H1))
        self.assert_fails(page(H1, title='  '), '<title>')

    def test_one_main(self):
        self.assert_passes(page(H1))
        self.assert_fails(page(H1 + '<main>druga</main>'), 'exactly one <main>')

    def test_one_h1(self):
        self.assert_passes(page(H1 + '<h2>Sekcja</h2>'))
        self.assert_fails(page(H1 + '<h1>Drugi</h1>'), 'exactly one <h1>')
        self.assert_fails(page('<h2>Sekcja</h2>'), 'exactly one <h1>')

    def test_no_skipped_heading_levels(self):
        self.assert_passes(page(H1 + '<h2>A</h2><h3>B</h3><h2>C</h2>'))
        self.assert_fails(page(H1 + '<h3>B</h3>'), 'heading level skipped')

    def test_first_focusable_is_a_skip_link(self):
        self.assert_passes(page(H1 + '<a href="/x">Dalej</a>'))
        no_skip = (
            '<html lang="pl"><head><title>T</title></head><body>'
            '<a href="/">FamilyNotes</a><main id="main">' + H1 + '</main></body></html>'
        )
        self.assert_fails(no_skip, 'must be a skip link')
        broken = page(H1).replace('href="#main"', 'href="#tresc"')
        self.assert_fails(broken, 'skip link points at a missing id')

    def test_unique_ids(self):
        self.assert_passes(page(H1 + '<p id="a">A</p><p id="b">B</p>'))
        self.assert_fails(page(H1 + '<p id="a">A</p><p id="a">B</p>'), 'duplicate id "a"')

    def test_references_resolve(self):
        self.assert_passes(page(
            H1 + '<p id="d">Opis</p><label for="f">Pole</label>'
            '<input id="f" aria-describedby="d"><a href="#d">Do opisu</a>'
        ))
        self.assert_fails(
            page(H1 + '<label for="f">Pole</label><input id="f" aria-describedby="brak">'),
            'aria-describedby points at a missing id: brak',
        )
        self.assert_fails(
            page(H1 + '<section aria-labelledby="brak">x</section>'),
            'aria-labelledby points at a missing id: brak',
        )
        self.assert_fails(page(H1 + '<a href="#brak">Link</a>'), 'links to a missing id')

    def test_fields_have_labels(self):
        self.assert_passes(page(
            H1 + '<label for="a">A</label><textarea id="a"></textarea>'
            '<select aria-label="B"></select><label><input type="checkbox"> C</label>'
            '<input type="hidden" name="key"><input type="submit" value="Wyślij">'
        ))
        self.assert_fails(page(H1 + '<input id="a" name="a">'), 'field without a label')

    def test_invalid_fields_have_a_description(self):
        self.assert_passes(page(
            H1 + '<label for="a">A</label><input id="a" aria-invalid="true" aria-describedby="a_error">'
            '<small id="a_error">Błąd.</small>'
        ))
        self.assert_fails(
            page(H1 + '<label for="a">A</label><input id="a" aria-invalid="true">'),
            'invalid field without a resolvable description',
        )
        self.assert_fails(
            page(
                H1 + '<label for="a">A</label><input id="a" aria-invalid="true" '
                'aria-describedby="a_error"><small id="a_error"> </small>'
            ),
            'invalid field without a resolvable description',
        )

    def test_links_and_buttons_have_names(self):
        self.assert_passes(page(
            H1 + '<a href="/x">Edytuj<span class="fn-visually-hidden">: wpis</span></a>'
            '<button aria-label="Zamknij"></button>'
        ))
        self.assert_fails(page(H1 + '<a href="/x"> </a>'), 'has no text or aria-label')
        self.assert_fails(page(H1 + '<button type="button"></button>'), 'has no text or aria-label')

    def test_no_positive_tabindex(self):
        self.assert_passes(page(H1 + '<div tabindex="-1">x</div><div tabindex="0">y</div>'))
        self.assert_fails(page(H1 + '<div tabindex="2">x</div>'), 'positive tabindex')

    def test_at_most_one_autofocus(self):
        field = '<label for="{0}">{0}</label><input id="{0}"{1}>'
        self.assert_passes(page(H1 + field.format('a', ' autofocus') + field.format('b', '')))
        self.assert_fails(
            page(H1 + field.format('a', ' autofocus') + field.format('b', ' autofocus')),
            'autofocus',
        )

    def test_static_status_panels_need_visible_text(self):
        self.assert_passes(page(H1 + '<div role="status"><p>Dodano wpis.</p></div>'))
        self.assert_passes(page(H1 + '<div role="alert"><p>Popraw pola.</p></div>'))
        self.assert_fails(page(H1 + '<div role="status"></div>'), 'has no visible text')
        self.assert_fails(
            page(H1 + '<div role="alert"><p hidden>Ukryty błąd</p></div>'), 'has no visible text'
        )

    def test_script_updated_live_region_needs_a_hidden_state_block(self):
        self.assert_passes(page(
            H1 + '<div role="status" aria-live="polite" data-live-region>'
            '<div data-progress-state="running" hidden><p>Rozpoznaję wpis…</p></div></div>'
        ))
        self.assert_fails(
            page(H1 + '<div role="status" aria-live="polite" data-live-region></div>'),
            'no hidden state block with text',
        )
        self.assert_fails(
            page(
                H1 + '<div role="status" aria-live="polite" data-live-region>'
                '<div hidden></div></div>'
            ),
            'no hidden state block with text',
        )

    def test_live_region_marker_needs_aria_live(self):
        self.assert_fails(
            page(H1 + '<div role="status" data-live-region><div hidden><p>x</p></div></div>'),
            'has no visible text',
        )


class ProjectPagesAuditTests(FamilyFixtureMixin, TestCase):
    """Sign-in, account status, error pages and the offline page (S-06)."""

    def test_login(self):
        assert_accessible(self, self.client.get(reverse('account_login')))

    def test_login_with_errors(self):
        response = self.client.post(
            reverse('account_login'), {'login': 'nikt@example.test', 'password': 'zle-haslo'}
        )
        self.assertEqual(response.status_code, 200)
        assert_accessible(self, response)

    def test_account_status_for_parent_child_and_unconfigured(self):
        unconfigured = get_user_model().objects.create_user(username='unconfigured')
        for name, user in (
            ('parent', self.parent.user),
            ('child', self.child.user),
            ('unconfigured', unconfigured),
        ):
            with self.subTest(name):
                self.client.force_login(user)
                response = self.client.get(reverse('account_status'))
                self.assertEqual(response.status_code, 200)
                assert_accessible(self, response)

    def test_403(self):
        self.client.force_login(self.parent.user)
        response = self.client.get(reverse('entries:child_list'))
        self.assertEqual(response.status_code, 403)
        assert_accessible(self, response)

    def test_404_for_authenticated_and_anonymous(self):
        for name, user in (('anonymous', None), ('child', self.child.user)):
            with self.subTest(name):
                self.client.logout()
                if user is not None:
                    self.client.force_login(user)
                response = self.client.get('/does-not-exist/')
                self.assertEqual(response.status_code, 404)
                assert_accessible(self, response)

    def test_offline_for_anonymous_and_authenticated(self):
        for name, user in (('anonymous', None), ('parent', self.parent.user)):
            with self.subTest(name):
                self.client.logout()
                if user is not None:
                    self.client.force_login(user)
                response = self.client.get(reverse('offline'))
                self.assertEqual(response.status_code, 200)
                assert_accessible(self, response)

    def test_500(self):
        assert_accessible(self, render_to_string('500.html'))

    def test_manifest_does_not_lock_orientation(self):
        """WCAG 2.2 SC 1.3.4: content is not restricted to one orientation."""
        manifest = json.loads(self.client.get(reverse('web_manifest')).content)

        self.assertIn(manifest.get('orientation', 'any'), ('any',))
