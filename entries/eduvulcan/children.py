"""Family-scoped child snapshots and name matching for automated conversion."""

from __future__ import annotations

from typing import Iterable, Optional, Tuple

from family_access.models import Family, FamilyMember

from .text import normalize_text
from .types import ChildSnapshot


def snapshot_active_children(family: Family) -> Tuple[ChildSnapshot, ...]:
    """Return the active child memberships of an active ``family``, oldest first.

    Parents, inactive members, other families' members, and every member of an
    inactive family are excluded.
    """
    if not family.is_active:
        return ()
    members = (
        FamilyMember.objects.filter(
            family=family, role=FamilyMember.Role.CHILD, is_active=True
        )
        .order_by('pk')
        .values_list('pk', 'display_name')
    )
    return tuple(ChildSnapshot(pk=pk, display_name=name) for pk, name in members)


def normalize_child_name(name: str) -> str:
    """Normalize Unicode and whitespace and ignore case; diacritics still count."""
    return normalize_text(name).casefold()


def match_child(name: str, children: Iterable[ChildSnapshot]) -> Optional[ChildSnapshot]:
    """Resolve a name to one snapshot child; the newest membership wins ties.

    Returns ``None`` when no active child carries that name, so the caller
    produces an unassigned proposal.
    """
    wanted = normalize_child_name(name)
    if not wanted:
        return None
    matches = [child for child in children if normalize_child_name(child.display_name) == wanted]
    if not matches:
        return None
    return max(matches, key=lambda child: child.pk)
