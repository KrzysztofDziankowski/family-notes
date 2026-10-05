# Enter Text Submission Implementation Plan

## Overview

Implement roadmap-future slice S-05 (PK-07, US-07): a parent who types an instruction into the natural-language capture box, an answer into the follow-up question box, or a correction into S-03's „Popraw opis” box, can submit it by pressing Enter. Shift+Enter keeps inserting a newline, an in-progress IME/keyboard composition never submits, and the forms keep working unchanged without JavaScript.

The repository has no JavaScript today, so this slice also introduces the first project static script, as a small, opt-in, progressively enhancing file.

### Owner Decisions (2026-10-04)

- Enter also submits on a phone's virtual keyboard (newline on the phone only by pasting).
- All future-roadmap slices except removed ones are in the next milestone; confirmed order: S-01, S-02, S-20, S-03, S-04, S-05, S-06, S-07, S-08, S-09, S-17, S-14, S-15, S-16.
- Ship without feature flags and without backfilling existing data.
- No Playwright/E2E tests in this slice; browser tests will be added later.
- The S-03 „Popraw opis” correction box opts in to Enter-to-submit. Enter there triggers the „Popraw” button explicitly (`form.requestSubmit(<Popraw button>)`), never the form's default action, which would save the entry (review F2, owner-confirmed 2026-10-04).

Owner decisions were applied on 2026-10-04 after plan review. Items below not marked owner-confirmed remain assumed defaults; they stand unless the owner objects.

### Decisions

Each decision below stands in for PRD-v2 Open Question 8 (and, for the release item, Questions 1, 12 and 20).

1. **Forms in scope: the natural-language instruction boxes** — the capture instruction (`CaptureForm.text`, "Rozpoznaj"), the follow-up answer (`FollowUpAnswerForm.answer`, "Dalej") and the S-03 correction box (`correction`, „Popraw opis”, submitted through „Popraw”; owner-confirmed 2026-10-04). S-04's batch review (lands before this slice) opts in each per-proposal „Popraw tekstem” box the same way; its textarea's `data-enter-submitter` points at that proposal's `e{i}-correct-submit` button. The review form's and structured create/edit forms' "Tytuł" (`content`) textarea keep Enter = newline. Rationale: those are the "text input → submit" interactions US-07 describes; on review/manage forms Enter in "Tytuł" would save an entry, and their single-line inputs (date, time) already submit on Enter natively. (Q8)
2. **Plain Enter submits; Shift+Enter inserts a newline; Ctrl/Alt/Meta+Enter keep the browser default (no submit).** Rationale: the common chat convention; the smallest key map that keeps a newline shortcut. (Q8)
3. **Composition never submits:** a keydown with `isComposing === true` or `keyCode === 229` is ignored, so confirming an IME candidate, Android predictive text or a dead-key sequence (Polish diacritics) cannot submit. (Q8)
4. **On a phone's virtual keyboard Enter also submits** (owner-confirmed 2026-10-04) and the keyboard shows a "send" action (`enterkeyhint="send"`); a newline is then available only via pasting. Rationale: instructions are one short sentence; one consistent rule is simpler than device sniffing. (Q8)
5. **Enter on empty or whitespace-only text does nothing** (no newline, no submit, no browser validation bubble). Rationale: avoids an accidental empty classification request and a non-Polish native bubble. (Q8)
6. **Enter submits through the form's default action unless the field names an explicit submitter.** In the follow-up form it means "Dalej", never "Pomiń". In the review form the correction box names „Popraw”, so Enter posts to `entries:correct` and can never post to `entries:confirm` (owner-confirmed 2026-10-04). (Q8)
7. **A short Polish hint is shown under each opted-in box once the script is running**: "Enter wysyła, Shift+Enter dodaje nową linię." It is rendered `hidden` and revealed by the script, so it never misleads without JavaScript. Rationale: discoverability without changing the layout. (Q8)
8. **No Playwright/E2E infrastructure is introduced** (owner-confirmed 2026-10-04); the key handling is verified by rendered-markup tests plus a manual browser matrix, in line with `context/foundation/test-plan.md:87` ("e2e: none planned"). (Q12)
9. **Release** (owner-confirmed 2026-10-04): ships as an independent slice, no feature flag; rollback is removing the script include. (Q1, Q12, Q20)

## Current State Analysis

- Capture is a plain HTML form posting to `entries:capture`; the instruction is a `Textarea` with `rows=3` and `autofocus` (`entries/forms.py:32-38`, `entries/templates/entries/_capture_form.html:1-5`). In a `<textarea>` Enter inserts a newline, so today a parent must tap "Rozpoznaj".
- The follow-up answer is also a `Textarea` (`entries/forms.py:294-300`) inside a form with two submit buttons: the default "Dalej" and `name="action" value="skip"` "Pomiń" (`entries/templates/entries/_follow_up_form.html:14-18`). The view decides skip vs. answer by `request.POST.get('action') == 'skip'` (`entries/views.py:151`).
- Review and structured create/edit forms also use a `Textarea` for "Tytuł" (`entries/forms.py:62-66`, `entries/templates/entries/_review_form.html:9-16`, `entries/templates/entries/_manage_form.html:17`).
- S-03 (`free-text-proposal-correction`, lands before this slice) adds an optional `correction` Textarea („Popraw opis”) to `EntryReviewForm`/`ProposalCorrectionForm` and a secondary submit „Popraw” with `name="action" value="correct"`, `formaction="{% url 'entries:correct' %}"`, `formnovalidate` and a stable prefix-aware `id` (`correct-submit`, or `{prefix}-correct-submit`) to `_review_form.html`; the correction textarea carries `data-enter-submitter="<that button id>"`. „Zapisz wpis” stays the form's default (first) submit, posting to `entries:confirm` (S-03 plan, Phase 2 §1 and §3). S-04 (`multi-entry-text-capture`) adds per-proposal correction boxes whose „Popraw” submit has `name="action" value="correct-{i}"` and `id="e{i}-correct-submit"`, with the textarea carrying `data-enter-submitter="e{i}-correct-submit"` (S-04 plan, Phase 3). S-03/S-04 add no JavaScript.
- No JavaScript exists anywhere in the project: no `<script>` tags in templates and only `css/` and `vendor/pico/` under `family_notes/static/`. `base.html` already provides an empty `{% block extra_body %}` before `</body>` (`family_notes/templates/base.html:35`). No Content-Security-Policy is configured (`family_notes/settings.py:209-219`), so a same-origin static script is allowed.
- The DEBUG-only kitchen sink `/entries/_states/` renders the capture and follow-up partials from synthetic data (`entries/templates/entries/states.html:18-26`, `entries/views.py:249`).
- The template quality gate forbids literal colours, `style=` and `<style>` in cleaned templates (`scripts/hooks/quality_gate.py:59-72`); it does not restrict scripts.

## Desired End State

On the capture page, on the follow-up question and in the review's „Popraw opis” box, a parent with a hardware keyboard presses Enter to submit (in the correction box: to run „Popraw”, never to save), presses Shift+Enter for a newline, and never submits while composing a character. On Android Chrome, the virtual keyboard shows a send action that submits. Empty input is ignored. Without JavaScript, both forms behave exactly as today. The "Tytuł" box of the review, create and edit forms is unchanged.

### Key Discoveries:

- Both target fields are Django form widgets, so an opt-in marker can be set once in `entries/forms.py` widget attrs instead of in templates (`entries/forms.py:37`, `entries/forms.py:298`).
- `HTMLFormElement.requestSubmit()` with no submitter fires the `submit` event and runs constraint validation, and it does not include any named button value — so it always maps to "Dalej", not "Pomiń" (`entries/views.py:151`).
- `requestSubmit()` with no submitter ignores every button's `formaction`, so on the review form it would post to `entries:confirm` and **save** the entry. `requestSubmit(button)` applies the button's `formaction`, `formnovalidate` and `name`/`value`, which is why the correction box must name its submitter.
- `requestSubmit()` does not always produce a submission: constraint validation or another `submit` handler (S-06 cancels offline submits with `preventDefault()`) can stop it.
- `base.html:35` `extra_body` is the existing hook for page-specific scripts; nothing else needs to change in the base layout.
- S-06 (`mobile-classification-progress`) plans a separate script that listens to the same forms' `submit` event and marks the form `aria-busy="true"` while a classification is in flight; this slice must not re-submit a busy form.

## What We're NOT Doing

- No Enter-to-submit on the review form's "Tytuł" box, structured create/edit forms, management lists, sign-in or any other page. The correction box is the only opted-in field on the review form.
- No change to server-side handling, validation, classification, or the stored text; newlines that a parent pastes are kept as today.
- No custom shortcut configuration, no Ctrl+Enter alternative.
- No JavaScript build tooling, npm, bundler, or test runner; no Playwright setup.
- No visual redesign of the capture page.
- No progress indicator or double-submit UI; S-06 owns that.

## Implementation Approach

Mark the opted-in textareas with a data attribute (naming an explicit submitter where the default action is wrong) and `enterkeyhint="send"` in their form definitions, add one small deferred static script with a single delegated `keydown` listener, include it only on the pages that render those forms, and add a muted hint line. Server tests prove the opt-in markup and the script include; manual checks cover real keyboards and IMEs.

## Critical Implementation Details

**Timing & lifecycle** — Ignore `event.repeat` and remember that the form was submitted for the current page life, so a held key or a double press cannot post twice. Record that flag only for submissions that really go out: a `submit` listener on `window` (bubble phase, so it runs after S-06's `document` listener) sets it only when `!event.defaultPrevented`. A submit cancelled by validation or by S-06's offline branch therefore leaves Enter working; comment this listener-order reliance in the script. Reset the flag on `pageshow` (bfcache restore after Back), otherwise a restored page would ignore Enter forever. Also skip when the form already has `aria-busy="true"`, the busy marker S-06 sets; that way the two scripts compose in either landing order.

**Submitter safety** — A field that carries `data-enter-submitter="<button id>"` (rendered by S-03/S-04, see `free-text-proposal-correction/plan.md` Phase 2 §3) is submitted only through that button, which must be a submit button inside the same form. If it is missing, the script does nothing (browser default newline) and never falls back to `requestSubmit()` with no submitter.

**User experience spec** — The composition check must use both `isComposing` and `keyCode === 229`. Android Gboard reports some composition keydowns only through the 229 code, and Polish diacritics typed with a long press or swipe typing go through composition.

## Phase 1: Enter-to-Submit Behavior

### Overview

Opt the capture, follow-up and correction textareas in, ship the script, and wire it into the capture page and the DEBUG state gallery.

### Changes Required:

#### 1. Opt-in markers on the two fields

**File**: `entries/forms.py`

**Intent**: Declare, once at the form level, which textareas submit on Enter, so templates and the state gallery inherit it automatically.

**Contract**: `CaptureForm.text` and `FollowUpAnswerForm.answer` widgets gain an empty `data-enter-submit` (= the form's default action) and `enterkeyhint="send"` alongside their existing attrs (`rows`, `autofocus`). The S-03 `correction` widget (on `EntryReviewForm` and `ProposalCorrectionForm`) gains an empty `data-enter-submit` and `enterkeyhint="send"`; it already carries S-03's `data-enter-submitter="<Popraw button id>"` (`correct-submit` or `{prefix}-correct-submit`), and this slice adds no button markers. If S-04's batch review exists, each sub-form's `correction` widget gets the same opt-in and already points at `e{i}-correct-submit` (S-04 Phase 3).

#### 2. Enter-submit script

**File**: `family_notes/static/js/enter-submit.js` (new)

**Intent**: Turn a plain Enter in an opted-in textarea into a normal form submission, without breaking newlines, composition, or no-JS behavior.

**Contract**: One delegated `keydown` listener on `document`, acting only when the target is `textarea[data-enter-submit]`. It does nothing (browser default) when `key !== 'Enter'`, when Shift/Ctrl/Alt/Meta is held, when `isComposing` is true or `keyCode === 229`, or when the field has `data-enter-submitter` and `document.getElementById(<that id>)` is not a submit button inside the same form. Otherwise it calls `preventDefault()`. It then returns early when `event.repeat` is set, when the trimmed value is empty, when the form has `aria-busy="true"`, or when this page already submitted the form. In every other case, for a field with `data-enter-submitter` it calls `form.requestSubmit(document.getElementById(<that id>))` — never the form's default submit — and otherwise `form.requestSubmit()` with no submitter (capture, follow-up). A `submit` listener on `window` records the per-form submitted flag only when `!event.defaultPrevented` (see Critical Implementation Details). On load it removes `hidden` from every `[data-enter-hint]`. A `pageshow` listener clears the per-form submitted flag. The file is plain ES2017 or older and uses no globals besides `document`/`window`. Code comments are in English.

#### 3. Script include and hint

**Files**: `entries/templates/entries/capture.html`, `entries/templates/entries/states.html`, `entries/templates/entries/_capture_form.html`, `entries/templates/entries/_follow_up_form.html`, `entries/templates/entries/_review_form.html` (S-03 correction box; S-04 batch partial if present)

**Intent**: Load the script only where the opted-in forms render, and tell the parent about the shortcut.

**Contract**: `capture.html` and `states.html` fill `{% block extra_body %}` with `<script src="{% static 'js/enter-submit.js' %}" defer></script>`, loading `{% load static %}`. Each opted-in field's partial renders, directly after the field include, a `<p class="fn-muted" id="{{ field.auto_id }}-enter-hint" data-enter-hint hidden><small>` hint with the exact Polish copy "Enter wysyła, Shift+Enter dodaje nową linię." The script reveals it, so without JavaScript it stays hidden. Do not put `aria-describedby` in widget attrs (it would suppress Django's automatic `_error` reference); S-17's field-association helper composes the hint ID into the description. The hint uses no inline styles or new CSS literals.

### Success Criteria:

#### Automated Verification:

- Form/view tests prove the capture `text`, follow-up `answer` and review `correction` textareas render `data-enter-submit` and `enterkeyhint="send"` (the correction box additionally carrying S-03's `data-enter-submitter`), while review, create and edit `content` textareas do not.
- View tests prove the capture page (empty, question, proposal states) and the DEBUG state gallery include the `js/enter-submit.js` script tag, and each opted-in field renders the hint copy in a `hidden` `data-enter-hint` element with `id="<auto_id>-enter-hint"`.
- A test proves `js/enter-submit.js` is resolvable through Django's static files finders.
- Review-form tests (proposal, follow-up-highlight, `correction_failed` and confirm-invalid states, plus the S-04 batch review if present) prove Enter there can never post to `entries:confirm`: every `data-enter-submit` field inside a form whose action is `entries:confirm` carries a `data-enter-submitter` id that resolves to a submit button in the same form with `formaction` equal to `reverse('entries:correct')` (batch: `name="action" value="correct-<i>"`, id `e{i}-correct-submit`); no field points at „Zapisz wpis”.
- Focused tests pass: `uv run python manage.py test entries.tests.test_capture_views entries.tests.test_follow_up_views entries.tests.test_correction_views entries.tests.test_states_view entries.tests.test_entry_forms`.
- Django checks pass: `uv run python manage.py check`.

#### Manual Verification:

- Desktop Chrome: Enter on the capture box submits; Shift+Enter inserts a newline; Enter on empty or whitespace-only text does nothing; holding Enter posts only once.
- Desktop Chrome: in the follow-up question, Enter performs "Dalej" (the answer is classified), never "Pomiń".
- Android Chrome with Gboard: the keyboard shows a send action; typing Polish diacritics by long press and swipe typing never submits mid-word; the send key submits.
- With JavaScript disabled, all opted-in forms still submit only through their buttons, Enter inserts a newline, and no Enter hint is visible.
- Review, structured create and edit forms: Enter in "Tytuł" still inserts a newline and does not save.
- Review form: Enter in „Popraw opis” runs „Popraw” (the revised proposal is shown), no entry is saved, and an empty correction box ignores Enter.

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding.

---

## Phase 2: Regression and Release Verification

### Overview

Prove the slice leaves the rest of the capture, follow-up, privacy and management behavior intact, and that the static file ships in a release.

### Changes Required:

#### 1. Regression coverage

**File**: `entries/tests/test_capture_views.py`, `entries/tests/test_follow_up_views.py`

**Intent**: Lock in that the server contract is unchanged: a POST without any button value on the follow-up form is treated as an answer, not a skip. This is the request `requestSubmit()` produces.

**Contract**: A follow-up POST carrying the answer and hidden draft fields but no `action` key is classified as an answer (backend called once). The same POST with `action=skip` still skips without calling the backend.

#### 2. Static collection check

**File**: none (verification only)

**Intent**: Confirm the new `js/` directory is collected for production, where static files come from `STATIC_ROOT` (`family_notes/settings.py:456-458`).

**Contract**: `collectstatic` into a temporary directory includes `js/enter-submit.js`.

### Success Criteria:

#### Automated Verification:

- Follow-up tests prove a POST without `action` is answered via the backend and a POST with `action=skip` skips without a backend call.
- Full test suite passes: `uv run python manage.py test`.
- Django checks pass: `uv run python manage.py check`.
- Migration drift check passes: `uv run python manage.py makemigrations --check --dry-run`.
- Static collection includes the script: `DJANGO_STATIC_ROOT=$(mktemp -d) uv run python manage.py collectstatic --noinput` lists `js/enter-submit.js`.

#### Manual Verification:

- After deployment, on the production capture page in Chrome on Android, Enter/send submits an instruction end to end through review and save.

**Implementation Note**: Complete manual verification before implementation review.

---

## Testing Strategy

### Unit Tests:

- Widget attrs: opted-in vs. not-opted-in textareas, including the correction box's named submitter.
- Static finder resolves the script.

### Integration Tests:

- Rendered capture page in each state and the DEBUG state gallery contain the script include and the hidden hint.
- Review form states: the correction box's named submitter is „Popraw” with the `entries:correct` formaction; „Zapisz wpis” is never an Enter submitter.
- Follow-up POST without `action` → answer path; with `action=skip` → skip path.

### Manual Testing Steps:

1. Desktop Chrome: Enter, Shift+Enter, empty Enter, held Enter on the capture box.
2. Follow-up question: Enter answers ("Dalej"), button "Pomiń" still skips.
3. Review form: Enter in „Popraw opis” corrects and never saves; Enter in "Tytuł" is a newline.
4. Android Chrome + Gboard: long-press diacritics, swipe typing, predictive suggestion tap, send key.
5. Back navigation after a submit (bfcache): Enter works again on the restored page.
6. JavaScript disabled: buttons only; Enter inserts a newline; the hint is hidden.
7. Review/create/edit "Tytuł": Enter is a newline.

## Performance Considerations

One small deferred script (well under 2 KB) on the capture page only; no impact on server latency.

## Migration Notes

No database or data changes. Rollback: remove the script include and widget attrs; the forms keep working through their buttons.

## References

- `context/foundation/prd-v2.md` — PK-07, US-07, Open Question 8
- `context/foundation/roadmap-future.md` — S-05
- `entries/forms.py:32-38`, `entries/forms.py:294-300`
- `entries/templates/entries/_capture_form.html:1-5`, `entries/templates/entries/_follow_up_form.html:14-18`
- `context/changes/free-text-proposal-correction/plan.md` — Phase 2 §1 (correction field), §3 (review partial „Popraw” submit); `context/changes/multi-entry-text-capture/plan.md` — Phase 3 (per-proposal correction)
- `entries/views.py:141-197` (follow-up answer/skip)
- `family_notes/templates/base.html:35`
- `context/foundation/test-plan.md:87`
- Related slice: `context/changes/mobile-classification-progress/plan.md` — Critical Implementation Details, Timing & lifecycle (shared `aria-busy` busy-form contract; S-06 cancels offline submits)

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Enter-to-Submit Behavior

#### Automated

- [x] 1.1 Form/view tests prove the capture `text`, follow-up `answer` and review `correction` textareas render `data-enter-submit` and `enterkeyhint="send"` (the correction box additionally carrying S-03's `data-enter-submitter`), while review, create and edit `content` textareas do not. — 3d13573
- [x] 1.2 View tests prove the capture page (empty, question, proposal states) and the DEBUG state gallery include the `js/enter-submit.js` script tag, and each opted-in field renders the hint copy in a `hidden` `data-enter-hint` element with `id="<auto_id>-enter-hint"`. — 3d13573
- [x] 1.3 A test proves `js/enter-submit.js` is resolvable through Django's static files finders. — 3d13573
- [x] 1.11 Review-form tests (proposal, follow-up-highlight, `correction_failed` and confirm-invalid states, plus the S-04 batch review if present) prove Enter there can never post to `entries:confirm`: every `data-enter-submit` field inside a form whose action is `entries:confirm` carries a `data-enter-submitter` id that resolves to a submit button in the same form with `formaction` equal to `reverse('entries:correct')` (batch: `name="action" value="correct-<i>"`, id `e{i}-correct-submit`); no field points at „Zapisz wpis”. — 3d13573
- [x] 1.4 Focused tests pass: `uv run python manage.py test entries.tests.test_capture_views entries.tests.test_follow_up_views entries.tests.test_correction_views entries.tests.test_states_view entries.tests.test_entry_forms`. — 3d13573
- [x] 1.5 Django checks pass: `uv run python manage.py check`. — 3d13573

#### Manual

- [ ] 1.6 Desktop Chrome: Enter on the capture box submits; Shift+Enter inserts a newline; Enter on empty or whitespace-only text does nothing; holding Enter posts only once.
- [ ] 1.7 Desktop Chrome: in the follow-up question, Enter performs "Dalej" (the answer is classified), never "Pomiń".
- [ ] 1.8 Android Chrome with Gboard: the keyboard shows a send action; typing Polish diacritics by long press and swipe typing never submits mid-word; the send key submits.
- [ ] 1.9 With JavaScript disabled, all opted-in forms still submit only through their buttons, Enter inserts a newline, and no Enter hint is visible.
- [ ] 1.10 Review, structured create and edit forms: Enter in "Tytuł" still inserts a newline and does not save.
- [ ] 1.12 Review form: Enter in „Popraw opis” runs „Popraw” (the revised proposal is shown), no entry is saved, and an empty correction box ignores Enter.

### Phase 2: Regression and Release Verification

#### Automated

- [x] 2.1 Follow-up tests prove a POST without `action` is answered via the backend and a POST with `action=skip` skips without a backend call.
- [x] 2.2 Full test suite passes: `uv run python manage.py test`.
- [x] 2.3 Django checks pass: `uv run python manage.py check`.
- [x] 2.4 Migration drift check passes: `uv run python manage.py makemigrations --check --dry-run`.
- [x] 2.5 Static collection includes the script: `DJANGO_STATIC_ROOT=$(mktemp -d) uv run python manage.py collectstatic --noinput` lists `js/enter-submit.js`.

#### Manual

- [ ] 2.6 After deployment, on the production capture page in Chrome on Android, Enter/send submits an instruction end to end through review and save.
