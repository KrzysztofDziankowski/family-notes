# Manual verification

Date: 2026-10-05

## Code review (review agent)

Environment: code review on branch `feature/m2-improved-family-capture` (no browser).

- 1.5 PASS — scratch SQLite migrated to `entries 0006`, six raw-SQL entries inserted (test/quiz/class_test/homework, grade, non-school; manual + eduvulcan, with and without date/time/submission_key), then `migrate entries 0007`: the only new column is `school_subject varchar(100) DEFAULT '' NOT NULL`; every row has `school_subject = ''` and every other column is byte-identical to the pre-migration snapshot (6/6 rows).

## Browser (agent A)

Environment: headless Chromium (/usr/bin/chromium-browser) + Playwright (Python), local `runserver` on 127.0.0.1:8101 (gunicorn with `EDUVULCAN_WORKER_ENABLED=True` for 4.7/4.8), scratch SQLite seeded with `scripts/dev/seed_test_family.py`, live classification (`gpt-5.4-nano`). Today = Monday 2026-10-05.

- 3.4 PASS — `/entries/_states/` at 360 px: `proposal` shows „Element szkolny” select and „Przedmiot” field full-width, `follow_up_subject` shows „Podaj przedmiot.”, `question_subject` asks „Z jakiego przedmiotu jest „Sprawdzian”?”; no element off-screen or clipped. Screenshots `screenshots/3.4-*-360.png`.
- 3.5 DEVICE-ONLY (left [ ]) — desktop-emulated PASS at 360 px: „Sprawdzian dla Kasi w piątek” → subject question → „z geografii” → review shows Przedmiot „geografia” → saved entry detail shows „Przedmiot geografia”. Real Android Chrome still needed. Observation: the live title kept „dla Kasi” („Sprawdzian dla Kasi”), so the question read „Z jakiego przedmiotu jest „Sprawdzian dla Kasi”?”.
- 4.7 PASS — automation token issued in the scratch DB; POST `/api/automation/notifications/` with title „Sprawdzian”, message „Kasia Testowa: sprawdzian z biologii 09.10” → 202; the worker converted it (status `processed`) into entry „Sprawdzian z biologii”, 2026-10-09, school_item `test`, subject `biologia`; parent detail and child detail both show „Przedmiot biologia”. Screenshots `screenshots/4.7-*.png`.
- 4.8 PASS — seeded school entry „Sprawdzian z matematyki” (school_item `test`, subject empty): parent `/entries/1/` and child `/entries/mine/1/` render 200 with „sprawdzian” and no Przedmiot row; `GET /api/automation/entries/` returns it with `"school_subject": null`. Note: the row was created after migration 0007 (empty subject), which matches a migrated pre-existing row (see 1.5). Screenshots `screenshots/4.8-*.png`.
