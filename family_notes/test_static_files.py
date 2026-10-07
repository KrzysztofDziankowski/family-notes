"""Content-hashed static files outside DEBUG (cache busting after a release).

Production serves /static/ with a long browser cache, so an unchanged URL let phones keep
the previous release's tokens.css for hours. Outside DEBUG, ManifestStaticFilesStorage gives
every collected file a content-hashed name, and its strict manifest turns a reference to a
file that does not exist into a server error, so every reference must resolve.
"""

import json
import re
import tempfile
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles import finders, storage
from django.core.management import call_command
from django.templatetags.static import static
from django.test import SimpleTestCase, override_settings

MANIFEST_STORAGES = {
    **settings.STORAGES,
    'staticfiles': {
        'BACKEND': 'django.contrib.staticfiles.storage.ManifestStaticFilesStorage',
    },
}
SOURCE_DIRS = ('family_notes', 'entries', 'family_access')
TEMPLATE_STATIC = re.compile(r"""\{%\s*static\s+['"]([^'"]+)['"]""")
PYTHON_STATIC = re.compile(r"""\bstatic\(\s*['"]([^'"]+)['"]\s*\)""")
PRECACHE_BLOCK = re.compile(r'PWA_PRECACHE_STATIC = \((.*?)\)', re.DOTALL)


def referenced_static_paths():
    """Every literal static path named by project templates and Python code."""
    base = Path(settings.BASE_DIR)
    paths = set()
    for directory in SOURCE_DIRS:
        for template in (base / directory).rglob('*.html'):
            paths.update(TEMPLATE_STATIC.findall(template.read_text(encoding='utf-8')))
        for module in (base / directory).rglob('*.py'):
            if module.name.startswith('test'):
                continue
            source = module.read_text(encoding='utf-8')
            paths.update(PYTHON_STATIC.findall(source))
            for block in PRECACHE_BLOCK.findall(source):
                paths.update(re.findall(r"""['"]([^'"]+)['"]""", block))
    return paths


class StaticReferenceTests(SimpleTestCase):
    def test_every_referenced_static_file_exists(self):
        paths = referenced_static_paths()
        self.assertIn('css/tokens.css', paths)
        self.assertIn('pwa/icon-512.png', paths)
        for path in sorted(paths):
            with self.subTest(path=path):
                self.assertIsNotNone(finders.find(path), f'{path} is not a static file')


class ManifestStorageTests(SimpleTestCase):
    def test_debug_off_uses_hashed_storage_and_debug_on_plain_names(self):
        # settings.STORAGES is chosen from DJANGO_DEBUG at import time (on for the suite;
        # the test runner only flips settings.DEBUG afterwards).
        self.assertEqual(
            settings.STORAGES['staticfiles']['BACKEND'],
            'django.contrib.staticfiles.storage.StaticFilesStorage',
        )
        source = (Path(settings.BASE_DIR) / 'family_notes' / 'settings.py').read_text(encoding='utf-8')
        self.assertRegex(
            source,
            r"'django\.contrib\.staticfiles\.storage\.StaticFilesStorage'\s*"
            r"if DEBUG\s*else 'django\.contrib\.staticfiles\.storage\.ManifestStaticFilesStorage'",
        )

    def test_collectstatic_links_pages_to_content_hashed_files(self):
        with tempfile.TemporaryDirectory() as root:
            # Overriding STORAGES makes Django rebuild staticfiles_storage, before and after.
            with override_settings(STORAGES=MANIFEST_STORAGES, STATIC_ROOT=root):
                self.assertIsInstance(storage.staticfiles_storage, storage.ManifestStaticFilesStorage)
                call_command('collectstatic', interactive=False, verbosity=0)
                manifest = json.loads((Path(root) / 'staticfiles.json').read_text())['paths']
                for path in sorted(referenced_static_paths()):
                    with self.subTest(path=path):
                        self.assertIn(path, manifest)
                        self.assertEqual(static(path), f'/static/{manifest[path]}')
                self.assertRegex(manifest['css/tokens.css'], r'^css/tokens\.[0-9a-f]{12}\.css$')
        self.assertEqual(static('css/tokens.css'), '/static/css/tokens.css')
