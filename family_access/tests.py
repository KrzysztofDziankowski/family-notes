from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

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
