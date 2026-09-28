<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Automation Token Access

- **Plan**: context/changes/automation-token-access/plan.md
- **Scope**: Full plan
- **Reviewed phases**: 1, 2, 3
- **Date**: 2026-09-28
- **Verdict**: NEEDS ATTENTION
- **Findings**: 0 critical, 3 warnings, 5 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | WARNING |
| Scope Discipline | PASS |
| Safety & Quality | WARNING |
| Architecture | PASS |
| Pattern Consistency | WARNING |
| Success Criteria | WARNING |

Automated checks (2026-09-28): `manage.py test` gives 231 tests, OK (3 skipped). `manage.py check` is clean. `makemigrations --check --dry-run` reports no changes.

## Findings

### F1 — Impossible ISO date returns 500 instead of 400

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: entries/api_views.py:49
- **Detail**: `parse_datetime('2026-02-30T10:00:00')` raises `ValueError: day is out of range for month` (verified). `_parse_payload` only catches errors from `json.loads`, so a well-formed but impossible `captured_at_iso` escapes the view and returns a 500. The plan promises `400 invalid_payload` for an unparseable `captured_at_iso`.
- **Fix**: Wrap `parse_datetime` in `try/except ValueError` so it returns `None`. Add tests for `2026-02-30T…` and `2026-13-01T…`.
- **Decision**: FIXED — try/except ValueError around parse_datetime; impossible day/month tests added

### F2 — NUL characters in payload crash intake on PostgreSQL

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: entries/api_views.py:42-47
- **Detail**: Intake validates fields with `isinstance(str)` and `.strip()` only. It bypasses Django forms, so `ProhibitNullCharactersValidator` never runs. PostgreSQL, the production database (`settings.py:182`), rejects `\x00` in text columns and `\u0000` in jsonb. The resulting DataError is not an `IntegrityError`, so it becomes a 500. The tests use SQLite, which accepts NUL, so the suite can't catch this.
- **Fix**: Return 400 in `_parse_payload` when any required string contains `'\x00'`, and add a test.
- **Decision**: FIXED — recursive NUL check over the whole payload (jsonb stores it all) returns 400; title and extra-field tests added

### F3 — README "verify these routes" block now sits under the token section

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Adherence
- **Location**: README.md:97, README.md:144
- **Detail**: The new `### Issue an automation token` section was inserted before the paragraph "With the local server running, verify these routes:". That paragraph closed "Test authentication locally / Create the initial family". It now reads as part of the automation-token section, after the intake `curl` example.
- **Fix**: Move the "verify these routes" block (README.md:144-153) back above `### Issue an automation token`.
- **Decision**: FIXED — verify-routes and production-callback paragraphs moved back above "Issue an automation token"

### F4 — Plan text disagrees with code on issuing and intake lookup

- **Severity**: 💬 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Adherence
- **Location**: family_access/admin.py:80-83; plan.md "Critical Implementation Details"
- **Detail**: The two differences:
  - Admin `save_model` calls `obj.assign_new_secret()` rather than `AutomationToken.issue()`. Both share the helper, so the secret format and hash are identical.
  - The plan's Critical Implementation Details says "one `get_or_create`". The code does what Phase 3 says: a Q lookup, then an atomic create, then a re-lookup on IntegrityError. That's the right choice, because `get_or_create` can't express the OR lookup.
- **Fix**: Add a one-line plan addendum for both, so S-05 plans against accurate text.
- **Decision**: FIXED — addendum added to plan.md above "S-05 Handoff"

### F5 — Notification titles listed in admin despite the model's privacy intent

- **Severity**: 💬 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: entries/admin.py (InboundNotificationAdmin.list_display)
- **Detail**: `InboundNotification.__str__` deliberately avoids title and message because they name children. The changelist still shows `title` for every family. Only superusers can see it, but this contradicts the stated intent and the `Entry` admin's "no content column" rule.
- **Fix**: Drop `title` from `list_display` (it stays visible on the read-only detail page), or accept it and document why.
- **Decision**: SKIPPED

### F6 — Issued-token page shows English role label

- **Severity**: 💬 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: family_access/templates/admin/family_access/automationtoken/issued.html:14
- **Detail**: `{{ token.member }}` uses `FamilyMember.__str__`, whose role labels are English, so the page renders "Anna (Parent)" on a page that is otherwise Polish. This breaks the lessons.md rule that user-facing text is in Polish.
- **Fix**: Render `{{ token.member.display_name }}` in the template.
- **Decision**: ACCEPTED-AS-RULE: Write code in English, user-facing and OpenAI messages in Polish (amended: /admin/ stays English). Existing Polish admin copy left unchanged.

### F7 — Test module and API URL naming diverge from siblings

- **Severity**: 💬 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: family_access/test_automation.py; entries/api_urls.py; family_access/api_urls.py
- **Detail**: Two naming mismatches:
  - `family_access/test_automation.py` sits next to `tests.py`, while `entries` uses a `tests/` package.
  - The API URL modules have no `app_name`, so their names are flat (`automation_ping`, `automation_notification_submit`). `entries/urls.py` is namespaced.
- **Fix**: Leave as is; move to `family_access/tests/` and agree on an API namespace the next time S-05 touches these files.
- **Decision**: SKIPPED — deferred to S-05

### F8 — Production manual checks ticked without recorded evidence

- **Severity**: 💬 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Success Criteria
- **Location**: plan.md Progress 2.10, 2.11, 3.10
- **Detail**: The deployed proxy check, the real-phone ping and the real-phone intake are marked `[x]`. Unlike every other step, they have no SHA or note. They are production-only checks, so the diff can't show them, but nothing records when they were confirmed or with which token.
- **Fix**: Add a date and a short note (e.g. "2026-09-27, token `fnat_abcd…`, N rows, no duplicates") to each item, or untick any that weren't actually run.
- **Decision**: FIXED — 2.10, 2.11, 3.10 annotated "verified manually on production 2026-09-27"
