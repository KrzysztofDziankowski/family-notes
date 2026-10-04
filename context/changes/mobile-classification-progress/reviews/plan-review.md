<!-- PLAN-REVIEW-REPORT -->
# Plan Review: Mobile Classification Progress Implementation Plan

- **Plan**: context/changes/mobile-classification-progress/plan.md
- **Mode**: Deep
- **Date**: 2026-10-04
- **Verdict**: SOUND (after triage; was REVISE)
- **Triage**: applied 2026-10-04
- **Findings**: 0 critical, 6 warnings, 3 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| End-State Alignment | WARNING |
| Lean Execution | PASS |
| Architectural Fitness | WARNING |
| Blind Spots | WARNING |
| Plan Completeness | PASS |

## Grounding
Grounding: 7/7 paths ✓ (`entries/views.py`, `family_notes/views.py`, `family_notes/urls.py`, `base.html`, `_capture_form.html`, `_follow_up_form.html`, `mikrus-runbook.md`), 7/7 symbols ✓ (`_render` views.py:90, `CLASSIFICATION_DEADLINE_SECONDS`/`ATTEMPT_TIMEOUT` settings.py:326-329, no CSP/login middleware settings.py:209-219, `STATIC_URL`/`DJANGO_STATIC_ROOT` settings.py:456-458, nginx `location /` + `expires 1h` runbook:495-508, Gunicorn `--timeout 45` runbook:445, `{% block nav %}` inside `user.is_authenticated` base.html:17-25), brief↔plan ✓. Progress↔Phase ✓ (3 phases, 29 steps).

Production serving verified: `/sw.js`, `/manifest.webmanifest`, `/offline/` fall through nginx `location /` to Gunicorn; root scope needs no `Service-Worker-Allowed`; `SecurityMiddleware` sends `nosniff`, so the explicit content types are required, as the plan says. The service-worker privacy contract itself (non-GET ignored, navigations network-only, no `cache.put`, precache with `credentials: 'omit'`) is sound.

## Findings

### F1 — Manifest `orientation: "portrait"` fails WCAG 2.2 AA 1.3.4 (S-17 target)

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Architectural Fitness
- **Location**: Phase 2 §2 (`web_manifest` fields)
- **Detail**: The manifest locks the installed app to `"orientation": "portrait"`. WCAG 2.2 SC 1.3.4 Orientation (AA) forbids restricting display to one orientation unless it is essential. The owner confirmed WCAG 2.2 AA for S-17, which lands after this slice and covers the capture flow. Nothing in capture or review needs portrait, and landscape matters for users with mounted devices or larger fonts.
- **Fix**: Drop the `orientation` member (or set `"any"`), and add a manifest test asserting it is absent or `"any"`.
- **Owner input**: no
- **Decision**: FIXED (Fix A)

### F2 — Live region sits inside a `hidden` panel; announcements will be unreliable

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Blind Spots
- **Location**: Phase 1 §2 (progress partial contract); Critical Implementation Details — User experience spec; manual check 3.12
- **Detail**: The `role="status" aria-live="polite"` element is inside `<div … data-classification-progress hidden>`. On submit, the script removes `hidden` from the panel and from the `running` block at the same moment. A live region that becomes rendered at the same time as its content is often not announced (TalkBack/Chrome and NVDA in particular), because the region was not in the accessibility tree before the change. Manual check 3.12 ("TalkBack announces the running state once") is then likely to fail, with no fix path inside the plan. The same markup also collides with S-17's planned audit rule "`role=status` only on elements with text" (see S-17 review).
- **Fix**: Keep the `role="status"` element always rendered (never under a `hidden` ancestor) in both forms. Toggle only the visual panel wrapper and the state blocks inside the region, so that un-hiding one block inside an already-present region is announced. State this in the partial contract and add a markup test that no ancestor of `[role=status][data-progress-live]` carries `hidden`.
  - Strength: The standard reliable live-region pattern; keeps all copy server-rendered (no JS strings).
  - Tradeoff: The empty region is in the DOM on every capture page; S-17's audit must allow that (coordinated finding there).
  - Confidence: MEDIUM — screen-reader behaviour varies, but the "region present before change" rule is well established.
  - Blind spot: Not tested on the actual Pico markup with TalkBack.
- **Owner input**: no
- **Decision**: FIXED (Fix A)

### F3 — Manual `PWA_CACHE_VERSION` leaves the offline page and CSS stale after deploys

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Blind Spots
- **Location**: Phase 2 §2 (`service_worker` context, "Bump the constant whenever the precache list changes")
- **Detail**: The worker precaches `/offline/`, `pico.min.css`, `tokens.css` and an icon once, at install. There is no runtime `cache.put`, and the network-first branch does not refresh the cache. The worker is only reinstalled when `/sw.js` bytes change, which happens only when the precache *list* or the manual constant changes. Changing the *content* of `base.html`, `offline.html` or `tokens.css` therefore never reaches the cached copies. S-17 (later in the same milestone) changes both `base.html` (skip link) and `tokens.css` (focus, borders), and every later UI slice does too. Offline users keep seeing the install-time page and styles indefinitely. The bump rule is easy to forget and the plan has no test for it.
- **Fix**: Derive the cache name from the release, for example `familynotes-shell-<settings.FAMILY_NOTES_RELEASE_ID>` (already defined at `family_notes/settings.py:380`). Every deploy then changes `/sw.js` bytes, so the worker re-installs, re-precaches and deletes the old cache. Drop the manual constant and test that the rendered worker contains the release id.
  - Strength: No manual step; the reinstall cost is about 100 KB per device per deploy, which is negligible at family scale.
  - Tradeoff: Each deploy triggers one worker update per device.
  - Confidence: HIGH — the setting exists and is release-specific in production.
  - Blind spot: In development `FAMILY_NOTES_RELEASE_ID` falls back to the directory name (stable), so local testing of updates still needs a manual change.
- **Owner input**: no
- **Decision**: FIXED (Fix A)

### F4 — Indicator scope misses S-03's „Popraw”, a provider call that lands first

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: End-State Alignment
- **Location**: Decision 10; Phase 1 §2–§3; test 1.3 ("review form… do not render the progress partial")
- **Detail**: Decision 10 limits the indicator to capture and follow-up because "only these call the provider". In the confirmed order S-03 (`free-text-proposal-correction`) ships before S-06. It adds a „Popraw” submit on the review form (`formaction` → `entries:correct`) that makes one provider call under the same 25 s deadline (`free-text-proposal-correction/plan.md:66,197,299`), and S-04 adds per-proposal corrections. US-06 ("parent sees classification activity") then has an uncovered long wait, and test 1.3 would pin the gap. Extending the indicator naively is risky too. The retry button calls `form.requestSubmit()` with no submitter, which on the review form ignores „Popraw”'s `formaction` and posts to `entries:confirm`, so a retry would **save** the entry.
- **Fix**: Make the indicator submitter-scoped instead of form-scoped. Mark provider-calling submitters (`data-classification-submit`: „Rozpoznaj”, „Dalej”, „Popraw”) and include the partial in the review/batch forms. Show the indicator only when `event.submitter` is a marked button, or when it is null on a form whose default action calls the provider. The retry calls `form.requestSubmit(lastSubmitter)`. Replace test 1.3 with "review form renders the partial, but „Zapisz wpis” is not a classification submitter", and add a test that the retry keeps the submitter.
  - Strength: Covers every provider wait the parent can trigger; closes the retry-saves bug.
  - Tradeoff: More markup and a slightly larger script contract; depends on S-03/S-04 final markup.
  - Confidence: MEDIUM — S-03/S-04 plans are not yet implemented.
  - Blind spot: S-04 batch layout (one form, several „Popraw” buttons) not verified.
- **Owner input**: no
- **Decision**: FIXED (Fix A)

### F5 — Lost connection mid-POST usually ends on the browser's error page, not the in-page state

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: End-State Alignment
- **Location**: Desired End State ("if the connection drops while waiting…"); Phase 1 §3 (`offline` while busy); manual checks 3.9, 3.11
- **Detail**: The classification is a top-level form-POST navigation. When the network drops, Chrome aborts that navigation (for example `ERR_INTERNET_DISCONNECTED` or `ERR_NETWORK_CHANGED`) and replaces the document with its own error page. Because the worker deliberately ignores non-GET requests, the installed app shows Chrome's generic offline page, not "Brak połączenia". The `connection_lost` panel and its retry button are visible only for the moments before the abort, so check 3.9 ("shows the connection-lost copy, and the retry after reconnecting completes") will usually fail. This is not a privacy problem; the plan simply promises behaviour the platform will not deliver.
- **Fix A ⭐ Recommended**: Keep the owner-confirmed "ignore non-GET" contract. Reword the end state and check 3.9: the connection-lost copy may flash, and the parent then lands on the browser error page. Pressing Back restores the capture page with the text (verify bfcache + `pageshow` reset), and resubmitting works. Keep the `connection_lost` state for the cases where the request merely hangs.
  - Strength: No change to the privacy contract; honest manual check.
  - Tradeoff: Chrome's error page in standalone mode is less friendly than the styled page.
  - Confidence: MEDIUM — exact Chrome behaviour per failure mode is not verified on device.
  - Blind spot: Whether Back restores the typed text in standalone mode.
- **Fix B**: Let the worker `respondWith(fetch(request).catch(() => <in-memory Polish error response>))` for POST navigations to the classification endpoints only, never reading or storing the body.
  - Strength: Styled page instead of Chrome's error.
  - Tradeoff: Reopens owner-confirmed Decision 4 ("ignores every non-GET request") and the worker now handles requests that carry instruction text.
  - Confidence: MEDIUM.
  - Blind spot: Redirect handling of proxied POST navigations.
- **Owner input**: no
- **Decision**: FIXED (Fix A)

### F6 — `event.submitter` is null for S-05 Enter submits and for retry

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Architectural Fitness
- **Location**: Phase 1 §3 (skip-button check `event.submitter.value === 'skip'`); Key Discoveries ("Enter-submits get the indicator for free")
- **Detail**: S-05 submits with `form.requestSubmit()` and no submitter, and so does this plan's retry. `event.submitter` is then `null`, so `event.submitter.value` throws a TypeError in the listener. The submission still goes out (an exception does not cancel it), but the busy state and indicator never appear, and the S-05 double-Enter guard (`aria-busy`) never engages. This silently breaks the shared contract both plans rely on.
- **Fix**: Use a null-safe check (`event.submitter && event.submitter.value === 'skip'`), and add manual check 1.8's Enter case explicitly: "Enter shows the indicator and sets `aria-busy`".
- **Owner input**: no
- **Decision**: FIXED (Fix A)

### F7 — Worker template escaping and incomplete URL guard in tests

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 2 §2–§3, test 2.3
- **Detail**: `sw.js` is a Django template rendered with autoescape on. Values serialized with `json.dumps` and output with `{{ }}` become `&quot;…&quot;`, which is invalid JavaScript, and the worker fails to install. Test 2.3 checks only for absent strings, so it would still pass. Its URL guard lists `/account/` but not allauth's `/accounts/` or `/admin/`.
- **Fix**: Output the JSON values with `|safe` inside `{% autoescape off %}` (values come only from `static()`/`reverse()`). Assert the rendered source contains the literal `"/offline/"` with real double quotes, and extend the forbidden list to `/accounts/` and `/admin/`.
- **Owner input**: no
- **Decision**: FIXED (Fix A)

### F8 — "Nothing family-related is ever stored on the device" is broader than the plan delivers

- **Severity**: 💡 OBSERVATION
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Blind Spots
- **Location**: Desired End State; Success Criteria summary in plan-brief.md
- **Detail**: The worker stores nothing family-related, which is correct. Authenticated Django pages, however, are sent with no `Cache-Control` (no `never_cache`, no middleware; `settings.py:209-219`), so Chrome's HTTP disk cache and the bfcache keep entry lists and details on the device, as they do today. The success criterion promises more than the slice changes.
- **Fix A ⭐ Recommended**: Narrow the wording to "the app's service worker stores no family data on the device" and leave HTTP caching as it is.
  - Strength: Accurate; no behaviour change; keeps bfcache, which S-05/S-06 `pageshow` logic already handles.
  - Tradeoff: Family HTML can still sit in the browser's disk cache on a shared phone.
  - Confidence: HIGH.
  - Blind spot: None significant.
- **Fix B**: Add `Cache-Control: private, no-store` to authenticated HTML responses (middleware), and test it.
  - Strength: Makes the strong privacy claim true.
  - Tradeoff: Slower Back navigation, more server load, and a new cross-cutting behaviour outside this slice's scope.
  - Confidence: MEDIUM — bfcache interplay with `no-store` varies by Chrome version.
  - Blind spot: Impact on Google OAuth return flow.
- **Owner input**: yes
- **Decision**: FIXED (owner: Fix A — wording narrowed to "the service worker stores no family data"; no no-store headers; browser cache noted as accepted limitation)

### F9 — Duplicated theme colours and stale cross-plan line references

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 2 §2 (theme/background Python constants); Key Discoveries; Decisions header
- **Detail**: `theme_color`/`background_color` are Python constants "mirroring" `--fn-color-accent`/`--fn-color-bg`, so they will drift silently when tokens change (S-17 adds tokens). Key Discoveries cite `enter-text-submission/plan.md:41,:58,:84` for the busy contract, but those lines are "Desired End State", a NOT-doing bullet and a blank line. The confirmed order omits S-20.
- **Fix**: Add a manifest test that reads the two values from `tokens.css` `:root` and compares them (S-17 later adds a parser for the same file). Cite S-05 by section ("Critical Implementation Details — Timing & lifecycle"), and add S-20 to the order.
- **Owner input**: no
- **Decision**: FIXED (Fix A)
