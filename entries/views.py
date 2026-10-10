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
from django.db.models import F
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from family_access.context import require_family_context, resolve_family_context
from family_access.models import FamilyMember
from family_notes.log_safety import exception_summary

from .classification.service import (
    MAX_PROPOSALS_PER_INSTRUCTION,
    CorrectionRejection,
    ParentBatchClassification,
    ParentClassification,
    classify_entries_for_child,
    classify_entries_for_parent,
    classify_follow_up_answer,
    classify_follow_up_answer_for_child,
    correct_proposal_for_child,
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
    EntryPrivacyForm,
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
    GROUP_FAMILY,
    is_weekend,
    parent_day_heading,
    split_by_assignee,
    with_effective_date,
)
from .models import Entry
from .services import (
    active_family_children,
    child_entries,
    create_family_entry,
    delete_family_entry,
    parent_family_entries,
    require_child_membership,
    require_parent_membership,
    save_child_entries,
    save_child_entry,
    save_confirmed_entries,
    save_confirmed_entry,
    set_entry_privacy,
    update_family_entry,
    visible_family_entries,
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


class _CaptureFlow:
    """One role's natural-language capture journey: who may use it, its services and routes.

    The parent flow is the original capture; the child flow reuses every step
    for an active child, whose services assign every entry to the child.
    Services are looked up when called (not bound at import time), and every
    step re-authorizes the request's family context.
    """

    def __init__(self, *, child):
        self.child = child
        prefix = 'entries:child_' if child else 'entries:'
        self.routes = {
            name: f'{prefix}{name}'
            for name in ('capture', 'answer', 'correct', 'confirm', 'confirm_batch')
        }
        self.template = 'entries/child_capture.html' if child else 'entries/capture.html'

    def authorize(self, request):
        membership = resolve_family_context(request)
        if self.child:
            return require_child_membership(membership)
        return require_parent_membership(membership)

    def classify_entries(self, membership, text, *, reference_date):
        classify = classify_entries_for_child if self.child else classify_entries_for_parent
        return classify(membership, text, reference_date=reference_date)

    def classify_answer(self, membership, text, draft, answer, *, reference_date, draft_member):
        if self.child:
            return classify_follow_up_answer_for_child(
                membership, text, draft, answer, reference_date=reference_date
            )
        return classify_follow_up_answer(
            membership, text, draft, answer,
            reference_date=reference_date, draft_member=draft_member,
        )

    def correct(self, membership, current, correction, *, reference_date, current_member):
        if self.child:
            return correct_proposal_for_child(
                membership, current, correction, reference_date=reference_date
            )
        return correct_proposal_for_parent(
            membership, current, correction,
            reference_date=reference_date, current_member=current_member,
        )

    def save_entry(self, membership, **values):
        save = save_child_entry if self.child else save_confirmed_entry
        return save(membership, **values)

    def save_entries(self, membership, items):
        save = save_child_entries if self.child else save_confirmed_entries
        return save(membership, items)

    def saved_entries(self, membership):
        """Entries the saved panel may name: the child's own, or the parent's visible ones."""
        return child_entries(membership) if self.child else visible_family_entries(membership)

    def capture_url(self):
        return reverse(self.routes['capture'])


PARENT_CAPTURE = _CaptureFlow(child=False)
CHILD_CAPTURE = _CaptureFlow(child=True)


def _render(request, flow, state, **context):
    _describe_capture_forms(context)
    return render(
        request,
        flow.template,
        {'state': state, 'capture_routes': flow.routes, **_progress_thresholds(), **context},
    )


@sensitive_post_parameters('text', 'content')
@require_http_methods(['GET', 'POST'])
@login_required
def capture(request):
    return _capture(request, PARENT_CAPTURE)


@sensitive_post_parameters('text', 'content')
@require_http_methods(['GET', 'POST'])
@login_required
def child_capture(request):
    """The child's natural-language capture; every entry is the child's own."""
    return _capture(request, CHILD_CAPTURE)


def _capture(request, flow):
    membership = flow.authorize(request)

    if request.method == 'GET':
        saved_entries = _saved_entries(flow.saved_entries(membership), request.GET.get('saved', ''))
        return _render(
            request,
            flow,
            'saved' if saved_entries else 'empty',
            capture_form=CaptureForm(),
            saved_entries=saved_entries,
        )

    capture_form = CaptureForm(request.POST)
    if not capture_form.is_valid():
        return _render(request, flow, 'empty', capture_form=capture_form)

    text = capture_form.cleaned_data['text']
    today = timezone.localdate()
    batch = flow.classify_entries(membership, text, reference_date=today)
    if not batch.is_single:
        return _render(
            request,
            flow,
            'batch',
            batch_form=batch_review_form_from_classification(membership, batch, today=today),
        )

    outcome = batch.single
    result = outcome.result

    if isinstance(result, ClassificationUnavailable) and (
        result.reason == UnavailableReason.INPUT_TOO_LONG
    ):
        capture_form.add_error('text', INPUT_TOO_LONG_ERROR)
        return _render(request, flow, 'empty', capture_form=capture_form)

    if isinstance(result, ClassificationFollowUp):
        return _render(
            request,
            flow,
            'question',
            follow_up_form=follow_up_form_from_classification(membership, outcome, text),
        )

    review_form, _ = review_form_from_classification(membership, outcome, text, today=today)
    state = 'proposal' if isinstance(result, ClassificationProposal) else 'unavailable'
    notice = ''
    if state == 'unavailable':
        too_many = result.reason == UnavailableReason.TOO_MANY_ENTRIES
        notice = TOO_MANY_ENTRIES_NOTICE if too_many else UNAVAILABLE_NOTICE
    return _render(request, flow, state, review_form=review_form, notice=notice)


@sensitive_post_parameters('text', 'content', 'answer')
@require_POST
@login_required
def answer(request):
    """Classify the parent's answer to the follow-up question, or skip it.

    Nothing is saved here: every path ends on a review form posted to
    ``confirm``. The draft comes back from hidden fields and is re-validated.
    """
    return _answer(request, PARENT_CAPTURE)


@sensitive_post_parameters('text', 'content', 'answer')
@require_POST
@login_required
def child_answer(request):
    """The child's answer to a follow-up question; the draft stays the child's own."""
    return _answer(request, CHILD_CAPTURE)


def _answer(request, flow):
    membership = flow.authorize(request)
    skip = request.POST.get('action') == 'skip'
    form = FollowUpAnswerForm(membership, request.POST, skip=skip)
    if not form.is_valid():
        return _render(request, flow, 'question', follow_up_form=form)

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
        return _render(request, flow, 'proposal', review_form=review_form)

    if skip:
        return _render(
            request,
            flow,
            'skipped',
            review_form=skip_review_form(membership, draft, member, today=today),
            notice=SKIPPED_NOTICE,
        )

    outcome = flow.classify_answer(
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
    return _render(request, flow, state, review_form=review_form, notice=notice)


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
    return _correct(request, PARENT_CAPTURE)


@sensitive_post_parameters('text', 'content', 'correction')
@require_POST
@login_required
def child_correct(request):
    """The child's free-text correction; the person never changes."""
    return _correct(request, CHILD_CAPTURE)


def _carry_privacy(initial, form):
    """Keep the privacy choice of a posted review form on the form that replaces it."""
    if 'is_private' in form.fields:
        initial['is_private'] = form.cleaned_data.get('is_private', False)


def _correct(request, flow):
    membership = flow.authorize(request)
    form = ProposalCorrectionForm(membership, request.POST)
    if not form.is_valid():
        return _render(request, flow, 'invalid', review_form=form)

    today = timezone.localdate()
    current, member = proposal_values_from_form(form)
    correction = flow.correct(
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
        _carry_privacy(review_form.initial, form)
        state = (
            'proposal'
            if isinstance(correction.outcome.result, ClassificationProposal)
            else 'follow_up'
        )
        return _render(
            request,
            flow,
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
    return _render(request, flow, 'correction_failed', review_form=retry_form, notice=notice)


@sensitive_post_parameters('text', 'content', 'correction')
@require_POST
@login_required
def confirm(request):
    return _confirm(request, PARENT_CAPTURE)


@sensitive_post_parameters('text', 'content', 'correction')
@require_POST
@login_required
def child_confirm(request):
    """Save the child's reviewed proposal for the child, public unless marked private."""
    return _confirm(request, CHILD_CAPTURE)


def _confirm(request, flow):
    membership = flow.authorize(request)
    review_form = EntryReviewForm(membership, request.POST)
    if not review_form.is_valid():
        if review_form.has_error('correction'):
            # An unapplied correction: nothing is saved, and the next save
            # gets a new key.
            review_form = _with_fresh_key(EntryReviewForm, membership, request.POST)
        return _render(request, flow, 'invalid', review_form=review_form)

    data = review_form.cleaned_data
    values = dict(
        entry_type=data['entry_type'],
        content=data['content'],
        date=data['date'],
        time=data['time'],
        assigned_member=data['assigned_member'],
        school_item=data['school_item'],
        school_subject=data['school_subject'],
        submission_key=data['submission_key'],
    )
    if 'is_private' in data:
        values['is_private'] = data['is_private']
    try:
        entry, _ = flow.save_entry(membership, **values)
    except ValidationError as error:
        _log_rejected_save(error)
        retry_data = request.POST.copy()
        retry_data['submission_key'] = str(uuid.uuid4())
        retry_form = EntryReviewForm(membership, retry_data)
        retry_form.is_valid()
        retry_form.add_error(None, SAVE_FAILED_ERROR)
        return _render(request, flow, 'invalid', review_form=retry_form)

    return redirect(f"{flow.capture_url()}?saved={entry.pk}")


def _with_fresh_batch_keys(data, count):
    """The posted batch with a new submission key for every proposal."""
    retry_data = data.copy()
    for index in range(count):
        retry_data[f'{BatchReviewForm.prefix(index)}-submission_key'] = str(uuid.uuid4())
    return retry_data


def _render_batch(request, flow, form):
    return _render(request, flow, 'batch', batch_form=form)


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
    return _confirm_batch(request, PARENT_CAPTURE)


# All parameters hidden, as in ``confirm_batch``.
@sensitive_post_parameters()
@require_POST
@login_required
def child_confirm_batch(request):
    """The child's batch save or correction; every proposal stays the child's own."""
    return _confirm_batch(request, CHILD_CAPTURE)


def _confirm_batch(request, flow):
    membership = flow.authorize(request)
    form = BatchReviewForm(membership, request.POST)
    if form.correcting or form.stale:
        return _correct_batch_entry(request, flow, membership, form)
    if not form.is_valid():
        return _render_batch(request, flow, form)

    try:
        entries = flow.save_entries(membership, form.save_items())
    except ValidationError as error:
        _log_rejected_save(error)
        retry_form = BatchReviewForm(membership, _with_fresh_batch_keys(request.POST, form.count))
        retry_form.is_valid()
        retry_form.add_error(SAVE_FAILED_ERROR)
        return _render_batch(request, flow, retry_form)

    saved = ','.join(str(entry.pk) for entry in entries)
    return redirect(f"{flow.capture_url()}?saved={saved}")


# Keeps a posted ID inside the database integer range.
_MAX_ID_DIGITS = 18


def _correct_batch_entry(request, flow, membership, form):
    """Correct only the targeted proposal; every other one is carried through.

    Nothing is saved. Every proposal gets a new submission key, so the next
    save is a fresh one.
    """
    if form.stale or not form.is_target_valid():
        return _render_batch(request, flow, form)

    index = form.target
    target = form.target_form
    today = timezone.localdate()
    current, member = proposal_values_from_form(target)
    correction = flow.correct(
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
        _carry_privacy(initial, target)
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
        return _render_batch(request, flow, retry_form)

    notice = CORRECTION_FAILED_NOTICE
    if correction.rejection == CorrectionRejection.TOO_LONG:
        retry_form.target_form.add_error('correction', CORRECTION_TOO_LONG_ERROR)
        notice = ''
    elif correction.rejection == CorrectionRejection.SCHOOL_ITEM_MISMATCH:
        label = dict(Entry.ENTRY_TYPE_CHOICES)[correction.school_item.entry_type.value]
        notice = CORRECTION_SCHOOL_ITEM_NOTICE.format(label=label)
    if notice:
        retry_form.notices[index] = BATCH_CORRECTION_NOTICE.format(number=number, notice=notice)
    return _render_batch(request, flow, retry_form)


def _saved_entries(entries, saved):
    """Up to ``MAX_PROPOSALS_PER_INSTRUCTION`` of ``entries`` named in ``saved``.

    ``entries`` is what the reader may see (``_CaptureFlow.saved_entries``).
    ``saved`` is a comma-separated list of IDs, kept in the posted order.
    Anything else (non-digit parts, too many IDs, other families' entries,
    other members' private entries, for a child anything not their own) is
    ignored.
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
    found = entries.in_bulk(ids)
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
STATES_MEMBER_CHOICES = [('', 'Ogólne')] + [
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
    private_review = synthetic_review(
        replace(proposal, content='Prezent urodzinowy dla Kasi'), member_value='s1'
    )
    private_review.initial['is_private'] = True
    saved_private_entry = Entry(
        entry_type=EntryType.TODO.value,
        content='Prezent urodzinowy dla Kasi',
        date=STATES_DATE,
        assigned_member=FamilyMember(display_name='Kasia'),
        is_private=True,
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
            'name': 'proposal_private',
            'label': 'Propozycja oznaczona jako prywatna',
            'review_form': private_review,
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
            'notice': CORRECTION_APPLIED_NOTICE.format(fields='data wydarzenia'),
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
            'name': 'saved_private',
            'label': 'Zapisano wpis prywatny',
            'saved_entries': [saved_private_entry],
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

CALENDAR_WINDOW_DAYS = 14
ENTRY_CREATED_MESSAGE = 'Dodano wpis.'
ENTRY_UPDATED_MESSAGE = 'Zapisano zmiany.'
ENTRY_DELETED_MESSAGE = 'Usunięto wpis.'
ENTRY_PRIVATE_MESSAGE = 'Wpis jest teraz prywatny — widoczny tylko dla Ciebie.'
ENTRY_PUBLIC_MESSAGE = 'Wpis nie jest już prywatny.'


def _index_url(start, member=None, privacy=None):
    return f"{reverse('entries:index')}?{_list_query(start, member, privacy)}"


def _calendar_window(value, today):
    """Return a valid inclusive 14-day calendar window; ``today``'s window by default.

    ``value`` must be a canonical ISO date whose window and both neighbouring windows
    stay inside the date range; anything else falls back to the window starting today."""
    step = datetime.timedelta(days=CALENDAR_WINDOW_DAYS)
    try:
        start = datetime.date.fromisoformat(value) if value else today
    except (TypeError, ValueError):
        start = today
    if value and start.isoformat() != value:
        start = today
    # The window and both neighbouring windows must stay inside the date range.
    if not datetime.date.min + step <= start <= datetime.date.max - 2 * step:
        start = today
    return start, start + datetime.timedelta(days=CALENDAR_WINDOW_DAYS - 1)


def _window_containing(day, today):
    """Start of the fortnight containing ``day`` on the 14-day grid anchored at ``today``."""
    offset = (day - today).days // CALENDAR_WINDOW_DAYS * CALENDAR_WINDOW_DAYS
    return today + datetime.timedelta(days=offset)


def _calendar_query(start):
    return f'start={start.isoformat()}'


# --- Parent calendar filter by child ---

ALL_MEMBERS_KEY = 'all'
ALL_MEMBERS_LABEL = 'Wszyscy'
ALL_MEMBERS_STATUS = 'Pokazano: wszystkie wpisy'


def _filter_query(member=None, privacy=None):
    """``member=<pk>`` for a selected child and ``privacy=<value>`` for a privacy filter,
    joined by ``&``; empty for "Wszyscy" / "Wszystkie"."""
    parts = []
    if member:
        parts.append(f'member={member.pk}')
    if privacy:
        parts.append(f'privacy={privacy}')
    return '&'.join(parts)


def _list_query(start, member=None, privacy=None):
    """The calendar state as a query string: ``start=<iso>`` plus the active filters."""
    filter_query = _filter_query(member, privacy)
    query = _calendar_query(start)
    return f'{query}&{filter_query}' if filter_query else query


def _member_key(member):
    """Assignee group key of the selected child (``split_by_assignee``), ``None`` for all."""
    return f'member-{member.pk}' if member else None


def _member_filter(membership, value):
    """``(children, selected)``: the family's active children and the one ``value`` names.

    Only the pk of an active child in the request's family selects; any other value (another
    family, a parent, an inactive child, junk) means "Wszyscy" and is never echoed back."""
    children = list(active_family_children(membership))
    selected = next((child for child in children if str(child.pk) == value), None)
    return children, selected


def _member_filters(children, selected, start, privacy=None):
    """Filter links of the parent calendar: "Wszyscy", then one per child (empty without children).

    Every link keeps the window and the privacy filter."""
    if not children:
        return []
    filters = [{
        'key': ALL_MEMBERS_KEY,
        'label': ALL_MEMBERS_LABEL,
        'status': ALL_MEMBERS_STATUS,
        'url': _index_url(start, privacy=privacy),
        'current': selected is None,
    }]
    for child in children:
        filters.append({
            'key': _member_key(child),
            'label': child.display_name,
            'status': f'Pokazano: {child.display_name} i {FAMILY_GROUP_HEADING}',
            'url': _index_url(start, child, privacy),
            'current': selected is not None and selected.pk == child.pk,
        })
    return filters


# --- Privacy filter (parent and child calendars) ---

PRIVACY_PRIVATE = 'private'
PRIVACY_PUBLIC = 'public'
ALL_PRIVACY_KEY = 'all'
# (query value, label); ``None`` is "Wszystkie", the default.
PRIVACY_FILTERS = (
    (None, 'Wszystkie'),
    (PRIVACY_PRIVATE, 'Prywatne'),
    (PRIVACY_PUBLIC, 'Nieprywatne'),
)


def _privacy_filter(value):
    """The privacy filter ``value`` names: ``"private"``, ``"public"`` or ``None`` (all).

    Any other value (missing, junk, another case) means "Wszystkie" and is never echoed."""
    return value if value in (PRIVACY_PRIVATE, PRIVACY_PUBLIC) else None


def _filter_privacy(entries, privacy):
    """Narrow ``entries`` (already visibility-scoped) by the privacy filter, in the query."""
    if privacy == PRIVACY_PRIVATE:
        return entries.filter(is_private=True)
    if privacy == PRIVACY_PUBLIC:
        return entries.filter(is_private=False)
    return entries


def _privacy_filters(url_name, start, member, selected):
    """Links "Wszystkie", "Prywatne" and "Nieprywatne" of a calendar; each keeps the window
    and the selected child."""
    base = reverse(url_name)
    return [
        {
            'key': value or ALL_PRIVACY_KEY,
            'label': label,
            'url': f'{base}?{_list_query(start, member, value)}',
            'current': value == selected,
        }
        for value, label in PRIVACY_FILTERS
    ]


def _calendar_navigation(url_name, start, today, query_extra=''):
    """Links of the shared calendar nav; ``query_extra`` (``"a=b"``) is appended to each."""
    step = datetime.timedelta(days=CALENDAR_WINDOW_DAYS)
    suffix = f'&{query_extra}' if query_extra else ''
    base = reverse(url_name)

    def url(window_start):
        return f'{base}?{_calendar_query(window_start)}{suffix}'

    return {
        'previous_url': url(start - step),
        'today_url': url(today),
        'next_url': url(start + step),
        'is_today': start == today,
    }


def _managed_entry_or_404(membership, pk):
    """Resolve an entry the parent may manage; missing, foreign and other members'
    private IDs are all 404."""
    try:
        return with_effective_date(parent_family_entries(membership)).get(pk=pk)
    except Entry.DoesNotExist:
        raise Http404 from None


FAMILY_GROUP_HEADING = 'Ogólne'


def _assignee_heading(member):
    if member is None:
        return FAMILY_GROUP_HEADING
    if not member.is_active:
        return f'{member.display_name}{INACTIVE_MEMBER_SUFFIX}'
    return member.display_name


def _group_visible(group_key, member_key):
    """The filter's visibility rule (mirrored by ``js/member-filter.js``): every group without a
    selected child, otherwise only the child's own group and the unassigned "Ogólne" group."""
    return member_key is None or group_key in (member_key, GROUP_FAMILY)


def _index_days(entries, start, today, member_key=None):
    """Build all fourteen chronological calendar days, including empty dates.

    Shared by the parent and child calendars; the child's days hold one group each. Every row is
    kept: with ``member_key`` the other groups are only marked ``hidden``, and a day without a
    visible group is ``is_empty``."""
    rows_by_date = {}
    for entry in entries:
        rows_by_date.setdefault(entry.effective_date, []).append(entry)
    days = []
    for offset in range(CALENDAR_WINDOW_DAYS):
        day = start + datetime.timedelta(days=offset)
        groups = [
            {
                'key': group.key,
                'heading': _assignee_heading(group.member),
                'entries': group.entries,
                'hidden': not _group_visible(group.key, member_key),
            }
            for group in split_by_assignee(rows_by_date.get(day, []))
        ]
        days.append(
            {
                'key': day.isoformat(),
                'heading': parent_day_heading(day, today),
                'is_weekend': is_weekend(day),
                'groups': groups,
                'is_empty': all(group['hidden'] for group in groups),
            }
        )
    return days


def _index_context(entries, today, start=None, url_name='entries:index', member=None,
                   children=(), privacy=None):
    """Calendar context for the window starting at ``start`` (today by default);
    ``url_name`` is the calendar the navigation links point to. ``member`` (a validated child)
    and ``children`` (the filter's choices) are the parent calendar's filter; ``privacy`` (a
    validated ``_privacy_filter`` value, already applied to ``entries``) is either calendar's
    privacy filter. Both filters are carried by every navigation, filter and entry link."""
    start = start or today
    return {
        'days': _index_days(entries, start, today, _member_key(member)),
        'detail_query': _list_query(start, member, privacy),
        'filters': _member_filters(children, member, start, privacy),
        'privacy_filters': _privacy_filters(url_name, start, member, privacy),
        **_calendar_navigation(url_name, start, today, _filter_query(member, privacy)),
    }


def _calendar_rows(entries, start, end):
    """``entries`` with an effective date inside ``start``..``end``, in calendar order."""
    return list(
        with_effective_date(entries).filter(effective_date__range=(start, end)).order_by(
            'effective_date', F('time').asc(nulls_last=True), 'pk'
        )
    )


def _detail_list_start(request, entry, today):
    """Window "Wróć do listy" returns to: a valid ``?start``, else the one containing the entry.

    A missing and an invalid ``?start`` behave alike: neither may strand the back link in
    today's window when the entry lives in another fortnight."""
    requested_start = request.GET.get('start')
    if requested_start:
        list_start, _ = _calendar_window(requested_start, today)
        if list_start.isoformat() == requested_start:
            return list_start
    if entry.effective_date:
        requested_start = _window_containing(entry.effective_date, today).isoformat()
    else:
        requested_start = None
    list_start, _ = _calendar_window(requested_start, today)
    return list_start


def _detail_context(entry, list_start, delete_open=False, member=None, privacy=None,
                    can_change_privacy=False):
    """Parent detail context; ``can_change_privacy`` (the viewer created the entry) shows the
    privacy control."""
    return {
        'entry': entry,
        'list_start': list_start,
        'list_query': _list_query(list_start, member, privacy),
        'list_member': member,
        'list_privacy': privacy,
        'delete_open': delete_open,
        'can_change_privacy': can_change_privacy,
    }


def _is_creator(membership, entry):
    return entry.created_by_id is not None and entry.created_by_id == membership.pk


def _posted_start(data, today):
    """The posted ``start`` when it is a valid canonical window start, else ``None``."""
    value = data.get('start')
    if not value:
        return None
    start, _ = _calendar_window(value, today)
    return start if start.isoformat() == value else None


def _change_privacy(request, membership, pk):
    """Apply the creator's posted privacy choice to entry ``pk``; non-creators get a 404.

    Only ``is_private`` changes (``set_entry_privacy``). An invalid posted value changes
    nothing."""
    form = EntryPrivacyForm(request.POST)
    if not form.is_valid():
        return
    is_private = form.cleaned_data['is_private']
    try:
        set_entry_privacy(membership, pk, is_private=is_private)
    except Entry.DoesNotExist:
        raise Http404 from None
    messages.success(request, ENTRY_PRIVATE_MESSAGE if is_private else ENTRY_PUBLIC_MESSAGE)


def _detail_redirect(url_name, pk, start, member=None, privacy=None):
    """Back to the detail page, keeping the validated calendar state it was opened from."""
    url = reverse(url_name, args=[pk])
    query = _list_query(start, member, privacy) if start else _filter_query(member, privacy)
    return redirect(f'{url}?{query}' if query else url)


def _form_context(form, *, entry=None):
    describe_fields(form)
    return {'form': form, 'entry': entry}


@require_http_methods(['GET'])
@login_required
def index(request):
    membership = _require_parent(request)
    today = timezone.localdate()
    start, end = _calendar_window(request.GET.get('start'), today)
    children, member = _member_filter(membership, request.GET.get('member'))
    privacy = _privacy_filter(request.GET.get('privacy'))
    # Every row of the window is rendered; the child filter only hides groups (instant
    # switching). The privacy filter narrows the query itself, before date grouping.
    entries = parent_family_entries(membership).exclude(
        school_item=SchoolItemKind.LUCKY_NUMBER.value
    )
    rows = _calendar_rows(_filter_privacy(entries, privacy), start, end)
    return render(
        request,
        'entries/manage_index.html',
        _index_context(rows, today, start, member=member, children=children, privacy=privacy),
    )


@require_http_methods(['GET'])
@login_required
def detail(request, pk):
    membership = _require_parent(request)
    entry = _managed_entry_or_404(membership, pk)
    list_start = _detail_list_start(request, entry, timezone.localdate())
    _, member = _member_filter(membership, request.GET.get('member'))
    privacy = _privacy_filter(request.GET.get('privacy'))
    return render(
        request,
        'entries/manage_detail.html',
        _detail_context(
            entry, list_start, member=member, privacy=privacy,
            can_change_privacy=_is_creator(membership, entry),
        ),
    )


@require_POST
@login_required
def privacy(request, pk):
    """The creator's privacy change for an entry the parent created; only ``is_private``."""
    membership = _require_parent(request)
    _change_privacy(request, membership, pk)
    _, member = _member_filter(membership, request.POST.get('member'))
    return _detail_redirect(
        'entries:detail', pk, _posted_start(request.POST, timezone.localdate()),
        member, _privacy_filter(request.POST.get('privacy')),
    )


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
    membership = _require_parent(request)
    try:
        delete_family_entry(membership, pk)
    except Entry.DoesNotExist:
        raise Http404 from None
    messages.success(request, ENTRY_DELETED_MESSAGE)
    start, _ = _calendar_window(request.POST.get('start'), timezone.localdate())
    _, member = _member_filter(membership, request.POST.get('member'))
    return redirect(_index_url(start, member, _privacy_filter(request.POST.get('privacy'))))


# Fictional management kitchen-sink data (DEBUG gallery): unsaved rows only.
STATES_ENTRY_PK = 900001


def _synthetic_entry(offset, **fields):
    """An unsaved entry with explicit provenance; the pk only feeds URL reversing."""
    created_at = timezone.make_aware(datetime.datetime(2026, 9, 21, 18, 40))
    values = dict(
        pk=STATES_ENTRY_PK + offset,
        entry_type=EntryType.TODO.value,
        date=STATES_DATE,
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


def _synthetic_list(entries, start=STATES_DATE, member=None, children=(), privacy=None):
    return _index_context(
        entries, STATES_DATE, start, member=member, children=children, privacy=privacy
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
    library_task = _synthetic_entry(4, content='Oddać książkę do biblioteki',
                                    date=STATES_DATE + datetime.timedelta(days=3))
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
    gift = _synthetic_entry(
        9,
        content='Kupić prezent urodzinowy dla Kasi',
        date=STATES_DATE + datetime.timedelta(days=1),
        is_private=True,
    )
    own_public = _synthetic_entry(
        10,
        entry_type=EntryType.NOTE.value,
        content='Zapisać Tymka na basen',
        member='Tymek',
    )
    earlier_start = STATES_DATE - datetime.timedelta(days=CALENDAR_WINDOW_DAYS)
    past_entry = _synthetic_entry(
        5,
        content='Zapłacić za obiady',
        date=earlier_start,
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

    create_form = EntryCreateForm(membership, today=STATES_DATE)
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
            'name': 'list_today',
            'label': 'Lista: bieżące dwa tygodnie',
            'list': _synthetic_list(
                [test_entry, parent_note, family_meeting, long_note, trip, library_task],
            ),
        },
        {
            'name': 'list_filtered',
            'label': 'Lista: filtr „Kasia”',
            'list': _synthetic_list(
                [test_entry, parent_note, family_meeting, long_note, trip, library_task],
                member=_states_member('Kasia'),
                children=[_states_member('Kasia'), _states_member('Tymek')],
            ),
        },
        {
            'name': 'list_private',
            'label': 'Lista: filtr „Prywatne”',
            'list': _synthetic_list([gift], privacy=PRIVACY_PRIVATE),
        },
        {
            'name': 'list_not_private',
            'label': 'Lista: filtr „Nieprywatne” i „Kasia”',
            'list': _synthetic_list(
                [test_entry, parent_note, family_meeting, long_note, trip, library_task],
                member=_states_member('Kasia'),
                children=[_states_member('Kasia'), _states_member('Tymek')],
                privacy=PRIVACY_PUBLIC,
            ),
        },
        {
            'name': 'list_earlier',
            'label': 'Lista: wcześniejsze dwa tygodnie',
            'list': _synthetic_list([past_entry], earlier_start),
        },
        {
            'name': 'list_empty',
            'label': 'Lista: pusta',
            'list': _synthetic_list([]),
        },
        {
            'name': 'detail_manual',
            'label': 'Szczegóły: wpis ręczny',
            'detail': _detail_context(test_entry, STATES_DATE),
        },
        {
            'name': 'detail_eduvulcan',
            'label': 'Szczegóły: wpis z EduVulcan',
            'detail': _detail_context(eduvulcan_entry, STATES_DATE),
        },
        {
            'name': 'detail_private',
            'label': 'Szczegóły: własny wpis prywatny',
            'detail': _detail_context(
                gift, STATES_DATE, privacy=PRIVACY_PRIVATE, can_change_privacy=True
            ),
        },
        {
            'name': 'detail_own_public',
            'label': 'Szczegóły: własny wpis nieprywatny',
            'detail': _detail_context(own_public, STATES_DATE, can_change_privacy=True),
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
            'detail': _detail_context(past_entry, earlier_start, delete_open=True),
        },
    ]


# --- Child assigned entry view (S-03) ---


def _child_calendar_context(entries, today, start, privacy=None):
    return _index_context(entries, today, start, url_name='entries:child_list', privacy=privacy)


def _child_detail_context(entry, list_start, privacy=None, can_change_privacy=False):
    """Child detail context; ``can_change_privacy`` (the child created the entry) shows the
    privacy control, the child's only post-creation action."""
    return {
        'entry': entry,
        'list_start': list_start,
        'list_query': _list_query(list_start, privacy=privacy),
        'list_privacy': privacy,
        'can_change_privacy': can_change_privacy,
    }


@require_GET
@login_required
def child_list(request):
    """The signed-in child's own entries, lucky numbers included, in a 14-day window."""
    entries = child_entries(resolve_family_context(request))
    today = timezone.localdate()
    start, end = _calendar_window(request.GET.get('start'), today)
    privacy = _privacy_filter(request.GET.get('privacy'))
    rows = _calendar_rows(_filter_privacy(entries, privacy), start, end)
    return render(
        request,
        'entries/child_list.html',
        _child_calendar_context(rows, today, start, privacy),
    )


@require_GET
@login_required
def child_detail(request, pk):
    """One entry the signed-in child may read; any other ID (including someone else's
    private entry) is a plain 404."""
    membership = resolve_family_context(request)
    entries = child_entries(membership)
    entry = get_object_or_404(with_effective_date(entries), pk=pk)
    list_start = _detail_list_start(request, entry, timezone.localdate())
    return render(
        request,
        'entries/child_detail.html',
        _child_detail_context(
            entry, list_start, _privacy_filter(request.GET.get('privacy')),
            can_change_privacy=_is_creator(membership, entry),
        ),
    )


@require_POST
@login_required
def child_privacy(request, pk):
    """The child's privacy change for an entry the child created; no other field changes."""
    membership = require_child_membership(resolve_family_context(request))
    _change_privacy(request, membership, pk)
    return _detail_redirect(
        'entries:child_detail', pk, _posted_start(request.POST, timezone.localdate()),
        privacy=_privacy_filter(request.POST.get('privacy')),
    )


def _child_states_entry(pk, content, entry_type, *, date=None, time=None, school_item='',
                        school_subject='', source=Entry.Source.MANUAL, effective_date=None,
                        is_private=False):
    """Unsaved fictional entry for the child gallery; never written."""
    date = date or STATES_DATE
    entry = Entry(
        pk=pk,
        entry_type=entry_type.value,
        content=content,
        date=date,
        time=time,
        school_item=school_item,
        school_subject=school_subject,
        source=source,
        is_private=is_private,
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
    membership = require_family_context(request)

    day = datetime.timedelta(days=1)
    earlier_start = STATES_DATE - CALENDAR_WINDOW_DAYS * day
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
    long_note = _child_states_entry(
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
    match = _child_states_entry(
        9008, 'Mecz szkolnej drużyny', EntryType.CALENDAR_EVENT,
        date=STATES_DATE + 12 * day, time=datetime.time(10, 0),
    )
    homework = _child_states_entry(
        9009, 'Zadanie domowe z angielskiego', EntryType.CALENDAR_EVENT, date=STATES_DATE - day,
    )
    year_start = _child_states_entry(
        9010, 'Apel szkolny', EntryType.CALENDAR_EVENT,
        date=earlier_start, time=datetime.time(9, 0),
    )
    lucky = _child_states_entry(
        9011, 'Szczęśliwy numerek: 7', EntryType.NOTE, date=STATES_DATE + day,
        school_item=SchoolItemKind.LUCKY_NUMBER.value, source=Entry.Source.EDUVULCAN,
    )
    diary = _child_states_entry(
        9012, 'Pomysł na prezent dla mamy', EntryType.NOTE, date=STATES_DATE + 2 * day,
        is_private=True,
    )

    def list_state(name, label, entries, start=STATES_DATE, privacy=None):
        return {
            'name': name,
            'label': label,
            'list': _child_calendar_context(entries, STATES_DATE, start, privacy),
        }

    sections = [
        list_state('list_today', 'Bieżące dwa tygodnie', [
            test, long_note, grade, todo, lucky, reading, match,
        ]),
        list_state('list_earlier', 'Wcześniejsze dwa tygodnie', [
            year_start, returned, quiz, homework,
        ], earlier_start),
        list_state('list_empty', 'Dwa tygodnie bez wpisów', []),
        list_state('list_private', 'Filtr „Prywatne”', [diary], privacy=PRIVACY_PRIVATE),
        list_state('list_not_private', 'Filtr „Nieprywatne”', [
            test, long_note, grade, todo, lucky, reading, match,
        ], privacy=PRIVACY_PUBLIC),
        {'name': 'detail_manual', 'label': 'Szczegóły wpisu ręcznego',
         **_child_detail_context(long_note, STATES_DATE)},
        {'name': 'detail_eduvulcan', 'label': 'Szczegóły wpisu z EduVulcan',
         **_child_detail_context(quiz, earlier_start)},
        {'name': 'detail_private', 'label': 'Szczegóły własnego wpisu prywatnego',
         **_child_detail_context(diary, STATES_DATE, PRIVACY_PRIVATE, can_change_privacy=True)},
        {'name': 'detail_own_public', 'label': 'Szczegóły własnego wpisu nieprywatnego',
         **_child_detail_context(todo, STATES_DATE, can_change_privacy=True)},
        {'name': 'error_forbidden', 'label': 'Błąd: brak dostępu',
         'error': {'heading': 'Brak dostępu',
                   'message': 'Ta strona nie jest dostępna dla Twojego konta.'}},
        *_child_capture_state_sections(membership),
    ]
    return render(
        request,
        'entries/child_states.html',
        {'sections': sections, 'capture_routes': CHILD_CAPTURE.routes, **_progress_thresholds()},
    )


# Synthetic pk of the gallery's fictional child; only feeds unsaved objects.
STATES_CHILD_PK = 900101


def _child_capture_state_sections(membership):
    """Child capture states for the DEBUG gallery: unsaved synthetic data, no family rows.

    The forms are built for a fictional, unsaved child of the context family, so
    they show exactly the child's controls (no assignee choice, the privacy
    choice) whatever the viewer's role.
    """
    child = FamilyMember(
        pk=STATES_CHILD_PK,
        family=membership.family,
        role=FamilyMember.Role.CHILD,
        display_name=STATES_MEMBER_CHOICES[1][1],
        is_active=True,
    )

    def review(result, text=''):
        outcome = ParentClassification(result=result, member=child)
        form, _ = review_form_from_classification(child, outcome, text, today=STATES_DATE)
        return form

    homework = ClassificationProposal(
        entry_type=EntryType.CALENDAR_EVENT,
        content='Zadanie domowe z matematyki',
        date=STATES_DATE + datetime.timedelta(days=2),
        school_item=SchoolItemKind.HOMEWORK,
        school_subject='matematyka',
        member_name=child.display_name,
    )
    missing_date = ClassificationFollowUp(
        missing_fields=(MissingField.DATE,),
        entry_type=EntryType.CALENDAR_EVENT,
        content='Trening piłki nożnej',
        member_name=child.display_name,
    )
    question = follow_up_form_from_classification(
        child, ParentClassification(result=missing_date, member=child), 'Mam trening piłki nożnej'
    )
    invalid_form = EntryReviewForm(
        child,
        {
            'entry_type': EntryType.TODO.value,
            'content': '',
            'date': '',
            'time': '',
            'school_item': '',
            'school_subject': '',
            'submission_key': str(uuid.uuid4()),
        },
    )
    invalid_form.is_valid()
    failed_correction = review(homework)
    failed_correction.initial['correction'] = 'bla bla'
    batch = batch_review_form_from_classification(
        child,
        ParentBatchClassification(items=tuple(
            ParentClassification(
                result=ClassificationProposal(
                    entry_type=EntryType.TODO,
                    content='Spakować strój na basen',
                    date=STATES_DATE + datetime.timedelta(days=offset),
                    member_name=child.display_name,
                ),
                member=child,
            )
            for offset in (1, 3)
        )),
        today=STATES_DATE,
    )

    def saved(is_private):
        return Entry(
            entry_type=EntryType.NOTE.value,
            content='Pożyczyłam książkę od Oli',
            date=STATES_DATE,
            assigned_member=child,
            is_private=is_private,
        )

    sections = [
        {'name': 'capture_empty', 'label': 'Dodawanie: pusty formularz',
         'capture_form': CaptureForm()},
        {'name': 'capture_proposal', 'label': 'Dodawanie: propozycja do sprawdzenia',
         'review_form': review(homework)},
        {'name': 'capture_question', 'label': 'Dodawanie: pytanie o brakującą datę',
         'follow_up_form': question},
        {'name': 'capture_follow_up', 'label': 'Dodawanie: brakująca data w propozycji',
         'review_form': review(missing_date)},
        {'name': 'capture_unavailable', 'label': 'Dodawanie: rozpoznanie niedostępne',
         'notice': UNAVAILABLE_NOTICE,
         'review_form': review(
             ClassificationUnavailable(reason=UnavailableReason.TIMEOUT),
             text='Kupić zeszyt w kratkę',
         )},
        {'name': 'capture_correction_failed', 'label': 'Dodawanie: poprawka niezastosowana',
         'notice': CORRECTION_FAILED_NOTICE, 'review_form': failed_correction},
        {'name': 'capture_invalid', 'label': 'Dodawanie: błędy w formularzu',
         'review_form': invalid_form},
        {'name': 'capture_batch', 'label': 'Dodawanie: kilka wpisów', 'batch_form': batch},
        {'name': 'capture_saved', 'label': 'Dodawanie: zapisano wpis',
         'saved_entries': [saved(False)], 'capture_form': CaptureForm()},
        {'name': 'capture_saved_private', 'label': 'Dodawanie: zapisano wpis prywatny',
         'saved_entries': [saved(True)], 'capture_form': CaptureForm()},
    ]
    for section in sections:
        _describe_capture_forms(section)
    return sections
