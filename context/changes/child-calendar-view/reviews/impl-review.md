<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Shared Calendar for Parent and Child

- **Plan**: context/changes/child-calendar-view/plan.md
- **Scope**: Full plan
- **Reviewed phases**: 1, 2, 3, 4
- **Date**: 2026-10-10
- **Verdict**: APPROVED
- **Findings**: 0 critical, 2 warnings, 3 observations

All automated criteria are green at 8d278ed:
- greps 1.2, 2.3 and 3.2 are clean (3.2 matches only a negative assertion in a test);
- check and makemigrations pass;
- 1547 Django tests are OK;
- the member-filter E2E spec passes.

The 8 manual checks were left unchecked by the owner. The pre-existing E2E failure in
parent-entry-lands-grouped (heading without the weekday) is out of scope by the owner's decision.

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

### F1 — `:has()` selector disables the margin fallback in older browsers

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: family_notes/static/css/tokens.css:471-472
- **Detail**: `.fn-calendar-day > :last-child` now shares one selector list with a `:has(~ section:not([hidden]))` selector. A browser without `:has` (Firefox < 121, Safari < 15.4) drops the whole rule, including the old reset that worked everywhere.
- **Fix**: Split into two rules: keep `.fn-calendar-day > :last-child { margin-bottom: 0; }` alone and put the `:has` selector in its own rule.
- **Decision**: FIXED — split into two rules (tokens.css)

### F2 — Manual verification pending

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Success Criteria
- **Location**: context/changes/child-calendar-view/plan.md (Progress 1.3, 2.4, 2.5, 3.4, 3.5, 4.6, 4.7, 4.8)
- **Detail**: The owner closed the change with the manual rows unchecked. No rows were rubber-stamped. The no-JS path (4.7) and the screen-reader announcement (4.8) have no automated coverage in a browser.
- **Fix**: Run the manual checks (phone portrait and landscape, no-JS, screen reader) and tick the rows.
- **Decision**: ACCEPTED — owner closed the change with manual rows unchecked (2026-10-10)

### F3 — No query-count tests for the calendars

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: entries/tests/test_manage_views.py, entries/tests/test_child_views.py
- **Detail**: `entries:index` runs 2 queries and `entries:child_list` runs 1 (now bounded to 14 days), but nothing pins those counts. Dropping `select_related('assigned_member')` would bring back an N+1 query per group heading unnoticed.
- **Fix**: Add `assertNumQueries` cases for index (with and without `member`) and child_list, using a window with several assignees.
- **Decision**: FIXED — CalendarQueryCountTests and ChildCalendarQueryCountTests pin that query counts do not grow with rows or assignees

### F4 — E2E fixtures dated today can leak at Warsaw midnight

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: tests/e2e/member-filter.spec.ts:10-15, 26-37
- **Detail**: Fixtures are dated today and tomorrow, and cleanup searches the default `/entries/` window. A run that crosses midnight leaves today's entry outside the window: cleanup finds 0 rows and passes, and the entry stays behind. The `start` assertions can also flake.
- **Fix**: Date the fixtures a few days into the window (+2/+3), or clean up via `/entries/?start=<creation date>`.
- **Decision**: FIXED — fixtures dated +2/+3 days; window assertions read the expected start from the nav links

### F5 — Detail with an invalid `start` goes back to today's window

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Adherence
- **Location**: entries/views.py:1072-1078
- **Detail**: `_detail_list_start` falls back to today when `?start` is present but invalid, rather than to the window containing the entry. This matches the plan's wording ("from ?start, else from the entry's date"). Only hand-edited URLs reach it.
- **Fix**: Treat an invalid `start` like a missing one: validate first, and on fallback use `_window_containing(entry.effective_date, today)`.
- **Decision**: FIXED — an invalid start falls back to the window containing the entry; parent and child tests updated
