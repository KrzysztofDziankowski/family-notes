"""S-15 role-change service: escalation matrix, guards, tokens and admin flags."""

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from family_access import membership
from family_access.membership import (
    INACTIVE_ROLE_TARGET_ERROR,
    INVALID_ROLE_ERROR,
    LAST_PARENT_ERROR,
    SELF_DEMOTION_CONFIRM_ERROR,
    can_change_role,
    change_member_role,
    deactivate_member,
)
from family_access.models import AutomationToken, Family, FamilyMember

from .test_membership_services import MembershipFixtureMixin

PARENT = FamilyMember.Role.PARENT
CHILD = FamilyMember.Role.CHILD


class RoleFixtureMixin(MembershipFixtureMixin):
    def user_flags(self):
        return list(
            get_user_model().objects.order_by('pk').values_list(
                'pk', 'is_staff', 'is_superuser', 'is_active'
            )
        )

    def role_of(self, member):
        return FamilyMember.objects.get(pk=member.pk).role


class RoleChangeTests(RoleFixtureMixin, TestCase):
    def test_parent_promotes_child(self):
        changed = change_member_role(self.parent, self.child.pk, PARENT)

        self.assertEqual(changed.role, PARENT)
        self.assertEqual(self.role_of(self.child), PARENT)

    def test_parent_demotes_other_parent(self):
        changed = change_member_role(self.parent, self.other_parent.pk, CHILD)

        self.assertEqual(changed.role, CHILD)
        self.assertEqual(self.role_of(self.other_parent), CHILD)

    def test_unchanged_role_is_a_silent_no_op(self):
        before = self.snapshot()

        with self.assertNoLogs(membership.logger, level='INFO'):
            changed = change_member_role(self.parent, self.child.pk, CHILD)
            change_member_role(self.parent, self.parent.pk, PARENT)

        self.assertEqual(changed.role, CHILD)
        self.assertEqual(self.snapshot(), before)

    def test_invalid_role_is_rejected(self):
        before = self.snapshot()
        for value in ('admin', 'manager', '', None, 'Parent'):
            with self.subTest(value=value), self.assertRaises(ValidationError) as caught:
                change_member_role(self.parent, self.child.pk, value)
            self.assertEqual(caught.exception.messages, [INVALID_ROLE_ERROR])
        self.assertEqual(self.snapshot(), before)

    def test_role_change_logs_ids_and_roles_only(self):
        with self.assertLogs(membership.logger, level='INFO') as logs:
            change_member_role(self.parent, self.child.pk, PARENT)
            change_member_role(self.parent, self.child.pk, CHILD)

        prefix = (
            f'membership_event=role_changed family={self.family.pk} '
            f'member={self.child.pk} actor={self.parent.pk}'
        )
        self.assertEqual(
            [record.getMessage() for record in logs.records],
            [
                f'{prefix} old_role=child new_role=parent',
                f'{prefix} old_role=parent new_role=child',
            ],
        )
        for secret in ('Kasia', 'Alex', '@example.test'):
            self.assertNotIn(secret, '\n'.join(logs.output))


class EscalationTests(RoleFixtureMixin, TestCase):
    def assert_denied(self, actor, member_id, new_role, exception=PermissionDenied):
        before = self.snapshot()
        with self.assertRaises(exception):
            change_member_role(actor, member_id, new_role, confirm_self=True)
        self.assertEqual(self.snapshot(), before)

    def test_child_cannot_change_any_role(self):
        second_child = self.member('second-child', CHILD, 'Tymek')
        for target, role in (
            (self.child, PARENT),
            (second_child, PARENT),
            (self.parent, CHILD),
            (self.other_parent, CHILD),
        ):
            with self.subTest(target=target.display_name, role=role):
                self.assert_denied(self.child, target.pk, role)

    def test_child_cannot_promote_themselves(self):
        self.assert_denied(self.child, self.child.pk, PARENT)

    def test_inactive_parent_is_denied(self):
        inactive_parent = self.member('inactive-parent', PARENT, 'Ex', is_active=False)
        self.assert_denied(inactive_parent, self.child.pk, PARENT)
        self.assert_denied(inactive_parent, inactive_parent.pk, PARENT)

    def test_missing_membership_is_denied(self):
        self.assert_denied(None, self.child.pk, PARENT)

    def test_parent_of_another_family_cannot_reach_members(self):
        self.assert_denied(
            self.foreign_parent, self.child.pk, PARENT, exception=FamilyMember.DoesNotExist
        )
        self.assert_denied(
            self.foreign_parent, self.parent.pk, CHILD, exception=FamilyMember.DoesNotExist
        )

    def test_missing_member_id_is_not_found(self):
        with self.assertRaises(FamilyMember.DoesNotExist):
            change_member_role(self.parent, 999999, PARENT)

    def test_parent_in_inactive_family_is_denied(self):
        Family.objects.filter(pk=self.family.pk).update(is_active=False)
        self.parent.family.refresh_from_db()
        self.assert_denied(self.parent, self.child.pk, PARENT)


class RoleGuardTests(RoleFixtureMixin, TestCase):
    def assert_refused(self, actor, member_id, new_role, message, **kwargs):
        before = self.snapshot()
        with self.assertRaises(ValidationError) as caught:
            change_member_role(actor, member_id, new_role, **kwargs)
        self.assertEqual(caught.exception.messages, [message])
        self.assertEqual(self.snapshot(), before)

    def test_last_active_parent_cannot_be_demoted(self):
        change_member_role(self.parent, self.other_parent.pk, CHILD)

        self.assert_refused(
            self.parent, self.parent.pk, CHILD, LAST_PARENT_ERROR, confirm_self=True
        )

    def test_parent_with_disabled_account_does_not_count_as_remaining(self):
        get_user_model().objects.filter(pk=self.other_parent.user_id).update(is_active=False)

        self.assert_refused(
            self.parent, self.parent.pk, CHILD, LAST_PARENT_ERROR, confirm_self=True
        )

    def test_last_parent_guard_is_shared_with_deactivation(self):
        deactivate_member(self.parent, self.other_parent.pk)

        self.assert_refused(
            self.parent, self.parent.pk, CHILD, LAST_PARENT_ERROR, confirm_self=True
        )

    def test_self_demotion_without_confirmation_is_refused(self):
        self.assert_refused(self.parent, self.parent.pk, CHILD, SELF_DEMOTION_CONFIRM_ERROR)

    def test_self_demotion_with_confirmation_succeeds_when_another_parent_remains(self):
        changed = change_member_role(self.parent, self.parent.pk, CHILD, confirm_self=True)

        self.assertEqual(changed.role, CHILD)
        self.assertEqual(self.role_of(self.parent), CHILD)
        self.assertEqual(self.role_of(self.other_parent), PARENT)

    def test_inactive_member_role_cannot_change(self):
        FamilyMember.objects.filter(pk__in=[self.child.pk, self.other_parent.pk]).update(
            is_active=False
        )
        self.assert_refused(self.parent, self.child.pk, PARENT, INACTIVE_ROLE_TARGET_ERROR)
        self.assert_refused(self.parent, self.other_parent.pk, CHILD, INACTIVE_ROLE_TARGET_ERROR)

    def test_can_change_role_mirrors_guards(self):
        self.assertTrue(can_change_role(self.parent, self.child))
        self.assertTrue(can_change_role(self.parent, self.other_parent))
        self.assertTrue(can_change_role(self.parent, self.parent))
        self.assertFalse(can_change_role(self.child, self.child))
        change_member_role(self.parent, self.other_parent.pk, CHILD)
        self.assertFalse(can_change_role(self.parent, self.parent))
        FamilyMember.objects.filter(pk=self.child.pk).update(is_active=False)
        self.child.refresh_from_db()
        self.assertFalse(can_change_role(self.parent, self.child))


class RoleTokenTests(RoleFixtureMixin, TestCase):
    def test_demotion_revokes_every_unrevoked_token_of_the_member_only(self):
        first, _ = AutomationToken.issue(self.other_parent, 'Skrót')
        second, _ = AutomationToken.issue(self.other_parent, 'Drugi skrót')
        own, _ = AutomationToken.issue(self.parent, 'Mój skrót')

        change_member_role(self.parent, self.other_parent.pk, CHILD)

        for token in (first, second, own):
            token.refresh_from_db()
        self.assertIsNotNone(first.revoked_at)
        self.assertIsNotNone(second.revoked_at)
        self.assertIsNone(own.revoked_at)

    def test_already_revoked_token_keeps_its_revocation_time(self):
        old, _ = AutomationToken.issue(self.other_parent, 'Stary skrót')
        deactivate_member(self.parent, self.other_parent.pk)
        membership.reactivate_member(self.parent, self.other_parent.pk)
        old.refresh_from_db()
        revoked_at = old.revoked_at

        change_member_role(self.parent, self.other_parent.pk, CHILD)

        old.refresh_from_db()
        self.assertEqual(old.revoked_at, revoked_at)

    def test_re_promotion_leaves_tokens_revoked(self):
        token, _ = AutomationToken.issue(self.other_parent, 'Skrót')
        change_member_role(self.parent, self.other_parent.pk, CHILD)
        token.refresh_from_db()
        revoked_at = token.revoked_at

        change_member_role(self.parent, self.other_parent.pk, PARENT)

        token.refresh_from_db()
        self.assertEqual(token.revoked_at, revoked_at)
        self.assertEqual(self.role_of(self.other_parent), PARENT)

    def test_promotion_issues_no_token(self):
        change_member_role(self.parent, self.child.pk, PARENT)

        self.assertFalse(AutomationToken.objects.filter(member=self.child).exists())


class AdminFlagTests(RoleFixtureMixin, TestCase):
    def test_role_changes_never_touch_staff_or_superuser_flags(self):
        get_user_model().objects.filter(pk=self.other_parent.user_id).update(
            is_staff=True, is_superuser=True
        )
        before = self.user_flags()

        for actor, target, role, confirm in (
            (self.parent, self.child, PARENT, False),
            (self.parent, self.child, CHILD, False),
            (self.parent, self.other_parent, CHILD, False),
            (self.parent, self.other_parent, PARENT, False),
            (self.parent, self.parent, CHILD, True),
        ):
            with self.subTest(target=target.display_name, role=role):
                change_member_role(actor, target.pk, role, confirm_self=confirm)
                self.assertEqual(self.user_flags(), before)


class RoleStaleAuthorityTests(RoleFixtureMixin, TestCase):
    """The request-resolved actor and target are stale; rows re-read under the lock decide."""

    def test_actor_demoted_after_resolution_cannot_promote(self):
        actor = self.parent  # resolved at the start of the request
        FamilyMember.objects.filter(pk=actor.pk).update(role=CHILD)
        before = self.snapshot()

        with self.assertRaises(PermissionDenied):
            change_member_role(actor, self.child.pk, PARENT)
        self.assertEqual(self.snapshot(), before)

    def test_actor_deactivated_after_resolution_cannot_change_roles(self):
        actor = self.parent
        FamilyMember.objects.filter(pk=actor.pk).update(is_active=False)
        before = self.snapshot()

        for target, role in ((self.child, PARENT), (self.other_parent, CHILD)):
            with self.subTest(target=target.display_name), self.assertRaises(PermissionDenied):
                change_member_role(actor, target.pk, role)
        self.assertEqual(self.snapshot(), before)

    def test_target_deactivated_after_resolution_is_refused(self):
        target = self.child  # the edit page showed it active
        FamilyMember.objects.filter(pk=target.pk).update(is_active=False)
        before = self.snapshot()

        with self.assertRaises(ValidationError) as caught:
            change_member_role(self.parent, target.pk, PARENT)

        self.assertEqual(caught.exception.messages, [INACTIVE_ROLE_TARGET_ERROR])
        self.assertEqual(self.snapshot(), before)
