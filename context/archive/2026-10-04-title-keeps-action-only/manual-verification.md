# Manual verification

Date: 2026-10-05

## Code review (review agent)

Environment: code review on branch `feature/m2-improved-family-capture` (no browser).

- 1.4 PASS — `_TITLE_RULE` (with the „kasia zrobić pranie w piątek” → „Zrobić pranie” example, other people and the school subject kept) and `DATE_RULES` (Europe/Warsaw, Monday week start, bare weekday = next occurrence and +7 days on the same weekday, „w przyszłym tygodniu w <dzień>”, „dziś”, day+month without a year) read as natural, correct Polish and cover every item in Phase 1 Intent.
- 2.6 PASS — `entries/tests/test_title_cleanup.py`: every removed case strips only a name listed in `assignee_refs`, the passed `date_phrase` or a self-reference with `self_reference=True`; kept cases pin non-assignee names (Bartek, Michał, babcia, Tomek) and date phrases that are absent, blank or not at the end. The 10 tests pass.

## Browser (agent A)

Environment: headless Chromium (/usr/bin/chromium-browser) + Playwright (Python), local `runserver` on 127.0.0.1:8101 (gunicorn with `EDUVULCAN_WORKER_ENABLED=True` for 4.7/4.8), scratch SQLite seeded with `scripts/dev/seed_test_family.py`, live classification (`gpt-5.4-nano`). Today = Monday 2026-10-05.

- 3.3 PASS — as `test_rodzic`, „kasia zrobić pranie w piątek” → review: Tytuł „Zrobić pranie”, Data 2026-10-09 (the coming Friday), Dla kogo Kasia (twice, live). Saving created exactly one entry (id 15: „Zrobić pranie”, 2026-10-09, todo, Kasia). Screenshot `screenshots/3.3-review-kasia-pranie.png`.
- 3.4 PASS — „Kupić mleko” → title „Kupić mleko”, no date, unchanged from the instruction (3 live runs).
- Observation (not a listed check): the live run of „Sprawdzian dla Kasi w piątek” kept „dla Kasi” in the title, and the three-meetings batch kept the verb („Dodaj spotkanie z X”).
