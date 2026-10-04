<!-- PLAN-REVIEW-REPORT -->
# Plan Review: School Event Details Implementation Plan

- **Plan**: context/changes/school-event-details/plan.md
- **Mode**: Deep
- **Date**: 2026-10-04
- **Verdict**: SOUND (after fixes; was REVISE)
- **Triage**: applied 2026-10-04
- **Findings**: 0 critical, 2 warnings, 1 observation

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| End-State Alignment | PASS |
| Lean Execution | PASS |
| Architectural Fitness | PASS |
| Blind Spots | WARNING |
| Plan Completeness | WARNING |

## Grounding
Grounding: 12/12 paths ✓ (migration 0007 is the next free number; no other plan in this set adds an `entries` migration), 6/6 symbols ✓ (`SchoolItemKind.required_fields`, `_validate_entry_invariants`, `create_automated_entry`, `classify_for_family`, `_merge_answer`, `MISSING_FIELD_HINTS`), 1 stale line reference ✗ (`validation.py:461-483` — the file has 112 lines; the required-field logic is at `validation.py:73-83`), brief↔plan ✓. Progress↔Phase consistency ✓ (4 phases, 21 rows, no checkboxes outside Progress).

Cross-plan composition (S-01 → S-02 → S-20): S-01 lands first, so its `school_subject` schema field, INSTRUCTIONS sentence, `BackendOutput` field and `require_school_subject` keyword become the base the other two build on. Nothing in S-02 or S-20 conflicts with them, provided S-02 keeps `school_subject` when it rebuilds `BackendOutput` (see S-02 review F4).

## Findings

### F1 — Subject requirement on edit is permanent friction, not only for legacy rows

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Blind Spots
- **Location**: Assumed Decision 4; Phase 1 §3 (`update_family_entry` validates with `require_subject=True`); Phase 3 §1
- **Detail**: The plan frames "editing requires a subject" as a legacy-data cost. However, automated intake will keep creating subject-less school events after this slice: the classification fallback stores a subject only when the model returns one, and the rule path leaves it blank for over-long or unparsed subjects (Decision 5, Phase 4 §1). `update_family_entry` (`entries/services.py:210-243`) validates every managed field on every save. A parent who only reassigns, moves the date of, or retitles an EduVulcan sprawdzian is therefore blocked with "Podaj przedmiot." for as long as automated intake produces such rows. This is behaviour users see, and the PRD (PK-09) does not decide it for edits of automatically created entries.
- **Fix A ⭐ Recommended**: Require a subject on capture confirmation and structured create. On edit, require it only when the stored entry already had a subject, or when the parent sets or changes the school item to one of the four kinds. A blank subject may stay blank otherwise (the same approach as `kept_assignee_id` for deactivated assignees).
  - Strength: Unrelated edits to automated or legacy entries never fail, and new parent-created events always carry a subject.
  - Tradeoff: Adds one more conditional to `_validate_entry_invariants` / form validation and one more test row per kind.
  - Confidence: HIGH — mirrors the existing `kept_assignee_id` exemption in `entries/services.py:153-171`.
  - Blind spot: Whether the owner wants edits to actively push parents to fill in missing subjects.
- **Fix B**: Keep the plan (always require on edit) and state explicitly that it also applies to new EduVulcan entries without a subject.
  - Strength: One simple rule everywhere.
  - Tradeoff: Recurring friction on every edit of an automated school event.
  - Confidence: MED — acceptable only if such edits are rare.
  - Blind spot: How many EduVulcan events arrive without a parsable subject.
- **Owner input**: yes
- **Decision**: FIXED (owner: require subject on edit only if the entry already had one or the parent sets/changes the school kind; always required on capture and manual create; automated entries without subject stay valid)

### F2 — Mandatory `require_school_subject` breaks callers not listed in the plan

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Blind Spots
- **Location**: Phase 2 §2 ("Callers must pass it")
- **Detail**: `classify_output` is also called by `entries/management/commands/classification_smoke.py:80` and twice in `entries/tests/test_classification_live_wire.py`. The plan lists neither, so a required keyword-only argument raises `TypeError` in the smoke command. The live-wire tests are skipped by default, so the full suite would not catch the break.
- **Fix**: Add both files to Phase 2. The smoke command passes `require_school_subject=False`, because it checks provider health and not the parent flow. The live-wire tests pass the value that matches the flow they exercise.
- **Owner input**: no
- **Decision**: FIXED (Fix A)

### F3 — Stale references and cross-slice notes predate the confirmed order

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Current State Analysis; Owner Decisions; Critical Implementation Details ("Cross-slice overlap")
- **Detail**: `validation.py:461-483` does not exist (the file has 112 lines; the logic is at `:73-83`). The owner-decision order omits S-20 (the confirmed order is S-01, S-02, S-20, S-03, …). The overlap note names S-02 and S-03 but not S-20, which also edits `INSTRUCTIONS`, the `content` description and `_translate`. It also says "whichever lands second rebases", although the order is now fixed.
- **Fix**: Correct the line reference, add S-20 to the order and to the overlap note, and state that S-01 lands first and S-02/S-20 build on its schema, `INSTRUCTIONS` sentence and `BackendOutput`/`_merge_answer` fields.
- **Owner input**: no
- **Decision**: FIXED (Fix A)
