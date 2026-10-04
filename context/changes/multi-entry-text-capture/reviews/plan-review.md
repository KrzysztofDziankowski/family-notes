<!-- PLAN-REVIEW-REPORT -->
# Plan Review: Multi-Entry Text Capture Implementation Plan

- **Plan**: context/changes/multi-entry-text-capture/plan.md
- **Mode**: Deep
- **Date**: 2026-10-04
- **Verdict**: SOUND (after triage; was REVISE)
- **Triage**: applied 2026-10-04
- **Findings**: 1 critical, 3 warnings, 1 observation

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| End-State Alignment | FAIL |
| Lean Execution | PASS |
| Architectural Fitness | WARNING |
| Blind Spots | WARNING |
| Plan Completeness | PASS |

## Grounding
Grounding: 9/9 paths ✓ (backends.py, openai_backend.py, service.py, forms.py, services.py, views.py, urls.py, _saved_panel.html, capture.html; new files are correctly marked new), 8/8 symbols ✓ (`DEFAULT_MAX_OUTPUT_TOKENS=1024` at openai_backend.py:51, `save_confirmed_entry` with an inner `transaction.atomic()` and an `IntegrityError` replay at services.py:51-70, `submission_key` unique at models.py:62, `_saved_entry` at views.py:233, `_log_rejected_save`, `SAVE_FAILED_ERROR`, `classification_smoke.py:77` `.classify(`, `_general_note`). 1 stale line ref: `validation.py:112-172`/`:175-179` (the file has 112 lines; `validate_output` is at 45-95 and `_general_note` at 108-112). Brief↔plan ✓. Progress↔Phase ✓ (4 phases, all criteria mapped, no checkboxes in phase blocks).

Cross-slice composition was checked against the contracts in S-01 `school-event-details`, S-02 `classification-short-names`, S-20 `title-keeps-action-only` and S-03 `free-text-proposal-correction`, which all land before S-04.

## Findings

### F1 — The batch pipeline skips the S-01 subject and S-02 short-name steps

- **Severity**: ❌ CRITICAL
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: End-State Alignment
- **Location**: Phase 1 §3 (`classify_entries_for_parent`, "each output goes through `classify_output` and `_resolve_member`"); Phase 2 §1–2 (`BatchReviewForm`, `save_confirmed_entries`)
- **Owner input**: no
- **Detail**: By the time S-04 starts, `classify_for_parent` will run `_apply_member_mention(output, candidates)` before validation (S-02 §3), and it will call `classify_output(..., require_school_subject=True)` with a required keyword (S-01 Phase 2 §2–3). The S-04 plan lists only `classify_output` and `_resolve_member` for a multi-output batch, and says the one-output path "may share a helper". Without these steps, three problems follow. (a) "Dodaj spotkanie z Hanią dziś i jutro" falls back to `UNKNOWN_MEMBER` → the whole batch becomes a note (Assumed Decision 7), while a single entry works. (b) Batch school events never get a `SCHOOL_SUBJECT` highlight. (c) `save_confirmed_entries` passes items to `save_confirmed_entry(**item)`, which after S-01 requires a subject for the four school kinds. If the items omit `school_subject`, every batch with a school event fails with `SAVE_FAILED_ERROR`. The sub-forms are `EntryReviewForm`s, so they inherit S-01's visible school item and subject. The duplicate-hint key (type, title, date, time) also ignores the school item and subject.
- **Fix**: Make it mandatory, not optional, to share one per-output helper, e.g. `_finish_parent_output(request, output, candidates)` = `_apply_member_mention` → `classify_output(require_school_subject=True)` → `_resolve_member`. Use it in `classify_for_parent`, the batch path and (through S-03) the correction merge. Build each batch save item from the sub-form's `cleaned_data`, including `school_subject`. Add batch tests: a diminutive in a batch resolves, a school event in a batch without a subject is highlighted, and a batch with a school event saves with its subject.
  - Strength: One pipeline, so later parent-path rules cannot diverge between single and batch.
  - Tradeoff: A small refactor of `classify_for_parent` in a slice that otherwise only adds code.
  - Confidence: HIGH — S-01 and S-02 explicitly change exactly these call sites.
  - Blind spot: The final S-01/S-02 helper names are planned, not yet merged.
- **Decision**: FIXED (Fix A)

### F2 — `DATE_RULES` and `INSTRUCTIONS` already come from S-20; the list path must reuse per-entry translation

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Architectural Fitness
- **Location**: Phase 1 §2 (`DATE_RULES` "appended to both `INSTRUCTIONS` and `MULTI_INSTRUCTIONS`"), Phase 1 §4 test "`INSTRUCTIONS` contains `DATE_RULES`", Manual 1.4
- **Owner input**: no
- **Detail**: S-20 lands first. It creates `DATE_RULES`, appends it (and the title rule) to `INSTRUCTIONS`, and adds the title guard inside `_translate` after date grounding. S-04 defines `MULTI_INSTRUCTIONS` as `INSTRUCTIONS` plus one sentence and also appends `DATE_RULES` to it, so the rules would be sent twice. The test "`INSTRUCTIONS` contains `DATE_RULES`" duplicates S-20's test. Also, `_translate` today rejects anything that is not a `StructuredClassification` (`openai_backend.py:327-329`), so `classify_many` needs its own translator. If it does not reuse the single-entry translation, per-entry grounding and the S-20 title guard (per-entry `date_source` such as „jutro” or „dziś”) are skipped in batches, and titles keep „… dziś” or „… jutro”.
- **Fix**: Reuse S-20's `DATE_RULES` and build `MULTI_INSTRUCTIONS = INSTRUCTIONS + split sentence` with no second append. Drop the duplicate test, and instead assert that `DATE_RULES` appears exactly once in `MULTI_INSTRUCTIONS`. Extract a per-entry `_translate_entry(parsed, request) -> BackendOutput` (grounding, then the S-20 guard, then mapping) that both `_translate` and the list translator call. Add an adapter test where a batch entry's title has its own date phrase stripped. Re-scope 1.4 to `MULTI_INSTRUCTIONS` with an inline note; do not change the step title. Update the brief's "created by whichever of S-03 or S-04 lands first".
- **Decision**: FIXED (Fix A)

### F3 — The "single path unchanged" claim does not hold for the real adapter

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Blind Spots
- **Location**: Critical Implementation Details ("byte-identical in behaviour"); Phase 2 §3 (`capture` calls `classify_entries_for_parent`); Phase 4 §2 ("existing single-entry corpus cases still pass through `classify_entries_for_parent`")
- **Owner input**: no
- **Detail**: The OpenAI backend will implement `classify_many`, so every production capture, including single-entry ones, uses the list schema, `MULTI_INSTRUCTIONS` and the 2048-token budget. Only fake backends keep the old single path. The regression gate the plan relies on does not cover this. `test_capture_views` uses fake backends. The acceptance corpus calls `classify_for_parent` directly (`entries/tests/test_classification_acceptance.py:86-104`), and `model_output` scripts a single-object body. After the change, `classify_for_parent` is no longer called by any view (`entries/views.py:115` is its only production caller). The corpus therefore keeps testing a path production no longer takes. Phase 4's claim that the corpus "still passes through `classify_entries_for_parent`" would fail parsing unless each scripted body is wrapped in `{"entries": [...]}`.
- **Fix**: Run the existing adapter-path corpus through `classify_entries_for_parent`. Give `model_output` a list-wrapping variant used by `run_service`, and assert `batch.single` equals the old expected result. Make `classify_for_parent` a thin wrapper (`classify_entries_for_parent(...).single` for one item) or state that it remains only for tests and smoke. Name the single-entry quality risk under the list schema in Performance Considerations; the 4.4 live check already covers it.
  - Strength: The regression gate exercises the code production actually runs.
  - Tradeoff: Every existing corpus case is touched (mechanically).
  - Confidence: HIGH — the corpus helper and the view call site are as described.
  - Blind spot: The live single-entry quality under the list schema is unmeasured until 4.4.
- **Decision**: FIXED (Fix A)

### F4 — Correction validates every sub-form; duplicate keys within a batch are accepted

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Blind Spots
- **Location**: Phase 3 §1 ("checks field formats and family scope only, for every sub-form"); Phase 2 §1–2
- **Owner input**: no
- **Detail**: (a) For a `correct-<i>` action, the plan validates every sub-form, including unticked ones. Phase 2 deliberately ignores unticked proposals on save, but here a broken date in an unticked proposal 3 blocks correcting proposal 1. (b) Nothing rejects two sub-forms posting the same `submission_key`, which happens with a tampered form or a copy and paste in devtools. `save_confirmed_entry` returns the first entry for the second item (`entries/services.py:44-46`), so the batch "saves" fewer rows than shown, and the redirect lists the same ID twice.
- **Fix**: On a correction action, validate formats and family scope for the target sub-form only, and carry the others through as posted, with errors only for included ones. Make `BatchReviewForm.is_valid()` reject duplicate `submission_key` values among included sub-forms with a stale-form error. Add a test for each.
- **Decision**: FIXED (Fix A)

### F5 — Phase 3 sequencing and stale references after the confirmed order

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Overview, Phase 3 §1, brief "Prerequisites" / "Open Risks", Current State
- **Owner input**: no
- **Detail**: The confirmed order puts S-03 entirely before S-04. S-03 Phase 2 already adds an optional `correction` field to `EntryReviewForm`, so the batch sub-forms carry it from S-04 Phase 2 onward. Phase 3 §1 "Each sub-form gains an optional `correction` field" is therefore redundant. The brief's contingency "If S-04 ships before S-03, Phase 3 waits" is moot, and the reuse of S-03's "skip schedule rules" needs a named hook, e.g. a `skip_schedule_rules` flag on `EntryReviewForm`, rather than "as in `ProposalCorrectionForm`". The `validation.py:112-179` references are stale. The Overview and brief still say the slice "stays `blocked`" although the owner decided the scope on 2026-10-04.
- **Fix**: Reword Phase 3 §1 to reuse S-03's `correction` field and a named schedule-skip hook. Drop the "ships before S-03" contingency. Fix the line references and the "blocked" sentence.
- **Decision**: FIXED (Fix A)
