"""Injectable classification backend seam.

A backend receives the minimum application request and returns
provider-neutral structured data. Provider adapters translate their own
response types into ``BackendOutput`` and raise ``ClassificationBackendError``
for failures; neither may retain raw provider payloads.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Optional, Protocol, Tuple, runtime_checkable

from .types import ClassificationError, EntryType, SchoolItemKind


@dataclass(frozen=True)
class BackendRequest:
    """Everything a backend may see: text, allowed names, date, and locale.

    ``follow_up_question`` and ``follow_up_answer`` are set only when the
    parent answers a follow-up question about a draft; the answer supplements
    ``submitted_text``. Both are family text and stay out of ``repr``.
    """

    submitted_text: str = field(repr=False)
    allowed_member_names: Tuple[str, ...] = field(repr=False)
    reference_date: datetime.date
    locale: str
    follow_up_question: Optional[str] = field(default=None, repr=False)
    follow_up_answer: Optional[str] = field(default=None, repr=False)

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
    """

    entry_type: Optional[EntryType]
    content: str = field(repr=False)
    grounded: bool
    date: Optional[datetime.date] = None
    time: Optional[datetime.time] = None
    school_item: Optional[SchoolItemKind] = None
    member_name: Optional[str] = field(default=None, repr=False)
    school_subject: Optional[str] = field(default=None, repr=False)


class ClassificationBackendError(ClassificationError):
    """Normalized backend failure with a safe category code only."""


@runtime_checkable
class ClassificationBackend(Protocol):
    def classify(self, request: BackendRequest) -> BackendOutput:
        """Return structured data or raise ``ClassificationBackendError``."""
        ...
