from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from entries.forms import describe_fields

from .access import get_active_membership, is_parent
from .forms import MemberRenameForm
from .membership import (
    ACTIVE_ELSEWHERE_ERROR,
    DUPLICATE_NAME_ERROR,
    LAST_PARENT_ERROR,
    can_deactivate,
    deactivate_member,
    family_members as list_family_members,
    get_family_member,
    reactivate_member,
    rename_member,
)
from .models import FamilyMember

MEMBER_RENAMED_MESSAGE = 'Zapisano nowe imię: {name}.'
MEMBER_DEACTIVATED_MESSAGE = 'Wyłączono dostęp: {name}.'
MEMBER_REACTIVATED_MESSAGE = 'Przywrócono dostęp: {name}.'


@login_required
def account_status(request):
    return render(
        request,
        'family_access/account_status.html',
        {'membership': get_active_membership(request.user)},
    )


# --- Family member management (S-14) -----------------------------------------


def _require_parent(request):
    actor = get_active_membership(request.user)
    if not is_parent(actor):
        raise PermissionDenied('An active parent membership is required.')
    return actor


def _member_or_404(actor, pk):
    """A member of the actor's family; missing and foreign IDs are both 404."""
    try:
        return get_family_member(actor, pk)
    except FamilyMember.DoesNotExist:
        raise Http404 from None


def _row(actor, member, *, deactivatable, confirm_open=False):
    return {
        'member': member,
        'is_self': member.pk == actor.pk,
        'can_deactivate': deactivatable,
        'confirm_open': confirm_open,
    }


def _members_context(actor, error=''):
    rows = [
        _row(actor, member, deactivatable=can_deactivate(actor, member))
        for member in list_family_members(actor)
    ]
    return {'rows': rows, 'error': error}


def _render_members(request, actor, error=''):
    return render(request, 'family_access/members.html', _members_context(actor, error))


def _edit_context(form, member):
    describe_fields(form)
    field = form['display_name']
    if member.role == FamilyMember.Role.CHILD:
        attrs = field.field.widget.attrs
        note_id = f'{field.auto_id}-note'
        attrs['aria-describedby'] = ' '.join(
            filter(None, [attrs.get('aria-describedby', ''), note_id])
        )
    return {'form': form, 'member': member}


@require_GET
@login_required
def family_members(request):
    actor = _require_parent(request)
    return _render_members(request, actor)


@require_http_methods(['GET', 'POST'])
@login_required
def family_member_edit(request, pk):
    actor = _require_parent(request)
    member = _member_or_404(actor, pk)
    if request.method == 'GET':
        form = MemberRenameForm(initial={'display_name': member.display_name})
    else:
        form = MemberRenameForm(request.POST)
        if form.is_valid():
            try:
                renamed = rename_member(actor, member.pk, form.cleaned_data['display_name'])
            except FamilyMember.DoesNotExist:
                raise Http404 from None
            except ValidationError as error:
                form.add_error('display_name', error)
            else:
                messages.success(
                    request, MEMBER_RENAMED_MESSAGE.format(name=renamed.display_name)
                )
                return redirect('family_members')
    return render(request, 'family_access/member_edit.html', _edit_context(form, member))


def _mutate(request, pk, service, success_message):
    actor = _require_parent(request)
    try:
        member = service(actor, pk)
    except FamilyMember.DoesNotExist:
        raise Http404 from None
    except ValidationError as error:
        return _render_members(request, actor, error=' '.join(error.messages))
    messages.success(request, success_message.format(name=member.display_name))
    return redirect('family_members')


@require_POST
@login_required
def family_member_deactivate(request, pk):
    return _mutate(request, pk, deactivate_member, MEMBER_DEACTIVATED_MESSAGE)


@require_POST
@login_required
def family_member_reactivate(request, pk):
    return _mutate(request, pk, reactivate_member, MEMBER_REACTIVATED_MESSAGE)


# Fictional member-management kitchen-sink data (DEBUG gallery): unsaved rows only.
STATES_MEMBER_PK = 910001


def _states_member(offset, display_name, role, *, is_active=True):
    return FamilyMember(
        pk=STATES_MEMBER_PK + offset, display_name=display_name, role=role, is_active=is_active
    )


def _states_rows(actor, members, *, open_pk=None, last_parent_pk=None):
    rows = []
    for member in members:
        deactivatable = (
            member.is_active and member.pk != actor.pk and member.pk != last_parent_pk
        )
        rows.append(_row(actor, member, deactivatable=deactivatable,
                         confirm_open=member.pk == open_pk))
    return rows


def _states_form(name, member, data=None, *, error=''):
    form = MemberRenameForm(
        data,
        initial={'display_name': member.display_name},
        auto_id=f'id_{name}_%s',
    )
    if data is not None and form.is_valid() and error:
        form.add_error('display_name', error)
    return _edit_context(form, member)


def family_member_states(request):
    """DEBUG-only gallery of every member-management state from unsaved synthetic data."""
    if not settings.DEBUG:
        raise Http404
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    _require_parent(request)

    parent = _states_member(1, 'Ewa', FamilyMember.Role.PARENT)
    other_parent = _states_member(2, 'Marek', FamilyMember.Role.PARENT)
    child = _states_member(3, 'Kasia', FamilyMember.Role.CHILD)
    son = _states_member(4, 'Tymek', FamilyMember.Role.CHILD)
    former_parent = _states_member(5, 'Jola', FamilyMember.Role.PARENT, is_active=False)
    former_child = _states_member(6, 'Ola', FamilyMember.Role.CHILD, is_active=False)
    everyone = [parent, other_parent, child, son, former_parent, former_child]

    sections = [
        {'name': 'list', 'label': 'Lista członków z nieaktywnymi osobami',
         'list': {'rows': _states_rows(parent, everyone)}},
        {'name': 'deactivate_open', 'label': 'Otwarte potwierdzenie wyłączenia dostępu',
         'list': {'rows': _states_rows(parent, everyone, open_pk=other_parent.pk)}},
        {'name': 'reactivate_parent_open',
         'label': 'Otwarte potwierdzenie przywrócenia rodzica',
         'list': {'rows': _states_rows(parent, everyone, open_pk=former_parent.pk)}},
        {'name': 'last_parent', 'label': 'Ostatni aktywny rodzic',
         'list': {'rows': _states_rows(
             other_parent, [parent, other_parent, child], last_parent_pk=parent.pk)}},
        {'name': 'guard_error', 'label': 'Błąd: ostatni rodzic',
         'list': {'rows': _states_rows(parent, everyone), 'error': LAST_PARENT_ERROR}},
        {'name': 'reactivate_error', 'label': 'Błąd: konto w innej rodzinie',
         'list': {'rows': _states_rows(parent, everyone), 'error': ACTIVE_ELSEWHERE_ERROR}},
        {'name': 'edit', 'label': 'Zmiana imienia dziecka', 'form': _states_form('edit', child)},
        {'name': 'edit_parent', 'label': 'Zmiana imienia rodzica',
         'form': _states_form('edit_parent', other_parent)},
        {'name': 'edit_invalid', 'label': 'Błąd: puste imię',
         'form': _states_form('edit_invalid', child, {'display_name': '  '})},
        {'name': 'edit_duplicate', 'label': 'Błąd: imię już zajęte',
         'form': _states_form('edit_duplicate', son, {'display_name': 'kasia'},
                              error=DUPLICATE_NAME_ERROR)},
    ]
    return render(request, 'family_access/member_states.html', {'sections': sections})
