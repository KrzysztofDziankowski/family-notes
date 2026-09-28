"""Single write path for parent-confirmed family entries."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.views.decorators.debug import sensitive_variables

from family_access.access import can_read_assigned_child, get_active_membership, is_parent

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
    membership = get_active_membership(user)
    if not is_parent(membership):
        raise PermissionDenied('An active parent membership is required.')

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


def _validate(membership, entry_type, date, assigned_member, school_item):
    if assigned_member is not None and (
        not assigned_member.is_active or assigned_member.family_id != membership.family_id
    ):
        raise ValidationError('Wybrana osoba nie należy do rodziny.')
    if entry_type == EntryType.CALENDAR_EVENT and date is None:
        raise ValidationError('Wydarzenie musi mieć datę.')
    if school_item is not None and school_item.entry_type == entry_type:
        if MissingField.DATE in school_item.required_fields and date is None:
            raise ValidationError('Ten wpis szkolny wymaga daty.')
        if MissingField.AFFECTED_MEMBER in school_item.required_fields and assigned_member is None:
            raise ValidationError('Ten wpis szkolny wymaga wskazania osoby.')


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
