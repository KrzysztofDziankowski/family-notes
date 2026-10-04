"""Shared login protection and narrowly scoped operator recovery.

The private allauth key/lock API is isolated here and covered by regressions.
Do not log exception text: Database errors can contain connection credentials.
"""

import ipaddress
import logging

from allauth.account import app_settings
from allauth.account.adapter import get_adapter
from allauth.core.internal import ratelimit
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.utils.deprecation import MiddlewareMixin
from family_notes.auth_cache import AuthCacheUnavailable
from family_notes.log_safety import exception_summary

logger = logging.getLogger(__name__)


class AuthCacheFailureMiddleware(MiddlewareMixin):
    def process_exception(self, request, exception):
        # This cache is used only for authentication state. Deny rather
        # than return a traceback or retry with an unprotected cache.
        if isinstance(exception, AuthCacheUnavailable):
            # The summary follows the suppressed database cause, never its text.
            logger.error('authentication_cache_unavailable error=%s', exception_summary(exception))
            return HttpResponse(
                'Logowanie jest chwilowo niedostępne. Spróbuj ponownie później.',
                status=503,
                content_type='text/plain; charset=utf-8',
            )
        return None


def admin_limit_targets(user_id, client_ip):
    """Return server-derived cache keys; arguments never select arbitrary keys."""
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
        raise ValidationError('Invalid operator ID.')
    try:
        client_ip = str(ipaddress.ip_address(client_ip))
    except ValueError:
        raise ValidationError('Invalid client IP.') from None
    user = get_user_model().objects.filter(
        pk=user_id, is_active=True, is_superuser=True,
    ).first()
    if user is None:
        raise ValidationError('An active superuser is required.')

    request = HttpRequest()
    request.method = 'POST'
    # The first allowed host is the canonical production host in the runbook.
    host = settings.ALLOWED_HOSTS[0] if settings.ALLOWED_HOSTS else ''
    if not host or host == '*' or host.startswith('.'):
        raise ValidationError('A canonical host is required.')
    request.META['HTTP_HOST'] = host
    request.META['REMOTE_ADDR'] = client_ip
    request.META['HTTP_X_REAL_IP'] = client_ip
    request.user = user

    credentials = []
    for method in app_settings.LOGIN_METHODS:
        if method == 'username':
            credentials.append({'username': user.get_username()})
        elif method == 'email' and user.email:
            credentials.append({'email': user.email})
        else:
            raise ValidationError('Unsupported operator login configuration.')
    targets = set()
    adapter = get_adapter(request)
    for action in ('login', 'login_failed'):
        for credential in credentials:
            account_key = adapter._get_login_attempts_cache_key(request, **credential)
            for rate in ratelimit.parse_rates(app_settings.RATE_LIMITS.get(action)):
                targets.add(ratelimit.get_cache_key(
                    request, action=action, rate=rate, key=account_key, user=user,
                ))
    if not targets:
        raise ValidationError('Login rate limits are not configured.')
    return sorted(targets)


def reset_admin_login_limits(user_id, client_ip):
    """Clear only selected histories under allauth's own per-key locks.

    Lock contention fails explicitly. Another live attempt can recreate a
    history after recovery; verify before announcing success, without flushing.
    """
    targets = admin_limit_targets(user_id, client_ip)
    for key in targets:
        with ratelimit.cache_lock(key) as locked:
            if not locked:
                raise ValidationError('Login limit reset busy; retry later.')
            cache.delete(key)
            if cache.get(key) is not None:
                raise ValidationError('Login limit reset could not be verified.')
    if any(cache.get(key) is not None for key in targets):
        raise ValidationError('Login activity resumed; reset could not be verified.')
    logger.info('admin_login_limits_reset user_id=%s', user_id)
