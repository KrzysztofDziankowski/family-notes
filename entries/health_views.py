"""Conversion-worker health probe (``GET /healthz/conversion/``).

Separate from ``/healthz/``, which stays the release gate's exact-body
database check. Intake never depends on this state.
"""

from django.http import JsonResponse
from django.views.decorators.http import require_safe

from .eduvulcan.health import HEALTH_UNAVAILABLE, conversion_health


@require_safe
def conversion_healthz(request):
    state = conversion_health()
    return JsonResponse({'status': state}, status=503 if state == HEALTH_UNAVAILABLE else 200)
