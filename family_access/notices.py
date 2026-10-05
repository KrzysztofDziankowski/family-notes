"""Changed-membership notice (S-15): tell a parent who lost parent rights what happened.

The user's own session remembers the membership id and role it last saw
(``family_access.seen_membership``) in the current family context (S-16).
The current membership comes from ``peek_family_context``, so a switch to
another family is never mistaken for a lost parent role. When that entry says ``parent`` and the
same membership is now a child, or is no longer active, the next request
queues one Polish warning. Nothing is stored in the database and nothing
naming a person is stored or logged. A new sign-in seeds the entry from the
current state, so a change made while signed out produces no notice.
"""

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from .context import peek_family_context
from .models import FamilyMember

SESSION_KEY = 'family_access.seen_membership'

DEMOTED_NOTICE = (
    'Inny rodzic lub administrator rodziny zmienił Twoją rolę na „Dziecko”. '
    'Nie możesz już zarządzać wpisami ani członkami rodziny. Jeśli to pomyłka, '
    'skontaktuj się z drugim rodzicem lub administratorem rodziny.'
)
DEACTIVATED_NOTICE = (
    'Twoje uprawnienia rodzica w tej rodzinie zostały wyłączone przez innego rodzica '
    'lub administratora rodziny. Jeśli to pomyłka, skontaktuj się z drugim rodzicem '
    'lub administratorem rodziny.'
)


def remember_membership(request, membership):
    """Store (or clear) the membership this session last saw; writes only on change."""
    entry = None if membership is None else {'id': membership.pk, 'role': membership.role}
    session = request.session
    if session.get(SESSION_KEY) == entry:
        return
    if entry is None:
        session.pop(SESSION_KEY, None)
    else:
        session[SESSION_KEY] = entry


def _lost_parent_notice(seen, membership):
    if not isinstance(seen, dict) or seen.get('role') != FamilyMember.Role.PARENT:
        return None
    if membership is not None and membership.pk == seen.get('id'):
        return DEMOTED_NOTICE if membership.role == FamilyMember.Role.CHILD else None
    still_active = FamilyMember.objects.filter(pk=seen.get('id'), is_active=True).exists()
    return None if still_active else DEACTIVATED_NOTICE


class MembershipNoticeMiddleware:
    """Queue the notice once on the next request.

    Place after ``MessageMiddleware`` and ``FamilyContextMiddleware``.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Requests without a session cookie (anonymous, automation API) are
        # skipped without touching the session, so they gain no Vary: Cookie.
        if settings.SESSION_COOKIE_NAME in request.COOKIES and request.user.is_authenticated:
            membership, _count = peek_family_context(request)
            notice = _lost_parent_notice(request.session.get(SESSION_KEY), membership)
            if notice:
                messages.warning(request, notice)
            remember_membership(request, membership)
        return self.get_response(request)


@receiver(user_logged_in, dispatch_uid='family_access.seed_seen_membership')
def seed_seen_membership(sender, request, user, **kwargs):
    """Start each sign-in from the current state, so it never shows a stale notice."""
    if request is not None and hasattr(request, 'session'):
        remember_membership(request, peek_family_context(request, user)[0])
