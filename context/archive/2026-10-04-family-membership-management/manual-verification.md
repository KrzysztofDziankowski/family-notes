# Manual verification

Date: 2026-10-05

## Code review (review agent)

Environment: code review on branch `feature/m2-improved-family-capture` (no browser).

- 1.7 PASS — `family_access/membership.py` has two logger calls: `_log_event` (`membership_event`, family, member and actor ids) and the role change (ids plus the fixed `old_role`/`new_role` enum values). Neither logs an email or a display name. Its callees (`is_parent`, `normalize_child_name`, the models) do not log.

## Browser (browser agent B)

Environment: headless Chromium (Playwright, `/usr/bin/chromium-browser`) against `runserver` (DEBUG on, own SQLite DB seeded with `scripts/dev/seed_test_family.py`), live classification (`gpt-5.4-nano`). Password logins only; no real Google. Operator = a local superuser created for this run; the "Google first sign-in" user was simulated by a password user with no FamilyMember (`qa_nowy_b`).

- 2.10 PASS — at 360 px as Ewa: renamed Kasia → "Kasia QA" ("Zapisano nowe imię: Kasia QA."), duplicate "Tymek" refused with "W rodzinie jest już osoba o takim imieniu." and a "Błąd:" title, renamed back; deactivated Tymek via the "Wyłącz dostęp" disclosure (Tymek then lands on the "nie jest jeszcze skonfigurowane" account page) and reactivated him (Tymek back on `/entries/mine/`). Self guard shown on Ewa's own row. As sole parent `test_obcy`: self guard on the list, a forced self-deactivate POST re-renders with the role="alert" guard error, and the edit page shows the last-parent explanation. No horizontal overflow (`screenshots/phone-member-list.png`, `phone-after-rename.png`, `phone-deactivate-confirm.png`, `phone-after-deactivate.png`, `phone-guard-error-sole-parent.png`, `phone-edit-last-parent.png`). Note: the list-level `last-parent-guard` row text cannot appear for another person in-app (the acting parent always counts as a remaining parent); it shows only in the `/account/family/_states/` gallery.
- 2.11 PASS — keyboard only at 360 px: reached "Członkowie rodziny" from the account page, renamed with Enter in the field, invalid empty name gave "Błąd:" title, the error-summary link moved focus to the field, disclosure summary and "Wyłącz dostęp"/"Przywróć dostęp" buttons operated with Enter. Checklist script (lang, title, skip link first, one main/h1, heading order, names, unique IDs, valid aria refs, no positive tabindex, labels, error containers, visible 2px focus at every tab stop, no trap) found no issues on the list, edit and edit-invalid pages.
- 2.12 PASS — admin "Family members → Dodaj" for `qa_nowy_b` (child "Nowy QA", Rodzina testowa): Ewa's open member list shows "Nowy QA" on reload, and `qa_nowy_b`'s already-open session moves from the not-configured account page to `/entries/mine/` on its next request (`screenshots/admin-member-added.png`, `phone-member-list-after-admin-add.png`).

Related finding (for 1.7, not changed here): with the current `LOGGING`, `family_access.membership` has effective level WARNING, so the INFO `membership_event=…` lines are never printed (no lines in the server log after renames, (de)activations and role changes).
