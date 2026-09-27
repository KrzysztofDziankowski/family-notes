import uuid

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_POST

from family_access.access import get_active_membership, is_parent, scope_queryset_to_family

from .classification.service import classify_for_parent
from .classification.types import (
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
