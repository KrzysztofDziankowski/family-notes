import datetime
import uuid

from django import forms
from django.db.models import Q

from family_access.access import scope_queryset_to_family
from family_access.models import FamilyMember

from .classification.follow_up import follow_up_question
from .classification.service import MAX_FOLLOW_UP_ANSWER_LENGTH, MAX_SUBMITTED_TEXT_LENGTH
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


INACTIVE_MEMBER_SUFFIX = ' (nieaktywne konto)'


class FamilyMemberChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, member):
        if not member.is_active:
            return f'{member.display_name}{INACTIVE_MEMBER_SUFFIX}'
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
        if entry is not None and entry.assigned_member_id is not None:
            # Keep a since-deactivated assignee selectable so an unrelated edit
            # does not silently reassign the entry to the whole family.
            self.fields['assigned_member'].queryset = scope_queryset_to_family(
                FamilyMember.objects.filter(
                    Q(is_active=True) | Q(pk=entry.assigned_member_id)
                ),
                membership,
            ).order_by('pk')


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


class HiddenDateInput(forms.DateInput):
    input_type = 'hidden'


class HiddenTimeInput(forms.TimeInput):
    input_type = 'hidden'


FOLLOW_UP_DEFAULT_QUESTION = 'Uzupełnij brakujące informacje'
FOLLOW_UP_ANSWER_REQUIRED_ERROR = 'Wpisz odpowiedź albo wybierz „Pomiń”.'
FOLLOW_UP_STALE_ERROR = 'Nie udało się odczytać wpisu. Zacznij od nowa.'
_DRAFT_FIELDS = ('entry_type', 'content', 'date', 'time', 'school_item', 'assigned_member', 'missing')


class FollowUpAnswerForm(forms.Form):
    """The follow-up question; the text and draft travel as untrusted hidden fields.

    Every hidden value is re-validated on each post: the assignee must be an
    active member of the parent's family, and ``draft_from_form`` recomputes
    which missing fields the rules allow. ``skip`` makes the answer optional.
    """

    text = forms.CharField(max_length=MAX_SUBMITTED_TEXT_LENGTH, widget=forms.HiddenInput)
    entry_type = forms.ChoiceField(choices=Entry.ENTRY_TYPE_CHOICES, widget=forms.HiddenInput)
    content = forms.CharField(max_length=MAX_SUBMITTED_TEXT_LENGTH, widget=forms.HiddenInput)
    date = forms.DateField(required=False, widget=HiddenDateInput(format='%Y-%m-%d'))
    time = forms.TimeField(required=False, widget=HiddenTimeInput(format='%H:%M'))
    school_item = forms.ChoiceField(
        choices=[('', '')] + Entry.SCHOOL_ITEM_CHOICES,
        required=False,
        widget=forms.HiddenInput,
    )
    assigned_member = forms.ModelChoiceField(
        queryset=FamilyMember.objects.none(),
        required=False,
        widget=forms.HiddenInput,
    )
    missing = forms.MultipleChoiceField(
        choices=[(field.value, field.value) for field in MissingField],
        widget=forms.MultipleHiddenInput,
    )
    answer = forms.CharField(
        label=FOLLOW_UP_DEFAULT_QUESTION,
        max_length=MAX_FOLLOW_UP_ANSWER_LENGTH,
        strip=True,
        widget=forms.Textarea(attrs={'rows': 2, 'autofocus': True}),
        error_messages={'required': FOLLOW_UP_ANSWER_REQUIRED_ERROR},
    )

    stale_error = FOLLOW_UP_STALE_ERROR

    def __init__(self, membership, *args, skip=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.skip = skip
        self.fields['assigned_member'].queryset = scope_queryset_to_family(
            FamilyMember.objects.filter(is_active=True), membership
        ).order_by('pk')
        if skip:
            # A skipped question ignores whatever was typed into the answer.
            answer = self.fields['answer']
            answer.required = False
            answer.validators = []

    def set_question(self, question):
        self.fields['answer'].label = question
        # Validation already cached the bound field with the previous label.
        self['answer'].label = question

    def clean(self):
        cleaned = super().clean()
        if all(name in cleaned for name in _DRAFT_FIELDS):
            draft, _ = _draft_from_cleaned(cleaned)
            if draft.missing_fields:
                self.set_question(follow_up_question(draft))
        return cleaned

    def has_stale_fields(self):
        """True when a hidden draft value failed validation (tampered or stale)."""
        return any(name != 'answer' for name in self.errors)

    def recognized_type(self):
        return dict(Entry.ENTRY_TYPE_CHOICES).get(self['entry_type'].value(), '')

    def recognized_content(self):
        return self['content'].value() or ''


def follow_up_form_from_classification(membership, outcome, text):
    """The question form prefilled from a ``ParentClassification`` follow-up."""
    result = outcome.result
    form = FollowUpAnswerForm(
        membership,
        initial={
            'text': text,
            'entry_type': result.entry_type.value,
            'content': result.content,
            'date': result.date,
            'time': result.time,
            'school_item': result.school_item.value if result.school_item else '',
            'assigned_member': outcome.member.pk if outcome.member else None,
            'missing': [field.value for field in result.missing_fields],
        },
    )
    form.set_question(follow_up_question(result))
    return form


def draft_from_form(form):
    """Rebuild ``(ClassificationFollowUp, member)`` from a valid answer form.

    Posted ``missing`` values the rules would not produce for the draft's type,
    school item, date and member are dropped, so the result may have none.
    """
    return _draft_from_cleaned(form.cleaned_data)


def _draft_from_cleaned(cleaned):
    school_item = SchoolItemKind(cleaned['school_item']) if cleaned['school_item'] else None
    # A recognized school item fixes the entry type, as in classification.
    entry_type = school_item.entry_type if school_item else EntryType(cleaned['entry_type'])
    member = cleaned['assigned_member']
    date = cleaned['date']

    required = set(school_item.required_fields) if school_item else set()
    if entry_type == EntryType.CALENDAR_EVENT:
        required.add(MissingField.DATE)
    allowed = set()
    if MissingField.DATE in required and date is None:
        allowed.add(MissingField.DATE)
    if member is None:
        allowed.add(MissingField.AMBIGUOUS_MEMBER)
        if MissingField.AFFECTED_MEMBER in required:
            allowed.add(MissingField.AFFECTED_MEMBER)
    posted = {MissingField(value) for value in cleaned['missing']}
    missing = tuple(field for field in MissingField if field in posted & allowed)

    draft = ClassificationFollowUp(
        missing_fields=missing,
        entry_type=entry_type,
        content=cleaned['content'],
        date=date,
        time=cleaned['time'],
        school_item=school_item,
        member_name=member.display_name if member else None,
    )
    return draft, member


def proposal_from_draft(draft):
    """The draft as a complete proposal, for a draft with nothing left missing."""
    return ClassificationProposal(
        entry_type=draft.entry_type,
        content=draft.content,
        date=draft.date,
        time=draft.time,
        school_item=draft.school_item,
        member_name=draft.member_name,
    )


def skip_review_form(membership, draft, member):
    """The review form prefilled as a note, keeping the known values."""
    return EntryReviewForm(
        membership,
        initial={
            'entry_type': EntryType.NOTE.value,
            'content': draft.content,
            'date': draft.date,
            'time': draft.time,
            'assigned_member': member.pk if member else None,
            'school_item': '',
            'submission_key': uuid.uuid4(),
        },
    )
