# Parent Note Assignment Implementation Plan

## Overview

Roadmap-future slice S-07 (PK-03, US-03): a parent can reliably assign a new note to themselves or to another parent in the same family, as well as to a child. Research shows the capability already exists in every parent write path: assignee choices are all active members of the parent's family, regardless of role. Nothing in the test suite proves it, though, because every fixture family has exactly one parent. This plan therefore takes a verification-first approach. It adds a two-parent regression matrix across manual creation, natural-language capture, editing, listing, detail, the automation read API, and child visibility. Code changes are allowed only where a matrix test fails. The plan also makes parent assignees visible in the DEBUG state gallery so the visual gate covers them. Finally, at the owner's request (2026-10-04), Phase 3 resolves a self-reference in free text ("dla mnie", "mi", "ja") to the requesting parent. This is the slice's only production change by design, and it changes the data sent to OpenAI by one key.

### Owner Decisions (2026-10-04)

- All future-roadmap slices except removed ones are in the next milestone; confirmed order: S-01, S-02, S-20, S-03, S-04, S-05, S-06, S-07, S-08, S-09, S-17, S-14, S-15, S-16. S-02, S-20, S-03 and S-04 therefore land before S-07.
- Self-reference: when the parent writes "dla mnie" / "mi" / "ja", the proposal is assigned to the requesting parent automatically (owner-confirmed 2026-10-04; plan-review F2). This adds Phase 3 and one new key to the OpenAI payload (owner-approved 2026-10-04).
- Ship without feature flags and without backfilling existing data.
- No Playwright/E2E tests in this slice; browser tests will be added later.

Owner decisions from the plan review were applied 2026-10-04. Items below that the owner did not address remain assumed defaults; they stand unless the owner objects.

### Assumed Decisions

1. **Parent assignment applies to both manual creation and classification review.** Both paths already share `EntryFieldsForm` and the same candidate list, so excluding one would be a regression. (PRD Open Question 4)
2. **All entry types (todo, event, note) keep accepting parent assignees, not notes only.** The form is type-agnostic today (`entries/forms.py:77`), and narrowing it would remove existing behavior. (PRD Open Question 4)
3. **Self-reference in free text ("dla mnie", "mi", "ja") resolves to the requesting parent (owner-confirmed 2026-10-04).** Today the requester is not identified to the classifier, so "dla mnie" yields an unassigned proposal. Phase 3 sends the requester's display name, which is already one of `dozwolone_osoby`, under one new payload key `autor_polecenia`. A Polish instruction maps self-references to it, and the title rule drops the phrase ("dla mnie: kupić mleko" → "Kupić mleko"). Member validation is unchanged: the name must still be an allowed active member. The parent's own capture and the parent's S-03 text correction get the key ("przypisz mnie", "dla mnie" in a correction assigns the requester; owner-confirmed 2026-10-04); follow-up answers and automated EduVulcan classification do not. (PRD Open Question 4)
4. **Automated EduVulcan intake stays child-only.** `snapshot_active_children` (`entries/eduvulcan/children.py:13`) is intentional, and US-03 covers parent-created notes only. (PRD Open Question 4)
5. **No visual "(ja)" or role marker in the assignee dropdown.** Labels stay the display names. A marker is not demonstrated as necessary, and it would change every form. (PRD Open Questions 4 and 12)
6. **Release scope and compatibility:** no schema or data migration. Existing entries are unaffected. (PRD Open Questions 1, 12, 20)

## Current State Analysis

- Assignee choices for review, structured create, and edit are all active members of the parent's own family, of every role, ordered by pk (`entries/forms.py:84-88`). Edit additionally keeps a since-deactivated current assignee (`entries/forms.py:212-220`). The follow-up form uses the same queryset (`entries/forms.py:307`).
- The write services validate only that the assignee belongs to the family and is active. They impose no role restriction (`entries/services.py:94-98`, `entries/services.py:153-170`).
- Classification sends the display names of all active family members, parents included, to the backend (`entries/classification/service.py:110-116`, `entries/classification/service.py:243-247`). It resolves a returned name locally to exactly one member (`entries/classification/service.py:250-265`). Existing tests assert that the parent's name `Ewa` is in the allow-list (`entries/tests/test_classification_service.py:256`).
- Parent list and detail rows render `assigned_member.display_name` or "Cała rodzina" without role logic (`entries/templates/entries/_entry_row.html:21`). The API serializes only `display_name` (`entries/api_views.py:213-222`).
- Child reads filter `assigned_member=membership` (`entries/services.py:257-270`), so a parent-assigned entry is never visible to a child.
- Gap in evidence: every test fixture has one parent (`entries/tests/test_classification_service.py:73-103`). No test creates, edits, classifies, lists, or serializes an entry assigned to a second parent or to the author, and no test checks that a foreign family's parent is rejected as an assignee.
- The DEBUG gallery's synthetic assignee choices are children only (`entries/views.py:244`), so the visual gate never shows a parent option.
- The OpenAI payload is built only by `build_input` (`entries/classification/openai_backend.py:134-150`). It sends the reference date, weekday, locale, `dozwolone_osoby` and `polecenie`, plus the follow-up keys only when answering. The module docstring is the privacy contract for what is sent (`openai_backend.py:9-14`). The requester's membership is known in `classify_for_parent` (`entries/classification/service.py:102`) but is not passed to `BackendRequest` (`entries/classification/backends.py:19-40`).
- Write paths added by earlier slices in the confirmed order: S-03 re-resolves the member through `_resolve_member` with a trusted `current_member` in `correct_proposal_for_parent` (`context/changes/free-text-proposal-correction/plan.md:112-117`). S-04 adds `classify_entries_for_parent`, `batch_review_form_from_classification` and the `entries:confirm_batch` endpoint (`context/changes/multi-entry-text-capture/plan.md:110-117`, `:177`, `:195`); after S-04, `capture` calls `classify_entries_for_parent`.
- S-20 adds the title rule to `StructuredClassification.content` and `INSTRUCTIONS`, the shared `DATE_RULES` constant, and `strip_extracted_phrases` in `entries/classification/title.py`, wired in `_translate` (`context/changes/title-keeps-action-only/plan.md` Phases 1–2). S-02 adds `member_mention` and `_apply_member_mention`, where a mention with zero matches leaves the output unchanged (`context/changes/classification-short-names/plan.md:139-167`).

## Desired End State

Automated tests prove that an active parent can create, confirm from capture, answer a follow-up, correct (S-03), batch-save (S-04), and edit an entry assigned to themselves or to the other parent of the family. They also prove that such entries appear correctly in the parent list, detail, and automation API, never appear in any child's list or detail, and that a parent from another family can never be assigned. The DEBUG gallery shows a parent among the assignee options and a parent-assigned row. Any defect the matrix uncovers is fixed with a minimal reviewed diff. Entering "dla mnie: kupić mleko" as the parent Ewa produces a todo proposal titled "Kupić mleko" with Ewa preselected.

### Key Discoveries:

- `EntryFieldsForm.__init__` is the single assignee-choice contract for review, create, and edit (`entries/forms.py:84`).
- `_validate_entry_invariants` is the single service-level assignee guard (`entries/services.py:91`).
- Classification candidates come from `_active_family_members` (`entries/classification/service.py:243`).
- AGENTS.md requires parent, assigned-child, other-child, and unauthenticated access cases for every visibility or mutation path.

## What We're NOT Doing

- No OpenAI payload change beyond the single `autor_polecenia` key on the parent's own capture and S-03 correction (Phase 3). Follow-up answers and EduVulcan classification send byte-identical payloads.
- No change to member validation: a self-reference resolves only to the requester's allow-listed active membership.
- No role markers, grouping, or reordering in the assignee dropdown.
- No parent-assigned EduVulcan entries.
- No parent "my entries" view (the parent family list stays the only parent list; see S-08 for grouping).
- No schema migration and no data backfill.
- No change to child visibility rules: unassigned and parent-assigned entries stay invisible to children.

## Implementation Approach

Extend the shared test fixtures with a second active parent in the same family and use the existing other-family parent. Then add a regression matrix at each layer (form, service, classification resolution, capture/confirm view, management views, API, child views). Run it. When a test fails, treat it as a demonstrated gap: fix the production code minimally in the owning module and never weaken the assertion. Then add a parent assignee to the DEBUG gallery and verify the result manually at phone width. Finally, add requester-aware self-reference resolution on top of the S-02/S-20 prompt contract.

## Phase 1: Two-Parent Assignment Regression Matrix

### Overview

Prove the parent-assignment contract end to end, and fix only what the proof shows broken.

### Changes Required:

#### 1. Two-parent fixtures

**File**: new test classes in the test modules below, built on `FamilyFixtureMixin` (`entries/tests/test_classification_service.py:73`)

**Intent**: Give the family a second active parent so tests can tell "self" from "other parent" assignment, without changing the shared mixin.

**Contract**: The new test classes add `self.second_parent` (role parent, active, same family, distinct display name) and one inactive parent in their own `setUp`. They reuse the mixin's `_member` helper and the existing `other_family_parent`. The shared `FamilyFixtureMixin` stays unchanged, so existing exact-member assertions (for example `entries/tests/test_entry_forms.py:44-49` and `entries/tests/test_classification_service.py:256`) remain valid.

#### 2. Form and service matrix

**File**: `entries/tests/test_entry_forms.py`, `entries/tests/test_entry_service.py`

**Intent**: Prove that review, create, and edit forms accept self and the other parent, and that services persist them.

**Contract**: For `EntryReviewForm`, `EntryCreateForm`, and `EntryEditForm`, the author and `second_parent` are valid choices. `other_family_parent` and inactive parents are rejected with the existing Polish error. `save_confirmed_entry`, `create_family_entry`, and `update_family_entry` persist `assigned_member` equal to the author or the other parent, for a note and for at least one other entry type. A foreign-family parent raises `ValidationError` without writing a row.

#### 3. Classification resolution

**File**: `entries/tests/test_classification_service.py`, `entries/tests/test_capture_views.py` (capture → confirm), `entries/tests/test_follow_up_views.py` (follow-up answer and skip), and, since S-03/S-04 land earlier, `entries/tests/test_proposal_correction.py`, `entries/tests/test_correction_views.py`, `entries/tests/test_batch_classification.py`, `entries/tests/test_batch_capture_views.py`. (`test_family_classification.py` covers `classify_for_family`, which acts for no user, so it is not a home for these tests.)

**Intent**: Prove that a classifier result naming a parent resolves to that membership and pre-selects it in the review form.

**Contract**: A fake backend that returns the second parent's display name yields `ParentClassification.member == second_parent`. A result naming the requesting parent resolves to the requester. `review_form_from_classification` sets `assigned_member` initial to that member. Posting the confirm view saves the entry with that assignee.

Follow-up (`/entries/answer/`, same queryset as review, `entries/forms.py:307`): an answer, and a skip with a parent preselected, both save the parent assignee.

S-03/S-04 paths (they land before S-07 in the confirmed order; if either has not merged, record its part as N/A in the phase commit): a correction keeps a parent `current_member` when the correction does not mention the person; `batch_review_form_from_classification` offers both parents per proposal, and `entries:confirm_batch` saves a parent assignee per proposal. Use the endpoint and helper names as merged by S-04.

#### 4. Read paths and isolation

**File**: `entries/tests/test_manage_views.py`, `entries/tests/test_entries_api.py`, `entries/tests/test_child_views.py`

**Intent**: Prove that parent-assigned entries surface everywhere a parent reads, and nowhere a child reads.

**Contract**: The parent index and detail render the parent assignee's display name for a parent-assigned entry. The automation API returns `assigned_member.display_name` for it. Child list and detail exclude it: the detail returns 404 with the same body as a missing ID, and the child's own and the other child's views are both covered. Anonymous access is unchanged (login redirect).

#### 5. Demonstrated-gap fixes (conditional)

**File**: whichever of `entries/forms.py`, `entries/services.py`, `entries/classification/service.py`, `entries/views.py`, templates a failing test points to

**Intent**: Fix only a defect a matrix test exposes.

**Contract**: Each fix is the smallest change in the owning module, keeps family scoping in both form and service layers, and is noted in the phase's commit message. If no test fails, this item is a no-op and is recorded as such.

### Success Criteria:

#### Automated Verification:

- Form and service tests prove that self and other-parent assignment are accepted and that foreign-family and inactive parents are rejected without writes.
- Classification tests prove that a parent's display name resolves to that parent and pre-fills the review form, and that confirming saves the assignee.
- Read-path tests prove that the parent index, parent detail, and API show the parent assignee and that child list and detail never expose a parent-assigned entry.
- Targeted tests pass: `uv run python manage.py test entries.tests.test_entry_forms entries.tests.test_entry_service entries.tests.test_classification_service entries.tests.test_capture_views entries.tests.test_follow_up_views entries.tests.test_manage_views entries.tests.test_entries_api entries.tests.test_child_views entries.tests.test_child_entries` (plus the S-03/S-04 modules named in item 3 once merged)
- Full suite, checks and migration check pass: `uv run python manage.py test`, `uv run python manage.py check`, `uv run python manage.py makemigrations --check --dry-run`
- Follow-up, correction and batch tests prove that a follow-up answer or skip, an S-03 correction, and an S-04 batch save keep or save a parent assignee: `uv run python manage.py test entries.tests.test_follow_up_views entries.tests.test_proposal_correction entries.tests.test_correction_views entries.tests.test_batch_classification entries.tests.test_batch_capture_views`

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 2: Gallery Coverage and Manual Verification

### Overview

Make parent assignees visible in the DEBUG visual gate and confirm the real flow on a phone-width screen.

### Changes Required:

#### 1. Gallery assignee options and a parent-assigned row

**File**: `entries/views.py` (`STATES_MEMBER_CHOICES`, `_manage_state_sections`), `entries/tests/test_states_view.py`, `entries/tests/test_manage_states.py`

**Intent**: Show a parent among the synthetic assignee options, and include one parent-assigned synthetic row, so the screenshot gate covers this slice.

**Contract**: The synthetic choices add one fictional parent name after the children. The upcoming list state includes one note assigned to that parent. The gallery still reads and writes no family data and returns 404 with `DEBUG=False`. Gallery tests assert that the parent name appears in the create form options and in the list state.

### Success Criteria:

#### Automated Verification:

- Gallery tests assert that the synthetic parent appears in assignee options and in the upcoming list state: `uv run python manage.py test entries.tests.test_states_view entries.tests.test_manage_states`
- Django checks pass: `uv run python manage.py check`

#### Manual Verification:

- At phone width, a parent creates a note via "Nowy wpis" assigned to themselves and another assigned to the other parent; both show the right name in the list and detail.
- Via "Dodaj wpis z tekstu", a parent writes a note naming the other parent; the review form pre-selects that parent and saving keeps it.
- Signed in as a child, neither note is visible in "Moje wpisy".
- A phone-width screenshot of the gallery list state is saved under `context/changes/parent-note-assignment/screenshots/`.

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding.

---

## Phase 3: Self-Reference Resolves to the Requesting Parent

### Overview

When the parent writes "dla mnie", "mi" or "ja", assign the proposal to the requesting parent and keep the phrase out of the title (owner-confirmed 2026-10-04). This builds on the S-02 (`member_mention`) and S-20 (title rule, `DATE_RULES`, `strip_extracted_phrases`) contracts, which land earlier; it does not change them beyond the additions below.

### Changes Required:

#### 1. Requester on the backend request

**File**: `entries/classification/backends.py`, `entries/classification/service.py`

**Intent**: Tell the backend who is asking, only on the parent's own capture.

**Contract**:
- `BackendRequest` gains `requester_name: Optional[str] = field(default=None, repr=False)`; its docstring says it is set only for a parent's own capture and is always one of `allowed_member_names`.
- `classify_for_parent` and S-04's `classify_entries_for_parent` (or their shared request helper) set it to the requesting membership's `display_name`.
- S-03's `correct_proposal_for_parent` also sets it to the requesting parent's display name (owner-confirmed 2026-10-04). `classify_follow_up_answer` and `classify_for_family` leave it `None` (no requester for follow-ups and EduVulcan).
- The service module docstring step 3 ("Invoke") names the requester's display name as sent data.
- Member validation and `_resolve_member` are unchanged: a returned name must still be exactly one allow-listed active member. S-02's `_apply_member_mention` is unchanged; a self-reference mention ("ja", "mnie") matches no candidate and leaves the output as is.

#### 2. Payload key and Polish instruction

**File**: `entries/classification/openai_backend.py`

**Intent**: Send the requester under one Polish key and teach the model to map self-references to it.

**Contract**:
- `build_input` adds `'autor_polecenia': request.requester_name` after `dozwolone_osoby`, only when `requester_name is not None` — in both the capture payload and S-03's correction payload (`context/changes/free-text-proposal-correction/plan.md:112`). A request without a requester (follow-up, EduVulcan) produces a byte-identical payload.
- S-03's `CORRECTION_INSTRUCTIONS` gains the matching Polish sentence: if `autor_polecenia` is present and the correction refers to its author („przypisz mnie”, „dla mnie”, „to dla mnie”), set `osoba` to that value and list `member_name` in `changed_fields`.
- `INSTRUCTIONS` gains one Polish sentence, for example: "Jeśli dane zawierają autor_polecenia, a polecenie odnosi się do autora (np. „dla mnie”, „mi”, „ja”), ustaw member_name na wartość autor_polecenia, member_mention na null i nie umieszczaj tego zwrotu w treści." S-04's `MULTI_INSTRUCTIONS` inherits it because it extends `INSTRUCTIONS`.
- S-20's title rule (the `content` field description) also lists the self-reference phrase among the extracted values that never appear in the title. The schema shape is unchanged.
- The module docstring privacy paragraph lists the requester's display name (parent capture only, already one of the allowed names) among the data sent, and records: "Changes the data sent to OpenAI: `autor_polecenia` added by S-07 (owner-approved 2026-10-04)."

#### 3. Title guard drops the self-reference

**File**: `entries/classification/title.py` (created by S-20), `entries/classification/openai_backend.py` (`_translate` and S-04's per-item translation)

**Intent**: Remove "dla mnie" and similar from the title when the model still echoes it.

**Contract**: `strip_extracted_phrases` gains `self_reference: bool = False`. When true, it also removes, case-insensitively, a leading self-reference phrase from the fixed tuple `SELF_REFERENCE_PHRASES = ('dla mnie', 'mnie', 'mi', 'ja')` (longest first, whole words, optional trailing comma or colon) and a trailing "dla mnie", then re-capitalizes. The S-20 rules apply unchanged: never an empty title, other people and details stay. The adapter passes `self_reference=True` only when `request.requester_name` is set and the returned `member_name` equals it exactly.

#### 4. Tests and live check

**File**: `entries/tests/test_openai_backend.py`, `entries/tests/test_title_cleanup.py`, `entries/tests/test_classification_service.py`, `entries/tests/test_classification_acceptance.py`, `entries/tests/test_follow_up_answer.py`, `entries/tests/test_family_classification.py`, `entries/tests/test_batch_classification.py` (S-04), `entries/tests/test_classification_live_wire.py`

**Intent**: Pin the new payload contract, the guard, the resolution and the exclusions.

**Contract**:
- Adapter: the exact-payload test (`test_input_is_minimal_payload`, `entries/tests/test_openai_backend.py:287`) keeps a requester-less request unchanged; a new test pins `autor_polecenia` for a capture request and for a correction request with a requester; `CORRECTION_INSTRUCTIONS` contains the self-reference sentence; the follow-up payload test (`:304`) asserts the key is absent; `INSTRUCTIONS` contains the self-reference sentence; the content description names the self-reference phrase.
- Guard: "dla mnie: kupić mleko" → "Kupić mleko"; "Kupić mleko dla mnie" → "Kupić mleko"; "mi kupić mleko" → "Kupić mleko"; "Kupić prezent dla mamy" unchanged; `self_reference=False` leaves "dla mnie" in place; "dla mnie" alone unchanged (no empty title).
- Service: a fake backend capturing the request sees `requester_name` equal to the requesting parent's display name in `classify_for_parent`, `classify_entries_for_parent` and `correct_proposal_for_parent`, and `None` in `classify_follow_up_answer` and `classify_for_family`. A correction "przypisz mnie" on a proposal assigned to a child yields the requesting parent. A returned foreign or inactive name still yields `UNKNOWN_MEMBER`; a duplicate display name still yields `AMBIGUOUS_MEMBER`.
- Acceptance (adapter path, family Ewa (requester), second parent, Kasia): scripted output `member_name="Ewa"`, content "dla mnie: kupić mleko" → todo proposal "Kupić mleko", member Ewa; a clean output gives the same result; text naming the second parent still resolves to the second parent.
- Live (opt-in, skipped unless `CLASSIFICATION_LIVE_EVAL=1`): "dla mnie: kupić mleko" with requester Ewa → member Ewa, title "Kupić mleko" (case-insensitive).

### Success Criteria:

#### Automated Verification:

- Adapter tests prove that `autor_polecenia` is sent only with a requester, that requester-less and follow-up payloads are unchanged, and that the instructions carry the self-reference rule: `uv run python manage.py test entries.tests.test_openai_backend`
- Guard tests prove that self-reference phrases are stripped only when the resolved member is the requester: `uv run python manage.py test entries.tests.test_title_cleanup`
- Service and acceptance tests prove that "dla mnie: kupić mleko" yields the requester and the title "Kupić mleko", that corrections carry the requester while follow-up and EduVulcan requests do not, and that member validation is unchanged: `uv run python manage.py test entries.tests.test_classification_service entries.tests.test_classification_acceptance entries.tests.test_follow_up_answer entries.tests.test_family_classification entries.tests.test_batch_classification`
- Full suite and checks pass, with live tests skipped by default: `uv run python manage.py test`, `uv run python manage.py check`

#### Manual Verification:

- With `CLASSIFICATION_LIVE_EVAL=1` and a configured key, the live self-reference case passes.
- In the running app as `test_rodzic` (Ewa), entering "dla mnie: kupić mleko" shows the review form with title "Kupić mleko" and Ewa preselected; saving keeps Ewa as the assignee.
- Reading the adapter module docstring confirms that the privacy contract lists `autor_polecenia` and records the owner approval of 2026-10-04.

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding.

---

## Testing Strategy

### Unit Tests:

- Form choice sets with two parents, one inactive parent, and a foreign-family parent.
- Service persistence for self and other-parent assignees across create, confirm, and update, with foreign-family rejection and no rows written.
- Classification member resolution for both parent names.
- Payload key `autor_polecenia` present only on parent capture; self-reference title guard.

### Integration Tests:

- Capture → review → confirm with a fake backend naming a parent.
- Follow-up answer/skip, S-03 correction and S-04 batch save with a parent assignee.
- Adapter-path "dla mnie: kupić mleko" → requester assignee, title "Kupić mleko".
- Parent index, detail, and API rendering of parent assignees, plus the child list and detail isolation matrix (own child, other child, anonymous).

### Manual Testing Steps:

1. Create a note for yourself and for the other parent via the structured form; check the list and detail.
2. Capture a note naming the other parent; confirm the pre-selection and the save.
3. Sign in as a child; confirm that neither note is visible.
4. As `test_rodzic`, enter "dla mnie: kupić mleko"; confirm the title and that Ewa is preselected.

## Performance Considerations

None. No new queries. Rows already `select_related('assigned_member')`. Phase 3 adds one short key to the payload and one sentence to the instructions.

## Migration Notes

None. No schema or data change. Existing entries keep their assignees. The OpenAI payload change (Phase 3) applies to new parent captures only.

## References

- Roadmap item: `context/foundation/roadmap-future.md` (S-07)
- PRD: `context/foundation/prd-v2.md` (PK-03, US-03, Open Question 4)
- Assignee contract: `entries/forms.py:84`
- Service guard: `entries/services.py:91`
- Classification candidates: `entries/classification/service.py:243`
- Payload builder and privacy contract: `entries/classification/openai_backend.py:9-14`, `:134-150`
- Earlier slices relied on: `context/changes/classification-short-names/plan.md:139-167` (S-02), `context/changes/title-keeps-action-only/plan.md` Phases 1–2 (S-20), `context/changes/free-text-proposal-correction/plan.md:90-117` (S-03), `context/changes/multi-entry-text-capture/plan.md:100-117`, `:177-195` (S-04)
- Prior plan style: `context/archive/2026-09-28-parent-family-entry-management/plan.md`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Two-Parent Assignment Regression Matrix

#### Automated

- [x] 1.1 Form and service tests prove that self and other-parent assignment are accepted and that foreign-family and inactive parents are rejected without writes.
- [x] 1.2 Classification tests prove that a parent's display name resolves to that parent and pre-fills the review form, and that confirming saves the assignee.
- [x] 1.3 Read-path tests prove that the parent index, parent detail, and API show the parent assignee and that child list and detail never expose a parent-assigned entry.
- [x] 1.4 Targeted tests pass: `uv run python manage.py test entries.tests.test_entry_forms entries.tests.test_entry_service entries.tests.test_classification_service entries.tests.test_capture_views entries.tests.test_follow_up_views entries.tests.test_manage_views entries.tests.test_entries_api entries.tests.test_child_views entries.tests.test_child_entries` (plus the S-03/S-04 modules named in item 3 once merged)
- [x] 1.5 Full suite, checks and migration check pass: `uv run python manage.py test`, `uv run python manage.py check`, `uv run python manage.py makemigrations --check --dry-run`
- [x] 1.6 Follow-up, correction and batch tests prove that a follow-up answer or skip, an S-03 correction, and an S-04 batch save keep or save a parent assignee: `uv run python manage.py test entries.tests.test_follow_up_views entries.tests.test_proposal_correction entries.tests.test_correction_views entries.tests.test_batch_classification entries.tests.test_batch_capture_views`

### Phase 2: Gallery Coverage and Manual Verification

#### Automated

- [ ] 2.1 Gallery tests assert that the synthetic parent appears in assignee options and in the upcoming list state: `uv run python manage.py test entries.tests.test_states_view entries.tests.test_manage_states`
- [ ] 2.2 Django checks pass: `uv run python manage.py check`

#### Manual

- [ ] 2.3 At phone width, a parent creates a note via "Nowy wpis" assigned to themselves and another assigned to the other parent; both show the right name in the list and detail.
- [ ] 2.4 Via "Dodaj wpis z tekstu", a parent writes a note naming the other parent; the review form pre-selects that parent and saving keeps it.
- [ ] 2.5 Signed in as a child, neither note is visible in "Moje wpisy".
- [ ] 2.6 A phone-width screenshot of the gallery list state is saved under `context/changes/parent-note-assignment/screenshots/`.

### Phase 3: Self-Reference Resolves to the Requesting Parent

#### Automated

- [ ] 3.1 Adapter tests prove that `autor_polecenia` is sent only with a requester, that requester-less and follow-up payloads are unchanged, and that the instructions carry the self-reference rule: `uv run python manage.py test entries.tests.test_openai_backend`
- [ ] 3.2 Guard tests prove that self-reference phrases are stripped only when the resolved member is the requester: `uv run python manage.py test entries.tests.test_title_cleanup`
- [ ] 3.3 Service and acceptance tests prove that "dla mnie: kupić mleko" yields the requester and the title "Kupić mleko", that corrections carry the requester while follow-up and EduVulcan requests do not, and that member validation is unchanged: `uv run python manage.py test entries.tests.test_classification_service entries.tests.test_classification_acceptance entries.tests.test_follow_up_answer entries.tests.test_family_classification entries.tests.test_batch_classification`
- [ ] 3.4 Full suite and checks pass, with live tests skipped by default: `uv run python manage.py test`, `uv run python manage.py check`

#### Manual

- [ ] 3.5 With `CLASSIFICATION_LIVE_EVAL=1` and a configured key, the live self-reference case passes.
- [ ] 3.6 In the running app as `test_rodzic` (Ewa), entering "dla mnie: kupić mleko" shows the review form with title "Kupić mleko" and Ewa preselected; saving keeps Ewa as the assignee.
- [ ] 3.7 Reading the adapter module docstring confirms that the privacy contract lists `autor_polecenia` and records the owner approval of 2026-10-04.
