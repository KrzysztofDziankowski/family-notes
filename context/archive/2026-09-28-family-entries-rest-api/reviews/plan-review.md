<!-- PLAN-REVIEW-REPORT -->
# Plan Review: Family Entries REST API

- **Plan**: context/changes/family-entries-rest-api/plan.md
- **Mode**: Deep (verified inline)
- **Date**: 2026-09-28
- **Verdict**: REVISE → SOUND after triage
- **Findings**: 0 critical, 3 warnings, 1 observation

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| End-State Alignment | PASS |
| Lean Execution | PASS |
| Architectural Fitness | PASS |
| Blind Spots | WARNING |
| Plan Completeness | WARNING |

## Grounding
7/7 paths ✓, 6/6 symbols ✓ (automation_token_required, automation_membership, is_parent covers inactive family, _family_entries + select_related, entry_family_date_idx, MS-01), brief↔plan ✓, Progress↔Phase ✓

## Findings

### F1 — Offset pages shift when entries are added or deleted

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Blind Spots
- **Location**: Public API (ordering + limit/offset), Phase 3 README
- **Detail**: With `created_at DESC`, every new entry (including background inserts from the S-05 worker) moves to offset 0 and shifts later pages, so a client paging through gets duplicates. Deletes cause skipped entries. The plan called the order "stable", which holds only for a fixed dataset.
- **Fix A ⭐ Recommended**: Document "pages are not a snapshot; dedupe by id" plus a test.
- **Fix B**: Sort `created_at ASC, id ASC` so inserts don't shift earlier pages.
- **Decision**: FIXED (Fix B). The sort is now ascending in the plan and brief, the ordering test covers an insert between pages, and the README documents that deletes can still shift pages.

### F2 — Parameter edge cases left undecided

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Blind Spots
- **Location**: Public API — include_undated, date_from/date_to
- **Detail**: The plan left three cases open: `include_undated=false` with no bounds, how case in booleans is handled, and an impossible date (2026-02-30) that gives 500 instead of 400.
- **Fix**: Decide the semantics and add the cases to test 1.1.
- **Decision**: FIXED (different approach). Explicit `false` with no bounds returns dated entries only. Booleans are case-insensitive, and `1`/`0`/`yes`/empty → 400. An impossible date → 400.

### F3 — Undecided file placement; no runnable test commands

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 1 §1, Phase 2 §2, Success Criteria 1–2
- **Detail**: The plan said "services.py or a dedicated module" and "a new module in entries/tests/". It did not reuse `_family_entries()`, and gave no commands for Phases 1–2. `api_views.py` is being edited in parallel by S-05.
- **Fix**: Pin the files, the reuse and the commands.
- **Decision**: FIXED. The queryset goes in `services.py` on top of `_family_entries`. Parser, serializer and view go in `api_views.py` (docstring extended). Tests go in `entries/tests/test_entries_api.py`. Commands for Phase 1, Phase 2 and the 2.6 regression suites are in the plan.

### F4 — Tokens already issued silently gain read access

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Blind Spots
- **Location**: What We're NOT Doing, Phase 3 README
- **Detail**: Tokens issued under F-04's write-only promise gain read access to all family entries without a reissue.
- **Fix**: Add an operator note to the README.
- **Decision**: FIXED. The Phase 3 README contract now includes the operator note about revoking tokens that shouldn't have this access.
