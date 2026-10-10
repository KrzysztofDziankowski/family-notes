<!-- PLAN-REVIEW-REPORT -->
# Plan Review: Entry Title Keeps Only the Action Implementation Plan

- **Plan**: context/changes/title-keeps-action-only/plan.md
- **Mode**: Deep
- **Date**: 2026-10-04
- **Verdict**: SOUND (after fixes)
- **Triage**: applied 2026-10-04
- **Findings**: 0 critical, 1 warning, 4 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| End-State Alignment | WARNING |
| Lean Execution | PASS |
| Architectural Fitness | WARNING |
| Blind Spots | WARNING |
| Plan Completeness | WARNING |

## Grounding
Grounding: 6/6 paths ✓ (`title.py` and `test_title_cleanup.py` are new), 6/6 symbols ✓ (`_translate`, `_date_is_grounded` at `openai_backend.py:359-372`, `StructuredClassification.content` at `:78-80`, `test_instructions_forbid_reference_date_as_default` at `test_openai_backend.py:452`, `LiveWireClassificationTests`, `_general_note` at `validation.py:108-112`), brief↔plan ✓. Line references are within ±4 lines. The existing acceptance fixtures have no leading member name or trailing date phrase in `content`, so the guard leaves them unchanged. 2026-10-04 is a Sunday, so the coming Friday is 2026-10-09 ✓. Progress↔Phase consistency ✓ (3 phases, 14 rows).

Cross-plan composition (S-01 → S-02 → S-20): the title rule and `DATE_RULES` go at the end of `INSTRUCTIONS`, after the S-01 subject sentence and the S-02 mention sentences. The `content` description change is independent of the new `school_subject`/`member_mention` fields. The guard edits only the `content` argument of the `BackendOutput` constructor in `_translate`. The composition is clean apart from F1 and F2.

## Findings

### F1 — Stripping `member_mention` unconditionally removes names that were never extracted

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: End-State Alignment
- **Location**: Phase 2 §2 (adapter wiring: "When S-02 has landed, also pass `member_mention`")
- **Detail**: S-02 fills `member_mention` whenever the parent names a person, including when the name matches no active family member. In that case it is not stored in any field: the mention resolves to zero candidates and `member_name` may be null. Stripping it anyway breaks this plan's own Decision 2 and the roadmap risk ("never drop meaning that was not extracted into another field"). For example, "Bartek odebrać paczkę" in a family without Bartek would become "Odebrać paczkę", unassigned. The wording is also conditional ("when S-02 has landed"), although the confirmed order guarantees S-02 lands first. Multi-word display names ("Hanna Kowalska") are not covered by the "leading token equal to the member name" rule either.
- **Fix A ⭐ Recommended**: In `_translate`, strip `member_mention` only when S-02's `match_mention(mention, request.allowed_member_names, display_name=str)` returns at least one name. A unique or ambiguous match both mean the person goes into a member field or the member question. Strip `member_name` by its full display name or its given name (first word), as in S-02. Make the S-02 dependency unconditional and add a guard test for an unmatched leading name.
  - Strength: Stays in the adapter, where `date_source` is available, and uses data the adapter already has (`request.allowed_member_names`).
  - Tradeoff: The adapter imports the S-02 matcher (pure, no DB).
  - Confidence: HIGH — S-02's matcher is a pure function over names.
  - Blind spot: Inflected leading names ("Kasi trzeba…") are still not stripped, which is conservative and acceptable.
- **Fix B**: Move the guard into the service after `_apply_member_mention`, carrying the accepted date phrase on `BackendOutput` as a transient `repr=False` field.
  - Strength: Strips exactly when the member was resolved against real candidates.
  - Tradeoff: Adds a field to the provider-neutral seam and a step to each parent path, and `classify_for_family` would need its own call.
  - Confidence: MED — more moving parts across S-03/S-04 call sites.
  - Blind spot: S-04's batch path would also need it per entry.
- **Owner input**: no
- **Decision**: FIXED (Fix A)

### F2 — `DATE_RULES` matches S-04; S-03/S-04 plans still assume they create it

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Architectural Fitness
- **Location**: Phase 1 §1 (`DATE_RULES`); cross-plan with `free-text-proposal-correction` and `multi-entry-text-capture`
- **Detail**: S-20's rule list matches S-04 Assumed Decision 1 exactly: Europe/Warsaw, Monday week start, bare weekday = next occurrence after the reference date, "w przyszłym tygodniu w <dzień>" = next calendar week, "dziś" = reference date, and day+month without a year = nearest on/after. S-03 Decision 6 omits "dziś" but adds "a relative shift counts from the proposal's current date". That rule only makes sense in `CORRECTION_INSTRUCTIONS`, which S-03 already states separately (`free-text-proposal-correction/plan.md:103`), so the shared constant is compatible. Three drifts remain:
  - (a) S-03 (`plan.md:103`) and S-04 (`plan.md:102`) still say they create `DATE_RULES` "if the other has not".
  - (b) S-04 says `DATE_RULES` "is appended to both `INSTRUCTIONS` and `MULTI_INSTRUCTIONS`". `MULTI_INSTRUCTIONS` is built from `INSTRUCTIONS`, which after S-20 already ends with `DATE_RULES`, so appending again duplicates it.
  - (c) S-20 Decision 3 calls the bare-weekday rule "confirmed", but in S-03/S-04 it is still an assumed decision. The owner confirmed only Europe/Warsaw and "w przyszłym tygodniu w poniedziałek".
- **Fix**: In S-20, list the exact `DATE_RULES` items (the S-04 Decision 1 set) and state that the relative-shift rule stays in S-03's `CORRECTION_INSTRUCTIONS`. Change "confirmed" to "assumed (shared with S-03/S-04)". When those plans are revised, have S-03/S-04 reuse S-20's `DATE_RULES`, and have S-04 not re-append it (`MULTI_INSTRUCTIONS` inherits it from `INSTRUCTIONS`).
- **Owner input**: no
- **Decision**: FIXED (Fix A)

### F3 — Bare weekday said on the same weekday is a product decision

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Blind Spots
- **Location**: Assumed Decision 3; `DATE_RULES`
- **Detail**: "w piątek" typed on a Friday becomes next week's Friday. Users see this rule, and it applies to every capture once S-20 puts it in the shared prompt (and later to S-03/S-04). The owner has not explicitly confirmed it. Today's `INSTRUCTIONS` leave it to the model.
- **Fix**: Ask the owner once for all three slices. Recommended: next occurrence (next week); alternative: today.
- **Owner input**: yes
- **Decision**: FIXED (owner: bare weekday on the same weekday = next week's, never today; explicit in DATE_RULES + test with Friday reference → +7 days)

### F4 — After S-01, should the school subject also leave the title?

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Blind Spots
- **Location**: Assumed Decision 2 and 4 ("School titles such as 'Kartkówka z matematyki' are unaffected")
- **Detail**: This slice's principle is "remove values extracted into their own fields". S-01, which lands first, makes the school subject such a field, but S-20 keeps it in the title ("Kartkówka z matematyki" alongside "Przedmiot: matematyka"). That choice is consistent and the safer one, but it is unstated with respect to S-01. Lists show only the title (S-01 leaves list rows unchanged), so removing the subject would hide it from lists.
- **Fix**: State explicitly that the subject stays in the title, because list rows do not show `school_subject`. Recommended: keep it; alternative: strip it like person/date.
- **Owner input**: yes
- **Decision**: FIXED (owner: keep the school subject in the title; only assignee and accepted date/time phrase removed; test added)

### F5 — Phase 1 schema test must use the post-S-01/S-02 field set

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 1 §2 ("the schema still has the same field set")
- **Detail**: By the time S-20 lands, `StructuredClassification` also has `school_subject` (S-01) and `member_mention` (S-02). A hard-coded field list copied from today's code would fail, and loosening it would hide drift.
- **Fix**: Assert the exact field set including `school_subject` and `member_mention`, and note that S-20 adds no field.
- **Owner input**: no
- **Decision**: FIXED (Fix A)
