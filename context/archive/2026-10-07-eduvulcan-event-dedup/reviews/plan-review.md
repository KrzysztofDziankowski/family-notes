<!-- PLAN-REVIEW-REPORT -->
# Plan Review: EduVulcan Event Deduplication and Exam Merge

- **Plan**: context/changes/eduvulcan-event-dedup/plan.md
- **Mode**: Deep
- **Date**: 2026-10-07
- **Verdict**: SOUND
- **Findings**: 0 critical, 2 warnings, 2 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| End-State Alignment | PASS |
| Lean Execution | PASS |
| Architectural Fitness | WARNING |
| Blind Spots | WARNING |
| Plan Completeness | WARNING |

## Grounding
5/5 paths ✓, 4/4 symbols ✓, brief↔plan ✓

## Findings

### F1 — Existing worker test will break and isn't named

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 2 — Success Criteria 2.3
- **Detail**: `entries/tests/test_conversion_worker.py:101-110` converts two identical Sprawdzian notifications and expects two entries; this is the intended behavior change.
- **Fix**: Name the test in Phase 2 as an intended update (make the notifications distinct events).
- **Decision**: FIXED

### F2 — Full FOR UPDATE on Family blocks unrelated inserts

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Architectural Fitness
- **Location**: Critical Implementation Details — Timing & lifecycle
- **Detail**: On PostgreSQL a plain `FOR UPDATE` conflicts with KEY SHARE locks taken by intake (`api_views.py:116`) and manual entry (`services.py:62`) inserts. No inverse lock order exists.
- **Fix**: Use `select_for_update(no_key=True)`.
- **Decision**: FIXED

### F3 — Exact-vs-exam precedence undefined for equal-rank re-send

- **Severity**: OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Blind Spots
- **Location**: Implementation Approach — Matching rules
- **Detail**: An exact exam re-send matches both rules; output kind was unspecified.
- **Fix**: Exact-duplicate check first (→ `duplicate`), exam ranking only otherwise.
- **Decision**: FIXED

### F4 — Model docstring says NULL entry means "parent deleted"

- **Severity**: OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Blind Spots
- **Location**: Phase 1 — Output kinds
- **Detail**: `entries/models.py:199-202` documents NULL `entry` only as a tombstone.
- **Fix**: Update the docstring in Phase 1 change #2.
- **Decision**: FIXED
