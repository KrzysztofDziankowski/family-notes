<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Family Entries REST API

- **Plan**: context/changes/family-entries-rest-api/plan.md
- **Scope**: Full plan
- **Reviewed phases**: 1, 2, 3
- **Date**: 2026-09-28
- **Verdict**: APPROVED
- **Findings**: 0 critical, 1 warning, 3 observations

Phase 2 code and automated criteria were reviewed; its manual items 2.7–2.8 (and 3.5–3.7) are still pending human confirmation.

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | PASS |
| Scope Discipline | PASS |
| Safety & Quality | WARNING |
| Architecture | PASS |
| Pattern Consistency | PASS |
| Success Criteria | PASS |

Automated evidence (HEAD 786ab51, `DJANGO_DEBUG=true`): `test entries.tests.test_entries_api` 54 OK; regression set 128 OK; full `test` 582 OK (3 skipped); `check` no issues; `makemigrations --check --dry-run` no changes; README section present.

## Findings

### F1 — Oversized `offset`/`limit` returns HTML 500 instead of 400

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: entries/api_views.py:145 (`_UNSIGNED_INT`), entries/api_views.py:159 (`_parse_unsigned_int`)
- **Detail**: `[0-9]+` accepts unbounded digit strings. `offset=9223372036854775808` overflows the DB bind (probe: 500 on SQLite; bigint out of range on PostgreSQL), and a >4300-digit value makes `int()` raise `ValueError` (500). Breaks the documented `400 invalid_query` contract and emits an error traceback per request (authenticated callers only; no data leak).
- **Fix**: Bound the digit length (e.g. `[0-9]{1,18}`) or add a `MAX_OFFSET` cap returning `None`; add parser + endpoint tests for `9223372036854775808` and a 5000-digit value; state the upper bound in the README parameter table.
- **Decision**: FIXED — ffa1bdf (18-digit cap; break-check confirmed tests go red on the old regex)

### F2 — Phase 3 and SHA-record commits use `docs(`/`chore(` prefix

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: commits d1f58bf, 786ab51
- **Detail**: lessons.md asks for a `feat(<feature-id>):` prefix; the feature id is present but the type is `docs`/`chore` (consistent with the prior feature's chore commits and the implement skill's type selection).
- **Fix**: No rewrite of pushed history; use `feat(` for remaining commits of this change if the lesson is meant literally.
- **Decision**: FIXED — history kept; remaining commits of this change use `feat(family-entries-rest-api):` (ffa1bdf onward)

### F3 — Repeated query parameters: last value wins, undocumented

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: entries/api_views.py:182
- **Detail**: `?limit=abc&limit=5` → 200 (limit 5), `?limit=5&limit=abc` → 400. No security impact; behaviour not documented or tested.
- **Fix**: Add one sentence to the README ("if a parameter is repeated, the last value is used").
- **Decision**: FIXED — README notes that a repeated parameter uses its last value

### F4 — README date example needs GNU `date`

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Adherence
- **Location**: README.md:225
- **Detail**: `date -I -d '+28 days'` fails on macOS/BSD `date`.
- **Fix**: Add a note with the BSD equivalent `date -v+28d +%F`.
- **Decision**: SKIPPED
