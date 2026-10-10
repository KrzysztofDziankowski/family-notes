"""Shared calendar helpers for entry views (S-02 parent index, S-03 child view).

The effective date, day headings, weekend marker and assignee grouping used by
both calendars. The helpers never filter by family, role or assignee: scoping
is the caller's job.
"""

from typing import NamedTuple

from django.conf import settings
from django.db.models import Case, DateField, When
from django.db.models.functions import Coalesce, TruncDate
from django.utils import translation
from django.utils.formats import date_format
from django.utils.text import capfirst

from family_access.models import FamilyMember

from .classification.types import SchoolItemKind

# Group key for entries assigned to no member ("Ogólne").
GROUP_FAMILY = 'family'


class AssigneeGroup(NamedTuple):
    """One assignee's rows within a day: ``member`` is ``None`` for the
    family-wide group; ``entries`` keeps the input row order."""

    key: str
    member: object
    entries: list


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


RELATIVE_DAY_HEADINGS = {0: 'Dziś', 1: 'Jutro', -1: 'Wczoraj'}


def _calendar_pattern(day, today):
    """``"j E"`` (``"12 października"``), plus the year when it differs from today's."""
    return 'j E' if day.year == today.year else 'j E Y'


def _relative_day_heading(day, today):
    """``"Dziś, czwartek 8 października"`` for an adjacent day, else ``None``.

    ``Dziś``/``Jutro``/``Wczoraj`` always name the weekday and the calendar date
    (year added when it differs from ``today.year``). Callers must hold the
    ``LANGUAGE_CODE`` override."""
    relative = RELATIVE_DAY_HEADINGS.get((day - today).days)
    if relative is None:
        return None
    weekday = date_format(day, 'l').lower()
    return f'{relative}, {weekday} {date_format(day, _calendar_pattern(day, today))}'


def parent_day_heading(day, today):
    """Full Polish calendar heading for one day in the parent and child calendars:
    ``"Dziś, czwartek 8 października"`` or ``"Sobota, 10 października"``."""
    with translation.override(settings.LANGUAGE_CODE):
        return _relative_day_heading(day, today) or capfirst(
            date_format(day, f'l, {_calendar_pattern(day, today)}')
        )


def is_weekend(day):
    """True for Saturday and Sunday; their day headings get the weekend colour."""
    return day.weekday() >= 5


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
