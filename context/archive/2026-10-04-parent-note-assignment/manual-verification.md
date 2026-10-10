# Manual verification

Date: 2026-10-05

## Code review (review agent)

Environment: code review on branch `feature/m2-improved-family-capture` (no browser).

- 3.7 PASS — the `entries/classification/openai_backend.py` module docstring lists the parent's display name sent as `autor_polecenia` (own capture and correction only) and records „S-07 (owner-approved 2026-10-04)”.

## Browser (browser agent B)

Environment: headless Chromium (Playwright 1.x, `/usr/bin/chromium-browser`) against `runserver` (DEBUG on, own SQLite DB seeded with `scripts/dev/seed_test_family.py`), live classification (`gpt-5.4-nano`). Password logins only; no real Google. Second parent of "Rodzina testowa" = Ola (`test_dwie`).

- 2.3 PASS — at 360 px as Ewa, "Nowy wpis" created `PNA-Ewa-…` (Dla kogo: Ewa) and `PNA-Ola-…` (Dla kogo: Ola); each sits under its own parent group on `/entries/` and the detail shows "Dla kogo: Ewa" / "Dla kogo: Ola" (`screenshots/phone-detail-assigned-ewa.png`, `phone-detail-assigned-ola.png`, `phone-list-two-parent-assignees.png`).
- 2.4 PASS (live) — "Ola musi odebrać paczkę z poczty w piątek" → review title "Odebrać paczkę z poczty", Dla kogo pre-selected "Ola"; saved entry is assigned to Ola (DB check: role parent) (`phone-capture-review-other-parent.png`, `phone-capture-saved-other-parent.png`).
- 2.5 PASS — as `test_kasia` and `test_tymek`, none of the parent-assigned notes (both PNA notes, the 2.4 and 3.6 captures) appear in "Moje wpisy" upcoming or past; `/entries/mine/<id>/` returns 404 for each.
- 2.6 PASS — `screenshots/phone-gallery-list-upcoming.png` (360 px, `list_upcoming` section; shows the synthetic parent "Marta" group). Full gallery: `phone-gallery-full.png`.
- 3.6 PASS (live, first try) — "dla mnie: kupić mleko" as Ewa → review title "Kupić mleko", Dla kogo "Ewa"; saved entry assigned to Ewa (`phone-capture-review-self-reference.png`, `phone-capture-saved-self-reference.png`).
