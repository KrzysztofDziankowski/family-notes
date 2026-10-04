# Accessible Family Flows Implementation Plan

## Overview

Implement roadmap-future slice S-17 (PK-17): family members can use the core family flows under an explicit, written accessibility target. This plan fixes WCAG 2.2 Level AA as that target for a named set of flows, closes the concrete gaps found in the current templates and design tokens, and adds automated checks to the Django suite plus a recorded manual pass with assistive technology. That keeps the target enforced after this slice ships.

The PRD leaves the criteria and covered interactions open (`context/foundation/prd-v2.md:241`, Question 18). The owner confirmed the target, slice order, release and testing stance on 2026-10-04, and plan-review decisions were applied on 2026-10-04; the remaining decisions below are assumed defaults.

### Owner Decisions (2026-10-04)

- Accessibility target is WCAG 2.2 AA.
- All future-roadmap slices except removed ones are in the next milestone; confirmed order: S-01, S-02, S-20, S-03, S-04, S-05, S-06, S-07, S-08, S-09, S-17, S-14, S-15, S-16.
- Ship without feature flags and without backfilling existing data.
- No Playwright/E2E tests in this slice; browser tests will be added later.

Items below that the owner did not address remain assumed defaults; they stand unless the owner objects.

### Decisions

1. **Target standard: WCAG 2.2 Level AA** (owner-confirmed 2026-10-04) (all A and AA success criteria) for the covered flows, applied to the server-rendered Polish UI. Rationale: WCAG 2.2 AA is the current baseline that the EU accessibility rules and the Polish public-sector law point to, and the existing tokens already aim at AA contrast (`family_notes/static/css/tokens.css:8-9`). (PRD Q18)
2. **Covered flows:** sign-in page, natural-language capture → review → confirm (including saved, unavailable, past-date and invalid states, S-03's correction states `corrected`/`correction_failed`, and S-04's batch review), the capture and follow-up forms in each S-06 progress state (running, slow, stalled, offline, connection lost), Enter-to-submit (S-05), follow-up question (answer and skip), parent family list / detail / structured create / edit / delete disclosure, child assigned-entry list and detail, account status, the S-06 `/offline/` page (anonymous and authenticated), the S-06 web manifest (no orientation lock, SC 1.3.4), and the 403/404/500 pages. Not covered: Django admin (operator-only, English), allauth pages other than sign-in, and the DEBUG-only state galleries. Rationale: these are all the product pages a family member can reach; admin is already excluded from product UX rules (`context/foundation/lessons.md`). (PRD Q18)
3. **Automated checks: Django test-client HTML audit plus a token-contrast unit test, with no Playwright or axe in CI in this slice** (no-E2E part owner-confirmed 2026-10-04). Rationale: the repository has no Node or Playwright stack, and the test plan explicitly records "e2e: none planned" and "visual/accessibility: none planned" (`context/foundation/test-plan.md:87-88`). A stdlib-parser audit catches the structural regressions found here at zero dependency cost. Rendered checks (axe) run manually through the axe DevTools browser extension. Alternative: run `/10x-e2e-setup` and add `@axe-core/playwright`, which is deferred until an E2E stack exists. (PRD Q18)
4. **Manual assistive-technology matrix:** keyboard only in desktop Chrome, NVDA with Firefox on Windows, VoiceOver with Safari on iOS, and TalkBack with Chrome on Android, plus 200% zoom and a 320 CSS px reflow check. Rationale: this covers the two phone platforms the PRD's mobile use implies and the most common desktop screen reader. (PRD Q18)
5. **S-05 and S-06 have shipped before this slice; it verifies their markup and scripts against the contract and may fix them in place, without adding new behaviour.** Classification progress announcements are S-06 (`mobile-classification-progress`) behaviour: an always-rendered `role="status"` live region marked `data-live-region` plus `aria-busy="true"` on the busy form, as S-05's plan expects (S-05 plan, "Critical Implementation Details — Timing & lifecycle"). This slice writes that contract down in `accessibility.md` and adds no new script. Rationale: this avoids two slices shipping competing scripts on the same forms. (PRD Q7, Q18)
6. **Error pages and invalid forms prefix the document title with "Błąd: "**, and the structured-form error summary links to each invalid field. Rationale: on a full page reload without JavaScript, `role="alert"` content is announced unreliably, but screen readers always read the title. This is the established no-JS pattern. (PRD Q18)
7. **Light theme only.** No dark mode and no visual redesign. The only animation is S-06's Pico `aria-busy` spinner, which Pico disables under `prefers-reduced-motion` and which falls under SC 2.2.2's essential-loading exception, so no extra reduced-motion work is needed; the AT pass confirms it. Rationale: these keep the current look (`family_notes/static/css/tokens.css:39`). (PRD Q18)
8. **Release:** (no flag and no backfill owner-confirmed 2026-10-04) an independent slice with no feature flag, scheduled after S-01–S-09 and before S-14–S-16 in the confirmed order. Rationale: changes are markup and CSS only, with no schema or data impact. (PRD Q1, Q12, Q20)

## Current State Analysis

The UI is server-rendered Django on Pico CSS 2.1.1 with a project token layer. Much is already in place:

- `<html lang="pl">`, a `<main>` landmark, and a labelled main navigation (`family_notes/templates/base.html:2,11-34`).
- Labels for every product form field (`entries/templates/entries/_field.html:2`).
- `role="alert"` and `role="status"` on panels (`entries/templates/entries/_manage_messages.html:4`, `_saved_panel.html:1`, `_notice.html:1`).
- `aria-current="page"` on list-mode tabs (`entries/templates/entries/_list_modes.html:9`).
- Explicit focus outlines on entry rows and tabs (`family_notes/static/css/tokens.css:171-175,236-240`).
- Text colour pairs that all pass 4.5:1. Measured: muted on every panel background ≥5.08:1, danger on danger-bg 5.72:1, white on accent 5.91:1.

The audit found these concrete gaps:

1. **Dangling error references.** Django 5.2 automatically adds `aria-describedby="id_<name>_error"` to a field with errors. `_field.html:5` renders the error with `id="{{ field.auto_id }}-error"` (hyphen), so on the capture page (`entries/views.py:110-111,122`) and on confirm-invalid (`entries/views.py:207,228`) the reference points at no element. Only the views that call `_mark_invalid_fields` (`entries/views.py:443-449`) override it to the hyphen form. (WCAG 1.3.1, 3.3.1)
2. **Duplicate IDs.** `_field.html:5` repeats the same `id` for every error message when a field has more than one error. (WCAG 4.1.1 is obsolete in 2.2, but duplicate IDs still break 1.3.1 name/description computation.)
3. **Hint and error collision.** The review form sets `aria-describedby="<id>-hint"` on missing fields (`entries/forms.py:129-133`), but `_field.html:4-8` renders the hint only when there are no errors. A missing field that also fails validation therefore references a hint that is not rendered.
4. **Unassociated human-readable date.** The review form's readable date (`entries/templates/entries/_review_form.html:13`) sits next to the date input but is not associated with it.
5. **Weak or invisible focus indicators.** Pico's secondary buttons ("Wyloguj", "Pomiń", "Dodaj wpis z tekstu") use `--pico-secondary-focus: rgba(93,107,137,0.25)` in light mode, so the ring is nearly invisible. Primary buttons use a ring the same colour as the button fill, so focus shows only as a 2px growth. (WCAG 2.4.7, 1.4.11)
6. **Low-contrast form control borders.** Pico's input border `#cfd5e2` on the input background measures about 1.43:1, which is below the 3:1 non-text contrast that identifies a control's boundary. (WCAG 1.4.11)
7. **No skip link.** `base.html` has no bypass link before the navigation. The `<main>` landmark meets 2.4.1 for screen-reader users, but sighted keyboard users have no shortcut.
8. **Ambiguous repeated link text.** Every parent list row has an "Edytuj" link (`entries/templates/entries/_entry_row.html:22`), so a links list reads "Edytuj, Edytuj, …". (WCAG 2.4.4 is met through list context; 2.4.9 AAA is not required. This is cheap to fix and helps screen-reader link lists.)
9. **Silent errors after reload.** The create and edit error summary says only "Popraw zaznaczone pola." (`entries/templates/entries/_manage_form.html:11-13`), with no way to reach the fields. Without JavaScript, a re-rendered invalid page has no reliable announcement.
10. **No automated accessibility checks.** Existing tests assert a few `aria-invalid` and `aria-current` strings (`entries/tests/test_capture_views.py:220,343-346`, `entries/tests/test_manage_views.py:162,322-323`), but nothing checks page-level structure.

The sign-in form already renders labelled fields with correct Django error association, because allauth's `fields` element ignores `unlabeled` and renders `form.as_p`. This was checked by rendering `LoginForm`. No change is needed beyond the shared layout.

## Desired End State

Every covered page meets WCAG 2.2 AA under these assumptions. The page-structure audit and the token-contrast test enforce the structural and contrast parts in `uv run python manage.py test`. A recorded manual pass with the assistive-technology matrix confirms the rendered behaviour, and `context/foundation/accessibility.md` states the target, the covered flows and the checklist so later slices (S-14, S-15, S-16 and others) stay compliant.

Verify by running the audit test modules and walking through `context/changes/accessible-family-flows/a11y-verification.md`.

### Key Discoveries:

- Django 5.2 auto-adds `aria-invalid="true"` and `aria-describedby="id_<name>_error"` to bound fields with errors, unless the widget attributes already set `aria-describedby`. This was checked by rendering `CaptureForm` with an empty value. The template must therefore use the Django `_error` ID convention.
- `test_manage_views.py:323` asserts the current `id="id_content-error"` form. That ID convention changes in a reviewed diff; the behaviour does not.
- The quality gate forbids literal colours, `style=` and `<style>` in the cleaned templates (`scripts/hooks/quality_gate.py:59-72`), so all new visual rules go into `tokens.css`.
- A 404 response must be byte-identical for missing and foreign entries (`family_notes/templates/404.html:5-9`). The skip link is static, so this still holds.
- `500.html` is standalone and has no request context (`family_notes/templates/500.html:1-4`). It needs its own copy of the skip link.
- The DEBUG galleries render several forms on one page and so repeat field IDs by design. The audit therefore runs against real views, with classification mocked as in `entries/tests/test_capture_views.py:38-45`.
- S-05 and S-06 ship the first scripts on the capture, follow-up and review forms before this slice. S-06 owns `aria-busy` and the progress live region (S-06 plan, Phase 1 §2–§3); S-05 renders a hidden Enter hint with `id="<auto_id>-enter-hint"` under each opted-in field (S-05 plan, Phase 1 §3).

## What We're NOT Doing

- No new JavaScript behaviour, focus management scripts or progress/loading indicator. S-05/S-06 have shipped; this slice verifies their markup and scripts against the contract and may make small in-place fixes, without adding new behaviour.
- No Playwright, axe-core, Node toolchain or CI browser job.
- No dark mode, theming, visual redesign, or replacement of Pico.
- No accessibility work on Django admin, allauth secondary pages (password reset, sign-up, MFA), or the DEBUG galleries.
- No WCAG AAA criteria and no formal accessibility statement or certification.
- No changes to copy meaning, flows, permissions, classification, or data model; no migration.
- No removal of the sign-up link (S-09 `remove-sign-up-option`).

## Implementation Approach

First fix the shared form-field contract, because every flow uses it. Then fix the shared layout and tokens. Then add a reusable page audit that runs every covered flow through the Django test client, plus a token-contrast unit test, and write the criteria document so later slices inherit the rule. Finish with a manual assistive-technology pass recorded in the change folder. Each phase keeps the existing no-JavaScript, Pico-plus-tokens architecture.

## Critical Implementation Details

**State sequencing:** in `_field.html`, a field's `aria-describedby` must list only IDs that the same render actually outputs. When a review field is both "missing" (hint) and invalid (error), render both the hint and the error and reference both IDs. Do not drop one of them.

**User experience spec:** primary buttons have an accent fill, so their focus indicator must be an outline offset from the button. A ring flush with the fill is indistinguishable from the fill. The offset outline is measured against the page background (`--fn-color-bg`), not against the button.

## Phase 1: Form Field Error and Hint Association

### Overview

Make every form field's label, hint, error and readable date programmatically associated, with unique IDs, in all flows that use the shared field partial.

### Changes Required:

#### 1. Shared field partial

**File**: `entries/templates/entries/_field.html`

**Intent**: Render errors in one container whose ID matches Django's automatic reference, and keep the hint rendered alongside errors, so references always resolve and IDs never repeat.

**Contract**: Errors are rendered as one element with `id="{{ field.auto_id }}_error"` containing every error message. The hint (when non-empty) is rendered with `id="{{ field.auto_id }}-hint"` whether or not errors exist. The partial accepts an optional `describe` parameter (an extra element ID, used for the readable date). Existing classes (`fn-field-error`) stay. No inline styles.

#### 2. Widget attributes for invalid and missing fields

**File**: `entries/views.py`, `entries/forms.py`

**Intent**: Have a single place that sets `aria-describedby` to the exact IDs the partial will render, instead of two conflicting conventions.

**Contract**: `_mark_invalid_fields` (`entries/views.py:443`) either becomes a thin wrapper around a shared helper or is removed in favour of it. The helper is called on every re-rendered invalid form (capture, follow-up, confirm-invalid, correction, create, edit and the gallery invalid state) and also on the initial capture, follow-up and review renders, so fields carrying the S-05 Enter hint are described on valid renders too. For each field it sets `aria-invalid="true"` when the field has errors, and `aria-describedby` to the space-separated union of `<auto_id>-hint` (when a hint is shown), `<auto_id>_error` (when errors exist), `<auto_id>-enter-hint` (when the field has `data-enter-submit`, i.e. the S-05 hint is rendered), and the readable-date ID for the review date field. `EntryReviewForm.__init__` (`entries/forms.py:129-133`) keeps marking missing fields with `aria-invalid` but delegates the `aria-describedby` composition to the same helper.

#### 3. Readable date association

**File**: `entries/templates/entries/_review_form.html`

**Intent**: Let screen-reader users hear the weekday and month name that sighted users see under the date input.

**Contract**: The `data-human-date` paragraph gets a stable ID (`id_date-human`) and is passed to `_field.html` as `describe`, so the date input's `aria-describedby` includes it.

#### 4. Tests

**File**: `entries/tests/test_capture_views.py`, `entries/tests/test_follow_up_views.py`, `entries/tests/test_manage_views.py`, `entries/tests/test_entry_forms.py`

**Intent**: Lock the association contract in the flows where it was broken, and update the one assertion that encoded the old ID convention.

**Contract**:
- Capture with empty text and with too-long text renders `aria-describedby="id_text_error"` and an element with that ID.
- Confirm-invalid renders resolvable error references.
- A missing-and-invalid review field references both hint and error, and both are present.
- A field with two errors renders the error ID once.
- The review date input references `id_date-human` when the readable date is shown.
- On the initial capture and follow-up renders (valid, no errors), the opted-in textarea's `aria-describedby` includes `<auto_id>-enter-hint` and that element exists; with an error it lists both the error and the Enter hint.
- `test_manage_views.py:323` changes from `id_content-error` to `id_content_error`.

### Success Criteria:

#### Automated Verification:

- Field association tests pass: `uv run python manage.py test entries.tests.test_capture_views entries.tests.test_follow_up_views entries.tests.test_manage_views entries.tests.test_entry_forms`
- State gallery tests still pass: `uv run python manage.py test entries.tests.test_states_view entries.tests.test_manage_states`
- Django checks pass: `uv run python manage.py check`
- No model changes: `uv run python manage.py makemigrations --check --dry-run`

#### Manual Verification:

- In the browser, submitting an empty capture form shows the Polish error under the field, and the accessibility inspector shows the textarea described by that error text.
- On the review step with a past date, the date input's accessible description includes the warning and the readable weekday date.

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 2: Layout, Focus and Contrast Tokens

### Overview

Give every page a skip link, visible focus on every interactive element, form-control borders with 3:1 contrast, an error-aware page title, and distinguishable "Edytuj" links. Everything goes through the shared layout and `tokens.css`.

### Changes Required:

#### 1. Accessibility tokens and shared classes

**File**: `family_notes/static/css/tokens.css`

**Intent**: Add the missing non-text contrast and focus rules once, as tokens and shared classes, so templates stay free of literal colours.

**Contract**:
- A new `--fn-color-control-border` token is at least 3:1 against `--fn-color-bg`, `--fn-color-surface` and Pico's input background, and is mapped onto `--pico-form-element-border-color`. Document its source in the header comment, as the existing tokens do.
- `--pico-secondary-focus` maps to `--fn-color-focus`.
- A shared `:focus-visible` rule for `button`, `[role="button"]`, `[type="submit"]`, `summary`, `a`, `select`, `input` and `textarea` draws a solid outline of at least 2px in `--fn-color-focus`, offset from the element. Pico's flush box-shadow ring is suppressed so it does not merge with accent fills. Existing `.fn-entry-link` and `.fn-tabs a` focus rules fold into it or stay consistent with it.
- A `.fn-visually-hidden` utility (clip pattern) and a `.fn-skip-link` class, hidden until focused and then visible at the top with surface background and focus outline, are added.

#### 2. Skip link and main target

**File**: `family_notes/templates/base.html`, `family_notes/templates/500.html`

**Intent**: Let keyboard users bypass the navigation on every page.

**Contract**: The first focusable element in `<body>` is `<a class="fn-skip-link" href="#main">Przejdź do treści</a>`. `<main>` gets `id="main"` and `tabindex="-1"` so focus moves into it. `500.html` gets the same markup without URL tags.

#### 3. Error-aware titles

**File**: `entries/templates/entries/capture.html`, `entries/templates/entries/manage_form.html`

**Intent**: Make a re-rendered invalid form audible on page load without JavaScript (Decision 6).

**Contract**: The `title` block is prefixed with `Błąd: ` when the rendered capture, review, follow-up or managed form has errors. Error pages already have distinct titles. The views pass no new context; the templates test the existing forms' `errors`.

#### 4. Linked error summary and contextual edit links

**File**: `entries/templates/entries/_manage_form.html`, `entries/templates/entries/_entry_row.html`

**Intent**: Let users jump from the error summary to each invalid field, and make each "Edytuj" link unique in a links list.

**Contract**: When the managed form has field errors, the summary keeps "Popraw zaznaczone pola." and adds a list of links (`href="#<auto_id>"`, link text = field label) in form order. The row's "Edytuj" link appends `<span class="fn-visually-hidden">: {{ entry.content|truncatechars:60 }}</span>`, and the visible text is unchanged.

#### 5. Tests

**File**: `family_notes/tests.py`, `entries/tests/test_manage_views.py`, `entries/tests/test_capture_views.py`

**Intent**: Assert the new layout contract on representative pages.

**Contract**:
- Login, a parent page, a child page, 403, anonymous 404 and the rendered 500 template each contain the skip link before the navigation and `<main id="main"`.
- Foreign and missing entry 404 bodies remain identical (the existing test still passes).
- Invalid create and capture titles start with `Błąd: `.
- The error summary links to `#id_content` when content is missing.
- Parent list rows include the visually hidden entry context in the edit link.

### Success Criteria:

#### Automated Verification:

- Layout and title tests pass: `uv run python manage.py test family_notes.tests entries.tests.test_manage_views entries.tests.test_capture_views`
- Child and gallery views still pass: `uv run python manage.py test entries.tests.test_child_views entries.tests.test_child_states_view entries.tests.test_states_view entries.tests.test_manage_states`
- Django checks pass: `uv run python manage.py check`

#### Manual Verification:

- Pressing Tab once on any covered page reveals "Przejdź do treści", and activating it moves focus into the main content.
- Tabbing through the capture, follow-up, management list, edit form and child list shows a clearly visible focus outline on every link, button (including "Wyloguj", "Pomiń" and "Dodaj wpis z tekstu"), select, textarea and the "Usuń wpis" disclosure.
- Input, select and textarea boundaries are clearly visible on the light background, and the page looks otherwise unchanged.

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 3: Automated Accessibility Audit and Written Criteria

### Overview

Encode the structural WCAG checks as a reusable page audit that runs every covered flow, add a token-contrast unit test, and write the criteria into foundation docs so future slices inherit them.

### Changes Required:

#### 1. Page audit helper

**File**: `family_notes/a11y_audit.py` (new, test support; imported only from tests)

**Intent**: Provide one dependency-free checker (stdlib `html.parser`) that any app's tests can run against a rendered response.

**Contract**: `audit_page(html: str) -> list[str]` returns human-readable violations (an empty list means pass) for these rules:
- `<html lang="pl">`; a non-empty `<title>`; exactly one `<main>` and exactly one `<h1>`.
- No skipped heading levels.
- The first focusable element is a skip link to an existing ID.
- Unique `id` values.
- Every `aria-describedby`, `aria-labelledby` and `href="#…"` target exists.
- Every visible `input`, `select` and `textarea` has a `<label for>` or `aria-label`.
- Every `aria-invalid="true"` field has a resolvable non-empty description.
- Every link and button has non-empty text or `aria-label`.
- No positive `tabindex`; at most one `autofocus`.
- A `role="alert"` / `role="status"` element must contain visible (not `hidden`) text, **unless** it carries `aria-live` and the `data-live-region` marker (a script-updated region, e.g. S-06's progress region). Such a region must contain at least one `hidden` state block with text, and may have no visible text at render time. The helper's unit tests include one passing and one failing snippet for each branch.

A companion `assert_accessible(testcase, response)` fails with the violation list. Where it lives: `family_notes/` already hosts project-wide test modules (`family_notes/test_auth_security.py`). The helper has no runtime import from product code.

#### 2. Core-flow audit tests

**File**: `entries/tests/test_accessibility.py` (new), `family_notes/test_accessibility.py` (new)

**Intent**: Run the audit across every covered flow and state through real views, so a regression in any template fails the suite.

**Contract**: `entries/tests/test_accessibility.py` uses `FamilyFixtureMixin` and mocks classification the way `entries/tests/test_capture_views.py:38-45` does. It covers capture in the empty, invalid, proposal, past-date, unavailable, follow-up question, follow-up invalid, skipped, confirm-invalid and saved states. It also covers the S-03 correction states (`corrected`, `correction_failed`, correction-invalid), the S-04 batch review (several proposals, and batch-invalid), and capture and follow-up rendered with each S-06 `progress_state` (running, slow, stalled, offline, connection lost; one form per page so IDs stay unique, using the same context the S-06 gallery uses). It also covers parent list (upcoming, past, empty), detail, delete-open, create, create-invalid, edit and edit-invalid, and child list (upcoming, past, empty) and detail. `family_notes/test_accessibility.py` covers login, account status for parent, child and unconfigured users, 403, 404 for authenticated and anonymous users, `/offline/` for anonymous and authenticated users, and the rendered 500 template, plus a manifest assertion that `/manifest.webmanifest` has no `orientation` lock (absent or `"any"`, SC 1.3.4). Each case asserts `audit_page(...) == []`.

#### 3. Token contrast test

**File**: `family_notes/test_tokens_contrast.py` (new)

**Intent**: Stop future token edits from silently breaking contrast.

**Contract**: The test parses the `:root` custom properties in `family_notes/static/css/tokens.css` and computes WCAG relative-luminance ratios. It asserts at least 4.5:1 for each declared text pair: text, text-strong, muted, accent and danger on bg and surface; muted on success-bg, notice-bg and danger-bg; danger on danger-bg; accent-inverse on accent and on danger. It asserts at least 3:1 for non-text pairs: control-border on bg and surface, and focus on bg, surface, success-bg, notice-bg and danger-bg. The pair list lives in the test with one-line WCAG references.

#### 4. Criteria and conventions

**File**: `context/foundation/accessibility.md` (new), `AGENTS.md`, `context/foundation/test-plan.md`

**Intent**: Make the target and checklist a living foundation decision, and point agents at it.

**Contract**:
- `accessibility.md` states WCAG 2.2 AA, the covered flows list, the assistive-technology matrix, the progress/live-region contract for S-06 (an always-rendered `role="status"` `aria-live` region marked `data-live-region` whose hidden state blocks the script reveals, plus `aria-busy="true"` on the form; never disable the submitter in the submit handler), the S-05 Enter-hint association, the field-association contract from Phase 1, and the rule that new product pages add a case to the audit tests.
- `AGENTS.md` "UI Conventions" gains one bullet pointing to `@context/foundation/accessibility.md` and the audit helper.
- In `test-plan.md` §4, the "visual/accessibility" row changes from "none planned" to "Django HTML audit + token contrast test; manual axe/AT pass per accessibility.md".

### Success Criteria:

#### Automated Verification:

- Audit tests pass: `uv run python manage.py test entries.tests.test_accessibility family_notes.test_accessibility`
- Token contrast test passes: `uv run python manage.py test family_notes.test_tokens_contrast`
- Deliberate break detected: temporarily restoring `id="{{ field.auto_id }}-error"` in `_field.html` makes `entries.tests.test_accessibility` fail, and reverting makes it pass
- Full suite passes: `uv run python manage.py test`
- Django checks pass: `uv run python manage.py check`
- No model changes: `uv run python manage.py makemigrations --check --dry-run`

#### Manual Verification:

- `context/foundation/accessibility.md` reads clearly and matches the Decisions, and the AGENTS.md bullet points to it

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 4: Assistive-Technology Verification Pass

### Overview

Confirm the rendered behaviour that markup tests cannot prove, using the agreed matrix, and record the results in the change folder.

### Changes Required:

#### 1. Verification record

**File**: `context/changes/accessible-family-flows/a11y-verification.md` (new)

**Intent**: Keep dated evidence of the manual pass, and of any remaining issue, next to the change.

**Contract**: A table with one row per covered flow and columns for each matrix entry: keyboard/Chrome, NVDA/Firefox, VoiceOver/iOS Safari, TalkBack/Android Chrome, axe DevTools, and 200% zoom / 320 px reflow. Rows include Enter-to-submit (capture, follow-up, correction), the progress running/slow announcements and the `/offline/` page. Each cell says pass or fail with a short note. A failing AA criterion is either fixed in this change (templates, tokens, or a small in-place fix to the S-05/S-06 scripts that adds no new behaviour, with a matching audit case where markup is involved) or recorded as a follow-up with its WCAG number.

### Success Criteria:

#### Manual Verification:

- axe DevTools reports no serious or critical violations on each covered page (login, capture states including correction, batch review and progress states, follow-up, parent list/detail/create/edit, child list/detail, account status, 403, 404, `/offline/`)
- Keyboard only: every covered flow, including delete via the disclosure, skip on the follow-up question and Enter-to-submit in capture, follow-up and „Popraw opis”, completes without a mouse, with visible focus and no focus trap
- NVDA + Firefox: page title, headings, field labels, errors, hints (including the Enter hint) and the saved/notice panels are announced in Polish, Enter in focus mode submits the opted-in boxes, the progress running and slow states are each announced once, and invalid re-renders are recognisable from the "Błąd:" title
- VoiceOver on iOS Safari and TalkBack on Android Chrome: capture → review → confirm and the child list/detail flows complete with correctly announced controls, the TalkBack send key submits, progress running/slow states are announced, and the `/offline/` page reads correctly
- At 200% zoom and at 320 CSS px width, all covered pages reflow without horizontal scrolling or clipped content, and targets meet 24×24 px or the spacing exception
- `a11y-verification.md` is filled in for every flow and matrix column

**Implementation Note**: This phase is manual-only. Any fix it requires reruns the Phase 3 automated checks before the change is marked implemented.

---

## Testing Strategy

### Unit Tests:

- Token contrast ratios for all declared text and non-text pairs.
- Audit helper rules on small fixed HTML snippets (one passing and one failing snippet per rule, and per branch of the live-region rule), in `family_notes/test_accessibility.py`.
- Field `aria-describedby` composition for hint only, error only, hint plus error, multiple errors, readable date, and the S-05 Enter hint (valid and invalid renders).

### Integration Tests:

- Each covered flow state rendered through the Django test client with mocked classification, then passed through `audit_page`.
- 404 bodies identical for missing and foreign entries after the layout change.

### Manual Testing Steps:

1. Open the capture page, Tab once, activate "Przejdź do treści", then submit empty text and confirm the title starts with "Błąd:" and the error is announced with the field.
2. Classify a past-dated note, check that the date field's description reads the warning and weekday, confirm, and hear the saved panel.
3. As a parent, create an entry with missing content, follow the summary link to the field, fix it and save.
4. As a child, open the list and a detail page with VoiceOver and TalkBack.
5. Run axe DevTools on each covered page and record the results.

## Performance Considerations

None. The changes are static markup and CSS, and the audit is a pure-Python parse in tests.

## Migration Notes

No schema or data changes. Rollback is reverting the template, CSS and test files. The ID convention change (`-error` to `_error`) affects only rendered HTML and tests.

## References

- PRD: `context/foundation/prd-v2.md:174` (PK-17), `context/foundation/prd-v2.md:241` (Question 18)
- Roadmap: `context/foundation/roadmap-future.md` — S-17
- Test plan tooling stance: `context/foundation/test-plan.md:87-88,93`
- Shared field partial: `entries/templates/entries/_field.html:1-9`
- Invalid-field marking: `entries/views.py:443-449`; review hints: `entries/forms.py:129-133`
- Tokens and focus rules: `family_notes/static/css/tokens.css:8-9,39-65,171-175,236-240`
- Layout: `family_notes/templates/base.html:1-37`; standalone 500: `family_notes/templates/500.html:1-29`
- Template literal gate: `scripts/hooks/quality_gate.py:59-72`
- S-05/S-06 script coordination: `context/changes/enter-text-submission/plan.md` ("Critical Implementation Details — Timing & lifecycle", Phase 1 §3 hint), `context/changes/mobile-classification-progress/plan.md` (Phase 1 §2 progress partial, Phase 2 §2 manifest/offline)
- S-03/S-04 review states: `context/changes/free-text-proposal-correction/plan.md` (Phase 2–3), `context/changes/multi-entry-text-capture/plan.md` (Phase 2–4)

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Form Field Error and Hint Association

#### Automated

- [ ] 1.1 Field association tests pass: `uv run python manage.py test entries.tests.test_capture_views entries.tests.test_follow_up_views entries.tests.test_manage_views entries.tests.test_entry_forms`
- [ ] 1.2 State gallery tests still pass: `uv run python manage.py test entries.tests.test_states_view entries.tests.test_manage_states`
- [ ] 1.3 Django checks pass: `uv run python manage.py check`
- [ ] 1.4 No model changes: `uv run python manage.py makemigrations --check --dry-run`

#### Manual

- [ ] 1.5 In the browser, submitting an empty capture form shows the Polish error under the field, and the accessibility inspector shows the textarea described by that error text.
- [ ] 1.6 On the review step with a past date, the date input's accessible description includes the warning and the readable weekday date.

### Phase 2: Layout, Focus and Contrast Tokens

#### Automated

- [ ] 2.1 Layout and title tests pass: `uv run python manage.py test family_notes.tests entries.tests.test_manage_views entries.tests.test_capture_views`
- [ ] 2.2 Child and gallery views still pass: `uv run python manage.py test entries.tests.test_child_views entries.tests.test_child_states_view entries.tests.test_states_view entries.tests.test_manage_states`
- [ ] 2.3 Django checks pass: `uv run python manage.py check`

#### Manual

- [ ] 2.4 Pressing Tab once on any covered page reveals "Przejdź do treści", and activating it moves focus into the main content.
- [ ] 2.5 Tabbing through the capture, follow-up, management list, edit form and child list shows a clearly visible focus outline on every link, button (including "Wyloguj", "Pomiń" and "Dodaj wpis z tekstu"), select, textarea and the "Usuń wpis" disclosure.
- [ ] 2.6 Input, select and textarea boundaries are clearly visible on the light background, and the page looks otherwise unchanged.

### Phase 3: Automated Accessibility Audit and Written Criteria

#### Automated

- [ ] 3.1 Audit tests pass: `uv run python manage.py test entries.tests.test_accessibility family_notes.test_accessibility`
- [ ] 3.2 Token contrast test passes: `uv run python manage.py test family_notes.test_tokens_contrast`
- [ ] 3.3 Deliberate break detected: temporarily restoring `id="{{ field.auto_id }}-error"` in `_field.html` makes `entries.tests.test_accessibility` fail, and reverting makes it pass
- [ ] 3.4 Full suite passes: `uv run python manage.py test`
- [ ] 3.5 Django checks pass: `uv run python manage.py check`
- [ ] 3.6 No model changes: `uv run python manage.py makemigrations --check --dry-run`

#### Manual

- [ ] 3.7 `context/foundation/accessibility.md` reads clearly and matches the Decisions, and the AGENTS.md bullet points to it

### Phase 4: Assistive-Technology Verification Pass

#### Manual

- [ ] 4.1 axe DevTools reports no serious or critical violations on each covered page (login, capture states including correction, batch review and progress states, follow-up, parent list/detail/create/edit, child list/detail, account status, 403, 404, `/offline/`)
- [ ] 4.2 Keyboard only: every covered flow, including delete via the disclosure, skip on the follow-up question and Enter-to-submit in capture, follow-up and „Popraw opis”, completes without a mouse, with visible focus and no focus trap
- [ ] 4.3 NVDA + Firefox: page title, headings, field labels, errors, hints (including the Enter hint) and the saved/notice panels are announced in Polish, Enter in focus mode submits the opted-in boxes, the progress running and slow states are each announced once, and invalid re-renders are recognisable from the "Błąd:" title
- [ ] 4.4 VoiceOver on iOS Safari and TalkBack on Android Chrome: capture → review → confirm and the child list/detail flows complete with correctly announced controls, the TalkBack send key submits, progress running/slow states are announced, and the `/offline/` page reads correctly
- [ ] 4.5 At 200% zoom and at 320 CSS px width, all covered pages reflow without horizontal scrolling or clipped content, and targets meet 24×24 px or the spacing exception
- [ ] 4.6 `a11y-verification.md` is filled in for every flow and matrix column
