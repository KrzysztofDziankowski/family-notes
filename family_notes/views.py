import json
import logging

from django.conf import settings
from django.db import DatabaseError, connection
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.templatetags.static import static
from django.urls import reverse
from django.views.decorators.http import require_safe

from family_access.access import is_parent
from family_access.context import resolve_family_context
from family_access.models import FamilyMember
from family_notes.log_safety import exception_summary

logger = logging.getLogger(__name__)


def home(request):
    """Send each visitor to the home page of their role in the current family."""
    if not request.user.is_authenticated:
        return redirect('account_login')

    membership = resolve_family_context(request)
    if membership is not None and membership.role == FamilyMember.Role.CHILD:
        return redirect('entries:child_list')
    if is_parent(membership):
        return redirect('entries:index')
    return redirect('account_status')


def healthz(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
    except DatabaseError as exc:
        logger.warning('healthz database check failed: error=%s', exception_summary(exc))
        return JsonResponse({'status': 'unavailable'}, status=503)

    return JsonResponse({'status': 'ok'})


# --- Installable web app (S-06) ---

# Mirror --fn-color-accent and --fn-color-bg in css/tokens.css (a test keeps
# them in sync); the manifest carries the colours because templates may not.
PWA_THEME_COLOR = '#2f6f5e'
PWA_BACKGROUND_COLOR = '#f7f8fa'
PWA_CACHE_PREFIX = 'familynotes-'
# Shell assets the service worker may cache; never family data or pages.
PWA_PRECACHE_STATIC = (
    'vendor/pico/pico.min.css',
    'css/tokens.css',
    'pwa/icon-192.png',
)


def web_manifest_data():
    return {
        'name': 'FamilyNotes',
        'short_name': 'FamilyNotes',
        'description': 'Wspólne notatki i sprawy rodziny',
        'lang': 'pl',
        'dir': 'ltr',
        'id': '/',
        'start_url': '/',
        'scope': '/',
        'display': 'standalone',
        'theme_color': PWA_THEME_COLOR,
        'background_color': PWA_BACKGROUND_COLOR,
        'icons': [
            {'src': static('pwa/icon-192.png'), 'sizes': '192x192', 'type': 'image/png',
             'purpose': 'any'},
            {'src': static('pwa/icon-512.png'), 'sizes': '512x512', 'type': 'image/png',
             'purpose': 'any'},
            {'src': static('pwa/icon-maskable-512.png'), 'sizes': '512x512',
             'type': 'image/png', 'purpose': 'maskable'},
        ],
    }


@require_safe
def web_manifest(request):
    """The web app manifest, served from the root so its scope can be ``/``."""
    return JsonResponse(web_manifest_data(), content_type='application/manifest+json')


def service_worker_cache_name():
    """Release-derived, so every deploy re-installs the worker and its shell."""
    return f'{PWA_CACHE_PREFIX}shell-{settings.FAMILY_NOTES_RELEASE_ID}'


@require_safe
def service_worker(request):
    """The service worker, served from the root so its scope can be ``/``.

    Template values are JSON-serialized here and come only from ``static()``,
    ``reverse()`` and the release id.
    """
    offline_url = reverse('offline')
    precache = [offline_url, *(static(path) for path in PWA_PRECACHE_STATIC)]
    response = render(
        request,
        'pwa/sw.js',
        {
            'cache_name': json.dumps(service_worker_cache_name()),
            'cache_prefix': json.dumps(PWA_CACHE_PREFIX),
            'offline_url': json.dumps(offline_url),
            'precache_urls': json.dumps(precache),
        },
        content_type='text/javascript; charset=utf-8',
    )
    response['Cache-Control'] = 'no-cache'
    return response


@require_safe
def offline(request):
    """The offline fallback page; it renders nothing user-specific."""
    response = render(request, 'offline.html')
    response['Cache-Control'] = 'no-cache'
    return response
