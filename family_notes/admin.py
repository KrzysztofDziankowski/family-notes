from allauth.account.decorators import secure_admin_login
from django.contrib.admin import AdminSite
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect


class SuperuserAdminSite(AdminSite):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.login = secure_admin_login(self.login)

    def login(self, request, extra_context=None):
        # The stock form would let an authenticated staff non-superuser try
        # another account's password outside allauth's rate limits.
        if not self.has_permission(request):
            raise PermissionDenied
        return redirect('admin:index')

    def has_permission(self, request):
        return request.user.is_active and request.user.is_superuser
