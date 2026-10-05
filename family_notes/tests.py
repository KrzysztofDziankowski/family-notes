from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import DatabaseError
from django.conf import settings
from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from entries.models import Entry
from family_notes.log_safety import exception_summary
from entries.tests.test_classification_service import FamilyFixtureMixin


class RootRouteTests(FamilyFixtureMixin, TestCase):
    def test_root_redirects_each_visitor_to_their_home(self):
        unconfigured = get_user_model().objects.create_user(username='unconfigured')
        cases = {
            'anonymous': (None, reverse('account_login')),
            'child': (self.child.user, '/entries/mine/'),
            'parent': (self.parent.user, '/entries/'),
            'no membership': (unconfigured, '/account/'),
        }
        for name, (user, expected) in cases.items():
            with self.subTest(name):
                self.client.logout()
                if user is not None:
                    self.client.force_login(user)

                response = self.client.get(reverse('home'))

                self.assertRedirects(response, expected, fetch_redirect_response=False)

    def test_login_redirects_to_root(self):
        self.assertEqual(settings.LOGIN_REDIRECT_URL, '/')
        self.assertEqual(settings.LOGOUT_REDIRECT_URL, '/')

    def test_account_status_requires_authentication(self):
        response = self.client.get(reverse('account_status'))

        self.assertRedirects(
            response,
            f"{reverse('account_login')}?next={reverse('account_status')}",
        )

    def test_admin_redirects_unauthenticated_users_to_admin_login(self):
        response = self.client.get(reverse('admin:index'))

        self.assertRedirects(response, f"{reverse('admin:login')}?next=/admin/",
                             fetch_redirect_response=False)

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
            fetch_redirect_response=False,
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


class LoginPageTests(TestCase):
    def test_login_page_uses_app_layout_and_offers_google_first(self):
        response = self.client.get(reverse('account_login'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'account/login.html')
        self.assertTemplateUsed(response, 'base.html')
        self.assertContains(response, 'css/tokens.css')
        self.assertContains(response, '<h1>Zaloguj się</h1>', html=True)
        self.assertContains(response, 'Zaloguj przez Google')
        self.assertContains(response, '/accounts/google/login/')
        self.assertNotContains(response, 'Wyloguj')
        self.assertNotContains(response, 'Menu:')
        body = response.content.decode()
        self.assertLess(body.index('/accounts/google/login/'), body.index('name="password"'))

    def test_google_link_preserves_next(self):
        response = self.client.get(reverse('account_login'), {'next': '/entries/mine/'})

        self.assertContains(response, '/accounts/google/login/?next=%2Fentries%2Fmine%2F')

    def test_login_page_offers_no_sign_up_option(self):
        response = self.client.get(reverse('account_login'))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, reverse('account_signup'))
        body = response.content.decode().lower()
        for stem in ('zarejestruj', 'rejestracj', 'sign up'):
            with self.subTest(stem=stem):
                self.assertNotIn(stem, body)
        self.assertContains(response, 'name="password"')


class ErrorPageTests(FamilyFixtureMixin, TestCase):
    def test_parent_on_child_list_gets_polish_403_in_base_layout(self):
        self.client.force_login(self.parent.user)

        response = self.client.get(reverse('entries:child_list'))

        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, '403.html')
        self.assertTemplateUsed(response, 'base.html')
        self.assertContains(response, 'Brak dostępu', status_code=403)
        self.assertContains(response, 'css/tokens.css', status_code=403)
        self.assertContains(response, 'Wróć na stronę główną', status_code=403)
        self.assertContains(response, f'href="{reverse("home")}"', status_code=403)

    def test_foreign_and_missing_entries_get_identical_polish_404(self):
        foreign = Entry.objects.create(
            family=self.other_family,
            entry_type='note',
            content='SENTINEL-FOREIGN',
            assigned_member=self.other_family_child,
        )
        missing_pk = foreign.pk + 100
        self.client.force_login(self.child.user)

        responses = [
            self.client.get(reverse('entries:child_detail', args=[pk]))
            for pk in (foreign.pk, missing_pk)
        ]

        for response in responses:
            self.assertEqual(response.status_code, 404)
            self.assertTemplateUsed(response, '404.html')
            self.assertContains(response, 'Nie znaleziono', status_code=404)
            self.assertNotContains(response, 'SENTINEL', status_code=404)
        self.assertEqual(responses[0].content, responses[1].content)

    def test_anonymous_404_shows_only_the_brand(self):
        response = self.client.get('/does-not-exist/')

        self.assertContains(response, 'Nie znaleziono', status_code=404)
        self.assertNotContains(response, 'Wyloguj', status_code=404)
        self.assertNotContains(response, 'Konto', status_code=404)

    def test_500_renders_without_context(self):
        body = render_to_string('500.html')

        self.assertIn('css/tokens.css', body)
        self.assertIn('href="/"', body)


class HealthCheckTests(TestCase):
    def test_health_check_succeeds_when_database_is_available(self):
        response = self.client.get(reverse('healthz'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'ok'})
        self.assertEqual(response.content, b'{"status": "ok"}')

    @patch('family_notes.views.connection.cursor', side_effect=DatabaseError)
    def test_health_check_hides_database_failure_details(self, _cursor):
        response = self.client.get(reverse('healthz'))

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {'status': 'unavailable'})


class LocaleSettingsTests(SimpleTestCase):
    def test_project_uses_polish_locale_and_time(self):
        self.assertEqual(settings.LANGUAGE_CODE, 'pl')
        self.assertEqual(settings.TIME_ZONE, 'Europe/Warsaw')
        self.assertTrue(settings.USE_TZ)


class ExceptionSummaryTests(SimpleTestCase):
    def _raised(self, raise_it):
        try:
            raise_it()
        except Exception as exc:
            return exc
        self.fail('expected an exception')

    def test_names_class_and_location_but_never_the_message(self):
        def fail():
            raise RuntimeError('SECRET family text')

        summary = exception_summary(self._raised(fail))

        self.assertTrue(summary.startswith('RuntimeError stack=family_notes/tests.py:'))
        self.assertIn(':fail', summary)
        self.assertNotIn('SECRET', summary)

    def test_follows_a_cause_suppressed_with_from_none(self):
        class Driver(Exception):
            sqlstate = '0A000'

        def fail():
            try:
                raise Driver('SECRET key value')
            except Driver:
                raise DatabaseError('SECRET wrapper') from None

        summary = exception_summary(self._raised(fail))

        self.assertTrue(summary.startswith('DatabaseError stack='))
        self.assertIn(' <- caused by Driver sqlstate=0A000 stack=', summary)
        self.assertNotIn('SECRET', summary)


SKIP_LINK = '<a class="fn-skip-link" href="#main">Przejdź do treści</a>'


class SkipLinkTests(FamilyFixtureMixin, TestCase):
    """Every layout starts with a skip link to ``<main id="main">`` (S-17, WCAG 2.4.1)."""

    def assert_skip_link_first(self, body):
        self.assertIn(SKIP_LINK, body)
        self.assertIn('<main id="main" class="container" tabindex="-1">', body)
        after_body = body[body.index('<body'):]
        self.assertLess(after_body.index(SKIP_LINK), after_body.index('<nav'))
        self.assertTrue(after_body.split('<a ', 1)[1].startswith('class="fn-skip-link"'))

    def test_layout_pages_start_with_the_skip_link(self):
        cases = (
            ('login', None, reverse('account_login'), 200),
            ('parent list', self.parent, reverse('entries:index'), 200),
            ('child list', self.child, reverse('entries:child_list'), 200),
            ('403', self.parent, reverse('entries:child_list'), 403),
            ('anonymous 404', None, '/does-not-exist/', 404),
        )
        for name, member, url, status in cases:
            with self.subTest(name):
                self.client.logout()
                if member is not None:
                    self.client.force_login(member.user)
                response = self.client.get(url)
                self.assertEqual(response.status_code, status)
                self.assert_skip_link_first(response.content.decode())

    def test_500_has_its_own_skip_link(self):
        self.assert_skip_link_first(render_to_string('500.html'))
