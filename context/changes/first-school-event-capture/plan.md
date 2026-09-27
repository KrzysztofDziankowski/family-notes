# First School Event Capture Implementation Plan

## Overview

Deliver roadmap slice S-01 (US-01, FR-001–FR-005, FR-008): an active parent opens `/entries/new/`, types one natural-language instruction, reviews the classified proposal as an editable form, corrects it if needed, confirms, and the application saves exactly one family `Entry` and shows it back with a confirmation. This introduces the first product model (`Entry`) — shaped so S-05 can reuse it for EduVulcan entries saved without confirmation — and the first shared UI base (vendored Pico CSS, project tokens, `base.html`).

## Current State Analysis

- Classification is done and transient. `classify_for_parent()` (`entries/classification/service.py:61`) authorizes an active parent, sends only text/names/date/locale, and returns `ParentClassification(result, member)` where `result` is a `ClassificationProposal`, `ClassificationFollowUp` or `ClassificationUnavailable` (`entries/classification/types.py:85-124`). It never writes rows.
- The `entries` app (`entries/apps.py`) has no `models.py`, no migrations, no views, no URLs.
- Access helpers exist: `get_active_membership`, `is_parent`, `scope_queryset_to_family` (`family_access/access.py:6-36`). `FamilyMember` has `display_name`, `role`, `is_active` (`family_access/models.py:19`).
- UI: `/` is a public placeholder with inline CSS (`family_notes/templates/family_notes/home.html:7-62`); `account_status.html` is unstyled English. No base template, no static assets, no `STATICFILES_DIRS`. `collectstatic` already runs on deploy (`scripts/deployment/family-notes-deploy:103`).
- Settings: `LANGUAGE_CODE = 'en-us'`, `TIME_ZONE = 'UTC'` (`family_notes/settings.py:287-290`). With UTC, `timezone.localdate()` is the wrong reference day for relative dates ("w poniedziałek", "jutro") between 00:00 and 01:00/02:00 Polish time.
- Timing: classification deadline 25 s (`family_notes/settings.py:255`) sits inside the production Gunicorn timeout (`--workers 2 --timeout 45`, `context/changes/deployment/mikrus-runbook.md:445`) and nginx `proxy_read_timeout 50s` (`context/changes/deployment/mikrus-runbook.md:498`), so a synchronous request/response flow meets the 30-second NFR.
- `family_notes` is not an app for static discovery (`family_notes/apps.py` subclasses `AdminConfig`), so project-wide static files need `STATICFILES_DIRS`, mirroring the existing template `DIRS`.
- Lessons: code in English; user-facing and OpenAI-bound text in Polish; commits prefixed `feat(first-school-event-capture):`.
- F-04 (`automation-token-access`, in planning) adds `family_access 0002`, and in its Phase 3 `entries/migrations/0002_inboundnotification.py`, which depends on this change's `entries/migrations/0001_initial.py`. Keep the name `0001_initial` stable.

## Desired End State

- An active parent at `/entries/new/` submits text; within the classification deadline they see an editable proposal (type, title/content, date, optional time, assigned member) and can correct and confirm it.
- Confirm re-validates every value server-side, saves one `Entry` for the parent's family with `source = manual`, and redirects to `/entries/new/?saved=<pk>`, which shows "Dodano wpis" with the saved values and an empty capture field ready for the next instruction.
- Repeating the same Confirm POST (double tap, back + resubmit) shows the already-saved entry and never creates a second row.
- Follow-up and most unavailable outcomes still let the parent save through a prefilled form; nothing is ever stuck.
- Children get 403, users without an active membership get 403, anonymous users are redirected to login; a parent can never see or assign another family's data.
- US-01 passes as an automated acceptance test: "Michał ma w poniedziałek sprawdzian z biologii o skórze" entered on 2026-09-19 yields a proposal for Michał dated 2026-09-21 and, after confirm, a saved calendar entry shown as added.
- All pages extending `base.html` use vendored Pico CSS plus a token stylesheet; a DEBUG-only kitchen-sink page renders every capture state and has been screenshotted at phone width.

### Key Discoveries:

- `ClassificationProposal`/`FollowUp` expose `entry_type`, `content`, `date`, `time`, `school_item`, `member_name`; `ParentClassification.member` is the locally resolved `FamilyMember` (`entries/classification/service.py:48-57`) — prefill from `member`, never from the name string.
- `SchoolItemKind` fixes each kind's `entry_type` and `required_fields` (`entries/classification/types.py:36-65`); reuse it for confirm-time validation instead of duplicating rules.
- `MAX_SUBMITTED_TEXT_LENGTH = 2000` (`entries/classification/service.py:45`) — reuse as the capture field and content limit.
- Test fixtures to reuse: `FamilyFixtureMixin` (`entries/tests/test_classification_service.py:73`) and the scripted OpenAI transport helpers (`entries/tests/test_openai_backend.py`, used by `entries/tests/test_classification_acceptance.py`).
- `family_notes/tests.py:14` asserts the English home headline — home stays untouched, so that test is unaffected.

## What We're NOT Doing

- No conversational follow-up question (S-04). S-01 only highlights missing fields in the prefilled form.
- No entry list, edit, or delete UI (S-02) and no child view (S-03). The child placeholder is a 403, not a page.
- No EduVulcan intake, token route, notification id or dedup-by-content fields (S-05). The model only carries the `source` marker (with the `eduvulcan` choice) and does not store a confirmation flag.
- No persistence of the submitted instruction, proposals, or drafts: no draft rows, no session copy, no logging of text.
- No change to `/` (public placeholder) or `LOGIN_REDIRECT_URL`; capture is reached at `/entries/new/` and linked from account status.
- No restyle of `home.html`; only the new capture views and `account_status.html` adopt `base.html`.
- No screenshot test harness; the visual gate is a manual screenshot of the kitchen sink.
- No CSS build step, no JavaScript framework, no CDN request from family pages.
- No tags, priorities, or recurring events.

## Implementation Approach

Build bottom-up so each layer is testable alone: the model and a family-scoped save service first, then the global UI contract (tokens before the view), then the capture flow on top, then the visual gate. The flow is stateless between steps: classification output becomes the initial data of an editable review form; the confirm POST is untrusted input that is fully re-validated (family-scoped member queryset, date rules, school-item rules) before the save service writes a row. A random `submission_key` generated when the review form is rendered and stored uniquely on the entry makes Confirm idempotent without storing any draft.

## Critical Implementation Details

- **Idempotent confirm under a race**: the save service must create inside `transaction.atomic()` and, on `IntegrityError` for `submission_key`, re-fetch the existing row *scoped to the parent's family*. A key that exists in another family (only possible by tampering) makes the service raise `ValidationError`; the confirm view re-renders the review form with a fresh `submission_key` and never returns the foreign entry. A repeat POST with the same key but edited values does not update the saved entry: first save wins, and the saved panel always shows the stored values, so the parent sees what was actually saved.
- **Reference date**: pass `timezone.localdate()` as `reference_date` only after `TIME_ZONE` is `Europe/Warsaw`; otherwise "Monday" is computed from the UTC date around midnight.
- **School item vs corrected type**: if the parent changes `entry_type` away from `school_item.entry_type`, drop the school item before validation and saving. The parent's correction wins and no stale kind rules apply. Otherwise enforce the kind's `required_fields`.

## Phase 1: Entry Model and Save Service

### Overview

Introduce the `Entry` table and one auditable, family-scoped write path that later slices (S-02 edits, S-05 intake) can extend.

### Changes Required:

#### 1. Entry model

**File**: `entries/models.py`

**Intent**: Persist a family entry with exactly the fields classification and US-01 need, open to S-05 (source marker, no confirmation state).

**Contract**: `Entry` fields: `family` (FK `Family`, CASCADE), `entry_type` (choices from `EntryType` values: todo / calendar_event / note), `content` (TextField, non-blank, ≤ 2000 enforced by forms/service), `date` (DateField, null), `time` (TimeField, null), `assigned_member` (FK `FamilyMember`, null, RESTRICT, `related_name='assigned_entries'`), `school_item` (CharField, choices from `SchoolItemKind` values, blank), `source` (CharField choices `manual` / `eduvulcan`, default `manual`), `created_by` (FK `FamilyMember`, null, SET_NULL, `related_name='created_entries'`), `submission_key` (UUIDField, null, unique), `created_at`, `updated_at`. DB `CheckConstraint`: `entry_type != calendar_event OR date IS NOT NULL`. Index on `(family, date)`. `__str__` returns a non-content label (type + pk) so text never leaks into admin logs or tracebacks. Polish `verbose_name`s for admin.

#### 2. Migration

**File**: `entries/migrations/0001_initial.py`

**Intent**: Create the table; additive only.

**Contract**: Generated by `makemigrations entries`; depends on `family_access` 0001 (not on F-04's 0002).

#### 3. Save service

**File**: `entries/services.py`

**Intent**: Single write path for a parent-confirmed entry that re-checks authorization and family scope independently of the view.

**Contract**: `save_confirmed_entry(user, *, entry_type, content, date, time, assigned_member, school_item, submission_key) -> tuple[Entry, bool]` (entry, created). Raises `PermissionDenied` unless `is_parent(get_active_membership(user))`. Raises `ValidationError` if `assigned_member` is not an active member of the parent's family, or if calendar-event/school-item required fields are missing (defence in depth; the form checks first). Sets `family` and `created_by` from the membership and `source = manual`. Idempotent on `submission_key` per Critical Implementation Details: an existing key in the same family returns `(existing entry, False)` unchanged; a key owned by another family raises `ValidationError`. Decorated with `sensitive_variables('content')`.

#### 4. Admin

**File**: `entries/admin.py`

**Intent**: Let the operator inspect saved entries until S-02 exists, without exposing content in list views.

**Contract**: Register `Entry` with `list_display` of type, date, assigned member, source, created_at (no content column); `list_filter` on type/source/family; read-only `submission_key`, `created_by`, `source`.

### Success Criteria:

#### Automated Verification:

- Migration is present and consistent: `uv run python manage.py makemigrations --check --dry-run`
- Django checks pass: `uv run python manage.py check`
- Model tests pass: calendar event without date is rejected by the DB constraint; note/todo without date are accepted; an `eduvulcan` entry with no `submission_key` and no `created_by` saves (S-05 openness)
- Service tests pass: active parent creates an entry with `source=manual`, `family` and `created_by` set; child, inactive parent, inactive family, no membership and anonymous raise `PermissionDenied` and write nothing; assigning another family's member or an inactive member raises `ValidationError` and writes nothing
- Idempotency tests pass: the same `submission_key` twice returns `(same entry, False)` with one row; a second call with the same key but different values returns the original, unchanged entry; a key belonging to another family raises `ValidationError` and returns nothing
- `Entry.__str__` and `repr` contain no content text (sentinel test)
- Delete behaviour: deleting a Family with assigned entries cascades them; deleting an assigned FamilyMember or its User raises `RestrictedError` and leaves the entry
- Full suite passes: `uv run python manage.py test`

#### Manual Verification:

- Entries appear in `/admin/` for a superuser with no content column in the list view

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 2: UI Foundation (Pico CSS, Tokens, Base Template)

### Overview

Establish the global UI contract before the view: one vendored framework, one token source, one base template, Polish locale and Polish local time.

### Changes Required:

#### 1. Vendored Pico CSS

**File**: `family_notes/static/vendor/pico/pico.min.css`, `family_notes/static/vendor/pico/SOURCE.md`

**Intent**: Classless styling for plain Django form HTML without a build step or third-party request (adds a vendored dependency — the repo has no existing design system).

**Contract**: The current Pico CSS v2 release `pico.min.css`, unmodified, with its license banner kept. `SOURCE.md` names the exact version, download URL, license (MIT), and date vendored.

#### 2. Token stylesheet

**File**: `family_notes/static/css/tokens.css`

**Intent**: The single source of project design values; overrides Pico's CSS variables so views never hard-code colours.

**Contract**: First line comment names the source of values ("colours and font stack taken from `family_notes/templates/family_notes/home.html` placeholder"). Defines semantic custom properties on `:root` (`--fn-color-bg`, `--fn-color-text`, `--fn-color-muted`, `--fn-color-accent` = `#2f6f5e`, `--fn-color-danger`, `--fn-color-success`, `--fn-font-sans`, spacing/radius as needed) and maps them onto Pico variables (`--pico-primary`, `--pico-background-color`, `--pico-font-family`, …). Forces light scheme (`color-scheme: light`), matching the current app; dark mode is out of scope.

#### 3. Base template

**File**: `family_notes/templates/base.html`

**Intent**: Shared page shell for every product view.

**Contract**: `<html lang="pl">`, charset + viewport meta, `{% load static %}` links to Pico then `tokens.css`, `<title>{% block title %}{% endblock %} | FamilyNotes</title>`, `<main class="container">{% block content %}{% endblock %}</main>`, a small header nav block (FamilyNotes, "Konto", "Wyloguj"), no JavaScript.

#### 4. Settings

**File**: `family_notes/settings.py`

**Intent**: Serve project static files, render Polish framework strings, and compute local dates in Poland.

**Contract**: `STATICFILES_DIRS = [BASE_DIR / 'family_notes' / 'static']`; `LANGUAGE_CODE = 'pl'`; `TIME_ZONE = 'Europe/Warsaw'` (`USE_TZ` stays `True`; stored datetimes remain UTC).

#### 5. Account status on the base

**File**: `family_access/templates/family_access/account_status.html`

**Intent**: Move the existing page onto `base.html` with Polish copy, and give parents the entry point to capture.

**Contract**: Extends `base.html`; Polish labels ("Status konta", "Rola"); for an active parent shows a primary link "Dodaj wpis" to `entries:capture`. Existing `AccountStatusRouteTests` are updated to the Polish strings.

### Success Criteria:

#### Automated Verification:

- `uv run python manage.py check` passes and `uv run python manage.py collectstatic --noinput --dry-run` finds `vendor/pico/pico.min.css` and `css/tokens.css`
- Account status tests pass with Polish strings; parent sees the "Dodaj wpis" link, child and unconfigured user do not
- A settings test asserts `TIME_ZONE == 'Europe/Warsaw'` and `LANGUAGE_CODE == 'pl'`
- Full suite passes: `uv run python manage.py test`

#### Manual Verification:

- `/account/` renders with Pico styling and the accent colour at 360 px width in Chrome device mode, with no horizontal scroll
- Login pages (allauth) render in Polish

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 3: Capture Flow (Classify → Review/Correct → Confirm)

### Overview

The parent-facing flow at `/entries/new/`, built on Phases 1–2 and the F-02 service.

### Changes Required:

#### 1. Forms

**File**: `entries/forms.py`

**Intent**: One form for the instruction and one for the reviewable proposal. The review form treats every posted value as untrusted.

**Contract**:
- `CaptureForm`: `text` (Textarea, required, stripped, `max_length=MAX_SUBMITTED_TEXT_LENGTH`, Polish label "Co trzeba zapisać?", `autofocus`).
- `EntryReviewForm(membership, …)`: `entry_type` (ChoiceField with Polish labels: Zadanie / Wydarzenie / Notatka), `content` (CharField, required, ≤ 2000, label "Tytuł"), `date` (DateField, optional, widget `DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')`), `time` (TimeField, optional, widget `TimeInput(attrs={'type': 'time'}, format='%H:%M')`) — the explicit formats are required: under `LANGUAGE_CODE='pl'` Django renders `21.09.2026` and `08:30:00`, which `<input type=date>`/`<input type=time>` show as empty or reject, `assigned_member` (ModelChoiceField over `scope_queryset_to_family(FamilyMember.objects.filter(is_active=True), membership)`, optional, empty label "Cała rodzina"), `school_item` (hidden, optional, must be a `SchoolItemKind` value), `submission_key` (hidden UUID, required). `clean()`: drop `school_item` when `entry_type` differs from its kind's type; require `date` for calendar events; enforce the remaining kind's `required_fields` (date / member). All error messages in Polish.
- A helper builds `EntryReviewForm` initial data plus a fresh `uuid4` `submission_key` from a `ParentClassification`, and returns the list of missing fields to highlight.

#### 2. Views

**File**: `entries/views.py`

**Intent**: Orchestrate the three steps without storing anything between them.

**Contract**:
- `capture` (`GET`/`POST` `entries/new/`, name `entries:capture`): `login_required`, then 403 unless `is_parent`. GET renders an empty `CaptureForm`. If `?saved=<pk>` is present, it looks the entry up with `scope_queryset_to_family` and shows the "Dodano wpis" panel. An unknown or other-family pk shows no panel and no error. POST validates `CaptureForm` and calls `classify_for_parent(request.user, text, reference_date=timezone.localdate())`, then renders the review state:
  - `ClassificationProposal` → review form prefilled, `member` preselected from `ParentClassification.member`.
  - `ClassificationFollowUp` → review form prefilled with the partial draft, missing fields marked as required (`AMBIGUOUS_MEMBER` → member field "Wybierz osobę").
  - `ClassificationUnavailable` with `INPUT_TOO_LONG` → `CaptureForm` error, text kept, no review form.
  - Any other `ClassificationUnavailable` → Polish notice ("Nie udało się teraz rozpoznać wpisu. Możesz zapisać go jako notatkę lub poprawić.") plus review form prefilled as `note` with `content` = submitted text.
- `confirm` (`POST` only `entries/confirm/`, name `entries:confirm`; other methods 405): same authorization. Binds `EntryReviewForm`. Invalid → re-render the review state with errors (same `submission_key`). `ValidationError` from the service (foreign key) → re-render the review state with a fresh `submission_key`. Valid → `save_confirmed_entry(...)` → `redirect(f"{reverse('entries:capture')}?saved={entry.pk}")`, for both created and already existing entries.
- Both views are decorated with `sensitive_post_parameters('text', 'content')` and log nothing about the text.

#### 3. URLs

**File**: `entries/urls.py`, `family_notes/urls.py`

**Intent**: Compose the app's routes in the project URLconf, following the existing include pattern.

**Contract**: `app_name = 'entries'`; `family_notes/urls.py` adds `path('entries/', include('entries.urls'))`.

#### 4. Templates

**File**: `entries/templates/entries/capture.html` (plus partials under `entries/templates/entries/_*.html` for the capture form, review form, notice, and saved panel)

**Intent**: Render the flow's states with Pico's semantic HTML and tokens only. No inline colours.

**Contract**: Extends `base.html`. States: `empty`, `proposal`, `follow_up`, `unavailable`, `invalid` (review form with errors), and `saved` (panel + empty capture form). The review form shows the date in an `<input type=date>` plus a human-readable Polish date next to it (e.g. "poniedziałek, 21 września 2026"). Buttons: "Rozpoznaj" (classify), "Zapisz wpis" (confirm), and "Zacznij od nowa" (link to `entries:capture`). Missing or invalid fields use `aria-invalid="true"` and a Polish helper text.

#### 5. Tests

**File**: `entries/tests/test_capture_views.py`, `entries/tests/test_entry_forms.py`

**Intent**: Prove access, validation, idempotency, failure fallbacks, privacy and US-01 end to end without network access.

**Contract**: Reuse `FamilyFixtureMixin`. Views take the classification backend through a patch point (patch `entries.views.classify_for_parent` or inject a recording backend); the US-01 acceptance case uses the real service with the scripted OpenAI transport from `test_openai_backend.py`. The reference day is pinned with `mock.patch('entries.views.timezone.localdate', return_value=date(2026, 9, 19))`; the repo has no freezegun/time-machine and none is added.

### Success Criteria:

#### Automated Verification:

- Access matrix: anonymous GET/POST → login redirect; child, no membership, inactive parent → 403 on both views; `GET entries/confirm/` → 405; no backend call and no row for any denied path
- US-01 acceptance: with `entries.views.timezone.localdate` patched to return 2026-09-19 and the scripted backend returning Michał / "Sprawdzian z biologii o skórze" / 2026-09-21, the review page preselects Michał, shows 2026-09-21 and the title; confirming creates one `calendar_event` entry for Michał, `source=manual`, and the redirected page shows "Dodano wpis" with the same values
- Correction: changing member, date, type and title on the review form saves the corrected values, not the classified ones
- Re-validation: a posted `assigned_member` from another family or inactive → form error, no row; calendar event without date → error; `school_item=test` with type still `calendar_event` and no member → error; `school_item=test` with type changed to `note` → saves with `school_item` cleared
- Follow-up: missing date renders the prefilled form with the date field marked invalid and saves after the parent fills it
- Unavailable: `TIMEOUT`/`DISABLED`/`UNKNOWN_MEMBER` render the notice and a `note` form containing the original text; `INPUT_TOO_LONG` renders a capture error with no review form
- Idempotency: posting the same confirm payload twice yields one row and both responses redirect to the same `?saved=<pk>`; re-posting the same key with an edited date keeps the first saved values and the saved panel shows them; a key owned by another family re-renders the review form with a new key and writes no row
- `?saved=<pk>` for another family's entry shows no panel and leaks no content
- Privacy: a log-capture test with a sentinel instruction proves the text appears in no log record across classify and confirm; the only rows written are the confirmed `Entry`
- Widget formats: under `LANGUAGE_CODE='pl'` the review form renders `value="2026-09-21"` for the date and `value="08:30"` for the time
- Django checks and migration check pass; full suite passes: `uv run python manage.py test`

#### Manual Verification:

- With `CLASSIFICATION_ENABLED` and a real key, on Chrome for Android (or device mode), entering "Michał ma w poniedziałek sprawdzian z biologii o skórze" returns a proposal within 30 s, and confirm shows "Dodano wpis"
- With classification disabled, the same text falls back to a saveable note
- Double-tapping "Zapisz wpis" on a phone creates one entry (checked in admin)

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 4: States Kitchen Sink and Screenshot Gate

### Overview

Render every capture state on one page from synthetic data and screenshot it at phone width as the visual gate.

### Changes Required:

#### 1. Kitchen-sink view

**File**: `entries/views.py`, `entries/urls.py`, `entries/templates/entries/states.html`

**Intent**: Show all partials side by side so visual regressions and missing states are visible in one screenshot.

**Contract**: `entries/_states/` (name `entries:states`) is always routed but the view raises `Http404` unless `settings.DEBUG` is true (checked per request so `override_settings` works in tests), and is limited to parents. It renders `empty`, `proposal`, `follow_up` (missing date and ambiguous member), `unavailable`, `invalid`, and `saved`, using unsaved synthetic objects (fictional names). It writes nothing to the database and makes no backend call. The same partials as `capture.html` are reused, not copied.

#### 2. Screenshot evidence

**File**: `context/changes/first-school-event-capture/screenshots/`

**Intent**: Keep the gate's evidence with the change.

**Contract**: Full-page PNGs of `/entries/_states/` at 360 px width, plus one of the real `/account/` page, all with synthetic data only.

### Success Criteria:

#### Automated Verification:

- With `DEBUG=False` `entries:states` returns 404; with `DEBUG=True` a parent gets 200 containing a marker for each of the six states, a child gets 403, and no `Entry` rows are created
- Full suite passes: `uv run python manage.py test`

#### Manual Verification:

- Kitchen-sink screenshot at 360 px shows all six states legibly: no horizontal scroll, invalid fields visibly marked, accent colour from tokens, Polish copy throughout
- Screenshots are committed under `context/changes/first-school-event-capture/screenshots/`

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Testing Strategy

### Unit Tests:

- Model constraint and S-05 openness (`eduvulcan`, no key, no creator).
- Save service: authorization matrix, family-scoped member check, idempotency, and race handling (simulate `IntegrityError`).
- `EntryReviewForm.clean()`: school-item/type interplay, calendar date rule, and the member queryset scoped to the family.

### Integration Tests:

- View flow via the Django test client: classify → review → confirm → saved panel.
- The US-01 acceptance case through the real service with the scripted OpenAI transport.
- Fallback branches for follow-up and unavailable results.
- Log-capture privacy test with a sentinel instruction.

### Manual Testing Steps:

1. Sign in as a parent and open `/account/`, then tap "Dodaj wpis".
2. Enter the US-01 sentence, check the proposal, change the date, confirm, and verify "Dodano wpis" shows the corrected date.
3. Sign in as a child and open `/entries/new/`; expect 403.
4. Disable classification, submit text, and save the fallback note.
5. Screenshot `/entries/_states/` at 360 px.

## Performance Considerations

The flow is synchronous: one classification call per submit, bounded by the 25 s application deadline, inside the 45 s Gunicorn and 50 s nginx timeouts. With 2 sync workers, one in-flight classification occupies half the capacity and two overlapping ones stall other requests; this is the existing infrastructure risk (`context/foundation/infrastructure.md`, concurrency row), not addressed in this slice. The idempotent confirm step keeps retries after a slow response from creating duplicates, a risk named in `context/foundation/infrastructure.md`. The `(family, date)` index serves S-02/S-03 listings later.

## Migration Notes

This adds one table (`entries 0001`) and no data migration. To roll back, unapply `entries 0001`, which drops saved entries. Do this only before real family data exists. Changing `TIME_ZONE`/`LANGUAGE_CODE` needs no data migration, because `USE_TZ=True` keeps stored datetimes in UTC.

## References

- Roadmap slice: `context/foundation/roadmap.md` (S-01, S-05 risk note)
- PRD: `context/foundation/prd.md` (US-01, FR-001–FR-005, FR-008, Business Logic)
- Change note: `context/changes/first-school-event-capture/change.md`
- Classification boundary: `context/archive/2026-09-24-classification-privacy-boundary/plan.md`, `entries/classification/service.py:61`
- Access helpers: `family_access/access.py:6-51`
- Test fixtures: `entries/tests/test_classification_service.py:73`, `entries/tests/test_openai_backend.py`
- Parallel change: `context/changes/automation-token-access/plan.md` (migration lives in `family_access`)

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Entry Model and Save Service

#### Automated

- [x] 1.1 Migration is present and consistent: `uv run python manage.py makemigrations --check --dry-run` — d594e66
- [x] 1.2 Django checks pass: `uv run python manage.py check` — d594e66
- [x] 1.3 Model tests pass: calendar event without date is rejected by the DB constraint; note/todo without date are accepted; an `eduvulcan` entry with no `submission_key` and no `created_by` saves (S-05 openness) — d594e66
- [x] 1.4 Service tests pass: active parent creates an entry with `source=manual`, `family` and `created_by` set; child, inactive parent, inactive family, no membership and anonymous raise `PermissionDenied` and write nothing; assigning another family's member or an inactive member raises `ValidationError` and writes nothing — d594e66
- [x] 1.5 Idempotency tests pass: the same `submission_key` twice returns `(same entry, False)` with one row; a second call with the same key but different values returns the original, unchanged entry; a key belonging to another family raises `ValidationError` and returns nothing — d594e66
- [x] 1.6 `Entry.__str__` and `repr` contain no content text (sentinel test) — d594e66
- [x] 1.7 Delete behaviour: deleting a Family with assigned entries cascades them; deleting an assigned FamilyMember or its User raises `RestrictedError` and leaves the entry — d594e66
- [x] 1.8 Full suite passes: `uv run python manage.py test` — d594e66

#### Manual

- [x] 1.9 Entries appear in `/admin/` for a superuser with no content column in the list view — d594e66

### Phase 2: UI Foundation (Pico CSS, Tokens, Base Template)

#### Automated

- [x] 2.1 `uv run python manage.py check` passes and `uv run python manage.py collectstatic --noinput --dry-run` finds `vendor/pico/pico.min.css` and `css/tokens.css` — 212054a
- [x] 2.2 Account status tests pass with Polish strings; parent sees the "Dodaj wpis" link, child and unconfigured user do not — 212054a
- [x] 2.3 A settings test asserts `TIME_ZONE == 'Europe/Warsaw'` and `LANGUAGE_CODE == 'pl'` — 212054a
- [x] 2.4 Full suite passes: `uv run python manage.py test` — 212054a

#### Manual

- [x] 2.5 `/account/` renders with Pico styling and the accent colour at 360 px width in Chrome device mode, with no horizontal scroll — 212054a
- [x] 2.6 Login pages (allauth) render in Polish — 212054a

### Phase 3: Capture Flow (Classify → Review/Correct → Confirm)

#### Automated

- [x] 3.1 Access matrix: anonymous GET/POST → login redirect; child, no membership, inactive parent → 403 on both views; `GET entries/confirm/` → 405; no backend call and no row for any denied path — 1df989d
- [x] 3.2 US-01 acceptance: with `entries.views.timezone.localdate` patched to return 2026-09-19 and the scripted backend returning Michał / "Sprawdzian z biologii o skórze" / 2026-09-21, the review page preselects Michał, shows 2026-09-21 and the title; confirming creates one `calendar_event` entry for Michał, `source=manual`, and the redirected page shows "Dodano wpis" with the same values — 1df989d
- [x] 3.3 Correction: changing member, date, type and title on the review form saves the corrected values, not the classified ones — 1df989d
- [x] 3.4 Re-validation: a posted `assigned_member` from another family or inactive → form error, no row; calendar event without date → error; `school_item=test` with type still `calendar_event` and no member → error; `school_item=test` with type changed to `note` → saves with `school_item` cleared — 1df989d
- [x] 3.5 Follow-up: missing date renders the prefilled form with the date field marked invalid and saves after the parent fills it — 1df989d
- [x] 3.6 Unavailable: `TIMEOUT`/`DISABLED`/`UNKNOWN_MEMBER` render the notice and a `note` form containing the original text; `INPUT_TOO_LONG` renders a capture error with no review form — 1df989d
- [x] 3.7 Idempotency: posting the same confirm payload twice yields one row and both responses redirect to the same `?saved=<pk>`; re-posting the same key with an edited date keeps the first saved values and the saved panel shows them; a key owned by another family re-renders the review form with a new key and writes no row — 1df989d
- [x] 3.8 `?saved=<pk>` for another family's entry shows no panel and leaks no content — 1df989d
- [x] 3.9 Privacy: a log-capture test with a sentinel instruction proves the text appears in no log record across classify and confirm; the only rows written are the confirmed `Entry` — 1df989d
- [x] 3.10 Widget formats: under `LANGUAGE_CODE='pl'` the review form renders `value="2026-09-21"` for the date and `value="08:30"` for the time — 1df989d
- [x] 3.11 Django checks and migration check pass; full suite passes: `uv run python manage.py test` — 1df989d

#### Manual

- [x] 3.12 With `CLASSIFICATION_ENABLED` and a real key, on Chrome for Android (or device mode), entering "Michał ma w poniedziałek sprawdzian z biologii o skórze" returns a proposal within 30 s, and confirm shows "Dodano wpis" — 1df989d
- [x] 3.13 With classification disabled, the same text falls back to a saveable note — 1df989d
- [x] 3.14 Double-tapping "Zapisz wpis" on a phone creates one entry (checked in admin) — 1df989d

### Phase 4: States Kitchen Sink and Screenshot Gate

#### Automated

- [x] 4.1 With `DEBUG=False` `entries:states` returns 404; with `DEBUG=True` a parent gets 200 containing a marker for each of the six states, a child gets 403, and no `Entry` rows are created — 9c9c380
- [x] 4.2 Full suite passes: `uv run python manage.py test` — 9c9c380

#### Manual

- [x] 4.3 Kitchen-sink screenshot at 360 px shows all six states legibly: no horizontal scroll, invalid fields visibly marked, accent colour from tokens, Polish copy throughout — 9c9c380
- [x] 4.4 Screenshots are committed under `context/changes/first-school-event-capture/screenshots/` — 9c9c380
