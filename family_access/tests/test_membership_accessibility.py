"""S-17 structural accessibility audit of the S-14 member-management pages.

Each case renders a real view and must pass ``assert_accessible``; see
``context/foundation/accessibility.md``.
"""

from django.test import TestCase
from django.urls import reverse

from family_access.models import FamilyMember
from family_notes.a11y_audit import assert_accessible

from .test_membership_services import MembershipFixtureMixin


class MembershipAccessibilityTests(MembershipFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.member('former-parent', FamilyMember.Role.PARENT, 'Jola', is_active=False)
        self.member('former-child', FamilyMember.Role.CHILD, 'Ola', is_active=False)
        self.client.force_login(self.parent.user)

    def test_member_list(self):
        response = self.client.get(reverse('family_members'))

        self.assertEqual(response.status_code, 200)
        assert_accessible(self, response)

    def test_member_list_with_guard_error(self):
        response = self.client.post(
            reverse('family_member_deactivate', args=[self.parent.pk])
        )

        self.assertContains(response, 'role="alert"')
        assert_accessible(self, response)

    def test_member_list_after_success_notice(self):
        response = self.client.post(
            reverse('family_member_deactivate', args=[self.child.pk]), follow=True
        )

        self.assertContains(response, 'role="status"')
        assert_accessible(self, response)

    def test_edit_form_valid_for_child_and_parent(self):
        for member in (self.child, self.other_parent):
            with self.subTest(member=member.display_name):
                response = self.client.get(reverse('family_member_edit', args=[member.pk]))
                self.assertEqual(response.status_code, 200)
                assert_accessible(self, response)

    def test_edit_form_invalid(self):
        url = reverse('family_member_edit', args=[self.child.pk])
        for value in ('', 'SAM'):
            with self.subTest(value=value):
                response = self.client.post(url, {'display_name': value})
                self.assertContains(response, 'aria-invalid="true"')
                self.assertContains(response, 'id_display_name_error')
                self.assertContains(
                    response, 'aria-describedby="id_display_name_error id_display_name-note"'
                )
                assert_accessible(self, response)

    def test_account_page_with_member_link(self):
        response = self.client.get(reverse('account_status'))

        self.assertContains(response, reverse('family_members'))
        assert_accessible(self, response)
