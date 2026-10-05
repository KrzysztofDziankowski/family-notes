"""Semantic validation of provider-neutral classification output.

Structured parsing only proves shape. These rules decide whether backend
output may become an application proposal, needs a follow-up, or must be
rejected. Validation keeps nothing beyond the returned transient result and
raises only safe category codes.

"Supported by submitted information" is enforced conservatively:
content must be non-empty after trimming, the backend must assert that its
details are grounded in the instruction, and any member name must come from
the allow-list. Output that fails these checks is rejected rather than
repaired.
"""

from __future__ import annotations

from collections import Counter
from typing import Iterable, List, Optional

from .backends import BackendOutput, BackendRequest
from .types import (
    ClassificationError,
    ClassificationFollowUp,
    ClassificationProposal,
    ClassificationResult,
    EntryType,
    SCHOOL_SUBJECT_MAX_LENGTH,
    MissingField,
    UnavailableReason,
)


class ClassificationValidationError(ClassificationError):
    """Backend output violated a domain rule; carries a safe code only."""


def normalize_member_name(name: str) -> str:
    """Trim surrounding Unicode whitespace; spelling and case are preserved."""
    return name.strip()


def _name_counts(allowed_member_names: Iterable[str]) -> Counter:
    return Counter(normalize_member_name(name) for name in allowed_member_names)


def _clean_subject(value: Optional[str]) -> Optional[str]:
    """Trimmed subject; blank or over-long values are dropped to ``None``."""
    subject = (value or '').strip()
    if not subject or len(subject) > SCHOOL_SUBJECT_MAX_LENGTH:
        return None
    return subject


def validate_output(
    request: BackendRequest, output: BackendOutput, *, require_school_subject: bool
) -> ClassificationResult:
    """Return a proposal or follow-up, or raise ``ClassificationValidationError``.

    ``require_school_subject`` is true only where a parent can answer a
    follow-up; automated callers pass false so a missing subject never turns
    an otherwise complete proposal into a follow-up.
    """
    if output.entry_type is None:
        return _general_note(request)

    if not output.grounded:
        raise ClassificationValidationError(UnavailableReason.UNSUPPORTED_CONTENT)

    content = output.content.strip() if output.content else ''
    if not content:
        raise ClassificationValidationError(UnavailableReason.EMPTY_CONTENT)

    missing: List[MissingField] = []
    member_name: Optional[str] = None
    if output.member_ambiguous:
        # The local resolver found several family members fitting the
        # parent's words; never pick one, ask instead.
        missing.append(MissingField.AMBIGUOUS_MEMBER)
    elif output.member_name is not None:
        candidate = normalize_member_name(output.member_name)
        occurrences = (
            _name_counts(request.allowed_member_names)[candidate] if candidate else 0
        )
        if occurrences == 0:
            raise ClassificationValidationError(UnavailableReason.UNKNOWN_MEMBER)
        if occurrences > 1:
            missing.append(MissingField.AMBIGUOUS_MEMBER)
        else:
            member_name = candidate

    # A recognized school kind fixes the entry type and required fields,
    # whatever the backend said.
    kind = output.school_item
    entry_type = kind.entry_type if kind is not None else output.entry_type
    required = set(kind.required_fields) if kind is not None else set()
    if entry_type == EntryType.CALENDAR_EVENT:
        required.add(MissingField.DATE)
    if MissingField.DATE in required and output.date is None:
        missing.append(MissingField.DATE)
    if MissingField.AFFECTED_MEMBER in required and (
        output.member_name is None or output.member_ambiguous
    ):
        missing.append(MissingField.AFFECTED_MEMBER)
    school_subject = _clean_subject(output.school_subject)
    if (
        require_school_subject
        and MissingField.SCHOOL_SUBJECT in required
        and school_subject is None
    ):
        missing.append(MissingField.SCHOOL_SUBJECT)

    values = dict(
        entry_type=entry_type,
        content=content,
        date=output.date,
        time=output.time,
        school_item=output.school_item,
        member_name=member_name,
        school_subject=school_subject,
    )
    if missing:
        return ClassificationFollowUp(missing_fields=tuple(missing), **values)
    return ClassificationProposal(**values)


def classify_output(
    request: BackendRequest, output: BackendOutput, *, require_school_subject: bool
) -> ClassificationResult:
    """Like ``validate_output`` but maps rule violations to an unavailable result."""
    try:
        return validate_output(
            request, output, require_school_subject=require_school_subject
        )
    except ClassificationValidationError as error:
        return error.to_result()


def _general_note(request: BackendRequest) -> ClassificationResult:
    content = request.submitted_text.strip()
    if not content:
        raise ClassificationValidationError(UnavailableReason.EMPTY_CONTENT)
    return ClassificationProposal(entry_type=EntryType.NOTE, content=content)
