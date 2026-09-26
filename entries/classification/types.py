"""Provider-independent classification result types.

These types are the only classification objects later capture flows should
consume. They never reference provider SDK classes and never retain raw
provider payloads. Fields derived from the submitted instruction (content,
member names) are excluded from ``repr`` so results can be logged or appear in
tracebacks without leaking family text.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, Optional, Tuple, Union


class EntryType(str, Enum):
    TODO = 'todo'
    CALENDAR_EVENT = 'calendar_event'
    NOTE = 'note'


class MissingField(str, Enum):
    """Why a follow-up is needed before a proposal can be presented."""

    DATE = 'date'
    AFFECTED_MEMBER = 'affected_member'
    AMBIGUOUS_MEMBER = 'ambiguous_member'


_DATE = (MissingField.DATE,)
_DATE_AND_MEMBER = (MissingField.DATE, MissingField.AFFECTED_MEMBER)


class SchoolItemKind(str, Enum):
    """Recognized school item kinds.

    Each kind fixes its entry type, the fields a proposal requires, and a
    Polish label for display. Add a kind by adding one member here.
    """

    HOMEWORK = ('homework', 'zadanie domowe', EntryType.CALENDAR_EVENT, _DATE_AND_MEMBER)
    CLASS_TEST = ('class_test', 'praca klasowa', EntryType.CALENDAR_EVENT, _DATE_AND_MEMBER)
    TEST = ('test', 'sprawdzian', EntryType.CALENDAR_EVENT, _DATE_AND_MEMBER)
    QUIZ = ('quiz', 'kartkówka', EntryType.CALENDAR_EVENT, _DATE_AND_MEMBER)
    LUCKY_NUMBER = ('lucky_number', 'szczęśliwy numerek', EntryType.NOTE, ())
    GRADE = ('grade', 'ocena', EntryType.NOTE, ())
    SUBSTITUTION = ('substitution', 'zastępstwo', EntryType.NOTE, _DATE)
    LATE_ARRIVAL = ('late_arrival', 'spóźnienie', EntryType.NOTE, ())
    ROOM_CHANGE = ('room_change', 'zmiana sali', EntryType.NOTE, _DATE)

    def __new__(
        cls,
        value: str,
        label: str,
        entry_type: EntryType,
        required_fields: Tuple[MissingField, ...],
    ):
        member = str.__new__(cls, value)
        member._value_ = value
        member.label = label
        member.entry_type = entry_type
        member.required_fields = required_fields
        return member


class UnavailableReason(str, Enum):
    """Safe outcome categories; never carry provider or family content."""

    DISABLED = 'disabled'
    TIMEOUT = 'timeout'
    RATE_LIMITED = 'rate_limited'
    CONNECTION_ERROR = 'connection_error'
    PROVIDER_ERROR = 'provider_error'
    REFUSED = 'refused'
    MALFORMED_OUTPUT = 'malformed_output'
    INCOMPLETE_OUTPUT = 'incomplete_output'
    EMPTY_CONTENT = 'empty_content'
    UNSUPPORTED_CONTENT = 'unsupported_content'
    UNKNOWN_MEMBER = 'unknown_member'


@dataclass(frozen=True)
class ClassificationProposal:
    """A complete, validated proposal awaiting parent review."""

    entry_type: EntryType
    content: str = field(repr=False)
    date: Optional[datetime.date] = None
    time: Optional[datetime.time] = None
    school_item: Optional[SchoolItemKind] = None
    member_name: Optional[str] = field(default=None, repr=False)
    kind: Literal['proposal'] = field(default='proposal', init=False)


@dataclass(frozen=True)
class ClassificationFollowUp:
    """A partial draft that needs more information from the parent."""

    missing_fields: Tuple[MissingField, ...]
    entry_type: EntryType
    content: str = field(repr=False)
    date: Optional[datetime.date] = None
    time: Optional[datetime.time] = None
    school_item: Optional[SchoolItemKind] = None
    member_name: Optional[str] = field(default=None, repr=False)
    kind: Literal['follow_up'] = field(default='follow_up', init=False)


@dataclass(frozen=True)
class ClassificationUnavailable:
    """A safe failure outcome carrying only a category code."""

    reason: UnavailableReason
    kind: Literal['unavailable'] = field(default='unavailable', init=False)


ClassificationResult = Union[
    ClassificationProposal,
    ClassificationFollowUp,
    ClassificationUnavailable,
]


class ClassificationError(Exception):
    """Base classification failure carrying only a safe category code.

    The constructor accepts nothing but an ``UnavailableReason`` so submitted
    text, provider payloads, or exception bodies cannot be attached.
    """

    def __init__(self, reason: UnavailableReason):
        if not isinstance(reason, UnavailableReason):
            raise TypeError('reason must be an UnavailableReason')
        self.reason = reason
        super().__init__(reason.value)

    def __repr__(self):
        return f'{type(self).__name__}({self.reason.value!r})'

    def to_result(self) -> ClassificationUnavailable:
        return ClassificationUnavailable(reason=self.reason)
