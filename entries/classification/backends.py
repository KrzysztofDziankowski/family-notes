"""Injectable classification backend seam.

A backend receives the minimum application request and returns
provider-neutral structured data. Provider adapters translate their own
response types into ``BackendOutput`` and raise ``ClassificationBackendError``
for failures; neither may retain raw provider payloads.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import FrozenSet, Optional, Protocol, Tuple, runtime_checkable

from .types import ClassificationError, EntryType, ProposalValues, SchoolItemKind

# Fields a free-text correction may change, as named in ``changed_fields``.
CORRECTABLE_FIELDS = (
    'entry_type',
    'content',
    'school_item',
    'school_subject',
    'date',
    'time',
    'member_name',
)


@dataclass(frozen=True)
class BackendRequest:
    """Everything a backend may see: text, allowed names, date, and locale.

    ``follow_up_question`` and ``follow_up_answer`` are set only when the
    parent answers a follow-up question about a draft; the answer supplements
    ``submitted_text``. Both are family text and stay out of ``repr``.

    ``current_proposal`` and ``correction_text`` are set only for a free-text
    correction of the proposal on screen. ``submitted_text`` then holds the
    correction too, because it is the text a returned date must be grounded
    in; the original instruction is never sent.

    ``requester_name`` is the requesting parent's display name. It is set only
    for a parent's own capture and that parent's free-text correction (never
    for follow-up answers or automated classification), and it is always one
    of ``allowed_member_names``; it lets a self-reference („dla mnie”) be
    mapped to the parent. It is family data and stays out of ``repr``.
    """

    submitted_text: str = field(repr=False)
    allowed_member_names: Tuple[str, ...] = field(repr=False)
    reference_date: datetime.date
    locale: str
    follow_up_question: Optional[str] = field(default=None, repr=False)
    follow_up_answer: Optional[str] = field(default=None, repr=False)
    current_proposal: Optional[ProposalValues] = field(default=None, repr=False)
    correction_text: Optional[str] = field(default=None, repr=False)
    requester_name: Optional[str] = field(default=None, repr=False)

    def __post_init__(self):
        # Normalize to an immutable tuple so callers cannot mutate it later.
        object.__setattr__(
            self, 'allowed_member_names', tuple(self.allowed_member_names)
        )


@dataclass(frozen=True)
class BackendOutput:
    """Provider-neutral structured classification data before validation.

    ``entry_type`` is ``None`` when the backend recognized no entry type.
    ``grounded`` is the backend's assertion that every returned detail is
    supported by the submitted instruction; ``False`` is never trusted.

    ``member_mention`` is the person as the parent named them (nominative,
    possibly a diminutive). It is transient family text used only to pick
    among the allow-listed candidates locally; it is never logged or stored.
    ``member_ambiguous`` is set only by the local resolver, never by a
    provider adapter, when the mention fits several candidates.

    ``changed_fields`` is set only for a correction: the names of the fields
    (from ``CORRECTABLE_FIELDS``) the correction changes. ``None`` means the
    output is not a correction.
    """

    entry_type: Optional[EntryType]
    content: str = field(repr=False)
    grounded: bool
    date: Optional[datetime.date] = None
    time: Optional[datetime.time] = None
    school_item: Optional[SchoolItemKind] = None
    member_name: Optional[str] = field(default=None, repr=False)
    school_subject: Optional[str] = field(default=None, repr=False)
    member_mention: Optional[str] = field(default=None, repr=False)
    member_ambiguous: bool = False
    changed_fields: Optional[FrozenSet[str]] = None


class ClassificationBackendError(ClassificationError):
    """Normalized backend failure with a safe category code only."""


@runtime_checkable
class ClassificationBackend(Protocol):
    def classify(self, request: BackendRequest) -> BackendOutput:
        """Return structured data or raise ``ClassificationBackendError``."""
        ...


@runtime_checkable
class MultiEntryClassificationBackend(Protocol):
    """A backend that can split one instruction into several entries.

    Optional: the parent batch service treats a backend without
    ``classify_many`` as returning a one-item batch from ``classify``.
    """

    def classify_many(self, request: BackendRequest) -> Tuple[BackendOutput, ...]:
        """Return one output per requested entry, or raise ``ClassificationBackendError``."""
        ...
