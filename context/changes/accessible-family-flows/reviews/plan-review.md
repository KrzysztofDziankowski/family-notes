<!-- PLAN-REVIEW-REPORT -->
# Plan Review: Accessible Family Flows Implementation Plan

- **Plan**: context/changes/accessible-family-flows/plan.md
- **Mode**: Deep
- **Date**: 2026-10-04
- **Verdict**: SOUND (after triage; was REVISE)
- **Triage**: applied 2026-10-04
- **Findings**: 0 critical, 3 warnings, 2 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| End-State Alignment | WARNING |
| Lean Execution | PASS |
| Architectural Fitness | WARNING |
| Blind Spots | WARNING |
| Plan Completeness | PASS |

## Grounding
Grounding: 9/9 paths ✓ (`_field.html`, `_review_form.html`, `_manage_form.html`, `_entry_row.html`, `base.html`, `500.html`, `404.html`, `test_manage_states.py`, `test_child_states_view.py`), 5/5 symbols ✓ (`id="{{ field.auto_id }}-error"` _field.html:5, `_mark_invalid_fields` views.py:443 with callers :154/:527/:563/:669, `-hint` describedby forms.py:129-133, `id_content-error` assertion test_manage_views.py:323, test-plan "e2e/visual: none planned" test-plan.md:87-88), brief↔plan ✗ for S-05/S-06 coverage (F1). Progress↔Phase ✓ (4 phases, 25 steps).

## Findings

### F1 — Promised S-05/S-06 coverage is missing from the plan body

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: End-State Alignment
- **Location**: Assumed Decision 2 (covered flows); Phase 3 §2 (audit cases); Phase 4 (AT matrix); plan-brief.md "Prerequisites"
- **Detail**: The brief says "S-05/S-06 progress and Enter markup must gain audit cases", and the confirmed order lands S-05, S-06, S-03 and S-04 before S-17. The plan body adds none of it:
  - (a) S-06's `/offline/` page is a family-reachable page that extends `base.html`, but it is not in the covered flows, the `family_notes/test_accessibility.py` cases or the axe list (4.1).
  - (b) No audit case renders the five S-06 progress states (the partial supports a `progress_state` parameter), so the live-region and retry-button markup is never audited.
  - (c) S-06's manifest is not checked for SC 1.3.4 (it currently locks `orientation: portrait`; see S-06 review F1).
  - (d) The AT matrix (4.2–4.4) never exercises Enter-to-submit (NVDA focus mode, TalkBack send key), the progress announcements or the offline page.
  - (e) The S-03 correction box and S-04 batch review states are not in the capture state list either.

  The AA claim in the Desired End State would therefore not cover the behaviour that M-2 adds to the same flows.
- **Fix**: Extend Assumed Decision 2 and the Phase 3 §2 case lists with: `/offline/` (anonymous and authenticated), capture/follow-up with each `progress_state` rendered, the correction and batch review states, and a manifest assertion (no orientation lock). Add matrix rows for Enter submit, the progress running/slow announcements and the offline page to Phase 4 (4.1–4.4) and `a11y-verification.md`.
  - Strength: Makes the brief's promise real; uses the existing audit helper with no new tooling.
  - Tradeoff: About 10 more audit cases, and the AT session gets longer.
  - Confidence: HIGH — every page and partial named here is planned in S-03/S-04/S-06.
  - Blind spot: Final S-03/S-04 state names are not yet fixed.
- **Owner input**: no
- **Decision**: FIXED (Fix A)

### F2 — Audit rule "role=status only on elements with text" conflicts with a script-updated live region

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Architectural Fitness
- **Location**: Phase 3 §1 (`audit_page` rules)
- **Detail**: The rule fits the static panels (`_notice.html`, `_saved_panel.html`). S-06, however, uses a `role="status"` region whose text lives in `hidden` child blocks, and the reliable pattern is a region that is present and *empty or all-hidden* before the script reveals a state (S-06 review F2). The plan does not say whether text inside `hidden` descendants counts. If it counts, the audit can never catch an empty static panel behind a `hidden` child. If it does not count, every capture page fails the audit once S-06 is in. Either way the implementer guesses, and S-14–S-16 inherit the guess.
- **Fix**: Define the rule precisely. A `role=status`/`role=alert` element must contain visible (not `hidden`) text, **unless** it carries `aria-live` and a `data-live-region` marker (a script-updated region), in which case it must contain at least one `hidden` state block with text. Add one passing and one failing snippet for each branch to the helper's unit tests, and write the marker into `accessibility.md`'s S-06 contract.
  - Strength: Supports the reliable live-region pattern and still flags empty static panels.
  - Tradeoff: A project-specific marker that S-06 must adopt.
  - Confidence: MEDIUM — depends on S-06 accepting its F2 fix.
  - Blind spot: S-06 may land before this rule is written, so its markup needs a follow-up edit.
- **Owner input**: no
- **Decision**: FIXED (Fix A)

### F3 — Ordering contradictions: contract written after its consumer ships; fixes limited to templates/tokens

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Blind Spots
- **Location**: What We're NOT Doing (first bullet); Assumed Decisions 5 and 7; Phase 4 §1 ("templates or tokens only"); Key Discoveries last bullet
- **Detail**: The plan says S-06 "must meet the contract in `accessibility.md`", but `accessibility.md` is written in this slice's Phase 3, after S-06 has shipped, and S-06's plan never references it. The sentence describes a pre-S-05 world: Key Discoveries says S-05/S-06 only "plan" the first scripts. Phase 4 allows fixes only in "templates or tokens". So any AA failure the AT pass finds in `enter-submit.js` or `classification-progress.js` (focus, announcement, readOnly state) can only become a follow-up, which undermines the "WCAG 2.2 AA confirmed" end state for the capture flow. Decision 7 also says "the product has no animations", which is no longer true after S-06's Pico `aria-busy` spinner (Pico honours `prefers-reduced-motion`, and a loading spinner falls under SC 2.2.2's essential exception, so this is a wording fix).
- **Fix**: Restate Decision 5 and the NOT-doing bullet as "S-05/S-06 have shipped; this slice verifies their markup and scripts against the contract and may fix them in place, without adding new behaviour". Allow small script fixes in Phase 4. Update Decision 7 to mention the spinner and reduced-motion handling.
- **Owner input**: no
- **Decision**: FIXED (Fix A)

### F4 — Field-association helper should include the S-05 Enter hint

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Blind Spots
- **Location**: Phase 1 §2 (shared helper composing `aria-describedby`)
- **Detail**: S-05 adds the hint „Enter wysyła, Shift+Enter dodaje nową linię.” under the capture and follow-up textareas, but it is not associated with the field. Enter changing from newline to submit is exactly what a screen-reader user needs to hear on the field (SC 3.3.2). The helper is planned to run only "on every re-rendered invalid form". If the hint ID is added only there, valid initial renders get no description. If it is added through widget attrs, Django stops emitting its automatic `_error` reference.
- **Fix**: Have the helper also run on the initial capture and follow-up renders and include `<auto_id>-enter-hint` when the S-05 hint is rendered (S-05 review F3 gives the hint that ID). Add the case to the Phase 1 composition tests.
- **Owner input**: no
- **Decision**: FIXED (Fix A)

### F5 — Stale text: owner-confirmed items still "assumed", order omits S-20, dead line refs

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Overview, Assumed Decisions 1/3/8, Key Discoveries, References; plan-brief.md "Open Risks"
- **Detail**: The Overview still says "written without an owner interview, so the decisions below are assumptions", although Decision 1 (WCAG 2.2 AA) and the parts of Decisions 3 and 8 about no E2E and no flags are owner-confirmed. The confirmed order omits S-20 (`roadmap-future.md:43`). References to `enter-text-submission/plan.md:41,58` point at unrelated lines ("Desired End State" and a NOT-doing bullet).
- **Fix**: Mark the confirmed decisions as owner-confirmed, add S-20 to the order, and cite S-05 and S-06 by section name.
- **Owner input**: no
- **Decision**: FIXED (Fix A)
