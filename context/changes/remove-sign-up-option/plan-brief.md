# Remove Sign-Up Option — Plan Brief

> Full plan: `context/changes/remove-sign-up-option/plan.md`

## What & Why

S-09 (PK-02, US-02): the login page still offers allauth's "sign up" link, and `/accounts/signup/` accepts local registrations. The family is provisioned by an operator, so self-registration is noise and an attack surface. The risk is breaking provisioning: Google first sign-in must still create the user the admin later maps to a family member.

## Starting Point

There is no allauth adapter or signup setting, so allauth defaults apply and signup is open. The login override renders the sign-up link (`family_notes/templates/account/login.html:36-44`). Provisioning works like this: a person signs in with Google, allauth auto-creates a `User`, and a superuser creates the `FamilyMember` in admin. Until then the user sees only "not configured". Important coupling: allauth's social adapter delegates `is_open_for_signup` to the account adapter, so closing signup naively also blocks Google first sign-in.

## Desired End State

The login page shows only Google and the password form. `/accounts/signup/` shows a Polish "Rejestracja jest wyłączona" page and creates no user. A brand-new Google account still signs in, gets a `User`, and waits for admin mapping exactly as today.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
| --- | --- | --- | --- |
| What "remove sign-up" means | Remove the link **and** close local registration (owner-confirmed 2026-10-04) | Hiding the link alone leaves a working signup URL. | Owner |
| Google first sign-in | Keeps auto-creating a `User`; admin maps it as before (owner-confirmed 2026-10-04) | It preserves the existing provisioning flow with no operator change. | Owner |
| Mechanism | Closed account adapter plus social adapter that explicitly returns `True` | The default social adapter delegates to the account adapter and would block Google. | Research |
| Password login | Kept | US-02 covers sign-up only. | Assumed (owner to confirm) |
| Google allow-list or invitations | Not added | Family access is already gated by an admin-created `FamilyMember`. | Assumed (owner to confirm) |
| Closed page | Polish override of `account/signup_closed.html` | allauth's translated page is generic; the override adds "the family administrator creates accounts" and a login link. | Research |
| Adapter location | `family_access/auth_adapters.py` | Identity policy belongs to `family_access`; `family_notes/` only wires settings. | Research |

## Scope

**In scope:** two allauth adapters, settings wiring, a Polish closed page, removal of the login-page link, tests, and screenshots.

**Out of scope:** password login/reset removal, allow-lists or invitations, in-app member management (S-14), migrations, and cleanup of existing users.

## Architecture / Approach

`ACCOUNT_ADAPTER` → `ClosedSignupAccountAdapter` (signup `False`). `SOCIALACCOUNT_ADAPTER` → `ExternalSignInSocialAccountAdapter` (signup `True`). Family-data access is unchanged: it still requires an active `FamilyMember` (`family_access/access.py:6`). The template layer drops the link and overrides the closed page.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Close local registration, keep Google first sign-in | Server-side signup closed, Polish closed page, provisioning proven intact | Inheriting the default social adapter silently blocks new Google users |
| 2. Remove the visible sign-up option | Login page without the link, tests, screenshots | None significant |

**Prerequisites:** none (confirmed order S-01, S-02, S-20, S-03, S-04, S-05, S-06, S-07, S-08, S-09, S-17, S-14, S-15, S-16). S-14 (in-app membership management) may later replace admin mapping but does not block this.
**Estimated effort:** ~1 session across 2 phases.

## Open Risks & Assumptions

- Owner review 2026-10-04 confirmed the decisions listed under "Owner Decisions (2026-10-04)" in plan.md; remaining assumed rows stand unless the owner objects.
- Owner decisions were applied 2026-10-04. Rows still marked "Assumed" stand in for PRD Open Questions 1, 3, 12, and 20 and stand unless the owner objects.
- If the owner also wants new Google users rejected (allow-list or pre-created users only), scope grows into provisioning and the admin workflow.
- The automated social-signup test relies on allauth internals (`complete_social_login`, `SocialLogin`). If they are awkward to drive, fall back to adapter-level tests plus the manual fresh-Google-account check.

## Success Criteria (Summary)

- No sign-up option is visible or usable in the app.
- New family members can still be provisioned: a first Google sign-in followed by admin mapping works as before.
