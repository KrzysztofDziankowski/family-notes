# Identity and Family Access Contract Implementation Plan

## Overview

Implement the F-01 foundation for FamilyNotes: family members sign in through Google OAuth, operators configure the single MVP family through Django admin, and future family-data paths get a reusable access contract. This plan establishes identity, role, and family-scope invariants without building entry CRUD, classification UI, or in-app family administration.

## Current State Analysis

FamilyNotes is currently a small Django scaffold. Django auth and session middleware are installed, but no external identity provider, family membership model, product app, admin URL, or family access helper exists yet. The roadmap makes this change the first foundation because every future entry and classification path depends on knowing the current user's family membership and role.

## Desired End State

After this plan is complete, Google-authenticated users can sign in, superusers can configure the single MVP family and its members through Django admin, and application code can ask a central access contract whether the current user is a parent, an assigned child, or outside the configured family. A minimal protected account/status page verifies login and membership state before product entry UI exists.

### Key Discoveries:

- Django auth apps and middleware are already configured in `family_notes/settings.py`, but no external provider or role model is wired.
- Product code should live outside `family_notes/`; project settings and URL composition stay there per `AGENTS.md`.
- The PRD fixes one preconfigured five-person family, preassigned parent/child roles, no in-app family administration, and no multi-family UX for the MVP.
- Shape notes name Google accounts as the preferred identity provider.
- Prior deployment checks intentionally expected `/admin/` to return 404; this plan intentionally changes that contract and must update tests/docs accordingly.

## What We're NOT Doing

- No family entry, todo, event, note, or classification model.
- No parent CRUD screens, child dashboard, or family dashboard.
- No in-app family member or role management for normal users.
- No support for multiple families in the user experience.
- No custom OAuth implementation.
- No committed real family email addresses, names, OAuth client IDs, or OAuth secrets.
- No read-only kiosk/token access.

## Implementation Approach

Use Django's built-in `User` as the authentication user and add a dedicated `family_access` app for local family membership and access rules. Add `django-allauth[socialaccount]` for Google OAuth, expose `/accounts/` for allauth flows, expose `/admin/` for superuser-only setup, and add a small protected account/status page. Future slices must call the central access helpers rather than duplicating role or family-scope logic in views.

## Critical Implementation Details

This plan deliberately reopens the old `/admin/` 404 deployment contract. The implementer must update the existing root-route/admin test and deployment documentation so production admin exposure is an intentional, superuser-only setup surface, not a regression.

Unknown authenticated Google users are not automatically admitted into the family. They may have a Django session, but the app must show only a non-sensitive not-configured state and deny all family-data access until a superuser creates an active `FamilyMember` record.

## Phase 1: Google Auth and Admin Wiring

### Overview

Add the external identity dependency and configure Django routes/settings so Google OAuth and Django admin become available without storing secrets in source.

### Changes Required:

#### 1. Dependency and lockfile

**File**: `pyproject.toml`, `uv.lock`

**Intent**: Add `django-allauth[socialaccount]` so the project uses a maintained Django OAuth integration instead of custom OAuth code.

**Contract**: `uv sync` installs allauth with social account support. The dependency must remain compatible with Python 3.10+ and Django 5.2.

#### 2. Django settings

**File**: `family_notes/settings.py`

**Intent**: Enable allauth, Google social auth, and admin-supporting settings using environment-backed provider credentials.

**Contract**: Settings include the required allauth apps, Google provider app, allauth middleware, allauth authentication backend, login/logout redirects, and Google provider configuration using `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET`. Missing OAuth credentials must not break tests that do not execute a real Google OAuth flow.

#### 3. Root URL composition

**File**: `family_notes/urls.py`

**Intent**: Expose account and admin routes while preserving the home and health endpoints.

**Contract**: Route `/accounts/` includes allauth URLs, `/admin/` exposes Django admin, `/account/` or an equivalent protected product route points to the minimal membership status view, and `/healthz/` remains public.

#### 4. Admin deployment documentation

**File**: `context/changes/deployment/deployment-plan.md`, `context/changes/deployment/mikrus-runbook.md`

**Intent**: Replace the old production acceptance expectation that `/admin/` returns 404 with the new superuser-only setup expectation.

**Contract**: Deployment docs state that `/admin/` is intentionally exposed, requires HTTPS, must be accessible only to active superusers, and must not be used by normal family members.

### Success Criteria:

#### Automated Verification:

- `uv sync` completes with the new locked auth dependency.
- `uv run python manage.py check` passes.
- `uv run python manage.py makemigrations --check --dry-run` shows only expected migration state for later phases.
- Existing home and health tests still pass after route changes.
- Admin route tests assert unauthenticated users cannot enter admin and active superusers can reach it.

#### Manual Verification:

- Operator can identify the Google OAuth redirect URI needed for provider setup.
- Production documentation no longer claims `/admin/` must return 404.
- No provider secret or real family identity appears in tracked files.

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 2: Family Membership Schema and Admin Setup

### Overview

Create the local data contract that maps authenticated Django users into the single configured family with preassigned parent/child roles.

### Changes Required:

#### 1. Product app

**File**: `family_access/apps.py`, `family_access/models.py`, `family_access/admin.py`, `family_access/migrations/`

**Intent**: Add an owning app for family identity and access code, keeping product models out of `family_notes/`.

**Contract**: App label is `family_access`, installed in settings, and owns the `Family` and `FamilyMember` models plus their migrations and admin registration.

#### 2. Family model

**File**: `family_access/models.py`

**Intent**: Represent the single configured MVP family explicitly so future entry queries can always carry a family scope.

**Contract**: `Family` has a human-readable name, active flag, created/updated timestamps, and string representation. The model does not expose multi-family UX, but it does allow tests and future entries to reference a family row.

#### 3. FamilyMember model

**File**: `family_access/models.py`

**Intent**: Bind a Django `User` to one family with a preassigned role and display identity.

**Contract**: `FamilyMember` links `user` and `family`, stores role choices `parent` and `child`, display name, active flag, timestamps, and enforces one active membership per user for the MVP. Normal family members are not automatically staff or superusers.

#### 4. Admin setup surface

**File**: `family_access/admin.py`

**Intent**: Let superusers configure the single family and its members without creating an in-app administration UI.

**Contract**: Admin registrations allow superusers to manage `Family` and `FamilyMember`; non-superuser staff are not part of the MVP setup path. Admin list/search fields make it practical to map users by email/display name without exposing secrets.

### Success Criteria:

#### Automated Verification:

- `uv run python manage.py makemigrations --check --dry-run` confirms migrations are present after model creation.
- `uv run python manage.py test` covers `Family` and `FamilyMember` creation, role choices, string output, active membership uniqueness, and user-to-membership mapping.
- Tests prove parent and child users do not receive admin access unless separately made superusers.

#### Manual Verification:

- Superuser can create the MVP family and assign five users as parent/child members in Django admin.
- Normal parent/child accounts cannot enter Django admin.
- Admin setup flow does not require committing family member names or emails.

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 3: Access Helpers and Account Status Route

### Overview

Add the reusable access contract that later entry/classification slices must call, plus a minimal protected route for manual verification of login and membership state.

### Changes Required:

#### 1. Central access helpers

**File**: `family_access/access.py`

**Intent**: Keep family-scope and role rules in one place so future views do not reimplement authorization checks.

**Contract**: Helper functions provide current active membership lookup, parent check, family queryset scoping, assigned-child read checks, and explicit unauthenticated/no-membership denial behavior. Functions must be easy to unit-test without real OAuth.

#### 2. Account/status view

**File**: `family_access/views.py`, `family_access/urls.py`, `family_notes/urls.py`

**Intent**: Provide a protected route that proves a signed-in user is either configured as a family member or safely denied family data.

**Contract**: Authenticated users with active membership see their display name and role. Authenticated users without membership see a generic not-configured message. Unauthenticated users are redirected to login or denied consistently with Django/allauth conventions.

#### 3. Templates

**File**: `family_access/templates/family_access/account_status.html`

**Intent**: Render membership status without starting the future family dashboard.

**Contract**: The page contains no family entries, classification input, or role-management controls. It displays only the current user's setup state and safe navigation actions such as login/logout.

### Success Criteria:

#### Automated Verification:

- Unit tests cover helper behavior for parent, assigned child, other child, inactive membership, unknown authenticated user, and unauthenticated request.
- Route tests cover unauthenticated access, configured parent, configured child, and authenticated no-membership states.
- `uv run python manage.py test` passes.

#### Manual Verification:

- Signing in as a configured parent shows parent status.
- Signing in as a configured child shows child status.
- Signing in with an unconfigured Google account shows no family data.

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 4: Contract Verification and Operational Finish

### Overview

Round out the foundation with focused tests, dependency audit, and documentation updates so later slices can safely build on the contract.

### Changes Required:

#### 1. Test suite coverage

**File**: `family_access/tests.py`, `family_notes/tests.py`

**Intent**: Make the PRD access rules executable before any family entry model exists.

**Contract**: Tests cover parent access, assigned-child read access, other-child denial, unauthenticated denial, unknown authenticated denial, and superuser-only admin access. Existing root and health behavior remains covered.

#### 2. Local setup documentation

**File**: `README.md`, `.env.example`

**Intent**: Document how to configure Google OAuth and create the initial superuser/family setup without leaking secrets.

**Contract**: Docs name required env vars, mention the account/status route, describe admin-based family setup, and keep real credential values out of tracked files.

#### 3. Deployment acceptance update

**File**: `context/changes/deployment/deployment-plan.md`, `context/changes/deployment/mikrus-runbook.md`

**Intent**: Align production acceptance with the new admin and auth contract.

**Contract**: Acceptance checks require HTTPS admin login denial for anonymous users, superuser-only admin access, no secrets/tokens/family-entry text in logs, and configured Google provider env vars when auth is deployed.

### Success Criteria:

#### Automated Verification:

- `uv run python manage.py check` passes.
- `uv run python manage.py makemigrations --check --dry-run` passes with committed migrations.
- `uv run python manage.py test` passes.
- `uv run --locked pip-audit` passes after the dependency change.

#### Manual Verification:

- Superuser can complete admin setup for the one MVP family.
- Configured parent and child accounts reach the account/status page with correct role display.
- Unknown authenticated account sees only not-configured state.
- Deployment docs reflect `/admin/` as intentionally enabled, not a 404.

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before considering the change implemented.

---

## Testing Strategy

### Unit Tests:

- `Family` and `FamilyMember` model constraints and role choices.
- Central access helper behavior for parent, child, inactive member, unknown authenticated user, and unauthenticated user.
- Admin permission expectations for superuser versus normal family member.

### Integration Tests:

- Account/status route for unauthenticated, parent, child, and unknown authenticated users.
- Root, health, allauth route inclusion, and admin route behavior.
- Future-facing helper tests that simulate assigned-child versus other-child read decisions using minimal test fixtures.

### Manual Testing Steps:

1. Create a Django superuser.
2. Configure Google OAuth credentials in environment or local allauth-compatible settings.
3. Create the single MVP family and five members in admin.
4. Sign in as a configured parent and verify parent status.
5. Sign in as a configured child and verify child status.
6. Sign in as an unconfigured Google account and verify no family data is shown.

## Performance Considerations

Membership lookup should use direct indexed relations and can be fetched per request by the view/helper when needed. No caching is required for the MVP. Future entry list views should use the central family-scope helper to avoid broad queries.

## Migration Notes

This is the first product schema migration. No existing family data needs migration. Production rollout requires applying allauth migrations and the new `family_access` migrations before superuser/admin setup. Because `/admin/` changes from intentionally disabled to intentionally enabled, deployment smoke tests must be updated in the same change.

## References

- PRD: `context/foundation/prd.md`
- Roadmap F-01: `context/foundation/roadmap.md`
- Existing settings and auth baseline: `family_notes/settings.py`
- Existing routes/tests: `family_notes/urls.py`, `family_notes/tests.py`
- allauth quickstart: `https://docs.allauth.org/en/dev/installation/quickstart.html`
- allauth Django 5.2 support metadata: `https://github.com/readthedocs/django-allauth/blob/main/pyproject.toml`
- Django admin auth guidance: `https://docs.djangoproject.com/en/5.2/topics/auth/customizing/`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Google Auth and Admin Wiring

#### Automated

- [x] 1.1 `uv sync` completes with the new locked auth dependency. — 41495db
- [x] 1.2 `uv run python manage.py check` passes. — 41495db
- [x] 1.3 `uv run python manage.py makemigrations --check --dry-run` shows only expected migration state for later phases. — 41495db
- [x] 1.4 Existing home and health tests still pass after route changes. — 41495db
- [x] 1.5 Admin route tests assert unauthenticated users cannot enter admin and active superusers can reach it. — 41495db

#### Manual

- [x] 1.6 Operator can identify the Google OAuth redirect URI needed for provider setup. — 41495db
- [x] 1.7 Production documentation no longer claims `/admin/` must return 404. — 41495db
- [x] 1.8 No provider secret or real family identity appears in tracked files. — 41495db

### Phase 2: Family Membership Schema and Admin Setup

#### Automated

- [x] 2.1 `uv run python manage.py makemigrations --check --dry-run` confirms migrations are present after model creation. — 5878243
- [x] 2.2 `uv run python manage.py test` covers `Family` and `FamilyMember` creation, role choices, string output, active membership uniqueness, and user-to-membership mapping. — 5878243
- [x] 2.3 Tests prove parent and child users do not receive admin access unless separately made superusers. — 5878243

#### Manual

- [x] 2.4 Superuser can create the MVP family and assign five users as parent/child members in Django admin. — 5878243
- [x] 2.5 Normal parent/child accounts cannot enter Django admin. — 5878243
- [x] 2.6 Admin setup flow does not require committing family member names or emails. — 5878243

### Phase 3: Access Helpers and Account Status Route

#### Automated

- [x] 3.1 Unit tests cover helper behavior for parent, assigned child, other child, inactive membership, unknown authenticated user, and unauthenticated request. — 0e6acb6
- [x] 3.2 Route tests cover unauthenticated access, configured parent, configured child, and authenticated no-membership states. — 0e6acb6
- [x] 3.3 `uv run python manage.py test` passes. — 0e6acb6

#### Manual

- [x] 3.4 Signing in as a configured parent shows parent status. — 0e6acb6
- [x] 3.5 Signing in as a configured child shows child status. — 0e6acb6
- [x] 3.6 Signing in with an unconfigured Google account shows no family data. — 0e6acb6

### Phase 4: Contract Verification and Operational Finish

#### Automated

- [x] 4.1 `uv run python manage.py check` passes. — 7858eb0
- [x] 4.2 `uv run python manage.py makemigrations --check --dry-run` passes with committed migrations. — 7858eb0
- [x] 4.3 `uv run python manage.py test` passes. — 7858eb0
- [x] 4.4 `uv run --locked pip-audit` passes after the dependency change. — 7858eb0

#### Manual

- [x] 4.5 Superuser can complete admin setup for the one MVP family. — 7858eb0
- [x] 4.6 Configured parent and child accounts reach the account/status page with correct role display. — 7858eb0
- [x] 4.7 Unknown authenticated account sees only not-configured state. — 7858eb0
- [x] 4.8 Deployment docs reflect `/admin/` as intentionally enabled, not a 404. — 7858eb0
