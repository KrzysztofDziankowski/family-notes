# School Event Details Implementation Plan

## Overview

Implement proposed roadmap slice S-01 (`context/foundation/roadmap-future.md`, PK-08, PK-09, US-08, US-09 in `context/foundation/prd-v2.md`): a parent sees, and can correct, the specific school event type (kartkówka, sprawdzian, praca klasowa, zadanie domowe) while reviewing a classified entry. These four kinds also gain a required school subject. Parent-facing capture asks for any missing date, person or subject before confirmation. Existing saved entries and automated EduVulcan intake stay compatible: neither is rejected, rewritten or downgraded because it has no subject.

### Owner Decisions (2026-10-04)

- School subject is free text for now (a fixed list/enum may come later).
- Existing school entries are not backfilled (consistent with the no-backfill decision).
- All future-roadmap slices except removed ones are in the next milestone; confirmed order: S-01, S-02, S-20, S-03, S-04, S-05, S-06, S-07, S-08, S-09, S-17, S-14, S-15, S-16.
- Ship without feature flags and without backfilling existing data.
- No Playwright/E2E tests in this slice; browser tests will be added later.
- On edit, the school subject is required only when the stored entry already had a subject, or when the parent sets or changes the school item to one of the four event kinds. It stays required on capture confirmation and structured creation. Automated EduVulcan entries without a subject stay valid and remain editable without one (owner-confirmed 2026-10-04, review F1).

Owner decisions from the plan review were applied 2026-10-04. Items below that the owner did not address remain assumed defaults; they stand unless the owner objects.

### Assumed Decisions

This plan was written without an owner interview. Each decision below is the recommended option and stands in for an open PRD question.

1. **The school type is visible and editable in capture review.** It uses the same visible select and strict type/school-item mismatch error as the edit form. Detail pages keep showing it, and list rows are unchanged. Rationale: one consistent control across review and edit, and the PRD asks for it "when reviewing or editing". Stands in for PRD Question 9.
2. **The school subject is free text** (trimmed, at most 100 characters) with no fixed vocabulary. Rationale: EduVulcan already delivers subject names verbatim ("Biologia", "Matematyka"), and school subject lists vary by school and grade. Stands in for PRD Question 10.
3. **The subject is required only for the four school event kinds** (homework, class test, test, quiz), and only on parent-facing paths: capture confirmation, structured creation and editing. Other entries may carry a subject but never need one. Rationale: matches PK-09 exactly without widening it. Stands in for PRD Question 10.
4. **Existing entries are not backfilled.** A blank subject stays valid in the database, on detail pages and in the API. Editing a school event that has no stored subject (legacy or automated) does not require one, unless the parent sets or changes its school item to one of the four event kinds; editing an entry that already has a subject keeps it required (owner-confirmed 2026-10-04). Rationale: no data migration risk, and unrelated edits (reassign, move date, retitle) of automated EduVulcan events never fail; this mirrors the `kept_assignee_id` exemption (`entries/services.py:153-171`). Stands in for PRD Questions 10 and 12.
5. **Automated EduVulcan intake never requires a subject.** Rule-based calendar notifications store the subject parsed from the message. The classification fallback stores a subject only when the model returns one. A missing subject never turns an automated school event into a general note. Rationale: protects existing unattended intake, which cannot ask questions. Stands in for PRD Questions 10 and 12.
6. **The automation read API gains an additive `school_subject` key** (`null` when blank). No existing key changes. Rationale: additive JSON is backward compatible for existing consumers, and the value already belongs to the family entry. Stands in for PRD Questions 9 and 12.
7. **Release and compatibility:** one additive migration with a database default, so a code-only rollback can still insert rows. There are no feature flags. Rationale: this follows the established `db_default` rollback pattern in `entries/models.py:133-138`. Stands in for PRD Questions 1, 12 and 20.

## Current State Analysis

- Nine school item kinds already exist. The four event kinds fix `calendar_event` and require date and member (`entries/classification/types.py:36-65`, kinds at `:43-46`). No subject concept exists anywhere in models, forms, classification or API (`grep school_subject` finds nothing).
- `Entry.school_item` is an optional `CharField` with kind choices (`entries/models.py:42-47`). There is no subject column.
- The capture review form carries `school_item` as a hidden input and silently drops it when the parent changes the type (`entries/forms.py:111-163`, hidden widget at `:114-118`). `_review_form.html` renders it hidden (`entries/templates/entries/_review_form.html:17`). Management forms expose it as a visible select with a strict mismatch error (`entries/forms.py:166-187`).
- Required-field rules live in four places that must stay aligned:
  - classifier validation (`entries/classification/validation.py:73-83`)
  - form validation (`entries/forms.py:94-108`)
  - follow-up draft reconstruction (`entries/forms.py:369-398`)
  - service invariants (`entries/services.py:91-105`), shared by manual saves and `create_automated_entry` (`entries/services.py:296-340`)
- Follow-up questions are built from `MissingField` phrases in a fixed order (`entries/classification/follow_up.py:14-47`). Answer merging takes only the missing fields from the backend output (`entries/classification/service.py:200-215`).
- The OpenAI structured schema is strict, with Polish descriptions (`entries/classification/openai_backend.py:69-103`). `classify_for_family` turns any follow-up into a general note (`entries/classification/service.py:369-371`). Adding a required subject without gating would therefore regress EduVulcan classification-path events into notes.
- EduVulcan calendar rules already parse a `subject` group for the four categories and fold it into content as `"Sprawdzian: Biologia"` (`entries/eduvulcan/rules.py:37-39`, `:166-181`). `EntryProposal` has no subject field (`entries/eduvulcan/types.py:46-61`). `_persist` passes proposal fields to `create_automated_entry` (`entries/eduvulcan/conversion.py:384-392`).
- Detail pages show the school item only when one is set (`entries/templates/entries/_manage_detail.html:17-20`, `entries/templates/entries/_child_entry_detail.html:18-20`). The API serializer is an explicit allow-list (`entries/api_views.py:213-226`).
- The uncommitted working-tree changes in `entries/views.py` and `entries/services.py` add only rejected-save logging and a `_locked_family_entry` helper (`entries/services.py:126-136`). This plan builds on that state.

## Desired End State

When a parent captures "Sprawdzian z matematyki dla Michała w piątek", the review form shows "Element szkolny: sprawdzian", "Przedmiot: matematyka", the date and the person, all editable. When the subject is missing, the parent is asked "Z jakiego przedmiotu jest „Sprawdzian”?" (combined with any missing date or person) before the review form. A school event cannot be confirmed or created without a subject, and an edit cannot clear a stored subject or set a school event kind without one; editing an automated or legacy school event that never had a subject does not demand one. EduVulcan school notifications keep converting unattended, and rule-based ones now carry their subject. Previously saved entries render unchanged and stay readable through the API, which also returns `school_subject`.

### Key Discoveries:

- A school kind's `required_fields` drives classifier follow-ups, form errors, draft reconstruction and service invariants (`entries/classification/types.py:53-65`). Adding `MissingField.SCHOOL_SUBJECT` there propagates the rule, but each consumer must also handle the automated exception explicitly.
- `_validate_entry_invariants` is shared by manual and automated writes (`entries/services.py:91-105`, `:326`). The subject requirement must be an explicit parameter, never inferred.
- `classify_for_family` converts follow-ups into notes (`entries/classification/service.py:369-371`). A missing subject must not create a follow-up on that path.
- `EntryReviewForm.rows()` lists the visible fields by name (`entries/forms.py:135-140`). Missing-field hints map `MissingField` to a form field (`entries/forms.py:21-25`).
- The rollback-safe column pattern uses `default` plus `db_default` (`entries/models.py:133-138`, migration `0005_inbound_notification_db_defaults.py`).
- The lessons apply: code is in English, while user-facing copy and OpenAI schema/instruction text are in Polish (`context/foundation/lessons.md`).

## What We're NOT Doing

- No fixed subject vocabulary, subject picker, or normalization of subject spelling.
- No backfill of subjects for existing entries, including EduVulcan entries whose content already contains the subject.
- No subject requirement for grade, substitution, room change, lucky number, late arrival or non-school entries.
- No change to list rows, list grouping or ordering, and no subject filtering in lists or the API.
- No change to EduVulcan rules for grades or timetable changes, even though they parse a subject.
- No JavaScript to show or hide the subject field. It is always visible and optional unless a school event kind is selected.
- No change to child permissions: children see the subject read-only on their own entries.
- No changes to free-text correction (S-03) or multi-entry capture (S-04).

## Implementation Approach

Add the subject as a first-class optional column and a `MissingField`. Make the four event kinds require it, and gate the requirement explicitly per caller: parent paths require it, automated paths never do. Thread the value through the classifier schema, follow-up drafts, forms, services, EduVulcan proposals, templates and the API. Make the review form's school item visible, reusing the management form's strict mismatch rule. Every layer that already enforces date/member gets the same subject rule, so no layer is the only gate.

## Critical Implementation Details

- **Automated exception ordering.** `SchoolItemKind.required_fields` gains `SCHOOL_SUBJECT`, but `validate_output`/`classify_output` and `_validate_entry_invariants` only enforce it when the caller passes the explicit "require subject" flag. `classify_for_family` and `create_automated_entry` never pass it. A test must prove that an automated school event without a subject still persists as a calendar event and is not turned into a note.
- **Cross-slice overlap.** S-02 (`classification-short-names`), S-20 (`title-keeps-action-only`) and S-03 (`free-text-proposal-correction`) also change `BackendOutput`, the structured schema, `INSTRUCTIONS`, the `content` description, `_translate` and `test_openai_backend` expectations. The order is fixed: S-01 lands first, and S-02, S-20 and S-03 build on its `school_subject` schema field, `INSTRUCTIONS` sentence, `BackendOutput` field and `_merge_answer` handling. All new `BackendOutput` fields keep defaults so later slices' constructors stay valid.

## Phase 1: Subject Data Model and Entry Invariants

### Overview

Store the subject and enforce the school-event rule in the service layer, with automated writes explicitly exempt.

### Changes Required:

#### 1. Entry column and migration

**File**: `entries/models.py`, `entries/migrations/0007_entry_school_subject.py` (new)

**Intent**: Persist an optional school subject on every entry without touching existing rows.

**Contract**: `Entry.school_subject = CharField('przedmiot', max_length=100, blank=True, default='', db_default='')`. Add a module constant `SCHOOL_SUBJECT_MAX_LENGTH = 100` and reuse it in forms and rules. The migration is additive only, with no data migration.

#### 2. Required-field vocabulary

**File**: `entries/classification/types.py`

**Intent**: Express "subject required" in the same place as the date and member requirements.

**Contract**: `MissingField.SCHOOL_SUBJECT = 'school_subject'`. `HOMEWORK`, `CLASS_TEST`, `TEST` and `QUIZ` require `(DATE, AFFECTED_MEMBER, SCHOOL_SUBJECT)`. Other kinds are unchanged.

#### 3. Service invariants and write paths

**File**: `entries/services.py`

**Intent**: Make every parent-facing save reject a school event without a subject, while automated EduVulcan saves accept it.

**Contract**:
- `_validate_entry_invariants(..., school_subject='', require_subject=False)` raises the Polish error `'Ten wpis szkolny wymaga przedmiotu.'` only when `require_subject` is true, the kind requires `SCHOOL_SUBJECT` and the stripped subject is empty.
- Subjects longer than `SCHOOL_SUBJECT_MAX_LENGTH` raise `'Przedmiot jest za długi.'` on every path.
- `save_confirmed_entry` and `create_family_entry` gain a `school_subject` keyword, store the stripped value and validate with `require_subject=True`. `MANAGED_FIELDS` includes `school_subject`.
- `update_family_entry` gains a `school_subject` keyword and stores the stripped value. It validates with `require_subject=True` only when the stored entry already had a non-blank subject, or when the new `school_item` is one of the four event kinds and differs from the stored `school_item`; otherwise it passes `require_subject=False` (owner-confirmed 2026-10-04). The decision is computed from the locked row, like `kept_assignee_id`.
- `create_automated_entry` gains an optional `school_subject=''` keyword and always validates with `require_subject=False`.
- Idempotent repeats of `save_confirmed_entry` still return the first saved row unchanged.

### Success Criteria:

#### Automated Verification:

- Migration is present and model drift is clean: `uv run python manage.py makemigrations --check --dry-run`
- Service tests cover required subject on confirm, create and update for each of the four kinds, optional subject elsewhere, subject length limit, and the automated path accepting a blank subject: `uv run python manage.py test entries.tests.test_entry_service`
- Service tests cover the edit rule: updating a subject-less automated or legacy school event (reassign, move date, retitle) saves without a subject; clearing an existing subject fails; changing the school item to one of the four kinds without a subject fails: `uv run python manage.py test entries.tests.test_entry_service`
- Contract tests reflect the new `SCHOOL_SUBJECT` required field for exactly the four event kinds: `uv run python manage.py test entries.tests.test_classification_contract`
- Django checks pass: `uv run python manage.py check`

#### Manual Verification:

- Running the migration against a copy of a database containing existing school entries leaves every row with an empty subject and no other change.

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase. Phase blocks use plain bullets — the corresponding `- [ ]` checkboxes for these items live in the `## Progress` section at the bottom of the plan.

---

## Phase 2: Classification Recognizes and Asks for the Subject

### Overview

Teach the parent classification path to return the subject and to ask for it when it is missing. The automated path keeps its current outcome.

### Changes Required:

#### 1. Provider-neutral types and backend schema

**File**: `entries/classification/backends.py`, `entries/classification/types.py`, `entries/classification/openai_backend.py`

**Intent**: Carry the subject from the model into transient results without logging it.

**Contract**:
- `BackendOutput`, `ClassificationProposal` and `ClassificationFollowUp` gain `school_subject: Optional[str] = field(default=None, repr=False)`.
- `StructuredClassification` gains a required nullable `school_subject` field with a Polish description, for example "Przedmiot szkolny (np. matematyka) dla sprawdzianu, kartkówki, pracy klasowej lub zadania domowego, tylko jeśli wynika z polecenia; inaczej null."
- `INSTRUCTIONS` gains one Polish sentence asking for the subject under the same "do not invent" rule.
- The adapter translates the value into `BackendOutput`. The request input payload is unchanged.

#### 2. Validation with an explicit subject gate

**File**: `entries/classification/validation.py`, `entries/management/commands/classification_smoke.py`, `entries/tests/test_classification_live_wire.py`

**Intent**: Ask for a missing subject only where the parent can answer.

**Contract**:
- `validate_output` and `classify_output` gain a keyword-only `require_school_subject: bool`. Callers must pass it, including `entries/management/commands/classification_smoke.py:80` (passes `False`: it checks provider health, not the parent flow), every `classify_output` call in `entries/tests/test_classification_live_wire.py` (pass the value matching the flow exercised) and the existing calls in `entries/tests/test_classification_contract.py`.
- When true and the recognized kind requires `SCHOOL_SUBJECT` and the stripped subject is empty, `MissingField.SCHOOL_SUBJECT` is added to the follow-up.
- The trimmed subject, capped at 100 characters (a longer value is dropped to `None`), is copied into proposals and follow-ups.
- When `require_school_subject` is false, the subject never adds a missing field.

#### 3. Service wiring, answer merge and question

**File**: `entries/classification/service.py`, `entries/classification/follow_up.py`

**Intent**: Parent paths require the subject. The automated path passes it through but never asks.

**Contract**:
- `classify_for_parent` and `classify_follow_up_answer` call `classify_output(..., require_school_subject=True)`.
- `classify_for_family` calls it with `False`, and its `ClassificationProposal` carries the subject.
- `_merge_answer` takes `school_subject` from the output only when the draft is missing `SCHOOL_SUBJECT`, otherwise from the draft.
- `_PHRASES` gains `SCHOOL_SUBJECT: ('Z jakiego przedmiotu jest {subject}', 'z jakiego przedmiotu')`, asked after date and member.

### Success Criteria:

#### Automated Verification:

- Validation tests prove that the four kinds without a subject produce a `SCHOOL_SUBJECT` follow-up only when required, that the subject is trimmed and passed through, and that a subject in an automated proposal never adds a missing field: `uv run python manage.py test entries.tests.test_classification_contract`
- Service tests cover parent classification, answer merge filling only a missing subject, and `classify_for_family` returning `CLASSIFIED` (not a general note) for a school event without a subject: `uv run python manage.py test entries.tests.test_classification_service entries.tests.test_family_classification entries.tests.test_follow_up_answer`
- Adapter tests cover the new schema field and translation, and that the input payload is unchanged: `uv run python manage.py test entries.tests.test_openai_backend entries.tests.test_classification_acceptance`
- Every `classify_output` caller, including the smoke command and the skipped live-wire tests, passes `require_school_subject` (no `TypeError`): `grep -rn "classify_output(" entries`

#### Manual Verification:

- With live classification enabled locally, "Kartkówka z historii dla <dziecko> jutro" yields subject "historia", and "Sprawdzian dla <dziecko> w piątek" asks for the subject.

**Implementation Note**: After completing this phase and all automated verification passes, pause for manual confirmation before proceeding.

---

## Phase 3: Parent Review, Follow-up and Management UI

### Overview

Show the school type and subject in capture review and require them on confirmation. Carry the subject through follow-up drafts, and add it to management forms and detail pages.

### Changes Required:

#### 1. Forms

**File**: `entries/forms.py`

**Intent**: One visible, consistently validated school type and subject across capture review, structured creation and editing.

**Contract**:
- `EntryFieldsForm` gains `school_subject = CharField(label='Przedmiot', max_length=100, required=False, strip=True)`.
- `_require_schedule_fields` adds the Polish error `'Podaj przedmiot.'` when the selected kind requires `SCHOOL_SUBJECT` and the subject is blank. On `EntryEditForm` the check applies only when the instance already had a subject or the parent changed `school_item` to one of the four kinds (same rule as `update_family_entry`); capture review and structured create always apply it.
- `EntryReviewForm.school_item` becomes the same visible labelled select as `ManagedEntryForm`: label `Element szkolny`, empty choice `Brak`. It uses the strict mismatch error instead of silent clearing. Move the strict `clean` into a shared helper or base class.
- `rows()` lists `entry_type, content, school_item, school_subject, date, time, assigned_member`.
- `MISSING_FIELD_HINTS[SCHOOL_SUBJECT] = ('school_subject', 'Podaj przedmiot.')`.
- `review_form_from_classification`, `skip_review_form` and `EntryEditForm` prefill `school_subject`.
- `FollowUpAnswerForm` gains a hidden `school_subject`. `_DRAFT_FIELDS`, `follow_up_form_from_classification`, `_draft_from_cleaned` (which allows `SCHOOL_SUBJECT` when required and blank) and `proposal_from_draft` carry it.

#### 2. Views and templates

**File**: `entries/views.py`, `entries/templates/entries/_review_form.html`, `_manage_form.html`, `_manage_detail.html`, `_child_entry_detail.html`

**Intent**: Persist the subject from every parent save path and display it wherever the school item is shown.

**Contract**:
- `confirm`, `create` and `edit` pass `school_subject` to their services.
- The review template drops the separate hidden `{{ form.school_item }}`, because the field is now a visible row.
- The manage form includes the subject field after the school item.
- Manage and child detail pages show `<dt>Przedmiot</dt>` only when the subject is set.
- All copy is in Polish, with no inline styles. Reuse `_field.html`.

#### 3. DEBUG state galleries

**File**: `entries/views.py` (`states`, `_manage_state_sections`, `child_states`)

**Intent**: Keep the kitchen sinks representative.

**Contract**:
- Synthetic school proposals carry a fictional subject.
- Add a capture state `follow_up_subject` (a test with date and member, subject missing) and a question state asking for the subject.
- Manage and child detail states show a subject.
- No `Entry` rows are written.

### Success Criteria:

#### Automated Verification:

- Form tests cover a visible school item in review, the strict mismatch error in review, the required subject for the four kinds in review/create/edit, the follow-up hidden subject round-trip and tamper handling, editing a subject-less school entry without changing its school item saving successfully, and setting a school event kind or clearing a stored subject on edit failing with `Podaj przedmiot.`: `uv run python manage.py test entries.tests.test_entry_forms entries.tests.test_follow_up_views`
- View tests cover confirm/create/edit persisting the subject, the capture follow-up asking for the subject, and detail pages rendering `Przedmiot` only when set: `uv run python manage.py test entries.tests.test_capture_views entries.tests.test_manage_views entries.tests.test_child_views`
- State gallery tests cover the new states, DEBUG gating and zero database writes: `uv run python manage.py test entries.tests.test_states_view entries.tests.test_manage_states entries.tests.test_child_states_view`

#### Manual Verification:

- At 360px width in the capture state gallery, the review form shows the school type select and subject field clearly, and the subject question reads naturally in Polish.
- In Chrome on Android, a parent captures a test without a subject, answers the question, sees the subject in review, saves, and sees it on the detail page.

**Implementation Note**: After completing this phase and all automated verification passes, pause for manual confirmation before proceeding.

---

## Phase 4: Automated Intake and Read Compatibility

### Overview

Fill the subject from rule-based EduVulcan notifications, expose it additively through the API, and prove existing data and intake keep working.

### Changes Required:

#### 1. EduVulcan proposals and persistence

**File**: `entries/eduvulcan/types.py`, `entries/eduvulcan/rules.py`, `entries/eduvulcan/conversion.py`

**Intent**: Store the subject the school notification already provides, without changing content or outcome.

**Contract**:
- `EntryProposal` gains `school_subject: str = field(default='', repr=False)`.
- `_calendar` sets it from the normalized `subject` group, but only when its length is at most `SCHOOL_SUBJECT_MAX_LENGTH`. A longer subject stays blank and the entry is still saved. Content is unchanged.
- `_convert` copies the classified proposal's subject.
- `_persist` passes `school_subject` to `create_automated_entry`.
- Grade and timetable rules are unchanged.

#### 2. API and admin

**File**: `entries/api_views.py`, `entries/admin.py`

**Intent**: Make the subject readable by existing automation consumers without breaking their parsing.

**Contract**:
- `serialize_entry` adds `'school_subject': entry.school_subject or None`. No other key changes.
- The admin entry list shows `school_item` and `school_subject` (English admin labels allowed).

### Success Criteria:

#### Automated Verification:

- EduVulcan rule tests assert the subject for the four calendar categories, a blank subject for over-long values, and unchanged content: `uv run python manage.py test entries.tests.test_eduvulcan_rules entries.tests.test_eduvulcan_acceptance`
- Conversion tests prove that a rule-based school event persists its subject and that a classified school event without a subject persists as a calendar event, not a general note: `uv run python manage.py test entries.tests.test_conversion_worker entries.tests.test_conversion_lifecycle`
- API tests cover `school_subject` for set and blank entries and confirm that the existing keys are unchanged: `uv run python manage.py test entries.tests.test_entries_api`
- Full suite passes: `uv run python manage.py test`
- Django checks pass: `uv run python manage.py check`
- Migration drift check passes: `uv run python manage.py makemigrations --check --dry-run`

#### Manual Verification:

- A forwarded EduVulcan "Sprawdzian" notification on a local stack creates an entry whose detail page shows the subject.
- A pre-existing school entry without a subject still renders on parent and child detail pages and in the API response.

**Implementation Note**: Complete manual verification before implementation review.

---

## Testing Strategy

### Unit Tests:

- Required-field matrix: each of the four kinds × {parent, automated} × {subject present, blank, over-long}, plus edit × {stored subject, no stored subject} × {kind unchanged, kind set/changed}.
- The follow-up question order and combined wording with date, member and subject.
- `_merge_answer` fills only a missing subject and keeps the draft subject otherwise.
- Strict visible school-item mismatch in review and management forms.

### Integration Tests:

- Capture → question (subject) → answer → review → confirm stores the subject.
- Structured create and edit with and without the subject; an unrelated edit of a subject-less legacy or automated school entry saves; clearing a stored subject or setting a school kind without a subject on edit is rejected.
- EduVulcan rule and classification conversion with and without a subject.
- The API read shows `school_subject` and keeps the existing shape.

### Manual Testing Steps:

1. Capture "Sprawdzian dla Michała w piątek" and confirm that the subject question appears before review.
2. In review, change the school item to "Brak" with type "Wydarzenie" and confirm that it saves without a subject.
3. Edit an existing school entry without a subject (only reassign it) and confirm that it saves; then change its school item to another event kind and confirm that the subject is requested.
4. Forward a synthetic EduVulcan test notification and confirm that the subject is stored and the entry is a calendar event.

## Performance Considerations

There is one extra short non-null text column, and one extra field in the provider schema (a few output tokens). No new queries.

## Migration Notes

Additive `AddField` with `default=''` and `db_default=''`. Existing rows receive an empty subject, and nothing is backfilled. Rolling back the code without reverting the migration stays safe, because the database default fills the column for inserts from the previous release. A reverse migration drops the column.

## References

- Roadmap slice: `context/foundation/roadmap-future.md` (S-01)
- PRD: `context/foundation/prd-v2.md` (PK-08, PK-09, US-08, US-09, Open Questions 9, 10, 12)
- School kinds: `entries/classification/types.py:36-65`
- Review vs. managed forms: `entries/forms.py:111-187`
- Service invariants: `entries/services.py:91-105`, `:296-340`
- EduVulcan calendar rule: `entries/eduvulcan/rules.py:166-181`
- Prior intake plan: `context/changes/eduvulcan-school-event-intake/plan.md`
- House-style reference: `context/archive/2026-09-28-parent-family-entry-management/plan.md`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Subject Data Model and Entry Invariants

#### Automated

- [x] 1.1 Migration is present and model drift is clean: `uv run python manage.py makemigrations --check --dry-run` — 6cf2ca4
- [x] 1.2 Service tests cover required subject on confirm, create and update for each of the four kinds, optional subject elsewhere, subject length limit, and the automated path accepting a blank subject: `uv run python manage.py test entries.tests.test_entry_service` — 6cf2ca4
- [x] 1.3 Contract tests reflect the new `SCHOOL_SUBJECT` required field for exactly the four event kinds: `uv run python manage.py test entries.tests.test_classification_contract` — 6cf2ca4
- [x] 1.4 Django checks pass: `uv run python manage.py check` — 6cf2ca4
- [x] 1.6 Service tests cover the edit rule: updating a subject-less automated or legacy school event (reassign, move date, retitle) saves without a subject; clearing an existing subject fails; changing the school item to one of the four kinds without a subject fails: `uv run python manage.py test entries.tests.test_entry_service` — 6cf2ca4

#### Manual

- [ ] 1.5 Running the migration against a copy of a database containing existing school entries leaves every row with an empty subject and no other change.

### Phase 2: Classification Recognizes and Asks for the Subject

#### Automated

- [x] 2.1 Validation tests prove that the four kinds without a subject produce a `SCHOOL_SUBJECT` follow-up only when required, that the subject is trimmed and passed through, and that a subject in an automated proposal never adds a missing field: `uv run python manage.py test entries.tests.test_classification_contract` — 65d57b8
- [x] 2.2 Service tests cover parent classification, answer merge filling only a missing subject, and `classify_for_family` returning `CLASSIFIED` (not a general note) for a school event without a subject: `uv run python manage.py test entries.tests.test_classification_service entries.tests.test_family_classification entries.tests.test_follow_up_answer` — 65d57b8
- [x] 2.3 Adapter tests cover the new schema field and translation, and that the input payload is unchanged: `uv run python manage.py test entries.tests.test_openai_backend entries.tests.test_classification_acceptance` — 65d57b8
- [x] 2.5 Every `classify_output` caller, including the smoke command and the skipped live-wire tests, passes `require_school_subject` (no `TypeError`): `grep -rn "classify_output(" entries` — 65d57b8

#### Manual

- [ ] 2.4 With live classification enabled locally, "Kartkówka z historii dla <dziecko> jutro" yields subject "historia", and "Sprawdzian dla <dziecko> w piątek" asks for the subject.

### Phase 3: Parent Review, Follow-up and Management UI

#### Automated

- [x] 3.1 Form tests cover a visible school item in review, the strict mismatch error in review, the required subject for the four kinds in review/create/edit, the follow-up hidden subject round-trip and tamper handling, editing a subject-less school entry without changing its school item saving successfully, and setting a school event kind or clearing a stored subject on edit failing with `Podaj przedmiot.`: `uv run python manage.py test entries.tests.test_entry_forms entries.tests.test_follow_up_views`
- [x] 3.2 View tests cover confirm/create/edit persisting the subject, the capture follow-up asking for the subject, and detail pages rendering `Przedmiot` only when set: `uv run python manage.py test entries.tests.test_capture_views entries.tests.test_manage_views entries.tests.test_child_views`
- [x] 3.3 State gallery tests cover the new states, DEBUG gating and zero database writes: `uv run python manage.py test entries.tests.test_states_view entries.tests.test_manage_states entries.tests.test_child_states_view`

#### Manual

- [ ] 3.4 At 360px width in the capture state gallery, the review form shows the school type select and subject field clearly, and the subject question reads naturally in Polish.
- [ ] 3.5 In Chrome on Android, a parent captures a test without a subject, answers the question, sees the subject in review, saves, and sees it on the detail page.

### Phase 4: Automated Intake and Read Compatibility

#### Automated

- [ ] 4.1 EduVulcan rule tests assert the subject for the four calendar categories, a blank subject for over-long values, and unchanged content: `uv run python manage.py test entries.tests.test_eduvulcan_rules entries.tests.test_eduvulcan_acceptance`
- [ ] 4.2 Conversion tests prove that a rule-based school event persists its subject and that a classified school event without a subject persists as a calendar event, not a general note: `uv run python manage.py test entries.tests.test_conversion_worker entries.tests.test_conversion_lifecycle`
- [ ] 4.3 API tests cover `school_subject` for set and blank entries and confirm that the existing keys are unchanged: `uv run python manage.py test entries.tests.test_entries_api`
- [ ] 4.4 Full suite passes: `uv run python manage.py test`
- [ ] 4.5 Django checks pass: `uv run python manage.py check`
- [ ] 4.6 Migration drift check passes: `uv run python manage.py makemigrations --check --dry-run`

#### Manual

- [ ] 4.7 A forwarded EduVulcan "Sprawdzian" notification on a local stack creates an entry whose detail page shows the subject.
- [ ] 4.8 A pre-existing school entry without a subject still renders on parent and child detail pages and in the API response.
