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


class RoleAccessibilityTests(MembershipFixtureMixin, TestCase):
    """S-15 role states on the real edit page."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.parent.user)

    def edit(self, member):
        return self.client.get(reverse('family_member_edit', args=[member.pk]))

    def test_promotion_form_for_a_child(self):
        response = self.edit(self.child)

        self.assertContains(response, 'Ta osoba będzie mogła zarządzać wpisami')
        assert_accessible(self, response)

    def test_demotion_form_for_another_parent(self):
        response = self.edit(self.other_parent)

        self.assertContains(response, 'tokeny automatyzacji zostaną unieważnione')
        assert_accessible(self, response)

    def test_self_demotion_checkbox_on_own_row(self):
        response = self.edit(self.parent)

        self.assertContains(response, 'name="confirm_self"')
        assert_accessible(self, response)

    def test_last_parent_explanation(self):
        FamilyMember.objects.filter(pk=self.other_parent.pk).update(
            role=FamilyMember.Role.CHILD
        )

        response = self.edit(self.parent)

        self.assertContains(response, 'To ostatni aktywny rodzic')
        self.assertNotContains(response, 'name="role"')
        assert_accessible(self, response)

    def test_guard_errors(self):
        url = reverse('family_member_role', args=[self.parent.pk])
        FamilyMember.objects.filter(pk=self.child.pk).update(is_active=False)
        cases = {
            'missing confirmation': (url, {'role': 'child'}),
            'inactive target': (
                reverse('family_member_role', args=[self.child.pk]), {'role': 'parent'}
            ),
            'invalid role': (
                reverse('family_member_role', args=[self.other_parent.pk]), {'role': 'admin'}
            ),
        }
        for label, (target, data) in cases.items():
            with self.subTest(case=label):
                response = self.client.post(target, data)
                self.assertContains(response, 'role="alert"')
                self.assertContains(response, '<title>Błąd: ')
                assert_accessible(self, response)

    def test_last_parent_guard_error(self):
        FamilyMember.objects.filter(pk=self.other_parent.pk).update(
            role=FamilyMember.Role.CHILD
        )

        response = self.client.post(
            reverse('family_member_role', args=[self.parent.pk]),
            {'role': 'child', 'confirm_self': 'on'},
        )

        self.assertContains(response, 'Rodzina musi mieć co najmniej jednego aktywnego rodzica.')
        assert_accessible(self, response)

    def test_changed_membership_notice(self):
        sam = self.client_class()
        sam.force_login(self.other_parent.user)
        self.client.post(
            reverse('family_member_role', args=[self.other_parent.pk]), {'role': 'child'}
        )

        response = sam.get(reverse('home'), follow=True)

        self.assertContains(response, 'zmienił Twoją rolę')
        assert_accessible(self, response)
