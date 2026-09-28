from django.contrib import admin

from .eduvulcan.conversion import requeue_failed_notifications
from .models import Entry, InboundNotification, NotificationConversionOutput

RAW_DATA_PRUNED = 'Raw data pruned'


@admin.register(Entry)
class EntryAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'entry_type', 'date', 'assigned_member', 'source', 'created_at')
    list_filter = ('entry_type', 'source', 'family')
    readonly_fields = ('submission_key', 'created_by', 'source', 'created_at', 'updated_at')


class ConversionOutputInline(admin.TabularInline):
    """Read-only provenance: which output index produced which entry."""

    model = NotificationConversionOutput
    fields = ('output_index', 'kind', 'entry', 'created_at')
    readonly_fields = fields
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(InboundNotification)
class InboundNotificationAdmin(admin.ModelAdmin):
    """Read-only inbox; superusers may only requeue failed conversions.

    Only safe diagnostics are shown for the lifecycle (status, attempts, error
    code). The legacy free-text ``error`` field is never displayed.
    """

    list_display = (
        'received_at',
        'family',
        'token',
        'title_display',
        'status',
        'attempt_count',
        'last_error_code',
    )
    list_filter = ('status', 'family')
    fields = (
        'family',
        'token',
        'notification_id',
        'title_display',
        'message_display',
        'payload_display',
        'captured_at',
        'captured_date',
        'content_hash',
        'status',
        'received_at',
        'processed_at',
        'attempt_count',
        'next_attempt_at',
        'lease_expires_at',
        'last_error_code',
        'raw_pruned_at',
    )
    readonly_fields = ('title_display', 'message_display', 'payload_display')
    inlines = (ConversionOutputInline,)
    actions = ('requeue_failed',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_requeue_permission(self, request):
        user = request.user
        return user.is_active and user.is_staff and user.is_superuser

    @admin.display(description='Title')
    def title_display(self, notification):
        return RAW_DATA_PRUNED if notification.raw_pruned_at else notification.title

    @admin.display(description='Message')
    def message_display(self, notification):
        return RAW_DATA_PRUNED if notification.raw_pruned_at else notification.message

    @admin.display(description='Payload')
    def payload_display(self, notification):
        return RAW_DATA_PRUNED if notification.raw_pruned_at else notification.payload

    @admin.action(
        description='Requeue selected failed notifications', permissions=('requeue',)
    )
    def requeue_failed(self, request, queryset):
        requeued = requeue_failed_notifications(queryset.values_list('pk', flat=True))
        self.message_user(request, f'Requeued failed notifications: {requeued}.')
