from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from .access import (
    can_read_assigned_child,
    get_active_membership,
    is_parent,
    require_active_membership,
    scope_queryset_to_family,
)
from .models import Family, FamilyMember


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

    def test_user_cannot_have_two_active_memberships(self):
        FamilyMember.objects.create(
            user=self.user,
            family=self.family,
            role=FamilyMember.Role.PARENT,
            display_name='Alex',
        )
        another_family = Family.objects.create(name='Another Family')

        with self.assertRaises(IntegrityError), transaction.atomic():
            FamilyMember.objects.create(
                user=self.user,
                family=another_family,
                role=FamilyMember.Role.PARENT,
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
        membership = get_active_membership(self.parent.user)

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

        self.assertIsNone(get_active_membership(self.child.user))
        with self.assertRaises(PermissionDenied):
            require_active_membership(self.child.user)

    def test_unknown_authenticated_user_is_denied(self):
        user = get_user_model().objects.create_user(username='unknown')

        self.assertIsNone(get_active_membership(user))
        with self.assertRaises(PermissionDenied):
            require_active_membership(user)

    def test_unauthenticated_user_is_denied(self):
        user = AnonymousUser()

        self.assertIsNone(get_active_membership(user))
        with self.assertRaises(PermissionDenied):
            require_active_membership(user)

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
        self.assertContains(response, 'Role: Parent')
        self.assertTemplateUsed(response, 'family_access/account_status.html')

    def test_configured_child_sees_display_name_and_role(self):
        user = self._create_member('child', FamilyMember.Role.CHILD, 'Sam')
        self.client.force_login(user)

        response = self.client.get(reverse('account_status'))

        self.assertContains(response, 'Sam')
        self.assertContains(response, 'Role: Child')

    def test_authenticated_user_without_membership_sees_generic_status(self):
        user = get_user_model().objects.create_user(username='unconfigured')
        self.client.force_login(user)

        response = self.client.get(reverse('account_status'))

        self.assertContains(response, 'Your family membership is not configured yet.')
        self.assertNotContains(response, self.family.name)
        self.assertNotContains(response, 'Role:')

    def _create_member(self, username, role, display_name):
        user = get_user_model().objects.create_user(username=username)
        FamilyMember.objects.create(
            user=user,
            family=self.family,
            role=role,
            display_name=display_name,
        )
        return user
