<!-- PLAN-REVIEW-REPORT -->
# Plan Review: Free-Text Proposal Correction Implementation Plan

- **Plan**: context/changes/free-text-proposal-correction/plan.md
- **Mode**: Deep
- **Date**: 2026-10-04
- **Verdict**: SOUND (after triage; was REVISE)
- **Triage**: applied 2026-10-04
- **Findings**: 1 critical, 6 warnings, 1 observation

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| End-State Alignment | FAIL |
| Lean Execution | PASS |
| Architectural Fitness | WARNING |
| Blind Spots | WARNING |
| Plan Completeness | PASS |

## Grounding
Grounding: 12/12 paths ✓ (types.py, backends.py, openai_backend.py, service.py, forms.py, views.py, urls.py, _review_form.html, test_openai_backend.py, test_capture_views.py, test_states_view.py, test_classification_acceptance.py), 9/9 symbols ✓ (`_merge_answer`, `_known_member_name`, `classify_output`, `_resolve_member`, `_require_schedule_fields`, `review_form_from_classification`, `MAX_SUBMITTED_TEXT_LENGTH`, `_date_is_grounded`, `follow_up` state). 1 stale line ref: `validation.py:112-162` (the file has 112 lines; `validate_output` is at 45-95). Brief↔plan ✓. Progress↔Phase ✓ (3 phases, all criteria mapped, no checkboxes in phase blocks).

Cross-slice composition was checked against the contracts in `school-event-details` (S-01), `classification-short-names` (S-02) and `title-keeps-action-only` (S-20), which all land before S-03. The plan names none of them except S-01, in "What We're NOT Doing".

## Findings

### F1 — Correction merge drops the S-01 school subject

- **Severity**: ❌ CRITICAL
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: End-State Alignment
- **Location**: Phase 1 §1 (`ProposalValues`), §2 (`obecna_propozycja`), §3 (merge); Phase 2 §1
- **Owner input**: no
- **Detail**: S-01 lands first. It adds `school_subject` to `BackendOutput`, `ClassificationProposal`/`FollowUp`, `StructuredClassification`, `EntryFieldsForm` and the review form rows. It also makes `school_item` a visible select with a strict mismatch error, and makes `classify_output(..., require_school_subject=...)` a required keyword (S-01 plan, Phase 2 §2–3, Phase 3 §1). The S-03 plan still describes the pre-S-01 code. `ProposalValues(entry_type, content, date, time, school_item, member_name)` has no subject, `obecna_propozycja` does not send it, and the merge builds a `BackendOutput` without it. So every correction of a school event (for example "zmień datę na piątek" on a „Sprawdzian, matematyka”) loses the subject the parent already has. The result becomes a `SCHOOL_SUBJECT` follow-up with the subject field emptied. That violates US-10's "unmentioned fields are preserved". The service call also does not pass the now-required `require_school_subject=True`. Assumed Decision 3's rationale ("hidden school item … not a field the parent sees") and Key Discovery 2 (silent clearing in `EntryReviewForm.clean`) are stale after S-01.
- **Fix**: Add `school_subject` to `ProposalValues` (repr=False), to `proposal_values_from_form`, and to `obecna_propozycja` (`przedmiot`). Carry it through the merge from `current` unless it is a correctable field (see F2). Call `classify_output(..., require_school_subject=True)` as `classify_for_parent` does after S-01. Update Assumed Decision 3, Key Discovery 2 and Current State to the post-S-01 form, where the school item is visible and a mismatch is a strict error. Add a test: a date-only correction of a school event keeps its school item and subject.
  - Strength: Restores the preserve-unmentioned guarantee on the slice that lands immediately before.
  - Tradeoff: Touches the same four contract objects S-01 already extended. S-03 must rebase on S-01 rather than on today's code.
  - Confidence: HIGH — S-01's contract explicitly threads `school_subject` through these exact types.
  - Blind spot: The final S-01 field names are planned, not yet merged. Re-check them when S-01 lands.
- **Decision**: FIXED (Fix A)

### F2 — Should text correction also change school type and subject?

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: End-State Alignment
- **Location**: Assumed Decision 3; Phase 1 §2 (`changed_fields` literal)
- **Owner input**: yes
- **Detail**: PK-10 says "date or any other entry field". After S-01, the review form shows „Element szkolny” and „Przedmiot” as editable fields. They are required for the four school event kinds, and a correction may be the natural way to fill a highlighted missing subject („przedmiot to fizyka”, „to kartkówka, nie sprawdzian”). The plan's `changed_fields` literal allows only `entry_type, content, date, time, member_name`. A subject correction therefore always ends as "Nie udało się zastosować poprawki". The only rationale for excluding them (the field is not visible) no longer holds.
- **Fix A ⭐ Recommended**: Make `school_item` and `school_subject` correctable. Add them to the `changed_fields` literal and the merge. A `school_item` whose type conflicts with the merged `entry_type` makes the correction not applied. The subject is trimmed and capped at `SCHOOL_SUBJECT_MAX_LENGTH`. The notice labels come from the S-01 form labels.
  - Strength: Matches PK-10 "any other entry field" and lets a correction fill S-01's highlighted subject.
  - Tradeoff: Two more schema fields and test cases. School-type mistakes from the model become possible but are visible before saving.
  - Confidence: MED — depends on the owner's reading of "any other field".
  - Blind spot: The live model quality for subject declension („z fizyki” → „fizyka”) is untested.
- **Fix B**: Keep them preserve-only (carried unchanged per F1), and leave a school type or subject change to manual editing.
  - Strength: Smaller scope; the model can never alter school metadata.
  - Tradeoff: A highlighted missing subject cannot be fixed by text, which is the PK-10 use case.
  - Confidence: HIGH — mechanically simple.
  - Blind spot: None significant.
- **Decision**: FIXED (owner: Fix A — school type and subject correctable; a mismatched school type is rejected with a Polish message, proposal unchanged)

### F3 — Member corrections ignore S-02 short-name resolution

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Architectural Fitness
- **Location**: Phase 1 §3 (merge, "unknown member" rule); Phase 3 live check („to dla Tymka”)
- **Owner input**: no
- **Detail**: S-02 adds `member_mention` and `member_ambiguous` to `BackendOutput` and `StructuredClassification`. It also adds `_apply_member_mention(output, candidates)`, which takes precedence over `member_name`, and S-02 applies it in the follow-up merge only when the draft was missing a member (S-02 plan §3). S-03's merge does not mention any of this. Two problems follow. (a) If the merged output carries the model's `member_mention` while `member_name` is not in `changed_fields`, `_apply_member_mention` can silently reassign the current member. (b) If it is never applied, „to dla Tymka” and „dla Hani” depend on the model echoing the exact full name. An ambiguous short name has no defined outcome: the plan says only "an unknown name is not applied".
- **Fix**: In the merge, take `member_name` and `member_mention` from the output only when `member_name` is in `changed_fields`. Otherwise set `member_mention=None` and `member_ambiguous=False`. Run `_apply_member_mention` on the merged output only in that case, mirroring S-02's follow-up rule. An ambiguous result is applied as an `AMBIGUOUS_MEMBER` highlight („Wybierz osobę.”), and zero matches with an unknown name stays not applied. Add tests for a diminutive correction, an ambiguous one, and a date-only correction whose output carries a stray mention.
- **Decision**: FIXED (Fix A)

### F4 — S-20 owns `DATE_RULES`; the title guard's behaviour in correction mode is undefined

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Architectural Fitness
- **Location**: Phase 1 §2 (`DATE_RULES`, `_translate`); Manual 1.4; brief "Open Risks"
- **Owner input**: no
- **Detail**: S-20 (which lands before S-03) creates the public `DATE_RULES` constant, appends it to `INSTRUCTIONS`, and adds a deterministic title guard (`strip_extracted_phrases`) in `_translate` after grounding. The plan still says "New module constant `DATE_RULES` … If S-04 has already added it, reuse it", and step 1.4 asks for a review of the `DATE_RULES` wording, which this slice no longer owns. More importantly, the plan changes `_translate` for corrections without saying whether the S-20 guard runs. If it runs on every correction output, it strips the member's name or the correction's `date_source` phrase from a title copied verbatim from `obecna_propozycja`. That is harmless only because the merge ignores `content` when it is not in `changed_fields`. When `content` is changed, the guard's inputs (which `date_source`, which member) are unspecified.
- **Fix**: State that S-03 reuses S-20's `DATE_RULES` unchanged and only appends it to `CORRECTION_INSTRUCTIONS`. Re-scope 1.4 to the `CORRECTION_INSTRUCTIONS` wording only. Do not change the step title; add an inline note instead. In correction mode, apply the S-20 guard only when `content` is in `changed_fields`, with the accepted correction `date_source` and the output `member_name`/`member_mention`. Otherwise leave the copied content untouched. Update the brief's "created by whichever of S-03 or S-04 lands first".
- **Decision**: FIXED (Fix A)

### F5 — `grounded` and `date_source` semantics are not redefined for corrections

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Blind Spots
- **Location**: Phase 1 §2 (`StructuredCorrection` "same fields as `StructuredClassification`"), §3 (merge)
- **Owner input**: no
- **Detail**: `validate_output` rejects `grounded=False` as `UNSUPPORTED_CONTENT` (`entries/classification/validation.py:52-53`). The existing descriptions say grounded means "każda zwrócona informacja wynika z polecenia", and `date_source` must be copied from "polecenie albo odpowiedz_rodzica" (`openai_backend.py:81-94`). A correction has neither key. Its unchanged fields come from `obecna_propozycja`, which is not in the correction text, so a literal-minded model returns `grounded=false` and every correction fails. Alternatively, the model may copy `date_source` from the proposal and lose the grounded date. The plan does not say which `grounded` value the merged `BackendOutput` uses. `_merge_answer` uses `output.grounded`.
- **Fix**: Give `StructuredCorrection` its own Polish descriptions. `grounded` means the values in `changed_fields` follow from `poprawka`, and copied values count as given. `date_source` is copied literally from `poprawka`, and is null when the date is unchanged. Set the merged `grounded` explicitly to `output.grounded`. Add an adapter test where the unchanged fields are copied and `grounded=true`, and a service test where `grounded=false` is not applied.
- **Decision**: FIXED (Fix A)

### F6 — Null `entry_type` in a correction becomes a note containing the correction text

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Blind Spots
- **Location**: Phase 1 §1 (`submitted_text` = correction), §2 (`StructuredCorrection.entry_type` nullable), §3 (merge then validate)
- **Owner input**: no
- **Detail**: `StructuredCorrection` copies the nullable `entry_type`. If the model lists `entry_type` in `changed_fields` with null, the merged output has `entry_type=None`. `validate_output` then returns `_general_note(request)` with `content=request.submitted_text` (`validation.py:49-50`, `:108-112`). The plan sets `submitted_text` to the correction text. The parent would see the proposal replaced by a note reading „zmień datę na 15 października”, reported as applied.
- **Fix**: Make `StructuredCorrection.entry_type` non-nullable (`EntryTypeValue`), or treat a null `entry_type` in `changed_fields` as not applied before the merge. Add a service test.
- **Decision**: FIXED (Fix A — non-nullable entry_type)

### F7 — A typed but unapplied correction is silently ignored on „Zapisz wpis”

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Blind Spots
- **Location**: Phase 2 §1 ("`confirm` ignores it"), §3 (two submits in one form)
- **Owner input**: yes
- **Detail**: The correction box and „Zapisz wpis” share one `<form>`, and „Zapisz wpis” is the default submit. A parent who types „zmień datę na 15 października” and taps „Zapisz wpis” (or uses Enter with S-05, which makes Enter submit on the phone) saves the old date without warning. The plan explicitly makes `confirm` ignore the field. That defeats the "nothing changes behind the parent's back" intent, and it becomes more likely once S-05 lands.
- **Fix A ⭐ Recommended**: Make `confirm` refuse to save when `correction` is non-blank. Re-render `invalid` with the field error „Masz niezastosowaną poprawkę — naciśnij „Popraw” albo wyczyść pole.” and a fresh key. Add a view test.
  - Strength: Nothing is saved that differs from what the parent asked for, and it costs one extra tap.
  - Tradeoff: An extra step when a parent typed a correction but changed their mind.
  - Confidence: HIGH — trivial form-level check.
  - Blind spot: Interaction with S-05's Enter-to-submit has not been designed.
- **Fix B**: Keep the plan as written (ignore the correction on save).
  - Strength: The simplest option; the save path is unchanged.
  - Tradeoff: Silent loss of the parent's typed intent.
  - Confidence: HIGH — no work.
  - Blind spot: How often parents mis-tap on a phone.
- **Decision**: FIXED (owner: Fix A — save refused with a Polish message while the correction box has text)

### F8 — Redundant failure outcome, unreachable length path, stale references

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 1 §3, Phase 2 §2, Current State, Overview
- **Owner input**: no
- **Detail**: (a) When not applied, the service rebuilds the unchanged current values as a `ParentClassification`, which is under-specified for incomplete drafts (proposal or follow-up?). The view ignores it and re-renders the posted values. (b) The form field's `max_length=MAX_CORRECTION_LENGTH` rejects a too-long correction before the service, so the view's `INPUT_TOO_LONG` → „Poprawka jest za długa.” branch is only reachable for direct service calls. Set the same message as the form's `max_length` error. (c) `validation.py:112-162` is a stale reference (`validate_output` is at 45-95). (d) The Overview and the brief still say the slice "stays `blocked`" pending owner confirmation, although the owner decided the scope on 2026-10-04 and the roadmap status is `planning`.
- **Fix**: Return `outcome=None` (or drop it) when `applied=False` and let the view own the re-render. Put the „Poprawka jest za długa.” text on the form's `max_length` error. Correct the line reference and the "blocked" sentence.
- **Decision**: FIXED (Fix A)
