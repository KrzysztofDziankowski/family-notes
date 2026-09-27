from django.contrib import admin
from django.template.response import TemplateResponse
from django.utils import timezone

from .models import AutomationToken, Family, FamilyMember


@admin.register(Family)
class FamilyAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active', 'created_at', 'updated_at')
    list_filter = ('is_active',)
    search_fields = ('name',)


@admin.register(FamilyMember)
class FamilyMemberAdmin(admin.ModelAdmin):
    list_display = (
        'display_name',
        'user_email',
        'family',
        'role',
        'is_active',
        'created_at',
        'updated_at',
    )
    list_filter = ('role', 'is_active', 'family')
    search_fields = (
        'display_name',
        'user__email',
        'user__username',
        'family__name',
    )
    autocomplete_fields = ('user', 'family')

    @admin.display(description='Email', ordering='user__email')
    def user_email(self, member):
        return member.user.email


@admin.register(AutomationToken)
class AutomationTokenAdmin(admin.ModelAdmin):
    add_fields = ('member', 'name', 'expires_at')
    change_fields = (
        'member',
        'name',
        'prefix',
        'expires_at',
        'created_at',
        'last_used_at',
        'revoked_at',
    )
    change_readonly_fields = (
        'member',
        'prefix',
        'created_at',
        'last_used_at',
        'revoked_at',
    )
    list_display = (
        'name',
        'member',
        'prefix',
        'created_at',
        'expires_at',
        'last_used_at',
        'revoked_at',
        'status',
    )
    list_filter = ('member', ('revoked_at', admin.EmptyFieldListFilter))
    search_fields = ('name', 'prefix', 'member__display_name')
    autocomplete_fields = ('member',)
    actions = ('revoke_tokens',)

    def get_fields(self, request, obj=None):
        return self.add_fields if obj is None else self.change_fields

    def get_readonly_fields(self, request, obj=None):
        return () if obj is None else self.change_readonly_fields

    def save_model(self, request, obj, form, change):
        if not change:
            request._automation_token_secret = obj.assign_new_secret()
        super().save_model(request, obj, form, change)

    def response_add(self, request, obj, post_url_continue=None):
        secret = getattr(request, '_automation_token_secret', None)
        if secret is None:
            return super().response_add(request, obj, post_url_continue)
        context = {
            **self.admin_site.each_context(request),
            'opts': self.opts,
            'title': 'Token automatyzacji wydany',
            'token': obj,
            'secret': secret,
        }
        return TemplateResponse(
            request,
            'admin/family_access/automationtoken/issued.html',
            context,
        )

    @admin.display(description='Status')
    def status(self, token):
        if token.is_revoked:
            return 'Unieważniony'
        if token.is_expired(timezone.now()):
            return 'Wygasły'
        return 'Aktywny'

    @admin.action(description='Unieważnij wybrane tokeny')
    def revoke_tokens(self, request, queryset):
        revoked = queryset.filter(revoked_at__isnull=True).update(
            revoked_at=timezone.now()
        )
        self.message_user(request, f'Unieważniono tokeny: {revoked}.')
