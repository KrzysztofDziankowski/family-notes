"""S-16 cross-family isolation matrix for the S-14/S-15 member-management routes."""

from django.test import TestCase
from django.urls import reverse

from entries.tests.test_multi_family_access import MixedRoleFixtureMixin
from family_access.models import FamilyMember


def member_routes(pk):
    return [
        reverse('family_member_edit', args=[pk]),
        reverse('family_member_deactivate', args=[pk]),
        reverse('family_member_reactivate', args=[pk]),
        reverse('family_member_role', args=[pk]),
    ]


class ParentContextMembersTests(MixedRoleFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.use(self.family_a)

    def test_member_list_shows_only_the_current_family(self):
        response = self.client.get(reverse('family_members'))

        self.assertContains(response, 'Michał')
        self.assertNotContains(response, 'Kuba')
        self.assertNotContains(response, 'Tomek')

    def test_members_of_another_family_are_404_without_changes(self):
        before = self.snapshot()
        for member in (self.child_b, self.tomek_b, self.kuba_b):
            with self.subTest(member=member.display_name):
                self.assertEqual(
                    self.client.get(reverse('family_member_edit', args=[member.pk])).status_code,
                    404,
                )
                for url in member_routes(member.pk):
                    response = self.post(url, {
                        'display_name': 'Zmienione', 'role': FamilyMember.Role.PARENT,
                    })
                    self.assertEqual(response.status_code, 404, url)
        self.assertEqual(self.snapshot(), before)

    def test_role_in_this_family_ignores_the_other_membership(self):
        response = self.client.get(reverse('account_status'))

        self.assertContains(response, 'Rodzic')
        self.assertContains(response, f'href="{reverse("family_members")}"')


class ChildContextMembersTests(MixedRoleFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.use(self.family_b)

    def test_member_management_is_forbidden_and_writes_nothing(self):
        before = self.snapshot()
        self.assertEqual(self.client.get(reverse('family_members')).status_code, 403)
        for member in (self.kuba_b, self.tomek_b, self.michal_a, self.parent_a):
            with self.subTest(member=member.display_name):
                self.assertEqual(
                    self.client.get(reverse('family_member_edit', args=[member.pk])).status_code,
                    403,
                )
                for url in member_routes(member.pk):
                    response = self.post(url, {
                        'display_name': 'Zmienione', 'role': FamilyMember.Role.PARENT,
                    })
                    self.assertEqual(response.status_code, 403, url)
        self.assertEqual(self.snapshot(), before)

    def test_account_shows_the_child_role_of_the_current_family(self):
        response = self.client.get(reverse('account_status'))

        self.assertContains(response, 'Dziecko')
        self.assertNotContains(response, f'href="{reverse("family_members")}"')
