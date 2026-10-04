from django.db import DatabaseError, connection
from django.http import JsonResponse
from django.shortcuts import redirect

from family_access.access import get_active_membership, is_parent
from family_access.models import FamilyMember


def home(request):
    """Send each visitor to the home page of their role."""
    if not request.user.is_authenticated:
        return redirect('account_login')

    membership = get_active_membership(request.user)
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
    except DatabaseError:
        return JsonResponse({'status': 'unavailable'}, status=503)

    return JsonResponse({'status': 'ok'})
