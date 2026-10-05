# Entry Title Keeps Only the Action Implementation Plan

## Overview

Roadmap-future slice S-20 (PRD v2 PK-20, US-11). When a parent enters "kasia zrobić pranie w piątek", classification already has separate fields for the person and the date, but nothing tells the model to keep them out of the entry text. The proposal title should be the action alone ("Zrobić pranie"), with the date set to the coming Friday and the entry assigned to Kasia. This plan tightens the classification contract sent to OpenAI and adds a small deterministic guard that removes a leading assignee name and a trailing date phrase the model may still leave in the title.

### Owner Decisions (2026-10-04)

- Example behaviour: "kasia zrobić pranie w piątek" → title "zrobić pranie", date = Friday, assigned person = Kasia.
- Slice order: S-01, S-02, **S-20**, S-03, S-04, … (S-20 lands before S-03/S-04 and therefore creates the shared `DATE_RULES` constant they reuse).
- Relative dates use Europe/Warsaw; "w przyszłym tygodniu w poniedziałek" = Monday of the next calendar week.
- No feature flag, no backfill of saved entries, no Playwright/E2E tests yet.
- A bare weekday typed on that same weekday means next week's day (the next occurrence after today), never today: "w piątek" on a Friday = reference date + 7 days. Stated explicitly in `DATE_RULES` and pinned by a test (owner-confirmed 2026-10-04, review F3).
- The school subject stays in the title ("Kartkówka z matematyki"); only the assigned person and the accepted date/time phrase are removed, because list rows do not show `school_subject` (owner-confirmed 2026-10-04, review F4).
- S-02 (`classification-short-names`) is an unconditional prerequisite: S-20 uses its `member_mention` and its pure matcher `match_mention` (review F1).
- S-07 (later) will extend the title rule so that "dla mnie" is treated as an assignee reference and removed. No action in S-20 beyond keeping the guard extensible (it takes a sequence of assignee references, not one name).

Owner decisions from the plan review were applied 2026-10-04.

### Assumed Decisions

1. **The title keeps the parent's words for the action and starts with a capital letter** ("Zrobić pranie"), matching existing titles such as "Kupić prezent dla babci" (`entries/tests/test_classification_acceptance.py:208`). Alternative: keep the parent's casing exactly ("zrobić pranie").
2. **Only extracted values are removed from the title:** the assigned person's name and the date/time phrase that filled the date/time fields. Any other person or detail stays ("Kupić prezent dla babci", "Spotkanie z Tomkiem"), and so does the school subject ("Kartkówka z matematyki", owner-confirmed 2026-10-04). A name is removed only when it matches an allowed family member (see Phase 2 §2); a leading name that matches nobody stays. A date phrase that was *not* accepted as the date (ungrounded, see `entries/classification/openai_backend.py:335`) is not removed by the guard.
3. **A bare weekday means its next occurrence after today** ("w piątek" said on a Friday = Friday of next week, never today) (owner-confirmed 2026-10-04). The full `DATE_RULES` set is S-04's Assumed Decision 1 (`context/changes/multi-entry-text-capture/plan.md:22`); the remaining items are assumed (shared with S-03/S-04). S-20 creates `DATE_RULES`; S-03 and S-04 reuse it unchanged.
4. **The rule applies to every classification path**, including automated EduVulcan conversion, because they share one prompt (`entries/classification/service.py:314`). School titles such as "Kartkówka z matematyki" keep the subject.
5. **The deterministic guard is conservative:** it strips only a leading assignee reference (the matched member's full display name or given name, or the matched `member_mention`, with an optional trailing comma or colon) and a trailing occurrence of the accepted date phrase, then re-capitalizes. It never returns an empty title; if stripping would empty it, the model's text is kept.
6. **Saved entries are not rewritten.** Only new proposals change.

## Current State Analysis

- The structured-output field `content` is described only as "Zwięzła treść wpisu po polsku, oparta wyłącznie na poleceniu" (`entries/classification/openai_backend.py:78-80`), and `INSTRUCTIONS` (`:110-131`) say nothing about leaving the person or date out of it. The model is therefore free to return "Kasia zrobić pranie w piątek" as the title.
- The adapter already checks the date: `_date_is_grounded` keeps `date` only when `date_source` occurs verbatim in the parent's text (`openai_backend.py:359-372`). `date_source` is available in `_translate` (`:314-344`) but discarded after grounding.
- `validate_output` trims `content` and requires it to be non-empty (`entries/classification/validation.py:52-54`); `member_name` must be exactly one allowed name (`:61-71`). A todo does not require a date (`:77-83`).
- `BackendOutput` carries `content`, `date`, `time`, `member_name` (`entries/classification/backends.py:40-55`); nothing downstream edits `content`.
- The test family includes a child named "Kasia" (`README.md:117`), so assignment of "kasia" works by exact name today; diminutive resolution (e.g. Kasia → Katarzyna) is S-02's job, and S-02 lands before S-20.
- Relative dates are computed by the model from `data_odniesienia` and `dzien_tygodnia` (`openai_backend.py:134-150`) with no explicit weekday rule. S-20 creates the shared `DATE_RULES` constant; S-03 and S-04 reuse it.
- Adapter-path acceptance tests script raw model output through the real adapter (`entries/tests/test_classification_acceptance.py:70-104`); an opt-in live test exists (`entries/tests/test_classification_live_wire.py:99-140`).

## Desired End State

Submitting "kasia zrobić pranie w piątek" on Sunday 2026-10-04 produces a todo proposal with title "Zrobić pranie", date 2026-10-09 and member Kasia, both when the model returns a clean title and when it echoes the name and date into the title. Existing school and general-note behaviour is unchanged; a school title keeps its subject ("Kartkówka z matematyki"). Verified by adapter-path acceptance tests, guard unit tests, the opt-in live test, and a manual check in the review form.

### Key Discoveries:

- `content` description and `INSTRUCTIONS` are the only places that define the title (`entries/classification/openai_backend.py:78-80`, `:110-131`); field descriptions are sent to OpenAI, so they must be Polish.
- `date_source` is the exact phrase to strip and is already verified against the parent's text (`openai_backend.py:359-372`).
- The general-note fallback uses the raw instruction as content (`validation.py:108-112`); this slice does not change it (a note with no recognized type keeps the parent's full text).
- Payload privacy is fixed by `build_input` (`openai_backend.py:134-150`); this slice adds no input fields.

## What We're NOT Doing

- No change to the general-note fallback (unrecognized instructions keep the full text).
- No diminutive resolution (S-02) and no free-text correction (S-03).
- No rewriting of saved entries, no migration, no feature flag.
- No grammatical rewriting of the action (no conjugation changes, no translation); the parent's words stay.
- No stripping of non-assignee names, places, the school subject, or other details.
- No "dla mnie" handling (S-07 extends the guard later).
- No Playwright/E2E tests.

## Implementation Approach

Fix the cause first: state the title rule in the prompt contract and add the shared relative-date rules. Then add a pure, conservative guard in the adapter that uses the two facts the adapter already trusts (accepted `date_source`, returned `member_name`) to remove the most common leftovers. Prove both with scripted adapter-path tests for clean and "echoing" model outputs, and confirm with the opt-in live test against the real model.

## Critical Implementation Details

- **State sequencing:** the guard must run after date grounding, and must use `date_source` only when the date was accepted; stripping a phrase whose date was dropped would lose information the follow-up question needs.
- **Cross-slice base.** S-01 and S-02 land first. The title rule and `DATE_RULES` go at the end of `INSTRUCTIONS`, after S-01's subject sentence and S-02's mention sentences. The guard edits only the `content` argument of the `BackendOutput` constructor in `_translate`, so S-01's `school_subject` and S-02's `member_mention` pass through untouched.

## Phase 1: Title Rule and Date Rules in the Prompt Contract

### Overview

Tell the model that the entry text is the action only, and make the bare-weekday rule explicit.

### Changes Required:

#### 1. Structured output and instructions

**File**: `entries/classification/openai_backend.py`

**Intent**: Describe `content` as the action in the parent's own words, without the assigned person's name and without the date or time phrase that fills `date`/`time`, starting with a capital letter; other people and details stay. Add a matching Polish sentence to `INSTRUCTIONS`, with the owner example. The title rule says explicitly that the school subject stays in the title ("Kartkówka z matematyki"). Add the module constant `DATE_RULES` with exactly these items (S-04 Assumed Decision 1): Europe/Warsaw; the week starts on Monday; a bare weekday = its next occurrence after the reference date, so the same weekday as the reference date means next week's day, never the reference date itself (explicit Polish sentence, owner-confirmed); "w przyszłym tygodniu w <dzień>" = that weekday in the next calendar week; "dziś" = the reference date; day+month without a year = the nearest such date on or after the reference date. Append it to `INSTRUCTIONS`. The correction-only rule "a relative shift counts from the proposal's current date" stays in S-03's `CORRECTION_INSTRUCTIONS`, not in `DATE_RULES`.

**Contract**: `StructuredClassification.content` description changes (schema shape unchanged). `INSTRUCTIONS` ends with the title rule and `DATE_RULES`. New public constant `DATE_RULES: str`, which S-03 and S-04 reuse unchanged (S-04's `MULTI_INSTRUCTIONS` inherits it through `INSTRUCTIONS` and must not append it again). `build_input` unchanged.

#### 2. Contract tests

**File**: `entries/tests/test_openai_backend.py`

**Intent**: Assert the title rule and `DATE_RULES` are present in `INSTRUCTIONS`, `DATE_RULES` states the same-weekday rule explicitly, the schema has exactly the post-S-01/S-02 field set (including `school_subject` and `member_mention`; S-20 adds no field), and the input payload is unchanged.

**Contract**: New tests alongside `test_instructions_forbid_reference_date_as_default` (`entries/tests/test_openai_backend.py:452`).

### Success Criteria:

#### Automated Verification:

- Adapter contract tests pass, including the new instruction and payload assertions: `uv run python manage.py test entries.tests.test_openai_backend`
- Contract tests assert that `DATE_RULES` states the same-weekday rule explicitly and that the schema field set is exactly the post-S-01/S-02 set (including `school_subject` and `member_mention`): `uv run python manage.py test entries.tests.test_openai_backend`
- Existing acceptance tests still pass unchanged: `uv run python manage.py test entries.tests.test_classification_acceptance`
- Django checks pass: `uv run python manage.py check`

#### Manual Verification:

- Reading `INSTRUCTIONS` and `DATE_RULES` confirms natural Polish wording of the title rule (with the "kasia zrobić pranie w piątek" example) and the relative-date rules

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase. Phase blocks use plain bullets — the corresponding `- [ ]` checkboxes for these items live in the `## Progress` section at the bottom of the plan.

---

## Phase 2: Deterministic Title Guard

### Overview

Remove a leading assignee name and a trailing accepted date phrase when the model still echoes them.

### Changes Required:

#### 1. Pure title helper

**File**: `entries/classification/title.py` (new)

**Intent**: A pure function that removes, case-insensitively and ignoring typographic quotes, a leading token equal to the member name (plus a following comma/colon) and a trailing occurrence of the date phrase (plus surrounding punctuation), collapses whitespace and capitalizes the first letter. If the result would be empty, it returns the input unchanged.

**Contract**: `strip_extracted_phrases(content: str, *, assignee_refs: Sequence[str], date_phrase: Optional[str]) -> str`. `assignee_refs` is a sequence of leading assignee references to try (any one may match), so S-07 can later add "dla mnie" without changing the signature. Never logs; inputs are family text.

#### 2. Adapter wiring

**File**: `entries/classification/openai_backend.py`

**Intent**: In `_translate`, after grounding, pass `date_source` (only when the date was accepted) and the assignee references to the helper and use its result as `BackendOutput.content`. Assignee references: the returned `member_name`'s full display name and its given name (first word), plus `member_mention` only when S-02's `match_mention(mention, request.allowed_member_names, display_name=str)` returns at least one name (a unique or ambiguous match both mean the person goes into a member field or the member question). An unmatched mention is never stripped. S-02 is a prerequisite, so this is unconditional.

**Contract**: `BackendOutput.content` is the guarded title; no new fields; the adapter imports S-02's pure matcher (no DB); logging unchanged (no content logged).

#### 3. Tests

**File**: `entries/tests/test_title_cleanup.py` (new), `entries/tests/test_classification_acceptance.py`

**Intent**: Table-driven unit tests for the helper, and adapter-path acceptance tests for the owner example with a clean model output and with an echoing one.

**Contract**: Unit cases: "Kasia zrobić pranie w piątek" → "Zrobić pranie"; "kasia, zrobić pranie" → "Zrobić pranie"; "Zrobić pranie w piątek" with phrase "w piątek" → "Zrobić pranie"; "Kupić prezent dla babci" unchanged; "Kartkówka z matematyki w piątek" with phrase "w piątek" → "Kartkówka z matematyki" (subject stays); "Hanna Kowalska, zrobić pranie" with refs ("Hanna Kowalska", "Hanna") → "Zrobić pranie"; "Kasia" alone unchanged; a date phrase not at the end unchanged; `date_phrase=None` leaves dates in place. Acceptance (reference date 2026-10-04, member Kasia): proposal `todo`, content "Zrobić pranie", date 2026-10-09, member Kasia, for both scripted outputs; an output whose `date_source` is ungrounded keeps the phrase in the title and asks no date for a todo; "Bartek odebrać paczkę" with `member_mention="Bartek"` in a family without Bartek keeps "Bartek odebrać paczkę" (unmatched name not stripped); "Kartkówka z matematyki dla Kasi w piątek" with `school_subject="matematyka"` keeps content "Kartkówka z matematyki".

### Success Criteria:

#### Automated Verification:

- Guard unit tests pass: `uv run python manage.py test entries.tests.test_title_cleanup`
- Owner-example acceptance tests pass for clean and echoing model outputs: `uv run python manage.py test entries.tests.test_classification_acceptance`
- Guard keeps what was not extracted: an unmatched leading name stays, and the school subject stays in "Kartkówka z matematyki": `uv run python manage.py test entries.tests.test_title_cleanup entries.tests.test_classification_acceptance`
- Classification service, follow-up and family classification tests still pass: `uv run python manage.py test entries.tests.test_classification_service entries.tests.test_follow_up_answer entries.tests.test_family_classification`
- EduVulcan conversion tests still pass: `uv run python manage.py test entries.tests.test_conversion_worker entries.tests.test_eduvulcan_acceptance`
- Full suite and checks pass: `uv run python manage.py test` and `uv run python manage.py check`

#### Manual Verification:

- Reviewing the guard's test table confirms no case removes a non-assignee name or an unaccepted date phrase

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase. Phase blocks use plain bullets — the corresponding `- [ ]` checkboxes for these items live in the `## Progress` section at the bottom of the plan.

---

## Phase 3: Live Check

### Overview

Confirm the real model follows the rule.

### Changes Required:

#### 1. Opt-in live case

**File**: `entries/tests/test_classification_live_wire.py`

**Intent**: Add opt-in cases (skipped unless `CLASSIFICATION_LIVE_EVAL=1`): "kasia zrobić pranie w piątek" with a fixed reference date, asserting a todo titled "Zrobić pranie" (case-insensitive), dated the coming Friday, assigned to Kasia; and the same-weekday rule, with reference date Friday 2026-10-09 and "kasia zrobić pranie w piątek", asserting date 2026-10-16 (reference + 7 days).

**Contract**: New test methods in `LiveWireClassificationTests`; default test runs remain offline. Every `classify_output` call passes S-01's `require_school_subject`.

### Success Criteria:

#### Automated Verification:

- Default suite still skips live tests: `uv run python manage.py test entries.tests.test_classification_live_wire`

#### Manual Verification:

- With `CLASSIFICATION_LIVE_EVAL=1` and a configured key, the live owner-example case passes
- With `CLASSIFICATION_LIVE_EVAL=1`, the live same-weekday case (reference Friday 2026-10-09, "w piątek") returns 2026-10-16
- In the running app as `test_rodzic`, entering "kasia zrobić pranie w piątek" shows the review form with title "Zrobić pranie", the coming Friday's date and Kasia selected; saving creates exactly that entry
- An instruction without a person or date (e.g. "Kupić mleko") still produces the same title as before

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase. Phase blocks use plain bullets — the corresponding `- [ ]` checkboxes for these items live in the `## Progress` section at the bottom of the plan.

---

## Testing Strategy

### Unit Tests:

- Guard helper: leading name with/without punctuation and casing, multi-word display name, trailing date phrase, typographic quotes, empty-result protection, non-assignee names and the school subject untouched.
- Prompt contract: title rule and `DATE_RULES` present (including the explicit same-weekday rule); exact post-S-01/S-02 schema field set; payload unchanged.

### Integration Tests:

- Adapter path through `classify_for_parent` for the owner example with clean and echoing model outputs.
- Follow-up merge keeps the draft's (already guarded) title.
- EduVulcan conversion regression.

### Manual Testing Steps:

1. Sign in as `test_rodzic`, enter "kasia zrobić pranie w piątek", confirm title, date and person on the review form.
2. Enter "Kupić prezent dla babci na sobotę" and confirm "dla babci" stays in the title.
3. Enter "Kartkówka z matematyki dla Kasi w piątek" and confirm the title is "Kartkówka z matematyki".
4. Run the opt-in live tests.

## Performance Considerations

None; one extra string operation per classification and slightly longer instructions.

## Migration Notes

None; saved entries are unchanged.

## References

- PRD: `context/foundation/prd-v2.md` (PK-20, US-11)
- Roadmap: `context/foundation/roadmap-future.md` (S-20)
- Shared date rules: `context/changes/multi-entry-text-capture/plan.md:22`, `context/changes/free-text-proposal-correction/plan.md:26`
- Short names (member mention, `match_mention`): `context/changes/classification-short-names/plan.md` (Phase 1 §1, Phase 2 §1)
- Adapter: `entries/classification/openai_backend.py:78-80`, `:110-131`, `:314-372`
- Validation: `entries/classification/validation.py:43-112`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Title Rule and Date Rules in the Prompt Contract

#### Automated

- [x] 1.1 Adapter contract tests pass, including the new instruction and payload assertions: `uv run python manage.py test entries.tests.test_openai_backend` — 4a34b42
- [x] 1.2 Existing acceptance tests still pass unchanged: `uv run python manage.py test entries.tests.test_classification_acceptance` — 4a34b42
- [x] 1.3 Django checks pass: `uv run python manage.py check` — 4a34b42
- [x] 1.5 Contract tests assert that `DATE_RULES` states the same-weekday rule explicitly and that the schema field set is exactly the post-S-01/S-02 set (including `school_subject` and `member_mention`): `uv run python manage.py test entries.tests.test_openai_backend` — 4a34b42

#### Manual

- [ ] 1.4 Reading `INSTRUCTIONS` and `DATE_RULES` confirms natural Polish wording of the title rule (with the "kasia zrobić pranie w piątek" example) and the relative-date rules

### Phase 2: Deterministic Title Guard

#### Automated

- [x] 2.1 Guard unit tests pass: `uv run python manage.py test entries.tests.test_title_cleanup` — f513172
- [x] 2.2 Owner-example acceptance tests pass for clean and echoing model outputs: `uv run python manage.py test entries.tests.test_classification_acceptance` — f513172
- [x] 2.3 Classification service, follow-up and family classification tests still pass: `uv run python manage.py test entries.tests.test_classification_service entries.tests.test_follow_up_answer entries.tests.test_family_classification` — f513172
- [x] 2.4 EduVulcan conversion tests still pass: `uv run python manage.py test entries.tests.test_conversion_worker entries.tests.test_eduvulcan_acceptance` — f513172
- [x] 2.5 Full suite and checks pass: `uv run python manage.py test` and `uv run python manage.py check` — f513172
- [x] 2.7 Guard keeps what was not extracted: an unmatched leading name stays, and the school subject stays in "Kartkówka z matematyki": `uv run python manage.py test entries.tests.test_title_cleanup entries.tests.test_classification_acceptance` — f513172

#### Manual

- [ ] 2.6 Reviewing the guard's test table confirms no case removes a non-assignee name or an unaccepted date phrase

### Phase 3: Live Check

#### Automated

- [x] 3.1 Default suite still skips live tests: `uv run python manage.py test entries.tests.test_classification_live_wire` — a242ecc

#### Manual

- [ ] 3.2 With `CLASSIFICATION_LIVE_EVAL=1` and a configured key, the live owner-example case passes
- [ ] 3.5 With `CLASSIFICATION_LIVE_EVAL=1`, the live same-weekday case (reference Friday 2026-10-09, "w piątek") returns 2026-10-16
- [ ] 3.3 In the running app as `test_rodzic`, entering "kasia zrobić pranie w piątek" shows the review form with title "Zrobić pranie", the coming Friday's date and Kasia selected; saving creates exactly that entry
- [ ] 3.4 An instruction without a person or date (e.g. "Kupić mleko") still produces the same title as before
