# Manual verification

Date: 2026-10-05

## Browser (browser agent B)

Environment: headless Chromium (Playwright, `/usr/bin/chromium-browser`) against `runserver` (DEBUG on, own SQLite DB seeded with `scripts/dev/seed_test_family.py`), live classification (`gpt-5.4-nano`). Password logins only; no real Google.

- 2.9 PASS — at 360 px Ewa promoted Tymek ("Zmieniono rolę: Tymek jest teraz rodzicem."); Tymek's sign-in lands on `/entries/` "Wpisy rodziny" with "Nowy wpis". Demoted back ("… jest teraz dzieckiem. Tokeny automatyzacji tej osoby zostały unieważnione."); Tymek's next request goes to `/entries/mine/` with the Polish notice "Inny rodzic lub administrator rodziny zmienił Twoją rolę na „Dziecko”…", and `/entries/` gives 403 (`screenshots/phone-role-form-Tymek-Rodzic.png`, `phone-promoted-child-parent-index.png`, `phone-demoted-notice.png`).
- 2.10 PASS — JavaScript disabled: sole parent `test_obcy` sees the last-parent explanation and no role form; Ewa's self-demotion disclosure shows the warning and the "Rozumiem…" checkbox; submitting without it re-renders with "Błąd:" title, the error summary and "Potwierdź, że chcesz zrezygnować z uprawnień rodzica." under the checkbox (aria-describedby → `id_confirm_self_error`); with it ticked Ewa lands on `/entries/mine/` with "Twoja rola to teraz „Dziecko”…" (`nojs-last-parent.png`, `nojs-self-demotion-confirm.png`, `nojs-self-demotion-missing-confirm.png`, `nojs-self-demoted-child-home.png`).
- 2.11 PASS — keyboard only at 360 px: "Zmień rolę" summary, radios (Space/arrow keys), the self-demotion checkbox and submit all reachable with a visible 2px focus outline; promote and demote completed by keyboard; checklist script found no issues on the open role form, the self-demotion invalid state and the last-parent page (`kb-self-demotion-invalid-360.png`).
- 2.14 FAIL — runbook step 2 cannot be followed: no `membership_event=role_changed` (or `deactivated`) line is ever logged, because `family_access` falls under the root logger at WARNING (`family_notes/settings.py` LOGGING; `logging.getLogger('family_access.membership').isEnabledFor(INFO)` is False) while the service logs at INFO. Steps 3–4 work: in Django admin, Family members filtered by "Rodzina testowa", member 1 (Ewa, demoted to Child by her own self-demotion) set back to Parent and saved; Ewa's next sign-in lands on the parent index (`runbook-admin-restore-role.png`).

## Fixes 2026-10-05

Environment: headless Chromium (Playwright, `/usr/bin/chromium-browser`) against `runserver` (DEBUG on, the browser-B SQLite DB seeded with `scripts/dev/seed_test_family.py`), password login as `test_dwie`.

- 2.14 PASS (fixed) — `LOGGING` now sets `family_access` to INFO with propagation to the root console handler (mirroring `entries.classification`). Promoting and demoting Tymek in the browser printed, in the server output: `INFO family_access.membership membership_event=role_changed family=1 member=3 actor=5 old_role=child new_role=parent` and the reverse line — ids only, no names. Runbook step 2 can now be followed; steps 3–4 were already PASS. Regression test: `family_access/tests/test_membership_logging.py` (listens on the root logger without lowering levels, unlike `assertLogs`). Note: the runbook (plan.md, not edited) names the S-14 event `membership_event=deactivated`, but the code logs `membership_event=member_deactivated` (also `member_reactivated`, `member_renamed`); searching for `membership_event=` plus `family=<id>` finds all of them.
