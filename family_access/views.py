from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from entries.forms import describe_fields

from .access import is_parent
from .context import resolve_family_context
from .forms import MemberRenameForm, MemberRoleForm
from .membership import (
    ACTIVE_ELSEWHERE_ERROR,
    DUPLICATE_NAME_ERROR,
    LAST_PARENT_ERROR,
    can_change_role,
    can_deactivate,
    change_member_role,
    deactivate_member,
    family_members as list_family_members,
    get_family_member,
    reactivate_member,
    rename_member,
)
from .models import FamilyMember
from .notices import remember_membership

MEMBER_RENAMED_MESSAGE = 'Zapisano nowe imię: {name}.'
MEMBER_DEACTIVATED_MESSAGE = 'Wyłączono dostęp: {name}.'
MEMBER_REACTIVATED_MESSAGE = 'Przywrócono dostęp: {name}.'
MEMBER_PROMOTED_MESSAGE = 'Zmieniono rolę: {name} jest teraz rodzicem.'
MEMBER_DEMOTED_MESSAGE = (
    'Zmieniono rolę: {name} jest teraz dzieckiem. '
    'Tokeny automatyzacji tej osoby zostały unieważnione.'
)
ROLE_UNCHANGED_MESSAGE = 'Rola bez zmian: {name}.'
SELF_DEMOTED_MESSAGE = (
    'Twoja rola to teraz „Dziecko”. Nie możesz już zarządzać wpisami ani członkami rodziny.'
)


@login_required
def account_status(request):
    return render(
        request,
        'family_access/account_status.html',
        {'membership': resolve_family_context(request)},
    )


# --- Family member management (S-14) -----------------------------------------


def _require_parent(request):
    actor = resolve_family_context(request)
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


def _edit_context(form, member, role=None):
    describe_fields(form)
    field = form['display_name']
    if member.role == FamilyMember.Role.CHILD:
        attrs = field.field.widget.attrs
        note_id = f'{field.auto_id}-note'
        attrs['aria-describedby'] = ' '.join(
            filter(None, [attrs.get('aria-describedby', ''), note_id])
        )
    return {'form': form, 'member': member, 'role': role}


def _other_role(member):
    if member.role == FamilyMember.Role.PARENT:
        return FamilyMember.Role.CHILD
    return FamilyMember.Role.PARENT


def _role_context(member, *, is_self, can_change, form=None, error='', open_=False,
                  auto_id='id_%s'):
    """The role section of the edit page (S-15); an unbound form preselects the other role."""
    if form is None:
        form = MemberRoleForm(
            member=member, is_self=is_self, initial={'role': _other_role(member)},
            auto_id=auto_id,
        )
    describe_fields(form)
    return {
        'member': member,
        'form': form,
        'can_change': can_change,
        'open': open_ or bool(form.errors) or bool(error),
        'error': error,
    }


def _render_edit(request, actor, member, rename_form, *, role_form=None, role_error=''):
    role = _role_context(
        member,
        is_self=member.pk == actor.pk,
        can_change=can_change_role(actor, member),
        form=role_form,
        error=role_error,
    )
    return render(
        request, 'family_access/member_edit.html', _edit_context(rename_form, member, role)
    )


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
    return _render_edit(request, actor, member, form)


@require_POST
@login_required
def family_member_role(request, pk):
    """Change a member's role (S-15); guard errors re-render the edit page."""
    actor = _require_parent(request)
    member = _member_or_404(actor, pk)
    is_self = member.pk == actor.pk
    form = MemberRoleForm(request.POST, member=member, is_self=is_self)
    role_error = ''
    if form.is_valid():
        old_role = member.role
        try:
            changed = change_member_role(
                actor,
                member.pk,
                form.cleaned_data['role'],
                confirm_self=form.cleaned_data.get('confirm_self', False),
            )
        except FamilyMember.DoesNotExist:
            raise Http404 from None
        except ValidationError as error:
            role_error = ' '.join(error.messages)
            member.refresh_from_db()
        else:
            if changed.role == old_role:
                message = ROLE_UNCHANGED_MESSAGE
            elif changed.role == FamilyMember.Role.PARENT:
                message = MEMBER_PROMOTED_MESSAGE
            elif is_self:
                # The session saw the change itself: no "someone demoted you" notice.
                remember_membership(request, changed)
                messages.success(request, SELF_DEMOTED_MESSAGE)
                return redirect('home')
            else:
                message = MEMBER_DEMOTED_MESSAGE
            messages.success(request, message.format(name=changed.display_name))
            return redirect('family_members')
    rename_form = MemberRenameForm(initial={'display_name': member.display_name})
    return _render_edit(request, actor, member, rename_form, role_form=form,
                        role_error=role_error)


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


def _states_role(name, member, *, is_self=False, can_change=True, data=None, error='',
                 open_=True):
    form = None
    if data is not None:
        form = MemberRoleForm(data, member=member, is_self=is_self, auto_id=f'id_{name}_%s')
    return _role_context(member, is_self=is_self, can_change=can_change, form=form,
                         error=error, open_=open_, auto_id=f'id_{name}_%s')


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
        {'name': 'role_promote', 'label': 'Zmiana roli: dziecko zostaje rodzicem',
         'role': _states_role('role_promote', child)},
        {'name': 'role_demote', 'label': 'Zmiana roli: rodzic zostaje dzieckiem',
         'role': _states_role('role_demote', other_parent)},
        {'name': 'role_self_demote', 'label': 'Zmiana własnej roli z potwierdzeniem',
         'role': _states_role('role_self_demote', parent, is_self=True)},
        {'name': 'role_self_demote_invalid', 'label': 'Błąd: brak potwierdzenia własnej zmiany',
         'role': _states_role('role_self_demote_invalid', parent, is_self=True,
                              data={'role': FamilyMember.Role.CHILD})},
        {'name': 'role_last_parent', 'label': 'Ostatni aktywny rodzic: rola bez zmiany',
         'role': _states_role('role_last_parent', parent, is_self=True, can_change=False)},
        {'name': 'role_guard_error', 'label': 'Błąd: ostatni rodzic przy zmianie roli',
         'role': _states_role('role_guard_error', other_parent, error=LAST_PARENT_ERROR,
                              open_=False)},
        {'name': 'role_inactive', 'label': 'Osoba bez dostępu: najpierw przywróć dostęp',
         'role': _states_role('role_inactive', former_child)},
    ]
    return render(request, 'family_access/member_states.html', {'sections': sections})
