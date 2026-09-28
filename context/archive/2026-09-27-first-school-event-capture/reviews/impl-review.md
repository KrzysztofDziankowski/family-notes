<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: First School Event Capture

- **Plan**: context/changes/first-school-event-capture/plan.md
- **Scope**: Full plan
- **Reviewed phases**: 1, 2, 3, 4
- **Date**: 2026-09-28
- **Verdict**: NEEDS ATTENTION
- **Findings**: 0 critical, 3 warnings, 3 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | WARNING |
| Scope Discipline | PASS |
| Safety & Quality | WARNING |
| Architecture | PASS |
| Pattern Consistency | WARNING |
| Success Criteria | PASS |

Automated checks (2026-09-28): `manage.py test` gives 231 tests, OK (3 skipped). `manage.py check` is clean. `makemigrations --check --dry-run` reports no changes. `collectstatic --dry-run` finds `vendor/pico/pico.min.css` and `css/tokens.css`. The Phase 4 screenshots are committed.

## Findings

### F1 — `assigned_member` RESTRICT makes assigned users undeletable

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Safety & Quality
- **Location**: entries/models.py:33-40 (migration 0001)
- **Detail**: `User → FamilyMember` is CASCADE, and `Entry.assigned_member` is RESTRICT. Deleting a user whose membership is assigned on any entry raises `RestrictedError`, unless the same delete also cascades those entries (a whole Family delete). Because a parent assigns entries to a child, the child's account also becomes undeletable. The plan chose RESTRICT and tested it (criterion 1.7), but it doesn't record what this means for account removal. S-05 intake entries will make assigned rows common.
- **Fix A ⭐ Recommended**: Keep RESTRICT and record the rule "deactivate memberships, never delete users" in the plan and README runbook.
  - Strength: It needs no migration, it keeps entries attributable, and it matches the existing `is_active` flags that every access check already honours.
  - Tradeoff: An operator can't hard-delete a user from admin without first reassigning or deleting their entries.
  - Confidence: HIGH — the plan tests this behaviour deliberately (1.7).
  - Blind spot: A future GDPR-style "delete my account" request would need a custom flow.
- **Fix B**: Switch to `SET_NULL` with a new migration, so a deleted member's entries become "Cała rodzina".
  - Strength: User deletion always works.
  - Tradeoff: It silently reassigns entries to the whole family and needs migration 0003 on a shared table.
  - Confidence: MED — it changes behaviour that 1.7 pins, so tests need updating.
  - Blind spot: Whether "whole family" is the right fallback for a child's school events.
- **Decision**: FIXED via Fix A — README "Create the initial family" and plan addendum document deactivate-not-delete; RESTRICT kept

### F2 — tokens.css source line credits home.html for values it doesn't contain

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Adherence
- **Location**: family_notes/static/css/tokens.css:1
- **Detail**: The first line says all colours and the font stack come from the home.html placeholder. Only #f7f8fa, #20242a, #2f6f5e, #5d6670, #3d454d and the Inter stack are in that file. These values are new to this change, and nothing says where they came from:
  - surface #ffffff and border #d9dde2
  - accent-hover #255a4c and the accent-focus rgba
  - danger #b3261e and #fdecea
  - success-bg #e6f2ee
  - notice #fff6e0 and #d9a520

  The design-system contract (CLAUDE.md) requires a line naming the source of any value.
- **Fix**: Split the header comment: name home.html as the source of the values it actually holds, and mark the rest as "derived for this change (state colours)".
- **Decision**: FIXED — header comment split into values from home.html (verified) and values derived for this change

### F3 — "Wyloguj" is a GET link that opens allauth's unstyled confirmation page

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: family_notes/templates/base.html:19
- **Detail**: `ACCOUNT_LOGOUT_ON_GET` is not set (only `LOGOUT_REDIRECT_URL`, settings.py:234), so the nav link doesn't log the user out. It lands on allauth's logout confirmation page, which uses allauth's own layout rather than `base.html`. Logging out takes two taps, and the second screen is outside the design system. This is safe (no CSRF-able logout), but no test covers it.
- **Fix**: Replace the link with `<form method="post" action="{% url 'account_logout' %}">{% csrf_token %}<button>Wyloguj</button></form>` in the nav. Don't enable `ACCOUNT_LOGOUT_ON_GET`.
- **Decision**: FIXED — nav logout is a POST form (csrf_token, .fn-nav-form in tokens.css); test asserts the form and that POST signs out. Committed screenshots predate the nav change; re-screenshot at the next visual gate.

### F4 — Save service validates before the idempotency lookup

- **Severity**: 💬 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: entries/services.py:37-39
- **Detail**: `_validate()` runs before `_existing_for_key()`. A repeat confirm with an existing key, whose assigned member became inactive since the first save, gets `ValidationError` instead of the plan's `(existing, False)`. The view path is protected today, because the form's active-member queryset rejects the post first and keeps the same key. Service-level callers (S-02/S-05) wouldn't get that protection.
- **Fix**: Move the `_existing_for_key` pre-check above `_validate` and add a test.
- **Decision**: FIXED — idempotency lookup moved before _validate; test_repeat_key_returns_existing_entry_after_member_deactivated added

### F5 — EntryAdmin allows an assigned member from another family

- **Severity**: 💬 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: entries/admin.py (EntryAdmin)
- **Detail**: `family` and `assigned_member` can be edited independently in admin, and `Entry` has no `clean()`. Only the service enforces that both belong to the same family, so a superuser edit can create a cross-family entry.
- **Fix**: Add `Entry.clean()` that checks `assigned_member.family_id == family_id`.
- **Decision**: SKIPPED

### F6 — Capture view keeps the instruction in an unmasked local

- **Severity**: 💬 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: entries/views.py (capture, `text` local)
- **Detail**: `sensitive_post_parameters('text', 'content')` masks the POST data, but the local `text` variable would still appear in Django error reports and tracebacks. The plan didn't require this, but it matches the privacy intent of `sensitive_variables('content')` in the service.
- **Fix**: Add `@sensitive_variables('text')` to `capture`.
- **Decision**: SKIPPED
