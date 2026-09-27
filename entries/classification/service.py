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
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Optional, Sequence

from django.core.exceptions import PermissionDenied
from django.views.decorators.debug import sensitive_variables

from family_access.access import get_active_membership, is_parent, scope_queryset_to_family
from family_access.models import FamilyMember

from .backends import BackendRequest, ClassificationBackend
from .types import (
    ClassificationError,
    ClassificationResult,
    ClassificationUnavailable,
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
        owns_backend = backend is None
        if owns_backend:
            # Imported lazily so the provider SDK is only touched once an
            # authorized parent actually needs it.
            from .openai_backend import build_openai_backend

            backend = build_openai_backend()
        try:
            output = backend.classify(request)
        finally:
            if owns_backend:
                backend.close()
    except ClassificationError as error:
        return ParentClassification(result=error.to_result())

    result = classify_output(request, output)
    return _resolve_member(result, candidates)


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
