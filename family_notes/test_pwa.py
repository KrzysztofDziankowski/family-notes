"""Installable web app shell (S-06): manifest, service worker, offline page."""

import json
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.templatetags.static import static
from django.test import TestCase, override_settings
from django.urls import reverse

from family_access.models import Family, FamilyMember

MANIFEST_URL = reverse('web_manifest')
SW_URL = reverse('service_worker')
OFFLINE_URL = reverse('offline')
TOKENS_CSS = Path(settings.BASE_DIR) / 'family_notes' / 'static' / 'css' / 'tokens.css'
FORBIDDEN_PATHS = ('/entries/', '/api/', '/account/', '/accounts/', '/admin/')
FORBIDDEN_EVENTS = ('push', 'sync', 'periodicsync', 'notificationclick', 'message')
REGISTER_SCRIPT = (
    f'<script src="{static("js/pwa-register.js")}" data-sw-url="/sw.js" defer></script>'
)


def root_token(name):
    """A colour from the first ``:root`` block of tokens.css."""
    css = TOKENS_CSS.read_text(encoding='utf-8')
    block = re.search(r':root\s*\{(.*?)\}', css, re.DOTALL).group(1)
    return re.search(rf'--{name}:\s*([^;]+);', block).group(1).strip()


def static_path(url):
    """The static-files path behind a ``static()`` URL."""
    prefix = static('')
    assert url.startswith(prefix), url
    return url[len(prefix):]


class ParentFixtureMixin:
    def setUp(self):
        super().setUp()
        self.family = Family.objects.create(name='Rodzina PWA')
        self.user = get_user_model().objects.create_user(
            username='rodzic-pwa-81f3', email='rodzic-pwa@example.test'
        )
        self.parent = FamilyMember.objects.create(
            user=self.user,
            family=self.family,
            role=FamilyMember.Role.PARENT,
            display_name='Rodzic-PWA-81f3',
        )


class AnonymousRouteTests(TestCase):
    def test_routes_are_anonymous_with_exact_types_and_cache_headers(self):
        cases = {
            MANIFEST_URL: ('application/manifest+json', None),
            SW_URL: ('text/javascript; charset=utf-8', 'no-cache'),
            OFFLINE_URL: ('text/html; charset=utf-8', 'no-cache'),
        }
        for url, (content_type, cache_control) in cases.items():
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response['Content-Type'], content_type)
                if cache_control:
                    self.assertEqual(response['Cache-Control'], cache_control)

    def test_routes_live_at_the_site_root(self):
        self.assertEqual(MANIFEST_URL, '/manifest.webmanifest')
        self.assertEqual(SW_URL, '/sw.js')
        self.assertEqual(OFFLINE_URL, '/offline/')

    def test_head_works_for_smoke_checks_and_posts_are_refused(self):
        for url in (MANIFEST_URL, SW_URL, OFFLINE_URL):
            with self.subTest(url=url):
                self.assertEqual(self.client.head(url).status_code, 200)
                self.assertEqual(self.client.post(url).status_code, 405)


class ManifestTests(TestCase):
    def setUp(self):
        super().setUp()
        self.manifest = json.loads(self.client.get(MANIFEST_URL).content)

    def test_identity_scope_and_display(self):
        manifest = self.manifest
        self.assertEqual(manifest['name'], 'FamilyNotes')
        self.assertEqual(manifest['short_name'], 'FamilyNotes')
        self.assertEqual(manifest['description'], 'Wspólne notatki i sprawy rodziny')
        self.assertEqual(manifest['id'], '/')
        self.assertEqual(manifest['start_url'], '/')
        self.assertEqual(manifest['scope'], '/')
        self.assertEqual(manifest['display'], 'standalone')
        self.assertEqual(manifest['lang'], 'pl')
        self.assertEqual(manifest['dir'], 'ltr')
        # Locking orientation would fail WCAG 2.2 SC 1.3.4.
        self.assertNotIn('orientation', manifest)

    def test_colours_mirror_the_design_tokens(self):
        self.assertEqual(self.manifest['theme_color'], root_token('fn-color-accent'))
        self.assertEqual(self.manifest['background_color'], root_token('fn-color-bg'))

    def test_icons_resolve_through_the_static_finders(self):
        icons = {(icon['sizes'], icon['purpose']): icon for icon in self.manifest['icons']}
        self.assertEqual(
            set(icons), {('192x192', 'any'), ('512x512', 'any'), ('512x512', 'maskable')}
        )
        for key, icon in icons.items():
            with self.subTest(icon=key):
                self.assertEqual(icon['type'], 'image/png')
                path = finders.find(static_path(icon['src']))
                self.assertIsNotNone(path, icon['src'])
                size = int(key[0].split('x')[0])
                with open(path, 'rb') as image:
                    header = image.read(24)
                self.assertEqual(header[:8], b'\x89PNG\r\n\x1a\n')
                self.assertEqual(int.from_bytes(header[16:20], 'big'), size)
                self.assertEqual(int.from_bytes(header[20:24], 'big'), size)

    def test_svg_source_and_apple_touch_icon_resolve(self):
        for path in ('pwa/icon.svg', 'pwa/apple-touch-icon.png'):
            with self.subTest(path=path):
                self.assertIsNotNone(finders.find(path))


class ServiceWorkerSourceTests(TestCase):
    RELEASE = '20261005-abc1234'

    def source(self):
        with override_settings(FAMILY_NOTES_RELEASE_ID=self.RELEASE):
            return self.client.get(SW_URL).content.decode()

    def test_cache_name_follows_the_release(self):
        source = self.source()

        self.assertIn(f'var CACHE_NAME = "familynotes-shell-{self.RELEASE}";', source)
        self.assertIn('var CACHE_PREFIX = "familynotes-";', source)
        with override_settings(FAMILY_NOTES_RELEASE_ID='next-release'):
            self.assertIn('"familynotes-shell-next-release"', self.client.get(SW_URL).content.decode())

    def test_values_are_real_javascript_literals(self):
        source = self.source()

        self.assertIn('var OFFLINE_URL = "/offline/";', source)
        self.assertNotIn('&quot;', source)
        self.assertNotIn('{{', source)
        self.assertNotIn('{%', source)

    def test_precache_is_the_explicit_shell_list(self):
        source = self.source()

        match = re.search(r'var PRECACHE_URLS = (\[.*?\]);', source)
        self.assertIsNotNone(match)
        urls = json.loads(match.group(1))
        self.assertEqual(
            urls,
            [
                '/offline/',
                static('vendor/pico/pico.min.css'),
                static('css/tokens.css'),
                static('pwa/icon-192.png'),
            ],
        )
        for url in urls[1:]:
            with self.subTest(url=url):
                self.assertIsNotNone(finders.find(static_path(url)))
        self.assertIn("credentials: 'omit'", source)
        self.assertIn("cache: 'reload'", source)

    def test_non_get_requests_return_before_any_response_is_chosen(self):
        source = self.source()

        guard = re.search(
            r"if \(request\.method !== 'GET'\) \{\s*(?://[^\n]*\s*)?return;\s*\}", source
        )
        self.assertIsNotNone(guard)
        fetch_handler = source.index("addEventListener('fetch'")
        self.assertLess(fetch_handler, guard.start())
        self.assertLess(guard.start(), source.index('respondWith', fetch_handler))

    def test_nothing_is_stored_at_runtime_and_no_push_or_sync(self):
        source = self.source()

        self.assertNotIn('cache.put', source)
        self.assertNotIn('.put(', source)
        self.assertNotIn('indexedDB', source)
        self.assertNotIn('localStorage', source)
        for event in FORBIDDEN_EVENTS:
            with self.subTest(event=event):
                self.assertNotRegex(source, rf"""addEventListener\(\s*['"]{event}['"]""")
                self.assertNotRegex(source, rf'\bon{event}\b')
        for path in FORBIDDEN_PATHS:
            with self.subTest(path=path):
                self.assertNotIn(path, source)


class OfflinePageTests(ParentFixtureMixin, TestCase):
    COPY = (
        'Nie możesz teraz połączyć się z FamilyNotes. Sprawdź połączenie z internetem. '
        'Twoje wpisy nie są zapisywane na tym urządzeniu.'
    )

    def test_polish_copy_and_actions(self):
        response = self.client.get(OFFLINE_URL)

        self.assertContains(response, '<h1>Brak połączenia</h1>', html=True)
        self.assertContains(response, self.COPY)
        self.assertContains(response, '<a href="">Spróbuj ponownie</a>', html=True)
        self.assertContains(response, f'<a href="{reverse("home")}">Strona główna</a>', html=True)

    def test_signed_in_parent_sees_nothing_personal(self):
        self.client.force_login(self.user)

        response = self.client.get(OFFLINE_URL)

        self.assertContains(response, self.COPY)
        for text in ('rodzic-pwa-81f3', 'Rodzic-PWA-81f3', 'Rodzina PWA', 'Wyloguj', 'Konto'):
            with self.subTest(text=text):
                self.assertNotContains(response, text)
        self.assertNotContains(response, 'csrfmiddlewaretoken')
        self.assertNotContains(response, reverse('account_logout'))


class LayoutWiringTests(ParentFixtureMixin, TestCase):
    def assert_wired(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'<link rel="manifest" href="{MANIFEST_URL}">', html=True)
        self.assertContains(
            response,
            f'<link rel="apple-touch-icon" href="{static("pwa/apple-touch-icon.png")}">',
            html=True,
        )
        self.assertContains(
            response, f'<link rel="icon" href="{static("pwa/icon-192.png")}">', html=True
        )
        self.assertContains(response, REGISTER_SCRIPT, html=True)
        self.assertNotContains(response, 'name="theme-color"')

    def test_login_page_is_wired(self):
        self.assert_wired(self.client.get(reverse('account_login')))

    def test_parent_entry_list_is_wired(self):
        self.client.force_login(self.user)

        self.assert_wired(self.client.get(reverse('entries:index')))

    def test_registration_script_resolves(self):
        self.assertIsNotNone(finders.find('js/pwa-register.js'))
