from django.contrib import admin

from .models import Entry


@admin.register(Entry)
class EntryAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'entry_type', 'date', 'assigned_member', 'source', 'created_at')
    list_filter = ('entry_type', 'source', 'family')
    readonly_fields = ('submission_key', 'created_by', 'source', 'created_at', 'updated_at')
