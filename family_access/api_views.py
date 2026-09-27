from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .automation import automation_token_required


@require_GET
@automation_token_required
def ping(request):
    return JsonResponse({'status': 'ok', 'token': request.automation_token.name})
