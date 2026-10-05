from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.test import TestCase
from unittest import mock

from family_access import membership
from family_access.membership import (
    ACTIVE_ELSEWHERE_ERROR,
    ALREADY_ACTIVE_ERROR,
    ALREADY_INACTIVE_ERROR,
    BLANK_NAME_ERROR,
    DUPLICATE_NAME_ERROR,
    LAST_PARENT_ERROR,
    NAME_TOO_LONG_ERROR,
    SELF_DEACTIVATION_ERROR,
    _ensure_parent_remains,
    can_deactivate,
    deactivate_member,
    family_members,
    get_family_member,
    reactivate_member,
    rename_member,
)
from family_access.models import AutomationToken, Family, FamilyMember


class MembershipFixtureMixin:
    def setUp(self):
        super().setUp()
        self.family = Family.objects.create(name='Rodzina testowa')
        self.parent = self.member('parent', FamilyMember.Role.PARENT, 'Alex')
        self.other_parent = self.member('other-parent', FamilyMember.Role.PARENT, 'Sam')
        self.child = self.member('child', FamilyMember.Role.CHILD, 'Kasia')
        self.foreign_family = Family.objects.create(name='Inna rodzina')
        self.foreign_parent = self.member(
            'foreign-parent', FamilyMember.Role.PARENT, 'Obcy', family=self.foreign_family
        )
        self.foreign_child = self.member(
            'foreign-child', FamilyMember.Role.CHILD, 'Obca', family=self.foreign_family
        )

    def member(self, username, role, display_name, *, family=None, is_active=True):
        user = get_user_model().objects.create_user(
            username=username, email=f'{username}@example.test'
        )
        return FamilyMember.objects.create(
            user=user,
            family=family or self.family,
            role=role,
            display_name=display_name,
            is_active=is_active,
        )

    def snapshot(self):
        return list(
            FamilyMember.objects.order_by('pk').values_list(
                'pk', 'display_name', 'is_active', 'role'
            )
        )


class ListingTests(MembershipFixtureMixin, TestCase):
    def test_lists_own_family_active_first_then_by_name(self):
        self.member('zuza', FamilyMember.Role.CHILD, 'Ala', is_active=False)

        names = [member.display_name for member in family_members(self.parent)]

        self.assertEqual(names, ['Alex', 'Kasia', 'Sam', 'Ala'])

    def test_get_family_member_resolves_own_family_only(self):
        self.assertEqual(get_family_member(self.parent, self.child.pk), self.child)
        with self.assertRaises(FamilyMember.DoesNotExist):
            get_family_member(self.parent, self.foreign_child.pk)
        with self.assertRaises(FamilyMember.DoesNotExist):
            get_family_member(self.parent, 999999)


class DenialTests(MembershipFixtureMixin, TestCase):
    def denied_actors(self):
        inactive_parent = self.member(
            'inactive-parent', FamilyMember.Role.PARENT, 'Ex', is_active=False
        )
        return {
            'child': self.child,
            'inactive parent': inactive_parent,
            'missing membership': None,
        }

    def test_non_parents_are_denied_every_operation(self):
        for label, actor in self.denied_actors().items():
            before = self.snapshot()
            calls = {
                'list': lambda: family_members(actor),
                'get': lambda: get_family_member(actor, self.child.pk),
                'rename': lambda: rename_member(actor, self.child.pk, 'Nowe'),
                'deactivate': lambda: deactivate_member(actor, self.child.pk),
                'reactivate': lambda: reactivate_member(actor, self.child.pk),
            }
            for name, call in calls.items():
                with self.subTest(actor=label, call=name), self.assertRaises(PermissionDenied):
                    call()
            self.assertEqual(self.snapshot(), before)

    def test_parent_of_another_family_cannot_reach_members(self):
        before = self.snapshot()
        calls = {
            'get': lambda: get_family_member(self.foreign_parent, self.child.pk),
            'rename': lambda: rename_member(self.foreign_parent, self.child.pk, 'Nowe'),
            'deactivate': lambda: deactivate_member(self.foreign_parent, self.child.pk),
            'reactivate': lambda: reactivate_member(self.foreign_parent, self.child.pk),
        }
        for name, call in calls.items():
            with self.subTest(call=name), self.assertRaises(FamilyMember.DoesNotExist):
                call()
        self.assertNotIn(self.child, family_members(self.foreign_parent))
        self.assertEqual(self.snapshot(), before)

    def test_missing_member_id_is_not_found(self):
        for call in (
            lambda: rename_member(self.parent, 999999, 'Nowe'),
            lambda: deactivate_member(self.parent, 999999),
            lambda: reactivate_member(self.parent, 999999),
        ):
            with self.assertRaises(FamilyMember.DoesNotExist):
                call()


class RenameTests(MembershipFixtureMixin, TestCase):
    def assert_rejected(self, name, message):
        before = self.snapshot()
        with self.assertRaises(ValidationError) as caught:
            rename_member(self.parent, self.child.pk, name)
        self.assertEqual(caught.exception.messages, [message])
        self.assertEqual(self.snapshot(), before)

    def test_parent_renames_member_with_stripped_name(self):
        renamed = rename_member(self.parent, self.child.pk, '  Katarzyna  ')

        self.assertEqual(renamed.display_name, 'Katarzyna')
        self.child.refresh_from_db()
        self.assertEqual(self.child.display_name, 'Katarzyna')

    def test_blank_name_is_rejected(self):
        self.assert_rejected('   ', BLANK_NAME_ERROR)

    def test_over_length_name_is_rejected(self):
        self.assert_rejected('x' * 121, NAME_TOO_LONG_ERROR)

    def test_max_length_name_is_accepted(self):
        rename_member(self.parent, self.child.pk, 'x' * 120)
        self.child.refresh_from_db()
        self.assertEqual(len(self.child.display_name), 120)

    def test_name_normalizing_to_another_active_member_is_rejected(self):
        self.assert_rejected('  SAM ', DUPLICATE_NAME_ERROR)

    def test_name_of_inactive_member_or_other_family_is_allowed(self):
        self.member('old', FamilyMember.Role.CHILD, 'Tymek', is_active=False)

        rename_member(self.parent, self.child.pk, 'Tymek')
        rename_member(self.parent, self.other_parent.pk, 'Obcy')

        self.child.refresh_from_db()
        self.assertEqual(self.child.display_name, 'Tymek')

    def test_member_may_keep_its_own_name_in_another_case(self):
        rename_member(self.parent, self.child.pk, 'KASIA')
        self.child.refresh_from_db()
        self.assertEqual(self.child.display_name, 'KASIA')


class DeactivationGuardTests(MembershipFixtureMixin, TestCase):
    def assert_refused(self, actor, member_id, message):
        before = self.snapshot()
        with self.assertRaises(ValidationError) as caught:
            deactivate_member(actor, member_id)
        self.assertEqual(caught.exception.messages, [message])
        self.assertEqual(self.snapshot(), before)

    def test_parent_deactivates_child(self):
        deactivate_member(self.parent, self.child.pk)

        self.child.refresh_from_db()
        self.assertFalse(self.child.is_active)

    def test_parent_cannot_deactivate_themselves(self):
        self.assert_refused(self.parent, self.parent.pk, SELF_DEACTIVATION_ERROR)

    def test_last_active_parent_cannot_be_deactivated(self):
        # Sam is the only other parent; once Alex is gone Sam is the last one.
        deactivate_member(self.other_parent, self.parent.pk)

        with self.assertRaises(ValidationError) as caught:
            _ensure_parent_remains(self.family, excluding_member_id=self.other_parent.pk)
        self.assertEqual(caught.exception.messages, [LAST_PARENT_ERROR])
        # An inactive parent membership never counts, so Alex cannot "remain".
        self.assertFalse(can_deactivate(self.parent, self.other_parent))

    def test_last_usable_parent_refused_through_the_service(self):
        # Sam's account is disabled: Alex is the family's last usable parent,
        # so Sam's still-active membership cannot remove Alex.
        get_user_model().objects.filter(pk=self.other_parent.user_id).update(is_active=False)

        self.assert_refused(self.other_parent, self.parent.pk, LAST_PARENT_ERROR)

    def test_parent_with_disabled_user_does_not_count_as_remaining(self):
        get_user_model().objects.filter(pk=self.parent.user_id).update(is_active=False)

        self.assert_refused(self.parent, self.other_parent.pk, LAST_PARENT_ERROR)
        with self.assertRaises(ValidationError):
            _ensure_parent_remains(self.family, excluding_member_id=self.other_parent.pk)

    def test_already_inactive_member_is_refused(self):
        FamilyMember.objects.filter(pk=self.child.pk).update(is_active=False)
        self.assert_refused(self.parent, self.child.pk, ALREADY_INACTIVE_ERROR)

    def test_deactivation_revokes_member_tokens_only(self):
        token, _ = AutomationToken.issue(self.other_parent, 'Skrót')
        own_token, _ = AutomationToken.issue(self.parent, 'Mój skrót')

        deactivate_member(self.parent, self.other_parent.pk)

        token.refresh_from_db()
        own_token.refresh_from_db()
        self.assertIsNotNone(token.revoked_at)
        self.assertIsNone(own_token.revoked_at)

    def test_reactivation_leaves_tokens_revoked(self):
        token, _ = AutomationToken.issue(self.other_parent, 'Skrót')
        deactivate_member(self.parent, self.other_parent.pk)
        token.refresh_from_db()
        revoked_at = token.revoked_at

        reactivate_member(self.parent, self.other_parent.pk)

        token.refresh_from_db()
        self.assertEqual(token.revoked_at, revoked_at)
        self.other_parent.refresh_from_db()
        self.assertTrue(self.other_parent.is_active)

    def test_can_deactivate_mirrors_guards(self):
        self.assertTrue(can_deactivate(self.parent, self.child))
        self.assertTrue(can_deactivate(self.parent, self.other_parent))
        self.assertFalse(can_deactivate(self.parent, self.parent))
        FamilyMember.objects.filter(pk=self.other_parent.pk).update(is_active=False)
        self.other_parent.refresh_from_db()
        self.assertFalse(can_deactivate(self.other_parent, self.other_parent))
        self.assertFalse(can_deactivate(self.child, self.parent))


class ReactivationTests(MembershipFixtureMixin, TestCase):
    def test_parent_reactivates_inactive_child_and_parent(self):
        FamilyMember.objects.filter(pk__in=[self.child.pk, self.other_parent.pk]).update(
            is_active=False
        )

        reactivate_member(self.parent, self.child.pk)
        reactivate_member(self.parent, self.other_parent.pk)

        self.child.refresh_from_db()
        self.other_parent.refresh_from_db()
        self.assertTrue(self.child.is_active)
        self.assertTrue(self.other_parent.is_active)

    def test_reactivation_refused_when_user_active_in_another_family(self):
        FamilyMember.objects.filter(pk=self.child.pk).update(is_active=False)
        FamilyMember.objects.create(
            user=self.child.user,
            family=self.foreign_family,
            role=FamilyMember.Role.CHILD,
            display_name='Kasia',
        )
        before = self.snapshot()

        with self.assertRaises(ValidationError) as caught:
            reactivate_member(self.parent, self.child.pk)

        self.assertEqual(caught.exception.messages, [ACTIVE_ELSEWHERE_ERROR])
        self.assertEqual(self.snapshot(), before)

    def test_uniqueness_violation_maps_to_polish_error(self):
        FamilyMember.objects.filter(pk=self.child.pk).update(is_active=False)
        with mock.patch.object(
            FamilyMember, 'save', side_effect=IntegrityError('unique')
        ), self.assertRaises(ValidationError) as caught:
            reactivate_member(self.parent, self.child.pk)

        self.assertEqual(caught.exception.messages, [ACTIVE_ELSEWHERE_ERROR])
        self.child.refresh_from_db()
        self.assertFalse(self.child.is_active)

    def test_already_active_member_is_refused(self):
        with self.assertRaises(ValidationError) as caught:
            reactivate_member(self.parent, self.child.pk)
        self.assertEqual(caught.exception.messages, [ALREADY_ACTIVE_ERROR])

    def test_reactivation_refused_when_name_now_taken(self):
        FamilyMember.objects.filter(pk=self.child.pk).update(is_active=False)
        self.member('new-kasia', FamilyMember.Role.CHILD, 'kasia')

        with self.assertRaises(ValidationError) as caught:
            reactivate_member(self.parent, self.child.pk)

        self.assertEqual(caught.exception.messages, [DUPLICATE_NAME_ERROR])
        self.child.refresh_from_db()
        self.assertFalse(self.child.is_active)


class StaleAuthorityTests(MembershipFixtureMixin, TestCase):
    """The request-resolved actor is stale; rows re-read under the lock decide."""

    def test_actor_deactivated_after_resolution_is_denied(self):
        actor = self.parent  # resolved at the start of the request
        FamilyMember.objects.filter(pk=actor.pk).update(is_active=False)
        before = self.snapshot()

        for call in (
            lambda: rename_member(actor, self.child.pk, 'Nowe'),
            lambda: deactivate_member(actor, self.other_parent.pk),
            lambda: deactivate_member(actor, self.child.pk),
        ):
            with self.assertRaises(PermissionDenied):
                call()
        self.assertEqual(self.snapshot(), before)

    def test_actor_demoted_after_resolution_is_denied(self):
        actor = self.parent
        FamilyMember.objects.filter(pk=self.child.pk).update(is_active=False)
        FamilyMember.objects.filter(pk=actor.pk).update(role=FamilyMember.Role.CHILD)
        before = self.snapshot()

        with self.assertRaises(PermissionDenied):
            reactivate_member(actor, self.child.pk)
        with self.assertRaises(PermissionDenied):
            deactivate_member(actor, self.other_parent.pk)
        self.assertEqual(self.snapshot(), before)

    def test_family_deactivated_after_resolution_is_denied(self):
        actor = self.parent
        Family.objects.filter(pk=self.family.pk).update(is_active=False)

        with self.assertRaises(PermissionDenied):
            deactivate_member(actor, self.child.pk)
        self.child.refresh_from_db()
        self.assertTrue(self.child.is_active)

    def test_target_already_reactivated_gives_state_error(self):
        target = self.child
        FamilyMember.objects.filter(pk=target.pk).update(is_active=False)
        target.refresh_from_db()  # the list showed it inactive
        FamilyMember.objects.filter(pk=target.pk).update(is_active=True)
        before = self.snapshot()

        with self.assertRaises(ValidationError) as caught:
            reactivate_member(self.parent, target.pk)

        self.assertEqual(caught.exception.messages, [ALREADY_ACTIVE_ERROR])
        self.assertEqual(self.snapshot(), before)

    def test_target_already_deactivated_gives_state_error(self):
        target = self.other_parent  # the list showed it active
        FamilyMember.objects.filter(pk=target.pk).update(is_active=False)
        before = self.snapshot()

        with self.assertRaises(ValidationError) as caught:
            deactivate_member(self.parent, target.pk)

        self.assertEqual(caught.exception.messages, [ALREADY_INACTIVE_ERROR])
        self.assertEqual(self.snapshot(), before)


class AuditLogTests(MembershipFixtureMixin, TestCase):
    def test_each_mutation_logs_ids_only(self):
        with self.assertLogs(membership.logger, level='INFO') as logs:
            rename_member(self.parent, self.child.pk, 'Katarzyna')
            deactivate_member(self.parent, self.child.pk)
            reactivate_member(self.parent, self.child.pk)

        family, child, actor = self.family.pk, self.child.pk, self.parent.pk
        self.assertEqual(
            [record.getMessage() for record in logs.records],
            [
                f'membership_event={event} family={family} member={child} actor={actor}'
                for event in ('member_renamed', 'member_deactivated', 'member_reactivated')
            ],
        )
        output = '\n'.join(logs.output)
        for secret in ('Katarzyna', 'Kasia', 'Alex', '@example.test'):
            self.assertNotIn(secret, output)

    def test_refused_mutation_logs_nothing(self):
        with self.assertNoLogs(membership.logger, level='INFO'):
            with self.assertRaises(ValidationError):
                deactivate_member(self.parent, self.parent.pk)
