"""Database cache contracts and disposable PostgreSQL process evidence."""
import os
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest import skipUnless
from unittest.mock import patch

from django.conf import settings
from django.core.cache import cache
from django.db import OperationalError, connection
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from family_notes import test_auth_security
from family_notes.auth_cache import AuthCacheUnavailable

DB_CACHE = {'default': {'BACKEND': 'family_notes.auth_cache.DatabaseAuthCache',
                        'LOCATION': 'family-notes-auth', 'KEY_PREFIX': 'family_notes_auth'}}
REQUIRED = os.getenv('AUTH_REHEARSAL_REQUIRED') == '1'


@override_settings(CACHES=DB_CACHE)
class DatabaseOperatorRecoveryTests(test_auth_security.AdminSecurityTests):
    """Run request/recovery policy against database state in the default suite."""


@override_settings(CACHES=DB_CACHE)
class DatabaseCacheTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_atomic_add_does_not_overwrite_and_expired_lock_can_be_replaced(self):
        self.assertTrue(cache.add('lock', True, 30))
        self.assertFalse(cache.add('lock', False, 30))
        self.assertIs(cache.get('lock'), True)
        cache.set('expired', [1], -1)
        self.assertTrue(cache.add('expired', [2], 30))
        self.assertEqual(cache.get('expired'), [2])

    def test_expired_cleanup_preserves_live_histories_without_capacity_eviction(self):
        cache.set('expired', [1], -1)
        for index in range(350):
            cache.set(f'live-{index}', [index], 300)
        self.assertIsNone(cache.get('expired'))
        for index in range(350):
            self.assertEqual(cache.get(f'live-{index}'), [index])

    def test_nonexpiring_and_zero_timeout_values(self):
        cache.set('forever', [1], None)
        self.assertFalse(cache.add('forever', [2], 30))
        self.assertEqual(cache.get('forever'), [1])
        cache.set('immediate', [1], 0)
        self.assertIsNone(cache.get('immediate'))

    def test_database_failures_are_translated_without_connection_details(self):
        with patch('family_notes.auth_cache.connections') as connections:
            connections.__getitem__.return_value.cursor.side_effect = OperationalError('secret-host-password')
            with self.assertRaisesMessage(AuthCacheUnavailable, 'Authentication state unavailable.'):
                cache.get('history')


CHILD = '''
import os, sys, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'family_notes.settings')
django.setup()
from django.core.cache import cache
from allauth.core.internal import ratelimit
from django.http import HttpRequest
if sys.argv[1] == 'add':
    print(int(cache.add(sys.argv[2], True, timeout=300)))
elif sys.argv[1] == 'consume':
    request = HttpRequest()
    request.method = 'POST'
    request.META['REMOTE_ADDR'] = '192.0.2.50'
    print(int(bool(ratelimit.consume(request, action=sys.argv[2],
              config={sys.argv[2]: '4/m/ip'}))))
elif sys.argv[1] == 'read':
    print(int(cache.get(sys.argv[2]) == [1, 2, 3]))
'''


@skipUnless(REQUIRED, 'Requires disposable PostgreSQL security rehearsal')
@override_settings(CACHES=DB_CACHE)
class DatabaseProcessIntegrationTests(TransactionTestCase):
    def child(self, operation, key):
        env = {**os.environ, 'DB_NAME': str(connection.settings_dict['NAME'])}
        result = subprocess.run([sys.executable, '-c', CHILD, operation, key],
                                env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, 'Database child failed')
        return int(result.stdout.strip())

    def test_atomic_add_has_one_winner_across_processes(self):
        key = 'integration-lock-' + uuid.uuid4().hex
        self.addCleanup(cache.delete, key)
        with ThreadPoolExecutor(max_workers=8) as workers:
            results = list(workers.map(lambda _: self.child('add', key), range(8)))
        self.assertEqual(sum(results), 1)

    def test_allauth_rate_history_is_shared_across_processes(self):
        action = 'integration-' + uuid.uuid4().hex
        with ThreadPoolExecutor(max_workers=8) as workers:
            results = list(workers.map(lambda _: self.child('consume', action), range(8)))
        self.assertEqual(sum(results), 4)

    def test_history_survives_new_application_process(self):
        key = 'integration-history-' + uuid.uuid4().hex
        self.addCleanup(cache.delete, key)
        cache.set(key, [1, 2, 3], 300)
        self.assertEqual(self.child('read', key), 1)


@skipUnless(REQUIRED, 'Requires disposable database outage rehearsal')
class CacheUnavailableIntegrationTests(SimpleTestCase):
    # Deliberately permit the connection attempt to the stopped disposable server.
    databases = {'default'}

    def test_actual_cache_outage_denies_login_without_sensitive_details(self):
        self.client.raise_request_exception = False
        response = self.client.post(reverse('account_login'),
                                    {'login': 'synthetic-operator', 'password': 'synthetic-password'})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.content.decode(),
                         'Logowanie jest chwilowo niedostępne. Spróbuj ponownie później.')
