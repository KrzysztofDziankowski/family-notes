<!-- PLAN-REVIEW-REPORT -->
# Plan Review: Automation Token Access

- **Plan**: context/changes/automation-token-access/plan.md
- **Mode**: Deep (inline verification)
- **Date**: 2026-09-27
- **Verdict**: REVISE → SOUND after triage
- **Findings**: 0 critical, 3 warnings, 3 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| End-State Alignment | PASS |
| Lean Execution | PASS |
| Architectural Fitness | PASS |
| Blind Spots | WARNING |
| Plan Completeness | WARNING |

## Grounding
6/6 paths ✓, 2/2 symbols ✓ (is_parent, SuperuserAdminSite), brief↔plan ✓, Progress↔Phase ✓

## Findings

### F1 — Deactivated Django user keeps a working token

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Blind Spots
- **Location**: Phase 2 — Authentication helper
- **Detail**: `is_parent()` (family_access/access.py:24) checks membership, family and role but not `member.user.is_active`. The token path bypasses the login check that refuses inactive users.
- **Fix**: Also require `member.user.is_active`, select_related `member__user`, and add an inactive-user 401 case and test.
- **Decision**: FIXED

### F2 — Refreshing the show-once page silently issues a second token

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Blind Spots
- **Location**: Phase 1 — Admin issuing; Critical Implementation Details
- **Detail**: `response_add` renders the secret as the POST response, so a refresh re-submits the add form and issues another token.
- **Fix A**: PRG, with the secret in the server-side session and removed on first display
  - Strength: No duplicates.
  - Tradeoff: The secret briefly sits in `django_session`; depends on the session engine staying server-side.
  - Confidence: HIGH — standard PRG.
  - Blind spot: A future switch to signed_cookies sessions would leak it.
- **Fix B ⭐ Recommended**: Keep the rendered response; add a Polish no-refresh warning, and make duplicates visible and revocable
  - Strength: The secret exists only in one response.
  - Tradeoff: Accidental duplicates remain possible.
  - Confidence: HIGH — a duplicate is an unused, revocable token.
  - Blind spot: None significant.
- **Decision**: FIXED (Fix B)

### F3 — CSRF-exemption test can't fail

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 2 — Success Criteria 2.7
- **Detail**: Django's test Client skips CSRF by default, so the check passes even without `csrf_exempt`.
- **Fix**: Use `Client(enforce_csrf_checks=True)`.
- **Decision**: FIXED

### F4 — Can an admin reassign an existing token to another member?

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 1 — Admin change form
- **Detail**: Which fields are editable was ambiguous; an editable `member` would move a live secret to another parent.
- **Fix**: `member` read-only after creation; `name` and `expires_at` editable; test added (1.12).
- **Decision**: FIXED

### F5 — Expiry boundary undecided

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Blind Spots
- **Location**: Phase 1 — is_expired(now)
- **Detail**: Validity at `expires_at == now` was left to the implementation.
- **Fix**: Expired means `expires_at <= now`; boundary test added (1.13).
- **Decision**: FIXED

### F6 — Info-level rejection logs will never be emitted

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Blind Spots
- **Location**: Phase 2 — Authentication helper
- **Detail**: There's no LOGGING config, and the last-resort handler prints only WARNING and above.
- **Fix**: Log rejections at WARNING with the reason and prefix, never the secret; `assertLogs` test added (2.12).
- **Decision**: FIXED
