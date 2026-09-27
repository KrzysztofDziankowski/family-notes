from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render

from family_access.access import get_active_membership, is_parent


def _require_parent(request):
    membership = get_active_membership(request.user)
    if not is_parent(membership):
        raise PermissionDenied('An active parent membership is required.')
    return membership


@login_required
def capture(request):
    _require_parent(request)
    return render(request, 'entries/capture.html', {'state': 'empty'})
