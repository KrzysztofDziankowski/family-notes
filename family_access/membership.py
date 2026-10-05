"""In-app family membership management (S-14, S-15): the only in-app write path for members.

Every function takes the acting ``FamilyMember`` (not the ``User``) and
re-checks that it is an active parent. Targets resolve inside the actor's
family only: foreign and missing ids both raise ``FamilyMember.DoesNotExist``.
Mutations lock the actor's ``Family`` row, then re-read the actor and the
target under that lock, so a parent who lost access while waiting cannot act
and two parents cannot remove each other's last manager. Adding members stays
operator-only in Django admin, which bypasses this lock by design.
"""

import logging

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from entries.eduvulcan.children import normalize_child_name

from .access import is_parent
from .models import Family, FamilyMember

logger = logging.getLogger(__name__)

DISPLAY_NAME_MAX_LENGTH = FamilyMember._meta.get_field('display_name').max_length

BLANK_NAME_ERROR = 'Podaj imię.'
NAME_TOO_LONG_ERROR = f'Imię może mieć najwyżej {DISPLAY_NAME_MAX_LENGTH} znaków.'
DUPLICATE_NAME_ERROR = 'W rodzinie jest już osoba o takim imieniu.'
LAST_PARENT_ERROR = 'Rodzina musi mieć co najmniej jednego aktywnego rodzica.'
SELF_DEACTIVATION_ERROR = (
    'Nie możesz wyłączyć własnego dostępu. Poproś o to drugiego rodzica '
    'lub administratora rodziny.'
)
ALREADY_INACTIVE_ERROR = 'Ta osoba jest już nieaktywna.'
ALREADY_ACTIVE_ERROR = 'Ta osoba jest już aktywna.'
INVALID_ROLE_ERROR = 'Wybierz rolę: rodzic albo dziecko.'
INACTIVE_ROLE_TARGET_ERROR = (
    'Nie można zmienić roli osoby bez dostępu. Najpierw przywróć jej dostęp.'
)
SELF_DEMOTION_CONFIRM_ERROR = (
    'Potwierdź, że chcesz zrezygnować z uprawnień rodzica.'
)
ACTIVE_ELSEWHERE_ERROR = (
    'Nie można przywrócić tej osoby, bo jej konto należy już do innej rodziny. '
    'Skontaktuj się z administratorem rodziny.'
)


def _log_event(event, member, actor):
    """Content-free audit line: event name and ids only, never names or emails."""
    logger.info(
        'membership_event=%s family=%s member=%s actor=%s',
        event,
        member.family_id,
        member.pk,
        actor.pk,
    )


def _require_parent_actor(actor):
    if not is_parent(actor):
        raise PermissionDenied('An active parent membership is required.')


def family_members(actor):
    """The actor family's members, active first and then by display name."""
    _require_parent_actor(actor)
    return FamilyMember.objects.filter(family_id=actor.family_id).order_by(
        '-is_active', 'display_name', 'pk'
    )


def get_family_member(actor, member_id):
    """One member of the actor's family; foreign and missing ids are both not found."""
    _require_parent_actor(actor)
    return FamilyMember.objects.filter(family_id=actor.family_id).get(pk=member_id)


def clean_display_name(display_name):
    """The stripped display name, or a Polish ``ValidationError`` when blank or too long."""
    name = (display_name or '').strip()
    if not name:
        raise ValidationError(BLANK_NAME_ERROR)
    if len(name) > DISPLAY_NAME_MAX_LENGTH:
        raise ValidationError(NAME_TOO_LONG_ERROR)
    return name


def _lock_family(family_id):
    """The ``Family`` row, locked for update until the transaction ends."""
    return Family.objects.select_for_update().get(pk=family_id)


def _relock_members(family, actor_id, member_id):
    """Re-read the actor and the target under the family lock.

    Authority is decided from these fresh rows, never from the request's
    in-memory actor: a parent deactivated or demoted while this request waited
    on the lock raises ``PermissionDenied``. The target must belong to the
    same family (``FamilyMember.DoesNotExist`` otherwise).
    """
    members = FamilyMember.objects.select_for_update().filter(family_id=family.pk)
    try:
        fresh_actor = members.get(pk=actor_id)
    except FamilyMember.DoesNotExist:
        raise PermissionDenied('An active parent membership is required.') from None
    fresh_actor.family = family
    if not is_parent(fresh_actor):
        raise PermissionDenied('An active parent membership is required.')
    target = members.get(pk=member_id)
    target.family = family
    return fresh_actor, target


def _remaining_parent_exists(family_id, *, excluding_member_id):
    return (
        FamilyMember.objects.filter(
            family_id=family_id,
            role=FamilyMember.Role.PARENT,
            is_active=True,
            user__is_active=True,
        )
        .exclude(pk=excluding_member_id)
        .exists()
    )


def _ensure_parent_remains(family, *, excluding_member_id):
    """Refuse a change that would leave the family without a usable parent.

    Only active parent memberships whose ``User`` is active count: a disabled
    account cannot sign in or use automation tokens.
    """
    if not _remaining_parent_exists(family.pk, excluding_member_id=excluding_member_id):
        raise ValidationError(LAST_PARENT_ERROR)


def _ensure_unique_name(family_id, display_name, *, excluding_member_id):
    """Refuse a name that normalizes to another active member's name.

    EduVulcan child matching and short-name resolution key on display names,
    so two active members with the same normalized name would be ambiguous.
    """
    wanted = normalize_child_name(display_name)
    names = (
        FamilyMember.objects.filter(family_id=family_id, is_active=True)
        .exclude(pk=excluding_member_id)
        .values_list('display_name', flat=True)
    )
    if any(normalize_child_name(name) == wanted for name in names):
        raise ValidationError(DUPLICATE_NAME_ERROR)


def can_deactivate(actor, member):
    """Whether the list may offer deactivation (the service re-checks under lock)."""
    if not member.is_active or member.pk == actor.pk:
        return False
    if member.role == FamilyMember.Role.PARENT:
        return _remaining_parent_exists(member.family_id, excluding_member_id=member.pk)
    return True


def can_change_role(actor, member):
    """Whether the edit page may offer a role change (the service re-checks under lock).

    Only active members change roles, and the family's last usable parent is
    never offered a demotion.
    """
    if not is_parent(actor) or not member.is_active:
        return False
    if member.role == FamilyMember.Role.PARENT:
        return _remaining_parent_exists(member.family_id, excluding_member_id=member.pk)
    return True


def rename_member(actor, member_id, display_name):
    """Change a member's display name; return the saved member."""
    _require_parent_actor(actor)
    name = clean_display_name(display_name)
    with transaction.atomic():
        family = _lock_family(actor.family_id)
        fresh_actor, target = _relock_members(family, actor.pk, member_id)
        _ensure_unique_name(family.pk, name, excluding_member_id=target.pk)
        target.display_name = name
        target.save(update_fields=['display_name', 'updated_at'])
    _log_event('member_renamed', target, fresh_actor)
    return target


def deactivate_member(actor, member_id):
    """Deactivate a member and revoke their automation tokens; return the member.

    Refuses the actor themselves and the family's last usable parent.
    """
    _require_parent_actor(actor)
    with transaction.atomic():
        family = _lock_family(actor.family_id)
        fresh_actor, target = _relock_members(family, actor.pk, member_id)
        if target.pk == fresh_actor.pk:
            raise ValidationError(SELF_DEACTIVATION_ERROR)
        if not target.is_active:
            raise ValidationError(ALREADY_INACTIVE_ERROR)
        if target.role == FamilyMember.Role.PARENT:
            _ensure_parent_remains(family, excluding_member_id=target.pk)
        target.is_active = False
        target.save(update_fields=['is_active', 'updated_at'])
        target.automation_tokens.filter(revoked_at__isnull=True).update(
            revoked_at=timezone.now()
        )
    _log_event('member_deactivated', target, fresh_actor)
    return target


def reactivate_member(actor, member_id):
    """Reactivate a child or a parent; revoked automation tokens stay revoked.

    Refuses when an active member already carries the same normalized name,
    or when the database's active-membership constraint rejects the row (the
    member's user is already active elsewhere; one active membership per user
    until S-16). The constraint, not a user lookup, is the authority.
    """
    _require_parent_actor(actor)
    with transaction.atomic():
        family = _lock_family(actor.family_id)
        fresh_actor, target = _relock_members(family, actor.pk, member_id)
        if target.is_active:
            raise ValidationError(ALREADY_ACTIVE_ERROR)
        _ensure_unique_name(family.pk, target.display_name, excluding_member_id=target.pk)
        target.is_active = True
        try:
            with transaction.atomic():
                target.save(update_fields=['is_active', 'updated_at'])
        except IntegrityError:
            raise ValidationError(ACTIVE_ELSEWHERE_ERROR) from None
    _log_event('member_reactivated', target, fresh_actor)
    return target


def change_member_role(actor, member_id, new_role, *, confirm_self=False):
    """Switch an active member between parent and child; return the member.

    Authority is decided under the ``Family`` lock from re-read rows: only an
    active parent may act, inactive targets are refused, the family's last
    usable parent cannot be demoted and demoting oneself needs
    ``confirm_self``. Demotion revokes the member's automation tokens; a later
    promotion never restores them. ``User`` staff and superuser flags are
    never read or written.
    """
    if new_role not in FamilyMember.Role.values:
        raise ValidationError(INVALID_ROLE_ERROR)
    _require_parent_actor(actor)
    with transaction.atomic():
        family = _lock_family(actor.family_id)
        fresh_actor, target = _relock_members(family, actor.pk, member_id)
        if not target.is_active:
            raise ValidationError(INACTIVE_ROLE_TARGET_ERROR)
        old_role = target.role
        if old_role == new_role:
            return target
        if target.pk == fresh_actor.pk and not confirm_self:
            raise ValidationError(SELF_DEMOTION_CONFIRM_ERROR)
        demoting = old_role == FamilyMember.Role.PARENT
        if demoting:
            _ensure_parent_remains(family, excluding_member_id=target.pk)
        target.role = new_role
        target.save(update_fields=['role', 'updated_at'])
        if demoting:
            target.automation_tokens.filter(revoked_at__isnull=True).update(
                revoked_at=timezone.now()
            )
    logger.info(
        'membership_event=role_changed family=%s member=%s actor=%s old_role=%s new_role=%s',
        target.family_id,
        target.pk,
        fresh_actor.pk,
        old_role,
        new_role,
    )
    return target
