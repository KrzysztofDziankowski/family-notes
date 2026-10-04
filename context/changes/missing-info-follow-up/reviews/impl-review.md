<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Missing Information Follow-Up Implementation Plan

- **Plan**: context/changes/missing-info-follow-up/plan.md
- **Scope**: Full plan
- **Reviewed phases**: 1, 2, 3
- **Date**: 2026-10-04
- **Verdict**: NEEDS ATTENTION
- **Findings**: 0 critical, 2 warnings, 1 observation

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | PASS |
| Scope Discipline | WARNING |
| Safety & Quality | WARNING |
| Architecture | PASS |
| Pattern Consistency | PASS |
| Success Criteria | WARNING |

## Findings

### F1 — Bare answer-key citation bypasses date evidence check

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Safety & Quality
- **Location**: entries/classification/openai_backend.py:388
- **Detail**: `_points_at_answer` accepts the bare key `odpowiedz_rodzica` without inspecting the answer. Reproduction: original text `Sprawdzian Ali`, answer `nie wiem`, source `odpowiedz_rodzica` makes `_date_is_grounded` return True. If the provider returns a fabricated date with grounded=True, the adapter retains it and the missing-date merge can produce a proposal rather than the intended highlighted fallback. The parent still confirms before saving. Existing tests cover key citations with a date-bearing answer, but omit this negative case.
- **Fix**: Reject bare input-key citations and require an actual fragment from the parent's text; add regressions for a key citation with `nie wiem` and a member-only answer.
  - Strength: Restores the adapter's documented literal evidence requirement.
  - Tradeoff: Small models that cite only the key will fall back to manual date completion.
  - Confidence: HIGH — the bypass is reproduced at runtime.
  - Blind spot: Literal fragment matching still cannot prove a fragment expresses a date or that its date interpretation is correct; whole-answer citations also need scrutiny.
- **Decision**: FIXED — Removed bare-key and surrounding-input date evidence shortcuts; regression tests pass.

### F2 — Cross-caller classification changes lack a plan addendum

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Scope Discipline
- **Location**: entries/classification/openai_backend.py:87
- **Detail**: Phase 3 introduced a required `date_source` structured-output field and filtering in the shared adapter, affecting initial capture and automated family classification as well as follow-up answers. It also added past-date warnings (`entries/forms.py:121`), a past-date gallery state, and later model guidance in `.env.example` and the deployment runbook. Commit messages explain these discoveries, but the plan describes phase 3 only as gallery states and manual verification. These are related, tested changes rather than missing core implementation, but their wider behavior is undocumented in the plan.
- **Fix**: Add a concise plan addendum describing discovered date problems, shared callers affected, warning behavior, model guidance and the additional verification performed.
  - Strength: Makes the final scope reviewable and preserves the fixes and their existing tests.
  - Tradeoff: Updates the original scope after implementation; distinguish discovered work explicitly.
  - Confidence: HIGH — feature commit diffs establish these additions.
  - Blind spot: Live results across configured models have not been independently reproduced in this review.
- **Decision**: FIXED — Added implementation addendum documenting discovered scope, affected callers and verification.

### F3 — Manual completion markers overstate available evidence

- **Severity**: ℹ️ OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Success Criteria
- **Location**: context/changes/missing-info-follow-up/plan.md:284
- **Detail**: Progress 3.3 states screenshots were taken, while change.md:14 explicitly records the owner's waiver and says none were taken. The waiver is respected; screenshots are not required again by this review. The question wording is observable in source, but phone-width browser completion (2.3) and the timed live follow-up run (3.4) have no saved evidence in the change directory. The model recommendation commit records live date checks, but not a measured two-step follow-up transcript. These historical completion claims cannot be independently verified from the repository. No live API call or browser run was performed during review.
- **Fix**: Annotate the screenshot step with its owner waiver without changing its title, and attach existing browser/live verification evidence or clearly record its absence and the basis for manual sign-off.
- **Decision**: FIXED — Recorded screenshot waiver and missing manual evidence in the descriptive plan; preserved Progress and historical declarations.

## Scope and evidence

- Progress has 11/11 checked steps; current phase is 3. All three phases were reviewed.
- Feature scope was resolved from commits 382506e, 7e9b93e, 215c246, b98fdc5 and 8849d1e, rather than a contiguous date range containing unrelated testing and hook work.
- Planned service, backend input, forms, endpoints, templates and gallery contracts are implemented. Authorization precedes provider invocation; hidden member IDs are family-scoped; saving remains in confirm; answer privacy tests and repr exclusions exist.
- Additional modified tests support shared-adapter regressions. Development IDE hygiene is benign. Interleaved testing-research documents and hook configuration are independent work and excluded.
- Existing uncommitted context/foundation/roadmap.md changes were preserved.
- Runtime reproduction of F1 returned True for a bare answer key and a no-date answer.

## Automated verification

- PASS: `uv run python manage.py test entries.tests.test_follow_up_answer entries.tests.test_openai_backend entries.tests.test_capture_views entries.tests.test_follow_up_views entries.tests.test_states_view` — 128 tests, 52.394 s, OK.
- PASS: `uv run python manage.py check` — System check identified no issues (0 silenced).
- PASS: `uv run python manage.py makemigrations --check --dry-run` — No changes detected.
- PASS: `git diff --check` — no output.
- PASS: `uv run python manage.py test` — 679 tests, 98.537 s, OK (skipped=4); opt-in live tests were not enabled.

The focused command runs every phase-specific suite required by the plan. The repeated full-suite commands in the plan are consolidated into one run on the current tree.

## Triage execution — 2026-10-04

F1, F2 and F3 fixed as approved. The original review verdict above is retained as historical evidence; all findings now have final decisions. Literal source matching remains a textual check rather than a guarantee of correct date semantics.

- Red reproduction: 11 date-grounding tests ran before the adapter fix; 12 negative subcases failed as expected.
- PASS: `uv run python manage.py test entries.tests.test_openai_backend entries.tests.test_follow_up_answer entries.tests.test_follow_up_views` — 104 tests, 11.810 s, OK.
- PASS: Django system checks, migration drift check and whitespace check — no issues, no model changes.
- PASS: `uv run python manage.py test` — 681 tests, 67.335 s, OK (skipped=4).
- Browser checks and paid live calls were not repeated, as agreed.
