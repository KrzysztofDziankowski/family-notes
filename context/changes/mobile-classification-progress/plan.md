# Mobile Classification Progress Implementation Plan

## Overview

Implement roadmap-future slice S-06 (PK-06, US-06). Today a parent who taps "Rozpoznaj" on a phone sees only the browser's own loading state while the server waits for the classification provider. After this slice:

- FamilyNotes is an installable **Progressive Web App** on Chrome for Android. It has a web app manifest, icons, standalone display, a minimal service worker and a Polish offline fallback page, layered on the existing server-rendered site.
- The capture page itself (capture, follow-up answer and S-03's „Popraw” correction on the review form) shows a visible, accessible "classification is running" indicator and says when it takes longer than usual. It handles lost connectivity and a stalled request with clear Polish copy and a safe retry. This matters even more in standalone mode, where there is no browser loading bar.

Completion and failure feedback stay the existing server-rendered outcomes: review, follow-up question, or the "could not recognize" notice. Push notifications, background sync and a native app are not part of this slice.

### Decisions

Owner decisions were made on 2026-10-04 and answer PRD-v2 Open Question 7 and release Questions 1, 12 and 20. Plan-review owner decisions were applied on 2026-10-04. Items marked "assumed" are planning defaults that stand unless the owner objects. Confirmed slice order: S-01, S-02, S-20, S-03, S-04, S-05, S-06, S-07, S-08, S-09, S-17, S-14, S-15, S-16.

1. **Mobile experience = an installable PWA on top of the existing site** (owner-confirmed 2026-10-04). It has a web app manifest, icons, `display: standalone`, a minimal service worker and an offline fallback page. There is no native app. Chrome on Android is the verified target. (Q7)
2. **No push or system notifications in this slice** (owner-confirmed 2026-10-04). Push is a possible future slice. The service worker has no `push`/`notificationclick` handlers and requests no notification permission. (Q7)
3. **Classification stays synchronous inside the submit request, and closing the page abandons it** (owner-confirmed 2026-10-04). There is no server-side job or queue, and no status is reported later. Continuing after close would need the instruction text stored server-side, which the classification-purpose guardrail and the hard rule against secondary storage exclude. The indicator says "Nie zamykaj tej strony". (Q7)
4. **The service worker caches only static shell assets and the offline fallback page** (owner-confirmed 2026-10-04). It never caches family data, authenticated HTML, API responses or classification text. It ignores every non-GET request, so the classification POST goes straight to the network. GET navigations are network-only, and the cached offline page is served only when the network fails. Nothing is written to the cache at runtime.
5. **Ship without feature flags and without a data backfill** (owner-confirmed 2026-10-04). Rollback is the code revert described in Migration Notes. (Q1, Q20)
6. **No Playwright/E2E tests in this slice** (owner-confirmed 2026-10-04). Verification is Django tests (rendered markup, headers, manifest JSON, service worker source, static resolution) plus manual checks on a real Android phone. E2E coverage may be added later. (Q12)
7. **S-05 `enter-text-submission` lands before S-06** (owner-confirmed 2026-10-04). S-06 keeps the shared busy contract: it marks an in-flight form `aria-busy="true"`, and S-05 skips busy forms. S-05 records a form as submitted only when the `submit` event was not cancelled, so S-06's offline `preventDefault()` leaves Enter usable. `capture.html`/`states.html` will already carry S-05's `extra_body` script, and S-06 adds its own script next to it.
8. **Offline at submit time blocks the submission and keeps the typed text** (assumed; stands unless the owner objects). Connectivity lost while waiting shows a message. A request with no response after *classification deadline + 10 s* is reported as stalled and offers "Spróbuj ponownie", which resubmits the same form with the original submitter. Capture, answer and correction are read-only (`entries/classification/service.py:18-19`; S-03 writes nothing before confirm), so resubmitting is safe. There is no offline queue. (Q7)
9. **Indicator type: an activity indicator, not a percentage** (assumed; stands unless the owner objects). It is a spinner on the submit button and a status panel with an elapsed-seconds counter, and it switches to "dłużej niż zwykle" after one provider attempt timeout (`CLASSIFICATION_ATTEMPT_TIMEOUT_SECONDS`, 10 s default). Past that point the provider is retrying. No real progress signal exists. The stalled threshold uses the existing `CLASSIFICATION_DEADLINE_SECONDS` setting. (Q7)
10. **Indicator scope: every submission that calls the provider** (owner-confirmed 2026-10-04): capture ("Rozpoznaj"), follow-up answer ("Dalej") and S-03's correction („Popraw”, and S-04's per-proposal `correct-<i>` submits if present). The indicator is submitter-scoped, not form-scoped: it does not cover "Pomiń" or "Zapisz wpis", even though „Zapisz wpis” shares the review form with „Popraw”. (Q7)
11. **PWA identity** (owner-confirmed 2026-10-04): `name`/`short_name` "FamilyNotes", `lang: "pl"`, `start_url: "/"`, `scope: "/"`, `id: "/"`. Theme and background colours mirror `--fn-color-accent`/`--fn-color-bg` (`family_notes/static/css/tokens.css:13-19`). The icon is a simple placeholder "FN" monogram (SVG source plus PNG exports). Installation uses Chrome's own menu or install banner, with no custom in-app install button. Other browsers (iOS Safari, desktop) get the manifest and `apple-touch-icon` on a best-effort basis and are not verified.

## Current State Analysis

- `capture` and `answer` are synchronous function views that call the provider inside the POST and render the next state (`entries/views.py:94-138`, `entries/views.py:141-197`). The page offers nothing while waiting. That is the "loading page" recorded in the PRD (`context/foundation/prd-v2.md:115-121`).
- The provider call is bounded by an application deadline of 25 s with a 10 s attempt timeout and at most one retry (`family_notes/settings.py:326-330`, `entries/classification/openai_backend.py:206-234`). Gunicorn runs 2 sync workers with `--timeout 45`, and nginx has `proxy_read_timeout 50s` (`context/changes/deployment/mikrus-runbook.md:445`, `context/changes/deployment/mikrus-runbook.md:501-508`).
- Failure feedback already exists. Provider failures render the review form with `UNAVAILABLE_NOTICE` (`entries/views.py:68-70`, `entries/views.py:132-138`), and answer failures use `ANSWER_UNAVAILABLE_NOTICE` (`entries/views.py:74`, `entries/views.py:191-196`). Notices use `role="status"` (`entries/templates/entries/_notice.html:1`).
- No PWA pieces exist. `base.html` `<head>` has only charset, viewport, title and two stylesheets (`family_notes/templates/base.html:3-9`). Its `{% block extra_body %}` is empty (`family_notes/templates/base.html:35`). Static sources contain only `css/` and `vendor/pico/`. S-05 adds the first script, `js/enter-submit.js`, before this slice.
- Root URLs are composed in `family_notes/urls.py:32-41`. Project-wide views (`home`, `healthz`) live in `family_notes/views.py:14-36`. No middleware forces login (`family_notes/settings.py:209-219`), so new root views are anonymous unless they opt in.
- **Production static and headers.** `STATIC_URL = 'static/'` uses default (non-hashed) storage (`family_notes/settings.py:456-458`). nginx serves `/static/` from `/var/www/family-notes/static/` with `expires 1h` and proxies everything else to Gunicorn (`context/changes/deployment/mikrus-runbook.md:495-508`). Mikrus terminates public HTTPS, so the site is a secure context, and `SECURE_SSL_REDIRECT` defaults on in production (`family_notes/settings.py:171-175`). **No Content-Security-Policy is configured** in Django (`family_notes/settings.py:209-219`; Django 5.2 has no built-in CSP) or in nginx (`context/changes/deployment/mikrus-runbook.md:487-509`). `SecurityMiddleware` sends `X-Content-Type-Options: nosniff` by default, so the service worker and manifest must be served with correct MIME types.
- Pico renders a spinner for any non-input element with `aria-busy="true"` (`family_notes/static/vendor/pico/pico.min.css`). Shared panel classes `fn-panel`, `fn-panel--notice` and `fn-actions` exist (`family_notes/static/css/tokens.css:83-127`).
- The quality gate rejects hex/`rgb(`/`style=` literals in `base.html` and other cleaned templates (`scripts/hooks/quality_gate.py:58-72`). A `<meta name="theme-color" content="#…">` in `base.html` would be flagged, so theme colour lives in the manifest JSON built in Python.
- Google sign-in exists through allauth (`family_notes/settings.py:205-206`, `family_notes/settings.py:429`). In standalone mode the Google OAuth pages are out of scope and open in a Chrome Custom Tab.
- The follow-up form has a default "Dalej" button and a `name="action" value="skip"` "Pomiń" button (`entries/templates/entries/_follow_up_form.html:14-18`). Skip never calls the provider (`entries/views.py:170-176`).
- S-03 (`free-text-proposal-correction`, lands before this slice) adds to the review form a „Popraw” submit with `formaction="{% url 'entries:correct' %}"` and `formnovalidate`, which makes one provider call under the same deadline. „Zapisz wpis” stays the review form's default submit and posts to `entries:confirm` (S-03 plan, Phase 2 §2–§3). S-04 adds per-proposal `name="action" value="correct-{i}"` submits with `id="e{i}-correct-submit"` in the batch review (S-04 plan, Phase 3). Each correction textarea carries `data-enter-submitter="<button id>"`, and S-05 submits with `form.requestSubmit(document.getElementById(<that id>))` on Enter, so `event.submitter` is the „Popraw” button.
- The DEBUG-only state gallery renders capture partials from synthetic data (`entries/views.py:249`, `entries/templates/entries/states.html:8-27`).

## Desired End State

On Chrome for Android, the parent can install FamilyNotes from the browser menu ("Zainstaluj aplikację" / "Dodaj do ekranu głównego"). It then opens full-screen from a home-screen icon at `/`, which sends each role to its home page. With no network, any navigation shows a styled Polish "Brak połączenia" page instead of the browser's error page, and the service worker stores no family data. The browser's own HTTP cache and back/forward cache may still keep authenticated pages as they do today; this is an accepted limitation (owner-confirmed 2026-10-04), and no `no-store` headers are added.

After tapping "Rozpoznaj", "Dalej" or „Popraw”, installed or in the browser, the parent immediately sees on the page:
- a spinner on the button and a status panel with "Rozpoznaję wpis…", an elapsed-seconds counter and "Nie zamykaj tej strony";
- after 10 s, "Trwa to dłużej niż zwykle…";
- if the device is offline when submitting, a "no connection" message and an unsent, intact text;
- if the connection drops while waiting, a "connection lost" message may flash, but Chrome usually aborts the form-POST navigation and shows its own error page (the worker deliberately ignores POSTs). Pressing Back restores the capture page, not busy, with the typed text, and resubmitting works. The in-page `connection_lost` state remains for requests that merely hang;
- if nothing arrives after deadline + 10 s, a "no server response" message with a "Spróbuj ponownie" button.

When the server responds, the next page shows the existing completion or failure feedback. Without JavaScript or service worker support the flow is exactly as today. After Back navigation the page is never left stuck in the busy state.

### Key Discoveries:

- The submit button cannot be `disabled` inside the `submit` handler. Doing that before the browser builds the form data set drops the submitter, and disabling a field would drop its value. Busy state uses `aria-busy`/`aria-disabled` and a JS guard instead (see Critical Implementation Details).
- `event.submitter` identifies the button that was used. It is `null` for `form.requestSubmit()` with no submitter (S-05 Enter in capture/follow-up, and a retry of such a submit), so every access must be null-safe. Provider-calling buttons carry `data-classification-submit`; "Pomiń" and „Zapisz wpis” do not.
- `form.requestSubmit()` with no submitter ignores „Popraw”'s `formaction` and would post the review form to `entries:confirm`, **saving** the entry. The retry must therefore call `form.requestSubmit(<original submitter>)`.
- The stalled threshold derives from `CLASSIFICATION_DEADLINE_SECONDS` (`family_notes/settings.py:326`), and the slow threshold from `CLASSIFICATION_ATTEMPT_TIMEOUT_SECONDS` (`family_notes/settings.py:327-329`), not from hard-coded numbers.
- S-05 submits through `form.requestSubmit()` (or `requestSubmit(<Popraw>)` in the correction box), which fires the same `submit` event, so Enter-submits get the indicator for free. S-05 skips forms marked `aria-busy="true"` (S-05 plan, "Critical Implementation Details — Timing & lifecycle").
- A live region that becomes rendered at the same moment as its content is often not announced (TalkBack/Chrome, NVDA). The `role="status"` region must therefore always be rendered, never under a `hidden` ancestor; only the state blocks inside it are toggled.
- **Service worker scope.** A worker's maximum scope is the directory of its script URL. Serving it from `/static/…` would cap the scope at `/static/`. That would need a `Service-Worker-Allowed: /` header added in nginx, and the 1 h static `expires` would still apply. Serving it from a Django route at `/sw.js` gives scope `/` with no extra header and no nginx change, because `/sw.js` falls through `location /` to Gunicorn (`context/changes/deployment/mikrus-runbook.md:501-508`).
- **Manifest scope.** A manifest under `/static/` would default its scope to `/static/`. The manifest is served from `/manifest.webmanifest` and sets explicit `scope: "/"`, `start_url: "/"` and `id: "/"`.
- A service worker that calls `respondWith` for a POST navigation could swap the classification response for the offline page on a network error and break the in-page progress flow. The worker therefore returns early for every non-GET request.

## What We're NOT Doing

- No push notifications, notification permission prompt, or `push`/`notificationclick` handlers (future slice).
- No Background Sync, Periodic Sync, offline submission queue, or IndexedDB/Cache storage of form text.
- No native app, Trusted Web Activity, or app-store listing.
- No caching of family data, authenticated HTML pages, `/api/` or `/admin/` responses, or classification text; no runtime `cache.put` of any response.
- No server-side background job, task queue, polling endpoint, WebSocket/SSE, or storage of instruction text or results between requests.
- No reporting of a result after the page was closed.
- No fake percentage progress bar.
- No change to the provider call, timeouts, retry policy or latency.
- No indicator for "Pomiń", "Zapisz wpis", or management forms.
- No `Cache-Control: no-store` or other HTTP caching change for authenticated pages (owner-confirmed 2026-10-04: the browser's own cache is an accepted limitation).
- No `beforeunload` confirmation dialog; no custom install button (`beforeinstallprompt`).
- No feature flag, data backfill, JavaScript build tooling, or Playwright setup.
- No Content-Security-Policy introduction (none exists today; see Critical Implementation Details for the directives a future CSP needs).

## Implementation Approach

The work comes in three layers, all server-rendered first:

1. **In-page progress.** A progress partial inside the capture, follow-up and review forms (and the S-04 batch review if present) carries the Polish copy for each state in hidden blocks, with slow/stalled thresholds as data attributes computed from settings. A small deferred static script (`family_notes/static/js/classification-progress.js`) switches states on `submit` from a provider-calling submitter, connectivity events and timers.
2. **PWA shell.** Three anonymous root routes in `family_notes/` serve `/manifest.webmanifest` (JSON built in Python), `/sw.js` (a Django-rendered JavaScript template, so `{% static %}` URLs and the release-derived cache name resolve server-side) and `/offline/` (a user-independent Polish page). `base.html` links the manifest and `apple-touch-icon` and loads `js/pwa-register.js`. Icons are committed static PNGs.
3. **Gallery and device verification.** DEBUG gallery states for progress, plus install, offline and progress checks on a real Android phone.

## Critical Implementation Details

**Timing & lifecycle** — Do not set `disabled` on the submitter or on any field in the `submit` handler. Instead:
- Set `aria-busy="true"` on the form and the submitter (when there is one), `aria-disabled="true"` on the submitter, `readOnly` on the submitting textarea(s), a JS "in flight" flag, and remember the original submitter (possibly `null`) for retry.
- A second `submit` while the flag is set calls `preventDefault()`. The explicit retry is the exception: it clears the flag first.
- Clear all of it on `pageshow` (bfcache restore) and when the retry is used.
- Clear timers on `pagehide`, so a restored page does not show stale "slow"/"stalled" text.

The service worker uses `skipWaiting()` + `clients.claim()`. This is safe because no page content is cached and a new worker cannot serve stale HTML.

**User experience spec** — The live region (`role="status"`, `aria-live="polite"`) announces only state changes: running, slow, stalled, offline, connection lost. The per-second counter sits outside the live region (`aria-hidden="true"`). The retry button resubmits with the original submitter: `form.requestSubmit(lastSubmitter)` when it was a button, `form.requestSubmit()` when the original submit had none. A retried „Popraw” therefore posts to `entries:correct` again and never saves, and a retried follow-up stays "Dalej". Standalone mode has no reload button or URL bar, so the offline page offers "Spróbuj ponownie" as `<a href="">`, which reloads the requested URL with no script, and a link to `/`.

**Privacy & caching contract** — The service worker:
- precaches an explicit list: the offline page URL, `vendor/pico/pico.min.css`, `css/tokens.css`, and the 192 px icon. It fetches them with `new Request(url, {cache: 'reload', credentials: 'omit'})`, so the offline page is always rendered for an anonymous visitor;
- in `fetch`, returns without `respondWith` when `request.method !== 'GET'`;
- for `request.mode === 'navigate'`, uses `fetch(request)` and falls back to the cached offline page only on a network error. The network response is returned as-is and never stored;
- for same-origin GETs whose pathname is in the precache list, goes network-first with a cache fallback;
- ignores everything else;
- uses the cache name `familynotes-shell-<FAMILY_NOTES_RELEASE_ID>` (`family_notes/settings.py:380`), so every deploy changes `/sw.js` bytes and the worker re-installs and re-precaches the current offline page and styles;
- in `activate`, deletes caches whose name starts with `familynotes-` but is not the current cache name.

There is no `cache.put`, no IndexedDB, and no message handling of page data. Logout needs no cache purge because the worker never caches user-specific content. The browser's own HTTP cache and bfcache are outside this contract (accepted limitation, owner-confirmed 2026-10-04).

**Production headers** — The views set these headers:
- `/sw.js`: `Content-Type: text/javascript; charset=utf-8` and `Cache-Control: no-cache`, so a deploy updates the worker on the next navigation.
- `/manifest.webmanifest`: `Content-Type: application/manifest+json`.
- `/offline/`: `Cache-Control: no-cache`.

`nosniff` is already sent by `SecurityMiddleware`, so these exact types matter. Because the worker is served from root, no `Service-Worker-Allowed` header is needed. No nginx change is needed, because all three paths are proxied by `location /`. If a CSP is introduced later, it needs `worker-src 'self'`, `manifest-src 'self'`, `script-src 'self'` and `img-src 'self'`. All scripts are external same-origin files with no inline `<script>`, so they work under a strict policy.

## Phase 1: In-Page Progress Indicator

### Overview

Render the progress partial and thresholds, ship the script, and wire it into the capture and follow-up forms.

### Changes Required:

#### 1. Progress thresholds

**File**: `entries/views.py`

**Intent**: Give templates one source for the slow and stalled thresholds, so client timing stays consistent with the server's provider limits.

**Contract**: A private helper returns `{'progress_slow_after': ceil(settings.CLASSIFICATION_ATTEMPT_TIMEOUT_SECONDS), 'progress_stalled_after': ceil(settings.CLASSIFICATION_DEADLINE_SECONDS) + 10}`, which gives 10 and 35 by default. `_render` (`entries/views.py:90-91`) and the `states` view merge it into their context; every view that renders the review form (including S-03's `correct` and the S-04 batch views) goes through `_render` or merges it the same way.

#### 2. Progress partial

**File**: `entries/templates/entries/_classification_progress.html` (new); included by `entries/templates/entries/_capture_form.html`, `entries/templates/entries/_follow_up_form.html`, `entries/templates/entries/_review_form.html` (and the S-04 batch review partial if present)

**Intent**: Server-render every user-visible string in Polish, hidden until the script reveals it, so no copy lives in JavaScript.

**Contract**: A `<div data-classification-progress>` that is never `hidden`, containing an always-rendered `role="status" aria-live="polite"` element marked `data-progress-live data-live-region` (S-17's script-updated live-region marker). No ancestor of that element carries `hidden`. Inside the region are five state blocks, each `class="fn-panel fn-panel--notice"`, marked `data-progress-state="<name>"` and `hidden` by default; the script toggles only these blocks, so revealing one inside the already-present region is announced:
- `running`: "Rozpoznaję wpis… Zwykle trwa to kilka sekund. Nie zamykaj tej strony."
- `slow`: "Trwa to dłużej niż zwykle. Poczekaj jeszcze chwilę."
- `stalled`: "Brak odpowiedzi serwera. Sprawdź połączenie i spróbuj ponownie." plus a `type="button"` "Spróbuj ponownie" marked `data-progress-retry`.
- `offline`: "Brak połączenia z internetem. Tekst nie został wysłany — spróbuj ponownie, gdy połączenie wróci."
- `connection_lost`: "Utracono połączenie podczas rozpoznawania. Gdy wróci, spróbuj ponownie." plus a second `data-progress-retry` button.

Outside the region, the wrapper also contains a `hidden`, `aria-hidden="true"` elapsed counter `data-progress-elapsed` ("0 s"). The including `<form>` gains `data-classification-progress-form`, `data-progress-slow-after` and `data-progress-stalled-after`; capture and follow-up forms also gain `data-classification-default`, meaning their default (no-submitter) action calls the provider. The review form does not, because its default action is „Zapisz wpis”. Provider-calling submit buttons gain `data-classification-submit`: „Rozpoznaj”, „Dalej”, S-03's „Popraw” and S-04's `correct-<i>` buttons; "Pomiń" and „Zapisz wpis” never do. The partial accepts an optional `progress_state` parameter that renders that block visible without `hidden`; only the state gallery uses it. Any new class goes in `family_notes/static/css/tokens.css`, built from existing tokens, with no inline styles.

#### 3. Progress script

**File**: `family_notes/static/js/classification-progress.js` (new)

**Intent**: Switch the server-rendered states on submit, connectivity changes and timers, without changing what is posted.

**Contract**: A delegated `submit` listener on `document` for `form[data-classification-progress-form]` handles these cases:
- **Already in flight**: `preventDefault()` (any submitter, including „Zapisz wpis” while a „Popraw” is running).
- **Not a classification submit**: the submitter is a button without `data-classification-submit` (e.g. "Pomiń", „Zapisz wpis”), or it is `null` on a form without `data-classification-default`: do nothing. Every `event.submitter` access is null-safe.
- **Offline** (`navigator.onLine === false`): `preventDefault()` and show `offline`.
- **Classification submit**: enter the busy state, remember `event.submitter` (possibly `null`), show `running`, and start a 1 s counter and the slow/stalled timers from the form's data attributes.

Other events:
- `offline` while busy shows `connection_lost`.
- The retry button clears busy state and calls `form.requestSubmit(lastSubmitter)` when the original submitter was a button, otherwise `form.requestSubmit()`. It never submits a review form without its original submitter.
- `pagehide` clears timers; `pageshow` resets the busy state and hides the panel.

The script makes no network calls, uses no storage APIs and never reads the textarea value. It does not interact with the service worker. Plain ES2017 or older; code comments in English.

#### 4. Script include

**Files**: `entries/templates/entries/capture.html`, `entries/templates/entries/states.html`

**Intent**: Load the script only where classification forms render.

**Contract**: `{% block extra_body %}` keeps S-05's `js/enter-submit.js` tag and adds `<script src="{% static 'js/classification-progress.js' %}" defer></script>`.

### Success Criteria:

#### Automated Verification:

- View tests prove the capture form and follow-up form render the progress partial with all five hidden `data-progress-state` blocks, the exact Polish copy, the retry button, and the `data-progress-slow-after="10"` / `data-progress-stalled-after="35"` attributes under default settings.
- A view test with `override_settings(CLASSIFICATION_DEADLINE_SECONDS=12, CLASSIFICATION_ATTEMPT_TIMEOUT_SECONDS=6)` proves both thresholds follow the settings (`6` and `22`).
- View tests prove the review form (proposal, `correction_failed`, confirm-invalid) renders the progress partial, „Popraw” carries `data-classification-submit`, „Zapisz wpis” does not, and the review form has no `data-classification-default`; capture and follow-up forms carry `data-classification-default`, "Pomiń" has no `data-classification-submit`; structured create/edit forms and the saved panel do not render the partial.
- A markup test proves that in every rendered progress partial no ancestor of `[role=status][data-progress-live]` carries `hidden`, and that the region contains the five hidden state blocks.
- View tests prove the capture page and DEBUG state gallery include both the `js/classification-progress.js` and S-05 `js/enter-submit.js` script tags, and a test proves the new file resolves through Django's static files finders.
- Focused tests pass: `uv run python manage.py test entries.tests.test_capture_views entries.tests.test_follow_up_views entries.tests.test_correction_views entries.tests.test_states_view`.
- Django checks pass: `uv run python manage.py check`.

#### Manual Verification:

- Desktop Chrome with network throttling: after "Rozpoznaj", the spinner and running panel appear immediately, the counter advances, and the slow copy appears after 10 s; the next page then shows the review, question, or unavailable notice.
- Follow-up: "Dalej" (click and Enter) shows the indicator and Enter sets `aria-busy` on the form; "Pomiń" does not show it; Enter while busy does not post a second time.
- DevTools offline before submitting: the submission is blocked, the text stays, and the offline copy appears; Enter while still offline is blocked too; going back online, both Enter and tapping "Rozpoznaj" submit.
- Review form with throttling: „Popraw” (click and Enter in „Popraw opis”) shows the indicator, „Zapisz wpis” does not; after forcing the stalled state (DevTools offline-then-online or a stubbed slow backend), "Spróbuj ponownie" re-posts to `entries:correct` and no entry is saved.
- Back button after a completed classification: the restored capture page is not busy and no stale panel is visible.

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding.

---

## Phase 2: Installable PWA Shell

### Overview

Make the site installable on Chrome for Android, with a minimal privacy-safe service worker and a Polish offline fallback page.

### Changes Required:

#### 1. Icons

**Files**: `family_notes/static/pwa/icon.svg`, `family_notes/static/pwa/icon-192.png`, `family_notes/static/pwa/icon-512.png`, `family_notes/static/pwa/icon-maskable-512.png`, `family_notes/static/pwa/apple-touch-icon.png` (180 px) — all new

**Intent**: Provide the icon set Chrome needs for installability and a home-screen icon.

**Contract**: The placeholder "FN" monogram uses the accent and background colours from `tokens.css`. The maskable variant keeps the glyph inside the central 80 % safe zone. PNGs are exported once from the SVG and committed as binaries. No image library is added to the project dependencies.

#### 2. PWA views and routes

**Files**: `family_notes/views.py`, `family_notes/urls.py`

**Intent**: Serve the manifest, service worker and offline page from the site root, so worker scope and manifest scope are `/` without extra headers or nginx changes.

**Contract**: Three anonymous GET views; none reads family data or requires login:
- `web_manifest` → `path('manifest.webmanifest', …, name='web_manifest')`. Returns a `JsonResponse` with `content_type='application/manifest+json'` and these fields: `name`, `short_name` ("FamilyNotes"), `description` ("Wspólne notatki i sprawy rodziny"), `lang` "pl", `dir` "ltr", `id`/`start_url`/`scope` "/", `display` "standalone", `theme_color` and `background_color` (Python constants mirroring `--fn-color-accent`/`--fn-color-bg`, guarded by a test that reads them from `tokens.css`), and `icons` built with `static()` (192 any, 512 any, 512 maskable). There is no `orientation` member, because locking orientation fails WCAG 2.2 SC 1.3.4 (S-17's AA target).
- `service_worker` → `path('sw.js', …, name='service_worker')`. Renders `family_notes/templates/pwa/sw.js` with `content_type='text/javascript; charset=utf-8'` and `Cache-Control: no-cache`. The context holds the precache URL list (via `static()` and `reverse('offline')`) and the cache name `familynotes-shell-<settings.FAMILY_NOTES_RELEASE_ID>`. There is no manual cache-version constant; every release changes the worker bytes. In development the release id falls back to the directory name, so testing a worker update locally needs a temporary override.
- `offline` → `path('offline/', …, name='offline')`. Renders `offline.html` with `Cache-Control: no-cache`.

#### 3. Service worker template

**File**: `family_notes/templates/pwa/sw.js` (new)

**Intent**: Give a minimal worker that makes the app installable and replaces the browser error page offline, without storing anything family-related.

**Contract**: Exactly the behaviour in Critical Implementation Details → Privacy & caching contract: `install` precache plus `skipWaiting`, `activate` stale-cache cleanup plus `clients.claim`, and a `fetch` handler that ignores non-GET, falls back to the offline page for navigations on network error, and goes network-first with cache fallback for precached static assets only. There are no `push`, `sync`, `periodicsync`, `notificationclick` or `message` handlers. Template variables (cache name, precache URL list, offline URL) are serialized with `json.dumps` in the view, never hand-concatenated, and output with `|safe` inside `{% autoescape off %}` (they come only from `static()`, `reverse()` and the release id), so they are not HTML-escaped into `&quot;`. Code comments are in English.

#### 4. Offline page

**File**: `family_notes/templates/offline.html` (new)

**Intent**: A styled Polish page shown when a navigation fails offline. It must contain nothing user-specific.

**Contract**: The page extends `base.html` and overrides `{% block nav %}` as empty, with no `{% csrf_token %}` and no context beyond the request. Copy:
- `<h1>`: "Brak połączenia"
- body: "Nie możesz teraz połączyć się z FamilyNotes. Sprawdź połączenie z internetem. Twoje wpisy nie są zapisywane na tym urządzeniu."
- actions: `<a href="">Spróbuj ponownie</a>` and `<a href="{% url 'home' %}">Strona główna</a>` in `fn-actions`

Uses only existing `fn-*` classes and no literals (quality gate).

#### 5. Base layout wiring and registration script

**Files**: `family_notes/templates/base.html`, `family_notes/static/js/pwa-register.js` (new)

**Intent**: Advertise the manifest on every page and register the worker once per browser.

**Contract**: `<head>` gains:
- `<link rel="manifest" href="{% url 'web_manifest' %}">`
- `<link rel="icon" href="{% static 'pwa/icon-192.png' %}">`
- `<link rel="apple-touch-icon" href="{% static 'pwa/apple-touch-icon.png' %}">`
- `<script src="{% static 'js/pwa-register.js' %}" data-sw-url="{% url 'service_worker' %}" defer></script>`

There is no `theme-color` meta, because the quality gate forbids hex literals in `base.html`; the manifest carries the colour. `pwa-register.js` reads `document.currentScript.dataset.swUrl`. If `'serviceWorker' in navigator`, it registers that URL with `{scope: '/'}` on `load`. A registration failure produces only a `console.warn` with no network reporting. The script uses no storage APIs.

#### 6. Deployment runbook

**File**: `context/changes/deployment/mikrus-runbook.md`

**Intent**: Record that the PWA routes need no nginx change, and add a post-release smoke check.

**Contract**: The note goes near the nginx section (step 9). `/sw.js`, `/manifest.webmanifest` and `/offline/` are served by Django through `location /`. Do not add a `/sw.js` static alias or long `expires` for it. If a CSP is ever added, it needs `worker-src 'self'` and `manifest-src 'self'`. Smoke check: `curl -sI https://familynotes.mikrus.dev/sw.js` shows `200`, `text/javascript` and `Cache-Control: no-cache`, and `curl -s https://familynotes.mikrus.dev/manifest.webmanifest` returns JSON with `"start_url": "/"`.

#### 7. Tests

**File**: `family_notes/tests.py` (or a new `family_notes/test_pwa.py`)

**Intent**: Lock in the manifest contract, the worker headers, and the privacy guarantees that can be checked server-side.

**Contract**:
- **Anonymous access and types:** each route returns 200 to anonymous users with the content type and `Cache-Control` above.
- **Manifest:** JSON has the scope, start_url, id, display and three icons, each icon `src` resolves through the static finders, `orientation` is absent, and `theme_color`/`background_color` equal `--fn-color-accent`/`--fn-color-bg` read from `tokens.css` `:root`.
- **Worker source:** contains the non-GET early return, the literal `"/offline/"` with real double quotes (not `&quot;`), the offline/static precache URLs, and the cache name with the release id (under `override_settings(FAMILY_NOTES_RELEASE_ID=…)`). It contains no `cache.put`, `indexedDB` or `push`/`sync`/`notificationclick` listeners, and no precache URL under `/entries/`, `/api/`, `/account/`, `/accounts/` or `/admin/`.
- **Offline page:** rendered for a logged-in parent, it contains no username, no "Wyloguj" and no CSRF token.
- **Layout wiring:** `base.html` output (login page and the parent entry list) contains the manifest link and the registration script tag.

### Success Criteria:

#### Automated Verification:

- PWA tests prove `/manifest.webmanifest`, `/sw.js` and `/offline/` return 200 to anonymous users with `application/manifest+json`, `text/javascript` + `Cache-Control: no-cache`, and `Cache-Control: no-cache` respectively.
- A manifest test proves `id`, `start_url` and `scope` are `/`, `display` is `standalone`, `lang` is `pl`, `orientation` is absent, `theme_color`/`background_color` match the `tokens.css` values, and the 192, 512 and maskable 512 icons resolve through Django's static files finders.
- A service worker source test proves the non-GET early return, the precache list, the unescaped literal `"/offline/"` and the release-derived cache name are present, and that `cache.put`, `indexedDB`, `push`/`sync`/`notificationclick` event listeners and any `/entries/`, `/api/`, `/account/`, `/accounts/` or `/admin/` URL are absent.
- An offline page test proves the Polish copy renders and, for an authenticated parent, no username, "Wyloguj" or CSRF token appears.
- Layout tests prove the login page and parent entry list include the manifest link, `apple-touch-icon` and `js/pwa-register.js` with `data-sw-url="/sw.js"`.
- Focused tests pass: `uv run python manage.py test family_notes`.
- Django checks pass: `uv run python manage.py check`.

#### Manual Verification:

- Desktop Chrome DevTools → Application: manifest shows no installability errors, the service worker at `/sw.js` is activated with scope `/`, and Cache Storage holds only the precached offline page, two stylesheets and the icon after browsing entries and running a classification.
- Desktop Chrome DevTools offline: navigating to `/entries/` shows the styled "Brak połączenia" page; "Spróbuj ponownie" after reconnecting loads the real page.
- Logging out and in as a child shows the child's own home page with no stale parent content, online and after the offline page.

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding.

---

## Phase 3: State Gallery and Mobile Verification

### Overview

Make every progress state reviewable at phone width without a live provider. Then prove install, offline and progress on Chrome for Android.

### Changes Required:

#### 1. Gallery states

**Files**: `entries/views.py` (`states`), `entries/templates/entries/states.html`

**Intent**: Render running, slow, stalled, offline and connection-lost progress states statically from synthetic data, as AGENTS.md requires for new capture states.

**Contract**: Five new gallery sections: `progress_running`, `progress_slow`, `progress_stalled`, `progress_offline`, `progress_connection_lost`. Each renders the synthetic capture form with the matching `progress_state` visible and the submit button marked `aria-busy="true"` (running/slow only). They create no database rows and stay DEBUG-only and parent-only like the existing gallery. A gallery link points to `/offline/`, so the offline page can be reviewed alongside the other states.

#### 2. Gallery tests

**File**: `entries/tests/test_states_view.py`

**Intent**: Keep the new states covered by the gallery's existing DEBUG gating, access and zero-write guarantees.

**Contract**: The new section markers and their visible copy are present. With `DEBUG=False` the gallery still returns 404, and there are zero database writes.

### Success Criteria:

#### Automated Verification:

- Gallery tests prove the five `progress_*` sections render with their copy, DEBUG gating holds, non-parents are denied, and no rows are written.
- Full test suite passes: `uv run python manage.py test`.
- Django checks pass: `uv run python manage.py check`.
- Migration drift check passes: `uv run python manage.py makemigrations --check --dry-run`.
- Static collection includes the new assets: `DJANGO_STATIC_ROOT=$(mktemp -d) uv run python manage.py collectstatic --noinput` lists `js/classification-progress.js`, `js/pwa-register.js` and the `pwa/` icons.

#### Manual Verification:

- The five progress gallery states and the offline page are reviewed at 360 px width: no clipping, readable copy, visible spinner, reachable retry button; a screenshot is saved under the change folder.
- Chrome on Android against production HTTPS (or USB port-forwarding to `localhost`): FamilyNotes installs from the browser menu, opens standalone from the home-screen icon at the role's home page, and shows the FamilyNotes name and icon.
- Installed app: signing in with Google and with username/password both return to the standalone window logged in.
- Installed app: a capture shows the indicator and then the review; switching to airplane mode while waiting may briefly show the connection-lost copy and then Chrome's own error page; pressing Back restores the capture page (not busy, text kept) and resubmitting after reconnecting completes.
- Installed app: in airplane mode, opening the app or following a link shows the "Brak połączenia" page; after reconnecting, "Spróbuj ponownie" loads the page.
- Installed app: switching to another app for a few seconds during a classification and returning shows either the still-running indicator or the finished result, never a stuck page.
- TalkBack announces the running state once and the slow state once, not every second.

**Implementation Note**: Complete manual verification before implementation review.

---

## Testing Strategy

No Playwright/E2E tests in this slice (owner-confirmed 2026-10-04). Client behaviour is verified manually on a real device.

### Unit Tests:

- Threshold helper: default and overridden deadline and attempt timeout.
- Manifest builder: fields, scope, icon URLs, no orientation lock, theme colours matching `tokens.css`.

### Integration Tests:

- Rendered capture (empty, question, invalid), follow-up and review pages contain the partial and thresholds, with the live region never under a `hidden` ancestor; only provider-calling submitters are marked; create and edit forms do not render the partial.
- Script includes (progress, S-05 Enter, PWA registration) and static resolution of scripts and icons.
- `/manifest.webmanifest`, `/sw.js`, `/offline/`: anonymous access, content types, cache headers, service worker source privacy guards, offline page free of user data.
- Gallery states, gating, access, zero writes.

### Manual Testing Steps:

1. Throttled desktop Chrome: running → slow → result.
2. Offline before submit (click and Enter); connection lost during wait → Back → resubmit; stalled → retry after reconnect.
3. Follow-up "Dalej" (click and Enter) vs. "Pomiń"; review „Popraw” (click and Enter) vs. „Zapisz wpis”; retry of a stalled „Popraw” never saves.
4. Back/forward cache restore.
5. DevTools Application panel: manifest, service worker scope, Cache Storage contents only static assets plus the offline page.
6. Android Chrome real device over HTTPS: install, standalone launch, Google sign-in, normal run, airplane mode during wait, offline navigation, app switch, TalkBack.
7. JavaScript disabled: the capture flow is unchanged.

## Performance Considerations

- The site gains one small deferred script on the capture page and one tiny registration script on every page.
- The service worker adds a pass-through `fetch` for GET navigations and four precached assets (~100 KB, dominated by Pico).
- Server cost is three cheap anonymous views; `/sw.js` is re-checked by browsers on navigation, at most about once per page load.
- An abandoned classification request still occupies one of the two Gunicorn workers until the provider deadline (≤ 25 s), so a retry needs the second worker. That is acceptable at single-family scale and is the existing behaviour.

## Migration Notes

There are no database or data changes, no backfill and no feature flag. Rollback by code revert:

- **Progress UI:** removing the script include and partial include restores the browser loading state.
- **PWA:** keep the `/sw.js` route and replace the worker with a self-unregistering version (`self.registration.unregister()` plus deleting `familynotes-*` caches). Remove the manifest link and registration script. Simply deleting `/sw.js` would leave installed workers active until their next failed update check.
- Installed home-screen icons keep working as plain bookmarks to `/`.

## References

- `context/foundation/prd-v2.md:115-121` (US-06), `:164` (PK-06), `:185` (constraints), `:230` (Open Question 7)
- `context/foundation/roadmap-future.md` — S-06
- `entries/views.py:68-74`, `entries/views.py:90-197`, `entries/views.py:249`
- `entries/classification/openai_backend.py:206-234`, `family_notes/settings.py:326-330`
- `family_notes/settings.py:171-175` (HTTPS/secure headers), `:205-206` (Google provider), `:209-219` (middleware, no CSP), `:456-458` (static)
- `family_notes/urls.py:32-41`, `family_notes/views.py:14-36`, `family_notes/templates/base.html:3-9`, `family_notes/templates/base.html:35`
- `scripts/hooks/quality_gate.py:58-72` (template literal gate)
- `context/changes/deployment/mikrus-runbook.md:445` (Gunicorn), `:487-509` (nginx `/static/` and proxy), `context/changes/deployment/deployment-plan.md:62` (Mikrus HTTPS)
- `entries/templates/entries/_capture_form.html`, `entries/templates/entries/_follow_up_form.html`
- Related slice: `context/changes/enter-text-submission/plan.md` (S-05, lands first; shared `aria-busy` busy-form contract, "Critical Implementation Details — Timing & lifecycle")
- Related slices: `context/changes/free-text-proposal-correction/plan.md` (S-03 „Popraw”, Phase 2 §2–§3), `context/changes/multi-entry-text-capture/plan.md` (S-04 per-proposal correction, Phase 3), `context/changes/accessible-family-flows/plan.md` (S-17 live-region audit rule and `data-live-region` marker)

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: In-Page Progress Indicator

#### Automated

- [x] 1.1 View tests prove the capture form and follow-up form render the progress partial with all five hidden `data-progress-state` blocks, the exact Polish copy, the retry button, and the `data-progress-slow-after="10"` / `data-progress-stalled-after="35"` attributes under default settings. — f2a88eb
- [x] 1.2 A view test with `override_settings(CLASSIFICATION_DEADLINE_SECONDS=12, CLASSIFICATION_ATTEMPT_TIMEOUT_SECONDS=6)` proves both thresholds follow the settings (`6` and `22`). — f2a88eb
- [x] 1.3 View tests prove the review form (proposal, `correction_failed`, confirm-invalid) renders the progress partial, „Popraw” carries `data-classification-submit`, „Zapisz wpis” does not, and the review form has no `data-classification-default`; capture and follow-up forms carry `data-classification-default`, "Pomiń" has no `data-classification-submit`; structured create/edit forms and the saved panel do not render the partial. — f2a88eb
- [x] 1.11 A markup test proves that in every rendered progress partial no ancestor of `[role=status][data-progress-live]` carries `hidden`, and that the region contains the five hidden state blocks. — f2a88eb
- [x] 1.4 View tests prove the capture page and DEBUG state gallery include both the `js/classification-progress.js` and S-05 `js/enter-submit.js` script tags, and a test proves the new file resolves through Django's static files finders. — f2a88eb
- [x] 1.5 Focused tests pass: `uv run python manage.py test entries.tests.test_capture_views entries.tests.test_follow_up_views entries.tests.test_correction_views entries.tests.test_states_view`. — f2a88eb
- [x] 1.6 Django checks pass: `uv run python manage.py check`. — f2a88eb

#### Manual

- [ ] 1.7 Desktop Chrome with network throttling: after "Rozpoznaj", the spinner and running panel appear immediately, the counter advances, and the slow copy appears after 10 s; the next page then shows the review, question, or unavailable notice.
- [ ] 1.8 Follow-up: "Dalej" (click and Enter) shows the indicator and Enter sets `aria-busy` on the form; "Pomiń" does not show it; Enter while busy does not post a second time.
- [ ] 1.9 DevTools offline before submitting: the submission is blocked, the text stays, and the offline copy appears; Enter while still offline is blocked too; going back online, both Enter and tapping "Rozpoznaj" submit.
- [ ] 1.12 Review form with throttling: „Popraw” (click and Enter in „Popraw opis”) shows the indicator, „Zapisz wpis” does not; after forcing the stalled state (DevTools offline-then-online or a stubbed slow backend), "Spróbuj ponownie" re-posts to `entries:correct` and no entry is saved.
- [ ] 1.10 Back button after a completed classification: the restored capture page is not busy and no stale panel is visible.

### Phase 2: Installable PWA Shell

#### Automated

- [x] 2.1 PWA tests prove `/manifest.webmanifest`, `/sw.js` and `/offline/` return 200 to anonymous users with `application/manifest+json`, `text/javascript` + `Cache-Control: no-cache`, and `Cache-Control: no-cache` respectively. — 1b3cbe4
- [x] 2.2 A manifest test proves `id`, `start_url` and `scope` are `/`, `display` is `standalone`, `lang` is `pl`, `orientation` is absent, `theme_color`/`background_color` match the `tokens.css` values, and the 192, 512 and maskable 512 icons resolve through Django's static files finders. — 1b3cbe4
- [x] 2.3 A service worker source test proves the non-GET early return, the precache list, the unescaped literal `"/offline/"` and the release-derived cache name are present, and that `cache.put`, `indexedDB`, `push`/`sync`/`notificationclick` event listeners and any `/entries/`, `/api/`, `/account/`, `/accounts/` or `/admin/` URL are absent. — 1b3cbe4
- [x] 2.4 An offline page test proves the Polish copy renders and, for an authenticated parent, no username, "Wyloguj" or CSRF token appears. — 1b3cbe4
- [x] 2.5 Layout tests prove the login page and parent entry list include the manifest link, `apple-touch-icon` and `js/pwa-register.js` with `data-sw-url="/sw.js"`. — 1b3cbe4
- [x] 2.6 Focused tests pass: `uv run python manage.py test family_notes`. — 1b3cbe4
- [x] 2.7 Django checks pass: `uv run python manage.py check`. — 1b3cbe4

#### Manual

- [ ] 2.8 Desktop Chrome DevTools → Application: manifest shows no installability errors, the service worker at `/sw.js` is activated with scope `/`, and Cache Storage holds only the precached offline page, two stylesheets and the icon after browsing entries and running a classification.
- [ ] 2.9 Desktop Chrome DevTools offline: navigating to `/entries/` shows the styled "Brak połączenia" page; "Spróbuj ponownie" after reconnecting loads the real page.
- [ ] 2.10 Logging out and in as a child shows the child's own home page with no stale parent content, online and after the offline page.

### Phase 3: State Gallery and Mobile Verification

#### Automated

- [x] 3.1 Gallery tests prove the five `progress_*` sections render with their copy, DEBUG gating holds, non-parents are denied, and no rows are written.
- [x] 3.2 Full test suite passes: `uv run python manage.py test`.
- [x] 3.3 Django checks pass: `uv run python manage.py check`.
- [x] 3.4 Migration drift check passes: `uv run python manage.py makemigrations --check --dry-run`.
- [x] 3.5 Static collection includes the new assets: `DJANGO_STATIC_ROOT=$(mktemp -d) uv run python manage.py collectstatic --noinput` lists `js/classification-progress.js`, `js/pwa-register.js` and the `pwa/` icons.

#### Manual

- [ ] 3.6 The five progress gallery states and the offline page are reviewed at 360 px width: no clipping, readable copy, visible spinner, reachable retry button; a screenshot is saved under the change folder.
- [ ] 3.7 Chrome on Android against production HTTPS (or USB port-forwarding to `localhost`): FamilyNotes installs from the browser menu, opens standalone from the home-screen icon at the role's home page, and shows the FamilyNotes name and icon.
- [ ] 3.8 Installed app: signing in with Google and with username/password both return to the standalone window logged in.
- [ ] 3.9 Installed app: a capture shows the indicator and then the review; switching to airplane mode while waiting may briefly show the connection-lost copy and then Chrome's own error page; pressing Back restores the capture page (not busy, text kept) and resubmitting after reconnecting completes.
- [ ] 3.10 Installed app: in airplane mode, opening the app or following a link shows the "Brak połączenia" page; after reconnecting, "Spróbuj ponownie" loads the page.
- [ ] 3.11 Installed app: switching to another app for a few seconds during a classification and returning shows either the still-running indicator or the finished result, never a stuck page.
- [ ] 3.12 TalkBack announces the running state once and the slow state once, not every second.
