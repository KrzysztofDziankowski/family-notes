"""Shared list contract for entry views (S-02 parent index, S-03 child view).

One definition of list modes, partitioning and ordering, so every entry list
in the app shows the same rows in the same order. The helper never filters by
family, role or assignee: scoping is the caller's job.
"""

from typing import NamedTuple

from django.db.models import Case, DateField, F, QuerySet, When
from django.db.models.functions import Coalesce, TruncDate

from .classification.types import SchoolItemKind

UPCOMING = 'upcoming'
PAST = 'past'
LIST_MODES = (UPCOMING, PAST)
DEFAULT_LIST_MODE = UPCOMING

# Section keys returned by ``partition_entries``.
SECTION_DATED = 'dated'
SECTION_UNDATED = 'undated'
SECTION_PAST = 'past'


class EntrySection(NamedTuple):
    """One ordered block of a list: ``key`` names it, ``entries`` holds the rows."""

    key: str
    entries: QuerySet


def normalize_list_mode(value):
    """Return ``value`` if it is one of ``LIST_MODES``, else ``DEFAULT_LIST_MODE``."""
    return value if value in LIST_MODES else DEFAULT_LIST_MODE


def with_effective_date(queryset):
    """Annotate ``effective_date``: the stored date, or for an undated grade the
    local (``TIME_ZONE``) day of ``created_at``. Other undated entries stay null.
    The stored ``date`` is never written."""
    return queryset.annotate(
        effective_date=Coalesce(
            'date',
            Case(
                When(
                    school_item=SchoolItemKind.GRADE.value,
                    then=TruncDate('created_at'),
                ),
                default=None,
                output_field=DateField(),
            ),
            output_field=DateField(),
        )
    )


def partition_entries(queryset, mode, today):
    """Split an already-scoped ``Entry`` queryset into ordered list sections.

    ``mode`` is normalized with ``normalize_list_mode``; ``today`` is the
    application-local date (``timezone.localdate()``). Lucky-number entries are
    excluded from every mode. Rows carry an ``effective_date`` annotation.

    Returns a list of ``EntrySection(key, entries)``; each ``entries`` is a lazy,
    ordered queryset (one query when evaluated):

    - ``upcoming``: ``[EntrySection('dated', ...), EntrySection('undated', ...)]``
      - ``dated``: ``effective_date >= today``, ordered by effective date asc,
        time asc with missing times last, then ``pk`` asc.
      - ``undated``: no effective date, ordered by ``updated_at`` desc, then
        ``pk`` desc.
    - ``past``: ``[EntrySection('past', ...)]`` with ``effective_date < today``,
      ordered by effective date desc, time desc with missing times last, then
      ``pk`` desc. Undated entries never appear in past.
    """
    mode = normalize_list_mode(mode)
    rows = with_effective_date(
        queryset.exclude(school_item=SchoolItemKind.LUCKY_NUMBER.value)
    )
    if mode == PAST:
        return [
            EntrySection(
                SECTION_PAST,
                rows.filter(effective_date__lt=today).order_by(
                    F('effective_date').desc(),
                    F('time').desc(nulls_last=True),
                    '-pk',
                ),
            )
        ]
    return [
        EntrySection(
            SECTION_DATED,
            rows.filter(effective_date__gte=today).order_by(
                F('effective_date').asc(),
                F('time').asc(nulls_last=True),
                'pk',
            ),
        ),
        EntrySection(
            SECTION_UNDATED,
            rows.filter(effective_date__isnull=True).order_by('-updated_at', '-pk'),
        ),
    ]
