<!-- PLAN-REVIEW-REPORT -->
# Plan Review: First School Event Capture

- **Plan**: context/changes/first-school-event-capture/plan.md
- **Mode**: Deep
- **Date**: 2026-09-27
- **Verdict**: REVISE (after triage: SOUND)
- **Findings**: 1 critical, 3 warnings, 2 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| End-State Alignment | FAIL |
| Lean Execution | PASS |
| Architectural Fitness | PASS |
| Blind Spots | WARNING |
| Plan Completeness | WARNING |

## Grounding

9/9 paths ✓, 10/10 symbols ✓, brief↔plan ~ (F6). Verified by running the full suite under `LANGUAGE_CODE='pl'` + `TIME_ZONE='Europe/Warsaw'`: 143 tests OK, 3 skipped, no breakage.

## Findings

### F1 — Polish locale makes <input type=date> render empty

- **Severity**: ❌ CRITICAL
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: End-State Alignment
- **Location**: Phase 2 §4 × Phase 3 §1 (EntryReviewForm)
- **Detail**: Verified: under 'pl' a default DateInput renders `value="21.09.2026"`, which `<input type=date>` shows as empty, and TimeInput renders `08:30:00`. On the phone the classified date disappears and every calendar event fails with "date required". Tests that post ISO dates would still pass.
- **Fix**: Pin `DateInput(format='%Y-%m-%d')` / `TimeInput(format='%H:%M')` and add a render test under 'pl'.
- **Decision**: FIXED — widget formats added to Phase 3 §1; new criterion 3.10.

### F2 — PROTECT on assigned_member blocks deleting a Family/User

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Blind Spots
- **Location**: Phase 1 §1
- **Detail**: Verified in an in-memory experiment: with PROTECT, deleting the Family, the User or the FamilyMember raises ProtectedError, even though the Entry would be cascade-deleted through the Family. With RESTRICT, a Family delete cascades cleanly, while a User or Member delete raises RestrictedError.
- **Fix A ⭐ Recommended**: SET_NULL
  - Strength: Deletes never block.
  - Tradeoff: A deleted child's entries quietly become family-wide.
  - Confidence: HIGH.
  - Blind spot: None significant.
- **Fix B**: RESTRICT
  - Strength: Family delete cascades; a person with assigned entries can't be removed by accident.
  - Tradeoff: The operator must reassign entries first.
  - Confidence: HIGH (verified).
  - Blind spot: The admin shows an error page.
- **Decision**: FIXED via Fix B — `on_delete=RESTRICT`; new criterion 1.7; brief risk added.

### F3 — Idempotent confirm: undecided edited-resubmission and foreign-key cases

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Blind Spots
- **Location**: Critical Implementation Details; Phase 1 §3; Phase 3 §2
- **Detail**: The plan never said what happens when the same key is posted again with edited values. It promised a "400 re-render" for a key from another family without a service or view contract for it.
- **Fix**: First save wins, and the saved panel shows the stored values. A foreign key makes the service raise ValidationError, and the view re-renders with a fresh key.
- **Decision**: FIXED — Critical Details, service and view contracts, and criteria 1.5 and 3.7 updated.

### F4 — Wrong Gunicorn figures in Current State / Performance

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Current State Analysis; Performance Considerations
- **Detail**: The plan cited a "default 30 s" timeout. The runbook unit (`context/changes/deployment/mikrus-runbook.md:445`) sets `--workers 2 --timeout 45`, and nginx sets `proxy_read_timeout 50s` (:498).
- **Fix**: Cite the real figures, and note that the 2-worker concurrency risk is existing and out of scope.
- **Decision**: FIXED.

### F5 — "Frozen localdate" with no freezing tool

- **Severity**: OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 3 §5; criterion 3.2
- **Detail**: The repo has no freezegun or time-machine; existing tests pass `reference_date` explicitly or use `mock.patch`.
- **Fix**: Name the `mock.patch('entries.views.timezone.localdate', …)` target.
- **Decision**: FIXED.

### F6 — Small plan↔brief inconsistencies

- **Severity**: OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 1 §4, Phase 2 §1
- **Detail**: The plan says "classless" but vendors `pico.min.css` and uses `.container`. The brief says "read-only admin", but the plan makes only 3 fields read-only.
- **Fix**: Align the wording and make the admin view-only.
- **Decision**: DISMISSED
