"""Family-scoped authorization helpers.

The family of a web request comes only from ``family_access.context``; these
helpers take that membership and never derive a family from a ``User``.
"""

from .models import FamilyMember


def is_parent(membership):
    return bool(
        membership
        and membership.is_active
        and membership.family.is_active
        and membership.role == FamilyMember.Role.PARENT
    )


def scope_queryset_to_family(queryset, membership, family_field='family'):
    if membership is None or not membership.is_active or not membership.family.is_active:
        return queryset.none()
    return queryset.filter(**{family_field: membership.family})


def can_read_assigned_child(membership, assigned_child):
    if (
        membership is None
        or assigned_child is None
        or not membership.is_active
        or not membership.family.is_active
        or not assigned_child.is_active
        or assigned_child.role != FamilyMember.Role.CHILD
        or membership.family_id != assigned_child.family_id
    ):
        return False

    return is_parent(membership) or membership.pk == assigned_child.pk
