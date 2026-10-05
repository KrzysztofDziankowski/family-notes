# Manual verification

Date: 2026-10-05

## Browser (agent A)

Environment: headless Chromium (/usr/bin/chromium-browser) + Playwright (Python), local `runserver` on 127.0.0.1:8101 (gunicorn with `EDUVULCAN_WORKER_ENABLED=True` for 4.7/4.8), scratch SQLite seeded with `scripts/dev/seed_test_family.py`, live classification (`gpt-5.4-nano`). Today = Monday 2026-10-05.

- 1.7 PASS — The capture POST was delayed 12 s through Playwright routing (stand-in for throttling). At +0.1 s: form `aria-busy=true`, running panel visible, counter „0 s”. The counter then read 1 s, 3 s and 6 s. At +11.5 s: slow panel („Trwa to dłużej niż zwykle…”). The next page is review.
- 1.8 PASS — Answer POST delayed 5 s. Enter → `aria-busy=true`, running panel, textarea read-only. Three more Enters plus clicks on Dalej and Pomiń while busy → still one POST. Clicking Dalej → busy with the running panel. Pomiń → no busy, no panel, `action=skip` posted.
- 1.9 PASS — With `context.set_offline(True)`, tapping Rozpoznaj and pressing Enter are both blocked (`defaultPrevented`, 0 POSTs). The text stays and the offline panel shows. Back online, Enter (run 1) and tapping (run 2) each post once → review.
- 1.10 PASS — after a completed classification, `go_back()` gives a capture page that is not busy: no visible state panel, elapsed hidden, the text is kept and not read-only, and the button is not busy.
- 1.12 PASS — Popraw click and Enter in „Popraw opis” each show the running indicator (busy). „Zapisz wpis” shows nothing (request aborted, nothing saved). The first correct POST was held 45 s; the stalled panel appeared (~35 s), and „Spróbuj ponownie” re-posted to `/entries/correct/` with `action=correct` → revised review (date 15.10). Entry count unchanged.
- 2.8 PASS — SW `/sw.js` activated, scope `/`. `Page.getInstallabilityErrors` is empty in a persistent profile; the incognito context reports only `in-incognito`. Manifest has no errors. After browsing entries/detail/list and running a classification, Cache Storage `familynotes-shell-10xdev` holds only `/offline/`, `pico.min.css`, `tokens.css` and `icon-192.png`.
- 2.9 PASS — offline navigation to `/entries/` shows „Brak połączenia | FamilyNotes” with both stylesheets applied (styled notice panel). Back online, „Spróbuj ponownie” loads „Wpisy rodziny”. Screenshot `screenshots/2.9-offline-page-desktop.png`.
- 2.10 PASS — After the parent saw the offline page, logged out and logged in as `test_kasia` → `/entries/mine/` „Moje wpisy” with no parent content (no „Dodaj wpis”, „Wpisy rodziny”, sibling or other-family entries); `/` also → `/entries/mine/`. Child offline → offline page; „Spróbuj ponownie” and „Strona główna” after reconnecting → `/entries/mine/`, still no parent content.
- 3.6 PASS — the five `progress_*` gallery sections and the offline page at 360 px: no clipping or sideways scroll, readable copy, spinner visible in the Rozpoznaj button (running/slow), and „Spróbuj ponownie” is reachable (stalled/connection_lost). Screenshots `screenshots/3.6-*-360.png`.
- 3.7–3.12 DEVICE-ONLY.
