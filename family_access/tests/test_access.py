from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.backends.db import SessionStore
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.test import RequestFactory, TestCase
from django.urls import reverse

from family_access.access import (
    can_read_assigned_child,
    is_parent,
    scope_queryset_to_family,
)
from family_access.context import (
    SESSION_KEY,
    peek_family_context,
    require_family_context,
    resolve_family_context,
)
from family_access.models import Family, FamilyMember


def context_request(user, family_id=None):
    """A GET request for ``user`` with a fresh session, optionally holding a family id."""
    request = RequestFactory().get('/')
    request.user = user
    request.session = SessionStore()
    if family_id is not None:
        request.session[SESSION_KEY] = family_id
    return request


class FamilyModelTests(TestCase):
    def test_family_creation_and_string_output(self):
        family = Family.objects.create(name='The Example Family')

        self.assertEqual(str(family), 'The Example Family')
        self.assertTrue(family.is_active)
        self.assertIsNotNone(family.created_at)
        self.assertIsNotNone(family.updated_at)


class FamilyMemberModelTests(TestCase):
    def setUp(self):
        self.family = Family.objects.create(name='The Example Family')
        self.user = get_user_model().objects.create_user(
            username='parent',
            email='parent@example.test',
        )

    def test_role_choices_are_parent_and_child(self):
        self.assertEqual(
            list(FamilyMember.Role.choices),
            [('parent', 'Parent'), ('child', 'Child')],
        )

    def test_membership_maps_user_to_family_with_display_identity(self):
        member = FamilyMember.objects.create(
            user=self.user,
            family=self.family,
            role=FamilyMember.Role.PARENT,
            display_name='Alex',
        )

        self.assertEqual(member.user, self.user)
        self.assertEqual(member.family, self.family)
        self.assertEqual(self.user.family_memberships.get(), member)
        self.assertEqual(self.family.members.get(), member)
        self.assertEqual(str(member), 'Alex (Parent)')
        self.assertTrue(member.is_active)
        self.assertFalse(self.user.is_staff)
        self.assertFalse(self.user.is_superuser)

    def test_user_can_be_active_in_two_families(self):
        # S-16: one active membership per (user, family), not per user.
        FamilyMember.objects.create(
            user=self.user,
            family=self.family,
            role=FamilyMember.Role.PARENT,
            display_name='Alex',
        )
        another_family = Family.objects.create(name='Another Family')

        FamilyMember.objects.create(
            user=self.user,
            family=another_family,
            role=FamilyMember.Role.CHILD,
            display_name='Alex',
        )

        self.assertEqual(self.user.family_memberships.filter(is_active=True).count(), 2)

    def test_user_cannot_have_two_active_memberships_in_one_family(self):
        FamilyMember.objects.create(
            user=self.user,
            family=self.family,
            role=FamilyMember.Role.PARENT,
            display_name='Alex',
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            FamilyMember.objects.create(
                user=self.user,
                family=self.family,
                role=FamilyMember.Role.CHILD,
                display_name='Alex',
            )

    def test_user_can_have_inactive_membership_history(self):
        FamilyMember.objects.create(
            user=self.user,
            family=self.family,
            role=FamilyMember.Role.PARENT,
            display_name='Alex',
            is_active=False,
        )

        active_membership = FamilyMember.objects.create(
            user=self.user,
            family=Family.objects.create(name='Current Family'),
            role=FamilyMember.Role.PARENT,
            display_name='Alex',
        )

        self.assertTrue(active_membership.is_active)
        self.assertEqual(self.user.family_memberships.count(), 2)


class FamilyMemberAdminAccessTests(TestCase):
    def setUp(self):
        self.family = Family.objects.create(name='The Example Family')

    def test_parent_membership_does_not_grant_admin_access(self):
        self._assert_membership_does_not_grant_admin_access(
            role=FamilyMember.Role.PARENT,
            username='parent',
        )

    def test_child_membership_does_not_grant_admin_access(self):
        self._assert_membership_does_not_grant_admin_access(
            role=FamilyMember.Role.CHILD,
            username='child',
        )

    def _assert_membership_does_not_grant_admin_access(self, role, username):
        user = get_user_model().objects.create_user(
            username=username,
            email=f'{username}@example.test',
        )
        FamilyMember.objects.create(
            user=user,
            family=self.family,
            role=role,
            display_name=username.title(),
        )
        self.client.force_login(user)

        response = self.client.get(reverse('admin:index'))

        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertRedirects(
            response,
            f"{reverse('admin:login')}?next={reverse('admin:index')}",
            fetch_redirect_response=False,
        )


class FamilyAccessHelperTests(TestCase):
    def setUp(self):
        self.family = Family.objects.create(name='The Example Family')
        self.parent = self._create_member('parent', FamilyMember.Role.PARENT)
        self.child = self._create_member('child', FamilyMember.Role.CHILD)
        self.other_child = self._create_member(
            'other-child',
            FamilyMember.Role.CHILD,
        )

    def test_parent_membership_is_active_and_can_read_assigned_child(self):
        membership = resolve_family_context(context_request(self.parent.user))

        self.assertEqual(membership, self.parent)
        self.assertTrue(is_parent(membership))
        self.assertTrue(can_read_assigned_child(membership, self.child))

    def test_assigned_child_can_read_own_assignment(self):
        self.assertTrue(can_read_assigned_child(self.child, self.child))

    def test_other_child_cannot_read_assignment(self):
        self.assertFalse(can_read_assigned_child(self.other_child, self.child))

    def test_inactive_membership_is_not_available(self):
        self.child.is_active = False
        self.child.save(update_fields=('is_active',))

        self.assertIsNone(resolve_family_context(context_request(self.child.user)))
        with self.assertRaises(PermissionDenied):
            require_family_context(context_request(self.child.user))

    def test_unknown_authenticated_user_is_denied(self):
        user = get_user_model().objects.create_user(username='unknown')

        self.assertIsNone(resolve_family_context(context_request(user)))
        with self.assertRaises(PermissionDenied):
            require_family_context(context_request(user))

    def test_unauthenticated_user_is_denied(self):
        user = AnonymousUser()

        self.assertIsNone(resolve_family_context(context_request(user)))
        with self.assertRaises(PermissionDenied):
            require_family_context(context_request(user))

    def test_queryset_is_scoped_to_membership_family(self):
        another_family = Family.objects.create(name='Another Family')
        self._create_member(
            'another-parent',
            FamilyMember.Role.PARENT,
            family=another_family,
        )

        scoped = scope_queryset_to_family(FamilyMember.objects.all(), self.parent)

        self.assertQuerySetEqual(
            scoped.order_by('pk'),
            [self.parent, self.child, self.other_child],
        )

    def _create_member(self, username, role, family=None):
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


class FamilyContextTests(TestCase):
    """S-16: the request family context is validated against the database."""

    def setUp(self):
        self.family = Family.objects.create(name='Rodzina A')
        self.other_family = Family.objects.create(name='Rodzina B')
        self.user = get_user_model().objects.create_user(username='parent')
        self.membership = FamilyMember.objects.create(
            user=self.user, family=self.family, role=FamilyMember.Role.PARENT,
            display_name='Ewa',
        )

    def assert_no_context(self, request):
        self.assertEqual(peek_family_context(request), (None, 0))
        self.assertIsNone(resolve_family_context(request))
        with self.assertRaises(PermissionDenied):
            require_family_context(request)

    def test_single_membership_is_selected_automatically(self):
        request = context_request(self.user)

        self.assertEqual(peek_family_context(request), (self.membership, 1))
        self.assertEqual(resolve_family_context(request), self.membership)
        self.assertEqual(require_family_context(request), self.membership)
        self.assertEqual(request.session.get(SESSION_KEY), None)
        self.assertFalse(request.session.modified)

    def test_valid_session_selection_is_used(self):
        request = context_request(self.user, family_id=self.family.pk)

        self.assertEqual(resolve_family_context(request), self.membership)
        self.assertEqual(request.session[SESSION_KEY], self.family.pk)

    def test_user_without_membership_has_no_context(self):
        user = get_user_model().objects.create_user(username='unconfigured')

        self.assert_no_context(context_request(user))

    def test_anonymous_user_has_no_context(self):
        self.assert_no_context(context_request(AnonymousUser()))

    def test_inactive_membership_gives_no_context(self):
        self.membership.is_active = False
        self.membership.save(update_fields=('is_active',))

        self.assert_no_context(context_request(self.user, family_id=self.family.pk))

    def test_inactive_family_gives_no_context(self):
        self.family.is_active = False
        self.family.save(update_fields=('is_active',))

        self.assert_no_context(context_request(self.user, family_id=self.family.pk))

    def test_inactive_user_gives_no_context(self):
        self.user.is_active = False
        self.user.save(update_fields=('is_active',))

        self.assert_no_context(context_request(self.user, family_id=self.family.pk))

    def test_session_id_of_a_foreign_family_is_discarded(self):
        request = context_request(self.user, family_id=self.other_family.pk)

        self.assertEqual(resolve_family_context(request), self.membership)
        self.assertEqual(request.session[SESSION_KEY], self.family.pk)

    def test_session_id_of_an_inactive_family_membership_is_discarded(self):
        FamilyMember.objects.create(
            user=self.user, family=self.other_family, role=FamilyMember.Role.PARENT,
            display_name='Ewa', is_active=False,
        )
        request = context_request(self.user, family_id=self.other_family.pk)

        self.assertEqual(resolve_family_context(request), self.membership)
        self.assertEqual(request.session[SESSION_KEY], self.family.pk)

    def test_stale_session_id_without_any_membership_is_removed(self):
        self.membership.is_active = False
        self.membership.save(update_fields=('is_active',))
        request = context_request(self.user, family_id=self.family.pk)

        self.assertIsNone(resolve_family_context(request))
        self.assertNotIn(SESSION_KEY, request.session)

    def test_tampered_session_value_is_ignored(self):
        for value in ('1', True, None, [self.family.pk]):
            with self.subTest(value=value):
                request = context_request(self.user)
                request.session[SESSION_KEY] = value

                self.assertEqual(peek_family_context(request), (self.membership, 1))

    def test_sign_in_records_the_single_family(self):
        self.client.force_login(self.user)

        self.assertEqual(self.client.session[SESSION_KEY], self.family.pk)


class AccountStatusRouteTests(TestCase):
    def setUp(self):
        self.family = Family.objects.create(name='The Example Family')

    def test_unauthenticated_user_is_redirected_to_login(self):
        response = self.client.get(reverse('account_status'))

        self.assertRedirects(
            response,
            f"{reverse('account_login')}?next={reverse('account_status')}",
        )

    def test_configured_parent_sees_display_name_and_role(self):
        user = self._create_member('parent', FamilyMember.Role.PARENT, 'Alex')
        self.client.force_login(user)

        response = self.client.get(reverse('account_status'))

        self.assertContains(response, 'Alex')
        self.assertContains(response, 'Rodzic')
        self.assertContains(response, 'Dodaj wpis')
        self.assertContains(response, f'href="{reverse("entries:capture")}"')
        self.assertTemplateUsed(response, 'family_access/account_status.html')
        self.assertTemplateUsed(response, 'base.html')

    def test_nav_logout_is_a_post_form_that_signs_out(self):
        user = self._create_member('parent', FamilyMember.Role.PARENT, 'Alex')
        self.client.force_login(user)

        response = self.client.get(reverse('account_status'))

        self.assertContains(
            response, f'<form method="post" action="{reverse("account_logout")}"'
        )
        self.assertNotContains(response, f'href="{reverse("account_logout")}"')
        self.client.post(reverse('account_logout'))
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_configured_child_sees_display_name_and_role(self):
        user = self._create_member('child', FamilyMember.Role.CHILD, 'Sam')
        self.client.force_login(user)

        response = self.client.get(reverse('account_status'))

        self.assertContains(response, 'Sam')
        self.assertContains(response, 'Dziecko')
        self.assertNotContains(response, 'Dodaj wpis')

    def test_authenticated_user_without_membership_sees_generic_status(self):
        user = get_user_model().objects.create_user(username='unconfigured')
        self.client.force_login(user)

        response = self.client.get(reverse('account_status'))

        self.assertContains(
            response, 'Twoje członkostwo w rodzinie nie jest jeszcze skonfigurowane.'
        )
        self.assertNotContains(response, self.family.name)
        self.assertNotContains(response, 'Rola')
        self.assertNotContains(response, 'Dodaj wpis')

    def _create_member(self, username, role, display_name):
        user = get_user_model().objects.create_user(username=username)
        FamilyMember.objects.create(
            user=user,
            family=self.family,
            role=role,
            display_name=display_name,
        )
        return user
