"""Deterministic cleanup of an entry title after classification.

The model is told to return only the action as the entry text ("Zrobić
pranie"), because the assigned person and the date already have their own
fields. Models sometimes still echo them ("Kasia zrobić pranie w piątek"), so
the adapter runs this conservative guard over the returned text. It removes
only what was extracted elsewhere:

* a leading assignee reference (one of ``assignee_refs``, optionally followed
  by a comma or colon), and
* a trailing occurrence of the accepted date phrase (``date_phrase``).

Matching ignores case, surrounding whitespace and typographic quotes, and
always ends on a word boundary, so "Kasiaczek" is not "Kasia". Anything else
(other people, places, the school subject) stays. If stripping would leave
nothing, the text is returned as the model wrote it. The result starts with a
capital letter.

The module is pure: no database access and no logging, because titles, names
and date phrases are family text.
"""

from __future__ import annotations

import re
from typing import Optional, Sequence

# Straight and typographic quotes the model may wrap a name or phrase in.
_QUOTES = '"\'„”“«»‚‘’'
_QUOTE = f'[{re.escape(_QUOTES)}]*'
# A name may be followed by a comma or colon ("Kasia, zrobić pranie").
_ASSIGNEE_TAIL = r'(?:\s*[,:])?(?=\s|$)'
# Punctuation that may separate the action from a trailing date phrase.
_DATE_LEAD = r'(?:^|[\s,;:\-–—]+)'
_DATE_TAIL = r'[\s.,;:!?]*$'


def strip_extracted_phrases(
    content: str,
    *,
    assignee_refs: Sequence[str],
    date_phrase: Optional[str],
) -> str:
    """``content`` without a leading assignee reference or trailing date phrase.

    ``assignee_refs`` are alternative references to the assigned person (full
    display name, given name, the parent's mention); the longest one that
    matches at the start is removed. ``date_phrase`` is removed only from the
    end, and only when given (``None`` leaves dates in place).
    """
    if not content or not content.strip():
        return content

    stripped = _strip_leading_assignee(content, assignee_refs)
    stripped = _strip_trailing_date(stripped, date_phrase)
    if stripped is content:
        return _capitalize(content)
    cleaned = ' '.join(stripped.split())
    if not cleaned.strip(_QUOTES).strip():
        return _capitalize(content)
    return _capitalize(cleaned)


def _phrase_pattern(phrase: str) -> Optional[str]:
    words = phrase.strip().strip(_QUOTES).split()
    if not words:
        return None
    return _QUOTE + r'\s+'.join(re.escape(word) for word in words) + _QUOTE


def _strip_leading_assignee(content: str, assignee_refs: Sequence[str]) -> str:
    patterns = (_phrase_pattern(ref or '') for ref in assignee_refs)
    # Longest first, so "Hanna Kowalska" wins over "Hanna".
    for pattern in sorted(filter(None, patterns), key=len, reverse=True):
        match = re.match(r'\s*' + pattern + _ASSIGNEE_TAIL, content, re.IGNORECASE)
        if match:
            return content[match.end():]
    return content


def _strip_trailing_date(content: str, date_phrase: Optional[str]) -> str:
    pattern = _phrase_pattern(date_phrase or '')
    if pattern is None:
        return content
    match = re.search(_DATE_LEAD + pattern + _DATE_TAIL, content, re.IGNORECASE)
    if match:
        return content[: match.start()]
    return content


def _capitalize(text: str) -> str:
    for index, char in enumerate(text):
        if char.isspace() or char in _QUOTES:
            continue
        if char.islower():
            return text[:index] + char.upper() + text[index + 1:]
        return text
    return text
