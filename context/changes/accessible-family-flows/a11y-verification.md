# Accessibility verification (S-17, Phase 4)

Date: 2026-10-05 (agent pass). Branch `feature/m2-improved-family-capture`.

**Agent environment:** headless Chromium (Playwright, `/usr/bin/chromium-browser`) against `runserver`
(DEBUG on, local SQLite DB seeded with `scripts/dev/seed_test_family.py`), live classification
(`gpt-5.4-nano`). axe-core 4.13.0 with the tags wcag2a, wcag2aa, wcag21a, wcag21aa and wcag22aa. The custom 404
page was checked on a second `runserver` with DEBUG off. Progress states that only exist briefly in the
browser (running, slow, stalled, offline, connection lost) were audited as rendered in the `/entries/_states/`
gallery sections.

**Not run by the agent (DEVICE-ONLY):** NVDA + Firefox, VoiceOver on iOS Safari, TalkBack on Android Chrome. Those
columns still need a person with the device or screen reader.

Legend: PASS, FAIL (with WCAG SC), DEVICE-ONLY (not yet run), n/a.

| Flow | Keyboard / Chrome | NVDA / Firefox | VoiceOver / iOS Safari | TalkBack / Android Chrome | axe | 200% zoom / 320 px reflow |
| --- | --- | --- | --- | --- | --- | --- |
| Sign-in (incl. invalid re-render) | PASS: skip link first; keyboard sign-in with Enter | DEVICE-ONLY | DEVICE-ONLY | DEVICE-ONLY | PASS (0 violations) | PASS |
| Capture: empty / invalid | PASS: textarea autofocus, Enter submits. Note: a truly empty submit is stopped by the native `required` bubble, so the Polish server error shows only for whitespace input (1.5) | DEVICE-ONLY | DEVICE-ONLY | DEVICE-ONLY | PASS | PASS |
| Capture: proposal / review (live) | FAIL 2.4.7: the date/time picker icon is a Tab stop with no visible focus. Otherwise PASS: "Zapisz wpis" with Enter | DEVICE-ONLY | DEVICE-ONLY | DEVICE-ONLY | PASS | PASS (320 px live review) |
| Capture: past date | PASS: description = warning + readable weekday date (1.6) | DEVICE-ONLY | DEVICE-ONLY | DEVICE-ONLY | PASS (live + gallery) | PASS |
| Capture: unavailable, too_many | not exercised live | DEVICE-ONLY | DEVICE-ONLY | DEVICE-ONLY | PASS (gallery) | PASS (gallery at 320 px) |
| Enter-to-submit: capture | PASS | DEVICE-ONLY (focus mode) | n/a | DEVICE-ONLY (send key) | n/a | n/a |
| Enter-to-submit: follow-up answer | PASS: Enter → next review | DEVICE-ONLY | n/a | DEVICE-ONLY | n/a | n/a |
| Enter-to-submit: „Popraw opis” | PASS: Enter → "Zaktualizowano: tytuł." | DEVICE-ONLY | n/a | DEVICE-ONLY | n/a | n/a |
| Correction states (corrected, correction_failed, correction-invalid) | PASS (live corrected) | DEVICE-ONLY | DEVICE-ONLY | DEVICE-ONLY | PASS (gallery) | PASS (gallery) |
| Batch review / batch-invalid / batch saved | not run by keyboard | DEVICE-ONLY | DEVICE-ONLY | DEVICE-ONLY | PASS (live batch review + gallery batch, duplicate, missing, invalid, corrected, saved) | PASS (320 px live batch) |
| Progress running / slow announcements | n/a (not run with throttling in this pass) | DEVICE-ONLY (announced once each) | DEVICE-ONLY | DEVICE-ONLY | PASS (gallery running, slow, stalled, offline, connection_lost) | PASS (gallery at 320 px) |
| Follow-up question: answer | PASS | DEVICE-ONLY | DEVICE-ONLY | DEVICE-ONLY | PASS (live + gallery question states) | PASS (320 px live) |
| Follow-up question: skip ("Pomiń") | PASS: Pomiń with Enter → skipped notice → save | DEVICE-ONLY | DEVICE-ONLY | DEVICE-ONLY | PASS (gallery skipped) | PASS |
| Parent list (upcoming, past, empty) | PASS: no trap, visible focus on 30+ stops | DEVICE-ONLY | DEVICE-ONLY | DEVICE-ONLY | PASS (real upcoming/past, gallery empty) | PASS |
| Parent detail + "Usuń wpis" disclosure | PASS: summary and "Usuń na stałe" with Enter, "Usunięto wpis." | DEVICE-ONLY | DEVICE-ONLY | DEVICE-ONLY | PASS (closed and open) | PASS |
| Structured create (valid, invalid) | FAIL 2.4.7: date/time picker icon (see above). Otherwise PASS | DEVICE-ONLY | DEVICE-ONLY | DEVICE-ONLY | PASS | PASS |
| Edit (valid, invalid) | FAIL 2.4.7: date/time picker icon. Otherwise PASS | DEVICE-ONLY | DEVICE-ONLY | DEVICE-ONLY | PASS | PASS |
| Child list (upcoming, past, empty) and detail | PASS: list → detail → back → "Minione" | DEVICE-ONLY | DEVICE-ONLY | DEVICE-ONLY | PASS (real + gallery empty) | PASS |
| Account status (parent, child, unconfigured) | PASS | DEVICE-ONLY | DEVICE-ONLY | DEVICE-ONLY | PASS | PASS |
| Member management (S-14) list / edit / invalid / guard | PASS (checklist script, keyboard rename, deactivate and reactivate) | DEVICE-ONLY | DEVICE-ONLY | DEVICE-ONLY | PASS (real + gallery) | PASS |
| Role change (S-15) promote / demote / self-demotion / last parent | PASS (keyboard promote and demote, self-demotion error) | DEVICE-ONLY | DEVICE-ONLY | DEVICE-ONLY | PASS (real + gallery) | PASS |
| Family chooser + header switcher (S-16, two memberships) | PASS (keyboard) | DEVICE-ONLY | DEVICE-ONLY | DEVICE-ONLY | PASS at 1280 px; at 320 px `target-size` on "Wróć do konta" | FAIL 1.4.10: header does not wrap, page 474 px wide at 320/360 px (chooser 391 px) |
| `/offline/` (anonymous, signed in) | PASS: skip link, "Spróbuj ponownie" reachable | DEVICE-ONLY | DEVICE-ONLY (reads correctly?) | DEVICE-ONLY | PASS | PASS |
| 403 | PASS | DEVICE-ONLY | DEVICE-ONLY | DEVICE-ONLY | PASS | PASS |
| 404 (anonymous; signed-in render is the same template) | PASS (DEBUG off) | DEVICE-ONLY | DEVICE-ONLY | DEVICE-ONLY | PASS (DEBUG off) | PASS |
| 500 | not run (needs a forced error with DEBUG off) | DEVICE-ONLY | DEVICE-ONLY | DEVICE-ONLY | not run | not run |
| Skip link on every covered page | PASS except capture: autofocus puts focus in the textarea, so the first Tab goes to "Rozpoznaj" (2.4) | DEVICE-ONLY | n/a | n/a | n/a | n/a |

## Findings and follow-ups

1. **Date/time picker icon has no visible focus (SC 2.4.7).** In Chromium the calendar/clock icon inside
   `<input type="date|time">` is its own Tab stop; with the current CSS it shows no indicator. Affects the create,
   edit, review and follow-up forms. Likely fix: an outline on `::-webkit-calendar-picker-indicator:focus-visible`
   in `tokens.css`.
2. **Two-family header does not reflow (SC 1.4.10).** For users with more than one active membership, the header
   is 474 px wide at 320/360 px and "Wyloguj" is off-screen. Single-family pages are fine. This came with S-16
   (`multiple-family-use`), after S-17.
3. **Empty capture submit uses the native `required` bubble.** The Polish server error and the `aria-describedby`
   association work, but only appear for whitespace-only input. Decide: accept, or add `novalidate`.
4. **allauth "Zalogowano jako <username>." panel** now shows on every page that extends `base.html` (S-15 moved
   the messages block into the layout). It sits above the `<h1>` on the child list, account page and chooser, but
   below the `<h1>` on the parent list and member list. It is a role="status" success panel with visible text
   (axe-clean) and shows the login username.
