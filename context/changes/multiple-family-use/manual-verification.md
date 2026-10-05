# Manual verification

Date: 2026-10-05

## Code review (review agent)

Environment: code review on branch `feature/m2-improved-family-capture` (no browser).

- 1.6 PASS — no view passes `request.user` to a domain service or form; the parent views get `membership` from `_require_parent(request)` → `resolve_family_context`. `correct_proposal_for_parent`, `classify_entries_for_parent`, `save_confirmed_entries`, `BatchReviewForm` and `classify_for_parent` all take `membership`, and S-07's `requester_name` comes from `membership.display_name`. The only remaining hand-off is `select_family` → `active_memberships(request.user)`, the context resolver that the plan itself defines as user-keyed for the chooser. Other `request.user` uses are authentication or admin checks.

## Browser (browser agent B)

Environment: headless Chromium (Playwright, `/usr/bin/chromium-browser`) against `runserver` (DEBUG on, own SQLite DB seeded with `scripts/dev/seed_test_family.py`), live classification (`gpt-5.4-nano`). Password logins only; no real Google.

- 2.10 FAIL (layout) — functionally fine at 360 px: `test_dwie` picks "Rodzina testowa" on the chooser, the header reads "Rodzina: Rodzina testowa | Zmień rodzinę", switching to "Inna rodzina" shows only "Lekcja gry na pianinie (Ola w innej rodzinie)" and none of the Rodzina testowa rows. But the header does not wrap for two-family users: the page is 474 px wide at a 360 px viewport (391 px on the chooser), so "Wyloguj" sits off-screen and the page scrolls sideways (`screenshots/phone-family-testowa-index.png`, `phone-family-inna-child-list.png`, `phone-stale-tab-409-capture.png`). Single-family headers do not overflow.
- 2.11 PASS — the same session with three tabs: a capture review open in Rodzina testowa, a structured create form, and a third tab switching to Inna rodzina. "Zapisz wpis" in the stale tab → HTTP 409, the Polish page "Ta strona dotyczyła innej rodziny. Odśwież ją i spróbuj ponownie."; the stale create form → 409 as well; entry count unchanged (17 → 17), no row with the run's marker (`phone-stale-tab-409-capture.png`).
- 2.12 PASS — admin added a second membership (child "Kasia D", Inna rodzina) for `test_kasia`; her already-open session showed "Rodzina: Rodzina testowa | Zmień rodzinę" on the next request (`phone-second-membership-switch-link.png`).
- 2.13 PASS — keyboard only at 1280 and 360 px: keyboard sign-in → chooser, radios with arrow keys, "Przejdź do rodziny" with Enter, header "Zmień rodzinę" reached and activated, switched back to the other family; checklist script found no issues on the chooser, the parent list with the switcher and the child list; every stop has a visible 2px outline. At 360 px focusing "Wyloguj" scrolls the page sideways (the 2.10 overflow).
- 3.6 PASS (live) — `test_dwie` in Rodzina testowa captured "Kupić bilety do kina …" and saved it; `/entries/`, past, `/account/`, `/account/family/` and the create form contain no Inna rodzina data (sentinel, "Lekcja gry", "Obcy", "Kasia D"). Switched to Inna rodzina: child list, past, detail and account contain no Rodzina testowa data (entry titles, Kasia/Tymek/Ewa, the new capture); `/entries/` and `/account/family/` give 403; `/entries/mine/1/` (a Rodzina testowa entry) gives 404. Side note: the live model assigned that capture to Ola (the requester) although the text named nobody.
- 3.7 PASS — `test_rodzic` and `test_tymek` (one membership each) land on `/entries/` and `/entries/mine/` with the header "FamilyNotes | Konto | Wyloguj", no family name and no switcher link, no overflow at 360/320 px; the create, capture, follow-up, correction, edit, delete and child flows all ran unchanged in the other checks (`phone-single-family-test_rodzic-landing.png`, `phone-single-family-test_tymek-landing.png`). Minor: typing `/account/family/select/` directly as a single-family user shows "Należysz do kilku rodzin…" with a single option (not reachable from the UI).

## Fixes 2026-10-05

Environment: headless Chromium (Playwright, `/usr/bin/chromium-browser`) against `runserver` (DEBUG on, the browser-B SQLite DB seeded with `scripts/dev/seed_test_family.py`), password login as `test_dwie`.

- 2.10 PASS (fixed) — the header nav now has `.fn-site-nav`, whose `flex-wrap: wrap` (`family_notes/static/css/tokens.css`) lets "Rodzina: …", "Zmień rodzinę", "Konto" and "Wyloguj" wrap onto new lines. As `test_dwie`: `document.documentElement.scrollWidth` = 320 at a 320 px viewport and 360 at 360 px, on both `/entries/` and the chooser (was 474 / 391); "Wyloguj" is on-screen (right edge 122 px at 320, 315 px at 360). Regression tests: `family_notes/test_tokens_rules.py` (wrap rule) and `family_access/tests/test_family_context_accessibility.py` (two-family header renders the class). Screenshots: `screenshots/phone-family-testowa-index-320-fixed.png`, `phone-family-testowa-index-360-fixed.png`, `phone-chooser-fixed.png`.
