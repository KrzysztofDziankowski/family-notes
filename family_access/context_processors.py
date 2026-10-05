"""Template context for the header family indicator (S-16)."""

from .context import peek_family_context


def family_context(request):
    """``current_family`` and ``family_count`` for ``base.html``.

    Uses only the non-raising ``peek_family_context``, so rendering any page
    (the chooser, sign-in and sign-out pages, error pages) never redirects.
    Anonymous visitors get nothing and cost no query.
    """
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return {}
    membership, count = peek_family_context(request)
    return {
        'current_family': membership.family if membership is not None else None,
        'family_count': count,
    }
