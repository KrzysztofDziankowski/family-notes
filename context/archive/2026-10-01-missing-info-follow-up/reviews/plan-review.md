<!-- PLAN-REVIEW-REPORT -->
# Plan Review: Missing Information Follow-Up

- **Plan**: context/changes/missing-info-follow-up/plan.md
- **Mode**: Deep
- **Date**: 2026-10-01
- **Verdict**: REVISE → SOUND after triage
- **Findings**: 0 critical, 3 warnings, 2 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| End-State Alignment | PASS |
| Lean Execution | PASS |
| Architectural Fitness | PASS |
| Blind Spots | WARNING |
| Plan Completeness | WARNING |

## Grounding
11/11 existing paths ✓ (3 new files confirmed absent), 6/6 symbols ✓, Progress↔Phases 11/11 ✓, brief↔plan ✓

## Findings

### F1 — Irrelevant fields in the second result can veto a good answer

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Blind Spots
- **Location**: Phase 1 — #3 Answer service (merge)
- **Detail**: The plan validated the whole second output with `classify_output` and then picked only the missing fields. But `validate_output` fails the whole result on an unknown member, empty content or ungrounded output (`entries/classification/validation.py:50-66`). If only the date was missing and the model echoed the known member with a different spelling, the valid date was lost and the parent saw the fallback.
- **Fix**: Build the merged `BackendOutput` first (the draft's values plus only the missing fields from the answer, with the answer's `grounded`), then validate and resolve it once.
  - Strength: The answer is judged only on what was asked, reusing the existing validator.
  - Tradeoff: The draft member must be passed back by display name.
  - Confidence: HIGH — validate_output is the single rule source.
  - Blind spot: None significant.
- **Decision**: FIXED

### F2 — Answer service signature omits draft_member

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 1 — #3 Contract
- **Detail**: `draft_member` was added in a trailing sentence instead of the signature line, but it is part of the contract between phase 1 and phase 2.
- **Fix**: Put `draft_member: Optional[FamilyMember] = None` in the signature line.
- **Decision**: FIXED

### F3 — Second capture follow-up test also breaks

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 2 — #4 Tests
- **Detail**: Both `test_follow_up_marks_missing_date_and_saves_once_filled` (`entries/tests/test_capture_views.py:247`) and `test_ambiguous_member_asks_to_choose_a_person` (`:269`) expect the highlighted review form from capture. The plan mentioned only one of them.
- **Fix**: Name both tests in phase 2 as rewritten for the `question` state.
- **Decision**: FIXED

### F4 — A time given in the answer is silently dropped

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Blind Spots
- **Location**: Phase 1 — #3 Merge
- **Detail**: Time is never a missing field, so in „w piątek o 8:00” the time is dropped, as the "fill only missing" decision implies.
- **Fix**: Take time from the answer when the date was missing and the draft has no time.
- **Decision**: ACCEPTED — the parent corrects the time in the review form; recorded in the brief's Open Risks.

### F5 — Nothing left to ask after server-side recomputation

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Blind Spots
- **Location**: Phase 2 — #1 draft_from_form
- **Detail**: The plan didn't say what happens when every posted missing value is dropped by recomputation (a tampered or stale form).
- **Fix**: Go straight to the proposal review form with no backend call.
- **Decision**: FIXED
