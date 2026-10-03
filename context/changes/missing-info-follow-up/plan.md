# Missing Information Follow-Up Implementation Plan

## Overview

Roadmap slice S-04. The PRD's Business Logic says: "If a required value is missing, the application asks a follow-up question before presenting the proposal for confirmation." S-01 left a placeholder for this: a follow-up result goes straight to the prefilled review form with the missing field highlighted. This plan replaces that with a real question step. The parent sees one combined Polish question about every missing value and answers in a single free-text field. The answer is classified once, together with the original instruction, and only the missing values are taken from that second result. If values are still missing, or the provider fails, the flow falls back to the S-01 highlighted review form. "Pomiń" turns the draft into a note.

## Current State Analysis

- What counts as "missing" is already settled and matches the PRD. `validate_output()` returns a `ClassificationFollowUp` with `missing_fields` (`DATE`, `AFFECTED_MEMBER`, `AMBIGUOUS_MEMBER`) (`entries/classification/validation.py:46-91`). Required fields come from `SchoolItemKind.required_fields` plus "every calendar event needs a date" (`entries/classification/types.py:24-65`). Todos and plain notes have no required fields.
- `classify_for_parent()` authorizes an active parent, sends only text, allowed names, the reference date and the locale, then resolves the member locally into a `ParentClassification(result, member)`. It never writes rows (`entries/classification/service.py:61-161`).
- `BackendRequest` carries `submitted_text`, `allowed_member_names`, `reference_date` and `locale` (`entries/classification/backends.py:18-32`). The OpenAI adapter serializes exactly those fields into a Polish JSON input (`entries/classification/openai_backend.py:103-115`). A test asserts the exact input dict (`entries/tests/test_openai_backend.py:271`).
- The capture flow keeps no state between steps. `capture` classifies and renders `proposal` / `follow_up` / `unavailable` through `review_form_from_classification()`. `confirm` re-validates everything through `EntryReviewForm` and saves idempotently (`entries/views.py:75-148`, `entries/forms.py:205-237`).
- The follow-up branch today is S-01's placeholder: `MISSING_FIELD_HINTS` highlights the fields in the review form (`entries/forms.py:20-24`).
- The DEBUG states page renders every capture state from synthetic data, including `follow_up` and `follow_up_member` (`entries/views.py:166-265`). A test lists the expected state names (`entries/tests/test_states_view.py:11`).
- Existing tests pin the S-01 follow-up behaviour (`entries/tests/test_capture_views.py:246-333`).

## Desired End State

A parent submits "Kasia ma kartkówkę z matematyki" and, instead of a review form, sees a question: "Kiedy jest „Kartkówka z matematyki”?" with one text field, "Dalej" and "Pomiń". After typing "w piątek", the parent sees the normal proposal with the date filled in, then confirms and saves as before. If the answer does not supply the value ("nie wiem", an unknown name, a provider timeout), the parent lands on the S-01 highlighted review form. "Pomiń" opens the review form prefilled as a note. Nothing is written before confirmation, and each step answers within the 30-second NFR.

Verify with the automated suites below, the DEBUG states page at 360 px, and one live check with OpenAI.

### Key Discoveries:

- Rules for missing fields already live in `SchoolItemKind` and `validate_output()`. The merge reuses them instead of duplicating them (`entries/classification/types.py:36-65`).
- `classify_output()` + `_resolve_member()` already produce a validated, locally resolved result. The answer path reuses them and only picks fields from the result (`entries/classification/service.py:113-161`).
- `EntryReviewForm` treats every posted value as untrusted, and `confirm` re-checks rules on the server. The question step can carry the draft in hidden fields with the same guarantee (`entries/forms.py:107-150`).
- The adapter's exact-input test means the new keys must be **absent** when there is no follow-up (`entries/tests/test_openai_backend.py:271`).
- Lesson: UI copy and OpenAI prompt text are Polish, code is English (`context/foundation/lessons.md`).

## What We're NOT Doing

- No new follow-up rules beyond the PRD's (tests/homework/quizzes, substitutions/room changes, calendar events). The roadmap's open question about other cases stays open.
- No second question round: after one answer the flow always moves on to a proposal, the highlighted review form, or the note.
- No re-classification of the whole instruction: the answer may only fill the missing values. Type, title, school item, time and already-known values come from the first draft.
- No follow-up for automated EduVulcan intake. `classify_for_family` keeps turning follow-ups into general notes.
- No server-side draft storage, signing or sessions. The draft travels in hidden fields, as in S-01.
- No JavaScript, no new model or migration, no changes to structured create/edit (S-02) or the child view (S-03).
- No fix for two members sharing one display name. A typed name cannot tell them apart, so that case falls back to the review form (see Open Risks in the brief).

## Implementation Approach

Extend the classification boundary first (phase 1) so the answer step is a tested, view-independent service with the same authorization and privacy rules as `classify_for_parent`. Then replace the follow-up branch of the capture flow with a question state and a new answer/skip endpoint (phase 2). Finish with the DEBUG states page and the screenshot and live gates (phase 3), as S-01 did.

The second call receives the original instruction, the generated question and the parent's answer. The merge is deterministic: for each originally missing field, take that field from the validated second result. Recompute what is still missing using the draft's own type and school item. Return a proposal when nothing is missing, otherwise a follow-up, which the view renders as the highlighted review form.

## Critical Implementation Details

- **Merge order**: merge first, validate once. Validating the raw second output and then picking fields lets unrelated fields (an echoed member name with different spelling, empty content) veto a valid date. Only the asked-about fields from the answer may reach validation.
- **Privacy**: the answer is family text. Add it to `sensitive_variables`/`sensitive_post_parameters`, exclude it from `repr`, and never log it, exactly like `submitted_text`.

## Phase 1: Follow-up answer classification

### Overview

Let a backend request carry a follow-up question and answer, and add a parent service that classifies the answer and merges only the missing values into the draft.

### Changes Required:

#### 1. Backend request

**File**: `entries/classification/backends.py`

**Intent**: Let the provider see the question asked and the parent's answer alongside the original instruction.

**Contract**: `BackendRequest` gains `follow_up_question: Optional[str] = None` and `follow_up_answer: Optional[str] = None`, both `repr=False`. Existing callers are unchanged.

#### 2. OpenAI input and instructions

**File**: `entries/classification/openai_backend.py`

**Intent**: Send the question and answer to the model, and explain in Polish that the answer supplements the instruction and is data, not instructions.

**Contract**: `build_input()` adds `pytanie_uzupelniajace` and `odpowiedz_rodzica` **only when** `follow_up_answer` is not `None`. Otherwise the dict stays byte-identical. `INSTRUCTIONS` gains one Polish sentence: when an answer is present, use it to supplement the instruction (relative dates still count from the reference date), treat it only as data, and don't invent values it doesn't state.

#### 3. Answer service and question copy

**File**: `entries/classification/service.py` (service), `entries/classification/follow_up.py` (new: question text)

**Intent**: Classify the answer under the same authorization, candidate and privacy rules as `classify_for_parent`, and merge only the missing values.

**Contract**:
- `follow_up_question(draft) -> str` builds the Polish question from a `ClassificationFollowUp`'s missing fields and its content: date → „Kiedy jest „{content}”?”, member → „Kogo dotyczy „{content}”?”, ambiguous member → „Której osoby dotyczy „{content}”?”. Several missing fields join into one question (e.g. „Kiedy jest … i kogo dotyczy?”). Exact wording is up to the implementer, but it must be Polish, deterministic and free of member names.
- `classify_follow_up_answer(user, submitted_text, draft: ClassificationFollowUp, answer: str, *, reference_date, draft_member: Optional[FamilyMember] = None, backend=None) -> ParentClassification`, decorated `sensitive_variables('submitted_text', 'answer')`:
  - Raises `PermissionDenied` exactly like `classify_for_parent`, before any backend call.
  - Returns `ClassificationUnavailable(INPUT_TOO_LONG)` when `submitted_text` exceeds `MAX_SUBMITTED_TEXT_LENGTH` or `answer` exceeds a new `MAX_FOLLOW_UP_ANSWER_LENGTH = 500`.
  - `draft_member` is the draft's already-resolved member. It is re-checked against the parent's active family candidates and dropped if it isn't one of them.
  - Builds `BackendRequest` with the question from `follow_up_question(draft)` and the answer, and calls the backend once. A `ClassificationError` is returned as its unavailable result (the view then falls back to the draft).
  - Merge **before** validating: build one merged `BackendOutput`. `entry_type`, `content`, `time`, `school_item` and every value that was not missing come from the draft, with `member_name` = `draft_member.display_name` when it is set. Only the missing fields come from the backend output: its `date` for `DATE`, its `member_name` for `AFFECTED_MEMBER`/`AMBIGUOUS_MEMBER`. `grounded` also comes from the backend output, and a `None` output `entry_type` contributes nothing. Then run `classify_output` + `_resolve_member` on the merged output exactly once. That single validation recomputes what is still missing from the draft's own type/school item, so a misspelled or echoed name, or a different title or type in the answer's result, can't discard a valid answer to a field that was asked about. The result is `ClassificationProposal` when nothing remains, `ClassificationFollowUp` with the remaining fields, or unavailable (e.g. the answer names someone outside the family).

#### 4. Tests

**File**: `entries/tests/test_follow_up_answer.py` (new), `entries/tests/test_openai_backend.py`

**Intent**: Pin the merge rules, authorization, privacy and the unchanged adapter input.

**Contract**: fake-backend tests for: missing date filled → proposal with the draft's title/type/school item kept; second result with a different type/title is ignored; date missing and the second output echoes the known member with a different spelling → the date is still filled (no unavailable); date and member both missing, answer gives only date → follow-up with member still missing; unknown name → unavailable; ambiguous name → still missing; provider timeout → unavailable; child/outsider/anonymous → `PermissionDenied` with zero backend calls; too-long answer → `INPUT_TOO_LONG` with zero backend calls; the backend request contains question and answer; zero database writes. Adapter tests: the input has the two keys when an answer is present, and the existing exact-dict test still passes without them.

### Success Criteria:

#### Automated Verification:

- Follow-up answer service and question tests pass: `uv run python manage.py test entries.tests.test_follow_up_answer`
- Adapter tests pass, including the unchanged input without a follow-up: `uv run python manage.py test entries.tests.test_openai_backend`
- Full suite and Django checks pass: `uv run python manage.py test` and `uv run python manage.py check`

#### Manual Verification:

- Reading `follow_up_question` output for date, member, ambiguous and combined cases confirms natural Polish wording

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 2: Question step in the capture flow

### Overview

Replace the follow-up branch of `capture` with a question state, and add an answer/skip endpoint that leads to the proposal, the highlighted review form, or a note.

### Changes Required:

#### 1. Follow-up answer form

**File**: `entries/forms.py`

**Intent**: Carry the original text and the draft between requests as untrusted hidden fields, and collect the answer.

**Contract**: `FollowUpAnswerForm(membership, …)` with hidden `text` (≤ `MAX_SUBMITTED_TEXT_LENGTH`), hidden draft fields `entry_type`, `content`, `date`, `time`, `school_item`, `assigned_member` (family-scoped, active, like `EntryFieldsForm`), hidden `missing` (multiple choice over `MissingField` values, at least one), and visible `answer` (Textarea, ≤ `MAX_FOLLOW_UP_ANSWER_LENGTH`, label = the generated question). `answer` is required only when the action is not skip. Helpers: `follow_up_form_from_classification(membership, outcome, text)` builds it with initial data from a `ParentClassification`, and `draft_from_form(form) -> (ClassificationFollowUp, Optional[FamilyMember])` rebuilds the draft. `draft_from_form` drops any posted `missing` value the rules wouldn't produce for the draft's type/school item, except `AMBIGUOUS_MEMBER` when no member is set. `skip_review_form(membership, draft, member)` returns an `EntryReviewForm` prefilled as a note: draft content, known date/time/member kept, `school_item` empty, fresh `submission_key`. `review_form_from_classification` keeps its current behaviour for the fallback paths.

#### 2. Views and route

**File**: `entries/views.py`, `entries/urls.py`

**Intent**: Ask the question instead of showing the highlighted form, and route the answer.

**Contract**:
- `capture`: a `ClassificationFollowUp` result renders state `question` with the follow-up form, not `follow_up`. Other branches are unchanged.
- If `draft_from_form` leaves no missing field (a tampered or stale form), `answer` renders the `proposal` review form from the draft directly, with no backend call.
- New `answer` view at `POST entries/answer/` (name `entries:answer`), with `require_POST`, `login_required`, parent-only (403 otherwise) and `sensitive_post_parameters('text', 'content', 'answer')`. An invalid form re-renders `question` with errors. `action=skip` renders state `skipped` (the review form from `skip_review_form`) plus a Polish notice („Brakujące dane pominięte — wpis zostanie zapisany jako notatka.”). Otherwise it calls `classify_follow_up_answer`:
  - Proposal → state `proposal`.
  - Follow-up (still missing) → state `follow_up` (S-01 highlighted review form, built from the merged draft).
  - Unavailable → state `follow_up` from the original draft, plus a Polish notice („Nie udało się rozpoznać odpowiedzi. Uzupełnij brakujące pola.”).
- Saving still happens only through `confirm`.

#### 3. Templates

**File**: `entries/templates/entries/_follow_up_form.html` (new), `entries/templates/entries/capture.html`

**Intent**: Render the question as its own partial so the capture page and the states page reuse it.

**Contract**: The partial posts to `entries:answer` with `data-state-part="question"`. It shows the question as the label of the `answer` field via `_field.html`, a short muted summary of what was recognized (type and title), all hidden fields, the buttons „Dalej” (primary) and „Pomiń” (`name="action" value="skip"`, secondary, `formnovalidate`), and the link „Zacznij od nowa”. `capture.html` renders the partial when `follow_up_form` is present and the notice for `skipped`/`follow_up` when one is given.

#### 4. Tests

**File**: `entries/tests/test_capture_views.py`, `entries/tests/test_follow_up_views.py` (new)

**Intent**: Pin the new flow end to end with a fake backend, and rewrite the two S-01 capture tests that expected the highlighted review form, `test_follow_up_marks_missing_date_and_saves_once_filled` and `test_ambiguous_member_asks_to_choose_a_person` (`entries/tests/test_capture_views.py:247`, `:269`), to expect the `question` state instead.

**Contract**: the follow-up classification renders `question` with no review form; answer → proposal → confirm saves exactly one entry with the merged date; date+member missing with only the date answered → highlighted review form with the member hint; provider unavailable → highlighted review form plus notice; skip → note review form keeping known values, `school_item` empty, and saving creates a note; skip with an empty answer is accepted; too-long answer → field error; tampered hidden `assigned_member` from another family → form error; nothing missing after recomputation → proposal review with zero backend calls; child, other family and anonymous get 403/redirect on `entries:answer`; nothing is written before confirm. Acceptance-style case (date 2026-09-19): „Kasia ma kartkówkę z matematyki” + „w piątek” → proposal dated 2026-09-25 for Kasia.

### Success Criteria:

#### Automated Verification:

- Capture and follow-up view tests pass: `uv run python manage.py test entries.tests.test_capture_views entries.tests.test_follow_up_views`
- Full suite, Django checks and migration check pass: `uv run python manage.py test`, `uv run python manage.py check`, `uv run python manage.py makemigrations --check --dry-run`

#### Manual Verification:

- With a stubbed or live backend, a parent on a phone-width browser answers a missing-date question and saves the entry, and „Pomiń” leads to a note

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 3: States page and screenshot gate

### Overview

Show the new states on the DEBUG kitchen sink, screenshot them at phone width, and check the flow once against live OpenAI.

### Changes Required:

#### 1. Kitchen-sink states

**File**: `entries/views.py`, `entries/templates/entries/states.html`, `entries/tests/test_states_view.py`

**Intent**: Make every new state visible from synthetic data in one place.

**Contract**: add sections `question` (missing date), `question_combined` (date and member missing), `answer_unavailable` (highlighted review plus notice) and `skipped` (note review plus notice). They reuse the same partials as `capture.html`, use fictional names, make no backend call and write nothing. `STATE_NAMES` in the test includes the new states.

### Success Criteria:

#### Automated Verification:

- States page tests pass: `uv run python manage.py test entries.tests.test_states_view`
- Full suite passes: `uv run python manage.py test`

#### Manual Verification:

- Screenshots of the four new states at 360 px width are taken and saved under `context/changes/missing-info-follow-up/screenshots/`, with nothing clipped or overflowing
- A live run with an OpenAI key: a missing-date instruction plus a relative-date answer („w piątek”) yields the correct date within 30 s per step

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful.

---

## Testing Strategy

### Unit Tests:

- Merge rules: only the missing fields change, the rest is recomputed from the draft's rules, and unknown/ambiguous/provider failures are handled.
- Question copy for each missing field and the combined case.
- Adapter input with and without a follow-up.

### Integration Tests:

- Capture → question → answer → proposal → confirm, with a single saved entry.
- Fallbacks: still missing, provider unavailable, skip to note.
- Access: parent only. Child, other family and anonymous are refused on `entries:answer`.
- No writes before confirm. The answer never appears in logs (assert with `assertLogs`/`assertNoLogs` around the answer call, as the S-01 privacy tests do).

### Manual Testing Steps:

1. On a 360 px viewport, submit „Kasia ma kartkówkę z matematyki” and check that the question appears with „Dalej” and „Pomiń”.
2. Answer „w piątek”, then check the proposal date and save.
3. Repeat and answer „nie wiem”. Check that the highlighted review form appears.
4. Repeat and press „Pomiń”. Check that the note review form appears and saves.

## Performance Considerations

The answer step makes at most one extra provider call, under the existing 25-second deadline per call, so each screen still meets the 30-second NFR. The skip path makes no call.

## Migration Notes

No schema change. Rolling back means reverting the code. Saved entries are unaffected.

## References

- PRD Business Logic and NFR 30 s: `context/foundation/prd.md`
- Roadmap S-04: `context/foundation/roadmap.md`
- S-01 plan (placeholder follow-up, stateless review): `context/archive/2026-09-27-first-school-event-capture/plan.md`
- F-02 plan (classification boundary and privacy): `context/archive/2026-09-24-classification-privacy-boundary/plan.md`
- Follow-up rules: `entries/classification/validation.py:46-91`, `entries/classification/types.py:24-65`
- Capture flow: `entries/views.py:75-148`, `entries/forms.py:205-237`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Follow-up answer classification

#### Automated

- [x] 1.1 Follow-up answer service and question tests pass — 382506e
- [x] 1.2 Adapter tests pass, including the unchanged input without a follow-up — 382506e
- [x] 1.3 Full suite and Django checks pass — 382506e

#### Manual

- [x] 1.4 Reading `follow_up_question` output for date, member, ambiguous and combined cases confirms natural Polish wording — 382506e

### Phase 2: Question step in the capture flow

#### Automated

- [x] 2.1 Capture and follow-up view tests pass
- [x] 2.2 Full suite, Django checks and migration check pass

#### Manual

- [x] 2.3 With a stubbed or live backend, a parent on a phone-width browser answers a missing-date question and saves the entry, and „Pomiń” leads to a note

### Phase 3: States page and screenshot gate

#### Automated

- [ ] 3.1 States page tests pass
- [ ] 3.2 Full suite passes

#### Manual

- [ ] 3.3 Screenshots of the four new states at 360 px width are taken and saved under `context/changes/missing-info-follow-up/screenshots/`, with nothing clipped or overflowing
- [ ] 3.4 A live run with an OpenAI key: a missing-date instruction plus a relative-date answer („w piątek”) yields the correct date within 30 s per step
