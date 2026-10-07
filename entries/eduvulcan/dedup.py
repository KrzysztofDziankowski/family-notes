"""Duplicate and exam-merge decisions for EduVulcan rule proposals.

``decide`` compares one fixed-rule proposal with candidate live entries of the
same family and says whether to create it, skip it as a duplicate, skip it as
merged into a higher-or-equal-ranked exam, or upgrade an existing exam entry.
It reads only the values it is given and never writes database rows.

Matching rules:

- Exact duplicate: an EduVulcan entry with equal entry type, assignee (both
  may be unassigned), school item, and normalized content. A dated proposal
  needs the same date; an undated one needs an undated entry whose source
  notification was captured on the same day.
- Exam merge: an EduVulcan calendar event for the same assignee and date whose
  content starts with an exam label and has the same normalized remainder.
  Kartkówka < Sprawdzian < Praca klasowa; homework is never ranked.

The exact-duplicate check runs first. Among several exam matches the
highest-ranked one wins, ties by the lowest id.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, NamedTuple, Optional

from ..classification.types import EntryType, SchoolItemKind
from ..models import Entry
from .rules import _CALENDAR_CATEGORIES
from .text import normalize_text
from .types import EntryProposal, OutputKind

# Exam kinds by rank; a higher rank replaces a lower one for the same lesson.
EXAM_RANKS = {
    SchoolItemKind.QUIZ: 1,
    SchoolItemKind.TEST: 2,
    SchoolItemKind.CLASS_TEST: 3,
}
EXAM_KINDS = frozenset(EXAM_RANKS)

# Entry label (as the rules write it) -> exam kind.
_EXAM_LABELS = {
    label: kind for label, kind in _CALENDAR_CATEGORIES.values() if kind in EXAM_RANKS
}

_DEDUPLICATED_KINDS = frozenset({OutputKind.RULE, OutputKind.RULE_REMAINDER})


def normalize_content(value: str) -> str:
    """NFC, collapsed whitespace, and case-insensitive comparison form."""
    return normalize_text(value).casefold()


class ExamRank(NamedTuple):
    """An exam entry's rank, canonical label, and normalized remainder."""

    rank: int
    label: str
    remainder: str


def _split_exam(content: str):
    """``(label, remainder text)`` for exam content, or ``None``."""
    text = normalize_text(content)
    for label in _EXAM_LABELS:
        prefix = f'{label}: '
        if text[: len(prefix)].casefold() == prefix.casefold():
            return label, text[len(prefix):]
    return None


def exam_rank(content: str) -> Optional[ExamRank]:
    """The exam rank of entry content, or ``None`` when it is not an exam."""
    split = _split_exam(content)
    if split is None:
        return None
    label, remainder = split
    return ExamRank(EXAM_RANKS[_EXAM_LABELS[label]], label, remainder.casefold())


@dataclass(frozen=True)
class Candidate:
    """A live entry of the family and its source notification's capture day.

    ``entry`` needs ``pk``, ``entry_type``, ``assigned_member_id``, ``date``,
    ``school_item`` (stored value, ``''`` when none), ``content`` and
    ``source``. ``captured_date`` is ``None`` when the entry has no source
    notification.
    """

    entry: Any = field(repr=False)
    captured_date: Optional[datetime.date] = None


class Action(str, Enum):
    CREATE = 'create'
    DUPLICATE = 'duplicate'
    MERGED = 'merged'
    UPGRADE = 'upgrade'


@dataclass(frozen=True)
class Decision:
    """What to do with one proposal.

    ``entry`` is the matched existing entry for every action except
    ``create``. ``content`` and ``school_item`` are the upgraded values and
    are set only for ``upgrade``.
    """

    action: Action
    entry: Any = field(default=None, repr=False)
    content: str = field(default='', repr=False)
    school_item: Optional[SchoolItemKind] = None


CREATE = Decision(Action.CREATE)


def _stored_school_item(school_item: Optional[SchoolItemKind]) -> str:
    return school_item.value if school_item is not None else ''


def _is_exact_duplicate(proposal, captured_date, candidate) -> bool:
    entry = candidate.entry
    if (
        entry.entry_type != EntryType(proposal.entry_type).value
        or entry.assigned_member_id != proposal.assigned_member_id
        or (entry.school_item or '') != _stored_school_item(proposal.school_item)
        or normalize_content(entry.content) != normalize_content(proposal.content)
    ):
        return False
    if proposal.date is not None:
        return entry.date == proposal.date
    return (
        entry.date is None
        and candidate.captured_date is not None
        and candidate.captured_date == captured_date
    )


def _exam_match(proposal, incoming: ExamRank, candidate) -> Optional[ExamRank]:
    entry = candidate.entry
    if (
        entry.entry_type != EntryType.CALENDAR_EVENT.value
        or entry.assigned_member_id != proposal.assigned_member_id
        or entry.date is None
        or entry.date != proposal.date
    ):
        return None
    existing = exam_rank(entry.content)
    if existing is None or existing.remainder != incoming.remainder:
        return None
    return existing


def decide(
    proposal: EntryProposal,
    captured_date: Optional[datetime.date],
    candidates: Iterable[Candidate],
) -> Decision:
    """Decide how to persist ``proposal`` given live family entries.

    Only ``rule`` and ``rule_remainder`` proposals are deduplicated; every
    other proposal, and every candidate that is not an EduVulcan entry, is
    ignored, so the result is ``create``.
    """
    if proposal.kind not in _DEDUPLICATED_KINDS:
        return CREATE
    candidates = sorted(
        (item for item in candidates if item.entry.source == Entry.Source.EDUVULCAN),
        key=lambda item: item.entry.pk,
    )

    for candidate in candidates:
        if _is_exact_duplicate(proposal, captured_date, candidate):
            return Decision(Action.DUPLICATE, entry=candidate.entry)

    incoming = exam_rank(proposal.content)
    if incoming is None or proposal.entry_type != EntryType.CALENDAR_EVENT or proposal.date is None:
        return CREATE
    best = None
    for candidate in candidates:
        existing = _exam_match(proposal, incoming, candidate)
        # Strictly greater keeps the lowest id among equal ranks.
        if existing is not None and (best is None or existing.rank > best[1].rank):
            best = (candidate.entry, existing)
    if best is None:
        return CREATE

    entry, existing = best
    if incoming.rank <= existing.rank:
        return Decision(Action.MERGED, entry=entry)
    _, remainder = _split_exam(entry.content)
    return Decision(
        Action.UPGRADE,
        entry=entry,
        content=f'{incoming.label}: {remainder}',
        school_item=_EXAM_LABELS[incoming.label] if entry.assigned_member_id is not None else None,
    )
