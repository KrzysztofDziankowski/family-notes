# Future Roadmap: Owner Decisions

> Owner answers given 2026-10-04 to the questions raised while planning `roadmap-future.md`.
> Applied to `roadmap-future.md` and to each plan's "Owner Decisions" / "Decisions" section.
> Plan defaults the owner did not address stand unless the owner objects.

## Decided

- **Scope and order:** every remaining slice is in the next milestone, in the order S-01, S-02, S-03, S-04, S-05, S-06, S-07, S-08, S-09, S-17, S-14, S-15, S-16.
- **Removed (do not implement):** S-10 token self-service, S-11 kiosk, S-12 external integrations, S-13 direct EduVulcan reading, S-18 faster classification, S-19 zero retention, and in-app member invitations (adding members stays in Django admin).
- **Delivery:** no feature flags, no backfill; Playwright E2E tests come later.
- **S-01:** school subject is free text for now; an enum may follow.
- **S-02:** built-in diminutive dictionary for now.
- **S-03 / S-04:** correction only before saving; batch save is all-or-nothing; relative dates in Europe/Warsaw, "w przyszłym tygodniu w poniedziałek" = Monday of next calendar week.
- **S-05:** Enter submits on the phone keyboard too.
- **S-06:** installable PWA; push notifications later.
- **S-08:** children first, then each parent, then "Cała rodzina".
- **S-09:** close username/password sign-up; first Google sign-in still creates a user that the admin maps to a family member.
- **S-14–S-16:** every active parent is a manager; operator creates families in admin; family context in the session with a chooser; a parent cannot deactivate themselves; a person may be a parent in one family and a child in another.
- **S-06 PWA identity:** name "FamilyNotes", placeholder "FN" icon, Chrome's own install prompt, Android verified (iOS best effort).
- **S-17:** WCAG 2.2 AA.
- **S-20:** title keeps only the action ("kasia zrobić pranie w piątek" → "Zrobić pranie", Friday, Kasia); the school subject stays in the title; requires S-02.

## Plan-review decisions (2026-10-04)

- Apply every technical review fix as recommended (54 findings).
- S-01: on edit, the subject is required only if the entry already had one or the school kind is set/changed; always required on capture and create.
- Dates: a bare weekday said on that weekday means next week's (e.g. "w piątek" on a Friday = +7 days).
- S-03: corrections may change school type and subject; pressing "Zapisz wpis" with an unapplied correction is refused with a message.
- S-05: Enter in the "Popraw opis" box runs "Popraw".
- S-06: promise only that the service worker stores no family data (no `no-store` headers).
- S-07: "dla mnie" / "mi" / "ja" assigns the entry to the requesting parent; the requester's name is sent to classification on capture and on S-03 corrections ("przypisz mnie"), not on follow-ups or EduVulcan.
- S-08: grouped list replaces the date list, no toggle.
- S-14: any parent may reactivate a deactivated parent after a confirmation.
- S-15: one parent may still demote another; the demoted parent sees a notice, and the operator has a recovery runbook.

## Still open

- **Activation:** M-2 can be adopted into `roadmap.md` only after M-1 `first-family-capture-loop` is finished or abandoned.
