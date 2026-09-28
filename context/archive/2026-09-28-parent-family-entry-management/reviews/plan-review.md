<!-- PLAN-REVIEW-REPORT -->
# Plan Review: Parent Family Entry Management

- **Plan**: `context/changes/parent-family-entry-management/plan.md`
- **Mode**: Deep
- **Date**: 2026-09-28
- **Verdict**: SOUND
- **Findings**: 0 critical, 2 warnings, 1 observation

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| End-State Alignment | PASS |
| Lean Execution | PASS |
| Architectural Fitness | PASS after F2 |
| Blind Spots | PASS |
| Plan Completeness | PASS after F1 and F3 |

## Grounding

Grounding: 7/7 paths ✓, 6/6 symbols ✓, brief↔plan ✓. Progress: 3/3 phases ✓, 25/25 criteria mapped ✓.

## Findings

### F1 — Past-entry ordering leaves visible tie behavior undefined

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 2 — Index organization and ordering
- **Detail**: The plan fixed past dates as descending but did not choose time direction, null placement, or primary-key direction, allowing visibly different implementations.
- **Fix**: Specify date descending, time descending with missing times last, then primary key descending, and test the exact sequence.
- **Decision**: FIXED — exact ordering added to the contract and test expectation.

### F2 — Shared validation can break the tested capture correction contract

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Architectural Fitness
- **Location**: Phase 1 — Shared entry forms
- **Detail**: Capture hides `school_item` and silently clears an incompatible classifier subtype, while management forms expose the subtype and must report incompatible visible choices.
- **Fix**: Share field definitions and invariant helpers while retaining capture's silent clearing and adding a Polish mismatch error to management forms.
- **Decision**: FIXED — compatibility policies are now explicit and separate.

### F3 — Unsaved synthetic details need explicit provenance values

- **Severity**: 🔎 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 3 — Management state gallery
- **Detail**: Django does not populate `auto_now_add` and `auto_now` fields on unsaved synthetic objects, so the gallery could render blank provenance.
- **Fix**: Assign source and timestamps explicitly and render the delete disclosure open through HTML markup.
- **Decision**: FIXED — synthetic-state requirements now name those values and markup state.

## Triage Summary

- **Fixed**: F1, F2, F3
- **Skipped**: none
- **Accepted**: none
- **Dismissed**: none
- **Verdict after fixes**: SOUND
