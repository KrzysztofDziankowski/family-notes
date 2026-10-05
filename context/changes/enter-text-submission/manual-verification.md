# Manual verification

Date: 2026-10-05

## Browser (agent A)

Environment: headless Chromium (/usr/bin/chromium-browser) + Playwright (Python), local `runserver` on 127.0.0.1:8101 (gunicorn with `EDUVULCAN_WORKER_ENABLED=True` for 4.7/4.8), scratch SQLite seeded with `scripts/dev/seed_test_family.py`, live classification (`gpt-5.4-nano`). Today = Monday 2026-10-05.

- 1.6 PASS — Enter on the empty box and on whitespace: 0 POSTs. Shift+Enter: newline added, 0 POSTs. Six keydowns of Enter without keyup (held Enter, auto-repeat) on „Kupić mleko”: exactly one POST to `/entries/new/` → review.
- 1.7 PASS — subject question („Z jakiego przedmiotu jest „Sprawdzian”?”): Enter in the answer posted once to `/entries/answer/` with no `action=skip`. The submit had no submitter (default = Dalej). The answer was classified → review.
- 1.9 PASS — JS disabled: Enter adds a newline and sends nothing in capture, question, review „Popraw opis” and the batch „Popraw tekstem” box. No `[data-enter-hint]` is visible. Rozpoznaj, Dalej, Popraw and batch Popraw submit through their buttons. No entries are saved.
- 1.10 PASS — Enter in „Tytuł” adds a newline and sends nothing on review, `/entries/create/` and `/entries/3/edit/`. The DB is unchanged.
- 1.12 PASS — Empty „Popraw opis” + Enter: 0 POSTs. „zmień datę na 15 października” + Enter: one POST to `/entries/correct/` with `action=correct`. The revised proposal is shown („Zaktualizowano: data.”, 2026-10-15). 0 entries are saved.
- 1.8 DEVICE-ONLY (Gboard). 2.6 DEVICE-ONLY (production).
