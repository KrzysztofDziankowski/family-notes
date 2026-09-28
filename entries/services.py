"""Single write path for parent-confirmed family entries."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.views.decorators.debug import sensitive_variables

from family_access.access import (
    can_read_assigned_child,
    get_active_membership,
    is_parent,
    scope_queryset_to_family,
)

from .classification.service import MAX_SUBMITTED_TEXT_LENGTH
from .classification.types import EntryType, MissingField, SchoolItemKind
from .models import Entry


@sensitive_variables('content')
def save_confirmed_entry(
    user,
    *,
    entry_type,
    content,
    date,
    time,
    assigned_member,
    school_item,
    submission_key,
):
    """Save one entry confirmed by an active parent; return ``(entry, created)``.

    Authorization and family scope are re-checked here, independently of the
    view. ``submission_key`` makes the call idempotent: the first save wins
    and a repeat returns that entry unchanged.
    """
    membership = require_parent_membership(user)

    entry_type = EntryType(entry_type)
    school_item = SchoolItemKind(school_item) if school_item else None

    # A repeat returns the saved entry even if its values no longer validate.
    existing = _existing_for_key(membership, submission_key)
    if existing is not None:
        return existing, False

    _validate(membership, entry_type, date, assigned_member, school_item)

    try:
        with transaction.atomic():
            entry = Entry.objects.create(
                family=membership.family,
                entry_type=entry_type.value,
                content=content,
                date=date,
                time=time,
                assigned_member=assigned_member,
                school_item=school_item.value if school_item else '',
                source=Entry.Source.MANUAL,
                created_by=membership,
                submission_key=submission_key,
            )
    except IntegrityError:
        existing = _existing_for_key(membership, submission_key)
        if existing is None:
            raise
        return existing, False
    return entry, True


def _existing_for_key(membership, submission_key):
    entry = Entry.objects.filter(submission_key=submission_key).first()
    if entry is None:
        return None
    if entry.family_id != membership.family_id:
        raise ValidationError('Nie można zapisać tego wpisu. Spróbuj ponownie.')
    return entry


def _validate(
    membership, entry_type, date, assigned_member, school_item, *, kept_assignee_id=None
):
    if assigned_member is not None and (
        assigned_member.family_id != membership.family_id
        or (not assigned_member.is_active and assigned_member.pk != kept_assignee_id)
    ):
        raise ValidationError('Wybrana osoba nie należy do rodziny.')
    if entry_type == EntryType.CALENDAR_EVENT and date is None:
        raise ValidationError('Wydarzenie musi mieć datę.')
    if school_item is not None and school_item.entry_type == entry_type:
        if MissingField.DATE in school_item.required_fields and date is None:
            raise ValidationError('Ten wpis szkolny wymaga daty.')
        if MissingField.AFFECTED_MEMBER in school_item.required_fields and assigned_member is None:
            raise ValidationError('Ten wpis szkolny wymaga wskazania osoby.')


# --- Parent family-entry management (S-02) -----------------------------------

MANAGED_FIELDS = ('entry_type', 'content', 'date', 'time', 'assigned_member', 'school_item')


def require_parent_membership(user):
    membership = get_active_membership(user)
    if not is_parent(membership):
        raise PermissionDenied('An active parent membership is required.')
    return membership


def _family_entries(membership):
    return scope_queryset_to_family(
        Entry.objects.select_related('assigned_member'), membership
    )


def parent_family_entries(user):
    """Entries of the active parent's family only; non-parents are denied."""
    return _family_entries(require_parent_membership(user))


def get_parent_family_entry(user, entry_id):
    """Resolve one entry within the parent's family.

    Missing and foreign-family IDs both raise ``Entry.DoesNotExist`` so the
    caller cannot tell them apart.
    """
    return parent_family_entries(user).get(pk=entry_id)


def _validate_managed(
    membership, entry_type, content, date, assigned_member, school_item, *, kept_assignee_id=None
):
    """Strict validation for parent-managed entries; nothing is cleared silently.

    ``kept_assignee_id`` lets an update keep an entry's current assignee after
    that member was deactivated; a deactivated member is never newly assigned.
    """
    if not content or not content.strip():
        raise ValidationError('Treść wpisu jest wymagana.')
    if len(content) > MAX_SUBMITTED_TEXT_LENGTH:
        raise ValidationError('Treść wpisu jest za długa.')
    if school_item is not None and school_item.entry_type != entry_type:
        raise ValidationError('Element szkolny nie pasuje do rodzaju wpisu.')
    _validate(
        membership, entry_type, date, assigned_member, school_item,
        kept_assignee_id=kept_assignee_id,
    )


@sensitive_variables('content')
def create_family_entry(
    user,
    *,
    entry_type,
    content,
    date,
    time,
    assigned_member,
    school_item,
    submission_key,
):
    """Create one manual entry from the structured form; return ``(entry, created)``.

    Idempotent on ``submission_key``: a repeat returns the first saved entry.
    """
    membership = require_parent_membership(user)
    entry_type = EntryType(entry_type)
    school_item_kind = SchoolItemKind(school_item) if school_item else None

    if _existing_for_key(membership, submission_key) is None:
        _validate_managed(
            membership, entry_type, content, date, assigned_member, school_item_kind
        )
    return save_confirmed_entry(
        user,
        entry_type=entry_type.value,
        content=content,
        date=date,
        time=time,
        assigned_member=assigned_member,
        school_item=school_item_kind.value if school_item_kind else '',
        submission_key=submission_key,
    )


@sensitive_variables('content')
def update_family_entry(
    user,
    entry_id,
    *,
    entry_type,
    content,
    date,
    time,
    assigned_member,
    school_item,
):
    """Change only the editable fields of an entry in the parent's family.

    Family, source, creator, submission key and creation time are preserved.
    Raises ``Entry.DoesNotExist`` for missing or foreign-family IDs.
    """
    membership = require_parent_membership(user)
    entry_type = EntryType(entry_type)
    school_item_kind = SchoolItemKind(school_item) if school_item else None

    with transaction.atomic():
        entry = _family_entries(membership).select_for_update().get(pk=entry_id)
        _validate_managed(
            membership, entry_type, content, date, assigned_member, school_item_kind,
            kept_assignee_id=entry.assigned_member_id,
        )
        entry.entry_type = entry_type.value
        entry.content = content
        entry.date = date
        entry.time = time
        entry.assigned_member = assigned_member
        entry.school_item = school_item_kind.value if school_item_kind else ''
        entry.save(update_fields=(*MANAGED_FIELDS, 'updated_at'))
    return entry


def delete_family_entry(user, entry_id):
    """Permanently delete one entry in the parent's family.

    Raises ``Entry.DoesNotExist`` for missing or foreign-family IDs.
    """
    membership = require_parent_membership(user)
    with transaction.atomic():
        entry = _family_entries(membership).select_for_update().get(pk=entry_id)
        entry.delete()


def child_entries(user):
    """Return the entries an active child may read: only those assigned to them.

    Authorization is checked here, independently of the view. Unassigned
    ("Cała rodzina") entries, other children's entries and other families'
    entries are never included.
    """
    membership = get_active_membership(user)
    if not can_read_assigned_child(membership, membership):
        raise PermissionDenied('An active child membership is required.')
    return Entry.objects.filter(
        family=membership.family,
        assigned_member=membership,
    ).select_related('assigned_member')
