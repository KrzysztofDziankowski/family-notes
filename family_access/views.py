from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .access import get_active_membership


@login_required
def account_status(request):
    return render(
        request,
        'family_access/account_status.html',
        {'membership': get_active_membership(request.user)},
    )
