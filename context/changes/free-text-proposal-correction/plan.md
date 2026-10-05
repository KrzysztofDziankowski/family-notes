# Free-Text Proposal Correction Implementation Plan

## Overview

Future roadmap slice S-03 (PK-10, US-10 in `context/foundation/prd-v2.md`). After capture shows a proposal for review, the parent can type a correction such as „zmień datę na 15 października” instead of editing fields by hand. One provider call interprets the correction against the proposal currently on screen. Only the fields the correction mentions change. Every other field keeps its current value, including manual edits the parent already made in the form. The revised proposal is shown again for confirmation. Nothing is saved before the parent presses „Zapisz wpis”. This also works when the first result was a complete general note, and when the review form shows a highlighted missing field.

The plan was written without an owner interview. The owner reviewed it and its plan review, and the owner decisions were applied on 2026-10-04; the roadmap status is `planning`. Decisions marked `(owner-confirmed 2026-10-04)` are confirmed; the remaining assumed defaults stand unless the owner objects.

This slice builds on S-01 `school-event-details` (visible school item with a strict mismatch error, `school_subject`, `classify_output(..., require_school_subject=...)`), S-02 `classification-short-names` (`member_mention`, `member_ambiguous`, `_apply_member_mention`) and S-20 `title-keeps-action-only` (`DATE_RULES`, the `strip_extracted_phrases` title guard in `_translate`). All three land before S-03; implement against their merged code and re-check field names when they land.

### Owner Decisions (2026-10-04)

- Free-text correction applies only before saving.
- Relative dates use Europe/Warsaw; "w przyszłym tygodniu w poniedziałek" = Monday of the next calendar week; a bare weekday said on that same weekday means next week's day. S-20 owns `DATE_RULES`.
- All future-roadmap slices except removed ones are in the next milestone; confirmed order: S-01, S-02, S-20, S-03, S-04, S-05, S-06, S-07, S-08, S-09, S-17, S-14, S-15, S-16.
- Ship without feature flags and without backfilling existing data.
- No Playwright/E2E tests in this slice; browser tests will be added later.
- A typed correction may change the school type and the school subject. A school type that does not fit the resulting entry type is rejected with a Polish message, and the proposal stays unchanged.
- If the „Popraw opis” box contains text when the parent presses „Zapisz wpis”, saving is refused with a Polish message asking to apply („Popraw”) or clear the correction. Nothing is saved.
- Pressing Enter in the „Popraw opis” box triggers „Popraw”. S-05 `enter-text-submission` implements the JavaScript; this slice only provides the stable markup it opts into (Phase 2 §3).

Items below that the owner did not address remain assumed defaults; they stand unless the owner objects.

### Assumed Decisions (owner-confirmed items marked)

1. **Correction applies only before saving (owner-confirmed 2026-10-04).** It is available on the capture review form, not on saved entries in `entries/<pk>/edit/`. This is the smallest scope PK-10 names ("after the first classification presents a proposal"). Stands in for PRD Open Question 11 (first half).
2. **In a multiple-proposal result, a correction targets exactly one proposal, chosen in the UI.** Each proposal gets its own correction box, and the model never picks the target. Deterministic targeting means a correction can never land on the wrong entry. S-04 `multi-entry-text-capture` delivers this wiring; this plan only provides the single-proposal service and UI it reuses. Stands in for PRD Open Question 11 (second half).
3. **Correctable fields are the visible review fields after S-01: type, title, school type, subject, date, time and person (owner-confirmed 2026-10-04).** PK-10 says "date or any other entry field", and S-01 makes „Element szkolny” and „Przedmiot” visible and editable in review. A merged school type that does not fit the merged entry type is never dropped silently (S-01's strict rule): the correction is rejected with „Ten element szkolny wymaga rodzaju „{label}”. Poprawka nie została zastosowana.” and the proposal stays unchanged. This also applies when only the entry type changes and the unchanged school type no longer fits. A corrected subject is trimmed; one longer than `SCHOOL_SUBJECT_MAX_LENGTH` makes the correction not applied. Stands in for PRD Open Question 11 (scope of "any other field") and Q9.
4. **"Unmentioned" is decided by an explicit `changed_fields` list the model returns, and merged deterministically.** Fields absent from the list keep the on-screen value byte-for-byte. Diffing the whole model output would let the model silently rewrite a title it was not asked about. Stands in for PRD Open Question 11 (preservation rule).
5. **A date change must be grounded in the correction text.** A non-null new date whose `date_source` is not a literal fragment of the correction is discarded, as the existing capture and follow-up grounding does. An explicit clear („usuń datę”) is accepted. This reuses the invented-date protection from `missing-info-follow-up`. Stands in for PRD Open Question 6 (ambiguous date handling, applied to corrections).
6. **Relative-date rules are S-20's `DATE_RULES`, reused unchanged (owner-confirmed 2026-10-04).** Dates are counted from today's date in `Europe/Warsaw`. Weeks start on Monday. „w przyszłym tygodniu w <dzień>” means that weekday in the next calendar week. A bare weekday means its next occurrence after today, so the same weekday means next week's. A day and month without a year means the nearest such date on or after today. The only correction-specific rule, in `CORRECTION_INSTRUCTIONS`, is that a relative shift („przesuń o tydzień”) counts from the proposal's current date. Stands in for PRD Open Question 6.
7. **A failed, unclear or no-op correction keeps the on-screen proposal unchanged and shows a Polish notice.** This covers a provider failure, ungrounded output, an unknown person, a mismatched school type (Decision 3), or an empty `changed_fields`. The correction text stays in the box so the parent can rephrase it. There is no question round, so the parent can never get stuck or lose edits. Stands in for PRD Open Question 11 (failure behaviour, not stated in the PRD).
8. **Each correction is one provider call, and the parent may correct repeatedly.** There is no session state: the proposal travels in the posted form, as in S-01 and the follow-up flow. Each re-rendered review form gets a fresh `submission_key`. This keeps the existing stateless, idempotent confirm design and the 30-second NFR per step. Stands in for PRD Open Question 12 (compatibility: no schema change).
9. **The provider receives the current proposal values, family display names, the reference date and the correction. It does not receive the original instruction.** That is the minimum data needed, and the review form does not carry the original text today. This keeps the classification-purpose limit. Stands in for PRD Open Question 19 (retention scope unchanged: `store=False`, no logging).
10. **An unapplied correction blocks saving (owner-confirmed 2026-10-04).** When the `correction` box is non-blank on „Zapisz wpis”, `confirm` saves nothing and re-renders state `invalid` with the field error „Masz niezastosowaną poprawkę — naciśnij „Popraw” albo wyczyść pole.” on `correction` and a fresh `submission_key`. Nothing changes behind the parent's back, and this stays safe once S-05 makes Enter submit.

## Current State Analysis

- Capture is stateless. `capture` classifies once and renders a review form (`proposal`, `unavailable`) or a question (`entries/views.py:94-138`). `answer` handles the follow-up question (`entries/views.py:141-197`). `confirm` re-validates every posted value and saves idempotently on `submission_key` (`entries/views.py:200-230`, `entries/services.py:21-70`).
- `EntryReviewForm` holds the editable proposal (`entry_type`, `content`, `date`, `time`, `assigned_member`) plus hidden `school_item` and `submission_key`. Today its `clean` drops a school item that no longer matches the type (`entries/forms.py:111-163`). After S-01 the review form shows `school_item` as a visible select („Element szkolny”) with the strict mismatch error `SCHOOL_ITEM_TYPE_MISMATCH_ERROR` (`entries/forms.py:51`, `:166-187`) and a `school_subject` field („Przedmiot”). `review_form_from_classification` builds it from a `ParentClassification` and highlights missing fields (`entries/forms.py:223-250`).
- The review partial posts only to `entries:confirm`, with „Zapisz wpis” and „Zacznij od nowa” (`entries/templates/entries/_review_form.html:1-23`).
- The follow-up merge is the closest precedent. `classify_follow_up_answer` merges first (draft values plus only the asked fields from the output) and validates once (`entries/classification/service.py:129-215`).
- The backend seam has a single method, `classify(BackendRequest) -> BackendOutput`. Its request already carries optional follow-up fields that are absent from the payload when unused (`entries/classification/backends.py:18-67`, `entries/classification/openai_backend.py:134-150`).
- Date grounding drops a date whose `date_source` is not a literal fragment of the parent's text (`entries/classification/openai_backend.py:359-372`). The structured schema is strict, and its field descriptions are Polish (`entries/classification/openai_backend.py:69-103`).
- Semantic rules (required date for calendar events, school-item required fields, allow-listed member) live in `validate_output` (`entries/classification/validation.py:45-95`). It rejects `grounded=False` (`:52-53`) and turns a null `entry_type` into a general note whose content is `request.submitted_text` (`:49-50`, `:108-112`).
- The reference date is `timezone.localdate()`, with `TIME_ZONE = 'Europe/Warsaw'` (`entries/views.py:114`, `family_notes/settings.py:446`).

## Desired End State

A parent submits „Spotkanie z wychowawczynią w piątek o 17” and sees the proposal. In the new „Popraw opis” box they type „zmień datę na 15 października” and press „Popraw”. The review form comes back with the date 15.10.2026. Title, type, time and person are unchanged. A notice says „Zaktualizowano: data.” Pressing „Zapisz wpis” saves exactly one entry with the corrected date. The same works when the first result was a general note („to jest zadanie na jutro” turns it into a todo dated tomorrow, keeping the title). „przedmiot to fizyka” fills a highlighted missing subject of a test. An unclear correction leaves the proposal untouched and shows a notice. Pressing „Zapisz wpis” with an unapplied correction in the box saves nothing and asks the parent to press „Popraw” or clear it. Children, other families and anonymous users cannot reach the endpoint. The correction text never appears in logs.

Verify with the automated suites below, the DEBUG states page and one live OpenAI check.

### Key Discoveries:

- The merge-before-validate pattern in `_merge_answer` stops unrelated output fields from vetoing or overwriting the asked change. The correction merge copies that pattern, keyed on `changed_fields` instead of `missing_fields` (`entries/classification/service.py:200-215`).
- `EntryReviewForm` field errors for the schedule rules (`_require_schedule_fields`) must not block a correction, because the correction may be the thing that adds the missing date or subject. The correction form therefore validates field formats, family scope and S-01's strict school-type mismatch only (`entries/forms.py:94-108`).
- `test_openai_backend` asserts the exact input dict, so the correction keys must be absent from first-classification and follow-up payloads (see the `missing-info-follow-up` plan, Key Discoveries).
- Lesson: UI copy and OpenAI prompt text are Polish, and code is English (`context/foundation/lessons.md`).

## What We're NOT Doing

- No correction of saved entries (manual edit already covers them), and no correction in structured create/edit or for EduVulcan conversions.
- No model-chosen target in a multi-proposal result, and no batch-wide correction („zmień godzinę wszystkich”). S-04 wires per-proposal correction.
- No correction that splits one proposal into several or adds new proposals.
- No new school fields: the school type and subject come from S-01 `school-event-details`; this slice only lets a correction change them.
- No server-side draft or session storage, no JavaScript (Enter-to-„Popraw” is S-05), no model or migration change.
- No change to S-20's `DATE_RULES` wording.
- No change to first classification or the follow-up question flow.

## Implementation Approach

Phase 1 extends the classification boundary with a view-independent correction service. It has the same authorization, candidate and privacy rules as `classify_for_parent`. A separate structured schema returns the full set of field values plus `changed_fields`. A deterministic merge applies only the changed fields to the current values, and the merged values are validated once. Phase 2 adds a correction box and a „Popraw” submit to the capture review form. The submit posts to a new `entries:correct` endpoint that re-renders the review form with the merged result or a notice. Phase 3 adds DEBUG states-page sections and the live check.

## Critical Implementation Details

- **Merge, then validate once.** Build the merged values first: current values, overwritten only by fields in the validated `changed_fields`. Then run the existing semantic validation on the merged values. Validating the raw output first would let an echoed or reformatted title, or a different type, cause an unavailable result or a silent rewrite.
- **Grounding before merge.** The adapter removes `date` from `changed_fields` when it returns a non-null date that is not grounded in the correction text. The service then treats a correction with nothing left in `changed_fields` as "not applied". A dropped date must never fall through as "clear the date".
- **Privacy.** The correction is family text. Add it to `sensitive_variables` and `sensitive_post_parameters`, keep it out of `repr`, and never log it. The adapter's single log line stays unchanged.

## Phase 1: Correction classification service

### Overview

Let a backend request carry the current proposal and a correction. Add an OpenAI correction schema and instructions, and add a parent service that merges only the changed fields.

### Changes Required:

#### 1. Proposal values and backend contract

**File**: `entries/classification/types.py`, `entries/classification/backends.py`

**Intent**: Give the correction path a neutral carrier for the on-screen proposal, which may be incomplete, and let the backend report which fields a correction changes.

**Contract**:
- New frozen `ProposalValues(entry_type, content, date, time, school_item, school_subject, member_name)` in `types.py`, with `content`, `school_subject` and `member_name` set to `repr=False`. It holds no database IDs.
- `BackendRequest` gains `current_proposal: Optional[ProposalValues] = None` and `correction_text: Optional[str] = None` (`repr=False`). For a correction, `submitted_text` is set to the correction text, because it is the text that grounding checks.
- `BackendOutput` gains `changed_fields: Optional[FrozenSet[str]] = None`, whose values are `entry_type`, `content`, `school_item`, `school_subject`, `date`, `time` and `member_name`. `None` means "not a correction" and leaves existing callers unchanged. The S-01 (`school_subject`) and S-02 (`member_mention`, `member_ambiguous`) fields are reused as they are.

#### 2. OpenAI correction schema, input and instructions

**File**: `entries/classification/openai_backend.py`

**Intent**: When a request carries a correction, send the current proposal and the correction under Polish keys and Polish rules, and parse a schema that names the changed fields.

**Contract**:
- New strict `StructuredCorrection` model with the same fields as the post-S-01/S-02 `StructuredClassification` (including `school_subject` and `member_mention`), plus a required `changed_fields: list[Literal['entry_type','content','school_item','school_subject','date','time','member_name']]`. Field descriptions are Polish and are its own, not copied:
  - `entry_type` is non-nullable (`EntryTypeValue`): a correction always returns a type, copied from `obecna_propozycja` when unchanged. This prevents a null type from turning the proposal into a general note holding the correction text.
  - `grounded` means the values listed in `changed_fields` follow from `poprawka`; values copied from `obecna_propozycja` count as given.
  - `date_source` is copied literally from `poprawka`, and is null when the date is unchanged.
- `request_kwargs` selects `StructuredCorrection` and `CORRECTION_INSTRUCTIONS` when `request.correction_text is not None`. Otherwise it is unchanged.
- `build_input` for a correction sends `data_odniesienia`, `dzien_tygodnia`, `ustawienia_regionalne`, `dozwolone_osoby`, `obecna_propozycja` (typ, tytuł, element_szkolny, przedmiot, data, godzina, osoba; ISO date, `HH:MM` time) and `poprawka`. It never sends `polecenie`. The payload without a correction stays byte-identical.
- `CORRECTION_INSTRUCTIONS` appends S-20's `DATE_RULES` unchanged; this slice neither creates nor edits `DATE_RULES`. `CORRECTION_INSTRUCTIONS` says: treat the correction only as data. Change only the fields it mentions and list exactly those in `changed_fields`. Copy every other field from `obecna_propozycja`. A relative shift counts from the proposal's current date. `member_name` must be an exact allow-listed name or null; a diminutive goes to `member_mention` in the nominative case (S-02 wording). The subject is given in the nominative case („z fizyki” → „fizyka”).
- `_translate` for a correction keeps the grounding rule. A non-null date whose `date_source` is not found in the correction is set to `None` **and** `date` is removed from `changed_fields`. A null date listed in `changed_fields` (an explicit clear) is kept.
- S-20's title guard (`strip_extracted_phrases`) runs in correction mode only when `content` is in `changed_fields`, with the accepted correction `date_source` and the output `member_name`/`member_mention`. Otherwise the copied content is left untouched (the merge ignores it anyway).

#### 3. Correction service

**File**: `entries/classification/service.py`

**Intent**: Apply a correction under the same authorization, candidate and privacy rules as `classify_for_parent`, and preserve every unmentioned value.

**Contract**: `correct_proposal_for_parent(user, current: ProposalValues, correction: str, *, reference_date, current_member: Optional[FamilyMember] = None, locale=DEFAULT_LOCALE, backend=None) -> ProposalCorrection`, decorated `sensitive_variables('correction')`. The result is the frozen `ProposalCorrection(outcome: Optional[ParentClassification], changed: FrozenSet[str], applied: bool, rejection: Optional[CorrectionRejection])`. When `applied=False`, `outcome` is `None` and the view owns the re-render of the posted values. `CorrectionRejection` is a small enum: `TOO_LONG`, `NOT_APPLIED`, `SCHOOL_ITEM_MISMATCH` (the last carries the merged school item so the view can name the required type).
- Raises `PermissionDenied` for anonymous users, children and non-members before any backend call.
- Returns `applied=False, rejection=TOO_LONG` when `correction` exceeds the new `MAX_CORRECTION_LENGTH = 500`, or when `current.content` exceeds `MAX_SUBMITTED_TEXT_LENGTH`. No backend call is made. (The form's `max_length` normally catches a long correction first; this guards direct service calls.)
- `current_member` is trusted only if it is an active member of the parent's family, as in `_known_member_name`. The current `member_name` comes from it.
- If the backend raises, `output.grounded` is false, the output names an unknown member, or the set of changed fields is empty, the service returns `applied=False, rejection=NOT_APPLIED`.
- Otherwise it merges, then validates once. Each field in `changed_fields` comes from the output (`member_name` normalized, `school_subject` trimmed). Every other field comes from `current`, including `school_item` and `school_subject`. The merged `grounded` is set explicitly to `output.grounded`.
- Member (S-02): `member_name` and `member_mention` come from the output only when `member_name` is in `changed_fields`; otherwise `member_mention=None` and `member_ambiguous=False`, so a stray mention can never reassign the current member. Only in that case does the service run `_apply_member_mention` on the merged output, mirroring S-02's follow-up rule. An ambiguous short name is applied as an `AMBIGUOUS_MEMBER` highlight („Wybierz osobę.”). Zero matches with an unknown name is not applied.
- School type (owner decision): if the merged `school_item` does not fit the merged `entry_type`, the service returns `applied=False, rejection=SCHOOL_ITEM_MISMATCH` and nothing is dropped silently. A merged subject longer than `SCHOOL_SUBJECT_MAX_LENGTH` is `NOT_APPLIED`.
- The service then runs `classify_output(..., require_school_subject=True)` (as `classify_for_parent` does after S-01) and `_resolve_member` on the merged `BackendOutput`, which returns a proposal or a follow-up with highlights (for example a missing `SCHOOL_SUBJECT`). A `ClassificationUnavailable` result from that step is treated as `NOT_APPLIED`.
- The service performs zero database writes.

#### 4. Tests

**File**: `entries/tests/test_proposal_correction.py` (new), `entries/tests/test_openai_backend.py`

**Intent**: Pin the preservation rule, grounding, authorization and privacy.

**Contract**: Fake-backend tests cover these cases:
- A date-only change keeps the title, type, time, member, school item and school subject (for example „zmień datę na piątek” on „Sprawdzian”, subject „matematyka”).
- Output with a different title but `changed_fields={'date'}` keeps the current title.
- A general note becomes a todo with a date, and the title is kept.
- A subject correction („przedmiot to fizyka”) fills a missing subject; a school type correction („to kartkówka, nie sprawdzian”) changes the school item.
- A type change that leaves an incompatible school item, or a corrected school item that does not fit the type, is rejected with `SCHOOL_ITEM_MISMATCH` and nothing changes.
- „usuń datę” on a calendar event gives a follow-up with the date missing.
- A member change to an allow-listed name resolves locally, and an unknown name is not applied.
- A diminutive member correction resolves through `_apply_member_mention`; an ambiguous one gives an `AMBIGUOUS_MEMBER` highlight; a date-only correction whose output carries a stray `member_mention` keeps the current member.
- An ungrounded date is not applied.
- An output with `grounded=false` is not applied.
- An empty `changed_fields` is not applied.
- A provider timeout is not applied, and `outcome` is `None`.
- A child, an outsider and an anonymous user each get `PermissionDenied` with zero backend calls.
- A too-long correction makes zero backend calls.
- The request carries `current_proposal` and `correction_text` and no original instruction, and nothing is written to the database.

Adapter tests cover:
- The correction input dict, with exact keys and without `polecenie`.
- The `StructuredCorrection` format is selected only for corrections, and its `entry_type` is non-nullable.
- An ungrounded date is removed from `changed_fields`, while an explicit null clear is kept.
- An output that copies the unchanged fields with `grounded=true` translates intact.
- The S-20 title guard runs only when `content` is in `changed_fields`.
- The existing exact-input test without a correction still passes.

### Success Criteria:

#### Automated Verification:

- Correction service tests pass: `uv run python manage.py test entries.tests.test_proposal_correction`
- Adapter tests pass, including the unchanged first-classification input: `uv run python manage.py test entries.tests.test_openai_backend`
- Full suite and Django checks pass: `uv run python manage.py test` and `uv run python manage.py check`

#### Manual Verification:

- Reading `CORRECTION_INSTRUCTIONS` and `DATE_RULES` confirms natural Polish wording that states the preserve-unmentioned rule and the relative-date rules from Assumed Decision 6

Note on 1.4: S-20 owns and reviews `DATE_RULES`. This check covers only the `CORRECTION_INSTRUCTIONS` wording (preserve-unmentioned, relative shift from the current date) and that it appends `DATE_RULES` unchanged.

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 2: Correction step in the capture review

### Overview

Add a correction box and a „Popraw” submit to the capture review form, and route it to a new endpoint that re-renders the revised proposal.

### Changes Required:

#### 1. Correction form

**File**: `entries/forms.py`

**Intent**: Read the on-screen proposal, including manual edits, plus the correction text. Only formats and family scope are validated, so a correction can fill a missing value.

**Contract**: `ProposalCorrectionForm(EntryReviewForm)` adds `correction` (Textarea, `strip=True`, required, ≤ `MAX_CORRECTION_LENGTH`). Its label is „Popraw opis”, its placeholder is „np. zmień datę na 15 października”, its required error is „Wpisz, co zmienić.” and its `max_length` error is „Poprawka jest za długa.” Its `clean` skips `_require_schedule_fields`. Field-level errors (bad date format, foreign or inactive member, unknown type, subject too long) and S-01's strict school-type mismatch error still apply, with no backend call. Helper `proposal_values_from_form(form) -> (ProposalValues, Optional[FamilyMember])`, which includes `school_item` and `school_subject`. `EntryReviewForm` gains the optional `correction` field so the same partial renders it. When `correction` is non-blank, `EntryReviewForm.clean` (used by `confirm`) adds the field error „Masz niezastosowaną poprawkę — naciśnij „Popraw” albo wyczyść pole.” on `correction`, so nothing is saved (owner decision, Assumed Decision 10).

#### 2. View, route and notices

**File**: `entries/views.py`, `entries/urls.py`

**Intent**: Apply the correction and show the revised proposal for confirmation, or keep the current one with a notice.

**Contract**: New `correct` view at `POST entries/correct/` (name `entries:correct`). It is `require_POST`, `login_required` and parent-only (403 otherwise), with `sensitive_post_parameters('content', 'correction')`.
- An invalid form re-renders state `invalid` with the posted values.
- Otherwise it calls `correct_proposal_for_parent` with `reference_date=timezone.localdate()`.
- When the correction is applied, the view renders state `proposal` (or `follow_up` when fields are still missing) via `review_form_from_classification`, with a fresh `submission_key` and an empty correction box. The notice is „Zaktualizowano: {pola}.”, where the Polish field labels come from the form labels (e.g. „data, godzina”).
- When the correction is not applied (`outcome is None`), the view re-renders the posted values itself in state `correction_failed`, with the correction text kept and a fresh key. The notice is „Nie udało się zastosować poprawki. Napisz ją inaczej albo popraw pola ręcznie.” For `SCHOOL_ITEM_MISMATCH` the notice is instead „Ten element szkolny wymaga rodzaju „{label}”. Poprawka nie została zastosowana.” For `TOO_LONG` (only reachable for an over-long current title, since the form catches a long correction) the field error „Poprawka jest za długa.” goes on `correction`.
- `confirm` with a non-blank `correction` saves nothing and re-renders state `invalid` with the posted values, the „Masz niezastosowaną poprawkę…” field error and a fresh `submission_key`.

#### 3. Review partial

**File**: `entries/templates/entries/_review_form.html`

**Intent**: Offer the correction next to the save action without JavaScript.

**Contract**: Below the fields, the partial renders the `correction` field through `_field.html` and a secondary submit „Popraw” with `formaction="{% url 'entries:correct' %}"` and `formnovalidate`. „Zapisz wpis” stays the default (first) submit. The partial uses existing token classes only, with no inline styles.

Stable markup for S-05 (owner decision: Enter in „Popraw opis” triggers „Popraw”; S-05 writes the JavaScript, this slice adds none):
- The „Popraw” button has `name="action" value="correct"` and a stable, prefix-aware `id` (`{{ form.prefix }}-correct-submit`, or `correct-submit` without a prefix), so it stays unique per proposal in S-04's multi-proposal form.
- The correction textarea carries `data-enter-submitter="<that button id>"`. S-05 opts in by submitting the form with that button as the explicit submitter (`form.requestSubmit(button)`), which keeps the `formaction` to `entries:correct`.
- Without JavaScript, Enter in the textarea inserts a newline as today, and the server-side refusal in `confirm` (Assumed Decision 10) still prevents a silent save.

#### 4. Tests

**File**: `entries/tests/test_correction_views.py` (new), `entries/tests/test_capture_views.py`

**Intent**: Cover the full flow, access and privacy.

**Contract**:
- Capture, correct the date, then confirm: exactly one entry is saved, with the corrected date and the other values from before.
- Manual edits made before „Popraw” survive a correction of another field.
- A general-note proposal is corrected into a todo.
- A correction that leaves a missing date renders `follow_up` with the date highlighted.
- A not-applied correction keeps the posted values and the correction text, and shows the notice.
- A school-type mismatch shows the „Ten element szkolny wymaga rodzaju…” notice with the proposal unchanged.
- „Zapisz wpis” with a non-blank correction saves nothing and shows the „Masz niezastosowaną poprawkę…” error with a fresh key.
- An empty correction gives a field error with no backend call, and a too-long one gives „Poprawka jest za długa.” with no backend call.
- A foreign member posted in the form gives a form error with no backend call.
- Child, other-family parent and anonymous users are refused on `entries:correct` (403 or redirect).
- Nothing is written before confirm.
- The correction text never appears in captured logs (`assertLogs` / `assertNoLogs`).
- A fresh `submission_key` is issued on every correction render.
- The review partial contains the „Popraw” submit with the `entries:correct` formaction, its stable `id`, and the textarea's matching `data-enter-submitter`.

### Success Criteria:

#### Automated Verification:

- Correction and capture view tests pass: `uv run python manage.py test entries.tests.test_correction_views entries.tests.test_capture_views`
- Full suite, Django checks and migration check pass: `uv run python manage.py test`, `uv run python manage.py check` and `uv run python manage.py makemigrations --check --dry-run`

#### Manual Verification:

- With a stubbed or live backend on a phone-width browser, a parent corrects the date of a proposal with „zmień datę na 15 października”, sees the revised proposal with the other fields unchanged, and saves it

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 3: States page and live check

### Overview

Show the new states on the DEBUG kitchen sink and confirm the behaviour against the real provider.

### Changes Required:

#### 1. DEBUG states page

**File**: `entries/views.py` (`states`), `entries/tests/test_states_view.py`

**Intent**: Make the corrected and failed-correction states reviewable without a provider.

**Contract**: The page adds the sections `corrected` (a synthetic proposal with the notice „Zaktualizowano: data.”) and `correction_failed` (a synthetic proposal with the kept correction text and the failure notice), built from fictional data only. The states test's expected names include both.

#### 2. Live check corpus

**File**: `entries/tests/test_classification_acceptance.py`

**Intent**: Add an opt-in live case (skipped by default under `CLASSIFICATION_LIVE_EVAL=1`) and a scripted-transport case for a date correction.

**Contract**: The scripted case sends a correction through the real `OpenAIClassificationBackend` with a scripted HTTP transport. It asserts the correction input keys and that a returned grounded date with `changed_fields=['date']` flows into the merged proposal. The live case asserts that only the date changes for „zmień datę na 15 października”.

### Success Criteria:

#### Automated Verification:

- States page and acceptance tests pass: `uv run python manage.py test entries.tests.test_states_view entries.tests.test_classification_acceptance`
- Full suite passes: `uv run python manage.py test`

#### Manual Verification:

- The `corrected` and `correction_failed` sections on `/entries/_states/` render at 360 px width with nothing clipped or overflowing
- A live run with an OpenAI key: „zmień datę na 15 października” and „to dla Tymka” each change only the named field, within 30 s per step

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful.

---

## Testing Strategy

### Unit Tests:

- The merge preserves every field not in `changed_fields`, for proposals, highlighted drafts and general notes.
- Grounding: an ungrounded date is removed from `changed_fields`, and an explicit clear is accepted.
- A school type that does not fit the merged entry type rejects the correction (`SCHOOL_ITEM_MISMATCH`); the school item and subject are otherwise preserved or corrected.
- Member corrections follow S-02's short-name resolution only when `member_name` is in `changed_fields`.
- Correction adapter input and schema selection, with first-classification input unchanged.

### Integration Tests:

- Capture → correct → confirm saves one entry with the corrected value.
- Repeated corrections in sequence each make one provider call and keep earlier changes.
- Access: parent only. Child, other family and anonymous users are refused.
- Privacy: correction text is never logged, and no rows are written before confirm.

### Manual Testing Steps:

1. Submit „Spotkanie z wychowawczynią w piątek o 17”, correct with „zmień datę na 15 października”, and check that only the date changed. Then save.
2. Submit a free-form note, correct with „to zadanie na jutro”, and check that the type and date changed while the title stayed the same.
3. Correct with „bla bla” and check that the notice appears, the proposal is unchanged and the text is kept.
4. Edit the time by hand, then correct the date, and check that the manual time survives.

## Performance Considerations

Each correction is one provider call under the existing 25-second deadline, so every screen still meets the 30-second NFR. An invalid form, an empty correction or a too-long correction makes no call.

## Migration Notes

No schema change. Rollback is a code revert. Saved entries and automation consumers are unaffected.

## References

- PRD v2 PK-10, US-10, Open Questions 6, 11, 12: `context/foundation/prd-v2.md`
- Future roadmap S-03: `context/foundation/roadmap-future.md`
- Interaction with multi-proposal results: `context/changes/multi-entry-text-capture/plan.md` (Phase 3)
- Follow-up merge precedent: `context/changes/missing-info-follow-up/plan.md`, `entries/classification/service.py:129-215`
- Capture flow: `entries/views.py:94-230`, `entries/forms.py:111-250`, `entries/templates/entries/_review_form.html`
- Grounding and schema: `entries/classification/openai_backend.py:69-150`, `entries/classification/openai_backend.py:359-372`
- Semantic validation: `entries/classification/validation.py:45-95`
- Upstream contracts: `context/changes/school-event-details/plan.md` (S-01), `context/changes/classification-short-names/plan.md` (S-02), `context/changes/title-keeps-action-only/plan.md` (S-20, `DATE_RULES`)

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Correction classification service

#### Automated

- [x] 1.1 Correction service tests pass
- [x] 1.2 Adapter tests pass, including the unchanged first-classification input
- [x] 1.3 Full suite and Django checks pass

#### Manual

- [ ] 1.4 Reading `CORRECTION_INSTRUCTIONS` and `DATE_RULES` confirms natural Polish wording that states the preserve-unmentioned rule and the relative-date rules from Assumed Decision 6

### Phase 2: Correction step in the capture review

#### Automated

- [ ] 2.1 Correction and capture view tests pass
- [ ] 2.2 Full suite, Django checks and migration check pass

#### Manual

- [ ] 2.3 With a stubbed or live backend on a phone-width browser, a parent corrects the date of a proposal with „zmień datę na 15 października”, sees the revised proposal with the other fields unchanged, and saves it

### Phase 3: States page and live check

#### Automated

- [ ] 3.1 States page and acceptance tests pass
- [ ] 3.2 Full suite passes

#### Manual

- [ ] 3.3 The `corrected` and `correction_failed` sections on `/entries/_states/` render at 360 px width with nothing clipped or overflowing
- [ ] 3.4 A live run with an OpenAI key: „zmień datę na 15 października” and „to dla Tymka” each change only the named field, within 30 s per step
