"""Authorized parent classification service.

This is the single application entry point for classifying a parent's
instruction. It keeps authorization, candidate selection, provider
invocation, validation, and local member resolution in one auditable place:

1. Authorize: only an active parent in an active family may classify.
   Anyone else gets ``PermissionDenied`` before any backend is built or
   called.
2. Select candidates: load only active members of the parent's family.
3. Invoke: send the backend only the instruction, the candidates' display
   names, the reference date, and the locale. For the parent's own capture
   and correction, the requesting parent's display name (already one of the
   candidates) is sent too, so "dla mnie" can be mapped to them; follow-up
   answers and automated classification never send it. No database IDs are
   sent.
4. Validate and resolve: validate the output against the same allow-list,
   then map a returned name to exactly one loaded membership locally.
   Duplicate names become an ``AMBIGUOUS_MEMBER`` follow-up; unknown,
   inactive, and cross-family names become ``UNKNOWN_MEMBER``. Before
   validation, the person as the parent named them (``member_mention``, which
   may be a diminutive such as "Hania") is matched against the same
   candidates: one match selects that member, several matches become an
   ``AMBIGUOUS_MEMBER`` follow-up, and no match leaves the model's name to the
   allow-list.

The service performs only reads and returns transient objects; it never
creates, updates, or deletes database rows.

``classify_follow_up_answer`` handles the parent's answer to a follow-up
question under the same rules. Only the values the draft was missing are
taken from the answer's classification; everything else stays as drafted.

``classify_entries_for_parent`` is the capture entry point: one instruction
may request several entries („dziś, jutro i w poniedziałek”). Every output
goes through the same per-output pipeline as ``classify_for_parent``
(``_finish_parent_output``), so single and batch results cannot diverge.

``correct_proposal_for_parent`` applies a parent's free-text correction to
the proposal on screen under the same rules. Only the fields the backend
lists as changed are taken from its output; everything else, including the
parent's manual edits, is kept.

``classify_for_family`` is the automated counterpart used for EduVulcan
notifications. It impersonates no user: the caller passes a snapshot of the
family's active children, and only their display names reach the backend.
Every outcome carries a usable proposal: a validated classification or a
general unassigned note. Transient provider failures are reported separately
so the caller can retry instead of saving the note straight away.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import FrozenSet, Optional, Sequence, Tuple

from django.core.exceptions import PermissionDenied
from django.views.decorators.debug import sensitive_variables

from family_access.access import get_active_membership, is_parent, scope_queryset_to_family
from family_access.models import FamilyMember

from ..eduvulcan.children import match_child
from ..eduvulcan.types import ChildSnapshot
from .backends import (
    CORRECTABLE_FIELDS,
    BackendOutput,
    BackendRequest,
    ClassificationBackend,
    MultiEntryClassificationBackend,
)
from .follow_up import follow_up_question
from .names import match_mention
from .types import (
    ClassificationError,
    ClassificationFollowUp,
    ClassificationProposal,
    ClassificationResult,
    ClassificationUnavailable,
    EntryType,
    MissingField,
    ProposalValues,
    SCHOOL_SUBJECT_MAX_LENGTH,
    SchoolItemKind,
    UnavailableReason,
)
from .validation import classify_output, normalize_member_name

DEFAULT_LOCALE = 'pl-PL'
# Upper bound on text sent to the provider; bounds cost and latency.
MAX_SUBMITTED_TEXT_LENGTH = 2000
# Upper bound on a parent's answer to a follow-up question.
MAX_FOLLOW_UP_ANSWER_LENGTH = 500
# Upper bound on a free-text correction of the proposal on screen.
MAX_CORRECTION_LENGTH = 500
# Upper bound on the proposals one instruction may produce.
MAX_PROPOSALS_PER_INSTRUCTION = 10
_MEMBER_FIELDS = frozenset(
    {MissingField.AFFECTED_MEMBER, MissingField.AMBIGUOUS_MEMBER}
)


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
        requester_name=membership.display_name,
    )

    try:
        output = _invoke_backend(request, backend)
    except ClassificationError as error:
        return ParentClassification(result=error.to_result())

    return _finish_parent_output(request, output, candidates)


@dataclass(frozen=True)
class ParentBatchClassification:
    """The transient results for one instruction, in model order.

    A one-item batch is exactly what ``classify_for_parent`` returns for the
    same output, including unavailable results.
    """

    items: Tuple[ParentClassification, ...]

    @property
    def is_single(self) -> bool:
        return len(self.items) == 1

    @property
    def single(self) -> ParentClassification:
        if not self.is_single:
            raise ValueError('The batch holds several results.')
        return self.items[0]


def _single(result: ClassificationResult) -> ParentBatchClassification:
    return ParentBatchClassification(items=(ParentClassification(result=result),))


# An output without a type: validation turns it into the general note.
_NO_ENTRY_TYPE = BackendOutput(entry_type=None, content='', grounded=False)


@sensitive_variables('submitted_text')
def classify_entries_for_parent(
    user,
    submitted_text: str,
    *,
    reference_date: datetime.date,
    locale: str = DEFAULT_LOCALE,
    backend: Optional[ClassificationBackend] = None,
) -> ParentBatchClassification:
    """Classify an instruction that may request up to ten entries.

    Authorization, the length limit, candidates, and privacy match
    ``classify_for_parent``. The backend's ``classify_many`` is used when it
    has one; otherwise its single output is a one-item batch. More than
    ``MAX_PROPOSALS_PER_INSTRUCTION`` outputs give one ``TOO_MANY_ENTRIES``
    result. With several outputs, an output without a type or any output
    that fails validation turns the whole instruction into one general note
    holding the full text, so no proposal built from rejected output reaches
    the parent. No rows are written.
    """
    membership = get_active_membership(user)
    if not is_parent(membership):
        raise PermissionDenied('An active parent membership is required.')
    if len(submitted_text) > MAX_SUBMITTED_TEXT_LENGTH:
        return _single(ClassificationUnavailable(reason=UnavailableReason.INPUT_TOO_LONG))

    candidates = _active_family_members(membership)
    if isinstance(reference_date, datetime.datetime):
        reference_date = reference_date.date()
    request = BackendRequest(
        submitted_text=submitted_text,
        allowed_member_names=tuple(member.display_name for member in candidates),
        reference_date=reference_date,
        locale=locale,
        requester_name=membership.display_name,
    )

    try:
        outputs = _invoke_backend_many(request, backend)
    except ClassificationError as error:
        return _single(error.to_result())

    if not outputs:
        outputs = (_NO_ENTRY_TYPE,)
    if len(outputs) > MAX_PROPOSALS_PER_INSTRUCTION:
        return _single(ClassificationUnavailable(reason=UnavailableReason.TOO_MANY_ENTRIES))
    if len(outputs) == 1:
        return ParentBatchClassification(
            items=(_finish_parent_output(request, outputs[0], candidates),)
        )

    general_note = ParentBatchClassification(
        items=(_finish_parent_output(request, _NO_ENTRY_TYPE, candidates),)
    )
    if any(output.entry_type is None for output in outputs):
        return general_note
    items = tuple(_finish_parent_output(request, output, candidates) for output in outputs)
    if any(isinstance(item.result, ClassificationUnavailable) for item in items):
        return general_note
    return ParentBatchClassification(items=items)


def _finish_parent_output(
    request: BackendRequest, output: BackendOutput, candidates: Sequence[FamilyMember]
) -> ParentClassification:
    """The shared per-output parent pipeline.

    The parent's mention is matched first, then the output is validated (a
    school event needs its subject), then the member is resolved locally.
    Every parent path (single, batch, correction) ends here.
    """
    output = _apply_member_mention(output, candidates)
    result = classify_output(request, output, require_school_subject=True)
    return _resolve_member(result, candidates)


class CorrectionRejection(str, Enum):
    """Why a free-text correction was not applied; safe to log."""

    TOO_LONG = 'too_long'
    NOT_APPLIED = 'not_applied'
    SCHOOL_ITEM_MISMATCH = 'school_item_mismatch'


@dataclass(frozen=True)
class ProposalCorrection:
    """The outcome of a free-text correction of the proposal on screen.

    When ``applied`` is true, ``outcome`` is the corrected proposal or a
    follow-up with highlighted fields, and ``changed`` names the corrected
    fields. Otherwise ``outcome`` is ``None``, ``rejection`` says why, and the
    caller re-renders the values the parent already has. ``school_item`` is
    the merged school item that did not fit the merged entry type, set only
    for ``SCHOOL_ITEM_MISMATCH``.
    """

    outcome: Optional[ParentClassification]
    changed: FrozenSet[str] = frozenset()
    applied: bool = False
    rejection: Optional[CorrectionRejection] = None
    school_item: Optional[SchoolItemKind] = None


def _not_applied(
    rejection: CorrectionRejection, school_item: Optional[SchoolItemKind] = None
) -> ProposalCorrection:
    return ProposalCorrection(outcome=None, rejection=rejection, school_item=school_item)


@sensitive_variables('correction', 'current')
def correct_proposal_for_parent(
    user,
    current: ProposalValues,
    correction: str,
    *,
    reference_date: datetime.date,
    current_member: Optional[FamilyMember] = None,
    locale: str = DEFAULT_LOCALE,
    backend: Optional[ClassificationBackend] = None,
) -> ProposalCorrection:
    """Apply a free-text ``correction`` to the proposal on screen.

    Authorization, candidates, and privacy match ``classify_for_parent``. The
    backend is called once with the current values and the correction, never
    the original instruction. Only the fields it lists in ``changed_fields``
    are taken from its output; every other value stays exactly as ``current``
    (including the parent's manual edits). The merged values are validated
    once. A provider failure, ungrounded or empty output, an unknown person,
    or a school item that does not fit the merged entry type leaves the
    proposal unchanged (``applied=False``). ``current_member`` is trusted only
    when it is an active member of the parent's family. No rows are written.
    """
    membership = get_active_membership(user)
    if not is_parent(membership):
        raise PermissionDenied('An active parent membership is required.')
    if (
        len(correction) > MAX_CORRECTION_LENGTH
        or len(current.content) > MAX_SUBMITTED_TEXT_LENGTH
    ):
        return _not_applied(CorrectionRejection.TOO_LONG)

    candidates = _active_family_members(membership)
    if isinstance(reference_date, datetime.datetime):
        reference_date = reference_date.date()
    member_name = _trusted_member_name(current.member_name, current_member, candidates)
    current = replace(current, member_name=member_name)
    request = BackendRequest(
        submitted_text=correction,
        allowed_member_names=tuple(member.display_name for member in candidates),
        reference_date=reference_date,
        locale=locale,
        current_proposal=current,
        correction_text=correction,
        requester_name=membership.display_name,
    )

    try:
        output = _invoke_backend(request, backend)
    except ClassificationError:
        return _not_applied(CorrectionRejection.NOT_APPLIED)

    changed = frozenset(output.changed_fields or ()) & frozenset(CORRECTABLE_FIELDS)
    if not output.grounded or not changed:
        return _not_applied(CorrectionRejection.NOT_APPLIED)
    if 'entry_type' in changed and output.entry_type is None:
        return _not_applied(CorrectionRejection.NOT_APPLIED)

    merged = _merge_correction(current, output, changed)
    if merged.school_subject is not None and len(merged.school_subject) > SCHOOL_SUBJECT_MAX_LENGTH:
        return _not_applied(CorrectionRejection.NOT_APPLIED)
    if merged.school_item is not None and merged.school_item.entry_type != merged.entry_type:
        # Never drop a school item silently: the parent decides.
        return _not_applied(CorrectionRejection.SCHOOL_ITEM_MISMATCH, merged.school_item)
    if 'member_name' in changed:
        merged = _apply_member_mention(merged, candidates)
        if merged.member_mention and merged.member_name is None and not merged.member_ambiguous:
            # The parent named someone who is not in the family.
            return _not_applied(CorrectionRejection.NOT_APPLIED)

    outcome = _finish_parent_output(request, merged, candidates)
    if isinstance(outcome.result, ClassificationUnavailable):
        return _not_applied(CorrectionRejection.NOT_APPLIED)
    return ProposalCorrection(outcome=outcome, changed=changed, applied=True)


def _merge_correction(
    current: ProposalValues, output: BackendOutput, changed: FrozenSet[str]
) -> BackendOutput:
    """Current values, with only the ``changed`` fields taken from ``output``.

    The person (and the parent's mention of them) comes from the output only
    when the correction changes it, so a stray mention cannot reassign the
    current member.
    """

    def pick(name):
        return getattr(output, name) if name in changed else getattr(current, name)

    member_changed = 'member_name' in changed
    member_name = output.member_name if member_changed else current.member_name
    school_subject = pick('school_subject')
    if 'school_subject' in changed:
        school_subject = (school_subject or '').strip() or None
    return BackendOutput(
        entry_type=pick('entry_type'),
        content=pick('content'),
        grounded=output.grounded,
        date=pick('date'),
        time=pick('time'),
        school_item=pick('school_item'),
        member_name=normalize_member_name(member_name or '') or None,
        school_subject=school_subject,
        member_mention=output.member_mention if member_changed else None,
        member_ambiguous=False,
    )


@sensitive_variables('submitted_text', 'answer')
def classify_follow_up_answer(
    user,
    submitted_text: str,
    draft: ClassificationFollowUp,
    answer: str,
    *,
    reference_date: datetime.date,
    draft_member: Optional[FamilyMember] = None,
    locale: str = DEFAULT_LOCALE,
    backend: Optional[ClassificationBackend] = None,
) -> ParentClassification:
    """Fill the missing values of ``draft`` from the parent's ``answer``.

    Authorization, candidates, and privacy match ``classify_for_parent``. The
    backend is called once with the original instruction, the generated
    question, and the answer. Its output is merged into the draft before a
    single validation: only the fields listed in ``draft.missing_fields`` (and
    ``grounded``) come from the output, so a changed title, type, or echoed
    name cannot override or veto the draft. When the member was missing, the
    answer text itself is matched against the candidates first, so a parent
    answering "Hanna" is never asked again because the model echoed the
    instruction's "Hania"; only otherwise is the model's mention used.
    ``draft_member`` is the draft's
    resolved member; it is dropped unless it is an active member of the
    parent's family. Raises ``ValueError`` if ``draft`` has no missing fields.
    """
    membership = get_active_membership(user)
    if not is_parent(membership):
        raise PermissionDenied('An active parent membership is required.')
    if (
        len(submitted_text) > MAX_SUBMITTED_TEXT_LENGTH
        or len(answer) > MAX_FOLLOW_UP_ANSWER_LENGTH
    ):
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
        follow_up_question=follow_up_question(draft),
        follow_up_answer=answer,
    )

    try:
        output = _invoke_backend(request, backend)
    except ClassificationError as error:
        return ParentClassification(result=error.to_result())

    merged = _merge_answer(draft, _known_member_name(draft, draft_member, candidates), output)
    if set(draft.missing_fields) & _MEMBER_FIELDS:
        merged = _resolve_answer_member(merged, answer, candidates)
    result = classify_output(request, merged, require_school_subject=True)
    return _resolve_member(result, candidates)


def _known_member_name(
    draft: ClassificationFollowUp,
    draft_member: Optional[FamilyMember],
    candidates: Sequence[FamilyMember],
) -> Optional[str]:
    """The draft's member name, trusted only for a current family candidate."""
    return _trusted_member_name(draft.member_name, draft_member, candidates)


def _trusted_member_name(
    member_name: Optional[str],
    member: Optional[FamilyMember],
    candidates: Sequence[FamilyMember],
) -> Optional[str]:
    """``member``'s current display name if it is a family candidate.

    Without a resolved member the given name is kept (validation still checks
    it against the allow-list).
    """
    if member is None:
        return member_name
    for candidate in candidates:
        if candidate.pk == member.pk:
            return candidate.display_name
    # A stale or foreign member is dropped, never replaced by the given name.
    return None


def _merge_answer(
    draft: ClassificationFollowUp,
    member_name: Optional[str],
    output: BackendOutput,
) -> BackendOutput:
    """Draft values, with only the missing fields taken from ``output``."""
    missing = set(draft.missing_fields)
    return BackendOutput(
        entry_type=draft.entry_type,
        content=draft.content,
        grounded=output.grounded,
        date=output.date if MissingField.DATE in missing else draft.date,
        time=draft.time,
        school_item=draft.school_item,
        member_name=output.member_name if missing & _MEMBER_FIELDS else member_name,
        school_subject=(
            output.school_subject
            if MissingField.SCHOOL_SUBJECT in missing
            else draft.school_subject
        ),
        member_mention=output.member_mention if missing & _MEMBER_FIELDS else None,
    )


def _resolve_answer_member(
    output: BackendOutput, answer: str, candidates: Sequence[FamilyMember]
) -> BackendOutput:
    """The member named by the answer itself, else the model's mention."""
    matches = _match_candidates(answer, candidates)
    if len(matches) == 1:
        return replace(
            output,
            member_name=matches[0].display_name,
            member_mention=None,
            member_ambiguous=False,
        )
    return _apply_member_mention(output, candidates)


def _apply_member_mention(
    output: BackendOutput, candidates: Sequence[FamilyMember]
) -> BackendOutput:
    """Resolve the parent's mention against the active family candidates.

    The parent's words win over the model's ``member_name``: a mention that
    fits exactly one candidate selects that candidate, one that fits several
    clears the name and flags ambiguity for validation, and one that fits
    nobody leaves ``output`` to the exact allow-list check. Only family
    candidates can ever be selected.
    """
    if not output.member_mention:
        return output
    matches = _match_candidates(output.member_mention, candidates)
    if len(matches) == 1:
        return replace(output, member_name=matches[0].display_name)
    if len(matches) > 1:
        return replace(output, member_name=None, member_ambiguous=True)
    return output


def _match_candidates(
    mention: str, candidates: Sequence[FamilyMember]
) -> Sequence[FamilyMember]:
    return match_mention(
        mention.strip(), candidates, display_name=lambda member: member.display_name
    )


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


def _invoke_backend_many(
    request: BackendRequest, backend: Optional[ClassificationBackend]
) -> Tuple[BackendOutput, ...]:
    """Like ``_invoke_backend``, but returns every entry the backend splits out."""
    owns_backend = backend is None
    if owns_backend:
        from .openai_backend import build_openai_backend

        backend = build_openai_backend()
    try:
        if isinstance(backend, MultiEntryClassificationBackend):
            return tuple(backend.classify_many(request))
        return (backend.classify(request),)
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
    # Automation cannot answer a question, so a missing subject is never asked.
    result = classify_output(request, output, require_school_subject=False)
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
