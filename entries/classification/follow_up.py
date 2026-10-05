"""Polish follow-up question asked about a classification draft.

The question is built deterministically from the draft's missing fields and
its content. It never contains member names from the allow-list; only the
draft's own title is quoted.
"""

from __future__ import annotations

from .types import ClassificationFollowUp, MissingField

# Each missing field maps to (opening with the subject, continuation without
# it). The continuation is used when several fields join into one question.
_PHRASES = {
    MissingField.DATE: ('Kiedy odbędzie się {subject}', 'kiedy odbędzie się'),
    MissingField.AFFECTED_MEMBER: ('Kogo dotyczy {subject}', 'kogo dotyczy'),
    MissingField.AMBIGUOUS_MEMBER: ('Której osoby dotyczy {subject}', 'której osoby dotyczy'),
    MissingField.SCHOOL_SUBJECT: ('Z jakiego przedmiotu jest {subject}', 'z jakiego przedmiotu'),
}
_FALLBACK_SUBJECT = 'ten wpis'
# Without a title, "Kiedy odbędzie się ten wpis?" reads oddly, so the date opening
# asks when the entry is planned instead.
_FALLBACK_DATE_OPENING = 'Na kiedy planowany jest {subject}'


def follow_up_question(draft: ClassificationFollowUp) -> str:
    """Return one Polish question covering every missing field of ``draft``.

    Fields are asked in a fixed order (date, member, then school subject), whatever order the
    draft lists them in. An ambiguous member supersedes an absent one, so the
    member is asked about once. Raises ``ValueError`` when nothing is missing.
    """
    missing = set(draft.missing_fields)
    if MissingField.AMBIGUOUS_MEMBER in missing:
        missing.discard(MissingField.AFFECTED_MEMBER)
    ordered = [field for field in _PHRASES if field in missing]
    if not ordered:
        raise ValueError('draft has no missing fields')

    content = (draft.content or '').strip()
    subject = f'„{content}”' if content else _FALLBACK_SUBJECT
    first, *rest = ordered
    opening = _PHRASES[first][0]
    if not content and first is MissingField.DATE:
        opening = _FALLBACK_DATE_OPENING
    parts = [opening.format(subject=subject)]
    parts.extend(_PHRASES[field][1] for field in rest)
    return ' i '.join(parts) + '?'
