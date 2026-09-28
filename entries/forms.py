import datetime
import uuid

from django import forms

from family_access.access import scope_queryset_to_family
from family_access.models import FamilyMember

from .classification.service import MAX_SUBMITTED_TEXT_LENGTH
from .classification.types import (
    ClassificationFollowUp,
    ClassificationProposal,
    EntryType,
    MissingField,
    SchoolItemKind,
)
from .models import Entry

MISSING_FIELD_HINTS = {
    MissingField.DATE: ('date', 'Podaj datę.'),
    MissingField.AFFECTED_MEMBER: ('assigned_member', 'Wybierz osobę, której dotyczy wpis.'),
    MissingField.AMBIGUOUS_MEMBER: ('assigned_member', 'Wybierz osobę.'),
}


class CaptureForm(forms.Form):
    text = forms.CharField(
        label='Co trzeba zapisać?',
        max_length=MAX_SUBMITTED_TEXT_LENGTH,
        strip=True,
        widget=forms.Textarea(attrs={'rows': 3, 'autofocus': True}),
    )


class FamilyMemberChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, member):
        return member.display_name


SCHOOL_ITEM_TYPE_MISMATCH_ERROR = 'Ten element szkolny wymaga rodzaju „{label}”.'


class EntryFieldsForm(forms.Form):
    """Editable entry fields shared by capture review, structured create and edit.

    Assignee choices are limited to active members of the parent's family.
    Subclasses decide how an incompatible school item is handled.
    """

    entry_type = forms.ChoiceField(label='Rodzaj', choices=Entry.ENTRY_TYPE_CHOICES)
    content = forms.CharField(
        label='Tytuł',
        max_length=MAX_SUBMITTED_TEXT_LENGTH,
        widget=forms.Textarea(attrs={'rows': 2}),
    )
    date = forms.DateField(
        label='Data',
        required=False,
        widget=forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
    )
    time = forms.TimeField(
        label='Godzina',
        required=False,
        widget=forms.TimeInput(attrs={'type': 'time'}, format='%H:%M'),
    )
    assigned_member = FamilyMemberChoiceField(
        label='Dla kogo',
        queryset=FamilyMember.objects.none(),
        required=False,
        empty_label='Cała rodzina',
    )

    def __init__(self, membership, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['assigned_member'].queryset = scope_queryset_to_family(
            FamilyMember.objects.filter(is_active=True), membership
        ).order_by('pk')

    def _cleaned_school_item(self, cleaned):
        value = cleaned.get('school_item')
        return SchoolItemKind(value) if value else None

    def _require_schedule_fields(self, cleaned, entry_type, school_item):
        """Enforce the calendar date and the school item's required fields."""
        date = cleaned.get('date')
        if entry_type == EntryType.CALENDAR_EVENT.value and date is None and 'date' not in self.errors:
            self.add_error('date', 'Wydarzenie musi mieć datę.')
        if school_item is not None:
            required = school_item.required_fields
            if MissingField.DATE in required and date is None and 'date' not in self.errors:
                self.add_error('date', 'Podaj datę.')
            if (
                MissingField.AFFECTED_MEMBER in required
                and cleaned.get('assigned_member') is None
                and 'assigned_member' not in self.errors
            ):
                self.add_error('assigned_member', 'Wybierz osobę, której dotyczy wpis.')


class EntryReviewForm(EntryFieldsForm):
    """The classified proposal as an editable form; every posted value is untrusted."""

    school_item = forms.ChoiceField(
        choices=[('', '')] + Entry.SCHOOL_ITEM_CHOICES,
        required=False,
        widget=forms.HiddenInput,
    )
    submission_key = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, membership, *args, missing=None, **kwargs):
        super().__init__(membership, *args, **kwargs)
        self.missing = dict(missing or {})
        for name in self.missing:
            attrs = self.fields[name].widget.attrs
            attrs['aria-invalid'] = 'true'
            attrs['aria-describedby'] = f'{self[name].auto_id}-hint'

    def rows(self):
        """Visible fields paired with the hint shown for a missing value."""
        return [
            {'field': self[name], 'hint': self.missing.get(name, '')}
            for name in ('entry_type', 'content', 'date', 'time', 'assigned_member')
        ]

    def display_date(self):
        value = self['date'].value()
        if isinstance(value, str):
            try:
                return datetime.date.fromisoformat(value)
            except ValueError:
                return None
        return value

    def clean(self):
        cleaned = super().clean()
        entry_type = cleaned.get('entry_type')
        school_item = self._cleaned_school_item(cleaned)

        # The school item is hidden classifier metadata: the parent's type
        # correction wins and silently drops a stale school item.
        if school_item is not None and entry_type and school_item.entry_type.value != entry_type:
            school_item = None
            cleaned['school_item'] = ''

        self._require_schedule_fields(cleaned, entry_type, school_item)
        return cleaned


class ManagedEntryForm(EntryFieldsForm):
    """Parent-managed entry fields with a visible, validated school item."""

    school_item = forms.ChoiceField(
        label='Element szkolny',
        choices=[('', 'Brak')] + Entry.SCHOOL_ITEM_CHOICES,
        required=False,
    )

    def clean(self):
        cleaned = super().clean()
        entry_type = cleaned.get('entry_type')
        school_item = self._cleaned_school_item(cleaned)

        # A visible choice is never discarded silently: a mismatch is an error.
        if school_item is not None and entry_type and school_item.entry_type.value != entry_type:
            label = dict(Entry.ENTRY_TYPE_CHOICES)[school_item.entry_type.value]
            self.add_error('school_item', SCHOOL_ITEM_TYPE_MISMATCH_ERROR.format(label=label))
            school_item = None

        self._require_schedule_fields(cleaned, entry_type, school_item)
        return cleaned


class EntryCreateForm(ManagedEntryForm):
    """Structured creation; the hidden key makes a resubmission idempotent."""

    submission_key = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)


class EntryEditForm(ManagedEntryForm):
    """Editing an existing entry; provenance fields are never exposed."""

    def __init__(self, membership, *args, entry=None, **kwargs):
        if entry is not None:
            initial = {
                'entry_type': entry.entry_type,
                'content': entry.content,
                'date': entry.date,
                'time': entry.time,
                'assigned_member': entry.assigned_member_id,
                'school_item': entry.school_item,
            }
            initial.update(kwargs.pop('initial', None) or {})
            kwargs['initial'] = initial
        super().__init__(membership, *args, **kwargs)


def review_form_from_classification(membership, outcome, submitted_text):
    """Build the prefilled review form and the list of fields to highlight.

    Returns ``(form, missing_field_names)``. Unavailable outcomes fall back to a
    note containing the submitted text so the parent is never stuck.
    """
    result = outcome.result
    initial = {'submission_key': uuid.uuid4()}
    missing = {}
    if isinstance(result, (ClassificationProposal, ClassificationFollowUp)):
        initial.update(
            entry_type=result.entry_type.value,
            content=result.content,
            date=result.date,
            time=result.time,
            school_item=result.school_item.value if result.school_item else '',
            assigned_member=outcome.member.pk if outcome.member else None,
        )
        if isinstance(result, ClassificationFollowUp):
            for missing_field in result.missing_fields:
                name, hint = MISSING_FIELD_HINTS[missing_field]
                missing.setdefault(name, hint)
    else:
        initial.update(entry_type=EntryType.NOTE.value, content=submitted_text, school_item='')
    form = EntryReviewForm(membership, initial=initial, missing=missing)
    return form, list(missing)
