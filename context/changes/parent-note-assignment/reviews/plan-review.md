<!-- PLAN-REVIEW-REPORT -->
# Plan Review: Parent Note Assignment Implementation Plan

- **Plan**: context/changes/parent-note-assignment/plan.md
- **Mode**: Deep
- **Date**: 2026-10-04
- **Verdict**: SOUND
- **Triage**: applied 2026-10-04
- **Findings**: 0 critical, 2 warnings, 2 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| End-State Alignment | WARNING |
| Lean Execution | PASS |
| Architectural Fitness | PASS |
| Blind Spots | WARNING |
| Plan Completeness | WARNING |

## Grounding
Grounding: 7/7 paths ✓ (`entries/forms.py`, `entries/services.py`, `entries/classification/service.py`, `entries/api_views.py`, `entries/eduvulcan/children.py`, `entries/tests/test_classification_service.py`, `entries/tests/test_states_view.py`). 6/6 symbols ✓: `EntryFieldsForm.__init__` queryset (forms.py:84-88), `EntryEditForm` kept assignee (forms.py:212-220), follow-up queryset (forms.py:~307), `_validate_entry_invariants` (services.py:91-98), `_active_family_members` and `_resolve_member` (service.py:243-268), `STATES_MEMBER_CHOICES` (views.py:244). `serialize_entry` emits only `display_name`, and `child_entries` filters `assigned_member=membership` (services.py:~262). The partial unique constraint is per user, so a second parent with its own user is valid. brief↔plan ✓ for phases and decisions. Brief and plan header text is stale (F4). Progress↔Phase ✓: 5+6 steps match the success criteria, and phase blocks contain no checkboxes.

## Findings

### F1 — Regression matrix misses write paths that exist when S-07 lands

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: End-State Alignment
- **Location**: Phase 1 — items 2–3 (form/service matrix, classification resolution)
- **Detail**: Current State lists the follow-up form as a parent write path that uses the same queryset (`entries/forms.py:~307`, `/entries/answer/`), but no matrix item covers it. In the confirmed order, S-03 `free-text-proposal-correction` and S-04 `multi-entry-text-capture` land before S-07. S-03 resolves the member again through `_resolve_member` with `current_member` (its plan, lines 112-117). S-04 adds `batch_review_form_from_classification` and a new batch save endpoint (its plan, lines 111-177). S-07's goal is to prove "every parent write path" for parent assignees, but those three paths stay unproven, so all success criteria could pass while a parent assignee is dropped in the batch save or the correction merge.
- **Fix**: Add the follow-up answer to matrix item 3: an answer, or a skip with a parent preselected, saves the parent assignee. Add a conditional item: "if S-03/S-04 have landed, a correction keeps a parent `current_member`, and the batch review offers and saves a parent assignee per proposal". Name the concrete test modules when they exist, and add them to the targeted test command.
  - Strength: It covers the actual write surface at implementation time, which the order in `roadmap-future.md` fixes.
  - Tradeoff: A few more tests, and the item depends on what has merged.
  - Confidence: HIGH — the paths are documented in the S-03/S-04 plans and in `entries/urls.py:9-10`.
  - Blind spot: The final S-04 endpoint names are unknown until S-04 is implemented.
- **Owner input**: no
- **Decision**: FIXED (Fix A)

### F2 — "dla mnie" deferral points to S-02, which does not take it

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Blind Spots
- **Location**: Assumed Decision 3; What We're NOT Doing (bullet 1); brief "Key Decisions"
- **Detail**: Assumed Decision 3 says that requester identity and "dla mnie" resolution "belong with S-02 `classification-short-names`". The S-02 plan has no requester, self-reference or "dla mnie" handling, and it explicitly excludes "Changes to who may be assigned an entry. Note assignment is S-07." (`classification-short-names/plan.md:58`). So the deferral lands in no slice. Today a parent who types "dla mnie" gets an unassigned proposal ("Cała rodzina"). That is visible behaviour on the main capture path that US-03 users are likely to try.
- **Fix A ⭐ Recommended**: Keep the manual pick in the review form for this milestone. Reword Decision 3 to "deferred, not owned by any current slice", and record it as a parked follow-up in `roadmap-future.md`.
  - Strength: It keeps S-07 test-only and keeps the OpenAI payload unchanged, as S-01–S-04/S-20 already expect.
  - Tradeoff: "dla mnie" keeps producing "Cała rodzina" until the follow-up ships.
  - Confidence: HIGH — the review form already lists the requester.
  - Blind spot: How often parents actually type self-references is unknown.
- **Fix B**: Add requester resolution to S-07: send the requester's display name as a Polish payload hint and map "dla mnie"/"ja" to the requester.
  - Strength: Natural-language self-assignment works.
  - Tradeoff: It changes the shared classification payload and prompt after S-01–S-04/S-20 have touched them, and needs a new acceptance corpus.
  - Confidence: MEDIUM — the merge cost against the classification chain is not measured.
  - Blind spot: The interaction with S-04's multi-entry outputs.
- **Owner input**: yes
- **Decision**: FIXED (owner: Fix B — resolve "dla mnie"/"mi"/"ja" to the requester via `autor_polecenia`; new Phase 3)

### F3 — Wrong and missing test modules in the classification and isolation items

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 1 — items 3 and 4; Success Criteria command 1.4
- **Detail**: Item 3 offers `entries/tests/test_family_classification.py` as a home for the capture-flow test. That module tests `classify_for_family`, the EduVulcan family fallback that acts for no user, not the parent capture flow. Child isolation at the service layer lives in `entries/tests/test_child_entries.py`, which the targeted command 1.4 does not run. Follow-up tests (`test_follow_up_views.py`, see F1) are also missing from 1.4.
- **Fix**: Name `entries/tests/test_capture_views.py` for capture/confirm and add `test_child_entries` and `test_follow_up_views` to the 1.4 command.
- **Owner input**: no
- **Decision**: FIXED (Fix A)

### F4 — Stale owner-decision text and "blocked" status

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Owner Decisions (2026-10-04); plan-brief "Open Risks & Assumptions"
- **Detail**: The confirmed order in the plan omits S-20, while `roadmap-future.md:43-60` places S-20 third. The brief says both "Owner review confirmed…" and "Implementation is **blocked on owner confirmation** (roadmap status: blocked)", but the roadmap row has status `planning` with `Blockers: —` and records S-07 as resolved.
- **Fix**: Update the order to include S-20 and drop the "blocked" sentence from the brief.
- **Owner input**: no
- **Decision**: FIXED (Fix A)
