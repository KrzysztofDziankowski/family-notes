# Multi-Entry Text Capture Implementation Plan

## Overview

This is future roadmap slice S-04 (PK-05 and US-05 in `context/foundation/prd-v2.md`). One instruction can produce several proposals. For example, „Dodaj spotkanie z X dziś, jutro i w przyszłym tygodniu w poniedziałek o 18:00” (or the English PRD example) produces three meeting proposals at 18:00, one for each requested date. The parent reviews all of them on one page, can leave any of them out, can fix or (with S-03) text-correct any single one, and saves the selected proposals in one all-or-nothing action. An instruction that yields one proposal keeps today's flow exactly: review, the question step, and the note fallback.

The plan was written without an owner interview. The owner reviewed it and its plan review, and the owner decisions were applied on 2026-10-04; the roadmap status is `planning`. Decisions marked `(owner-confirmed 2026-10-04)` are confirmed; the remaining assumed defaults stand unless the owner objects.

This slice builds on S-01 `school-event-details` (`school_subject`, visible school item, `classify_output(..., require_school_subject=...)`), S-02 `classification-short-names` (`_apply_member_mention`), S-20 `title-keeps-action-only` (`DATE_RULES` and the title guard in `_translate`) and S-03 `free-text-proposal-correction` (`correct_proposal_for_parent`, the `correction` field on `EntryReviewForm`, `ProposalCorrectionForm`). All four land before S-04; implement against their merged code and re-check helper names when they land.

### Owner Decisions (2026-10-04)

- Saving several entries is all-or-nothing, for simplicity.
- Corrections apply only before saving.
- Relative dates use Europe/Warsaw; "w przyszłym tygodniu w poniedziałek" = Monday of the next calendar week; a bare weekday said on that same weekday means next week's day. S-20 owns `DATE_RULES`.
- All future-roadmap slices except removed ones are in the next milestone; confirmed order: S-01, S-02, S-20, S-03, S-04, S-05, S-06, S-07, S-08, S-09, S-17, S-14, S-15, S-16.
- Ship without feature flags and without backfilling existing data.
- No Playwright/E2E tests in this slice; browser tests will be added later.
- (From S-03) A typed but unapplied correction blocks saving with a Polish message; Enter in a correction box triggers its „Popraw” button (S-05 writes the JavaScript against S-03's stable markup).

Items below that the owner did not address remain assumed defaults; they stand unless the owner objects.

### Assumed Decisions (owner-confirmed items marked)

1. **Relative dates are counted from today's date in `Europe/Warsaw`, by the model, under explicit shared rules (owner-confirmed 2026-10-04).** Weeks start on Monday. „w przyszłym tygodniu w <dzień>” / "next week on <day>" means that weekday in the next calendar week. A bare weekday means its next occurrence after today, so the same weekday means next week's. „dziś/today” is the reference date. A day and month without a year means the nearest such date on or after today. The rules live in S-20's `DATE_RULES` constant (`entries/classification/openai_backend.py`), reused unchanged by S-03 and S-04. They match Polish usage and the existing reference-date contract, and they avoid a hand-written bilingual date parser. Stands in for PRD Open Question 6 (timezone and relative-date rules).
2. **Ambiguous or colliding dates are shown, never silently resolved or merged.** A proposal without a grounded date shows its date field highlighted, as in S-01. Two proposals with the same type, title, date and time get a non-blocking hint („Taki sam jak wpis {n}”). This covers the Sunday case, where "tomorrow" and "next week Monday" fall on the same day. The parent decides by unticking a proposal, and no proposal is dropped behind their back. Stands in for PRD Open Question 6 (ambiguous dates).
3. **All proposals are reviewed on one page and saved with one action. Each proposal has an „Uwzględnij” checkbox, ticked by default.** US-05 says "all are shown for confirmation before saving". One action keeps the flow short on a phone, and unticking covers "I only want two of these". Proposals cannot be confirmed separately one by one. Stands in for PRD Open Question 6 (separate confirmation).
4. **Saving is all-or-nothing (owner-confirmed 2026-10-04).** The selected proposals are saved in one database transaction. If any of them fails validation, nothing is saved and the page re-renders with the errors. This rules out a half-saved batch the parent then has to reconcile by hand. Stands in for PRD Open Question 6 (partial batch save).
5. **A batch holds at most 10 proposals.** If the model returns more, the instruction falls back to the existing single-note review, with the notice „Za dużo wpisów w jednym poleceniu (maks. 10). Podziel polecenie.” The cap bounds output tokens, page length and accidental expansion. Stands in for PRD Open Question 1 (scope limits not stated).
6. **In a batch, a proposal with missing values is shown with highlights, not asked about.** There is no follow-up question round for a batch; only a single-proposal result keeps the question step. One question covering several proposals would be hard to answer by voice, and the fields are already on screen. Stands in for PRD Open Question 6 (ambiguous dates) and keeps the `missing-info-follow-up` contract intact for single results.
7. **If any proposal in a batch fails validation, the whole instruction falls back to the existing single-note review with the full text.** This covers an ungrounded proposal, an unknown person and empty content. It is conservative: no proposal built from rejected model output reaches the parent, and nothing is silently dropped. Stands in for PRD Open Question 6 (failure behaviour).
8. **Correcting one proposal in a batch targets that proposal only, chosen in the UI. Corrections apply only before saving (owner-confirmed 2026-10-04).** Each proposal has a collapsed „Popraw tekstem” box that calls S-03's `correct_proposal_for_parent` for that proposal; the other proposals are carried through unchanged. Batch-wide corrections are out of scope. This is the same assumption as S-03 decision 2. As in S-03, a non-blank correction box blocks „Zapisz wpisy” (owner-confirmed 2026-10-04). Stands in for PRD Open Question 11 (target selection).
9. **Automated EduVulcan intake stays single-entry.** Only parent capture gains batches. PK-05 is about a parent's instruction, and intake has its own lifecycle and deduplication. Stands in for PRD Open Question 12 (compatibility for existing consumers).

## Current State Analysis

- Capture classifies one instruction into one `ParentClassification`. It then renders a review form, the follow-up question, or the note fallback (`entries/views.py:94-138`). `confirm` saves one entry, idempotent on `submission_key` (`entries/views.py:200-230`, `entries/services.py:21-70`, `entries/models.py:62`).
- The backend seam has one method, `classify(BackendRequest) -> BackendOutput` (`entries/classification/backends.py:63-67`). Follow-up answers (`entries/classification/service.py:129-182`), EduVulcan intake (`entries/classification/service.py:313-380`) and the smoke command (`entries/management/commands/classification_smoke.py:77`) also use it.
- The OpenAI adapter uses one strict `StructuredClassification` schema and Polish `INSTRUCTIONS`. Relative dates are counted "from the reference date" with no further rules. The default `max_output_tokens` is 1024 (`entries/classification/openai_backend.py:51`, `entries/classification/openai_backend.py:69-131`). Date grounding is per output (`entries/classification/openai_backend.py:359-372`).
- `validate_output` turns one output into a proposal, a follow-up or a rule violation (`entries/classification/validation.py:45-95`). When no type is recognised, it falls back to a general note with the whole text (`entries/classification/validation.py:108-112`).
- `_translate` rejects any parsed body that is not a `StructuredClassification` (`entries/classification/openai_backend.py:327-329`), so a list response needs its own translator. After S-20 it also runs the title guard after date grounding.
- The acceptance corpus calls `classify_for_parent` directly with single-object scripted bodies (`entries/tests/test_classification_acceptance.py:86-104`), and `capture` is the only production caller of `classify_for_parent` (`entries/views.py:115`).
- `EntryReviewForm` is one unprefixed form, and the review partial wraps its own `<form>` posting to `entries:confirm` (`entries/forms.py:111-163`, `entries/templates/entries/_review_form.html:1-23`).
- The saved panel shows one entry, read from `?saved=<pk>` and scoped to the family (`entries/views.py:233-240`, `entries/templates/entries/_saved_panel.html`).
- The reference date is `timezone.localdate()`, with `TIME_ZONE = 'Europe/Warsaw'` (`entries/views.py:114`, `family_notes/settings.py:446`).

## Desired End State

On Wednesday 2026-10-07 a parent submits „Dodaj spotkanie z X dziś, jutro i w przyszłym tygodniu w poniedziałek o 18:00”. The page „Sprawdź wpisy (3)” lists three ticked calendar-event proposals. Each has the title „Spotkanie z X”, time 18:00, and the dates 07.10, 08.10 and 12.10, each shown with its weekday. The parent unticks nothing and presses „Zapisz wpisy (3)”. Exactly three entries are saved, and the saved panel lists all three. Unticking one saves two. Re-posting the form saves nothing new. A single-entry instruction behaves exactly as today. Children, other families and anonymous users cannot reach the batch endpoint. The instruction text never appears in logs.

Verify with the automated suites below, the DEBUG states page and one live OpenAI check.

### Key Discoveries:

- Existing fake backends implement only `classify`. The batch service can accept a backend without `classify_many` by treating its single output as a one-item batch. That keeps all existing tests and the smoke command valid, and only the OpenAI adapter gains the list schema (`entries/classification/backends.py:63-67`).
- `save_confirmed_entry` already opens its own atomic block and handles `IntegrityError` replays. Calling it inside an outer `transaction.atomic()` gives savepoint semantics, so the all-or-nothing batch reuses it unchanged (`entries/services.py:51-70`).
- The per-proposal `submission_key` already makes each proposal idempotent. A replayed batch therefore returns the same entries and writes nothing.
- The exact-input adapter test pins the payload. The batch call can keep the same input keys and change only the schema and instructions (`entries/tests/test_openai_backend.py`).
- Lesson: UI copy and OpenAI prompt text are Polish, and code is English (`context/foundation/lessons.md`).

## What We're NOT Doing

- No batches for EduVulcan intake, the REST API or structured create.
- No deterministic Polish/English date parser. The model computes dates under explicit rules, and grounding and the parent's review guard the result.
- No separate one-by-one confirmation, and no partial save of a failed batch.
- No follow-up question round inside a batch, and no batch-wide free-text correction.
- No recurring-event model ("every Monday"); each date is an independent entry.
- No server-side draft storage, JavaScript, model or migration change.

## Implementation Approach

Phase 1 extends the classification boundary with a list-returning call and a batch parent service. A one-item result is identical to today's `ParentClassification`. Phase 2 branches capture on the batch size. One proposal uses the existing flow. Several proposals render a prefixed multi-form review that posts to a new batch endpoint, which saves the selected proposals atomically. Phase 3 wires S-03's per-proposal correction (landed before S-04) into the batch page. Phase 4 adds DEBUG states, the acceptance corpus and the live check.

## Critical Implementation Details

- **The single-proposal path must stay identical in behaviour.** A one-item batch must reach exactly the same states (`proposal`, `question`, `unavailable`, `INPUT_TOO_LONG` error) as today. With the OpenAI backend every production capture, including a single-entry one, now goes through `classify_many` (list schema, `MULTI_INSTRUCTIONS`, larger token budget), so the regression gate is the existing acceptance corpus re-run through `classify_entries_for_parent` with list-wrapped scripted bodies (Phase 4 §2), plus the capture and follow-up view tests.
- **One per-output pipeline.** Every parent-path output goes through one shared helper, `_finish_parent_output(request, output, candidates)` = `_apply_member_mention` (S-02) → `classify_output(..., require_school_subject=True)` (S-01) → `_resolve_member`. `classify_for_parent`, the batch path and S-03's correction merge all use it, so later parent-path rules cannot diverge between single and batch.
- **Output budget.** The batch call uses its own `max_output_tokens`, at least 2048, so ten proposals fit. An `incomplete` response still maps to `INCOMPLETE_OUTPUT` and the note fallback.
- **Validation errors on unticked proposals are ignored.** An unticked proposal is neither validated nor saved, so a broken proposal the parent left out cannot block saving the others.
- **Privacy.** The batch form posts several `content` fields under prefixes, so `sensitive_post_parameters` must cover every prefixed `content` and `correction` key. Use the decorator with no arguments (all parameters) on the batch endpoint, and never log any posted value.

## Phase 1: Multi-entry classification boundary

### Overview

Let the provider return a list of entries for one instruction, and add a parent batch service that validates and resolves each entry.

### Changes Required:

#### 1. Backend contract

**File**: `entries/classification/backends.py`

**Intent**: Expose an optional list-returning call without breaking single-output backends.

**Contract**: New runtime-checkable `MultiEntryClassificationBackend(Protocol)` with `classify_many(request) -> Tuple[BackendOutput, ...]`. `ClassificationBackend` is unchanged. New constant `MAX_PROPOSALS_PER_INSTRUCTION = 10` (in `service.py` or `types.py`, next to the other limits).

#### 2. OpenAI list schema and shared date rules

**File**: `entries/classification/openai_backend.py`

**Intent**: Ask for every entry the instruction requests, each with its own grounded date, under explicit relative-date rules.

**Contract**:
- New strict `StructuredClassificationList` with `entries: list[StructuredClassification]`. Its Polish description says each requested date or occurrence is a separate entry and that a shared time or person applies to each.
- `classify_many(request)` uses that schema, `MULTI_INSTRUCTIONS = INSTRUCTIONS + <one sentence about splitting into separate entries and repeating shared details>` and `max_output_tokens` of at least 2048. It reuses the same retry, deadline and log path, and `classify` is unchanged.
- `DATE_RULES` is S-20's constant, already appended to `INSTRUCTIONS`; `MULTI_INSTRUCTIONS` inherits it through `INSTRUCTIONS` and never appends it a second time. This slice does not change its wording.
- Extract a per-entry `_translate_entry(parsed: StructuredClassification, request) -> BackendOutput` (date grounding, then S-20's title guard with that entry's accepted `date_source` and member, then mapping). Both `_translate` and the new list translator call it, so grounding and title stripping apply to each entry independently (for example „… dziś” and „… jutro” are stripped from each title).
- An empty `entries` list is translated to a single output with `entry_type=None`, which gives the existing general-note fallback.

#### 3. Batch parent service

**File**: `entries/classification/service.py`

**Intent**: Classify one instruction into up to ten validated, locally resolved results under the same authorization and privacy rules as `classify_for_parent`.

**Contract**: `classify_entries_for_parent(user, submitted_text, *, reference_date, locale=DEFAULT_LOCALE, backend=None) -> ParentBatchClassification`, decorated `sensitive_variables('submitted_text')`. The result is the frozen `ParentBatchClassification(items: Tuple[ParentClassification, ...])`, with properties `is_single` and `single`.
- Authorization and the `INPUT_TOO_LONG` check are identical to `classify_for_parent`.
- The service uses `classify_many` when the backend implements it; otherwise it uses `(backend.classify(request),)`.
- More than `MAX_PROPOSALS_PER_INSTRUCTION` outputs gives one item, `ClassificationUnavailable(TOO_MANY_ENTRIES)`, a new `UnavailableReason`.
- Each output goes through the shared `_finish_parent_output(request, output, candidates)` (`_apply_member_mention` → `classify_output(..., require_school_subject=True)` → `_resolve_member`). Extracting it is mandatory: `classify_for_parent` and S-03's `correct_proposal_for_parent` are switched to it in this phase (reuse it if S-03 already extracted an equivalent).
- One output gives exactly what `classify_for_parent` returns for the same output.
- `classify_for_parent` stays as the single-schema entry point for non-view callers and tests; after this slice `capture` calls `classify_entries_for_parent` instead.
- Several outputs: if any result is `ClassificationUnavailable`, or any output has `entry_type=None`, the whole batch becomes a single `_general_note` proposal holding the full text (Assumed Decision 7). Otherwise the items are proposals or follow-ups, in model order.
- The service performs zero database writes.

#### 4. Tests

**File**: `entries/tests/test_batch_classification.py` (new), `entries/tests/test_openai_backend.py`

**Intent**: Pin batch semantics, the single-result equivalence, authorization and privacy.

**Contract**: Fake multi-backend tests cover these cases:
- Three outputs give three proposals that keep each output's date and the shared time.
- A single-output backend (no `classify_many`) gives one item equal to `classify_for_parent`.
- One output with a missing date gives a follow-up item inside a batch.
- One unknown member falls back to the whole-text note.
- A diminutive („z Hanią”) in a batch resolves through `_apply_member_mention`.
- A school event in a batch without a subject is a follow-up item with `SCHOOL_SUBJECT` highlighted.
- Eleven outputs give `TOO_MANY_ENTRIES`.
- A provider timeout gives an unavailable result.
- A child, an outsider and an anonymous user each get `PermissionDenied` with zero backend calls.
- Too-long text makes zero backend calls, and nothing is written to the database.

Adapter tests cover:
- `classify_many` selects the list schema and the larger token budget with the same input keys.
- An ungrounded date in one entry is dropped only for that entry.
- A batch entry's title has its own accepted date phrase stripped by the S-20 guard.
- An empty list gives a `None`-type output.
- `DATE_RULES` appears exactly once in `MULTI_INSTRUCTIONS`.
- The existing exact-input test still passes.

### Success Criteria:

#### Automated Verification:

- Batch service tests pass: `uv run python manage.py test entries.tests.test_batch_classification`
- Adapter and existing classification tests pass: `uv run python manage.py test entries.tests.test_openai_backend entries.tests.test_classification_service entries.tests.test_follow_up_answer`
- Full suite and Django checks pass: `uv run python manage.py test` and `uv run python manage.py check`

#### Manual Verification:

- Reading `DATE_RULES` and `MULTI_INSTRUCTIONS` confirms natural Polish wording that states the rules from Assumed Decision 1 and the one-entry-per-date split

Note on 1.4: S-20 owns and reviews `DATE_RULES`. This check covers only the `MULTI_INSTRUCTIONS` split sentence and that `DATE_RULES` is included exactly once.

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 2: Batch review and all-or-nothing save

### Overview

Branch capture on the batch size, render several proposals on one review page, and save the selected proposals atomically.

### Changes Required:

#### 1. Batch review form

**File**: `entries/forms.py`

**Intent**: Carry several proposals as untrusted, prefixed review forms, each with an include checkbox.

**Contract**:
- `BatchReviewForm(membership, data=None, *, items=None, today=None)` wraps `EntryReviewForm` instances with prefixes `e0`…`e9`. Each instance gains a boolean `include` field labelled „Uwzględnij”, initially ticked.
- A hidden `count` field (1–`MAX_PROPOSALS_PER_INSTRUCTION`; anything else is a stale-form error) controls how many sub-forms are bound.
- Sub-forms are S-01 `EntryReviewForm`s, so each carries the visible school item and the subject.
- `is_valid()` validates only the included sub-forms and requires at least one included proposal, with the non-field error „Wybierz co najmniej jeden wpis.” It also rejects two included sub-forms posting the same `submission_key` with a stale-form error.
- `duplicate_hints()` returns, for each included sub-form, the 1-based number of an earlier sub-form with the same type, title, school item, subject, date and time. The hint text is „Taki sam jak wpis {n}.” and is not an error.
- Helper `batch_review_form_from_classification(membership, batch, today)` builds the initial data from `ParentBatchClassification` items. It gives one fresh `submission_key` per proposal and highlights missing fields as `review_form_from_classification` does.

#### 2. Batch save service

**File**: `entries/services.py`

**Intent**: Save the selected proposals all-or-nothing, with family scope re-checked and each proposal idempotent.

**Contract**: `save_confirmed_entries(user, items: Sequence[dict]) -> List[Entry]`, decorated `sensitive_variables('items')`. It runs inside `transaction.atomic()` and calls `save_confirmed_entry(user, **item)` for each item, in order. The view builds each item from the sub-form's `cleaned_data`, including S-01's `school_subject`. Any `ValidationError` propagates and rolls back every row. A replay with the same keys returns the existing entries and creates none. It raises `ValueError` for zero items or more than `MAX_PROPOSALS_PER_INSTRUCTION`.

#### 3. Views, route and templates

**File**: `entries/views.py`, `entries/urls.py`, `entries/templates/entries/_batch_review_form.html` (new), `entries/templates/entries/capture.html`, `entries/templates/entries/_saved_panel.html`

**Intent**: Show several proposals for review and save the chosen ones. Single results keep the old flow.

**Contract**:
- `capture` calls `classify_entries_for_parent`. When the result `is_single`, the existing branches run unchanged, with `outcome = batch.single`. A `TOO_MANY_ENTRIES` result renders state `unavailable` with the note fallback and the notice „Za dużo wpisów w jednym poleceniu (maks. 10). Podziel polecenie.” Several items render state `batch`, with the heading „Sprawdź wpisy ({n})”.
- New `confirm_batch` view at `POST entries/confirm-batch/` (name `entries:confirm_batch`). It is `require_POST`, `login_required` and parent-only (403 otherwise), with `sensitive_post_parameters()`.
  - An invalid form re-renders `batch` with per-proposal errors and keeps the keys.
  - A `ValidationError` from the service is logged via `_log_rejected_save`. The view then re-renders `batch` with fresh keys for every proposal and the non-field error `SAVE_FAILED_ERROR`.
  - On success it redirects to `entries:capture?saved=<pk>,<pk>,…`.
- `_saved_entry` becomes `_saved_entries`. It accepts up to `MAX_PROPOSALS_PER_INSTRUCTION` comma-separated digit IDs, scoped to the family and in the posted order, and ignores anything else. The saved panel lists each entry. Its heading is „Dodano wpis” for one entry and „Dodano wpisy ({n})” for several.
- `_batch_review_form.html` renders one `<fieldset>` per proposal. Each fieldset has a legend „Wpis {n}”, the „Uwzględnij” checkbox, the `_field.html` rows, the human-readable date line and the duplicate hint. The partial ends with one submit, „Zapisz wpisy”, and „Zacznij od nowa”. It uses existing token classes only, with no inline styles.

#### 4. Tests

**File**: `entries/tests/test_batch_capture_views.py` (new), `entries/tests/test_capture_views.py`

**Intent**: Cover the batch flow, the single-result regression, access, idempotency and privacy.

**Contract**:
- Three proposals render three fieldsets; confirming saves three rows and the redirect lists three IDs.
- Unticking one proposal saves two.
- An unticked invalid proposal does not block the save.
- A batch with a school event saves it with its subject.
- Two included sub-forms with the same `submission_key` give a stale-form error and no rows.
- Unticking all proposals gives a form error and no rows.
- An included proposal with a missing date gives an error, and no row of the batch is saved.
- A service `ValidationError` on the second proposal (for example, a key owned by another family) rolls back the first.
- A replayed POST creates no new rows.
- A tampered `count` (0 or 11) gives a stale-form error.
- A foreign member gives a field error.
- A single-output instruction still renders `proposal` or `question` exactly as before (the existing `test_capture_views` pass unchanged).
- `TOO_MANY_ENTRIES` renders the note fallback with the notice.
- The duplicate hint appears for identical proposals.
- The saved panel ignores foreign or invalid IDs.
- Child, other-family parent and anonymous users are refused on `entries:confirm_batch`.
- No posted text appears in logs.

### Success Criteria:

#### Automated Verification:

- Batch and capture view tests pass: `uv run python manage.py test entries.tests.test_batch_capture_views entries.tests.test_capture_views entries.tests.test_follow_up_views`
- Entry service tests pass: `uv run python manage.py test entries.tests.test_entry_service`
- Full suite, Django checks and migration check pass: `uv run python manage.py test`, `uv run python manage.py check` and `uv run python manage.py makemigrations --check --dry-run`

#### Manual Verification:

- With a stubbed or live backend on a phone-width browser, the three-meetings instruction shows three ticked proposals at 18:00 with the expected dates; unticking one and saving creates exactly two entries, both listed in the saved panel

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 3: Per-proposal free-text correction in the batch review

### Overview

Let the parent correct one proposal in a batch by text. The other proposals are carried through unchanged. It reuses S-03 `free-text-proposal-correction` (landed before S-04): `correct_proposal_for_parent`, the `correction` field S-03 already added to `EntryReviewForm`, `ProposalCorrectionForm` and its notices.

### Changes Required:

#### 1. Batch form correction fields

**File**: `entries/forms.py`

**Intent**: Give each proposal its own correction box, so the target is explicit.

**Contract**: Sub-forms already carry S-03's optional `correction` field. `BatchReviewForm.correction_target(data) -> Optional[int]` reads the posted `action` value `correct-<i>`. Only a 0-based index below `count` is valid. For a correction action only the target is validated: it is bound as S-03's `ProposalCorrectionForm` with prefix `e<i>` (formats, family scope, strict school-type mismatch; schedule rules skipped). The other sub-forms are carried through as posted, unvalidated.
- On `save`, a non-blank `correction` on any sub-form, ticked or not, refuses the save with S-03's error „Masz niezastosowaną poprawkę — naciśnij „Popraw” albo wyczyść pole.” on that sub-form; nothing is saved.

#### 2. Batch endpoint action

**File**: `entries/views.py`, `entries/templates/entries/_batch_review_form.html`

**Intent**: Apply a correction to the targeted proposal only, and re-render the batch for review.

**Contract**:
- `confirm_batch` dispatches on `action`. `save` (the default) behaves as in Phase 2.
- `correct-<i>` calls `correct_proposal_for_parent` with sub-form `i`'s values, its correction and `timezone.localdate()`.
  - When applied: sub-form `i` is replaced by the merged result (highlights if fields are still missing), and its notice reads „Wpis {i+1}: zaktualizowano: {pola}.” Every other proposal keeps its posted values and include state.
  - When not applied (`outcome is None`): sub-form `i` keeps its posted values and correction text, and gets S-03's failure notice (or its school-type mismatch notice) prefixed with „Wpis {i+1}: ”.
  - Fresh `submission_key` values are issued for all proposals on every correction render.
- The partial adds, per fieldset, a `<details>` „Popraw tekstem” with the `correction` field and a submit „Popraw” with `name="action" value="correct-{i}"`, marked `formnovalidate`. „Zapisz wpisy” is the first submit (`action=save`).
- It reuses S-03's stable markup for S-05's Enter handling: the button `id` is `e{i}-correct-submit`, and the textarea carries `data-enter-submitter="e{i}-correct-submit"`. No JavaScript in this slice.

#### 3. Tests

**File**: `entries/tests/test_batch_capture_views.py`

**Intent**: Pin the targeting and preservation rules.

**Contract**:
- Correcting the date of proposal 2 changes only proposal 2. Proposals 1 and 3, including their manual edits and unticked state, are unchanged.
- A broken date in an unticked proposal 3 does not block correcting proposal 1.
- „Zapisz wpisy” with a non-blank correction on any proposal saves nothing and shows the S-03 error on that proposal.
- Each fieldset's „Popraw” button has its stable `id`, matched by the textarea's `data-enter-submitter`.
- A failed correction keeps all three proposals and the text.
- An out-of-range or malformed target gives a stale-form error with no backend call.
- An empty correction for the target gives a field error with no backend call.
- After a correction, saving saves the corrected values.
- The correction text never appears in logs.
- Access is refused for non-parents.

### Success Criteria:

#### Automated Verification:

- Batch view tests including correction pass: `uv run python manage.py test entries.tests.test_batch_capture_views entries.tests.test_correction_views`
- Full suite passes: `uv run python manage.py test`

#### Manual Verification:

- On a phone-width browser, „zmień godzinę na 19:00” on the second of three proposals changes only that proposal's time, and saving creates the three entries with the corrected time on the second

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 4: States page, acceptance corpus and live check

### Overview

Show the batch states on the DEBUG kitchen sink, add the PRD example to the scripted acceptance corpus, and confirm it against the real provider.

### Changes Required:

#### 1. DEBUG states page

**File**: `entries/views.py` (`states`), `entries/tests/test_states_view.py`

**Intent**: Make every batch state reviewable without a provider.

**Contract**: The page adds these sections, built from fictional data:
- `batch`: three meetings at 18:00.
- `batch_duplicate`: a Sunday reference, where "tomorrow" and "next Monday" fall on the same date and show the duplicate hint.
- `batch_missing`: one proposal with its date highlighted.
- `batch_invalid`: the no-selection error.
- `batch_saved`: the saved panel with three entries.
- `too_many`: the note fallback with the cap notice.
- `batch_corrected`: one proposal with its correction notice.

The states test's expected names include all of them.

#### 2. Acceptance corpus

**File**: `entries/tests/test_classification_acceptance.py`

**Intent**: Run the PRD example through the real adapter with a scripted transport, plus an opt-in live case.

**Contract**:
- Scripted case, reference Wednesday 2026-10-07: the scripted list response flows through `classify_entries_for_parent` into three proposals dated 2026-10-07, 2026-10-08 and 2026-10-12 at 18:00. The request carries the reference date and weekday.
- Existing single-entry corpus cases are re-run through `classify_entries_for_parent`: `model_output` gains a list-wrapping variant (`{"entries": [...]}`) used by `run_service`, and each case asserts that `batch.single` equals the previously expected result.
- Live case under `CLASSIFICATION_LIVE_EVAL=1`, skipped by default: the same instruction on a fixed reference date yields three calendar events at 18:00 with the expected dates.

### Success Criteria:

#### Automated Verification:

- States page and acceptance tests pass: `uv run python manage.py test entries.tests.test_states_view entries.tests.test_classification_acceptance`
- Full suite passes: `uv run python manage.py test`

#### Manual Verification:

- The batch sections on `/entries/_states/` render at 360 px width with nothing clipped or overflowing
- A live run with an OpenAI key: the PRD three-meetings instruction (Polish and English) yields three proposals at 18:00 with the dates from Assumed Decision 1 within 30 s, and a single-entry instruction still yields one proposal

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful.

---

## Testing Strategy

### Unit Tests:

- Batch semantics: count cap, whole-batch note fallback, follow-ups inside a batch, and single-output equivalence.
- The adapter list schema, per-entry grounding and the shared `DATE_RULES`.
- The all-or-nothing save and replay idempotency.

### Integration Tests:

- Capture → batch review → save selected proposals, followed by a saved panel with N entries.
- Correcting one proposal preserves the others (Phase 3).
- Access: parent only. Child, other family and anonymous users are refused on `entries:confirm_batch`.
- Privacy: no posted text in logs, and no rows before save.

### Manual Testing Steps:

1. Submit the three-meetings instruction. Check the three dates against Assumed Decision 1 and the time 18:00, then save.
2. Repeat, untick one proposal, and save. Check that two entries were created.
3. Repeat on a Sunday reference (states page). Check that the duplicate hint appears.
4. Submit a single-entry instruction. Check that the old single review or question flow appears.
5. Correct the time on one proposal by text (with S-03 in place). Check that the others are unchanged.

## Performance Considerations

One provider call per instruction, whatever the number of proposals, under the existing 25-second deadline, so the 30-second NFR holds. The larger output budget slightly raises worst-case latency and cost for multi-entry instructions only. Risk: every production capture, including a single-entry one, now uses the list schema and `MULTI_INSTRUCTIONS`, so single-entry quality could shift. The scripted corpus pins the parsing path; live single-entry quality is checked in 4.4. The batch save is up to 10 inserts in one transaction.

## Migration Notes

No schema change. Rollback is a code revert. Single-entry capture, follow-up, EduVulcan intake and API consumers are unaffected. The `saved` query parameter still accepts a single ID.

## References

- PRD v2 PK-05, US-05, Open Questions 1, 6, 11, 12: `context/foundation/prd-v2.md`
- Future roadmap S-04: `context/foundation/roadmap-future.md`
- Interaction with free-text correction: `context/changes/free-text-proposal-correction/plan.md`
- Upstream contracts: `context/changes/school-event-details/plan.md` (S-01), `context/changes/classification-short-names/plan.md` (S-02), `context/changes/title-keeps-action-only/plan.md` (S-20, `DATE_RULES`)
- Semantic validation: `entries/classification/validation.py:45-95`, `:108-112`
- Capture flow: `entries/views.py:94-240`, `entries/forms.py:111-250`
- Backend seam and adapter: `entries/classification/backends.py`, `entries/classification/openai_backend.py:51-150`, `entries/classification/openai_backend.py:359-372`
- Idempotent save: `entries/services.py:21-79`, `entries/models.py:62`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Multi-entry classification boundary

#### Automated

- [x] 1.1 Batch service tests pass — 719fd5a
- [x] 1.2 Adapter and existing classification tests pass — 719fd5a
- [x] 1.3 Full suite and Django checks pass — 719fd5a

#### Manual

- [ ] 1.4 Reading `DATE_RULES` and `MULTI_INSTRUCTIONS` confirms natural Polish wording that states the rules from Assumed Decision 1 and the one-entry-per-date split

### Phase 2: Batch review and all-or-nothing save

#### Automated

- [x] 2.1 Batch and capture view tests pass — ae44e36
- [x] 2.2 Entry service tests pass — ae44e36
- [x] 2.3 Full suite, Django checks and migration check pass — ae44e36

#### Manual

- [ ] 2.4 With a stubbed or live backend on a phone-width browser, the three-meetings instruction shows three ticked proposals at 18:00 with the expected dates; unticking one and saving creates exactly two entries, both listed in the saved panel

### Phase 3: Per-proposal free-text correction in the batch review

#### Automated

- [x] 3.1 Batch view tests including correction pass — c93c4fc
- [x] 3.2 Full suite passes — c93c4fc

#### Manual

- [ ] 3.3 On a phone-width browser, „zmień godzinę na 19:00” on the second of three proposals changes only that proposal's time, and saving creates the three entries with the corrected time on the second

### Phase 4: States page, acceptance corpus and live check

#### Automated

- [x] 4.1 States page and acceptance tests pass
- [x] 4.2 Full suite passes

#### Manual

- [ ] 4.3 The batch sections on `/entries/_states/` render at 360 px width with nothing clipped or overflowing
- [ ] 4.4 A live run with an OpenAI key: the PRD three-meetings instruction (Polish and English) yields three proposals at 18:00 with the dates from Assumed Decision 1 within 30 s, and a single-entry instruction still yields one proposal
