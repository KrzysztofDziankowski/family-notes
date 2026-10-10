<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Family Membership Management Implementation Plan

- **Plan**: `context/changes/family-membership-management/plan.md`
- **Scope**: Full plan
- **Reviewed phases**: 1, 2
- **Date**: 2026-10-10
- **Verdict**: NEEDS ATTENTION
- **Findings**: 0 critical, 1 warning, 2 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | PASS |
| Scope Discipline | PASS |
| Safety & Quality | WARNING |
| Architecture | PASS |
| Pattern Consistency | PASS |
| Success Criteria | WARNING |

## Findings

### F1 — Disabled user retained in-flight service authority

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Safety & Quality
- **Location**: `family_access/membership.py:103`
- **Detail**: `_relock_members()` refreshed the membership but authorized it without refreshing and locking the actor's `User`. An operator-disabled user could therefore finish an in-flight rename, role change, deactivation or reactivation.
- **Fix**: Lock and check the actor's current `User` after the family and membership locks, and cover disabled-user stale authority across mutation types.
  - Strength: Preserves the plan's lock-then-fresh-authority guarantee for both membership and account state.
  - Tradeoff: Adds one locked user lookup to each membership mutation.
  - Confidence: HIGH — the stale account state was reproducible from the service boundary.
  - Blind spot: Operator-side admin writes do not share the family lock, as already accepted by the plan.
- **Decision**: FIXED — fresh authorization now locks and checks the actor's User; stale disabled-user mutation tests pass.

### F2 — State gallery omitted visitor-matrix cases

- **Severity**: ℹ️ OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Success Criteria
- **Location**: `family_access/tests/test_membership_views.py:299`
- **Detail**: The gallery test covered anonymous, child, parent and DEBUG-off behavior, but not inactive-parent, no-membership and foreign-parent behavior named by the plan's route matrix.
- **Fix**: Extend the gallery authorization test with those visitor types and confirm an active parent from another family sees only their synthetic gallery.
- **Decision**: FIXED

### F3 — Reactivation omitted from explicit CSRF regression

- **Severity**: ℹ️ OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Success Criteria
- **Location**: `family_access/tests/test_membership_views.py:269`
- **Detail**: The explicit CSRF regression covered rename and deactivate POSTs but omitted reactivate, although the implementation correctly used Django CSRF middleware.
- **Fix**: Add the reactivation endpoint to the enforced-CSRF loop with an inactive target.
- **Decision**: FIXED

## Evidence

- Both review passes found the planned family scoping, lock/re-read sequence, token revocation, UI routes, Polish copy, accessibility cases and regression behavior implemented.
- Focused post-fix verification: `uv run python manage.py test family_access.tests.test_membership_services family_access.tests.test_membership_views family_access.tests.test_membership_accessibility` — 74 tests passed.
- The review inspected implementation commits `df6fb11`, `df712be` and Progress-record commit `05c335e`.
