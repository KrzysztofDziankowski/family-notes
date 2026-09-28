"""Authorized parent classification service.

This is the single application entry point for classifying a parent's
instruction. It keeps authorization, candidate selection, provider
invocation, validation, and local member resolution in one auditable place:

1. Authorize: only an active parent in an active family may classify.
   Anyone else gets ``PermissionDenied`` before any backend is built or
   called.
2. Select candidates: load only active members of the parent's family.
3. Invoke: send the backend only the instruction, the candidates' display
   names, the reference date, and the locale. No database IDs are sent.
4. Validate and resolve: validate the output against the same allow-list,
   then map a returned name to exactly one loaded membership locally.
   Duplicate names become an ``AMBIGUOUS_MEMBER`` follow-up; unknown,
   inactive, and cross-family names become ``UNKNOWN_MEMBER``.

The service performs only reads and returns transient objects; it never
creates, updates, or deletes database rows.

``classify_for_family`` is the automated counterpart used for EduVulcan
notifications. It impersonates no user: the caller passes a snapshot of the
family's active children, and only their display names reach the backend.
Every outcome carries a usable proposal: a validated classification or a
general unassigned note. Transient provider failures are reported separately
so the caller can retry instead of saving the note straight away.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Sequence

from django.core.exceptions import PermissionDenied
from django.views.decorators.debug import sensitive_variables

from family_access.access import get_active_membership, is_parent, scope_queryset_to_family
from family_access.models import FamilyMember

from ..eduvulcan.children import match_child
from ..eduvulcan.types import ChildSnapshot
from .backends import BackendOutput, BackendRequest, ClassificationBackend
from .types import (
    ClassificationError,
    ClassificationProposal,
    ClassificationResult,
    ClassificationUnavailable,
    EntryType,
    UnavailableReason,
)
from .validation import classify_output, normalize_member_name

DEFAULT_LOCALE = 'pl-PL'
# Upper bound on text sent to the provider; bounds cost and latency.
MAX_SUBMITTED_TEXT_LENGTH = 2000


@dataclass(frozen=True)
class ParentClassification:
    """A transient classification result plus its locally resolved member.

    ``member`` is set only when ``result`` names exactly one active member of
    the parent's family; it is never derived from provider-supplied IDs.
    """

    result: ClassificationResult
    member: Optional[FamilyMember] = field(default=None, repr=False)


@sensitive_variables('submitted_text')
def classify_for_parent(
    user,
    submitted_text: str,
    *,
    reference_date: datetime.date,
    locale: str = DEFAULT_LOCALE,
    backend: Optional[ClassificationBackend] = None,
) -> ParentClassification:
    """Classify ``submitted_text`` on behalf of an authenticated active parent.

    Raises ``PermissionDenied`` for anonymous users, users without an active
    membership in an active family, and non-parent members; the backend is
    never built or called in those cases. When ``backend`` is omitted the
    configured OpenAI backend is built after authorization, and a disabled
    configuration yields an unavailable result. ``reference_date`` may be a
    ``datetime``; only its date part is used.
    """
    membership = get_active_membership(user)
    if not is_parent(membership):
        raise PermissionDenied('An active parent membership is required.')
    if len(submitted_text) > MAX_SUBMITTED_TEXT_LENGTH:
        return ParentClassification(
            result=ClassificationUnavailable(reason=UnavailableReason.INPUT_TOO_LONG)
        )

    candidates = _active_family_members(membership)
    if isinstance(reference_date, datetime.datetime):
        reference_date = reference_date.date()
    request = BackendRequest(
        submitted_text=submitted_text,
        allowed_member_names=tuple(member.display_name for member in candidates),
        reference_date=reference_date,
        locale=locale,
    )

    try:
        output = _invoke_backend(request, backend)
    except ClassificationError as error:
        return ParentClassification(result=error.to_result())

    result = classify_output(request, output)
    return _resolve_member(result, candidates)


def _invoke_backend(
    request: BackendRequest,
    backend: Optional[ClassificationBackend],
    *,
    max_retries: Optional[int] = None,
) -> BackendOutput:
    """Call ``backend``, or build, call, and close the configured one.

    Raises ``ClassificationError`` subclasses carrying safe codes only.
    ``max_retries`` applies only to a backend built here.
    """
    owns_backend = backend is None
    if owns_backend:
        # Imported lazily so the provider SDK is only touched once an
        # authorized caller actually needs it.
        from .openai_backend import build_openai_backend

        backend = build_openai_backend(max_retries=max_retries)
    try:
        return backend.classify(request)
    finally:
        if owns_backend:
            backend.close()


def _active_family_members(membership: FamilyMember) -> Sequence[FamilyMember]:
    queryset = scope_queryset_to_family(
        FamilyMember.objects.filter(is_active=True), membership
    )
    return tuple(queryset.order_by('pk'))


def _resolve_member(
    result: ClassificationResult, candidates: Sequence[FamilyMember]
) -> ParentClassification:
    member_name = getattr(result, 'member_name', None)
    if member_name is None:
        return ParentClassification(result=result)

    matches = [
        member
        for member in candidates
        if normalize_member_name(member.display_name) == member_name
    ]
    if len(matches) != 1:
        # Validation already guarantees a unique allow-listed name; this is a
        # defensive fail-closed guard, never a pick by database order.
        return ParentClassification(
            result=ClassificationUnavailable(reason=UnavailableReason.UNKNOWN_MEMBER)
        )
    return ParentClassification(result=result, member=matches[0])


# --- Family-scoped classification for automated conversion (S-05) ------------

# Provider failures worth retrying later; every other failure is final.
TRANSIENT_UNAVAILABLE_REASONS = frozenset(
    {
        UnavailableReason.TIMEOUT,
        UnavailableReason.RATE_LIMITED,
        UnavailableReason.CONNECTION_ERROR,
        UnavailableReason.PROVIDER_ERROR,
    }
)


class FamilyOutcome(str, Enum):
    """How a family-scoped classification ended; safe to log."""

    CLASSIFIED = 'classified'
    GENERAL_NOTE = 'general_note'
    PROVIDER_UNAVAILABLE = 'provider_unavailable'


@dataclass(frozen=True)
class FamilyClassification:
    """A transient automated classification with a usable proposal.

    ``proposal`` is always complete: the validated classification when
    ``outcome`` is ``CLASSIFIED``, otherwise a general unassigned note holding
    the submitted text. ``member`` is set only for a classified proposal that
    names one snapshot child. ``reason`` carries the safe failure code, if any.
    With ``PROVIDER_UNAVAILABLE`` the caller may retry later or save the note.
    """

    outcome: FamilyOutcome
    proposal: ClassificationProposal
    member: Optional[ChildSnapshot] = None
    reason: Optional[UnavailableReason] = None

    @property
    def retryable(self) -> bool:
        return self.outcome == FamilyOutcome.PROVIDER_UNAVAILABLE


@sensitive_variables('submitted_text')
def classify_for_family(
    submitted_text: str,
    *,
    reference_date: datetime.date,
    children: Sequence[ChildSnapshot],
    locale: str = DEFAULT_LOCALE,
    backend: Optional[ClassificationBackend] = None,
    allow_backend_retry: bool = True,
) -> FamilyClassification:
    """Classify notification text for a family without acting as any user.

    ``children`` is the caller's snapshot of the family's active child
    memberships; only their display names are sent, never database IDs. A
    returned name resolves locally to the newest matching snapshot child.
    ``allow_backend_retry=False`` builds the configured backend without its
    own retry so the caller's lifecycle bounds total provider calls; it does
    not affect an injected ``backend``. Raises ``ValueError`` for blank text.
    """
    if not submitted_text or not submitted_text.strip():
        raise ValueError('submitted_text must not be blank')
    if isinstance(reference_date, datetime.datetime):
        reference_date = reference_date.date()

    def general_note(outcome=FamilyOutcome.GENERAL_NOTE, reason=None):
        return FamilyClassification(
            outcome=outcome,
            proposal=ClassificationProposal(
                entry_type=EntryType.NOTE, content=submitted_text.strip()
            ),
            reason=reason,
        )

    if len(submitted_text) > MAX_SUBMITTED_TEXT_LENGTH:
        return general_note(reason=UnavailableReason.INPUT_TOO_LONG)

    request = BackendRequest(
        submitted_text=submitted_text,
        allowed_member_names=_unique_names(children),
        reference_date=reference_date,
        locale=locale,
    )
    try:
        output = _invoke_backend(
            request, backend, max_retries=None if allow_backend_retry else 0
        )
    except ClassificationError as error:
        if error.reason in TRANSIENT_UNAVAILABLE_REASONS:
            return general_note(FamilyOutcome.PROVIDER_UNAVAILABLE, error.reason)
        return general_note(reason=error.reason)

    if output.entry_type is None:
        return general_note()
    result = classify_output(request, output)
    if isinstance(result, ClassificationUnavailable):
        return general_note(reason=result.reason)
    if not isinstance(result, ClassificationProposal):
        # A follow-up cannot be asked of automation: keep the text as a note.
        return general_note()

    member = None
    if result.member_name is not None:
        member = match_child(result.member_name, children)
        if member is None:
            return general_note(reason=UnavailableReason.UNKNOWN_MEMBER)
    return FamilyClassification(
        outcome=FamilyOutcome.CLASSIFIED, proposal=result, member=member
    )


def _unique_names(children: Sequence[ChildSnapshot]) -> tuple:
    """Distinct display names in snapshot order, so duplicates are not ambiguous."""
    names = {}
    for child in children:
        names.setdefault(normalize_member_name(child.display_name), None)
    return tuple(name for name in names if name)
