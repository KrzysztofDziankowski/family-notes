from django.contrib import admin

from .models import Entry, InboundNotification


@admin.register(Entry)
class EntryAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'entry_type', 'date', 'assigned_member', 'source', 'created_at')
    list_filter = ('entry_type', 'source', 'family')
    readonly_fields = ('submission_key', 'created_by', 'source', 'created_at', 'updated_at')


@admin.register(InboundNotification)
class InboundNotificationAdmin(admin.ModelAdmin):
    list_display = ('received_at', 'family', 'token', 'title', 'status')
    list_filter = ('status', 'family')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
