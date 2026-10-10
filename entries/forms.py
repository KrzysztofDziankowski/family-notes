import datetime
import uuid

from django import forms
from django.forms.utils import ErrorDict
from django.db.models import Q
from django.utils import timezone

from family_access.access import is_parent, scope_queryset_to_family
from family_access.models import FamilyMember

from .classification.follow_up import follow_up_question
from .classification.service import (
    MAX_CORRECTION_LENGTH,
    MAX_FOLLOW_UP_ANSWER_LENGTH,
    MAX_PROPOSALS_PER_INSTRUCTION,
    MAX_SUBMITTED_TEXT_LENGTH,
)
from .classification.types import (
    SCHOOL_SUBJECT_MAX_LENGTH,
    ClassificationFollowUp,
    ClassificationProposal,
    EntryType,
    MissingField,
    ProposalValues,
    SchoolItemKind,
)
from .models import Entry
from .services import subject_required_on_edit

MISSING_FIELD_HINTS = {
    MissingField.DATE: ('date', 'Podaj datę.'),
    MissingField.AFFECTED_MEMBER: ('assigned_member', 'Wybierz osobę, której dotyczy wpis.'),
    MissingField.AMBIGUOUS_MEMBER: ('assigned_member', 'Wybierz osobę.'),
    MissingField.SCHOOL_SUBJECT: ('school_subject', 'Podaj przedmiot.'),
}
DATE_LABELS = {
    EntryType.NOTE.value: 'Data zapisania',
    EntryType.CALENDAR_EVENT.value: 'Data wydarzenia',
    EntryType.TODO.value: 'Termin wykonania',
}

PAST_DATE_WARNING = (
    'Data {date} jest w przeszłości. Jeśli jest poprawna, zapisz wpis. '
    'Jeśli nie, popraw datę powyżej.'
)


# Opt-in for Enter-to-submit (S-05, js/enter-submit.js): Enter submits the
# form, Shift+Enter inserts a newline; phones show a "send" key.
ENTER_SUBMIT_ATTRS = {'data-enter-submit': '', 'enterkeyhint': 'send'}


def describe_fields(form, *, with_errors=True):
    """Point every visible field's ``aria-describedby`` at what ``_field.html`` renders.

    The IDs, in rendering order: ``<auto_id>-hint`` (a review hint for a
    missing or past value), ``<auto_id>_error`` (Django's own error ID, one
    container per field), ``<auto_id>-enter-hint`` (the S-05 Enter hint of a
    ``data-enter-submit`` field) and ``<auto_id>-human`` (the readable review
    date). A field with an error or a hint is ``aria-invalid``. Call it on
    every rendered form after validation; ``with_errors=False`` composes the
    error-free part without triggering validation (form ``__init__``).
    """
    errors = form.errors if with_errors else {}
    hints = getattr(form, 'missing', None) or {}
    display_date = getattr(form, 'display_date', None)
    for bound in form.visible_fields():
        name = bound.name
        attrs = bound.field.widget.attrs
        ids = []
        if hints.get(name):
            ids.append(f'{bound.auto_id}-hint')
        if name in errors:
            ids.append(f'{bound.auto_id}_error')
        if 'data-enter-submit' in attrs:
            ids.append(f'{bound.auto_id}-enter-hint')
        if name == 'date' and display_date is not None and display_date():
            ids.append(f'{bound.auto_id}-human')
        if name in errors or hints.get(name):
            attrs['aria-invalid'] = 'true'
        else:
            attrs.pop('aria-invalid', None)
        if ids:
            attrs['aria-describedby'] = ' '.join(ids)
        else:
            attrs.pop('aria-describedby', None)


class CaptureForm(forms.Form):
    text = forms.CharField(
        label='Co trzeba zapisać?',
        max_length=MAX_SUBMITTED_TEXT_LENGTH,
        strip=True,
        widget=forms.Textarea(attrs={'rows': 3, 'autofocus': True, **ENTER_SUBMIT_ATTRS}),
    )


INACTIVE_MEMBER_SUFFIX = ' (nieaktywne konto)'


class FamilyMemberChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, member):
        if not member.is_active:
            return f'{member.display_name}{INACTIVE_MEMBER_SUFFIX}'
        return member.display_name


SCHOOL_ITEM_TYPE_MISMATCH_ERROR = 'Ten element szkolny wymaga rodzaju „{label}”.'


SCHOOL_SUBJECT_REQUIRED_ERROR = 'Podaj przedmiot.'


def self_assignee_of(membership):
    """The member a form must assign every entry to: ``None`` for a parent, else ``membership``.

    Fail-closed: anyone who is not an active parent (a child) gets no
    assignee choice at all.
    """
    return None if is_parent(membership) else membership


class EntryFieldsForm(forms.Form):
    """Editable entry fields shared by capture review, structured create and edit.

    Assignee choices are limited to active members of the parent's family. For
    a child (``self_assignee``) the assignee field is removed and every
    cleaned entry is assigned to the child, whatever was posted. The school
    item is a visible choice: a mismatch with the entry type is an error,
    never discarded silently.
    """

    entry_type = forms.ChoiceField(label='Rodzaj', choices=Entry.ENTRY_TYPE_CHOICES)
    content = forms.CharField(
        label='Tytuł',
        max_length=MAX_SUBMITTED_TEXT_LENGTH,
        widget=forms.Textarea(attrs={'rows': 2}),
    )
    date = forms.DateField(
        label='Data zapisania',
        required=True,
        error_messages={'required': 'Podaj datę.'},
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
        empty_label='Ogólne',
    )
    school_item = forms.ChoiceField(
        label='Element szkolny',
        choices=[('', 'Brak')] + Entry.SCHOOL_ITEM_CHOICES,
        required=False,
    )
    school_subject = forms.CharField(
        label='Przedmiot',
        max_length=SCHOOL_SUBJECT_MAX_LENGTH,
        required=False,
        strip=True,
    )

    def __init__(self, membership, *args, today=None, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound and not self.initial.get('entry_type'):
            self.initial['entry_type'] = EntryType.NOTE.value
        selected_type = self['entry_type'].value() or EntryType.NOTE.value
        self.fields['date'].label = DATE_LABELS.get(selected_type, 'Data zapisania')
        self.fields['entry_type'].widget.attrs['data-entry-date-type'] = ''
        self.fields['date'].widget.attrs['data-entry-date'] = ''
        if not self.is_bound and selected_type == EntryType.NOTE.value and 'date' not in self.initial:
            self.initial['date'] = today or timezone.localdate()
        self.self_assignee = self_assignee_of(membership)
        if self.self_assignee is not None:
            del self.fields['assigned_member']
        else:
            self.fields['assigned_member'].queryset = scope_queryset_to_family(
                FamilyMember.objects.filter(is_active=True), membership
            ).order_by('pk')

    def _cleaned_school_item(self, cleaned):
        value = cleaned.get('school_item')
        return SchoolItemKind(value) if value else None

    def clean(self):
        cleaned = super().clean()
        if self.self_assignee is not None:
            cleaned['assigned_member'] = self.self_assignee
        entry_type = cleaned.get('entry_type')
        school_item = self._cleaned_school_item(cleaned)

        if school_item is not None and entry_type and school_item.entry_type.value != entry_type:
            label = dict(Entry.ENTRY_TYPE_CHOICES)[school_item.entry_type.value]
            self.add_error('school_item', SCHOOL_ITEM_TYPE_MISMATCH_ERROR.format(label=label))
            school_item = None

        self._require_schedule_fields(cleaned, entry_type, school_item)
        return cleaned

    def _subject_required(self, school_item):
        """Whether a school event kind must carry a subject; edit relaxes this."""
        return True

    def _require_schedule_fields(self, cleaned, entry_type, school_item):
        """Enforce a saving date and the school item's required fields."""
        date = cleaned.get('date')
        if date is None and 'date' not in self.errors:
            self.add_error('date', 'Podaj datę.')
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
            if (
                MissingField.SCHOOL_SUBJECT in required
                and not cleaned.get('school_subject')
                and 'school_subject' not in self.errors
                and self._subject_required(school_item)
            ):
                self.add_error('school_subject', SCHOOL_SUBJECT_REQUIRED_ERROR)


CORRECTION_LABEL = 'Popraw opis'
CORRECTION_PLACEHOLDER = 'np. zmień datę na 15 października'
CORRECTION_REQUIRED_ERROR = 'Wpisz, co zmienić.'
CORRECTION_TOO_LONG_ERROR = 'Poprawka jest za długa.'
UNAPPLIED_CORRECTION_ERROR = (
    'Masz niezastosowaną poprawkę — naciśnij „Popraw” albo wyczyść pole.'
)
CORRECT_SUBMIT_ID = 'correct-submit'


class CorrectionTextarea(forms.Textarea):
    """Never rendered ``required``, so it cannot block „Zapisz wpis” in the browser."""

    def use_required_attribute(self, initial):
        return False


def _correction_field(required):
    return forms.CharField(
        label=CORRECTION_LABEL,
        max_length=MAX_CORRECTION_LENGTH,
        required=required,
        strip=True,
        # Enter runs „Popraw” only: the form names that button as the submitter.
        widget=CorrectionTextarea(
            attrs={'rows': 2, 'placeholder': CORRECTION_PLACEHOLDER, **ENTER_SUBMIT_ATTRS}
        ),
        error_messages={
            'required': CORRECTION_REQUIRED_ERROR,
            'max_length': CORRECTION_TOO_LONG_ERROR,
        },
    )


PRIVATE_LABEL = 'Prywatny — widoczny tylko dla mnie'


class EntryReviewForm(EntryFieldsForm):
    """The classified proposal as an editable form; every posted value is untrusted.

    ``correction`` is the „Popraw opis” box. Saving refuses a non-blank
    correction, so a typed but unapplied correction is never dropped silently.
    Every form (parent or child, single or batch) offers ``is_private``,
    unchecked (public) by default; the person confirming becomes the creator.
    """

    submission_key = forms.UUIDField(widget=forms.HiddenInput)
    is_private = forms.BooleanField(label=PRIVATE_LABEL, required=False, initial=False)
    correction = _correction_field(required=False)

    # Saving („Zapisz wpis”) refuses a typed but unapplied correction.
    refuse_pending_correction = True

    def __init__(self, membership, *args, missing=None, today=None, **kwargs):
        super().__init__(membership, *args, today=today, **kwargs)
        # Stable markup for Enter-to-„Popraw” (S-05): the box names its button.
        self.fields['correction'].widget.attrs['data-enter-submitter'] = self.correct_submit_id
        self.missing = dict(missing or {})
        shown_date = self.display_date()
        if today is not None and shown_date is not None and shown_date < today:
            # A warning, not a validation error: confirm still saves the date.
            self.missing.setdefault(
                'date', PAST_DATE_WARNING.format(date=shown_date.strftime('%d.%m.%Y'))
            )
        # Missing fields are aria-invalid and described by their hint; the
        # errors join in when the view describes the validated form.
        describe_fields(self, with_errors=False)

    @property
    def correct_submit_id(self):
        """The „Popraw” button id, unique per form prefix."""
        return f'{self.prefix}-{CORRECT_SUBMIT_ID}' if self.prefix else CORRECT_SUBMIT_ID

    def clean(self):
        cleaned = super().clean()
        if self.refuse_pending_correction and cleaned.get('correction'):
            self.add_error('correction', UNAPPLIED_CORRECTION_ERROR)
        return cleaned

    def rows(self):
        """Visible fields paired with the hint shown for a missing value.

        A child's form has no assignee row (``self_assignee`` is shown as
        text instead). Every form ends with the privacy choice.
        """
        return [
            {'field': self[name], 'hint': self.missing.get(name, '')}
            for name in (
                'entry_type', 'content', 'school_item', 'school_subject',
                'date', 'time', 'assigned_member', 'is_private',
            )
            if name in self.fields
        ]

    def display_date(self):
        value = self['date'].value()
        if isinstance(value, str):
            try:
                return datetime.date.fromisoformat(value)
            except ValueError:
                return None
        return value


class ProposalCorrectionForm(EntryReviewForm):
    """The proposal on screen (with manual edits) plus a free-text correction.

    Only formats, family scope and the strict school-type mismatch are
    checked; the schedule rules are skipped because the correction may be
    what adds a missing date or subject.
    """

    correction = _correction_field(required=True)

    refuse_pending_correction = False

    def __init__(self, membership, *args, **kwargs):
        super().__init__(membership, *args, **kwargs)
        self.fields['date'].required = False

    def _require_schedule_fields(self, cleaned, entry_type, school_item):
        return None


def proposal_values_from_form(form):
    """``(ProposalValues, member)`` from a valid review or correction form."""
    cleaned = form.cleaned_data
    member = cleaned['assigned_member']
    school_item = cleaned['school_item']
    values = ProposalValues(
        entry_type=EntryType(cleaned['entry_type']),
        content=cleaned['content'],
        date=cleaned['date'],
        time=cleaned['time'],
        school_item=SchoolItemKind(school_item) if school_item else None,
        school_subject=cleaned['school_subject'] or None,
        member_name=member.display_name if member else None,
    )
    return values, member


PRIVACY_VALUES = (('true', 'Prywatny'), ('false', 'Nieprywatny'))


class EntryPrivacyForm(forms.Form):
    """The creator's privacy switch for a saved entry: only ``is_private`` is posted.

    The value must be posted explicitly (``true`` or ``false``); a missing or
    unknown value is invalid, so a stray POST never makes an entry public.
    """

    is_private = forms.TypedChoiceField(
        choices=PRIVACY_VALUES,
        coerce=lambda value: value == 'true',
        widget=forms.HiddenInput,
    )


class ManagedEntryForm(EntryFieldsForm):
    """Parent-managed entry fields for structured create and edit."""


class EntryCreateForm(ManagedEntryForm):
    """Structured creation; the hidden key makes a resubmission idempotent."""

    submission_key = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)


class EntryEditForm(ManagedEntryForm):
    """Editing an existing entry; provenance fields are never exposed."""

    def __init__(self, membership, *args, entry=None, **kwargs):
        self.entry = entry
        if entry is not None:
            initial = {
                'entry_type': entry.entry_type,
                'content': entry.content,
                'date': entry.date,
                'time': entry.time,
                'assigned_member': entry.assigned_member_id,
                'school_item': entry.school_item,
                'school_subject': entry.school_subject,
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

    def _subject_required(self, school_item):
        if self.entry is None:
            return True
        return subject_required_on_edit(
            self.entry.school_item, self.entry.school_subject, school_item
        )


def review_form_from_classification(membership, outcome, submitted_text, *, today=None):
    """Build the prefilled review form and the list of fields to highlight.

    Returns ``(form, missing_field_names)``. Unavailable outcomes fall back to a
    note containing the submitted text so the parent is never stuck. A date
    before ``today`` (the classification reference date) is flagged with a
    warning hint; it is not counted as missing.
    """
    initial, missing = review_initial_from_classification(outcome, submitted_text)
    form = EntryReviewForm(membership, initial=initial, missing=missing, today=today)
    return form, list(missing)


def review_initial_from_classification(outcome, submitted_text):
    """``(initial, missing)`` for a review form built from ``outcome``."""
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
            school_subject=result.school_subject or '',
            assigned_member=outcome.member.pk if outcome.member else None,
        )
        if isinstance(result, ClassificationFollowUp):
            for missing_field in result.missing_fields:
                name, hint = MISSING_FIELD_HINTS[missing_field]
                missing.setdefault(name, hint)
    else:
        initial.update(entry_type=EntryType.NOTE.value, content=submitted_text, school_item='')
    return initial, missing


BATCH_STALE_ERROR = 'Nie udało się odczytać wpisów. Zacznij od nowa.'
BATCH_EMPTY_SELECTION_ERROR = 'Wybierz co najmniej jeden wpis.'
BATCH_DUPLICATE_HINT = 'Taki sam jak wpis {number}.'
INCLUDE_LABEL = 'Uwzględnij'
# The values that make two proposals look identical to the parent.
_DUPLICATE_FIELDS = (
    'entry_type', 'content', 'school_item', 'school_subject', 'date', 'time',
)


class BatchEntryForm(EntryReviewForm):
    """One proposal of a batch: a review form with an „Uwzględnij” checkbox."""

    include = forms.BooleanField(label=INCLUDE_LABEL, required=False, initial=True)

    def is_included(self):
        return bool(self['include'].value())

    def has_pending_correction(self):
        return bool((self['correction'].value() or '').strip())


class BatchEntryCorrectionForm(BatchEntryForm, ProposalCorrectionForm):
    """The proposal a batch correction targets: S-03's correction rules.

    Formats, family scope and the strict school-type mismatch are checked;
    the schedule rules are skipped; the correction is required.
    """

    # Redeclared: ``BatchEntryForm`` re-carries the optional review field.
    correction = _correction_field(required=True)


SAVE_ACTION = 'save'
CORRECT_ACTION_PREFIX = 'correct-'


def _batch_count(value):
    """The posted proposal count, or ``None`` when it is missing or out of range."""
    if not isinstance(value, str) or not value.isdigit():
        return None
    count = int(value)
    return count if 1 <= count <= MAX_PROPOSALS_PER_INSTRUCTION else None


class BatchReviewForm:
    """Several proposals reviewed together; every posted value is untrusted.

    Each proposal is a ``BatchEntryForm`` prefixed ``e0`` … ``e9``. The hidden
    ``count`` decides how many are bound; a missing or out-of-range count
    makes the whole form stale. Only included proposals are validated, at
    least one must be included, and two included proposals may not share a
    ``submission_key``.
    """

    def __init__(self, membership, data=None, *, items=None, today=None):
        self.membership = membership
        self.data = data
        self.is_bound = data is not None
        self.stale = False
        self.correcting = False
        self.target = None
        self.notices = {}
        self._non_field_errors = []
        if data is None:
            items = list(items or ())
            self.count = len(items)
            self.forms = [
                BatchEntryForm(
                    membership, prefix=self.prefix(index), initial=initial,
                    missing=missing, today=today,
                )
                for index, (initial, missing) in enumerate(items)
            ]
        else:
            self.count = _batch_count(data.get('count'))
            self.correcting = (data.get('action') or SAVE_ACTION) != SAVE_ACTION
            if self.count is not None and self.correcting:
                self.target = self.correction_target(data)
            if self.count is None or (self.correcting and self.target is None):
                self._mark_stale()
                self.forms = []
            else:
                self.forms = [
                    self._entry_form_class(index)(
                        membership, data, prefix=self.prefix(index), today=today
                    )
                    for index in range(self.count)
                ]

    @staticmethod
    def prefix(index):
        return f'e{index}'

    def _entry_form_class(self, index):
        return BatchEntryCorrectionForm if index == self.target else BatchEntryForm

    def correction_target(self, data):
        """The 0-based proposal a posted ``correct-<i>`` action targets, if valid."""
        action = data.get('action') or ''
        if not action.startswith(CORRECT_ACTION_PREFIX):
            return None
        index = action[len(CORRECT_ACTION_PREFIX):]
        if not (index.isascii() and index.isdigit()) or self.count is None:
            return None
        index = int(index)
        return index if index < self.count else None

    @property
    def target_form(self):
        return None if self.target is None else self.forms[self.target]

    def is_target_valid(self):
        """Validate only the correction target; the others are carried through."""
        if not self.is_bound or self.stale or self.target is None:
            return False
        for index, form in enumerate(self.forms):
            if index != self.target:
                self._carry(form)
        return self.target_form.is_valid()

    def replace_form(self, index, form):
        self.forms[index] = form

    def _carry(self, form):
        """Show an unchecked proposal as posted: errors only for included ones."""
        if form.is_included():
            form.is_valid()
        else:
            _without_validation(form)

    def _mark_stale(self):
        self.stale = True
        self._non_field_errors = [BATCH_STALE_ERROR]

    def add_error(self, message):
        self._non_field_errors.append(message)

    def non_field_errors(self):
        return list(self._non_field_errors)

    def included_forms(self):
        return [form for form in self.forms if form.is_included()]

    def has_errors(self):
        """Whether the rendered batch shows any error (page title prefix, S-17)."""
        return bool(self._non_field_errors) or any(form.errors for form in self.forms)

    def is_valid(self):
        if not self.is_bound or self.stale or self.correcting:
            return False
        # An excluded proposal is neither validated nor saved, but a typed and
        # unapplied correction on it still refuses the save.
        pending = False
        for form in self.forms:
            if form.is_included():
                continue
            if form.has_pending_correction():
                form.is_valid()
                pending = True
            else:
                _without_validation(form)
        included = self.included_forms()
        if not included:
            self.add_error(BATCH_EMPTY_SELECTION_ERROR)
            return False
        valid = all([form.is_valid() for form in included])
        if not valid or pending:
            return False
        keys = [form.cleaned_data['submission_key'] for form in included]
        if len(set(keys)) != len(keys):
            self._mark_stale()
            return False
        return not self._non_field_errors

    def duplicate_hints(self):
        """``{index: hint}`` for included proposals identical to an earlier one."""
        hints = {}
        seen = {}
        for index, form in enumerate(self.forms):
            if not form.is_included():
                continue
            key = tuple(_comparable(form[name].value()) for name in _DUPLICATE_FIELDS)
            if key in seen:
                hints[index] = BATCH_DUPLICATE_HINT.format(number=seen[key] + 1)
            else:
                seen[key] = index
        return hints

    def entries(self):
        """What the template renders per proposal, in order."""
        hints = self.duplicate_hints()
        return [
            {
                'number': index + 1,
                'index': index,
                'form': form,
                'hint': hints.get(index, ''),
                'notice': self.notices.get(index, ''),
            }
            for index, form in enumerate(self.forms)
        ]

    def save_items(self):
        """``save_confirmed_entries`` items from the valid included proposals."""
        return [_save_item(form.cleaned_data) for form in self.included_forms()]


def _without_validation(form):
    """Render a bound form as posted, without running or showing validation."""
    form._errors = ErrorDict()
    form.cleaned_data = {}


def _comparable(value):
    """A posted or initial value in one comparable text form."""
    if isinstance(value, datetime.time):
        return value.strftime('%H:%M')
    if isinstance(value, datetime.date):
        return value.isoformat()
    return '' if value is None else str(value).strip()


def _save_item(cleaned):
    item = {
        'entry_type': cleaned['entry_type'],
        'content': cleaned['content'],
        'date': cleaned['date'],
        'time': cleaned['time'],
        'assigned_member': cleaned['assigned_member'],
        'school_item': cleaned['school_item'],
        'school_subject': cleaned['school_subject'],
        'submission_key': cleaned['submission_key'],
    }
    if 'is_private' in cleaned:
        item['is_private'] = cleaned['is_private']
    return item


def batch_review_form_from_classification(membership, batch, *, today=None):
    """The batch review form prefilled from a ``ParentBatchClassification``.

    Every proposal gets its own fresh ``submission_key`` and the same missing
    highlights as a single review form.
    """
    items = [review_initial_from_classification(outcome, '') for outcome in batch.items]
    return BatchReviewForm(membership, items=items, today=today)


class HiddenDateInput(forms.DateInput):
    input_type = 'hidden'


class HiddenTimeInput(forms.TimeInput):
    input_type = 'hidden'


FOLLOW_UP_DEFAULT_QUESTION = 'Uzupełnij brakujące informacje'
FOLLOW_UP_ANSWER_REQUIRED_ERROR = 'Wpisz odpowiedź albo wybierz „Pomiń”.'
FOLLOW_UP_STALE_ERROR = 'Nie udało się odczytać wpisu. Zacznij od nowa.'
_DRAFT_FIELDS = (
    'entry_type', 'content', 'date', 'time', 'school_item', 'school_subject',
    'assigned_member', 'missing',
)


class FollowUpAnswerForm(forms.Form):
    """The follow-up question; the text and draft travel as untrusted hidden fields.

    Every hidden value is re-validated on each post: the assignee must be an
    active member of the parent's family (a child's form has no assignee
    field and always drafts for the child), and ``draft_from_form``
    recomputes which missing fields the rules allow. ``skip`` makes the
    answer optional.
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
    school_subject = forms.CharField(
        max_length=SCHOOL_SUBJECT_MAX_LENGTH,
        required=False,
        strip=True,
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
        widget=forms.Textarea(attrs={'rows': 2, 'autofocus': True, **ENTER_SUBMIT_ATTRS}),
        error_messages={'required': FOLLOW_UP_ANSWER_REQUIRED_ERROR},
    )

    stale_error = FOLLOW_UP_STALE_ERROR

    def __init__(self, membership, *args, skip=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.skip = skip
        self.self_assignee = self_assignee_of(membership)
        if self.self_assignee is not None:
            del self.fields['assigned_member']
        else:
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
        if self.self_assignee is not None:
            cleaned['assigned_member'] = self.self_assignee
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
            'school_subject': result.school_subject or '',
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
    school_subject = cleaned['school_subject'] or None

    required = set(school_item.required_fields) if school_item else set()
    required.add(MissingField.DATE)
    allowed = set()
    if MissingField.DATE in required and date is None:
        allowed.add(MissingField.DATE)
    if member is None:
        allowed.add(MissingField.AMBIGUOUS_MEMBER)
        if MissingField.AFFECTED_MEMBER in required:
            allowed.add(MissingField.AFFECTED_MEMBER)
    if MissingField.SCHOOL_SUBJECT in required and school_subject is None:
        allowed.add(MissingField.SCHOOL_SUBJECT)
    posted = {MissingField(value) for value in cleaned['missing']}
    missing = tuple(
        field for field in MissingField
        if field in posted & allowed or (field == MissingField.DATE and field in allowed)
    )

    draft = ClassificationFollowUp(
        missing_fields=missing,
        entry_type=entry_type,
        content=cleaned['content'],
        date=date,
        time=cleaned['time'],
        school_item=school_item,
        member_name=member.display_name if member else None,
        school_subject=school_subject,
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
        school_subject=draft.school_subject,
    )


def skip_review_form(membership, draft, member, *, today=None):
    """The review form prefilled as a note, keeping the known values."""
    return EntryReviewForm(
        membership,
        initial={
            'entry_type': EntryType.NOTE.value,
            'content': draft.content,
            'date': draft.date or today or timezone.localdate(),
            'time': draft.time,
            'assigned_member': member.pk if member else None,
            'school_item': '',
            'school_subject': draft.school_subject or '',
            'submission_key': uuid.uuid4(),
        },
        today=today,
    )
