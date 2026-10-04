"""Observable admin/login limits and narrowly targeted operator recovery."""

from contextlib import contextmanager
from io import StringIO
import os
import runpy
from pathlib import Path
from unittest.mock import patch

from allauth.account import app_settings
from allauth.core.internal import ratelimit
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from family_notes.auth_cache import AuthCacheUnavailable

from family_notes.auth_security import admin_limit_targets, reset_admin_login_limits

TEST_CACHE = {'default': {
    'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    'LOCATION': 'auth-security-tests',
}}


class AuthCacheSettingsTests(SimpleTestCase):
    def settings(self, **extra):
        values = {
            'DJANGO_DEBUG': 'False', 'DJANGO_SECRET_KEY': 'synthetic-only',
            'GOOGLE_OAUTH_CLIENT_ID': 'synthetic-only',
            'GOOGLE_OAUTH_CLIENT_SECRET': 'synthetic-only', **extra,
        }
        with patch.dict(os.environ, values, clear=True), patch('dotenv.load_dotenv'):
            return runpy.run_path(str(Path(__file__).with_name('settings.py')))

    def test_production_uses_existing_database_without_cache_url(self):
        values = self.settings()
        self.assertEqual(values['CACHES']['default']['BACKEND'],
                         'family_notes.auth_cache.DatabaseAuthCache')
        self.assertEqual(values['ALLAUTH_TRUSTED_CLIENT_IP_HEADER'], 'X-Real-IP')

    def test_development_can_opt_into_database_cache(self):
        values = self.settings(DJANGO_DEBUG='True', DJANGO_AUTH_DB_CACHE='True')
        self.assertEqual(values['CACHES']['default']['BACKEND'],
                         'family_notes.auth_cache.DatabaseAuthCache')

    def test_development_keeps_zero_setup_and_other_allauth_limits_exist(self):
        values = self.settings(DJANGO_DEBUG='True')
        self.assertEqual(values['CACHES']['default']['BACKEND'],
                         'django.core.cache.backends.locmem.LocMemCache')
        self.assertIsNone(values['ALLAUTH_TRUSTED_CLIENT_IP_HEADER'])
        self.assertEqual(app_settings.RATE_LIMITS['login'], '30/m/ip')
        self.assertEqual(app_settings.RATE_LIMITS['login_failed'], '10/m/ip,5/300s/key')
        self.assertIn('reset_password', app_settings.RATE_LIMITS)


@override_settings(CACHES=TEST_CACHE, ALLAUTH_TRUSTED_CLIENT_IP_HEADER='X-Real-IP',
                   ALLOWED_HOSTS=['testserver'],
                   PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class AdminSecurityTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.operator = get_user_model().objects.create_superuser(
            username='operator', email='operator@example.test', password='safe-test-password',
        )

    def login(self, username='operator', password='wrong-password', ip='192.0.2.1', **headers):
        return self.client.post(reverse('account_login'),
                                {'login': username, 'password': password},
                                HTTP_X_REAL_IP=ip, **headers)

    def test_anonymous_admin_post_cannot_use_original_password_form(self):
        response = self.client.post(reverse('admin:login'), {
            'username': 'operator', 'password': 'safe-test-password', 'next': '/admin/',
        })
        self.assertRedirects(response, '/accounts/login/?next=/admin/',
                             fetch_redirect_response=False)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_admin_sensitive_get_and_post_reject_non_superusers_without_mutation(self):
        for staff in (False, True):
            user = get_user_model().objects.create_user(username=f'user-{staff}', is_staff=staff)
            user.user_permissions.set(Permission.objects.filter(
                content_type__app_label='auth', codename__in=['add_user', 'view_user'],
            ))
            self.client.force_login(user)
            for method in (self.client.get, self.client.post):
                with self.subTest(staff=staff, method=method):
                    before = get_user_model().objects.count()
                    response = method(reverse('admin:auth_user_add'), {'username': 'intruder'})
                    self.assertEqual(response.status_code, 302)
                    self.assertEqual(get_user_model().objects.count(), before)
            response = self.client.get(reverse('admin:login'))
            self.assertEqual(response.status_code, 403)
            response = self.client.post(reverse('admin:login'), {
                'username': 'operator', 'password': 'safe-test-password',
            })
            self.assertEqual(response.status_code, 403)
            self.assertEqual(int(self.client.session['_auth_user_id']), user.pk)
            self.client.logout()

    def test_active_superuser_can_read_and_inactive_superuser_cannot_enter(self):
        self.client.force_login(self.operator)
        self.assertEqual(self.client.get(reverse('admin:auth_user_changelist')).status_code, 200)
        self.operator.is_active = False
        self.operator.save(update_fields=['is_active'])
        self.assertEqual(self.client.get(reverse('admin:index')).status_code, 302)

    def test_five_failed_attempts_block_correct_password_even_from_another_ip(self):
        for _ in range(5):
            self.login()
        response = self.login(password='safe-test-password', ip='192.0.2.2')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertTrue(response.context['form'].errors)

    def test_general_login_ip_limit_returns_429(self):
        with override_settings(ACCOUNT_RATE_LIMITS={'login': '2/m/ip'}):
            self.login('missing-1')
            self.login('missing-2')
            self.assertEqual(self.login('missing-3').status_code, 429)

    def test_failed_ip_limit_cannot_be_bypassed_with_different_accounts(self):
        for index in range(10):
            self.login(f'unknown-{index}')
        self.login(password='safe-test-password')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_spoofed_xff_does_not_change_trusted_ip_bucket(self):
        with override_settings(ACCOUNT_RATE_LIMITS={'login': '1/m/ip'}):
            self.login('missing-1', HTTP_X_FORWARDED_FOR='198.51.100.1')
            response = self.login('missing-2', HTTP_X_FORWARDED_FOR='198.51.100.2')
            self.assertEqual(response.status_code, 429)

    def test_expiry_restores_login_without_cache_flush(self):
        for _ in range(5):
            self.login()
        with patch('allauth.core.internal.ratelimit.time.time', return_value=10**11):
            response = self.login(password='safe-test-password')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.operator.pk)

    def test_cache_outage_denies_login_and_hides_exception(self):
        with patch('allauth.core.internal.ratelimit.cache.add',
                   side_effect=AuthCacheUnavailable('private-password')):
            with self.assertLogs('family_notes.auth_security', level='ERROR') as logs:
                response = self.login(password='safe-test-password')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertNotIn('private-password', response.content.decode() + str(logs.output))

    def test_authenticated_admin_access_survives_auth_cache_outage(self):
        self.client.force_login(self.operator)
        with patch('allauth.core.internal.ratelimit.cache.add', side_effect=AuthCacheUnavailable()):
            self.assertEqual(self.client.get(reverse('admin:index')).status_code, 200)

    def test_reset_preserves_other_account_and_other_ip_histories(self):
        other = get_user_model().objects.create_superuser(
            username='other-operator', email='other@example.test', password='test-password',
        )
        target = admin_limit_targets(self.operator.pk, '192.0.2.1')
        other_targets = set(admin_limit_targets(other.pk, '198.51.100.1')) - set(target)
        for key in target + list(other_targets):
            cache.set(key, [1, 2, 3], 300)
        cache.set('unrelated-protection', [9], 300)
        output = StringIO()
        call_command('reset_admin_login_limits', user_id=self.operator.pk,
                     client_ip='192.0.2.1', stdout=output)
        self.assertTrue(all(cache.get(key) is None for key in target))
        self.assertTrue(all(cache.get(key) == [1, 2, 3] for key in other_targets))
        self.assertEqual(cache.get('unrelated-protection'), [9])
        self.assertEqual(output.getvalue(), f'admin_login_limits_reset_ok user_id={self.operator.pk}\n')

    def test_targeted_reset_restores_actual_login_without_unblocking_other_account(self):
        other = get_user_model().objects.create_superuser(
            username='other', email='other@example.test', password='safe-test-password',
        )
        for _ in range(5):
            self.login()
            self.login('other', ip='198.51.100.1')
        reset_admin_login_limits(self.operator.pk, '192.0.2.1')
        self.assertEqual(self.login(password='safe-test-password').status_code, 302)
        self.client.logout()
        self.login('other', password='safe-test-password', ip='198.51.100.1')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_bad_operator_and_ip_fail_without_deletions(self):
        regular = get_user_model().objects.create_user(username='ordinary')
        targets = admin_limit_targets(self.operator.pk, '192.0.2.1')
        for key in targets:
            cache.set(key, [1], 300)
        for user_id, ip in [(0, '192.0.2.1'), (regular.pk, '192.0.2.1'),
                            (self.operator.pk, 'not-an-ip'), (999999, '192.0.2.1')]:
            with self.subTest(user_id=user_id, ip=ip), self.assertRaises(CommandError):
                call_command('reset_admin_login_limits', user_id=user_id, client_ip=ip)
        self.operator.is_active = False
        self.operator.save(update_fields=['is_active'])
        with self.assertRaises(CommandError):
            call_command('reset_admin_login_limits', user_id=self.operator.pk, client_ip='192.0.2.1')
        self.assertTrue(all(cache.get(key) == [1] for key in targets))

    def test_ipv6_reset_targets_same_prefix_and_preserves_another_prefix(self):
        self.assertEqual(admin_limit_targets(self.operator.pk, '2001:db8:1::1'),
                         admin_limit_targets(self.operator.pk, '2001:db8:1::2'))
        self.assertNotEqual(admin_limit_targets(self.operator.pk, '2001:db8:1::1'),
                            admin_limit_targets(self.operator.pk, '2001:db8:2::1'))

    def test_email_login_uses_real_adapter_account_key(self):
        with override_settings(ACCOUNT_LOGIN_METHODS={'email'}):
            self.assertEqual(app_settings.LOGIN_METHODS, {'email'})
            for _ in range(5):
                self.login(self.operator.email)
            reset_admin_login_limits(self.operator.pk, '192.0.2.1')
            self.assertEqual(self.login(self.operator.email, password='safe-test-password').status_code, 302)

    def test_reset_lock_contention_and_cache_failure_never_report_success(self):
        @contextmanager
        def busy_lock(_key):
            yield False
        with patch('family_notes.auth_security.ratelimit.cache_lock', busy_lock):
            with self.assertRaises(ValidationError):
                reset_admin_login_limits(self.operator.pk, '192.0.2.1')
        with patch('family_notes.auth_security.cache.delete',
                   side_effect=AuthCacheUnavailable('private-cache-password')):
            with self.assertRaisesMessage(CommandError, 'admin_login_limits_reset_failed'):
                call_command('reset_admin_login_limits', user_id=self.operator.pk, client_ip='192.0.2.1')
