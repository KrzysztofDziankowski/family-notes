# Manual verification

Date: 2026-10-05

## Code review (review agent)

Environment: code review on branch `feature/m2-improved-family-capture` (no browser).

- 1.4 PASS — `MULTI_INSTRUCTIONS` inherits `DATE_RULES` through `INSTRUCTIONS` (it is not appended twice) and adds the one-entry-per-date split („dziś, jutro i w poniedziałek” to trzy wpisy, a per-entry date_source, one matter = one entry). `DATE_RULES` matches every item in Assumed Decision 1. The Polish is natural.

## Browser (agent A)

Environment: headless Chromium (/usr/bin/chromium-browser) + Playwright (Python), local `runserver` on 127.0.0.1:8101 (gunicorn with `EDUVULCAN_WORKER_ENABLED=True` for 4.7/4.8), scratch SQLite seeded with `scripts/dev/seed_test_family.py`, live classification (`gpt-5.4-nano`). Today = Monday 2026-10-05.

- 2.4 PASS — 360 px, live: „Dodaj spotkanie z X dziś, jutro i w przyszłym tygodniu w poniedziałek o 18:00” → „Sprawdź wpisy (3)”, all ticked, 18:00, dates 2026-10-05, 2026-10-06, 2026-10-12 (as Assumed Decision 1 says for Monday 2026-10-05). Unticking Wpis 2 and saving created exactly two entries (05.10 and 12.10), both listed in „Dodano wpisy (2)”. Screenshots `screenshots/2.4-*.png`. Observation: the title was „Dodaj spotkanie z X”, not „Spotkanie z X” as in the plan's example.
- 3.3 PASS — 360 px, live: „zmień godzinę na 19:00” in Wpis 2's „Popraw tekstem” (1.8 s) changed only Wpis 2's time to 19:00. Saving created three entries: 05.10 18:00, 06.10 19:00, 12.10 18:00. Screenshot `screenshots/3.3-batch-second-corrected-360.png`.
- 4.3 PASS — `batch`, `batch_duplicate`, `batch_missing`, `batch_invalid`, `batch_corrected`, `batch_saved`, `too_many` at 360 px: no element off-screen or clipped, no sideways page scroll. Screenshots `screenshots/4.3-*-360.png`.
