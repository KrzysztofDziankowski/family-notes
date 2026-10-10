"""Shared list contract for entry views (S-02 parent index, S-03 child view).

One definition of list modes, partitioning and ordering, so every entry list
in the app shows the same rows in the same order. The helper never filters by
family, role or assignee: scoping is the caller's job.
"""

from itertools import groupby
from typing import NamedTuple

from django.conf import settings
from django.db.models import Case, DateField, F, QuerySet, When
from django.db.models.functions import Coalesce, TruncDate
from django.utils import translation
from django.utils.formats import date_format
from django.utils.text import capfirst

from family_access.models import FamilyMember

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


# Group key for entries assigned to no member ("Cała rodzina").
GROUP_FAMILY = 'family'


class AssigneeGroup(NamedTuple):
    """One assignee's rows within a day: ``member`` is ``None`` for the
    family-wide group; ``entries`` keeps the input row order."""

    key: str
    member: object
    entries: list


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


RELATIVE_DAY_HEADINGS = {0: 'Dziś', 1: 'Jutro', -1: 'Wczoraj'}
WEEKDAY_HEADING_MAX_DAYS = 6


def _calendar_pattern(day, today):
    """``"j E"`` (``"12 października"``), plus the year when it differs from today's."""
    return 'j E' if day.year == today.year else 'j E Y'


def _relative_day_heading(day, today):
    """``"Dziś, czwartek 8 października"`` for an adjacent day, else ``None``.

    Shared by the parent and child headings so ``Dziś``/``Jutro``/``Wczoraj``
    always name the weekday and the calendar date (year added when it differs
    from ``today.year``). Callers must hold the ``LANGUAGE_CODE`` override."""
    relative = RELATIVE_DAY_HEADINGS.get((day - today).days)
    if relative is None:
        return None
    weekday = date_format(day, 'l').lower()
    return f'{relative}, {weekday} {date_format(day, _calendar_pattern(day, today))}'


def day_heading(day, today):
    """Capitalised Polish heading for ``day`` relative to ``today``.

    ``"Dziś, poniedziałek 28 września"`` (likewise ``Jutro``/``Wczoraj``) for the
    adjacent days, the weekday name within six days either way, otherwise
    ``"Poniedziałek, 12 października"``; full dates carry the year when it
    differs from ``today.year``. Names come from Django's date formatting in
    ``LANGUAGE_CODE``, whatever locale the request activated.
    """
    with translation.override(settings.LANGUAGE_CODE):
        relative = _relative_day_heading(day, today)
        if relative:
            return relative
        if abs((day - today).days) <= WEEKDAY_HEADING_MAX_DAYS:
            pattern = 'l'
        else:
            pattern = f'l, {_calendar_pattern(day, today)}'
        return capfirst(date_format(day, pattern))


def parent_day_heading(day, today):
    """Full Polish calendar heading for one day in the parent's calendar:
    ``"Dziś, czwartek 8 października"`` or ``"Sobota, 10 października"``."""
    with translation.override(settings.LANGUAGE_CODE):
        return _relative_day_heading(day, today) or capfirst(
            date_format(day, f'l, {_calendar_pattern(day, today)}')
        )


def is_weekend(day):
    """True for Saturday and Sunday; their day headings get the weekend colour."""
    return day.weekday() >= 5


def group_by_day(entries, today):
    """Split ordered ``entries`` into consecutive ``(heading, entries)`` groups by
    ``effective_date``, keeping the input order. Every entry must carry an
    ``effective_date`` (see ``with_effective_date``)."""
    return [
        (day_heading(day, today), list(rows))
        for day, rows in groupby(entries, key=lambda entry: entry.effective_date)
    ]


def _assignee_group_order(member):
    """Children first, then parents, each by member pk; the family group last."""
    if member is None:
        return (2, 0)
    return (0 if member.role == FamilyMember.Role.CHILD else 1, member.pk)


def split_by_assignee(entries):
    """Split one day's ordered ``entries`` into assignee sub-groups (S-08 order).

    Returns ``AssigneeGroup``s ordered children (active or not) by pk, then
    parents by pk, then the ``GROUP_FAMILY`` group of unassigned entries. Each
    group keeps the input row order, and every row lands in exactly one group.
    Rows need ``assigned_member`` loaded (use ``select_related``) to avoid a
    query per row.
    """
    buckets = {}
    for entry in entries:
        member = entry.assigned_member
        key = GROUP_FAMILY if member is None else f'member-{member.pk}'
        buckets.setdefault(key, (member, []))[1].append(entry)
    ordered = sorted(buckets.items(), key=lambda item: _assignee_group_order(item[1][0]))
    return [AssigneeGroup(key, member, rows) for key, (member, rows) in ordered]
