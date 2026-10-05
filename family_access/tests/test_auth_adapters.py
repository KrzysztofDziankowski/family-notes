from allauth.account.adapter import get_adapter as get_account_adapter
from allauth.account.models import EmailAddress
from allauth.core.context import request_context
from allauth.socialaccount.adapter import get_adapter as get_social_adapter
from allauth.socialaccount.helpers import complete_social_login
from allauth.socialaccount.models import SocialAccount, SocialLogin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, TestCase
from django.urls import reverse

from family_access.models import FamilyMember


CLOSED_HEADING = 'Rejestracja jest wyłączona'


class LocalSignupClosedTests(TestCase):
    def test_signup_page_renders_polish_closed_page_in_app_layout(self):
        response = self.client.get(reverse('account_signup'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'account/signup_closed.html')
        self.assertTemplateUsed(response, 'base.html')
        self.assertContains(response, f'<h1>{CLOSED_HEADING}</h1>', html=True)
        self.assertContains(response, 'administrator rodziny')
        self.assertContains(response, f'href="{reverse("account_login")}"')
        self.assertNotContains(response, 'name="password1"')

    def test_signup_post_creates_no_user(self):
        response = self.client.post(reverse('account_signup'), {
            'username': 'intruder',
            'email': 'intruder@example.test',
            'password1': 'a-Strong-password-123',
            'password2': 'a-Strong-password-123',
        })

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'account/signup_closed.html')
        self.assertContains(response, CLOSED_HEADING)
        self.assertFalse(get_user_model().objects.exists())

    def test_account_adapter_is_closed_for_signup(self):
        request = RequestFactory().get('/')

        self.assertFalse(get_account_adapter(request).is_open_for_signup(request))


class GoogleFirstSignInTests(TestCase):
    email = 'new.parent@example.test'

    def _google_login(self, request):
        user = get_user_model()(email=self.email)
        account = SocialAccount(
            provider='google',
            uid='google-uid-123',
            extra_data={'email': self.email, 'email_verified': True},
        )
        email = EmailAddress(email=self.email, verified=True, primary=True)
        return SocialLogin(
            user=user,
            account=account,
            email_addresses=[email],
            provider=account.get_provider(request),
        )

    def _request(self):
        request = RequestFactory().get('/accounts/google/login/callback/')
        SessionMiddleware(lambda r: None).process_request(request)
        MessageMiddleware(lambda r: None).process_request(request)
        request.user = AnonymousUser()
        return request

    def test_social_adapter_stays_open_for_google_signup(self):
        request = self._request()

        self.assertTrue(
            get_social_adapter(request).is_open_for_signup(request, self._google_login(request))
        )

    def test_new_google_account_creates_unmapped_user_with_unconfigured_status(self):
        request = self._request()

        with request_context(request):
            response = complete_social_login(request, self._google_login(request))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], '/')
        user = get_user_model().objects.get(email=self.email)
        self.assertTrue(SocialAccount.objects.filter(user=user, provider='google').exists())
        self.assertFalse(FamilyMember.objects.filter(user=user).exists())

        self.client.force_login(user)
        status = self.client.get(reverse('account_status'))

        self.assertContains(status, 'nie jest jeszcze skonfigurowane')
        self.assertRedirects(
            self.client.get(reverse('home')), reverse('account_status'),
            fetch_redirect_response=False,
        )
