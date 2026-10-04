"""Write paths for family entries: parent-confirmed and automated EduVulcan."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.views.decorators.debug import sensitive_variables

from family_access.access import (
    can_read_assigned_child,
    get_active_membership,
    is_parent,
    scope_queryset_to_family,
)
from family_access.models import FamilyMember

from .classification.service import MAX_SUBMITTED_TEXT_LENGTH
from .classification.types import EntryType, MissingField, SchoolItemKind
from .models import SCHOOL_SUBJECT_MAX_LENGTH, Entry

SCHOOL_EVENT_KINDS = frozenset(
    kind for kind in SchoolItemKind if MissingField.SCHOOL_SUBJECT in kind.required_fields
)


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
    school_subject=None,
):
    """Save one entry confirmed by an active parent; return ``(entry, created)``.

    Authorization and family scope are re-checked here, independently of the
    view. ``submission_key`` makes the call idempotent: the first save wins
    and a repeat returns that entry unchanged.
    """
    membership = require_parent_membership(user)

    entry_type = EntryType(entry_type)
    school_item = SchoolItemKind(school_item) if school_item else None
    # Transitional: callers that do not send a subject yet (None) are not held
    # to the subject rule; the parent views pass it from the review form.
    require_subject = school_subject is not None
    school_subject = _clean_subject(school_subject)

    # A repeat returns the saved entry even if its values no longer validate.
    existing = _existing_for_key(membership, submission_key)
    if existing is not None:
        return existing, False

    _validate(
        membership, entry_type, date, assigned_member, school_item,
        school_subject=school_subject, require_subject=require_subject,
    )

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
                school_subject=school_subject,
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


def _clean_subject(school_subject):
    return (school_subject or '').strip()


def _validate(
    membership, entry_type, date, assigned_member, school_item, *,
    kept_assignee_id=None, school_subject='', require_subject=False,
):
    _validate_entry_invariants(
        membership.family_id, entry_type, date, assigned_member, school_item,
        kept_assignee_id=kept_assignee_id,
        school_subject=school_subject, require_subject=require_subject,
    )


def _validate_entry_invariants(
    family_id, entry_type, date, assigned_member, school_item, *,
    kept_assignee_id=None, school_subject='', require_subject=False,
):
    """Entry rules shared by parent and automated writes.

    A school event's subject is enforced only when the caller passes
    ``require_subject``: parent paths do, automated intake never does.
    """
    if len(school_subject) > SCHOOL_SUBJECT_MAX_LENGTH:
        raise ValidationError('Przedmiot jest za długi.')
    if assigned_member is not None and (
        assigned_member.family_id != family_id
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
        if (
            require_subject
            and MissingField.SCHOOL_SUBJECT in school_item.required_fields
            and not school_subject
        ):
            raise ValidationError('Ten wpis szkolny wymaga przedmiotu.')


# --- Parent family-entry management (S-02) -----------------------------------

MANAGED_FIELDS = (
    'entry_type', 'content', 'date', 'time', 'assigned_member', 'school_item', 'school_subject',
)


def require_parent_membership(user):
    membership = get_active_membership(user)
    if not is_parent(membership):
        raise PermissionDenied('An active parent membership is required.')
    return membership


def _family_entries(membership):
    return scope_queryset_to_family(
        Entry.objects.select_related('assigned_member'), membership
    )


def _locked_family_entry(membership, entry_id):
    """Lock one family entry row for update.

    The lock query has no ``select_related``: PostgreSQL rejects ``FOR UPDATE``
    on the nullable side of the outer join a nullable foreign key produces.
    """
    return (
        scope_queryset_to_family(Entry.objects.all(), membership)
        .select_for_update()
        .get(pk=entry_id)
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
    membership, entry_type, content, date, assigned_member, school_item, *,
    kept_assignee_id=None, school_subject='', require_subject=True,
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
        school_subject=school_subject, require_subject=require_subject,
    )


def subject_required_on_edit(stored_school_item, stored_subject, new_school_item):
    """Whether an edit must carry a school subject.

    Required when the entry already had a subject, or when the parent sets or
    changes the school item to a school event kind. A subject-less automated
    or legacy school event stays editable without one.
    """
    if (stored_subject or '').strip():
        return True
    return (
        new_school_item in SCHOOL_EVENT_KINDS
        and new_school_item.value != (stored_school_item or '')
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
    school_subject=None,
):
    """Create one manual entry from the structured form; return ``(entry, created)``.

    Idempotent on ``submission_key``: a repeat returns the first saved entry.
    """
    membership = require_parent_membership(user)
    entry_type = EntryType(entry_type)
    school_item_kind = SchoolItemKind(school_item) if school_item else None

    if _existing_for_key(membership, submission_key) is None:
        _validate_managed(
            membership, entry_type, content, date, assigned_member, school_item_kind,
            school_subject=_clean_subject(school_subject),
            require_subject=school_subject is not None,
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
        school_subject=school_subject,
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
    school_subject=None,
):
    """Change only the editable fields of an entry in the parent's family.

    Family, source, creator, submission key and creation time are preserved.
    The school subject is required only per ``subject_required_on_edit``.
    Raises ``Entry.DoesNotExist`` for missing or foreign-family IDs.
    """
    membership = require_parent_membership(user)
    entry_type = EntryType(entry_type)
    school_item_kind = SchoolItemKind(school_item) if school_item else None

    with transaction.atomic():
        entry = _locked_family_entry(membership, entry_id)
        # Transitional: a caller that does not send a subject yet (None) keeps
        # the stored one and is not held to the subject rule.
        if school_subject is None:
            school_subject = entry.school_subject
            require_subject = False
        else:
            school_subject = _clean_subject(school_subject)
            require_subject = subject_required_on_edit(
                entry.school_item, entry.school_subject, school_item_kind
            )
        _validate_managed(
            membership, entry_type, content, date, assigned_member, school_item_kind,
            kept_assignee_id=entry.assigned_member_id,
            school_subject=school_subject,
            require_subject=require_subject,
        )
        entry.entry_type = entry_type.value
        entry.content = content
        entry.date = date
        entry.time = time
        entry.assigned_member = assigned_member
        entry.school_item = school_item_kind.value if school_item_kind else ''
        entry.school_subject = school_subject
        entry.save(update_fields=(*MANAGED_FIELDS, 'updated_at'))
    return entry


def delete_family_entry(user, entry_id):
    """Permanently delete one entry in the parent's family.

    Raises ``Entry.DoesNotExist`` for missing or foreign-family IDs.
    """
    membership = require_parent_membership(user)
    with transaction.atomic():
        entry = _locked_family_entry(membership, entry_id)
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


# --- Automation read API (S-06) ---------------------------------------------


def automation_family_entries(membership, *, date_from=None, date_to=None, include_undated=True):
    """All entries of the token owner's family for the automation read API.

    Deliberately independent of the HTML listing rules: no sections, no
    skipped entry types. Both date bounds are inclusive and optional; undated
    entries are added only when ``include_undated`` is true. The order
    ``created_at, id`` is stable, so newly created entries land at the end and
    do not shift earlier ``limit + offset`` pages.
    """
    dated = Q(date__isnull=False)
    if date_from is not None:
        dated &= Q(date__gte=date_from)
    if date_to is not None:
        dated &= Q(date__lte=date_to)
    condition = (dated | Q(date__isnull=True)) if include_undated else dated
    return _family_entries(membership).filter(condition).order_by('created_at', 'id')


# --- Automated EduVulcan entries (S-05) ---------------------------------------


@sensitive_variables('content')
def create_automated_entry(
    family,
    *,
    entry_type,
    content,
    date=None,
    time=None,
    assigned_member_id=None,
    school_item=None,
    school_subject='',
):
    """Create one EduVulcan entry in ``family``; the only automated write path.

    The entry has ``source=eduvulcan`` and no creator or submission key. The
    assignee must be an active member of ``family`` and the normal entry
    invariants apply; any violation raises ``ValidationError`` before a row is
    written. A school subject is stored when given but never required:
    unattended intake cannot ask for one. Callers own the surrounding
    transaction.
    """
    entry_type = EntryType(entry_type)
    school_item = SchoolItemKind(school_item) if school_item else None
    school_subject = _clean_subject(school_subject)
    if not content or not content.strip():
        raise ValidationError('Treść wpisu jest wymagana.')
    if school_item is not None and school_item.entry_type != entry_type:
        raise ValidationError('Element szkolny nie pasuje do rodzaju wpisu.')
    assigned_member = None
    if assigned_member_id is not None:
        assigned_member = FamilyMember.objects.filter(
            pk=assigned_member_id, family_id=family.pk, is_active=True
        ).first()
        if assigned_member is None:
            raise ValidationError('Wybrana osoba nie należy do rodziny.')
    _validate_entry_invariants(
        family.pk, entry_type, date, assigned_member, school_item,
        school_subject=school_subject, require_subject=False,
    )
    return Entry.objects.create(
        family=family,
        entry_type=entry_type.value,
        content=content,
        date=date,
        time=time,
        assigned_member=assigned_member,
        school_item=school_item.value if school_item else '',
        school_subject=school_subject,
        source=Entry.Source.EDUVULCAN,
        created_by=None,
        submission_key=None,
    )
