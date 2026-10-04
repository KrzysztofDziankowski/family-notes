# Mobile Classification Progress — Plan Brief

> Full plan: `context/changes/mobile-classification-progress/plan.md`

## What & Why

When a parent taps "Rozpoznaj" on a phone, the app shows nothing of its own while the server waits up to ~25 s for the classification provider. The PRD calls this "a loading page" (PK-06, US-06). On 2026-10-04 the owner decided the mobile experience is an installable PWA. This plan makes FamilyNotes installable on Chrome for Android, with a privacy-safe minimal service worker and a Polish offline page. It also adds an in-page activity indicator that says classification is running, flags when it is slow, and handles offline and stalled requests clearly.

## Starting Point

`capture` and `answer` are synchronous Django views that call OpenAI inside the POST (`entries/views.py:94-197`). They work within a 25 s app deadline, Gunicorn's 45 s timeout and nginx's 50 s timeout. Failure already renders a Polish "could not recognize" notice. There is no manifest, service worker or CSP today. nginx serves `/static/` with a 1 h expiry and proxies everything else to Django, behind Mikrus HTTPS. S-05 (Enter-submit) lands first and adds the first script.

## Desired End State

On Chrome for Android, the parent installs FamilyNotes to the home screen and opens it full-screen at `/`. Offline navigation shows a styled "Brak połączenia" page instead of the browser's error, and the service worker stores no family data (the browser's own HTTP cache and bfcache are an accepted limitation; no `no-store` headers). After "Rozpoznaj", "Dalej" or S-03's „Popraw”, the parent sees right away a spinner, "Rozpoznaję wpis… Nie zamykaj tej strony" and an elapsed counter. After 10 s a "longer than usual" line appears. Offline submits are blocked with the text kept. A stalled request offers "Spróbuj ponownie", which resubmits with the original submitter; a dropped connection usually ends on Chrome's error page, from which Back restores the capture page for a resubmit. The next page shows the review, the follow-up question or the unavailable notice.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
| --- | --- | --- | --- |
| Mobile experience | Installable PWA (manifest, icons, standalone, minimal service worker, offline page) on the existing site; no native app | Owner decision; smallest change that makes the app feel like a phone app. | Owner |
| Notifications | No push or system notifications now; possible future slice | Owner decision; avoids a permission prompt and server push infrastructure. | Owner |
| "Background" meaning | Synchronous request stays; closing the page abandons classification; no server job/queue/polling | Continuing after close would store instruction text server-side, against the privacy guardrail. | Owner |
| Service worker caching | Only static shell assets + the offline page, precached with `credentials: 'omit'`; non-GET ignored; navigations network-only with offline fallback; no runtime `cache.put` | Family data, authenticated HTML, API responses and classification text must never reach device storage. | Owner |
| Release | No feature flag, no backfill; rollback is a code revert plus a self-unregistering worker | Owner decision; there is no data change to stage. | Owner |
| Testing | Django tests + manual Android phone checks; no Playwright/E2E now | Owner decision; E2E may be added later. | Owner |
| Slice order / S-05 | S-05 lands before S-06; S-06 marks busy forms `aria-busy="true"`, S-05 skips them | Owner-confirmed order; the shared contract keeps Enter from double-posting. | Owner |
| Worker & manifest location | Django routes `/sw.js` and `/manifest.webmanifest` at root, explicit `scope`/`start_url`/`id` = `/` | Root path gives scope `/` with no `Service-Worker-Allowed` header and no nginx change (`location /` proxies them). | Research |
| Production headers | `/sw.js` `text/javascript` + `Cache-Control: no-cache`; manifest `application/manifest+json`; no CSP today (future CSP needs `worker-src`/`manifest-src 'self'`) | `nosniff` is on by default, and a cached worker would delay updates. | Research |
| Theme colour | In manifest JSON (Python constant, test-checked against `tokens.css`), not a `<meta>` in `base.html`; no `orientation` lock (WCAG 1.3.4) | The quality gate forbids hex literals in `base.html`. | Research |
| Worker cache name | `familynotes-shell-<FAMILY_NOTES_RELEASE_ID>`; no manual version constant | Every deploy re-installs the worker, so cached offline page and CSS never go stale. | Research |
| PWA identity | Name "FamilyNotes", `lang: pl`, placeholder "FN" monogram icon, Chrome's own install UI, Android-only verification | No artwork or install-UX requirements recorded yet. | Owner |
| Offline / lost connection | Block offline submit; lost-connection and stalled states with a retry that resubmits with the original submitter; Chrome's error page + Back after a mid-POST drop; no offline queue | Capture/answer/correction are read-only (`entries/classification/service.py:18-19`), so resubmitting is safe; a POST navigation abort cannot be caught without the worker touching POSTs. | Assumed (owner to confirm) |
| Indicator | Spinner + status panel + elapsed seconds; "slow" after one attempt timeout (10 s); no percentage | No real progress signal; past the attempt timeout the provider is retrying. | Assumed (owner to confirm) |
| Stalled threshold | `CLASSIFICATION_DEADLINE_SECONDS` + 10 s (35 s default), rendered from settings | Keeps client timing tied to the existing server deadline. | Research |
| Submissions covered | Submitter-scoped: "Rozpoznaj", "Dalej", S-03 „Popraw” (and S-04 `correct-<i>`), marked `data-classification-submit`; not "Pomiń"/„Zapisz wpis” | These call the provider; „Popraw” shares the review form with „Zapisz wpis”, so scope follows the button, not the form. | Owner |
| Live region | `role="status"` region always rendered (`data-progress-live data-live-region`); only hidden state blocks inside it are toggled | A region that appears together with its content is often not announced. | Research |
| Device storage claim | "The service worker stores no family data"; browser HTTP cache/bfcache accepted as-is, no `no-store` headers | Accurate wording without a cross-cutting caching change. | Owner |
| Busy state | `aria-busy`/`aria-disabled` + JS flag, never `disabled` in the submit handler | Disabling there could drop the submitter/field values from the POST. | Research |
| Copy location | All Polish strings server-rendered (progress partial, offline template) | Keeps copy in templates; JS only toggles states. | Research |

## Scope

**In scope:**
- `_classification_progress.html` partial in capture, follow-up and review (and S-04 batch) forms; submitter markers; thresholds helper; `js/classification-progress.js`
- PWA shell: `/manifest.webmanifest`, `/sw.js`, `/offline/`, icons under `static/pwa/`, `js/pwa-register.js`, `base.html` head links
- Runbook note and post-release smoke check for the PWA routes
- Five DEBUG gallery progress states, Django tests, 360 px review, Android install/offline/progress/TalkBack checks

**Out of scope:**
- Push notifications, Background/Periodic Sync, offline submission queue, native app/TWA, custom install button
- Caching of any family data, authenticated HTML, API responses or classification text
- Server jobs, polling, SSE/WebSockets, result reporting after close, percentage bars, latency changes, indicators on "Pomiń"/„Zapisz wpis” or other forms
- HTTP caching changes (`no-store`) for authenticated pages
- Feature flags, backfill, CSP introduction, Playwright/E2E

## Architecture / Approach

The server renders an always-present live region holding hidden copy blocks for five states (running, slow, stalled, offline, connection lost), with thresholds as form data attributes. A deferred script switches states on `submit` from a provider-calling submitter, timers and connectivity events. Three anonymous Django root routes serve the manifest (JSON), the service worker (a rendered JS template with static URLs and a release-derived cache name) and the offline page. The worker precaches four assets, ignores non-GET requests, passes navigations to the network and falls back to the offline page only on network errors. `base.html` links the manifest and registers the worker.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. In-Page Progress Indicator | Partial, thresholds, script, includes, markup tests | Busy-state handling dropping POST values or sticking after Back |
| 2. Installable PWA Shell | Manifest, icons, service worker, offline page, head wiring, runbook note, header/privacy tests | Worker intercepting POSTs or caching user-specific HTML; stale worker after deploy |
| 3. State Gallery and Mobile Verification | Five gallery states, full suite, 360 px review, Android install/standalone/offline/TalkBack checks | Google sign-in or app-switch behaving differently in standalone mode |

**Prerequisites:** S-05 `enter-text-submission` and S-03 `free-text-proposal-correction` merged (confirmed order S-01, S-02, S-20, S-03, S-04, S-05, S-06, …). Manual phone checks need HTTPS: production after release, or USB port-forwarding to `localhost`.
**Estimated effort:** ~2–3 sessions across 3 phases.

## Open Risks & Assumptions

- Google OAuth opens in a Chrome Custom Tab from standalone mode. If the session does not return to the installed window, sign-in needs a follow-up fix (manual check 3.8).
- A deployed worker outlives a code revert. Rollback must ship a self-unregistering `/sw.js`, not delete the route.
- Owner decisions from plan review were applied 2026-10-04. Icon artwork, app name/description and the browser coverage beyond Chrome on Android remain assumed defaults that stand unless the owner objects.
- The browser's own HTTP cache and bfcache can keep authenticated pages on a shared phone, as today; accepted limitation (owner-confirmed 2026-10-04).
- The submitter markers and partial include depend on S-03/S-04 final review markup.
- An abandoned request keeps one of two Gunicorn workers busy for up to the deadline; acceptable at single-family scale.

## Success Criteria (Summary)

- A parent can install FamilyNotes on an Android phone and use it full-screen. Offline, it shows a clear Polish page, and the service worker stores no family data.
- On a phone, the parent always sees that classification (or a „Popraw” correction) is running, and that it is slow, without relying on a browser loading bar.
- Offline, lost-connection and stalled cases give clear Polish feedback and a safe retry. Completion and failure still land on the existing screens, and the no-JS flow is unchanged.
