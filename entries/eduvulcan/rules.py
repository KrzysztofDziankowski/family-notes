"""Fixed school rules: turn a known EduVulcan notification into entry proposals.

``propose_entries`` never calls a provider. It returns an ordered tuple of
proposals with stable output indexes ``0..n-1``, or ``None`` when no rule can
interpret the notification, so the caller falls back to classification.

Category mapping (PRD Business Logic):

- "Sprawdzian", "Kartkówka", "Praca klasowa", "Zadanie domowe": a dated
  calendar event for the named child.
- "Zmiana planu dla <child>": one dated child note per valid change; any
  unparsed remainder becomes one unassigned family note after them.
- "Ocena", "Szczęśliwy numerek", "Frekwencja": a child note.
- "Nowa wiadomość": an unassigned family note dated from the message.

A child name that matches no active child yields an unassigned proposal that
keeps the name in its text. Entry text is Polish because parents read it.
"""

from __future__ import annotations

import datetime
import re
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from django.utils import timezone

from ..classification.types import EntryType, MissingField, SchoolItemKind
from .children import match_child
from .text import normalize_text, resolve_yearless_date
from .types import ChildSnapshot, EntryProposal, OutputKind

Proposals = Tuple[EntryProposal, ...]

_DATE = r'(?P<day>\d{1,2}) (?P<month>[^\W\d_]+)'

_CALENDAR_MESSAGE = re.compile(
    rf'^(?:zadanie domowe )?{_DATE}, (?P<subject>.+?)(?: \([^()]*\))?, (?P<child>[^,]+)$',
    re.IGNORECASE,
)
_GRADE_MESSAGE = re.compile(
    r'^nowa ocena: (?P<grade>[^,]+), (?P<subject>.+), (?P<child>[^,]+)$', re.IGNORECASE
)
_LUCKY_NUMBER_MESSAGE = re.compile(
    rf'^w dniu {_DATE} szczęśliwy numer to: (?P<number>\d+), (?P<child>[^,]+)$',
    re.IGNORECASE,
)
_ATTENDANCE_MESSAGE = re.compile(
    rf'^(?P<event>.+?), (?P<child>[^,]+), w dniu {_DATE}$', re.IGNORECASE
)
_TEACHER_MESSAGE = re.compile(rf'^{_DATE} od (?P<sender>.+?): (?P<topic>.+)$', re.IGNORECASE)
_TIMETABLE_TITLE = re.compile(r'^zmiana planu dla (?P<child>.+)$', re.IGNORECASE)

# Each timetable change starts with one of these phrases followed by its date.
_CHANGE_START = re.compile(
    r'(?:zastępstwo|zmieniono salę|nieobecność nauczyciela(?: wspomagającego)?) w dniu ',
    re.IGNORECASE,
)
_CHANGE = re.compile(
    rf'^(?P<change>zastępstwo|zmieniono salę|nieobecność nauczyciela wspomagającego'
    rf'|nieobecność nauczyciela) w dniu {_DATE}'
    rf'(?: na lekcji (?P<subject>[^,]+))?, (?P<teacher>.+)$',
    re.IGNORECASE,
)

_CALENDAR_CATEGORIES = {
    'sprawdzian': ('Sprawdzian', SchoolItemKind.TEST),
    'kartkówka': ('Kartkówka', SchoolItemKind.QUIZ),
    'praca klasowa': ('Praca klasowa', SchoolItemKind.CLASS_TEST),
    'zadanie domowe': ('Zadanie domowe', SchoolItemKind.HOMEWORK),
}

# change phrase -> (entry label, school item kind, lesson subject required).
# A teacher absence has no matching school item kind, so it stays a plain note.
_CHANGE_KINDS = {
    'zastępstwo': ('Zastępstwo', SchoolItemKind.SUBSTITUTION, True),
    'zmieniono salę': ('Zmiana sali', SchoolItemKind.ROOM_CHANGE, True),
    'nieobecność nauczyciela': ('Nieobecność nauczyciela', None, False),
    'nieobecność nauczyciela wspomagającego': (
        'Nieobecność nauczyciela wspomagającego',
        None,
        False,
    ),
}


class _Builder:
    """Collects proposals and assigns consecutive output indexes."""

    def __init__(self, children: Sequence[ChildSnapshot]):
        self.children = tuple(children)
        self.proposals: List[EntryProposal] = []

    def add(self, *, kind=OutputKind.RULE, entry_type, content, date=None,
            school_item=None, member=None):
        self.proposals.append(
            EntryProposal(
                output_index=len(self.proposals),
                kind=kind,
                entry_type=entry_type,
                content=content,
                date=date,
                school_item=school_item,
                member=member,
            )
        )

    def add_for_child(self, child_name, *, entry_type, content, date=None, school_item=None):
        """Add a child-bound proposal, or an unassigned one naming the child."""
        member = match_child(child_name, self.children)
        if member is None:
            content = f'{content} — {normalize_text(child_name)}'
            if school_item is not None and MissingField.AFFECTED_MEMBER in school_item.required_fields:
                # An unassigned entry cannot carry a kind that requires a member.
                school_item = None
        self.add(
            entry_type=entry_type,
            content=content,
            date=date,
            school_item=school_item,
            member=member,
        )

    def result(self) -> Optional[Proposals]:
        return tuple(self.proposals) or None


def reference_date_for(captured_at) -> datetime.date:
    """The local capture day used to infer years; accepts a date or datetime."""
    if isinstance(captured_at, datetime.datetime):
        if timezone.is_aware(captured_at):
            return timezone.localdate(captured_at)
        return captured_at.date()
    return captured_at


def propose_entries(
    title: str,
    message: str,
    *,
    captured_at,
    children: Sequence[ChildSnapshot],
) -> Optional[Proposals]:
    """Return ordered rule-based proposals, or ``None`` when no rule applies."""
    title = normalize_text(title)
    message = normalize_text(message)
    if not title or not message:
        return None
    reference = reference_date_for(captured_at)
    builder = _Builder(children)
    key = title.casefold()

    handler = _HANDLERS.get(key)
    if handler is not None:
        return handler(key, message, reference, builder)
    timetable = _TIMETABLE_TITLE.match(title)
    if timetable is not None:
        return _timetable(title, timetable.group('child'), message, reference, builder)
    return None


def _date_from(match: re.Match, reference: datetime.date) -> Optional[datetime.date]:
    return resolve_yearless_date(int(match.group('day')), match.group('month'), reference)


def _calendar(key, message, reference, builder) -> Optional[Proposals]:
    label, school_item = _CALENDAR_CATEGORIES[key]
    match = _CALENDAR_MESSAGE.match(message)
    if match is None:
        return None
    date = _date_from(match, reference)
    if date is None:
        return None
    builder.add_for_child(
        match.group('child'),
        entry_type=EntryType.CALENDAR_EVENT,
        content=f"{label}: {match.group('subject')}",
        date=date,
        school_item=school_item,
    )
    return builder.result()


def _grade(key, message, reference, builder) -> Optional[Proposals]:
    match = _GRADE_MESSAGE.match(message)
    if match is None:
        return None
    # Grades stay undated; lists place them by their creation day.
    builder.add_for_child(
        match.group('child'),
        entry_type=EntryType.NOTE,
        content=f"Ocena: {match.group('grade')}, {match.group('subject')}",
        school_item=SchoolItemKind.GRADE,
    )
    return builder.result()


def _lucky_number(key, message, reference, builder) -> Optional[Proposals]:
    match = _LUCKY_NUMBER_MESSAGE.match(message)
    if match is None:
        return None
    date = _date_from(match, reference)
    if date is None:
        return None
    builder.add_for_child(
        match.group('child'),
        entry_type=EntryType.NOTE,
        content=f"Szczęśliwy numerek: {match.group('number')}",
        date=date,
        school_item=SchoolItemKind.LUCKY_NUMBER,
    )
    return builder.result()


def _attendance(key, message, reference, builder) -> Optional[Proposals]:
    match = _ATTENDANCE_MESSAGE.match(message)
    if match is None:
        return None
    date = _date_from(match, reference)
    if date is None:
        return None
    event = match.group('event')
    builder.add_for_child(
        match.group('child'),
        entry_type=EntryType.NOTE,
        content=event,
        date=date,
        school_item=(
            SchoolItemKind.LATE_ARRIVAL if event.casefold().startswith('spóźnienie') else None
        ),
    )
    return builder.result()


def _teacher_message(key, message, reference, builder) -> Optional[Proposals]:
    match = _TEACHER_MESSAGE.match(message)
    if match is None:
        return None
    date = _date_from(match, reference)
    if date is None:
        return None
    builder.add(
        entry_type=EntryType.NOTE,
        content=f"Wiadomość od {match.group('sender')}: {match.group('topic')}",
        date=date,
    )
    return builder.result()


def _split_changes(message: str) -> List[str]:
    """Split a timetable message at each change phrase; a leading prefix stays."""
    starts = [match.start() for match in _CHANGE_START.finditer(message)]
    if not starts or starts[0] != 0:
        starts.insert(0, 0)
    bounds = starts + [len(message)]
    return [
        message[begin:end].strip()
        for begin, end in zip(bounds, bounds[1:])
        if message[begin:end].strip()
    ]


def _timetable(title, child_name, message, reference, builder) -> Optional[Proposals]:
    unparsed = []
    for segment in _split_changes(message):
        match = _CHANGE.match(segment)
        date = _date_from(match, reference) if match is not None else None
        if date is None:
            unparsed.append(segment)
            continue
        label, school_item, needs_subject = _CHANGE_KINDS[match.group('change').casefold()]
        subject = match.group('subject')
        if needs_subject and subject is None:
            unparsed.append(segment)
            continue
        details = f"{subject}, {match.group('teacher')}" if subject else match.group('teacher')
        builder.add_for_child(
            child_name,
            entry_type=EntryType.NOTE,
            content=f'{label}: {details}',
            date=date,
            school_item=school_item,
        )
    if not builder.proposals:
        return None
    if unparsed:
        builder.add(
            kind=OutputKind.RULE_REMAINDER,
            entry_type=EntryType.NOTE,
            content=f"{title}: {' '.join(unparsed)}",
        )
    return builder.result()


_HANDLERS: Dict[str, Callable[..., Optional[Proposals]]] = {
    **{key: _calendar for key in _CALENDAR_CATEGORIES},
    'ocena': _grade,
    'szczęśliwy numerek': _lucky_number,
    'frekwencja': _attendance,
    'nowa wiadomość': _teacher_message,
}


def general_note_text(title: str, message: str) -> str:
    """Normalized notification text for classification and the general note."""
    title = normalize_text(title)
    message = normalize_text(message)
    return f'{title}: {message}' if title and message else title or message


def general_note_proposal(title: str, message: str, *, output_index: int = 0) -> EntryProposal:
    """The last-resort unassigned family note carrying the notification text."""
    return EntryProposal(
        output_index=output_index,
        kind=OutputKind.GENERAL_NOTE,
        entry_type=EntryType.NOTE,
        content=general_note_text(title, message),
    )
