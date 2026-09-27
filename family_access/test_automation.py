from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import resolve, reverse
from django.utils import timezone

from .models import AutomationToken, Family, FamilyMember


class AutomationFixtureMixin:
    def setUp(self):
        super().setUp()
        self.family = Family.objects.create(name='The Example Family')
        self.parent = self.create_member('parent', FamilyMember.Role.PARENT)
        self.child = self.create_member('child', FamilyMember.Role.CHILD)

    def create_member(self, username, role, family=None):
        user = get_user_model().objects.create_user(
            username=username,
            email=f'{username}@example.test',
        )
        return FamilyMember.objects.create(
            user=user,
            family=family or self.family,
            role=role,
            display_name=username.replace('-', ' ').title(),
        )


class AutomationTokenModelTests(AutomationFixtureMixin, TestCase):
    def test_issue_stores_only_hash_and_prefix(self):
        token, secret = AutomationToken.issue(self.parent, 'Telefon')

        self.assertTrue(secret.startswith('fnat_'))
        token.refresh_from_db()
        self.assertEqual(token.token_hash, AutomationToken.hash_secret(secret))
        self.assertEqual(token.prefix, secret[len('fnat_'):][:8])
        self.assertTrue(secret.startswith(f'fnat_{token.prefix}'))
        stored_values = [
            str(getattr(token, field.attname))
            for field in AutomationToken._meta.concrete_fields
        ]
        for value in stored_values:
            self.assertNotIn(secret, value)
            self.assertNotEqual(value, secret[len('fnat_'):])

    def test_issued_hashes_are_unique(self):
        _, first_secret = AutomationToken.issue(self.parent, 'Pierwszy')
        _, second_secret = AutomationToken.issue(self.parent, 'Drugi')

        self.assertNotEqual(first_secret, second_secret)
        self.assertEqual(AutomationToken.objects.values('token_hash').distinct().count(), 2)

    def test_usability_depends_on_revocation_and_expiry(self):
        now = timezone.now()
        token, _ = AutomationToken.issue(self.parent, 'Telefon')
        self.assertTrue(token.is_usable(now))

        token.expires_at = now + timedelta(days=1)
        self.assertTrue(token.is_usable(now))

        token.expires_at = now - timedelta(seconds=1)
        self.assertTrue(token.is_expired(now))
        self.assertFalse(token.is_usable(now))

        token.expires_at = None
        token.revoked_at = now
        self.assertTrue(token.is_revoked)
        self.assertFalse(token.is_usable(now))

    def test_expiry_boundary(self):
        now = timezone.now()
        token, _ = AutomationToken.issue(self.parent, 'Telefon', expires_at=now)

        self.assertFalse(token.is_usable(now))
        token.expires_at = now + timedelta(seconds=1)
        self.assertTrue(token.is_usable(now))

    def test_clean_accepts_parent_and_rejects_child(self):
        AutomationToken(member=self.parent, name='Telefon').clean()

        with self.assertRaises(ValidationError) as raised:
            AutomationToken(member=self.child, name='Telefon').clean()
        self.assertIn('member', raised.exception.message_dict)

    def test_string_shows_name_and_prefix_only(self):
        token, secret = AutomationToken.issue(self.parent, 'Telefon')

        self.assertEqual(str(token), f'Telefon ({token.prefix}…)')
        self.assertNotIn(secret, str(token))


class AutomationTokenAdminTests(AutomationFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.superuser = get_user_model().objects.create_superuser(
            username='operator',
            email='operator@example.test',
            password='unused-password',
        )
        self.add_url = reverse('admin:family_access_automationtoken_add')
        self.changelist_url = reverse('admin:family_access_automationtoken_changelist')

    def test_add_shows_secret_once_and_change_page_hides_it(self):
        self.client.force_login(self.superuser)

        response = self.client.post(
            self.add_url,
            {'member': self.parent.pk, 'name': 'Telefon', 'expires_at_0': '', 'expires_at_1': ''},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'admin/family_access/automationtoken/issued.html')
        token = AutomationToken.objects.get()
        secret = response.context['secret']
        self.assertEqual(token.token_hash, AutomationToken.hash_secret(secret))
        self.assertContains(response, secret)
        self.assertContains(response, 'Nie odświeżaj')
        self.assertContains(response, 'Nie zostanie pokazany ponownie')

        change_response = self.client.get(
            reverse('admin:family_access_automationtoken_change', args=(token.pk,))
        )
        self.assertEqual(change_response.status_code, 200)
        self.assertNotContains(change_response, secret)
        self.assertNotContains(change_response, token.token_hash)

    def test_add_rejects_child_member(self):
        self.client.force_login(self.superuser)

        response = self.client.post(
            self.add_url,
            {'member': self.child.pk, 'name': 'Telefon', 'expires_at_0': '', 'expires_at_1': ''},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateNotUsed(response, 'admin/family_access/automationtoken/issued.html')
        self.assertFalse(AutomationToken.objects.exists())

    def test_change_form_keeps_member_read_only(self):
        token, _ = AutomationToken.issue(self.parent, 'Telefon')
        other_parent = self.create_member('other-parent', FamilyMember.Role.PARENT)
        self.client.force_login(self.superuser)
        change_url = reverse('admin:family_access_automationtoken_change', args=(token.pk,))

        response = self.client.get(change_url)
        self.assertNotContains(response, 'name="member"')

        self.client.post(
            change_url,
            {
                'member': other_parent.pk,
                'name': 'Nowa nazwa',
                'expires_at_0': '',
                'expires_at_1': '',
            },
        )
        token.refresh_from_db()
        self.assertEqual(token.member, self.parent)
        self.assertEqual(token.name, 'Nowa nazwa')

    def test_revoke_action_sets_revoked_at_and_keeps_existing_revocations(self):
        active, _ = AutomationToken.issue(self.parent, 'Aktywny')
        already_revoked, _ = AutomationToken.issue(self.parent, 'Stary')
        earlier = timezone.now() - timedelta(days=3)
        AutomationToken.objects.filter(pk=already_revoked.pk).update(revoked_at=earlier)
        self.client.force_login(self.superuser)

        self.client.post(
            self.changelist_url,
            {
                'action': 'revoke_tokens',
                '_selected_action': [active.pk, already_revoked.pk],
            },
        )

        active.refresh_from_db()
        already_revoked.refresh_from_db()
        self.assertIsNotNone(active.revoked_at)
        self.assertEqual(already_revoked.revoked_at, earlier)

    def test_changelist_shows_derived_status(self):
        AutomationToken.issue(self.parent, 'Aktywny')
        AutomationToken.issue(
            self.parent,
            'Przeterminowany',
            expires_at=timezone.now() - timedelta(days=1),
        )
        revoked, _ = AutomationToken.issue(self.parent, 'Cofnięty')
        AutomationToken.objects.filter(pk=revoked.pk).update(revoked_at=timezone.now())
        self.client.force_login(self.superuser)

        response = self.client.get(self.changelist_url)

        self.assertContains(response, 'Aktywny')
        self.assertContains(response, 'Wygasły')
        self.assertContains(response, 'Unieważniony')

    def test_member_membership_does_not_grant_token_admin_access(self):
        self.client.force_login(self.parent.user)

        response = self.client.get(self.changelist_url)

        self.assertRedirects(
            response,
            f"{reverse('admin:login')}?next={self.changelist_url}",
        )


class AutomationPingTests(AutomationFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.token, self.secret = AutomationToken.issue(self.parent, 'Telefon')
        self.url = reverse('automation_ping')

    def ping(self, authorization=None, client=None):
        headers = {} if authorization is None else {'HTTP_AUTHORIZATION': authorization}
        return (client or self.client).get(self.url, **headers)

    def assert_rejected(self, response):
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {'error': 'invalid_token'})
        self.assertEqual(response['WWW-Authenticate'], 'Bearer')

    def test_valid_parent_token_is_accepted_and_marks_last_use(self):
        response = self.ping(f'Bearer {self.secret}')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'ok', 'token': 'Telefon'})
        self.token.refresh_from_db()
        self.assertIsNotNone(self.token.last_used_at)

    def test_scheme_is_case_insensitive(self):
        self.assertEqual(self.ping(f'bearer {self.secret}').status_code, 200)

    def test_header_problems_are_rejected(self):
        for authorization in (
            None,
            f'Basic {self.secret}',
            'Bearer',
            'Bearer ',
            f'Bearer {self.secret} extra',
            'Bearer fnat_unknown-secret',
        ):
            with self.subTest(authorization=authorization):
                self.assert_rejected(self.ping(authorization))
        self.token.refresh_from_db()
        self.assertIsNone(self.token.last_used_at)

    def test_revoked_token_is_rejected(self):
        AutomationToken.objects.filter(pk=self.token.pk).update(revoked_at=timezone.now())

        self.assert_rejected(self.ping(f'Bearer {self.secret}'))

    def test_expired_token_is_rejected(self):
        AutomationToken.objects.filter(pk=self.token.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )

        self.assert_rejected(self.ping(f'Bearer {self.secret}'))

    def test_owner_that_became_child_is_rejected(self):
        self.parent.role = FamilyMember.Role.CHILD
        self.parent.save(update_fields=('role',))

        self.assert_rejected(self.ping(f'Bearer {self.secret}'))

    def test_inactive_membership_is_rejected(self):
        self.parent.is_active = False
        self.parent.save(update_fields=('is_active',))

        self.assert_rejected(self.ping(f'Bearer {self.secret}'))

    def test_inactive_family_is_rejected(self):
        self.family.is_active = False
        self.family.save(update_fields=('is_active',))

        self.assert_rejected(self.ping(f'Bearer {self.secret}'))

    def test_inactive_user_account_is_rejected(self):
        user = self.parent.user
        user.is_active = False
        user.save(update_fields=('is_active',))

        self.assert_rejected(self.ping(f'Bearer {self.secret}'))

    def test_signed_in_session_without_token_is_rejected(self):
        self.client.force_login(self.parent.user)

        self.assert_rejected(self.ping())

    def test_non_get_is_not_allowed_and_route_is_csrf_exempt(self):
        client = self.client_class(enforce_csrf_checks=True)

        response = client.post(self.url, HTTP_AUTHORIZATION=f'Bearer {self.secret}')

        # CSRF middleware would answer 403 before the view if the route were not exempt.
        self.assertEqual(response.status_code, 405)
        self.assertTrue(resolve(self.url).func.csrf_exempt)

    def test_revocation_takes_effect_immediately(self):
        self.assertEqual(self.ping(f'Bearer {self.secret}').status_code, 200)

        AutomationToken.objects.filter(pk=self.token.pk).update(revoked_at=timezone.now())

        self.assert_rejected(self.ping(f'Bearer {self.secret}'))

    def test_rejection_is_logged_without_secret(self):
        AutomationToken.objects.filter(pk=self.token.pk).update(revoked_at=timezone.now())

        with self.assertLogs('family_access.automation', level='WARNING') as logs:
            self.ping(f'Bearer {self.secret}')

        output = '\n'.join(logs.output)
        self.assertIn('revoked token', output)
        self.assertIn(self.token.prefix, output)
        self.assertNotIn(self.secret, output)
