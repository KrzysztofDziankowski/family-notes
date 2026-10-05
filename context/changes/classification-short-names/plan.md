# Classification Short Names Implementation Plan

## Overview

This plan implements proposed roadmap slice S-02 (`context/foundation/roadmap-future.md`), covering PK-01 and US-01 in `context/foundation/prd-v2.md`. When a parent refers to a family member by a short name or diminutive during classification ("Hania"), the proposal is assigned to the matching member of the parent's own family ("Hanna"). When the name could match more than one active member of that family, the parent is asked who is meant before any assignment. Matching is deterministic and local, and it is limited to the active members of the parent's family.

### Owner Decisions (2026-10-04)

- Short names come from a built-in, code-maintained dictionary for now (no per-member nicknames).
- All future-roadmap slices except removed ones are in the next milestone; confirmed order: S-01, S-02, S-20, S-03, S-04, S-05, S-06, S-07, S-08, S-09, S-17, S-14, S-15, S-16.
- Ship without feature flags and without backfilling existing data.
- No Playwright/E2E tests in this slice; browser tests will be added later.

Plan-review fixes were applied 2026-10-04. Items below that the owner did not address remain assumed defaults; they stand unless the owner objects.

### Assumed Decisions

This plan was written without an owner interview. Each item below is the recommended option and stands in for a PRD open question.

1. **Mappings come from a built-in, code-maintained dictionary of common Polish diminutives** (owner-confirmed 2026-10-04). Examples: Hania/Hanka → Hanna, Anna; Kasia → Katarzyna; Tymek → Tymoteusz. Nobody maintains per-family aliases in this slice. Rationale: this covers the recorded example without a migration or an admin/member-management UI, which S-14 does not yet provide. It stands in for PRD Question 2 (supported names; who maintains mappings).
2. **Matching scope (two-tier):** an exact match (the mention equals a member's full display name or given name, i.e. first word, case-insensitively) is decisive when it hits at least one candidate. Only when no candidate matches exactly does group matching apply (both names belong to the same dictionary group). Diacritics stay significant. Rationale: this is predictable, names the parent typed exactly never become questions, and the dictionary encodes the variants. It stands in for PRD Question 2.
3. **Ambiguity:** a short name matching two or more active family members never picks one. It produces the existing "Której osoby dotyczy…?" clarification (`AMBIGUOUS_MEMBER`) with no member preselected. Rationale: this is required by PK-01. Source: PRD (not assumed).
4. **No match:** behaviour is unchanged. The model's allow-listed name is used if valid. Otherwise the current "unknown member" outcome applies: an unavailable notice with a note fallback. Rationale: this is the smallest change, and it keeps the existing security tests for invented, inactive and foreign names intact. It stands in for PRD Question 2 (what happens when no unique member matches).
5. **Scope of flows:** the change applies to parent capture classification and to answers to follow-up questions. It does not apply to automated EduVulcan classification, which keeps exact child-name matching (`entries/eduvulcan/children.py:36-48`). Rationale: school systems send full names, and an unattended flow cannot ask a clarification question. It stands in for PRD Questions 2 and 12.
6. **The model reports the person as mentioned, in the nominative case** (`member_mention`, for example "Hani" → "Hania"). This value is used only to select among the already allow-listed active family candidates. It is never logged and never shown. Rationale: Polish inflection makes a verbatim-grounding check impractical, and the mention cannot introduce a member outside the candidate set. It stands in for PRD Question 2.
7. **Release:** no schema migration, no data change and no feature flag. Rationale: the change is code-only and reverts cleanly. It stands in for PRD Questions 1, 12 and 20.

## Current State Analysis

- `classify_for_parent` sends the backend only the active family members' display names (`entries/classification/service.py:110-118`). The model must return `member_name` as "exactly one name from the list, unchanged" (`entries/classification/openai_backend.py:101-103`, `:118-119`).
- Validation accepts `member_name` only as an exact, whitespace-trimmed, case-sensitive allow-list match (`entries/classification/validation.py:34-36`, `:61-71`). A name occurring twice becomes `AMBIGUOUS_MEMBER`; an unlisted name raises `UNKNOWN_MEMBER`. Tests pin this case-sensitivity and the rejection of invented, inactive and foreign names (`entries/tests/test_classification_service.py:305-345`, `entries/tests/test_classification_contract.py:282-300`).
- `_resolve_member` maps the validated name to exactly one candidate locally and fails closed otherwise (`entries/classification/service.py:250-268`).
- As a result, "Hania" with a member "Hanna" either relies on the model silently substituting "Hanna" (picking one even when "Anna" also exists) or fails as `UNKNOWN_MEMBER`. The schema has no channel to express "this short name fits several people".
- The ambiguity UX already exists: `MissingField.AMBIGUOUS_MEMBER` (`entries/classification/types.py:29`), the Polish question "Której osoby dotyczy…" (`entries/classification/follow_up.py:17`), the review hint "Wybierz osobę." (`entries/forms.py:24`), and draft reconstruction, which allows `AMBIGUOUS_MEMBER` whenever no member is set (`entries/forms.py:382-385`).
- The follow-up answer merge takes `member_name` from the output only when a member field was missing (`entries/classification/service.py:200-215`).
- The automated family path uses its own exact, case-insensitive child matcher (`entries/eduvulcan/children.py:31-48`) and turns follow-ups into notes (`entries/classification/service.py:369-371`).

## Desired End State

A parent in a family with an active child "Hanna" types "Hania ma jutro dentystę". The review proposal has "Dla kogo: Hanna" preselected. If the family also has an active "Anna", the parent is instead asked "Której osoby dotyczy „…”?" and no one is preselected. Typing "Hania" as the answer to a member question resolves the same way. Names of inactive members and of other families' members never resolve. EduVulcan intake behaviour is unchanged.

### Key Discoveries:

- Member resolution is already local and family-scoped. The new matcher must take its candidates from `_active_family_members` (`entries/classification/service.py:243-247`) and nothing else.
- A local, provider-independent flag is the clean way to carry ambiguity into `validate_output`, because the provider never asserts ambiguity itself.
- `test_openai_backend` asserts the exact input payload (per the `missing-info-follow-up` plan). This slice changes only the output schema and instructions, so the input payload stays identical.
- From `context/foundation/lessons.md`: code is written in English; the schema descriptions and instructions sent to OpenAI are written in Polish.
- From AGENTS.md: classification input stays limited to producing the entry. The mention is transient, excluded from `repr`, and never logged or stored.

## What We're NOT Doing

- Per-family or per-member custom nicknames, an alias model, or alias management in the admin or the app.
- Fuzzy, phonetic, or edit-distance matching, and diacritic-insensitive matching.
- Changing the no-match outcome (`UNKNOWN_MEMBER` → note fallback).
- Short-name matching in EduVulcan rules or `classify_for_family`.
- Changes to the manual create and edit forms: they use a select, not free text.
- Sending any additional data to OpenAI. The request payload is unchanged.
- Changes to who may be assigned an entry. Note assignment is S-07.

## Implementation Approach

1. Add a pure, deterministic name-matching module with the diminutive dictionary.
2. Extend the provider output with a transient `member_mention`. The service resolves the mention against the active family candidates before validation:
   - A unique match rewrites `member_name` to that candidate's exact display name.
   - Several matches clear `member_name` and set a local ambiguity flag, which validation turns into `AMBIGUOUS_MEMBER`.
   - No match leaves the model's `member_name` to the existing exact validation.
3. Apply the same step to follow-up answers when the member was missing.

## Critical Implementation Details

- **Precedence.** A resolvable mention overrides the model's `member_name`, because the parent's words win over the model's choice. The ambiguity check runs on the mention's full candidate set, not on the model's pick. This prevents the model from silently choosing Hanna over Anna. In a follow-up answer to a member question, the parent's answer text wins over the model's `member_mention`: `match_mention(answer.strip(), candidates)` runs first, and a unique match decides the member. This prevents a loop in which the instruction's "Hania" keeps re-triggering the ambiguity question after the parent answered "Hanna".
- **Cross-slice overlap.** The order is fixed: S-01 (`school-event-details`) lands first, then S-02, then S-20 (`title-keeps-action-only`), then S-03 (`free-text-proposal-correction`). S-02 builds on S-01's defaulted `BackendOutput.school_subject`, its required `require_school_subject` keyword on `validate_output`/`classify_output` (S-02's new calls pass the same value as their path), and its `_merge_answer` change. S-20 consumes S-02's `member_mention`. Every new field keeps a default.
- **No field-by-field rebuilds.** `_apply_member_mention` must build its result with `dataclasses.replace(output, ...)`, never a field-by-field `BackendOutput(...)` constructor, so S-01's `school_subject` (and later slices' fields) survive resolution. A test asserts that `school_subject` survives both resolution and answer merge.

## Phase 1: Deterministic Short-Name Matcher

### Overview

Provide a pure function that returns the active candidates a spoken name can refer to, backed by a curated Polish diminutive dictionary.

### Changes Required:

#### 1. Name matching module

**File**: `entries/classification/names.py` (new)

**Intent**: Encode, in one auditable place, which short forms belong to which given names, and how a mention selects candidates.

**Contract**:
- `DIMINUTIVES: Mapping[str, FrozenSet[str]]` maps a full given name to its short forms. All entries are lowercase NFC. It covers at least the recorded example (`hanna: {hania, hanka, hanusia}`), Anna's forms (including `hania`, `ania`, `anka`), and a modest list of common Polish given names. Keep it data-only and sorted.
- `name_group(name) -> FrozenSet[str]` returns the normalized name plus every full name it belongs to, either as the full name itself or as one of its short forms.
- `match_mention(mention: str, candidates: Sequence[T], *, display_name: Callable[[T], str]) -> Tuple[T, ...]` is two-tier. Tier 1: the candidates whose full display name or given name (first word) equals the mention after normalization (NFC, trimmed, casefolded); if this yields any candidate, it is returned and group matching is skipped. Tier 2 (only when tier 1 is empty): the candidates whose name group intersects the mention's group. Candidate order is preserved, and a blank mention returns an empty tuple.
- No database access. The function never logs.

#### 2. Unit tests

**File**: `entries/tests/test_short_names.py` (new)

**Intent**: Pin the matching semantics independently of classification.

**Contract**: Cover the following cases:
- Hania → Hanna is unique.
- Hania → {Hanna, Anna} is ambiguous.
- Exact and case-insensitive full-name matches.
- Display names with a surname.
- A display name that is itself a diminutive ("Kasia") matched by its full form ("Katarzyna").
- Diacritics remain significant ("Michal" ≠ "Michał").
- A blank mention or an unknown name returns nothing.
- Exact beats group: display names "Hania" and "Ania" with mention "Ania" → only Ania (not ambiguous).
- Group fallback is pinned explicitly: a family with only display name "Hania" and mention "Ania" → the tier-2 result is asserted by a test, so the behaviour is visible and reviewed.

### Success Criteria:

#### Automated Verification:

- Matcher unit tests pass: `uv run python manage.py test entries.tests.test_short_names`
- Django checks pass: `uv run python manage.py check`

#### Manual Verification:

- The owner skims the dictionary and confirms it covers the family's names and expected diminutives.

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase. Phase blocks use plain bullets — the corresponding `- [ ]` checkboxes for these items live in the `## Progress` section at the bottom of the plan.

---

## Phase 2: Classification Resolves Mentions with Clarification on Ambiguity

### Overview

Carry the mentioned name from the model, then resolve it locally against the active family members for both first classification and follow-up answers.

### Changes Required:

#### 1. Backend types and OpenAI schema

**File**: `entries/classification/backends.py`, `entries/classification/openai_backend.py`

**Intent**: Let the model report the person as the parent named them, without changing what is sent.

**Contract**:
- `BackendOutput` gains `member_mention: Optional[str] = field(default=None, repr=False)` and `member_ambiguous: bool = False`. `member_ambiguous` is set only by the local resolver and never by an adapter.
- `StructuredClassification` gains a required, nullable `member_mention`. Its Polish description: the name or diminutive of the person exactly as the parent used it, converted to the nominative case (e.g. „Hania”); null if the instruction names no person.
- `INSTRUCTIONS` gains Polish sentences: always fill `member_mention`; if the parent uses a diminutive or short form, `member_name` is the matching name from the allowed list; when `odpowiedz_rodzica` is present, `member_mention` is the person named in the answer. There is no "return null when several fit" clause: `INSTRUCTIONS` is shared with `classify_for_family` (`entries/classification/service.py:349-366`), where a null `member_name` on a school event becomes a follow-up and then a general note (`:369-371`), and the local resolver decides ambiguity anyway.
- The adapter translates `member_mention`. The input payload is unchanged.

#### 2. Validation honours local ambiguity

**File**: `entries/classification/validation.py`

**Intent**: Turn locally detected ambiguity into the existing clarification.

**Contract**:
- When `output.member_ambiguous` is true, `validate_output` appends `MissingField.AMBIGUOUS_MEMBER` and leaves `member_name` as `None`. This holds for every recognized entry type; when `entry_type` is null, the existing early general-note return (`validation.py:47-48`) runs first and the ambiguity is ignored.
- For school kinds, `AFFECTED_MEMBER` is also appended (`validation.py:82`); `follow_up_question` de-duplicates the question, and tests expect both missing fields.
- The existing exact, case-sensitive allow-list rules are otherwise unchanged.

#### 3. Service resolution step

**File**: `entries/classification/service.py`

**Intent**: Resolve mentions in the parent paths only, from the family-scoped candidates.

**Contract**: New private `_apply_member_mention(output, candidates) -> BackendOutput`, which returns `dataclasses.replace(output, ...)` (never a field-by-field rebuild). With no mention, it returns `output` unchanged. Otherwise it calls `match_mention` over the active candidates:
- Exactly one candidate: `member_name` becomes that candidate's `display_name`.
- Two or more: `member_name=None, member_ambiguous=True`.
- Zero: `output` is returned unchanged.

Call sites:
- `classify_for_parent` applies it before `classify_output`.
- `classify_follow_up_answer`, only when the draft was missing a member field, first runs `match_mention(answer.strip(), candidates)`; a unique match sets `member_name` to that candidate and skips the model's mention. Otherwise it applies `_apply_member_mention` to the merged output. `_merge_answer` carries `member_mention` from the output in that case and `None` otherwise.
- `classify_for_family` does not call it.

#### 4. Acceptance corpus

**File**: `entries/tests/test_classification_acceptance.py`, `entries/tests/test_classification_service.py`, `entries/tests/test_follow_up_answer.py`, `entries/tests/test_openai_backend.py`

**Intent**: Prove the recorded example end to end through the real adapter with a scripted transport, plus the safety matrix.

**Contract**:
- Synthetic family with "Hanna": the model returns `member_mention="Hania"` → proposal with Hanna resolved.
- Family with "Hanna" and "Anna": the model returns `member_name="Hanna"`, `member_mention="Hania"` → an `AMBIGUOUS_MEMBER` follow-up with no member.
- A mention matching only an inactive or other-family member never resolves, and the existing `UNKNOWN_MEMBER` tests stay green.
- Follow-up answer "Hania" fills a missing member.
- Follow-up loop guard: family with Hanna and Anna, instruction "Hania…", answer "Hanna", the model returns `member_mention="Hania"` → the proposal has Hanna (no repeated question).
- `classify_for_family` regression: a school event naming a child still resolves to that child as before (the shared `INSTRUCTIONS` change does not turn it into a note).
- `school_subject` survives `_apply_member_mention` and answer merge.
- `classify_for_family` ignores the mention.
- `repr` of the request, output and results never contains the mention.

### Success Criteria:

#### Automated Verification:

- Adapter tests cover the new schema field, its translation and the unchanged input payload: `uv run python manage.py test entries.tests.test_openai_backend`
- Validation and service tests cover the unique, ambiguous and no-match cases, inactive and foreign safety, and repr safety: `uv run python manage.py test entries.tests.test_classification_contract entries.tests.test_classification_service`
- Follow-up answer tests cover resolving a short-name answer and the ambiguous answer: `uv run python manage.py test entries.tests.test_follow_up_answer`
- Follow-up answer text wins over the model's stale mention (Hanna+Anna family, instruction "Hania", answer "Hanna" → Hanna, no repeated question), and `school_subject` survives resolution and merge: `uv run python manage.py test entries.tests.test_follow_up_answer entries.tests.test_classification_service`
- Acceptance corpus includes the Hania → Hanna example and the ambiguity example: `uv run python manage.py test entries.tests.test_classification_acceptance`
- Automated family classification is unchanged, including a school event naming a child: `uv run python manage.py test entries.tests.test_family_classification entries.tests.test_conversion_worker`

#### Manual Verification:

- With live classification enabled locally (`CLASSIFICATION_LIVE_EVAL=1` or a local run), "Hania ma jutro dentystę" in a family with "Hanna" preselects Hanna.

**Implementation Note**: After completing this phase and all automated verification passes, pause for manual confirmation before proceeding.

---

## Phase 3: Capture Flow Regression and Visual Check

### Overview

Prove the parent-facing capture flow handles short names and their ambiguity correctly, and keep the DEBUG state gallery representative.

### Changes Required:

#### 1. View-level tests

**File**: `entries/tests/test_capture_views.py`, `entries/tests/test_follow_up_views.py`

**Intent**: Exercise the full request path with a fake backend.

**Contract**:
- `POST /entries/capture/` with a unique short-name mention renders the proposal with the resolved member selected.
- With an ambiguous mention, it renders the question state with "Której osoby dotyczy", and no hidden assignee is set.
- Answering with an unambiguous short name renders the proposal with that member.
- Confirming saves exactly the selected member.
- No view or template change is expected. Any needed change is limited to wiring.

#### 2. State gallery

**File**: `entries/views.py` (`states`)

**Intent**: Make the ambiguity clarification visible for review.

**Contract**:
- Add a fictional `question_ambiguous_member` state: a draft with `AMBIGUOUS_MEMBER` missing, rendered through `follow_up_form_from_classification`.
- It uses no real names and writes no database rows.

### Success Criteria:

#### Automated Verification:

- Capture and follow-up view tests pass: `uv run python manage.py test entries.tests.test_capture_views entries.tests.test_follow_up_views`
- State gallery tests include the new state and still prove DEBUG gating and zero writes: `uv run python manage.py test entries.tests.test_states_view`
- Full suite passes: `uv run python manage.py test`
- Django checks pass: `uv run python manage.py check`
- Migration drift check passes: `uv run python manage.py makemigrations --check --dry-run`

#### Manual Verification:

- At 360px width, the `question_ambiguous_member` gallery state reads naturally in Polish and the answer field is usable.
- In Chrome on Android, a parent in a family with "Hanna" captures an instruction about "Hania", sees Hanna preselected, and saves the entry assigned to Hanna.

**Implementation Note**: Complete manual verification before implementation review.

---

## Testing Strategy

### Unit Tests:

- Matcher semantics: unique, ambiguous, exact, case-insensitive, surname, reverse diminutive, diacritics, blank, unknown, exact-beats-group collisions.
- `_apply_member_mention` precedence over the model's `member_name`.
- Validation of `member_ambiguous` across entry types.

### Integration Tests:

- Real adapter with a scripted transport: Hania → Hanna; Hania with Hanna and Anna → clarification.
- Follow-up answer with a short name.
- Capture → proposal/question → confirm through the views.
- Family isolation: inactive and other-family names never resolve.

### Manual Testing Steps:

1. Configure a local family with an active child "Hanna" and capture "Hania ma jutro dentystę"; confirm that Hanna is preselected.
2. Add an active member "Anna" and repeat; confirm that the clarification question appears and no one is preselected.
3. Answer "Hanna" and confirm that the review shows Hanna.

## Performance Considerations

There are a few extra output tokens and an in-memory dictionary lookup over at most a handful of family members. There are no new queries.

## Migration Notes

Not applicable: no schema or data changes. Reverting the code restores the previous behaviour.

## References

- Roadmap slice: `context/foundation/roadmap-future.md` (S-02)
- PRD: `context/foundation/prd-v2.md` (PK-01, US-01, Business Logic Changes, Open Questions 2 and 12)
- Member resolution: `entries/classification/service.py:243-268`
- Allow-list validation: `entries/classification/validation.py:43-71`
- Model schema and instructions: `entries/classification/openai_backend.py:69-131`
- Follow-up flow: `entries/classification/follow_up.py:14-47`, `entries/forms.py:369-398`
- Automated child matching (unchanged): `entries/eduvulcan/children.py:31-48`
- Prior follow-up plan: `context/changes/missing-info-follow-up/plan.md`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Deterministic Short-Name Matcher

#### Automated

- [x] 1.1 Matcher unit tests pass: `uv run python manage.py test entries.tests.test_short_names` — e316efb
- [x] 1.2 Django checks pass: `uv run python manage.py check` — e316efb

#### Manual

- [x] 1.3 The owner skims the dictionary and confirms it covers the family's names and expected diminutives.

### Phase 2: Classification Resolves Mentions with Clarification on Ambiguity

#### Automated

- [x] 2.1 Adapter tests cover the new schema field, its translation and the unchanged input payload: `uv run python manage.py test entries.tests.test_openai_backend` — 6462e37
- [x] 2.2 Validation and service tests cover the unique, ambiguous and no-match cases, inactive and foreign safety, and repr safety: `uv run python manage.py test entries.tests.test_classification_contract entries.tests.test_classification_service` — 6462e37
- [x] 2.3 Follow-up answer tests cover resolving a short-name answer and the ambiguous answer: `uv run python manage.py test entries.tests.test_follow_up_answer` — 6462e37
- [x] 2.7 Follow-up answer text wins over the model's stale mention (Hanna+Anna family, instruction "Hania", answer "Hanna" → Hanna, no repeated question), and `school_subject` survives resolution and merge: `uv run python manage.py test entries.tests.test_follow_up_answer entries.tests.test_classification_service` — 6462e37
- [x] 2.4 Acceptance corpus includes the Hania → Hanna example and the ambiguity example: `uv run python manage.py test entries.tests.test_classification_acceptance` — 6462e37
- [x] 2.5 Automated family classification is unchanged, including a school event naming a child: `uv run python manage.py test entries.tests.test_family_classification entries.tests.test_conversion_worker` — 6462e37

#### Manual

- [ ] 2.6 With live classification enabled locally (`CLASSIFICATION_LIVE_EVAL=1` or a local run), "Hania ma jutro dentystę" in a family with "Hanna" preselects Hanna.

### Phase 3: Capture Flow Regression and Visual Check

#### Automated

- [x] 3.1 Capture and follow-up view tests pass: `uv run python manage.py test entries.tests.test_capture_views entries.tests.test_follow_up_views` — fca6790
- [x] 3.2 State gallery tests include the new state and still prove DEBUG gating and zero writes: `uv run python manage.py test entries.tests.test_states_view` — fca6790
- [x] 3.3 Full suite passes: `uv run python manage.py test` — fca6790
- [x] 3.4 Django checks pass: `uv run python manage.py check` — fca6790
- [x] 3.5 Migration drift check passes: `uv run python manage.py makemigrations --check --dry-run` — fca6790

#### Manual

- [x] 3.6 At 360px width, the `question_ambiguous_member` gallery state reads naturally in Polish and the answer field is usable.
- [ ] 3.7 In Chrome on Android, a parent in a family with "Hanna" captures an instruction about "Hania", sees Hanna preselected, and saves the entry assigned to Hanna.
