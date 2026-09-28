import datetime
import uuid

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_POST

from family_access.access import get_active_membership, is_parent, scope_queryset_to_family
from family_access.models import FamilyMember

from .classification.service import classify_for_parent
from .classification.service import ParentClassification
from .classification.types import (
    EntryType,
    MissingField,
    SchoolItemKind,
    ClassificationFollowUp,
    ClassificationProposal,
    ClassificationUnavailable,
    UnavailableReason,
)
from .forms import CaptureForm, EntryReviewForm, review_form_from_classification
from .models import Entry
from .services import save_confirmed_entry

UNAVAILABLE_NOTICE = (
    'Nie udało się teraz rozpoznać wpisu. Możesz zapisać go jako notatkę lub poprawić.'
)
INPUT_TOO_LONG_ERROR = 'Tekst jest za długi. Skróć go i spróbuj ponownie.'
SAVE_FAILED_ERROR = 'Nie udało się zapisać wpisu. Sprawdź dane i spróbuj ponownie.'


def _require_parent(request):
    membership = get_active_membership(request.user)
    if not is_parent(membership):
        raise PermissionDenied('An active parent membership is required.')
    return membership


def _render(request, state, **context):
    return render(request, 'entries/capture.html', {'state': state, **context})


@sensitive_post_parameters('text', 'content')
@require_http_methods(['GET', 'POST'])
@login_required
def capture(request):
    membership = _require_parent(request)

    if request.method == 'GET':
        saved_entry = _saved_entry(membership, request.GET.get('saved', ''))
        return _render(
            request,
            'saved' if saved_entry else 'empty',
            capture_form=CaptureForm(),
            saved_entry=saved_entry,
        )

    capture_form = CaptureForm(request.POST)
    if not capture_form.is_valid():
        return _render(request, 'empty', capture_form=capture_form)

    text = capture_form.cleaned_data['text']
    outcome = classify_for_parent(request.user, text, reference_date=timezone.localdate())
    result = outcome.result

    if isinstance(result, ClassificationUnavailable) and (
        result.reason == UnavailableReason.INPUT_TOO_LONG
    ):
        capture_form.add_error('text', INPUT_TOO_LONG_ERROR)
        return _render(request, 'empty', capture_form=capture_form)

    review_form, _ = review_form_from_classification(membership, outcome, text)
    if isinstance(result, ClassificationProposal):
        state = 'proposal'
    elif isinstance(result, ClassificationFollowUp):
        state = 'follow_up'
    else:
        state = 'unavailable'
    return _render(
        request,
        state,
        review_form=review_form,
        notice=UNAVAILABLE_NOTICE if state == 'unavailable' else '',
    )


@sensitive_post_parameters('text', 'content')
@require_POST
@login_required
def confirm(request):
    membership = _require_parent(request)
    review_form = EntryReviewForm(membership, request.POST)
    if not review_form.is_valid():
        return _render(request, 'invalid', review_form=review_form)

    data = review_form.cleaned_data
    try:
        entry, _ = save_confirmed_entry(
            request.user,
            entry_type=data['entry_type'],
            content=data['content'],
            date=data['date'],
            time=data['time'],
            assigned_member=data['assigned_member'],
            school_item=data['school_item'],
            submission_key=data['submission_key'],
        )
    except ValidationError:
        retry_data = request.POST.copy()
        retry_data['submission_key'] = str(uuid.uuid4())
        retry_form = EntryReviewForm(membership, retry_data)
        retry_form.is_valid()
        retry_form.add_error(None, SAVE_FAILED_ERROR)
        return _render(request, 'invalid', review_form=retry_form)

    return redirect(f"{reverse('entries:capture')}?saved={entry.pk}")


def _saved_entry(membership, saved):
    if not saved.isdigit():
        return None
    return (
        scope_queryset_to_family(Entry.objects.select_related('assigned_member'), membership)
        .filter(pk=int(saved))
        .first()
    )


# Fictional kitchen-sink data: never real family members or saved rows.
STATES_MEMBER_CHOICES = [('', 'Cała rodzina'), ('s1', 'Kasia'), ('s2', 'Tymek')]
STATES_DATE = datetime.date(2026, 10, 5)


def states(request):
    """DEBUG-only page rendering every capture state from unsaved synthetic data."""
    if not settings.DEBUG:
        raise Http404
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    membership = _require_parent(request)

    def synthetic_review(result, member_value='', text=''):
        form, _ = review_form_from_classification(
            membership, ParentClassification(result=result), text
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

    sections = [
        {'name': 'empty', 'label': 'Pusty formularz', 'capture_form': CaptureForm()},
        {
            'name': 'proposal',
            'label': 'Propozycja do sprawdzenia',
            'review_form': synthetic_review(proposal, member_value='s1'),
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
                ),
                member_value='s2',
            ),
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
        {'name': 'invalid', 'label': 'Błędy w formularzu', 'review_form': invalid_form},
        {
            'name': 'saved',
            'label': 'Zapisano',
            'saved_entry': saved_entry,
            'capture_form': CaptureForm(),
        },
    ]
    return render(request, 'entries/states.html', {'sections': sections})


def _use_synthetic_members(form):
    form.fields['assigned_member'].choices = STATES_MEMBER_CHOICES


# --- Parent family entry management (S-02) ---
# Imports live with the block so the S-02 and S-03 view additions merge independently.

from django.contrib import messages  # noqa: E402

from .forms import EntryCreateForm, EntryEditForm  # noqa: E402
from .listing import (  # noqa: E402
    LIST_MODES,
    PAST,
    SECTION_DATED,
    SECTION_PAST,
    SECTION_UNDATED,
    UPCOMING,
    normalize_list_mode,
    partition_entries,
    with_effective_date,
)
from .services import (  # noqa: E402
    create_family_entry,
    delete_family_entry,
    parent_family_entries,
    update_family_entry,
)

LIST_MODE_LABELS = {UPCOMING: 'Nadchodzące', PAST: 'Minione'}
SECTION_LABELS = {
    SECTION_DATED: 'Z datą',
    SECTION_UNDATED: 'Bez daty',
    SECTION_PAST: 'Minione',
}
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


def _managed_entry_or_404(user, pk):
    """Resolve an entry in the parent's family; missing and foreign IDs are both 404."""
    try:
        return with_effective_date(parent_family_entries(user)).get(pk=pk)
    except Entry.DoesNotExist:
        raise Http404 from None


def _mark_invalid_fields(form):
    """Expose field errors to assistive technology."""
    for name in form.errors:
        if name in form.fields:
            attrs = form.fields[name].widget.attrs
            attrs['aria-invalid'] = 'true'
            attrs['aria-describedby'] = f'{form[name].auto_id}-error'


def _index_sections(sections):
    return [
        {'key': section.key, 'label': SECTION_LABELS[section.key], 'entries': list(section.entries)}
        for section in sections
    ]


def _index_context(mode, sections):
    sections = _index_sections(sections)
    return {
        'mode': mode,
        'modes': [(key, LIST_MODE_LABELS[key]) for key in LIST_MODES],
        'sections': sections,
        'is_empty': not any(section['entries'] for section in sections),
        'empty_message': EMPTY_LIST_MESSAGES[mode],
    }


def _detail_context(entry, list_mode, delete_open=False):
    return {'entry': entry, 'list_mode': list_mode, 'delete_open': delete_open}


def _form_context(form, *, entry=None):
    return {'form': form, 'entry': entry}


@require_http_methods(['GET'])
@login_required
def index(request):
    mode = normalize_list_mode(request.GET.get('view', ''))
    sections = partition_entries(parent_family_entries(request.user), mode, timezone.localdate())
    return render(request, 'entries/manage_index.html', _index_context(mode, sections))


@require_http_methods(['GET'])
@login_required
def detail(request, pk):
    entry = _managed_entry_or_404(request.user, pk)
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
                request.user,
                entry_type=data['entry_type'],
                content=data['content'],
                date=data['date'],
                time=data['time'],
                assigned_member=data['assigned_member'],
                school_item=data['school_item'],
                submission_key=data['submission_key'],
            )
        except ValidationError:
            retry_data = request.POST.copy()
            retry_data['submission_key'] = str(uuid.uuid4())
            form = EntryCreateForm(membership, retry_data)
            form.is_valid()
            form.add_error(None, SAVE_FAILED_ERROR)
        else:
            messages.success(request, ENTRY_CREATED_MESSAGE)
            return redirect('entries:detail', pk=entry.pk)
    _mark_invalid_fields(form)
    return render(request, 'entries/manage_form.html', _form_context(form))


@sensitive_post_parameters('content')
@require_http_methods(['GET', 'POST'])
@login_required
def edit(request, pk):
    membership = _require_parent(request)
    entry = _managed_entry_or_404(request.user, pk)
    if request.method == 'GET':
        form = EntryEditForm(membership, entry=entry)
        return render(request, 'entries/manage_form.html', _form_context(form, entry=entry))

    form = EntryEditForm(membership, request.POST, entry=entry)
    if form.is_valid():
        data = form.cleaned_data
        try:
            update_family_entry(
                request.user,
                entry.pk,
                entry_type=data['entry_type'],
                content=data['content'],
                date=data['date'],
                time=data['time'],
                assigned_member=data['assigned_member'],
                school_item=data['school_item'],
            )
        except Entry.DoesNotExist:
            raise Http404 from None
        except ValidationError:
            form.add_error(None, SAVE_FAILED_ERROR)
        else:
            messages.success(request, ENTRY_UPDATED_MESSAGE)
            return redirect('entries:detail', pk=entry.pk)
    _mark_invalid_fields(form)
    return render(request, 'entries/manage_form.html', _form_context(form, entry=entry))


@require_POST
@login_required
def delete(request, pk):
    try:
        delete_family_entry(request.user, pk)
    except Entry.DoesNotExist:
        raise Http404 from None
    messages.success(request, ENTRY_DELETED_MESSAGE)
    return redirect(_index_url(request.POST.get('view', '')))
