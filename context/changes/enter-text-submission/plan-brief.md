# Enter Text Submission — Plan Brief

> Full plan: `context/changes/enter-text-submission/plan.md`

## What & Why

Parents want to submit a typed instruction by pressing Enter instead of reaching for the "Rozpoznaj" button (PK-07, US-07). This plan makes Enter submit the natural-language text boxes: capture, follow-up answer and S-03's „Popraw opis” correction box. It keeps a newline shortcut and protects keyboard composition (IME, Android predictive text, Polish diacritics).

## Starting Point

Both the capture instruction and the follow-up answer are plain `<textarea>` fields in no-JS Django forms (`entries/forms.py:32-38`, `entries/forms.py:294-300`), so Enter inserts a newline. S-03 (lands first) adds an optional `correction` textarea and a „Popraw” submit with `formaction` → `entries:correct` to the review form, where „Zapisz wpis” stays the default action. The project has no JavaScript at all yet. `base.html` already has an empty `extra_body` block for page scripts.

## Desired End State

On the capture page and the follow-up question, Enter submits ("Rozpoznaj" / "Dalej"); in „Popraw opis” it runs „Popraw” and can never save. Shift+Enter adds a newline, composition never submits, empty input is ignored, and the Android keyboard shows a send key. Without JavaScript nothing changes (the hint stays hidden). Review and create/edit forms keep Enter = newline in "Tytuł".

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
| --- | --- | --- | --- |
| Which forms | Capture text, follow-up answer and the S-03 correction box (plus S-04 per-proposal boxes if present) | Those are the "type text, submit" interactions; "Tytuł" boxes stay newline because Enter there would save an entry. | Owner |
| Correction box submitter | Enter calls `form.requestSubmit(document.getElementById(<id>))` via S-03/S-04's `data-enter-submitter="<button id>"` on the textarea (single: `correct-submit`/`{prefix}-correct-submit`; batch: `e{i}-correct-submit`); no fallback to the default action | The default action of the review form is „Zapisz wpis” (`entries:confirm`); a test pins that Enter can never post there. | Owner |
| Key map | Enter submits; Shift+Enter newline; modifiers = browser default | Common chat convention with a newline escape. | Assumed (owner to confirm) |
| Composition | Ignore `isComposing` and `keyCode 229` | Prevents submitting mid-word on IME/Gboard/diacritics. | Assumed (owner to confirm) |
| Phone keyboard | Enter/send submits too (`enterkeyhint="send"`) | Short one-line instructions; one rule for all devices. | Owner |
| Empty input | Enter does nothing | Avoids empty classification requests and a non-Polish browser bubble. | Assumed (owner to confirm) |
| Follow-up Enter | Default action = "Dalej", never "Pomiń" | `requestSubmit()` sends no `action`, which the view treats as an answer (`entries/views.py:151`). | Research |
| Hint copy | "Enter wysyła, Shift+Enter dodaje nową linię.", rendered `hidden` with `id="<auto_id>-enter-hint"` and revealed by the script | Discoverability without a false hint when JS is off; S-17 links the ID to the field. | Assumed (owner to confirm) |
| Mechanism | One opt-in deferred static script, data attribute on widgets | Progressive enhancement; no build tooling. | Research |
| Testing | Markup/static tests + manual browser matrix; no Playwright | Owner decision; test plan has "e2e: none planned" (`context/foundation/test-plan.md:87`). | Owner |
| Release | No feature flag, no backfill | Owner decision; rollback is removing the script include. | Owner |
| Coexistence with S-06 | Skip Enter while form is `aria-busy="true"`; record "submitted" only for submits not cancelled (`window` listener, `!defaultPrevented`) | Both scripts compose in either landing order; an offline-cancelled submit does not lock Enter. | Research |

## Scope

**In scope:**
- `data-enter-submit` + `enterkeyhint="send"` on the capture, follow-up and correction widgets; the correction box's submitter comes from S-03's `data-enter-submitter` id
- `family_notes/static/js/enter-submit.js`, included on the capture page and the DEBUG state gallery
- Polish hint line (hidden until the script runs) under each opted-in box
- Tests for markup, script include, static resolution, answer-vs-skip server contract, and that Enter in the correction box can never post to `entries:confirm`

**Out of scope:**
- "Tytuł" on review/create/edit, other forms, custom shortcuts, JS tooling/Playwright, progress UI (S-06), any server-side change

## Architecture / Approach

Widget attrs mark the fields; S-03's `data-enter-submitter` id names the submit button to use. A single delegated `keydown` listener checks key, modifiers, composition, repeat, empty value, the named submitter and the busy/submitted state. If all pass, it calls `form.requestSubmit()` (or `requestSubmit(document.getElementById(<data-enter-submitter>))`), which fires the normal `submit` event (S-06 hooks there). A `window` `submit` listener records the submitted flag only for submissions not cancelled, and a `pageshow` listener resets it after Back navigation.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Enter-to-Submit Behavior | Opt-in markers (incl. correction box), script, include, hint, markup and submitter tests | Android IME edge cases submitting mid-composition; Enter in the review form saving instead of correcting |
| 2. Regression and Release Verification | Answer-vs-skip contract test, full suite, collectstatic check, production smoke | Static `js/` directory missing in a release |

**Prerequisites:** None in the roadmap; in the confirmed order (S-01, S-02, S-20, S-03, S-04, S-05, S-06, …) S-03's correction box already exists. Coordination with S-06 through the `aria-busy` contract.
**Estimated effort:** ~1 session across 2 phases.

## Open Risks & Assumptions

- Owner review 2026-10-04 confirmed the decisions listed under "Owner Decisions (2026-10-04)" in plan.md; remaining assumed rows stand unless the owner objects.
- Owner decisions from plan review were applied 2026-10-04 (correction box opts in with an explicit „Popraw” submitter). Remaining "Assumed" rows stand in for PRD-v2 Open Question 8 and stand unless the owner objects.
- On phones a newline can only be pasted. If the owner wants newlines on mobile, the key map changes to "submit only from a hardware keyboard".
- If S-03/S-04 markup changes before this slice lands, the submitter markers must follow it; the "never posts to `entries:confirm`" test guards the review form.
- JS key handling has no automated browser test; regressions rely on the manual matrix until an E2E stack exists.

## Success Criteria (Summary)

- A parent submits an instruction or follow-up answer with Enter (or the phone's send key) without touching the button.
- Shift+Enter and keyboard composition never submit by accident; empty input is ignored.
- No-JS behavior and all other forms are unchanged.
