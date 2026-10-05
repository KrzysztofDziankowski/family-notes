# Manual verification

Date: 2026-10-05

## Code review (review agent)

Environment: code review on branch `feature/m2-improved-family-capture` (no browser).

- 1.4 PASS — `CORRECTION_INSTRUCTIONS` states the preserve-unmentioned rule („Zmień tylko te pola, o których mówi poprawka … Każde inne pole skopiuj bez zmian z obecna_propozycja”), the correction-only relative shift from the proposal date, and ends with the shared `DATE_RULES` unchanged (Assumed Decision 6). The Polish is natural and correct.

## Browser (agent A)

Environment: headless Chromium (/usr/bin/chromium-browser) + Playwright (Python), local `runserver` on 127.0.0.1:8101 (gunicorn with `EDUVULCAN_WORKER_ENABLED=True` for 4.7/4.8), scratch SQLite seeded with `scripts/dev/seed_test_family.py`, live classification (`gpt-5.4-nano`). Today = Monday 2026-10-05.

- 2.3 PASS — 360 px, live: „Kasia ma dentystę jutro o 16:00” → review (Ma dentystę, 2026-10-06, 16:00, Kasia). After „zmień datę na 15 października” + Popraw (1.5 s): notice „Zaktualizowano: data.”, only the date changed to 2026-10-15. Saving created one entry with 2026-10-15 16:00 Kasia. No horizontal scroll. Screenshot `screenshots/2.3-corrected-date-360.png`.
- 3.3 PASS — `corrected` and `correction_failed` gallery sections at 360 px: no element off-screen, no clipped overflow, no page scroll sideways. Screenshots `screenshots/3.3-*-360.png`.
- Observation: in a separate desktop run, „zmień na pojutrze” on a proposal dated tomorrow left the date unchanged and kept the text in the box (correction not applied). Live and not part of a listed check.
