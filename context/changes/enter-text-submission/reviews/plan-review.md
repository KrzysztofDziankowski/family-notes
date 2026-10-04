<!-- PLAN-REVIEW-REPORT -->
# Plan Review: Enter Text Submission Implementation Plan

- **Plan**: context/changes/enter-text-submission/plan.md
- **Mode**: Deep
- **Date**: 2026-10-04
- **Verdict**: SOUND (after triage; was REVISE)
- **Triage**: applied 2026-10-04
- **Findings**: 0 critical, 3 warnings, 1 observation

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| End-State Alignment | WARNING |
| Lean Execution | PASS |
| Architectural Fitness | PASS |
| Blind Spots | WARNING |
| Plan Completeness | PASS |

## Grounding
Grounding: 6/6 paths ✓ (`entries/forms.py`, `_capture_form.html`, `_follow_up_form.html`, `capture.html`, `states.html`, `base.html`), 5/5 symbols ✓ (`CaptureForm.text` forms.py:32-38, `FollowUpAnswerForm.answer` forms.py:294-300, `action == 'skip'` views.py:151, `extra_body` base.html:35, `test_entry_forms`/`test_states_view` modules exist), brief↔plan ✓ except the stale "blocked" status (F4). Progress↔Phase ✓ (2 phases, 16 steps, no checkboxes in phase bodies).

## Findings

### F1 — Per-form "submitted" flag sticks when the submit is cancelled (S-06 offline block)

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Blind Spots
- **Location**: Phase 1 §2 (Enter-submit script contract); Critical Implementation Details — Timing & lifecycle
- **Detail**: The script remembers "this page already submitted the form" when it calls `form.requestSubmit()`, and only `pageshow` clears it. `requestSubmit()` does not always produce a submission: S-06 (lands right after this slice) calls `preventDefault()` in its `submit` handler when `navigator.onLine === false` and keeps the typed text so the parent can retry (`mobile-classification-progress/plan.md` Phase 1 §3). Constraint validation can also block it. In both cases the flag is set anyway, so every later Enter is swallowed (`preventDefault()` + early return) until a page reload. After going back online the parent presses Enter and nothing happens. The S-06 retry button bypasses this script, which hides the bug in S-06's manual checks.
- **Fix**: Record the flag only for submissions that really go out: add a `submit` listener on `window` (bubble phase, so it runs after S-06's `document` listener) that sets the per-form flag only when `!event.defaultPrevented`. Keep the `aria-busy` check and the `event.repeat` guard. Add a manual step "offline Enter → blocked; back online → Enter submits" to the S-06 manual check 1.9 or to this plan's matrix.
  - Strength: Keeps the double-post guard S-05 needs before S-06 ships, and composes with any later `submit` handler in either landing order.
  - Tradeoff: Relies on listener order (`document` before `window`), which is standard DOM bubbling but should be commented in the script.
  - Confidence: HIGH — S-06's offline branch explicitly cancels the submit while keeping the page alive.
  - Blind spot: Behaviour of `requestSubmit()` validation bubbles on Android not checked.
- **Owner input**: no
- **Decision**: FIXED (Fix A)

### F2 — S-03 "Popraw opis" correction box (lands before S-05) is not addressed

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: End-State Alignment
- **Location**: Assumed Decision 1 (forms in scope); Current State Analysis; Phase 1 §1 and test 1.1
- **Detail**: The confirmed order is S-01, S-02, S-20, S-03, S-04, S-05. S-03 (`free-text-proposal-correction/plan.md:176,197`) adds a third natural-language textarea, `correction` („Popraw opis”), to the review form, with a secondary submit „Popraw” using `formaction="{% url 'entries:correct' %}"`. „Zapisz wpis” stays the default submit. S-04 adds per-proposal corrections in the batch review. This plan's Current State Analysis describes the pre-S-03 code and decides only "capture + follow-up". That leaves two problems. (a) It is the same "type an instruction → submit" interaction US-07 describes, but Enter will insert a newline there, so the app is inconsistent. (b) If someone later opts that box in with the current contract, `requestSubmit()` with no submitter ignores `formaction` and posts to `entries:confirm`, so Enter would **save the entry**. Test 1.1 lists only `content` textareas as "must not be marked", so neither outcome is pinned.
- **Fix A ⭐ Recommended**: Opt the correction box in, with an explicit submitter: the widget gets `data-enter-submit="<submitter marker>"`, and the script calls `form.requestSubmit(button)` with the marked „Popraw” button (so `formaction` and `formnovalidate` apply). Add tests proving the correction box is marked and its submitter is „Popraw”, and that the review `content` box stays unmarked.
  - Strength: One rule for every instruction box; `requestSubmit(submitter)` is the standard way to keep `formaction`.
  - Tradeoff: Script contract grows a submitter lookup; S-04 batch markup must give each proposal its own submitter.
  - Confidence: MEDIUM — depends on S-03/S-04 final markup.
  - Blind spot: S-04 batch form structure (one form, many correction boxes) not verified.
- **Fix B**: Explicitly exclude the correction box (Enter = newline), list it in "What We're NOT Doing", and add it to test 1.1's "not marked" set.
  - Strength: Smallest change; no risk of saving by Enter.
  - Tradeoff: Inconsistent Enter behaviour between the capture box and the correction box on the same flow.
  - Confidence: HIGH — no script change.
  - Blind spot: None significant.
- **Owner input**: yes
- **Decision**: FIXED (owner: Fix A — correction box opts in; Enter calls requestSubmit(<Popraw>); test pins no post to entries:confirm)

### F3 — Hint is rendered without JavaScript, contradicting "no-JS unchanged"

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Blind Spots
- **Location**: Phase 1 §3 (hint markup); Desired End State; manual check 1.9
- **Detail**: The hint „Enter wysyła, Shift+Enter dodaje nową linię.” is server-rendered in both partials unconditionally. Without JavaScript (or if the deferred script fails to load), Enter inserts a newline, which manual check 1.9 explicitly expects. The page then gives a false instruction, and the "Without JavaScript nothing changes" end state does not hold. The hint also has no `id`, so S-17's field-association helper cannot add it to the textarea's description. Screen-reader users who move by form fields then never hear that Enter submits, which matters for predictability (WCAG 3.2.2/3.3.2, owner-confirmed AA target in S-17).
- **Fix**: Render the hint with the `hidden` attribute and a stable `id="{{ field.auto_id }}-enter-hint"`, and have `enter-submit.js` remove `hidden` from `[data-enter-hint]` on load. Keep the Polish copy in the template. Do not put `aria-describedby` in widget attrs (it would suppress Django's automatic `_error` reference); S-17's helper composes it. Update test 1.2 to assert the hidden hint and its id.
- **Owner input**: no
- **Decision**: FIXED (Fix A)

### F4 — Stale status and order text in plan and brief

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: plan-brief.md "Open Risks & Assumptions"; plan.md "Owner Decisions" and "Assumed Decisions"
- **Detail**: The brief still says the plan "is blocked on owner confirmation… roadmap status stays `blocked`", while `roadmap-future.md:284` shows `planned` with owner decisions applied. The owner-confirmed order in the plan omits S-20 (`roadmap-future.md:43`: S-01, S-02, S-20, S-03, …). Assumed Decisions 4, 8 and 9 are now owner-confirmed (phone Enter, no E2E, no flags) but are still labelled "pending owner confirmation". Line references used by S-06/S-17 to this plan (`plan.md:41,58,84`) point at unrelated lines.
- **Fix**: Remove the "blocked" sentences from the brief, add S-20 to the order, mark Decisions 4, 8 and 9 as owner-confirmed, and refer to sections by name instead of line numbers.
- **Owner input**: no
- **Decision**: FIXED (Fix A)
