"""Transient proposal types produced from one EduVulcan notification.

A proposal is everything needed to save one entry, plus the stable
``output_index`` that identifies it within its notification across retries.
Fields derived from notification text (content, child names) are excluded
from ``repr`` so proposals can appear in logs or tracebacks safely.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from ..classification.types import EntryType, SchoolItemKind


class OutputKind(str, Enum):
    """How one conversion output was derived; safe, non-sensitive provenance."""

    RULE = ('rule', 'Fixed rule')
    RULE_REMAINDER = ('rule_remainder', 'Unparsed rule remainder')
    CLASSIFICATION = ('classification', 'Classification')
    GENERAL_NOTE = ('general_note', 'General note fallback')

    def __new__(cls, value: str, label: str):
        member = str.__new__(cls, value)
        member._value_ = value
        member.label = label
        return member


@dataclass(frozen=True)
class ChildSnapshot:
    """An active child membership captured at conversion time.

    Holds only the membership primary key and its display name; the name is
    family data and is kept out of ``repr``.
    """

    pk: int
    display_name: str = field(repr=False)


@dataclass(frozen=True)
class EntryProposal:
    """One entry to create for a notification, at a stable output index."""

    output_index: int
    kind: OutputKind
    entry_type: EntryType
    content: str = field(repr=False)
    date: Optional[datetime.date] = None
    time: Optional[datetime.time] = None
    school_item: Optional[SchoolItemKind] = None
    member: Optional[ChildSnapshot] = None

    @property
    def assigned_member_id(self) -> Optional[int]:
        return self.member.pk if self.member is not None else None
