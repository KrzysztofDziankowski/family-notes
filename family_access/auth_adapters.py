"""Sign-up policy for allauth.

Family accounts are provisioned by an operator: a person signs in with Google
once, allauth creates the Django ``User``, and a superuser then maps that user
to an active ``FamilyMember`` in the admin. Until that mapping exists the user
sees no family data (see ``family_access.access``).

Local (username/e-mail + password) self-registration is therefore closed.
allauth's default social adapter delegates ``is_open_for_signup`` to the
account adapter, so closing account sign-up alone would also block the Google
first sign-in that provisioning depends on. The social adapter below re-opens
sign-up for external identities explicitly.

allauth's "signed in as …" / "signed out" confirmations are dropped: they say
nothing the next page doesn't, and Django keeps queued messages in a cookie
that outlives the session, so a stale "Zalogowano jako …" surfaced on later,
unrelated pages (including the login page after signing out).
"""

from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter


SILENCED_MESSAGE_TEMPLATES = frozenset({
    'account/messages/logged_in.txt',
    'account/messages/logged_out.txt',
})


class ClosedSignupAccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request):
        return False

    def add_message(self, request, level, message_template=None, message_context=None,
                    extra_tags='', message=None):
        if message_template in SILENCED_MESSAGE_TEMPLATES:
            return
        super().add_message(
            request, level, message_template=message_template,
            message_context=message_context, extra_tags=extra_tags, message=message,
        )


class ExternalSignInSocialAccountAdapter(DefaultSocialAccountAdapter):
    def is_open_for_signup(self, request, sociallogin):
        return True
