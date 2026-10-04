<!-- PLAN-REVIEW-REPORT -->
# Plan Review: Classification Short Names Implementation Plan

- **Plan**: context/changes/classification-short-names/plan.md
- **Mode**: Deep
- **Date**: 2026-10-04
- **Verdict**: SOUND (after fixes; was REVISE)
- **Triage**: applied 2026-10-04
- **Findings**: 1 critical, 2 warnings, 1 observation

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| End-State Alignment | FAIL |
| Lean Execution | PASS |
| Architectural Fitness | WARNING |
| Blind Spots | WARNING |
| Plan Completeness | WARNING |

## Grounding
Grounding: 8/8 paths ✓ (`names.py` and `test_short_names.py` are new), 6/6 symbols ✓ (`_active_family_members`, `_resolve_member`, `_merge_answer`, `_MEMBER_FIELDS`, `MissingField.AMBIGUOUS_MEMBER`, `follow_up_question` de-duplicates AMBIGUOUS/AFFECTED), 2 stale line references ✗ (`validation.py:449-459` and `:424-459` — the file has 112 lines; the allow-list check is at `validation.py:61-71`), brief↔plan ✓. Progress↔Phase consistency ✓ (3 phases, 17 rows).

Cross-plan composition (S-01 → S-02 → S-20): S-02 lands after S-01. S-01's `school_subject` field, `require_school_subject` keyword and `_merge_answer` change are already in place when S-02 starts. S-20 consumes S-02's `member_mention` (see S-20 review F1).

## Findings

### F1 — Follow-up answer can be re-asked forever: the original mention overrides the answer

- **Severity**: ❌ CRITICAL
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: End-State Alignment
- **Location**: Phase 2 §1 (`member_mention` description), §3 (`classify_follow_up_answer`), Critical Implementation Details ("Precedence")
- **Detail**: The follow-up request sends the original instruction and the answer (`entries/classification/service.py:166-173`, `build_input`). `member_mention` is described as "the person exactly as the parent used it", without saying which text it comes from. In the Hanna+Anna case the instruction says "Hania" and the parent answers "Hanna". The model may still return `member_mention="Hania"` (from `polecenie`) with `member_name="Hanna"`. Under the plan's precedence rule the mention wins, resolves to {Hanna, Anna} and sets `member_ambiguous`, so the parent is asked "Której osoby dotyczy…?" again. No answer can get past this. Manual step 3 ("Answer 'Hanna' and confirm that the review shows Hanna") depends on model behaviour the plan never constrains, and the scripted tests would script the convenient mention, so they would pass anyway.
- **Fix A ⭐ Recommended**: In `classify_follow_up_answer`, when the draft is missing a member, first run `match_mention(answer.strip(), candidates)`. A unique match decides the member. Only otherwise use the model's `member_mention`. Also add a Polish sentence saying that, with `odpowiedz_rodzica`, `member_mention` is the person named in the answer. Add a scripted test in which the model returns the instruction's "Hania" while the answer is "Hanna", and assert that the proposal has Hanna.
  - Strength: Deterministic for the common one-word answer, and model variance can no longer trap the parent.
  - Tradeoff: One extra matcher call, and the answer text reaches `match_mention` (pure, never logged).
  - Confidence: HIGH — answers to a member question are usually just a name.
  - Blind spot: Long answers ("ta starsza, Hanna") fall back to the model's mention.
- **Fix B**: In the follow-up path, ignore `member_mention` entirely and keep today's exact allow-list check on the model's `member_name`.
  - Strength: Smallest change, and no loop is possible.
  - Tradeoff: Answering with a short name ("Hania" → Hanna in a family with only Hanna) stops working, which drops part of the Desired End State.
  - Confidence: HIGH.
  - Blind spot: None significant.
- **Owner input**: no
- **Decision**: FIXED (Fix A)

### F2 — Group matching lets an exact name lose, and stored diminutives cross-match

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Architectural Fitness
- **Location**: Phase 1 §1 (`match_mention` contract)
- **Detail**: `match_mention` returns every candidate that matches exactly or by group intersection, with equal weight. Display names are often stored as diminutives: the test family has "Kasia" and "Tymek" (`README.md:115-117`). Because the plan's dictionary puts "hania" under both Hanna and Anna, a stored display name "Hania" has the group {hania, hanna, anna}. That group causes two problems:
  - A family with display names "Hania" and "Ania" turns mention "Ania" into an AMBIGUOUS question, even though one member is literally named "Ania".
  - A family with only "Hania" silently preselects her for mention "Ania".
  The plan's own test list includes the stored-diminutive case ("Kasia" matched by "Katarzyna") but not these collisions.
- **Fix**: Make matching two-tier. An exact match (casefolded full display name or given name) is decisive when it hits exactly one candidate. Group matching runs only when no candidate matches exactly. Add the two collision cases above to `test_short_names`.
  - Strength: Names the parent typed exactly never become questions, and the behaviour stays deterministic and auditable.
  - Tradeoff: A parent who means Hanna but types the exact display name of another member gets that member (as today).
  - Confidence: HIGH — the same precedence S-20's guard and the existing allow-list rely on.
  - Blind spot: Families with duplicate display names stay ambiguous (existing behaviour).
- **Owner input**: no
- **Decision**: FIXED (Fix A)

### F3 — New shared INSTRUCTIONS sentence leaks into automated EduVulcan classification

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Blind Spots
- **Location**: Phase 2 §1 (`INSTRUCTIONS`: "If several people on the list fit, return member_name as null")
- **Detail**: `INSTRUCTIONS` is shared by `classify_for_family` (`entries/classification/service.py:349-366`). On that path a null `member_name` on a school event becomes a follow-up, and the follow-up becomes a general note (`:369-371`). The plan therefore changes EduVulcan outcomes while claiming "automated intake behaves exactly as before". The sentence is also redundant: the local resolver decides ambiguity from `member_mention`, whatever `member_name` the model returns (Critical Implementation Details, "Precedence").
- **Fix**: Drop the "return null when several fit" clause. Keep only "fill `member_mention`" and "use the allowed name for a diminutive". Add a `classify_for_family` regression test with a school event naming a child.
- **Owner input**: no
- **Decision**: FIXED (Fix A)

### F4 — Composition with S-01 and small contract gaps

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 2 §2–§3; Owner Decisions; Critical Implementation Details ("Cross-slice overlap")
- **Detail**: S-01 lands first and adds defaulted fields to `BackendOutput` (`school_subject`). It also adds a required `require_school_subject` keyword to `validate_output`/`classify_output` and changes `_merge_answer`. This plan has these gaps:
  - (a) `_apply_member_mention` is not specified to use `dataclasses.replace`. A field-by-field rebuild, as `_merge_answer` does, would silently drop `school_subject`, because the defaults hide the omission.
  - (b) The "whichever lands second rebases" wording and the order list omit S-20 and the fixed order.
  - (c) "AMBIGUOUS_MEMBER whatever the entry type" contradicts the early general-note return at `validation.py:49-50`.
  - (d) For school kinds, AFFECTED_MEMBER is appended too (`validation.py:82`). That is harmless, because `follow_up_question` de-duplicates it, but tests should expect both.
  - (e) The validation line references are stale.
- **Fix**: State that S-02 builds on S-01. Require `dataclasses.replace` in `_apply_member_mention`, plus a test that `school_subject` survives resolution and answer merge. Say that ambiguity is ignored when `entry_type` is null (general note). Fix the line references and the order list (S-01, S-02, S-20, S-03, …).
- **Owner input**: no
- **Decision**: FIXED (Fix A)
