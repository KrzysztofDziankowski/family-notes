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


# --- Child assigned entry view (S-03) ---
# Imports stay inside this block so the S-02 merge does not touch the header.
from django.shortcuts import get_object_or_404  # noqa: E402
from django.views.decorators.http import require_GET  # noqa: E402

from .listing import (  # noqa: E402
    PAST,
    SECTION_UNDATED,
    UPCOMING,
    normalize_list_mode,
    partition_entries,
    with_effective_date,
)
from .services import child_entries  # noqa: E402

CHILD_EMPTY_MESSAGES = {
    UPCOMING: 'Nie masz żadnych nadchodzących wpisów.',
    PAST: 'Nie masz żadnych minionych wpisów.',
}


def _child_list_context(mode, sections):
    """Template context for the child list body; ``sections`` are evaluated here."""
    sections = [
        {
            'key': section.key,
            'undated': section.key == SECTION_UNDATED,
            'entries': list(section.entries),
        }
        for section in sections
    ]
    return {
        'mode': mode,
        'detail_query': 'view=past' if mode == PAST else '',
        'sections': [section for section in sections if section['entries']],
        'empty_message': CHILD_EMPTY_MESSAGES[mode],
    }


@require_GET
@login_required
def child_list(request):
    """The signed-in child's own entries, upcoming (default) or past."""
    entries = child_entries(request.user)
    mode = normalize_list_mode(request.GET.get('view'))
    sections = partition_entries(entries, mode, timezone.localdate())
    return render(request, 'entries/child_list.html', _child_list_context(mode, sections))


@require_GET
@login_required
def child_detail(request, pk):
    """One entry assigned to the signed-in child; any other ID is a plain 404."""
    entry = get_object_or_404(with_effective_date(child_entries(request.user)), pk=pk)
    return render(
        request,
        'entries/child_detail.html',
        {'entry': entry, 'back_mode': normalize_list_mode(request.GET.get('view'))},
    )
