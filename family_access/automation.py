import logging
from functools import wraps

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .access import is_parent
from .models import AutomationToken

logger = logging.getLogger(__name__)


def _reject(reason, token=None):
    if token is None:
        logger.warning('Automation token rejected: %s', reason)
    else:
        logger.warning(
            'Automation token rejected: %s (prefix %s)',
            reason,
            token.prefix,
        )
    return None


def _bearer_secret(request):
    header = request.META.get('HTTP_AUTHORIZATION', '')
    parts = header.split()
    if len(parts) != 2 or parts[0].lower() != 'bearer':
        return None
    return parts[1]


def authenticate_automation_request(request):
    secret = _bearer_secret(request)
    if secret is None:
        return _reject('missing or malformed authorization header')

    token = (
        AutomationToken.objects.select_related('member__family', 'member__user')
        .filter(token_hash=AutomationToken.hash_secret(secret))
        .first()
    )
    if token is None:
        return _reject('unknown token')

    now = timezone.now()
    if token.is_revoked:
        return _reject('revoked token', token)
    if token.is_expired(now):
        return _reject('expired token', token)
    if not is_parent(token.member):
        return _reject('owner is not an active parent', token)
    if not token.member.user.is_active:
        return _reject('owner account is inactive', token)

    AutomationToken.objects.filter(pk=token.pk).update(last_used_at=now)
    token.last_used_at = now
    return token


def automation_token_required(view):
    @csrf_exempt
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        token = authenticate_automation_request(request)
        if token is None:
            response = JsonResponse({'error': 'invalid_token'}, status=401)
            response['WWW-Authenticate'] = 'Bearer'
            return response
        request.automation_token = token
        request.automation_membership = token.member
        return view(request, *args, **kwargs)

    return wrapper
