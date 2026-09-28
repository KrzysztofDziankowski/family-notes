import datetime
import uuid

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

from family_access.access import require_active_membership, scope_queryset_to_family
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
from .forms import (
    CaptureForm,
    EntryCreateForm,
    EntryEditForm,
    EntryReviewForm,
    review_form_from_classification,
)
from .listing import (
    LIST_MODES,
    PAST,
    SECTION_DATED,
    SECTION_PAST,
    SECTION_UNDATED,
    UPCOMING,
    EntrySection,
    normalize_list_mode,
    partition_entries,
    with_effective_date,
)
from .models import Entry
from .services import (
    child_entries,
    create_family_entry,
    delete_family_entry,
    parent_family_entries,
    require_parent_membership,
    save_confirmed_entry,
    update_family_entry,
)

UNAVAILABLE_NOTICE = (
    'Nie udało się teraz rozpoznać wpisu. Możesz zapisać go jako notatkę lub poprawić.'
)
INPUT_TOO_LONG_ERROR = 'Tekst jest za długi. Skróć go i spróbuj ponownie.'
SAVE_FAILED_ERROR = 'Nie udało się zapisać wpisu. Sprawdź dane i spróbuj ponownie.'


def _require_parent(request):
    return require_parent_membership(request.user)


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
    return render(
        request,
        'entries/states.html',
        {'sections': sections, 'manage_sections': _manage_state_sections(membership)},
    )


def _use_synthetic_members(form):
    form.fields['assigned_member'].choices = STATES_MEMBER_CHOICES


# --- Parent family entry management (S-02) ---

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
    if member:
        entry.assigned_member = FamilyMember(display_name=member)
    return entry


def _synthetic_list(mode, sections):
    return _index_context(
        mode,
        [EntrySection(key, entries) for key, entries in sections],
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
    )
    undated = _synthetic_entry(4, content='Oddać książkę do biblioteki')
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
    _mark_invalid_fields(invalid_form)

    edit_form = EntryEditForm(membership, entry=test_entry)
    _use_synthetic_members(edit_form)
    edit_form.initial['assigned_member'] = 's1'

    return [
        {
            'name': 'list_upcoming',
            'label': 'Lista: nadchodzące',
            'list': _synthetic_list(
                UPCOMING,
                [(SECTION_DATED, [test_entry, trip]), (SECTION_UNDATED, [undated, long_note])],
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


def _child_states_entry(pk, content, entry_type, *, date=None, time=None, school_item='',
                        source=Entry.Source.MANUAL, effective_date=None):
    """Unsaved fictional entry for the child gallery; never written."""
    entry = Entry(
        pk=pk,
        entry_type=entry_type.value,
        content=content,
        date=date,
        time=time,
        school_item=school_item,
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
    require_active_membership(request.user)

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
        school_item=SchoolItemKind.QUIZ.value, source=Entry.Source.EDUVULCAN,
    )
    returned = _child_states_entry(
        9006, 'Oddać książkę do biblioteki', EntryType.TODO, date=STATES_DATE - 5 * day,
    )

    def list_state(name, label, mode, sections):
        return {'name': name, 'label': label, 'list': _child_list_context(mode, sections)}

    sections = [
        list_state('upcoming', 'Nadchodzące', UPCOMING, [
            EntrySection(SECTION_DATED, [test, grade, todo]),
            EntrySection(SECTION_UNDATED, [undated]),
        ]),
        list_state('past', 'Minione', PAST, [EntrySection(SECTION_PAST, [quiz, returned])]),
        list_state('upcoming_empty', 'Brak nadchodzących', UPCOMING, [
            EntrySection(SECTION_DATED, []),
            EntrySection(SECTION_UNDATED, []),
        ]),
        list_state('past_empty', 'Brak minionych', PAST, [EntrySection(SECTION_PAST, [])]),
        {'name': 'detail_manual', 'label': 'Szczegóły wpisu ręcznego',
         'entry': undated, 'back_mode': UPCOMING},
        {'name': 'detail_eduvulcan', 'label': 'Szczegóły wpisu z EduVulcan',
         'entry': quiz, 'back_mode': PAST},
    ]
    return render(request, 'entries/child_states.html', {'sections': sections})
