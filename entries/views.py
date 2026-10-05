import datetime
import logging
import math
import uuid
from dataclasses import replace

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from family_access.access import scope_queryset_to_family
from family_access.context import require_family_context, resolve_family_context
from family_access.models import FamilyMember
from family_notes.log_safety import exception_summary

from .classification.service import (
    MAX_PROPOSALS_PER_INSTRUCTION,
    CorrectionRejection,
    ParentBatchClassification,
    ParentClassification,
    classify_entries_for_parent,
    classify_follow_up_answer,
    correct_proposal_for_parent,
)
from .classification.types import (
    EntryType,
    MissingField,
    SchoolItemKind,
    ClassificationFollowUp,
    ClassificationProposal,
    ClassificationUnavailable,
    UnavailableReason,
)
from .forms import (
    CORRECTION_TOO_LONG_ERROR,
    INACTIVE_MEMBER_SUFFIX,
    BatchEntryForm,
    BatchReviewForm,
    CaptureForm,
    EntryCreateForm,
    EntryEditForm,
    EntryReviewForm,
    FollowUpAnswerForm,
    ProposalCorrectionForm,
    review_initial_from_classification,
    batch_review_form_from_classification,
    describe_fields,
    draft_from_form,
    follow_up_form_from_classification,
    proposal_from_draft,
    proposal_values_from_form,
    review_form_from_classification,
    skip_review_form,
)
from .listing import (
    LIST_MODES,
    PAST,
    SECTION_DATED,
    SECTION_PAST,
    SECTION_UNDATED,
    UPCOMING,
    EntrySection,
    group_by_day,
    normalize_list_mode,
    partition_entries,
    split_by_assignee,
    with_effective_date,
)
from .models import Entry
from .services import (
    child_entries,
    create_family_entry,
    delete_family_entry,
    parent_family_entries,
    require_parent_membership,
    save_confirmed_entries,
    save_confirmed_entry,
    update_family_entry,
)

UNAVAILABLE_NOTICE = (
    'Nie udało się teraz rozpoznać wpisu. Możesz zapisać go jako notatkę lub poprawić.'
)
TOO_MANY_ENTRIES_NOTICE = (
    f'Za dużo wpisów w jednym poleceniu (maks. {MAX_PROPOSALS_PER_INSTRUCTION}). '
    'Podziel polecenie.'
)
INPUT_TOO_LONG_ERROR = 'Tekst jest za długi. Skróć go i spróbuj ponownie.'
SAVE_FAILED_ERROR = 'Nie udało się zapisać wpisu. Sprawdź dane i spróbuj ponownie.'
SKIPPED_NOTICE = 'Brakujące dane pominięte — wpis zostanie zapisany jako notatka.'
ANSWER_UNAVAILABLE_NOTICE = 'Nie udało się rozpoznać odpowiedzi. Uzupełnij brakujące pola.'
CORRECTION_APPLIED_NOTICE = 'Zaktualizowano: {fields}.'
CORRECTION_FAILED_NOTICE = (
    'Nie udało się zastosować poprawki. Napisz ją inaczej albo popraw pola ręcznie.'
)
BATCH_CORRECTION_NOTICE = 'Wpis {number}: {notice}'
CORRECTION_SCHOOL_ITEM_NOTICE = (
    'Ten element szkolny wymaga rodzaju „{label}”. Poprawka nie została zastosowana.'
)
# Changed correction fields, in review-form order, mapped to their form field.
_CORRECTION_FIELD_ORDER = (
    ('entry_type', 'entry_type'),
    ('content', 'content'),
    ('school_item', 'school_item'),
    ('school_subject', 'school_subject'),
    ('date', 'date'),
    ('time', 'time'),
    ('member_name', 'assigned_member'),
)


logger = logging.getLogger(__name__)


def _log_rejected_save(error):
    """A form-valid save the service rejected: shown to the parent as a
    generic error, so record which check fired (location only, no data)."""
    logger.warning('Entry save rejected by service: error=%s', exception_summary(error))


def _require_parent(request):
    """The request's family context when it is an active parent membership."""
    return require_parent_membership(resolve_family_context(request))


# The page reports a stalled request this long after the provider deadline.
PROGRESS_STALLED_MARGIN_SECONDS = 10


def _progress_thresholds():
    """Client-side progress timing (seconds), derived from the provider limits.

    After one attempt timeout the provider may be retrying, so the page says
    it takes longer than usual; with no response well past the deadline it
    offers a retry.
    """
    return {
        'progress_slow_after': math.ceil(settings.CLASSIFICATION_ATTEMPT_TIMEOUT_SECONDS),
        'progress_stalled_after': (
            math.ceil(settings.CLASSIFICATION_DEADLINE_SECONDS) + PROGRESS_STALLED_MARGIN_SECONDS
        ),
    }


def _describe_capture_forms(context):
    """Describe every form a capture page renders (see ``describe_fields``)."""
    for key in ('capture_form', 'follow_up_form', 'review_form'):
        if context.get(key) is not None:
            describe_fields(context[key])
    if context.get('batch_form') is not None:
        for entry_form in context['batch_form'].forms:
            describe_fields(entry_form)


def _render(request, state, **context):
    _describe_capture_forms(context)
    return render(
        request, 'entries/capture.html', {'state': state, **_progress_thresholds(), **context}
    )


@sensitive_post_parameters('text', 'content')
@require_http_methods(['GET', 'POST'])
@login_required
def capture(request):
    membership = _require_parent(request)

    if request.method == 'GET':
        saved_entries = _saved_entries(membership, request.GET.get('saved', ''))
        return _render(
            request,
            'saved' if saved_entries else 'empty',
            capture_form=CaptureForm(),
            saved_entries=saved_entries,
        )

    capture_form = CaptureForm(request.POST)
    if not capture_form.is_valid():
        return _render(request, 'empty', capture_form=capture_form)

    text = capture_form.cleaned_data['text']
    today = timezone.localdate()
    batch = classify_entries_for_parent(membership, text, reference_date=today)
    if not batch.is_single:
        return _render(
            request,
            'batch',
            batch_form=batch_review_form_from_classification(membership, batch, today=today),
        )

    outcome = batch.single
    result = outcome.result

    if isinstance(result, ClassificationUnavailable) and (
        result.reason == UnavailableReason.INPUT_TOO_LONG
    ):
        capture_form.add_error('text', INPUT_TOO_LONG_ERROR)
        return _render(request, 'empty', capture_form=capture_form)

    if isinstance(result, ClassificationFollowUp):
        return _render(
            request,
            'question',
            follow_up_form=follow_up_form_from_classification(membership, outcome, text),
        )

    review_form, _ = review_form_from_classification(membership, outcome, text, today=today)
    state = 'proposal' if isinstance(result, ClassificationProposal) else 'unavailable'
    notice = ''
    if state == 'unavailable':
        too_many = result.reason == UnavailableReason.TOO_MANY_ENTRIES
        notice = TOO_MANY_ENTRIES_NOTICE if too_many else UNAVAILABLE_NOTICE
    return _render(request, state, review_form=review_form, notice=notice)


@sensitive_post_parameters('text', 'content', 'answer')
@require_POST
@login_required
def answer(request):
    """Classify the parent's answer to the follow-up question, or skip it.

    Nothing is saved here: every path ends on a review form posted to
    ``confirm``. The draft comes back from hidden fields and is re-validated.
    """
    membership = _require_parent(request)
    skip = request.POST.get('action') == 'skip'
    form = FollowUpAnswerForm(membership, request.POST, skip=skip)
    if not form.is_valid():
        return _render(request, 'question', follow_up_form=form)

    text = form.cleaned_data['text']
    today = timezone.localdate()
    draft, member = draft_from_form(form)
    if not draft.missing_fields:
        # A stale or tampered form: nothing is left to ask, so no backend call.
        review_form, _ = review_form_from_classification(
            membership,
            ParentClassification(result=proposal_from_draft(draft), member=member),
            text,
            today=today,
        )
        return _render(request, 'proposal', review_form=review_form)

    if skip:
        return _render(
            request,
            'skipped',
            review_form=skip_review_form(membership, draft, member, today=today),
            notice=SKIPPED_NOTICE,
        )

    outcome = classify_follow_up_answer(
        membership,
        text,
        draft,
        form.cleaned_data['answer'],
        reference_date=today,
        draft_member=member,
    )
    result = outcome.result
    notice = ''
    if isinstance(result, ClassificationProposal):
        state = 'proposal'
    elif isinstance(result, ClassificationFollowUp):
        state = 'follow_up'
    else:
        state = 'follow_up'
        outcome = ParentClassification(result=draft, member=member)
        notice = ANSWER_UNAVAILABLE_NOTICE
    review_form, _ = review_form_from_classification(membership, outcome, text, today=today)
    return _render(request, state, review_form=review_form, notice=notice)


def _correction_notice(form, changed):
    labels = [
        str(form.fields[form_field].label).lower()
        for name, form_field in _CORRECTION_FIELD_ORDER
        if name in changed
    ]
    return CORRECTION_APPLIED_NOTICE.format(fields=', '.join(labels))


def _with_fresh_key(form_class, membership, data, **kwargs):
    """A bound form re-validated with the posted values and a new submission key."""
    retry_data = data.copy()
    retry_data['submission_key'] = str(uuid.uuid4())
    form = form_class(membership, retry_data, **kwargs)
    form.is_valid()
    return form


@sensitive_post_parameters('text', 'content', 'correction')
@require_POST
@login_required
def correct(request):
    """Apply the parent's free-text correction to the proposal on screen.

    Nothing is saved here: the revised proposal (or the unchanged one, with a
    notice) comes back on a review form posted to ``confirm``.
    """
    membership = _require_parent(request)
    form = ProposalCorrectionForm(membership, request.POST)
    if not form.is_valid():
        return _render(request, 'invalid', review_form=form)

    today = timezone.localdate()
    current, member = proposal_values_from_form(form)
    correction = correct_proposal_for_parent(
        membership,
        current,
        form.cleaned_data['correction'],
        reference_date=today,
        current_member=member,
    )
    if correction.applied:
        review_form, _ = review_form_from_classification(
            membership, correction.outcome, current.content, today=today
        )
        state = (
            'proposal'
            if isinstance(correction.outcome.result, ClassificationProposal)
            else 'follow_up'
        )
        return _render(
            request,
            state,
            review_form=review_form,
            notice=_correction_notice(review_form, correction.changed),
        )

    retry_form = _with_fresh_key(ProposalCorrectionForm, membership, request.POST, today=today)
    notice = CORRECTION_FAILED_NOTICE
    if correction.rejection == CorrectionRejection.TOO_LONG:
        retry_form.add_error('correction', CORRECTION_TOO_LONG_ERROR)
        notice = ''
    elif correction.rejection == CorrectionRejection.SCHOOL_ITEM_MISMATCH:
        label = dict(Entry.ENTRY_TYPE_CHOICES)[correction.school_item.entry_type.value]
        notice = CORRECTION_SCHOOL_ITEM_NOTICE.format(label=label)
    return _render(request, 'correction_failed', review_form=retry_form, notice=notice)


@sensitive_post_parameters('text', 'content', 'correction')
@require_POST
@login_required
def confirm(request):
    membership = _require_parent(request)
    review_form = EntryReviewForm(membership, request.POST)
    if not review_form.is_valid():
        if review_form.has_error('correction'):
            # An unapplied correction: nothing is saved, and the next save
            # gets a new key.
            review_form = _with_fresh_key(EntryReviewForm, membership, request.POST)
        return _render(request, 'invalid', review_form=review_form)

    data = review_form.cleaned_data
    try:
        entry, _ = save_confirmed_entry(
            membership,
            entry_type=data['entry_type'],
            content=data['content'],
            date=data['date'],
            time=data['time'],
            assigned_member=data['assigned_member'],
            school_item=data['school_item'],
            school_subject=data['school_subject'],
            submission_key=data['submission_key'],
        )
    except ValidationError as error:
        _log_rejected_save(error)
        retry_data = request.POST.copy()
        retry_data['submission_key'] = str(uuid.uuid4())
        retry_form = EntryReviewForm(membership, retry_data)
        retry_form.is_valid()
        retry_form.add_error(None, SAVE_FAILED_ERROR)
        return _render(request, 'invalid', review_form=retry_form)

    return redirect(f"{reverse('entries:capture')}?saved={entry.pk}")


def _with_fresh_batch_keys(data, count):
    """The posted batch with a new submission key for every proposal."""
    retry_data = data.copy()
    for index in range(count):
        retry_data[f'{BatchReviewForm.prefix(index)}-submission_key'] = str(uuid.uuid4())
    return retry_data


def _render_batch(request, form):
    return _render(request, 'batch', batch_form=form)


# Every posted value may be family text (several prefixed ``content`` and
# ``correction`` fields), so all parameters are hidden from error reports.
@sensitive_post_parameters()
@require_POST
@login_required
def confirm_batch(request):
    """Save the included proposals of a batch all-or-nothing, or correct one.

    ``action=save`` (the default) saves; ``action=correct-<i>`` applies the
    free-text correction of proposal ``i`` and re-renders the batch.
    """
    membership = _require_parent(request)
    form = BatchReviewForm(membership, request.POST)
    if form.correcting or form.stale:
        return _correct_batch_entry(request, membership, form)
    if not form.is_valid():
        return _render_batch(request, form)

    try:
        entries = save_confirmed_entries(membership, form.save_items())
    except ValidationError as error:
        _log_rejected_save(error)
        retry_form = BatchReviewForm(membership, _with_fresh_batch_keys(request.POST, form.count))
        retry_form.is_valid()
        retry_form.add_error(SAVE_FAILED_ERROR)
        return _render_batch(request, retry_form)

    saved = ','.join(str(entry.pk) for entry in entries)
    return redirect(f"{reverse('entries:capture')}?saved={saved}")


# Keeps a posted ID inside the database integer range.
_MAX_ID_DIGITS = 18


def _correct_batch_entry(request, membership, form):
    """Correct only the targeted proposal; every other one is carried through.

    Nothing is saved. Every proposal gets a new submission key, so the next
    save is a fresh one.
    """
    if form.stale or not form.is_target_valid():
        return _render_batch(request, form)

    index = form.target
    target = form.target_form
    today = timezone.localdate()
    current, member = proposal_values_from_form(target)
    correction = correct_proposal_for_parent(
        membership,
        current,
        target.cleaned_data['correction'],
        reference_date=today,
        current_member=member,
    )

    retry_form = BatchReviewForm(
        membership, _with_fresh_batch_keys(request.POST, form.count), today=today
    )
    retry_form.is_target_valid()
    number = index + 1
    if correction.applied:
        initial, missing = review_initial_from_classification(correction.outcome, current.content)
        initial['include'] = target.cleaned_data['include']
        corrected = BatchEntryForm(
            membership,
            prefix=BatchReviewForm.prefix(index),
            initial=initial,
            missing=missing,
            today=today,
        )
        retry_form.replace_form(index, corrected)
        notice = _correction_notice(corrected, correction.changed)
        retry_form.notices[index] = BATCH_CORRECTION_NOTICE.format(
            number=number, notice=notice[:1].lower() + notice[1:]
        )
        return _render_batch(request, retry_form)

    notice = CORRECTION_FAILED_NOTICE
    if correction.rejection == CorrectionRejection.TOO_LONG:
        retry_form.target_form.add_error('correction', CORRECTION_TOO_LONG_ERROR)
        notice = ''
    elif correction.rejection == CorrectionRejection.SCHOOL_ITEM_MISMATCH:
        label = dict(Entry.ENTRY_TYPE_CHOICES)[correction.school_item.entry_type.value]
        notice = CORRECTION_SCHOOL_ITEM_NOTICE.format(label=label)
    if notice:
        retry_form.notices[index] = BATCH_CORRECTION_NOTICE.format(number=number, notice=notice)
    return _render_batch(request, retry_form)


def _saved_entries(membership, saved):
    """Up to ``MAX_PROPOSALS_PER_INSTRUCTION`` family entries named in ``saved``.

    ``saved`` is a comma-separated list of IDs, kept in the posted order.
    Anything else (non-digit parts, too many IDs, other families' entries)
    is ignored.
    """
    parts = saved.split(',') if saved else []
    if len(parts) > MAX_PROPOSALS_PER_INSTRUCTION:
        return []
    ids = list(dict.fromkeys(
        int(part) for part in parts
        if part.isascii() and part.isdigit() and len(part) <= _MAX_ID_DIGITS
    ))
    if not ids:
        return []
    found = scope_queryset_to_family(
        Entry.objects.select_related('assigned_member'), membership
    ).in_bulk(ids)
    return [found[pk] for pk in ids if pk in found]


# Fictional kitchen-sink data: never real family members or saved rows.
# Children first, then one parent (S-07), in the real form's pk-like order.
# One table feeds the form choices and the synthetic list rows (S-08 grouping):
# (choice value, synthetic pk, display name, role).
STATES_PARENT_NAME = 'Marta'
STATES_MEMBERS = (
    ('s1', 900101, 'Kasia', FamilyMember.Role.CHILD),
    ('s2', 900102, 'Tymek', FamilyMember.Role.CHILD),
    ('s3', 900103, STATES_PARENT_NAME, FamilyMember.Role.PARENT),
)
STATES_MEMBER_CHOICES = [('', 'Cała rodzina')] + [
    (value, name) for value, _pk, name, _role in STATES_MEMBERS
]
# Also the gallery's fictional "today", so the past-date warning is deterministic.
STATES_DATE = datetime.date(2026, 10, 5)


# Progress states (S-06) shown statically in the gallery, with their labels.
PROGRESS_STATE_LABELS = (
    ('running', 'trwa'),
    ('slow', 'dłużej niż zwykle'),
    ('stalled', 'brak odpowiedzi'),
    ('offline', 'brak połączenia przed wysłaniem'),
    ('connection_lost', 'utracone połączenie'),
)
PROGRESS_STATES_TEXT = 'Kasia ma jutro sprawdzian z matematyki'


def states(request):
    """DEBUG-only page rendering every capture state from unsaved synthetic data."""
    if not settings.DEBUG:
        raise Http404
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    membership = _require_parent(request)

    def synthetic_review(result, member_value='', text=''):
        form, _ = review_form_from_classification(
            membership, ParentClassification(result=result), text, today=STATES_DATE
        )
        _use_synthetic_members(form)
        form.initial['assigned_member'] = member_value
        return form

    proposal = ClassificationProposal(
        entry_type=EntryType.CALENDAR_EVENT,
        content='Sprawdzian z historii o średniowieczu',
        date=STATES_DATE,
        time=datetime.time(8, 0),
        school_item=SchoolItemKind.TEST,
        school_subject='historia',
    )
    past_proposal = ClassificationProposal(
        entry_type=EntryType.TODO,
        content='Oddać zgodę na wycieczkę',
        date=STATES_DATE - datetime.timedelta(days=4),
    )
    invalid_form = EntryReviewForm(
        membership,
        {
            'entry_type': EntryType.CALENDAR_EVENT.value,
            'content': '',
            'date': '',
            'time': '',
            'assigned_member': '',
            'school_item': SchoolItemKind.TEST.value,
            'school_subject': '',
            'submission_key': str(uuid.uuid4()),
        },
    )
    _use_synthetic_members(invalid_form)
    invalid_form.is_valid()
    saved_entry = Entry(
        entry_type=EntryType.CALENDAR_EVENT.value,
        content='Sprawdzian z historii o średniowieczu',
        date=STATES_DATE,
        time=datetime.time(8, 0),
        assigned_member=FamilyMember(display_name='Kasia'),
    )

    def synthetic_question(draft, text):
        return follow_up_form_from_classification(
            membership, ParentClassification(result=draft), text
        )

    date_draft = ClassificationFollowUp(
        missing_fields=(MissingField.DATE,),
        entry_type=EntryType.CALENDAR_EVENT,
        content='Wywiadówka w szkole',
    )
    combined_draft = ClassificationFollowUp(
        missing_fields=(MissingField.DATE, MissingField.AMBIGUOUS_MEMBER),
        entry_type=EntryType.CALENDAR_EVENT,
        content='Sprawdzian z angielskiego',
        school_item=SchoolItemKind.TEST,
        school_subject='angielski',
    )
    # A short name ("Hania") that fits several family members (Hanna, Anna).
    ambiguous_member_draft = ClassificationFollowUp(
        missing_fields=(MissingField.AMBIGUOUS_MEMBER,),
        entry_type=EntryType.CALENDAR_EVENT,
        content='Dentysta',
        date=STATES_DATE + datetime.timedelta(days=1),
    )
    subject_draft = ClassificationFollowUp(
        missing_fields=(MissingField.SCHOOL_SUBJECT,),
        entry_type=EntryType.CALENDAR_EVENT,
        content='Sprawdzian',
        date=STATES_DATE,
        school_item=SchoolItemKind.TEST,
    )
    skipped_form = skip_review_form(membership, combined_draft, None, today=STATES_DATE)
    _use_synthetic_members(skipped_form)
    meeting = ClassificationProposal(
        entry_type=EntryType.CALENDAR_EVENT,
        content='Spotkanie z wychowawczynią',
        date=STATES_DATE + datetime.timedelta(days=10),
        time=datetime.time(17, 0),
    )
    corrected_form = synthetic_review(meeting)
    failed_correction_form = synthetic_review(
        replace(meeting, date=STATES_DATE + datetime.timedelta(days=4))
    )
    failed_correction_form.initial['correction'] = 'bla bla'

    def synthetic_batch(*results, reference=STATES_DATE):
        batch = ParentBatchClassification(
            items=tuple(ParentClassification(result=result) for result in results)
        )
        form = batch_review_form_from_classification(membership, batch, today=reference)
        for entry_form in form.forms:
            _use_synthetic_members(entry_form)
        return form

    def batch_meeting(date, **overrides):
        values = dict(
            entry_type=EntryType.CALENDAR_EVENT,
            content='Spotkanie z wychowawczynią',
            date=date,
            time=datetime.time(18, 0),
        )
        values.update(overrides)
        return ClassificationProposal(**values)

    # „dziś, jutro i w przyszłym tygodniu w poniedziałek o 18:00”
    meeting_dates = (
        STATES_DATE,
        STATES_DATE + datetime.timedelta(days=1),
        STATES_DATE + datetime.timedelta(days=7),
    )
    # Said on Sunday: „jutro” and „w przyszłym tygodniu w poniedziałek” are one day.
    sunday = STATES_DATE - datetime.timedelta(days=1)
    duplicate_batch = synthetic_batch(
        batch_meeting(STATES_DATE), batch_meeting(STATES_DATE), reference=sunday
    )
    missing_batch = synthetic_batch(
        batch_meeting(meeting_dates[0]),
        ClassificationFollowUp(
            missing_fields=(MissingField.DATE,),
            entry_type=EntryType.CALENDAR_EVENT,
            content='Spotkanie z wychowawczynią',
            time=datetime.time(18, 0),
        ),
    )
    invalid_batch_data = {'count': '2', 'action': 'save'}
    for index, date in enumerate(meeting_dates[:2]):
        invalid_batch_data.update({
            f'e{index}-entry_type': EntryType.CALENDAR_EVENT.value,
            f'e{index}-content': 'Spotkanie z wychowawczynią',
            f'e{index}-date': date.isoformat(),
            f'e{index}-time': '18:00',
            f'e{index}-submission_key': str(uuid.uuid4()),
        })
    invalid_batch = BatchReviewForm(membership, invalid_batch_data)
    for entry_form in invalid_batch.forms:
        _use_synthetic_members(entry_form)
    invalid_batch.is_valid()
    corrected_batch = synthetic_batch(
        batch_meeting(meeting_dates[0]),
        batch_meeting(meeting_dates[1], time=datetime.time(19, 0)),
        batch_meeting(meeting_dates[2]),
    )
    corrected_batch.notices[1] = BATCH_CORRECTION_NOTICE.format(
        number=2, notice='zaktualizowano: godzina.'
    )
    saved_meetings = [
        Entry(
            entry_type=EntryType.CALENDAR_EVENT.value,
            content='Spotkanie z wychowawczynią',
            date=date,
            time=datetime.time(18, 0),
        )
        for date in meeting_dates
    ]

    sections = [
        {'name': 'empty', 'label': 'Pusty formularz', 'capture_form': CaptureForm()},
        {
            'name': 'proposal',
            'label': 'Propozycja do sprawdzenia',
            'review_form': synthetic_review(proposal, member_value='s1'),
        },
        {
            'name': 'past_date',
            'label': 'Propozycja z datą w przeszłości',
            'review_form': synthetic_review(past_proposal, member_value='s2'),
        },
        {
            'name': 'follow_up',
            'label': 'Brakująca data',
            'review_form': synthetic_review(
                ClassificationFollowUp(
                    missing_fields=(MissingField.DATE,),
                    entry_type=EntryType.CALENDAR_EVENT,
                    content='Kartkówka z matematyki',
                    school_item=SchoolItemKind.QUIZ,
                    school_subject='matematyka',
                ),
                member_value='s2',
            ),
        },
        {
            'name': 'follow_up_subject',
            'label': 'Brakujący przedmiot',
            'review_form': synthetic_review(subject_draft, member_value='s1'),
        },
        {
            'name': 'follow_up_member',
            'label': 'Niejednoznaczna osoba',
            'review_form': synthetic_review(
                ClassificationFollowUp(
                    missing_fields=(MissingField.AMBIGUOUS_MEMBER,),
                    entry_type=EntryType.CALENDAR_EVENT,
                    content='Zadanie domowe z polskiego',
                    date=STATES_DATE,
                    school_item=SchoolItemKind.HOMEWORK,
                    school_subject='polski',
                )
            ),
        },
        {
            'name': 'unavailable',
            'label': 'Rozpoznanie niedostępne',
            'notice': UNAVAILABLE_NOTICE,
            'review_form': synthetic_review(
                ClassificationUnavailable(reason=UnavailableReason.TIMEOUT),
                text='Kupić blok techniczny na plastykę',
            ),
        },
        {
            'name': 'question',
            'label': 'Pytanie: brakująca data',
            'follow_up_form': synthetic_question(date_draft, 'Wywiadówka w szkole'),
        },
        {
            'name': 'question_combined',
            'label': 'Pytanie: brakująca data i osoba',
            'follow_up_form': synthetic_question(
                combined_draft, 'Sprawdzian z angielskiego, trzeba się przygotować'
            ),
        },
        {
            'name': 'question_ambiguous_member',
            'label': 'Pytanie: zdrobnienie pasuje do kilku osób',
            'follow_up_form': synthetic_question(
                ambiguous_member_draft, 'Hania ma jutro dentystę'
            ),
        },
        {
            'name': 'question_subject',
            'label': 'Pytanie: brakujący przedmiot',
            'follow_up_form': synthetic_question(subject_draft, 'Kasia ma dziś sprawdzian'),
        },
        {
            'name': 'answer_unavailable',
            'label': 'Odpowiedź nierozpoznana',
            'notice': ANSWER_UNAVAILABLE_NOTICE,
            'review_form': synthetic_review(combined_draft),
        },
        {
            'name': 'skipped',
            'label': 'Pytanie pominięte',
            'notice': SKIPPED_NOTICE,
            'review_form': skipped_form,
        },
        {
            'name': 'corrected',
            'label': 'Propozycja po poprawce',
            'notice': CORRECTION_APPLIED_NOTICE.format(fields='data'),
            'review_form': corrected_form,
        },
        {
            'name': 'correction_failed',
            'label': 'Poprawka niezastosowana',
            'notice': CORRECTION_FAILED_NOTICE,
            'review_form': failed_correction_form,
        },
        {'name': 'invalid', 'label': 'Błędy w formularzu', 'review_form': invalid_form},
        {
            'name': 'saved',
            'label': 'Zapisano',
            'saved_entries': [saved_entry],
            'capture_form': CaptureForm(),
        },
        {
            'name': 'batch',
            'label': 'Kilka wpisów do sprawdzenia',
            'batch_form': synthetic_batch(*(batch_meeting(date) for date in meeting_dates)),
        },
        {
            'name': 'batch_duplicate',
            'label': 'Kilka wpisów: dwa takie same (polecenie w niedzielę)',
            'batch_form': duplicate_batch,
        },
        {
            'name': 'batch_missing',
            'label': 'Kilka wpisów: brakująca data',
            'batch_form': missing_batch,
        },
        {
            'name': 'batch_invalid',
            'label': 'Kilka wpisów: nic nie wybrano',
            'batch_form': invalid_batch,
        },
        {
            'name': 'batch_corrected',
            'label': 'Kilka wpisów: jeden po poprawce',
            'batch_form': corrected_batch,
        },
        {
            'name': 'batch_saved',
            'label': 'Zapisano kilka wpisów',
            'saved_entries': saved_meetings,
            'capture_form': CaptureForm(),
        },
        {
            'name': 'too_many',
            'label': 'Za dużo wpisów w poleceniu',
            'notice': TOO_MANY_ENTRIES_NOTICE,
            'review_form': synthetic_review(
                ClassificationUnavailable(reason=UnavailableReason.TOO_MANY_ENTRIES),
                text='Trening codziennie przez dwa tygodnie o 17:00',
            ),
        },
        *(
            {
                'name': f'progress_{state}',
                'label': f'Postęp rozpoznawania: {label}',
                'capture_form': CaptureForm(initial={'text': PROGRESS_STATES_TEXT}),
                'progress_state': state,
            }
            for state, label in PROGRESS_STATE_LABELS
        ),
    ]
    for section in sections:
        _describe_capture_forms(section)
    return render(
        request,
        'entries/states.html',
        {
            'sections': sections,
            'manage_sections': _manage_state_sections(membership),
            **_progress_thresholds(),
        },
    )


def _use_synthetic_members(form):
    form.fields['assigned_member'].choices = STATES_MEMBER_CHOICES


# --- Parent family entry management (S-02) ---

LIST_MODE_LABELS = {UPCOMING: 'Nadchodzące', PAST: 'Minione'}
# Day group of the undated upcoming section, shown last (parent and child lists).
UNDATED_DAY_KEY = 'undated'
UNDATED_DAY_HEADING = 'Bez daty'
EMPTY_LIST_MESSAGES = {
    UPCOMING: 'Nie ma nadchodzących wpisów.',
    PAST: 'Nie ma minionych wpisów.',
}
ENTRY_CREATED_MESSAGE = 'Dodano wpis.'
ENTRY_UPDATED_MESSAGE = 'Zapisano zmiany.'
ENTRY_DELETED_MESSAGE = 'Usunięto wpis.'


def _index_url(mode):
    return f"{reverse('entries:index')}?view={normalize_list_mode(mode)}"


def _list_mode_for(entry, today):
    """The list an entry appears in: past for an effective date before today."""
    effective_date = getattr(entry, 'effective_date', entry.date)
    return PAST if effective_date is not None and effective_date < today else UPCOMING


def _managed_entry_or_404(membership, pk):
    """Resolve an entry in the parent's family; missing and foreign IDs are both 404."""
    try:
        return with_effective_date(parent_family_entries(membership)).get(pk=pk)
    except Entry.DoesNotExist:
        raise Http404 from None


FAMILY_GROUP_HEADING = 'Cała rodzina'


def _assignee_heading(member):
    if member is None:
        return FAMILY_GROUP_HEADING
    if not member.is_active:
        return f'{member.display_name}{INACTIVE_MEMBER_SUFFIX}'
    return member.display_name


def _index_days(sections, today):
    """Day groups over the partitioned ``sections`` (each evaluated once), as in
    the child list; inside a day, assignee sub-groups in S-08 order. The undated
    upcoming section becomes one final "Bez daty" day."""
    days = []
    for section in sections:
        entries = list(section.entries)
        if not entries:
            continue
        if section.key == SECTION_UNDATED:
            day_rows = [(UNDATED_DAY_KEY, UNDATED_DAY_HEADING, entries)]
        else:
            day_rows = [
                (rows[0].effective_date.isoformat(), heading, rows)
                for heading, rows in group_by_day(entries, today)
            ]
        days.extend(
            {
                'key': key,
                'heading': heading,
                'groups': [
                    {
                        'key': group.key,
                        'heading': _assignee_heading(group.member),
                        'entries': group.entries,
                    }
                    for group in split_by_assignee(rows)
                ],
            }
            for key, heading, rows in day_rows
        )
    return days


def _index_context(mode, sections, today):
    days = _index_days(sections, today)
    return {
        'mode': mode,
        'modes': [(key, LIST_MODE_LABELS[key]) for key in LIST_MODES],
        'days': days,
        'is_empty': not days,
        'empty_message': EMPTY_LIST_MESSAGES[mode],
    }


def _detail_context(entry, list_mode, delete_open=False):
    return {'entry': entry, 'list_mode': list_mode, 'delete_open': delete_open}


def _form_context(form, *, entry=None):
    describe_fields(form)
    return {'form': form, 'entry': entry}


@require_http_methods(['GET'])
@login_required
def index(request):
    mode = normalize_list_mode(request.GET.get('view', ''))
    membership = _require_parent(request)
    today = timezone.localdate()
    sections = partition_entries(parent_family_entries(membership), mode, today)
    return render(request, 'entries/manage_index.html', _index_context(mode, sections, today))


@require_http_methods(['GET'])
@login_required
def detail(request, pk):
    entry = _managed_entry_or_404(_require_parent(request), pk)
    list_mode = _list_mode_for(entry, timezone.localdate())
    return render(request, 'entries/manage_detail.html', _detail_context(entry, list_mode))


@sensitive_post_parameters('content')
@require_http_methods(['GET', 'POST'])
@login_required
def create(request):
    membership = _require_parent(request)
    if request.method == 'GET':
        form = EntryCreateForm(membership)
        return render(request, 'entries/manage_form.html', _form_context(form))

    form = EntryCreateForm(membership, request.POST)
    if form.is_valid():
        data = form.cleaned_data
        try:
            entry, _ = create_family_entry(
                membership,
                entry_type=data['entry_type'],
                content=data['content'],
                date=data['date'],
                time=data['time'],
                assigned_member=data['assigned_member'],
                school_item=data['school_item'],
                school_subject=data['school_subject'],
                submission_key=data['submission_key'],
            )
        except ValidationError as error:
            _log_rejected_save(error)
            retry_data = request.POST.copy()
            retry_data['submission_key'] = str(uuid.uuid4())
            form = EntryCreateForm(membership, retry_data)
            form.is_valid()
            form.add_error(None, SAVE_FAILED_ERROR)
        else:
            messages.success(request, ENTRY_CREATED_MESSAGE)
            return redirect('entries:detail', pk=entry.pk)
    return render(request, 'entries/manage_form.html', _form_context(form))


@sensitive_post_parameters('content')
@require_http_methods(['GET', 'POST'])
@login_required
def edit(request, pk):
    membership = _require_parent(request)
    entry = _managed_entry_or_404(membership, pk)
    if request.method == 'GET':
        form = EntryEditForm(membership, entry=entry)
        return render(request, 'entries/manage_form.html', _form_context(form, entry=entry))

    form = EntryEditForm(membership, request.POST, entry=entry)
    if form.is_valid():
        data = form.cleaned_data
        try:
            update_family_entry(
                membership,
                entry.pk,
                entry_type=data['entry_type'],
                content=data['content'],
                date=data['date'],
                time=data['time'],
                assigned_member=data['assigned_member'],
                school_item=data['school_item'],
                school_subject=data['school_subject'],
            )
        except Entry.DoesNotExist:
            raise Http404 from None
        except ValidationError as error:
            _log_rejected_save(error)
            form.add_error(None, SAVE_FAILED_ERROR)
        else:
            messages.success(request, ENTRY_UPDATED_MESSAGE)
            return redirect('entries:detail', pk=entry.pk)
    return render(request, 'entries/manage_form.html', _form_context(form, entry=entry))


@require_POST
@login_required
def delete(request, pk):
    try:
        delete_family_entry(_require_parent(request), pk)
    except Entry.DoesNotExist:
        raise Http404 from None
    messages.success(request, ENTRY_DELETED_MESSAGE)
    return redirect(_index_url(request.POST.get('view', '')))


# Fictional management kitchen-sink data (DEBUG gallery): unsaved rows only.
STATES_ENTRY_PK = 900001


def _synthetic_entry(offset, **fields):
    """An unsaved entry with explicit provenance; the pk only feeds URL reversing."""
    created_at = timezone.make_aware(datetime.datetime(2026, 9, 21, 18, 40))
    values = dict(
        pk=STATES_ENTRY_PK + offset,
        entry_type=EntryType.TODO.value,
        source=Entry.Source.MANUAL,
        created_at=created_at,
        updated_at=created_at + datetime.timedelta(days=1, minutes=5),
    )
    values.update(fields)
    member = values.pop('member', None)
    entry = Entry(**values)
    entry.effective_date = entry.date
    if member:
        entry.assigned_member = _states_member(member)
    return entry


def _states_member(display_name):
    """Unsaved fictional member from ``STATES_MEMBERS``, with its synthetic pk and role."""
    for _value, pk, name, role in STATES_MEMBERS:
        if name == display_name:
            return FamilyMember(pk=pk, display_name=name, role=role, is_active=True)
    raise ValueError(f'Unknown gallery member: {display_name}')


def _synthetic_list(mode, sections):
    return _index_context(
        mode,
        [EntrySection(key, entries) for key, entries in sections],
        STATES_DATE,
    )


def _manage_state_sections(membership):
    """Management states for the DEBUG gallery; no family data is read or written."""
    test_entry = _synthetic_entry(
        1,
        entry_type=EntryType.CALENDAR_EVENT.value,
        content='Sprawdzian z historii o średniowieczu',
        date=STATES_DATE,
        time=datetime.time(8, 0),
        school_item=SchoolItemKind.TEST.value,
        school_subject='historia',
        member='Kasia',
    )
    trip = _synthetic_entry(
        2,
        entry_type=EntryType.CALENDAR_EVENT.value,
        content='Wycieczka klasowa do muzeum techniki',
        date=STATES_DATE + datetime.timedelta(days=2),
        member='Tymek',
    )
    long_note = _synthetic_entry(
        3,
        entry_type=EntryType.NOTE.value,
        content=(
            'Bardzo długa notatka: '
            + 'Konstantynopolitańczykowianeczka' * 3
            + ' oraz opis, który musi się zawinąć na wąskim ekranie telefonu.'
        ),
        member='Tymek',
    )
    undated = _synthetic_entry(4, content='Oddać książkę do biblioteki')
    parent_note = _synthetic_entry(
        7,
        entry_type=EntryType.NOTE.value,
        content='Odebrać paczkę z paczkomatu',
        date=STATES_DATE,
        time=datetime.time(16, 0),
        member=STATES_PARENT_NAME,
    )
    family_meeting = _synthetic_entry(
        8,
        entry_type=EntryType.CALENDAR_EVENT.value,
        content='Zebranie z wychowawczynią',
        date=STATES_DATE,
        time=datetime.time(17, 30),
    )
    past_entry = _synthetic_entry(
        5,
        content='Zapłacić za obiady',
        date=STATES_DATE - datetime.timedelta(days=14),
        time=datetime.time(7, 45),
    )
    eduvulcan_entry = _synthetic_entry(
        6,
        entry_type=EntryType.CALENDAR_EVENT.value,
        content='Kartkówka z matematyki — ułamki',
        date=STATES_DATE + datetime.timedelta(days=1),
        time=datetime.time(9, 50),
        school_item=SchoolItemKind.QUIZ.value,
        school_subject='matematyka',
        source=Entry.Source.EDUVULCAN,
        member='Tymek',
    )

    create_form = EntryCreateForm(membership)
    _use_synthetic_members(create_form)

    invalid_form = EntryCreateForm(
        membership,
        {
            'entry_type': EntryType.NOTE.value,
            'content': '',
            'date': '',
            'time': '',
            'assigned_member': '',
            'school_item': SchoolItemKind.TEST.value,
            'submission_key': str(uuid.uuid4()),
        },
    )
    _use_synthetic_members(invalid_form)
    invalid_form.is_valid()

    edit_form = EntryEditForm(membership, entry=test_entry)
    _use_synthetic_members(edit_form)
    edit_form.initial['assigned_member'] = 's1'

    return [
        {
            'name': 'list_upcoming',
            'label': 'Lista: nadchodzące',
            'list': _synthetic_list(
                UPCOMING,
                [
                    (SECTION_DATED, [test_entry, parent_note, family_meeting, trip]),
                    (SECTION_UNDATED, [long_note, undated]),
                ],
            ),
        },
        {
            'name': 'list_past',
            'label': 'Lista: minione',
            'list': _synthetic_list(PAST, [(SECTION_PAST, [past_entry])]),
        },
        {
            'name': 'list_empty',
            'label': 'Lista: pusta',
            'list': _synthetic_list(UPCOMING, [(SECTION_DATED, []), (SECTION_UNDATED, [])]),
        },
        {
            'name': 'detail_manual',
            'label': 'Szczegóły: wpis ręczny',
            'detail': _detail_context(test_entry, UPCOMING),
        },
        {
            'name': 'detail_eduvulcan',
            'label': 'Szczegóły: wpis z EduVulcan',
            'detail': _detail_context(eduvulcan_entry, UPCOMING),
        },
        {'name': 'create', 'label': 'Nowy wpis', 'form': _form_context(create_form)},
        {'name': 'invalid', 'label': 'Błędy w formularzu', 'form': _form_context(invalid_form)},
        {
            'name': 'edit',
            'label': 'Edycja wpisu',
            'form': _form_context(edit_form, entry=test_entry),
        },
        {
            'name': 'delete_open',
            'label': 'Otwarte potwierdzenie usunięcia',
            'detail': _detail_context(past_entry, PAST, delete_open=True),
        },
    ]


# --- Child assigned entry view (S-03) ---

CHILD_EMPTY_MESSAGES = {
    UPCOMING: 'Nie masz żadnych nadchodzących wpisów.',
    PAST: 'Nie masz żadnych minionych wpisów.',
}


def _child_list_context(mode, sections, today):
    """Template context for the child list body; ``sections`` are evaluated here.

    Dated sections become day groups headed relative to ``today``; the undated
    section is one group under ``UNDATED_DAY_HEADING``."""
    child_sections = []
    for section in sections:
        entries = list(section.entries)
        if not entries:
            continue
        if section.key == SECTION_UNDATED:
            groups = [{'heading': UNDATED_DAY_HEADING, 'entries': entries}]
        else:
            groups = [
                {'heading': heading, 'entries': rows}
                for heading, rows in group_by_day(entries, today)
            ]
        child_sections.append({'key': section.key, 'groups': groups})
    return {
        'mode': mode,
        'modes': [(key, LIST_MODE_LABELS[key]) for key in LIST_MODES],
        'detail_query': 'view=past' if mode == PAST else '',
        'sections': child_sections,
        'empty_message': CHILD_EMPTY_MESSAGES[mode],
    }


@require_GET
@login_required
def child_list(request):
    """The signed-in child's own entries, upcoming (default) or past."""
    entries = child_entries(resolve_family_context(request))
    mode = normalize_list_mode(request.GET.get('view'))
    today = timezone.localdate()
    sections = partition_entries(entries, mode, today)
    return render(
        request, 'entries/child_list.html', _child_list_context(mode, sections, today)
    )


@require_GET
@login_required
def child_detail(request, pk):
    """One entry assigned to the signed-in child; any other ID is a plain 404."""
    entries = child_entries(resolve_family_context(request))
    entry = get_object_or_404(with_effective_date(entries), pk=pk)
    return render(
        request,
        'entries/child_detail.html',
        {'entry': entry, 'back_mode': normalize_list_mode(request.GET.get('view'))},
    )


def _child_states_entry(pk, content, entry_type, *, date=None, time=None, school_item='',
                        school_subject='', source=Entry.Source.MANUAL, effective_date=None):
    """Unsaved fictional entry for the child gallery; never written."""
    entry = Entry(
        pk=pk,
        entry_type=entry_type.value,
        content=content,
        date=date,
        time=time,
        school_item=school_item,
        school_subject=school_subject,
        source=source,
        assigned_member=FamilyMember(display_name=STATES_MEMBER_CHOICES[1][1]),
        updated_at=timezone.make_aware(datetime.datetime.combine(STATES_DATE, datetime.time(7, 0))),
    )
    entry.effective_date = effective_date or date
    return entry


def child_states(request):
    """DEBUG-only gallery of every child-view state from unsaved synthetic data."""
    if not settings.DEBUG:
        raise Http404
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    require_family_context(request)

    day = datetime.timedelta(days=1)
    test = _child_states_entry(
        9001, 'Sprawdzian z matematyki: ułamki zwykłe i dziesiętne', EntryType.CALENDAR_EVENT,
        date=STATES_DATE, time=datetime.time(8, 0), school_item=SchoolItemKind.TEST.value,
    )
    grade = _child_states_entry(
        9002, 'Ocena 5 z języka polskiego za wypracowanie', EntryType.NOTE,
        school_item=SchoolItemKind.GRADE.value, effective_date=STATES_DATE,
    )
    todo = _child_states_entry(
        9003, 'Przynieść strój na WF', EntryType.TODO, date=STATES_DATE + day,
    )
    undated = _child_states_entry(
        9004,
        'Wycieczka do muzeum: zabrać drugie śniadanie, picie, legitymację, wygodne buty, '
        'kurtkę przeciwdeszczową i pieniądze na bilety oraz pamiątki. Zbiórka przy bramie '
        'szkoły, powrót około godziny piętnastej.',
        EntryType.NOTE,
    )
    quiz = _child_states_entry(
        9005, 'Kartkówka z przyrody', EntryType.CALENDAR_EVENT,
        date=STATES_DATE - 3 * day, time=datetime.time(10, 15),
        school_item=SchoolItemKind.QUIZ.value, school_subject='przyroda',
        source=Entry.Source.EDUVULCAN,
    )
    returned = _child_states_entry(
        9006, 'Oddać książkę do biblioteki', EntryType.TODO, date=STATES_DATE - 5 * day,
    )
    reading = _child_states_entry(
        9007, 'Przeczytać rozdział lektury', EntryType.TODO, date=STATES_DATE + 3 * day,
    )
    meeting = _child_states_entry(
        9008, 'Zebranie z rodzicami', EntryType.CALENDAR_EVENT,
        date=STATES_DATE + 21 * day, time=datetime.time(17, 30),
    )
    homework = _child_states_entry(
        9009, 'Zadanie domowe z angielskiego', EntryType.TODO, date=STATES_DATE - day,
    )
    start = _child_states_entry(
        9010, 'Rozpoczęcie roku szkolnego', EntryType.CALENDAR_EVENT,
        date=STATES_DATE - 30 * day, time=datetime.time(9, 0),
    )

    def list_state(name, label, mode, sections):
        return {'name': name, 'label': label, 'list': _child_list_context(mode, sections, STATES_DATE)}

    sections = [
        list_state('upcoming', 'Nadchodzące', UPCOMING, [
            EntrySection(SECTION_DATED, [test, grade, todo, reading, meeting]),
            EntrySection(SECTION_UNDATED, [undated]),
        ]),
        list_state('past', 'Minione', PAST, [
            EntrySection(SECTION_PAST, [homework, quiz, returned, start]),
        ]),
        list_state('upcoming_empty', 'Brak nadchodzących', UPCOMING, [
            EntrySection(SECTION_DATED, []),
            EntrySection(SECTION_UNDATED, []),
        ]),
        list_state('past_empty', 'Brak minionych', PAST, [EntrySection(SECTION_PAST, [])]),
        {'name': 'detail_manual', 'label': 'Szczegóły wpisu ręcznego',
         'entry': undated, 'back_mode': UPCOMING},
        {'name': 'detail_eduvulcan', 'label': 'Szczegóły wpisu z EduVulcan',
         'entry': quiz, 'back_mode': PAST},
        {'name': 'error_forbidden', 'label': 'Błąd: brak dostępu',
         'error': {'heading': 'Brak dostępu',
                   'message': 'Ta strona nie jest dostępna dla Twojego konta.'}},
    ]
    return render(request, 'entries/child_states.html', {'sections': sections})
