# Manual verification

Date: 2026-10-05

## Browser (agent A)

Environment: headless Chromium (/usr/bin/chromium-browser) + Playwright (Python), local `runserver` on 127.0.0.1:8101 (gunicorn with `EDUVULCAN_WORKER_ENABLED=True` for 4.7/4.8), scratch SQLite seeded with `scripts/dev/seed_test_family.py`, live classification (`gpt-5.4-nano`). Today = Monday 2026-10-05.

- 3.6 PASS — `question_ambiguous_member` at 360 px: „Rozpoznano: wydarzenie „Dentysta”” / „Której osoby dotyczy „Dentysta”?”, the answer textarea spans the width and „Dalej” / „Pomiń” are reachable; nothing clipped. Screenshot `screenshots/3.6-question-ambiguous-member-360.png`.
- 2.6 DEVICE-ONLY — the seeded test family has no „Hanna”, so the live „Hania” check was not run.
- 1.3 owner-only (not run). 3.7 DEVICE-ONLY.
