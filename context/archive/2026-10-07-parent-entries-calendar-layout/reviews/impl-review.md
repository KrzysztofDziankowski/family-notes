<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Parent Entries Calendar Layout

- **Plan**: context/changes/parent-entries-calendar-layout/plan.md
- **Scope**: Full plan
- **Reviewed phases**: 1, 2, 3
- **Date**: 2026-10-07
- **Verdict**: NEEDS ATTENTION
- **Findings**: 0 critical, 3 warnings, 4 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | WARNING |
| Scope Discipline | PASS |
| Safety & Quality | WARNING |
| Architecture | PASS |
| Pattern Consistency | WARNING |
| Success Criteria | PASS |

Success criteria evidence: 1467 Django tests OK, `manage.py check` clean, `makemigrations --check` no changes, Playwright 3/3. Manual items 1.6–3.8 were exercised in a scripted browser pass against the E2E server (all 9 PASS: default windows, navigation + detail round trip, boundary links, tomorrow entry once under Kasia/Cała rodzina, empty fortnight with 14 boxes, 320px one column without overflow, 1280px 7×2 grid, dashed/bg-tinted empty boxes, 2px solid focus outline on tabs/navigation/entry links); rows remain unchecked pending owner confirmation.

## Findings

### F1 — Extreme `start` values crash with OverflowError (500)

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: entries/views.py:910-944 (`_calendar_window`, `_calendar_navigation`); also reached from detail (≈1053) and delete (≈1143)
- **Detail**: Verified: `_calendar_window('upcoming', '9999-12-31', …)` and past `start=0001-01-01` raise OverflowError from timedelta arithmetic. In `delete` the helper runs after `delete_family_entry`, so a crafted POST deletes the entry and then returns 500. Own-family only, crafted input, no security impact.
- **Fix**: Treat out-of-range values as invalid — in `_calendar_window` fall back to the default when the window or its ±14-day neighbours would overflow (e.g. clamp to ±100 years around today); add a test with `start=9999-12-31` and `view=past&start=0001-01-01`.
- **Decision**: FIXED

### F2 — DEBUG gallery detail states lost the back-link query

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Adherence
- **Location**: entries/templates/entries/states.html:44; entries/views.py:1012-1013
- **Detail**: The gallery include passes only `entry`, `list_mode`, `delete_open`, so `Wróć do listy` renders as `/entries/?` and the delete form's hidden `start` is empty in detail_manual / detail_eduvulcan / delete_open. `_detail_context` also defaults `list_start` from the real today, not STATES_DATE, so the gallery is not deterministic.
- **Fix**: Pass `list_query`/`list_start` through the include and give `_detail_context` a `today` argument (STATES_DATE in the gallery); assert the gallery back link in test_manage_states.
- **Decision**: FIXED

### F3 — E2E heading expectation breaks on 31 December

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: tests/e2e/parent-entry-lands-grouped.spec.ts:16-19, 55
- **Detail**: `parent_day_heading` appends the year whenever the day's year differs from today's, including relative days (verified: `Jutro, 1 stycznia 2027` for 2026-12-31). The spec formats only day+month, so it fails once a year. The relative cross-year case also has no unit test.
- **Fix**: Add `year: 'numeric'` in the spec when tomorrow's year differs from today's; add a `ParentDayHeadingTests` case for `parent_day_heading(date(2027,1,1), date(2026,12,31)) == 'Jutro, 1 stycznia 2027'`.
- **Decision**: FIXED

### F4 — Detail opened without list query returns to the default window

- **Severity**: 💡 OBSERVATION
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Plan Adherence
- **Location**: entries/views.py:1047-1058
- **Detail**: After create/edit (redirects without `view`/`start`) the back link goes to the mode's default fortnight, which may not contain the entry (e.g. an entry 20 days ahead). Also `?view=xyz` normalises to upcoming instead of the entry's own mode. The plan only specifies preserving a provided query.
- **Fix**: When no `start` is given, derive the fortnight containing `entry.effective_date` (aligned to the mode's 14-day grid) and use the entry's own mode for unknown `view` values.
  - Strength: Back link always lands on a window that shows the entry; matches the plan's "return to the same window" intent for create/edit flows.
  - Tradeoff: Small extra helper plus tests; changes current behaviour for paramless detail URLs.
  - Confidence: MED — straightforward arithmetic, but the alignment rule (multiples of 14 from today) is a product choice.
  - Blind spot: Not checked whether create/edit success messages are expected on the default window.
- **Decision**: FIXED

### F5 — Leftover context key and stale template comment

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: entries/views.py:1006; entries/templates/entries/_manage_detail.html:4
- **Detail**: `'start'` in `_index_context` is read by no template or test. `_manage_detail.html` header still lists only `entry, list_mode, delete_open`.
- **Fix**: Drop the `'start'` key; add `list_query, list_start` to the detail template comment.
- **Decision**: FIXED

### F6 — Trivially passing assertion uses the child heading helper

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Success Criteria
- **Location**: entries/tests/test_manage_views.py (GroupedIndexTests, `assertNotIn(day_heading(self.days(10), …), past)`)
- **Detail**: The parent page never renders the short child `day_heading`, so the assertion cannot fail.
- **Fix**: Use `parent_day_heading` in that assertion.
- **Decision**: FIXED

### F7 — Past fortnight: days ascend, rows within a day descend

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Adherence
- **Location**: entries/views.py (index ordering, past branch)
- **Detail**: Plan keeps "existing row ordering" (past = time desc) but days now run oldest→newest left-to-right. Mixed direction inside one calendar may read oddly.
- **Fix**: Product call — either keep, or order past rows within a day by time ascending like upcoming (one-line order_by change plus the past ordering test).
- **Decision**: FIXED
