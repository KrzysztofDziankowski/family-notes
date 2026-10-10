"""Deterministic matching of a spoken name to family-member candidates.

Parents often refer to family members by a short name or diminutive
("Hania") while the member is stored under a full name ("Hanna"). This module
maps a mention to the candidates it can refer to, using a curated,
code-maintained dictionary of common Polish diminutives.

Matching is two-tier:

1. Exact: a candidate whose full display name or given name (first word)
   equals the mention is decisive. Group matching is then skipped, so a name
   the parent typed exactly never becomes a question.
2. Group: only when nothing matches exactly, a candidate matches when its
   given name and the mention belong to the same dictionary group.

Names are compared after Unicode NFC normalization, trimming, whitespace
collapsing and casefolding. Diacritics stay significant ("Michal" is not
"Michał"). The module is pure: no database access and no logging, because
mentions and display names are family text.
"""

from __future__ import annotations

import unicodedata
from typing import Callable, FrozenSet, Mapping, Sequence, Tuple, TypeVar

T = TypeVar('T')

# Full given name -> its common short forms. Lowercase NFC, keys in code-point
# order (``sorted``).
# A short form may belong to several full names (e.g. "hania" is used for
# both Hanna and Anna); such a mention is ambiguous when both are present.
DIMINUTIVES: Mapping[str, FrozenSet[str]] = {
    'agnieszka': frozenset({'aga', 'agusia'}),
    'aleksander': frozenset({'alek', 'olek', 'oluś'}),
    'aleksandra': frozenset({'ola', 'olka', 'olcia', 'oleńka'}),
    'anna': frozenset({'ania', 'anka', 'anusia', 'hania'}),
    'antoni': frozenset({'antek', 'antoś', 'tosiek'}),
    'antonina': frozenset({'tosia', 'tonia'}),
    'barbara': frozenset({'basia', 'baśka'}),
    'bartłomiej': frozenset({'bartek', 'bartuś'}),
    'dominika': frozenset({'domi', 'domka'}),
    'elżbieta': frozenset({'ela', 'elka', 'elunia'}),
    'filip': frozenset({'filipek'}),
    'franciszek': frozenset({'franek', 'franio', 'franuś'}),
    'gabriela': frozenset({'gabi', 'gabrysia'}),
    'hanna': frozenset({'hania', 'hanka', 'hanusia'}),
    'ignacy': frozenset({'igi', 'ignaś'}),
    'jakub': frozenset({'kuba', 'kubuś'}),
    'jan': frozenset({'janek', 'jasiek', 'jaś'}),
    'joanna': frozenset({'asia', 'joasia'}),
    'julia': frozenset({'jula', 'julka'}),
    'kacper': frozenset({'kacperek'}),
    'katarzyna': frozenset({'kasia', 'kaśka'}),
    'krzysztof': frozenset({'krzyś', 'krzysiek'}),
    'magdalena': frozenset({'madzia', 'magda'}),
    'maria': frozenset({'marysia', 'maryśka'}),
    'mateusz': frozenset({'mateuszek', 'mati'}),
    'małgorzata': frozenset({'gosia', 'małgosia'}),
    'michał': frozenset({'michałek', 'michaś'}),
    'mikołaj': frozenset({'mikołajek', 'miki'}),
    'natalia': frozenset({'nata', 'natka'}),
    'piotr': frozenset({'piotrek', 'piotruś'}),
    'stanisław': frozenset({'staś', 'stasiek'}),
    'szymon': frozenset({'szymek'}),
    'tomasz': frozenset({'tomek'}),
    'tymoteusz': frozenset({'tymek', 'tymuś'}),
    'wiktoria': frozenset({'wika', 'wiki'}),
    'wojciech': frozenset({'wojtek', 'wojtuś'}),
    'zofia': frozenset({'zosia', 'zośka'}),
    'zuzanna': frozenset({'zuza', 'zuzia'}),
}


def normalize_name(name: str) -> str:
    """NFC, trimmed, whitespace-collapsed and casefolded; diacritics kept."""
    return ' '.join(unicodedata.normalize('NFC', name or '').casefold().split())


def _given_name(normalized: str) -> str:
    return normalized.split(' ', 1)[0] if normalized else ''


def name_group(name: str) -> FrozenSet[str]:
    """The normalized name plus every full name it is, or is a short form of."""
    normalized = normalize_name(name)
    if not normalized:
        return frozenset()
    group = {normalized}
    for full_name, short_forms in DIMINUTIVES.items():
        if normalized == full_name or normalized in short_forms:
            group.add(full_name)
    return frozenset(group)


def match_mention(
    mention: str,
    candidates: Sequence[T],
    *,
    display_name: Callable[[T], str],
) -> Tuple[T, ...]:
    """Candidates ``mention`` can refer to, in candidate order.

    An exact full-name or given-name match is decisive; dictionary groups are
    consulted only when no candidate matches exactly. A blank mention matches
    nothing.
    """
    normalized = normalize_name(mention)
    if not normalized:
        return ()

    names = [normalize_name(display_name(candidate)) for candidate in candidates]
    exact = tuple(
        candidate
        for candidate, name in zip(candidates, names)
        if name and (name == normalized or _given_name(name) == normalized)
    )
    if exact:
        return exact

    mention_group = name_group(normalized)
    return tuple(
        candidate
        for candidate, name in zip(candidates, names)
        if name and name_group(_given_name(name)) & mention_group
    )
