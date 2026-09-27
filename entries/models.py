from django.db import models
from django.db.models import Q

from family_access.models import Family, FamilyMember

from .classification.types import EntryType, SchoolItemKind

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
