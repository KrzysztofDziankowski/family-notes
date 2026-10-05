"""S-17 structural accessibility audit of the S-16 family chooser, header switcher and 409 page.

Each case renders a real response and must pass ``assert_accessible``; see
``context/foundation/accessibility.md``.
"""

from django.test import TestCase
from django.urls import reverse

from family_access.context import FORM_FIELD
from family_notes.a11y_audit import assert_accessible

from .test_family_context import CHOOSER_URL, MultiFamilyFixtureMixin


class FamilyContextAccessibilityTests(MultiFamilyFixtureMixin, TestCase):
    def test_chooser_with_two_memberships(self):
        self.sign_in()

        response = self.client.get(CHOOSER_URL)

        self.assertContains(response, '<legend>Rodzina</legend>')
        assert_accessible(self, response)

    def test_chooser_after_an_invalid_choice(self):
        self.sign_in()

        response = self.client.post(CHOOSER_URL, {})

        self.assertContains(response, 'role="alert"')
        self.assertContains(response, 'aria-describedby="id_family_id_error"')
        self.assertContains(response, '<title>Błąd: Wybierz rodzinę')
        assert_accessible(self, response)

    def test_product_page_with_the_header_switcher(self):
        self.sign_in(self.family_a)

        for url in (reverse('entries:index'), reverse('entries:capture')):
            with self.subTest(url):
                response = self.client.get(url)

                self.assertContains(response, 'Zmień rodzinę')
                assert_accessible(self, response)

    def test_two_family_header_uses_the_wrapping_nav(self):
        # SC 1.4.10: the wrap rule lives on .fn-site-nav (family_notes/test_tokens_rules.py).
        self.sign_in(self.family_a)

        for url in (reverse('entries:index'), CHOOSER_URL):
            with self.subTest(url):
                response = self.client.get(url)

                self.assertContains(response, 'Zmień rodzinę')
                self.assertContains(
                    response, '<nav class="fn-site-nav" aria-label="Główna nawigacja">', count=1
                )

    def test_stale_tab_409_page(self):
        self.sign_in(self.family_b)

        response = self.client.post(
            reverse('entries:create'), {FORM_FIELD: str(self.family_a.pk)}
        )

        self.assertEqual(response.status_code, 409)
        self.assertContains(response, '<h1>', count=1, status_code=409)
        self.assertTemplateUsed(response, 'base.html')
        assert_accessible(self, response)
