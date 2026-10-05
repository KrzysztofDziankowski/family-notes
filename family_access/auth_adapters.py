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
"""

from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter


class ClosedSignupAccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request):
        return False


class ExternalSignInSocialAccountAdapter(DefaultSocialAccountAdapter):
    def is_open_for_signup(self, request, sociallogin):
        return True
