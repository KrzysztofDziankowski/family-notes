# Remove Sign-Up Option Implementation Plan

## Overview

Roadmap-future slice S-09 (PK-02, US-02): users reaching the authentication experience must not see or be able to use a sign-up option. Family accounts are provisioned today in two steps: a person signs in with Google once, and allauth auto-creates a Django `User`; a superuser then maps that user to a `FamilyMember` in Django admin. This plan removes the visible link and closes local (username/email + password) registration. It explicitly keeps Google first sign-in able to create the `User` that admin provisioning depends on.

### Owner Decisions (2026-10-04)

- Close username/password sign-up; keep auto-creating a user on first Google sign-in, which the admin then maps to a family member. No invitation flow (owner removed invitations from S-14).
- All future-roadmap slices except removed ones are in the next milestone; confirmed order: S-01, S-02, S-20, S-03, S-04, S-05, S-06, S-07, S-08, S-09, S-17, S-14, S-15, S-16.
- Ship without feature flags and without backfilling existing data.
- No Playwright/E2E tests in this slice; browser tests will be added later.

Owner decisions from the plan review were applied 2026-10-04. Items below that the owner did not address remain assumed defaults; they stand unless the owner objects.

### Assumed Decisions

1. **Remove both the visible link and local registration.** `/accounts/signup/` shows a Polish "registration disabled" page and creates no user. Hiding only the link would leave a reachable signup URL, which does not meet "remove the option to sign up". (owner-confirmed 2026-10-04; PRD Open Question 3)
2. **Google first sign-in keeps auto-creating a Django `User`.** The existing provisioning model (sign in once, then the admin creates the `FamilyMember`) stays unchanged. Closing it too would require the admin to pre-create users and Google links, which is a bigger operator workflow change. Unmapped users still see only the non-sensitive "not configured" state. (owner-confirmed 2026-10-04; PRD Open Question 3)
3. **The password login form on `/accounts/login/` stays.** US-02 is about sign-up only, and removing password login is a separate access decision. (PRD Open Question 3)
4. **No allow-list of Google e-mails/domains is added.** Family-data access is already gated by an active `FamilyMember` (`family_access/access.py:6`). An allow-list would be a new provisioning feature. (PRD Open Question 3)
5. **The allauth social "complete sign-up" form (`/accounts/3rdparty/signup/`) stays reachable.** It is shown only within a Google sign-in when auto-signup cannot finish, for example on an e-mail collision, so it is part of first sign-in rather than a standalone option. (PRD Open Question 3)
6. **Release scope and compatibility:** settings and template change only. No migration. Existing users and memberships are unaffected. Rollback is a code-only revert. (PRD Open Questions 1, 12, 20)

## Current State Analysis

- The login page override renders a "sign up" link inside the `{% if not SOCIALACCOUNT_ONLY %}` block (`family_notes/templates/account/login.html:36-44`). With `LANGUAGE_CODE = 'pl'` (`family_notes/settings.py:444`) allauth's bundled Polish translation renders it as "Jeżeli nie masz jeszcze konta, to proszę **zarejestruj się**." (`allauth/locale/pl/LC_MESSAGES/django.po:1086-1089`), so a test must match lowercase Polish stems, not only English text.
- No `ACCOUNT_ADAPTER`/`SOCIALACCOUNT_ADAPTER` or signup settings exist. allauth defaults apply (`family_notes/settings.py:187-206`, `:298-304`, `:429-438`; django-allauth 65.19.7 in `uv.lock`). Its `DefaultAccountAdapter.is_open_for_signup` returns `True`, so `/accounts/signup/` is open.
- Critical coupling: by default, `DefaultSocialAccountAdapter.is_open_for_signup` delegates to the account adapter (`.venv/.../allauth/socialaccount/adapter.py:215-224`). If it returns `False`, `process_signup` raises `SignupClosedException` and Google first sign-in renders `account/signup_closed.html` instead of creating the user (`.venv/.../allauth/socialaccount/internal/flows/signup.py:109-111`, `.../flows/login.py:57-62`). Closing account signup alone would therefore break provisioning.
- Provisioning contract from F-01: unknown authenticated Google users get a session but no family data until a superuser creates an active `FamilyMember` (`context/archive/2026-09-23-identity-and-family-access-contract/plan.md:41`). Admin maps users by e-mail (`family_access/admin.py:15-37`).
- allauth's `account/signup_closed.html` renders in Polish via the bundled translation ("Rejestracja zamknięta / Przepraszamy, ale w tej chwili rejestracja jest zamknięta.", `allauth/locale/pl/LC_MESSAGES/django.po:1296-1301`), but it does not explain that accounts are created by the family administrator and has no link back to login. The project overrides allauth templates under `family_notes/templates/account/`.
- Existing login page tests cover Google-first ordering and `next` preservation (`family_notes/tests.py:82-101`). No test covers signup.

## Desired End State

The login page shows "Zaloguj przez Google" and the password form, with no sign-up link or text. Visiting or posting to `/accounts/signup/` shows a Polish page saying registration is disabled, with a link back to login, and creates no `User`. A brand-new Google account can still complete first sign-in. A `User` is created and lands on the "not configured" status, so a superuser can map it in admin exactly as before.

### Key Discoveries:

- Two adapters are required: a closed account adapter and a social adapter that stays open (`allauth/socialaccount/adapter.py:224`).
- Product auth policy belongs to `family_access` (identity/membership owner). `family_notes/` only wires settings (AGENTS.md: keep `family_notes/` limited to project-wide configuration).
- Template overrides live in `family_notes/templates/account/` and extend `account/base_entrance.html`.

## What We're NOT Doing

- No removal of password login, password reset, or admin login.
- No Google e-mail/domain allow-list or invitation flow.
- No in-app family/member administration (S-14).
- No change to `FamilyMember` provisioning in admin and no data migration.
- No change to the unconfigured-user status page.

## Implementation Approach

Introduce two allauth adapters in `family_access`. The account adapter closes local signup. The social adapter re-opens signup for social logins, so Google first sign-in still creates users. Wire both in settings and override `signup_closed.html` in Polish. Then remove the link from the login template. Tests prove both halves: local signup is closed (GET and POST, no user created), and a social login is still open for signup.

## Critical Implementation Details

The social adapter must override `is_open_for_signup(request, sociallogin)` to return `True` explicitly. Inheriting the default silently delegates to the closed account adapter, and every new Google user would see "registration closed". Add a regression test that would fail under that inheritance.

## Phase 1: Close Local Registration, Keep Google First Sign-In

### Overview

Change the server-side signup policy without touching the login page yet.

### Changes Required:

#### 1. Allauth adapters

**File**: `family_access/auth_adapters.py` (new)

**Intent**: Encode the sign-up policy in one auditable place: no local self-registration, while external-identity first sign-in still creates a `User`.

**Contract**:
- `ClosedSignupAccountAdapter(DefaultAccountAdapter)`: `is_open_for_signup(request)` returns `False`.
- `ExternalSignInSocialAccountAdapter(DefaultSocialAccountAdapter)`: `is_open_for_signup(request, sociallogin)` returns `True`.
- No other adapter behavior changes. A module docstring explains the coupling and that family access still requires an admin-created active `FamilyMember`.

#### 2. Settings wiring

**File**: `family_notes/settings.py` (near the existing allauth settings, ~line 187)

**Intent**: Activate the adapters.

**Contract**: `ACCOUNT_ADAPTER = 'family_access.auth_adapters.ClosedSignupAccountAdapter'`, `SOCIALACCOUNT_ADAPTER = 'family_access.auth_adapters.ExternalSignInSocialAccountAdapter'`. No other auth setting changes, and rate limits are preserved.

#### 3. Polish "registration disabled" page

**File**: `family_notes/templates/account/signup_closed.html` (new override)

**Intent**: Replace allauth's generic (translated) page with product copy in the app layout: explain that the family administrator creates accounts, and link back to login.

**Contract**:
- Extends `account/base_entrance.html`, with heading "Rejestracja jest wyłączona".
- One short paragraph: accounts are created by the family administrator; sign in with Google.
- A link to `account_login`.
- Only existing token classes; no inline styles.

#### 4. Tests

**File**: `family_access/tests/test_auth_adapters.py` (new) or `family_notes/tests.py` (next to `LoginPageTests`)

**Intent**: Prove the policy and its coupling.

**Contract**:
- GET `/accounts/signup/` returns 200 with the Polish page in `base.html`.
- POST of a valid signup payload creates no `User` and renders the closed page.
- `allauth.account.adapter.get_adapter(request).is_open_for_signup(request)` is `False`.
- `allauth.socialaccount.adapter.get_adapter(request).is_open_for_signup(request, sociallogin)` is `True` for a Google `SocialLogin`.
- A social signup through allauth's flow creates a `User` with no `FamilyMember`, and that user's `/account/` shows the unconfigured state. Drive it with allauth's `complete_social_login` and a constructed `SocialLogin`, or the allauth test utilities if available in 65.19.7. No real Google call.

### Success Criteria:

#### Automated Verification:

- Signup tests prove that GET/POST `/accounts/signup/` render the Polish closed page and create no user.
- Adapter tests prove that local signup is closed and social signup is open, and that a new social login creates an unmapped `User` that sees only the unconfigured state.
- Targeted tests pass: `uv run python manage.py test family_access family_notes`
- Django checks and migration check pass: `uv run python manage.py check`, `uv run python manage.py makemigrations --check --dry-run`

#### Manual Verification:

- With `runserver`, `/accounts/signup/` shows "Rejestracja jest wyłączona" in the app layout at phone width.
- A Google account never used with the app completes sign-in and lands on the "not configured" status; a superuser can then map it in admin and the user sees family data on the next request.

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 2: Remove the Visible Sign-Up Option

### Overview

Remove the sign-up link from the login page and prove that it is gone.

### Changes Required:

#### 1. Login template

**File**: `family_notes/templates/account/login.html`

**Intent**: Remove the "If you have not created an account yet… sign up" paragraph and its `setvar` link helpers.

**Contract**: The `{% if not SOCIALACCOUNT_ONLY %}` block keeps the divider and the password form only. Update the template comment to state that sign-up is intentionally absent. Google button order and `next` handling are unchanged.

#### 2. Login page tests

**File**: `family_notes/tests.py` (`LoginPageTests`)

**Intent**: Lock the absence of any sign-up affordance.

**Contract**: The login page response does not contain `reverse('account_signup')`, and `response.content.decode().lower()` contains none of the stems "zarejestruj", "rejestracj" or "sign up" (case-insensitive, Polish and English, so allauth's lowercase "zarejestruj się" is caught). Existing Google-first and `next` tests stay green.

### Success Criteria:

#### Automated Verification:

- Login page tests assert that no sign-up link or text is rendered, and the existing login tests stay green.
- Full suite, checks and migration check pass: `uv run python manage.py test`, `uv run python manage.py check`, `uv run python manage.py makemigrations --check --dry-run`

#### Manual Verification:

- At 360 px and 1280 px the login page shows the Google button and password form with no sign-up option; screenshots are saved under `context/changes/remove-sign-up-option/screenshots/`.

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding.

---

## Testing Strategy

### Unit Tests:

- Adapter `is_open_for_signup` results for account vs social logins.

### Integration Tests:

- `/accounts/signup/` GET/POST closed, with no `User` created.
- Social first sign-in creates an unmapped `User`, and the unconfigured status page denies family data.
- The login page has no sign-up affordance.

### Manual Testing Steps:

1. Open `/accounts/login/` and confirm there is no sign-up link.
2. Open `/accounts/signup/` and confirm the Polish closed page.
3. Sign in with a fresh Google account, map it in admin, and confirm access.

## Performance Considerations

None.

## Migration Notes

No schema or data change. Users created through earlier local signups (if any) remain and can still log in with a password. Removing them is an operator decision outside this plan. Rollback is reverting the settings, adapter, and template commit.

## References

- Roadmap item: `context/foundation/roadmap-future.md` (S-09)
- PRD: `context/foundation/prd-v2.md` (PK-02, US-02, Open Question 3)
- Provisioning contract: `context/archive/2026-09-23-identity-and-family-access-contract/plan.md:41`
- Login override: `family_notes/templates/account/login.html:36`
- allauth Polish copy: `.venv/lib/python3.10/site-packages/allauth/locale/pl/LC_MESSAGES/django.po:1086-1089`, `:1296-1301`
- allauth coupling: `.venv/lib/python3.10/site-packages/allauth/socialaccount/adapter.py:215`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Close Local Registration, Keep Google First Sign-In

#### Automated

- [x] 1.1 Signup tests prove that GET/POST `/accounts/signup/` render the Polish closed page and create no user.
- [x] 1.2 Adapter tests prove that local signup is closed and social signup is open, and that a new social login creates an unmapped `User` that sees only the unconfigured state.
- [x] 1.3 Targeted tests pass: `uv run python manage.py test family_access family_notes`
- [x] 1.4 Django checks and migration check pass: `uv run python manage.py check`, `uv run python manage.py makemigrations --check --dry-run`

#### Manual

- [ ] 1.5 With `runserver`, `/accounts/signup/` shows "Rejestracja jest wyłączona" in the app layout at phone width.
- [ ] 1.6 A Google account never used with the app completes sign-in and lands on the "not configured" status; a superuser can then map it in admin and the user sees family data on the next request.

### Phase 2: Remove the Visible Sign-Up Option

#### Automated

- [ ] 2.1 Login page tests assert that no sign-up link or text is rendered, and the existing login tests stay green.
- [ ] 2.2 Full suite, checks and migration check pass: `uv run python manage.py test`, `uv run python manage.py check`, `uv run python manage.py makemigrations --check --dry-run`

#### Manual

- [ ] 2.3 At 360 px and 1280 px the login page shows the Google button and password form with no sign-up option; screenshots are saved under `context/changes/remove-sign-up-option/screenshots/`.
