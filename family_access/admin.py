from django.contrib import admin

from .models import Family, FamilyMember


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
