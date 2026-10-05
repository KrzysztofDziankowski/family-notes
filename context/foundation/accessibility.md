---
project: family-notes
target: WCAG 2.2 Level AA
decided: 2026-10-04
source_change: accessible-family-flows (S-17, PK-17, PRD Question 18)
updated: 2026-10-05
---

# Accessibility

## Target

Every covered flow meets **WCAG 2.2 Level AA** (all Level A and AA success criteria) in the
server-rendered Polish UI. AAA criteria, a formal accessibility statement and certification are
out of scope.

## Covered flows

- Sign-in page (`account_login`), including its invalid re-render.
- Natural-language capture → review → confirm: empty, invalid, proposal, past date, unavailable,
  follow-up highlights, skipped, confirm-invalid and saved states; the S-03 correction states
  (`corrected`, `correction_failed`, correction-invalid); the S-04 batch review and batch-invalid.
- The capture and follow-up forms in each S-06 progress state: running, slow, stalled, offline and
  connection lost.
- Enter-to-submit (S-05) in capture, follow-up and „Popraw opis”.
- Follow-up question: answer and skip.
- Parent family list (upcoming, past, empty), detail, structured create and edit (valid and
  invalid), and the „Usuń wpis” disclosure.
- Child assigned-entry list (upcoming, past, empty) and detail.
- Account status (parent, child, unconfigured account).
- Family member management (S-14): member list (with guard error and notice), display-name
  edit (valid and invalid), and the account page link (`family_access/tests/test_membership_accessibility.py`).
- The S-06 `/offline/` page (anonymous and signed in) and web manifest: no orientation lock
  (SC 1.3.4).
- 403, 404 (signed in and anonymous) and 500 pages.

**Not covered:** Django admin (operator-only, English), allauth pages other than sign-in, and the
DEBUG-only state galleries (`/entries/_states/`, `/entries/mine/_states/`,
`/account/family/_states/`), which repeat field
IDs by design.

## Checklist for every product page

1. **Layout.** Extend `base.html` (500 keeps its own copy): `<html lang="pl">`, a non-empty
   `<title>`, the skip link `<a class="fn-skip-link" href="#main">Przejdź do treści</a>` as the
   first focusable element, exactly one `<main id="main" tabindex="-1">` and exactly one `<h1>`.
2. **Headings.** No skipped levels (h1 → h2 → h3).
3. **Names.** Every link and button has visible text or `aria-label`. Repeated link text gets a
   `.fn-visually-hidden` suffix that names its target (the row's „Edytuj” link).
4. **IDs and references.** IDs are unique; every `aria-describedby`, `aria-labelledby` and
   `href="#…"` target exists. No positive `tabindex`; at most one `autofocus` per page.
5. **Fields** — use `entries/_field.html` and `entries.forms.describe_fields`:
   - Every visible field has a `<label for>`.
   - Errors render in **one** container `id="<auto_id>_error"` (Django's own reference).
   - A review hint (missing or past value) renders as `id="<auto_id>-hint"`, also next to errors.
   - The S-05 Enter hint is `id="<auto_id>-enter-hint"`; the readable review date is
     `id="<auto_id>-human"`.
   - `describe_fields(form)` sets `aria-describedby` to exactly the IDs the render outputs, in that
     order (hint, error, Enter hint, readable date) and `aria-invalid="true"` on fields with an
     error or a hint. Call it on every rendered form after validation; the capture views do it in
     `_render`, the management views in `_form_context`.
6. **Errors without JavaScript.** An invalid re-render prefixes the title with „Błąd: ”. The
   structured-form error summary keeps „Popraw zaznaczone pola.” and links to each invalid field
   (`href="#<auto_id>"`, link text = field label).
7. **Status panels.** A static `role="status"` / `role="alert"` panel always contains visible text.
8. **Visual tokens** — only through `family_notes/static/css/tokens.css`, never literal colours in
   templates:
   - Text pairs ≥ 4.5:1, control borders (`--fn-color-control-border`) and focus (`--fn-color-focus`)
     ≥ 3:1. `family_notes/test_tokens_contrast.py` lists the pairs; add new pairs there.
   - One shared `:focus-visible` rule draws a 2px outline offset from every link, button, summary
     and field; Pico's flush ring is suppressed so focus never merges with an accent fill.
   - Light theme only; the only animation is S-06's Pico `aria-busy` spinner, which Pico stops under
     `prefers-reduced-motion` (essential loading indicator, SC 2.2.2).

## Script contracts (S-05, S-06)

- **Progress / live region (S-06, `js/classification-progress.js`).** The progress partial always
  renders one `role="status" aria-live="polite"` region marked `data-live-region`, never under a
  `hidden` ancestor. It holds `hidden` state blocks with text; the script reveals one at a time, so
  each state is announced once. On a provider submit the form gets `aria-busy="true"` and the
  submitter `aria-busy` / `aria-disabled`; textareas become read-only. **Never disable the
  submitter or fields in the submit handler** (their values would not be posted). The elapsed
  counter is `aria-hidden`.
- **Enter-to-submit (S-05, `js/enter-submit.js`).** An opted-in `<textarea data-enter-submit>`
  renders the hidden hint „Enter wysyła, Shift+Enter dodaje nową linię.” as
  `<auto_id>-enter-hint`; the field is described by it on valid and invalid renders; the script
  reveals it.

## Enforcement

- `family_notes/a11y_audit.py` — `audit_page(html)` / `assert_accessible(testcase, response)`, a
  stdlib-only structural audit of rules 1–7 and the live-region contract (a `data-live-region`
  region needs `aria-live` and at least one hidden state block with text). Test support only.
- `entries/tests/test_accessibility.py` and `family_notes/test_accessibility.py` run it over
  every covered flow and state. **A new product page or state adds a case there.**
- `family_notes/test_tokens_contrast.py` checks the token contrast pairs.
- No Playwright, axe-core or browser job in CI yet (owner decision 2026-10-04). Rendered
  behaviour is verified manually, below.

## Manual verification matrix

Run per change that alters covered markup, and record the results as `a11y-verification.md` in
that change's folder (one row per flow, one column per matrix entry, pass/fail with a note):

- Keyboard only, desktop Chrome.
- NVDA with Firefox (Windows).
- VoiceOver with Safari (iOS).
- TalkBack with Chrome (Android).
- axe DevTools browser extension: no serious or critical violations.
- 200% zoom and 320 CSS px reflow: no horizontal scrolling or clipped content; targets ≥ 24×24 px
  or meet the spacing exception (SC 2.5.8).
