# Manual verification

Date: 2026-10-05

## Browser (browser agent B)

Environment: headless Chromium (Playwright 1.x, `/usr/bin/chromium-browser`) against `runserver` (DEBUG on, own SQLite DB seeded with `scripts/dev/seed_test_family.py`), live classification (`gpt-5.4-nano`). Password logins only; no real Google.

- 2.5 PASS — at 360 px as Ewa, upcoming: h2 Kasia → Tymek → Ewa → Ola → Cała rodzina, each with h3 "Z datą"/"Bez daty"; past (after adding past entries for Tymek, Ewa and family): h2 Kasia → Tymek → Ewa → Cała rodzina. No horizontal overflow; hierarchy reads clearly (`screenshots/phone-real-list-upcoming.png`, `phone-real-list-past.png`).
- 2.6 PASS — `PNA-Ola-…` re-assigned from Ola to Tymek in "Edytuj": it now appears under the Tymek group and the Ola group disappears (it was Ola's only upcoming row) (`phone-after-reassign.png`); then reassigned back.
- 2.7 PASS — `screenshots/phone-gallery-grouped-upcoming.png` (Kasia, Tymek, Marta, Cała rodzina) and `phone-gallery-grouped-past.png` (one "Cała rodzina" group, as the plan's gallery contract says).
