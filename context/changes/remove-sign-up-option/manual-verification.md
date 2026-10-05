# Manual verification

Date: 2026-10-05

## Browser (browser agent B)

Environment: headless Chromium (Playwright 1.x, `/usr/bin/chromium-browser`) against `runserver` (DEBUG on, own SQLite DB seeded with `scripts/dev/seed_test_family.py`), live classification (`gpt-5.4-nano`). Password logins only; no real Google.

- 1.5 PASS — `/accounts/signup/` returns 200 with title "Rejestracja jest wyłączona | FamilyNotes", the app header and skip link, the explanation and "Wróć do logowania" at 360 px and 1280 px (`screenshots/signup-closed-360.png`, `signup-closed-1280.png`).
- 1.6 DEVICE-ONLY — needs a Google account never used with the app.
- 2.3 PASS — login page at 360 px and 1280 px shows "Zaloguj przez Google" and the password form; no sign-up text and no link to `/accounts/signup/` (`screenshots/login-360.png`, `login-1280.png`).
