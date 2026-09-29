from django.db import models
from django.db.models import Q

from family_access.models import AutomationToken, Family, FamilyMember

from .classification.types import EntryType, SchoolItemKind
from .eduvulcan.types import OutputKind

ENTRY_TYPE_LABELS = {
    EntryType.TODO: 'Zadanie',
    EntryType.CALENDAR_EVENT: 'Wydarzenie',
    EntryType.NOTE: 'Notatka',
}


class Entry(models.Model):
    class Source(models.TextChoices):
        MANUAL = 'manual', 'Ręcznie'
        EDUVULCAN = 'eduvulcan', 'EduVulcan'

    ENTRY_TYPE_CHOICES = [(kind.value, ENTRY_TYPE_LABELS[kind]) for kind in EntryType]
    SCHOOL_ITEM_CHOICES = [(kind.value, kind.label) for kind in SchoolItemKind]

    family = models.ForeignKey(
        Family,
        on_delete=models.CASCADE,
        related_name='entries',
        verbose_name='rodzina',
    )
    entry_type = models.CharField('rodzaj', max_length=20, choices=ENTRY_TYPE_CHOICES)
    content = models.TextField('treść')
    date = models.DateField('data', null=True, blank=True)
    time = models.TimeField('godzina', null=True, blank=True)
    assigned_member = models.ForeignKey(
        FamilyMember,
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name='assigned_entries',
        verbose_name='dla kogo',
    )
    school_item = models.CharField(
        'element szkolny',
        max_length=20,
        choices=SCHOOL_ITEM_CHOICES,
        blank=True,
    )
    source = models.CharField(
        'źródło',
        max_length=20,
        choices=Source.choices,
        default=Source.MANUAL,
    )
    created_by = models.ForeignKey(
        FamilyMember,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_entries',
        verbose_name='dodane przez',
    )
    submission_key = models.UUIDField(null=True, blank=True, unique=True, editable=False)
    created_at = models.DateTimeField('utworzono', auto_now_add=True)
    updated_at = models.DateTimeField('zmieniono', auto_now=True)

    class Meta:
        verbose_name = 'wpis'
        verbose_name_plural = 'wpisy'
        constraints = [
            models.CheckConstraint(
                condition=~Q(entry_type=EntryType.CALENDAR_EVENT.value)
                | Q(date__isnull=False),
                name='entry_calendar_event_requires_date',
            ),
        ]
        indexes = [
            models.Index(fields=('family', 'date'), name='entry_family_date_idx'),
        ]

    def __str__(self):
        # Never include content: it is family text and may reach logs or admin history.
        return f'{self.entry_type} #{self.pk}'

    def __repr__(self):
        return f'<Entry: {self}>'


class InboundNotification(models.Model):
    """A forwarded EduVulcan notification and its conversion lifecycle.

    ``failed`` is terminal until an operator requeues the row. A lease is held
    only while ``processing``; a retry is scheduled only while ``pending``; raw
    title, message, and payload are pruned only from ``processed`` rows.
    """

    class Status(models.TextChoices):
        PENDING = 'pending', 'Oczekuje'
        PROCESSING = 'processing', 'Przetwarzanie'
        PROCESSED = 'processed', 'Przetworzone'
        FAILED = 'failed', 'Błąd'

    family = models.ForeignKey(
        Family,
        on_delete=models.CASCADE,
        related_name='inbound_notifications',
        verbose_name='rodzina',
    )
    token = models.ForeignKey(
        AutomationToken,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inbound_notifications',
        verbose_name='token',
    )
    notification_id = models.CharField('identyfikator powiadomienia', max_length=255)
    title = models.CharField('tytuł', max_length=255)
    message = models.TextField('treść')
    captured_at = models.DateTimeField('przechwycono')
    captured_date = models.DateField('dzień przechwycenia')
    content_hash = models.CharField(max_length=64)
    payload = models.JSONField('dane źródłowe')
    status = models.CharField(
        'status',
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    received_at = models.DateTimeField('odebrano', auto_now_add=True)
    processed_at = models.DateTimeField('przetworzono', null=True, blank=True)
    error = models.TextField('błąd', blank=True)
    # Conversion lifecycle (S-05). Admin-only metadata, so labels are English.
    # ``last_error_code`` holds a safe category code only, never notification
    # text, provider responses, or tokens. The NOT NULL columns also carry a
    # database default, so the previous release's code (which does not know
    # them) can still insert rows after a code-only rollback.
    attempt_count = models.PositiveSmallIntegerField('attempt count', default=0, db_default=0)
    next_attempt_at = models.DateTimeField('next attempt at', null=True, blank=True)
    lease_expires_at = models.DateTimeField('lease expires at', null=True, blank=True)
    last_error_code = models.CharField(
        'last error code', max_length=64, blank=True, default='', db_default=''
    )
    raw_pruned_at = models.DateTimeField('raw data pruned at', null=True, blank=True)

    class Meta:
        verbose_name = 'powiadomienie przychodzące'
        verbose_name_plural = 'powiadomienia przychodzące'
        constraints = [
            models.UniqueConstraint(
                fields=('family', 'notification_id'),
                name='inbound_unique_notification_id_per_family',
            ),
            models.UniqueConstraint(
                fields=('family', 'content_hash', 'captured_date'),
                name='inbound_unique_content_per_family_day',
            ),
            models.CheckConstraint(
                condition=Q(status='processing', lease_expires_at__isnull=False)
                | (~Q(status='processing') & Q(lease_expires_at__isnull=True)),
                name='inbound_lease_only_while_processing',
            ),
            models.CheckConstraint(
                condition=Q(status='pending') | Q(next_attempt_at__isnull=True),
                name='inbound_retry_only_while_pending',
            ),
            models.CheckConstraint(
                condition=Q(raw_pruned_at__isnull=True)
                | Q(status='processed', title='', message=''),
                name='inbound_prune_only_processed_raw_data',
            ),
        ]
        indexes = [
            models.Index(
                fields=('status', 'next_attempt_at'), name='inbound_status_retry_idx'
            ),
            models.Index(
                fields=('status', 'lease_expires_at'), name='inbound_status_lease_idx'
            ),
        ]

    def __str__(self):
        # Never include title or message: they name family members.
        return f'notification #{self.pk} ({self.status})'


class NotificationConversionOutput(models.Model):
    """Provenance of one entry generated from a notification.

    ``output_index`` is stable within a notification, so a retry recognises
    completed outputs. Deleting the entry nulls ``entry`` but keeps this
    non-sensitive tombstone, so a retry never recreates a deleted entry.
    Admin-only metadata, so labels are English.
    """

    KIND_CHOICES = [(kind.value, kind.label) for kind in OutputKind]

    notification = models.ForeignKey(
        InboundNotification,
        on_delete=models.CASCADE,
        related_name='conversion_outputs',
        verbose_name='notification',
    )
    output_index = models.PositiveSmallIntegerField('output index')
    kind = models.CharField('kind', max_length=20, choices=KIND_CHOICES)
    # One output link owns a generated entry; several tombstones may hold NULL.
    entry = models.OneToOneField(
        Entry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='conversion_output',
        verbose_name='entry',
    )
    created_at = models.DateTimeField('created at', auto_now_add=True)
    updated_at = models.DateTimeField('updated at', auto_now=True)

    class Meta:
        verbose_name = 'notification conversion output'
        verbose_name_plural = 'notification conversion outputs'
        ordering = ('notification', 'output_index')
        constraints = [
            models.UniqueConstraint(
                fields=('notification', 'output_index'),
                name='conversion_output_unique_index_per_notification',
            ),
            models.CheckConstraint(
                condition=Q(kind__in=[kind.value for kind in OutputKind]),
                name='conversion_output_known_kind',
            ),
        ]

    def __str__(self):
        return f'notification #{self.notification_id} output {self.output_index} ({self.kind})'


class ConversionWorkerHeartbeat(models.Model):
    """Last time one conversion worker process proved it was alive.

    Each Gunicorn process's worker writes its own row, keyed by a stable
    process identity (hostname and PID), and records the release it runs.
    ``/healthz/conversion/`` counts only fresh rows of the current release, so
    heartbeats left by a previous release or an exited process never mask a
    release whose workers did not start. Stale rows are deleted by the
    worker's maintenance. Rows hold identities and timestamps only, never
    queue contents or family data. Admin-only metadata, so labels are English.
    """

    name = models.CharField('name', max_length=64, unique=True)
    release = models.CharField(
        'release', max_length=128, blank=True, default='', db_default=''
    )
    beat_at = models.DateTimeField('last heartbeat at')

    class Meta:
        verbose_name = 'conversion worker heartbeat'
        verbose_name_plural = 'conversion worker heartbeats'
        indexes = [
            models.Index(fields=('release', 'beat_at'), name='heartbeat_release_beat_idx'),
        ]

    def __str__(self):
        return f'{self.name} heartbeat'
