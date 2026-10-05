"""Request family context (S-16): the only way a web request learns its family.

A person may be an active member of several families. The session stores only
the id of the current family (``family_access.current_family_id``); every
request re-validates it against the user's active memberships, so a
deactivated membership, a deactivated family or a changed role takes effect
on the next request. The app never guesses: with several memberships and no
valid selection, product views raise ``FamilyContextRequired`` and
``FamilyContextMiddleware`` sends the user to the family chooser.

Product views call ``resolve_family_context`` or ``require_family_context``.
Templates, the chooser, the sign-in/out pages and error pages use only the
non-raising ``peek_family_context``. Token-authenticated automation requests
never use this module: their family comes from the token's membership.
"""

from django.contrib.auth.signals import user_logged_in
from django.core.exceptions import PermissionDenied
from django.dispatch import receiver
from django.shortcuts import redirect

from .models import FamilyMember

SESSION_KEY = 'family_access.current_family_id'
_CACHE_ATTR = '_family_context_cache'


class FamilyContextRequired(Exception):
    """The user has several active memberships and has not picked a family."""


def active_memberships(user):
    """The user's active memberships in active families, by family name then pk.

    Anonymous and inactive users have none: the account flag is checked here,
    independently of the authentication middleware.
    """
    if not getattr(user, 'is_authenticated', False) or not getattr(user, 'is_active', False):
        return FamilyMember.objects.none()
    return (
        FamilyMember.objects.select_related('family')
        .filter(user=user, is_active=True, family__is_active=True, user__is_active=True)
        .order_by('family__name', 'pk')
    )


def _session(request):
    return getattr(request, 'session', None)


def _session_family_id(request):
    session = _session(request)
    if session is None:
        return None
    value = session.get(SESSION_KEY)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _user(request, user=None):
    return user if user is not None else getattr(request, 'user', None)


def _cache(request, user, result):
    key = (getattr(user, 'pk', None), _session_family_id(request))
    setattr(request, _CACHE_ATTR, (key, result))


def _lookup(request, user=None):
    """``(membership | None, active_count)``, cached per request, user and selection."""
    user = _user(request, user)
    selected = _session_family_id(request)
    cached = getattr(request, _CACHE_ATTR, None)
    if cached is not None and cached[0] == (getattr(user, 'pk', None), selected):
        return cached[1]

    memberships = list(active_memberships(user)) if user is not None else []
    current = next((m for m in memberships if m.family_id == selected), None)
    if current is None and len(memberships) == 1:
        current = memberships[0]
    result = (current, len(memberships))
    _cache(request, user, result)
    return result


def peek_family_context(request, user=None):
    """``(membership | None, active_count)``; never raises, redirects or writes the session.

    Returns the validated session selection or the only active membership,
    otherwise ``None`` (no membership, or several without a valid selection).
    ``user`` defaults to ``request.user`` (the sign-in signal passes it).
    """
    return _lookup(request, user)


def remember_family(request, membership, user=None):
    """Make ``membership``'s family the session's current family (``None`` clears it)."""
    session = request.session
    if membership is None:
        session.pop(SESSION_KEY, None)
    else:
        session[SESSION_KEY] = membership.family_id
    setattr(request, _CACHE_ATTR, None)
    return _lookup(request, user)


def resolve_family_context(request):
    """The current ``FamilyMember`` of the request user, or ``None`` without one.

    One active membership is selected automatically. A session id that is no
    longer one of the user's active families is replaced by that automatic
    choice, or discarded. Ordinary requests never write the session: the
    selection is recorded at sign-in and by the chooser. Several active
    memberships with no valid selection raise ``FamilyContextRequired``.
    """
    membership, count = _lookup(request)
    session = _session(request)
    if session is not None and SESSION_KEY in session and (
        membership is None or session.get(SESSION_KEY) != membership.family_id
    ):
        membership, count = remember_family(request, membership)
    if membership is not None:
        return membership
    if count > 1:
        raise FamilyContextRequired
    return None


@receiver(user_logged_in, dispatch_uid='family_access.record_family_context')
def record_family_context(sender, request, user, **kwargs):
    """Record a single-family user's family at sign-in.

    The session then keeps that family when the operator later adds a second
    membership; a multi-family user picks a family on the chooser instead.
    """
    if request is None or not hasattr(request, 'session'):
        return
    membership, count = peek_family_context(request, user)
    if membership is not None and count == 1:
        remember_family(request, membership, user)


def require_family_context(request):
    """The current ``FamilyMember``; ``PermissionDenied`` when the user has none."""
    membership = resolve_family_context(request)
    if membership is None:
        raise PermissionDenied('An active family membership is required.')
    return membership


class FamilyContextMiddleware:
    """Send a user who must pick a family to the chooser.

    Place after ``AuthenticationMiddleware`` and ``MessageMiddleware``, and
    before ``MembershipNoticeMiddleware``.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if isinstance(exception, FamilyContextRequired):
            return redirect('select_family')
        return None
