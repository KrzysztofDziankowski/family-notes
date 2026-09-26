# Identity and Family Access Contract — Plan Brief

> Full plan: `context/changes/identity-and-family-access-contract/plan.md`

## What & Why

FamilyNotes needs a trustworthy identity and family access foundation before entry capture or classification can store family data. This plan adds Google sign-in, superuser-managed family setup, local parent/child membership, and central access helpers so later slices do not invent authorization rules.

## Starting Point

The project is a Django scaffold with auth/session middleware, home and health routes, and no product app or family models. The PRD and roadmap define one preconfigured five-person family, external identity, parent/child roles, and strict family-data isolation.

## Desired End State

Google-authenticated users can sign in. A superuser can configure the MVP family and members in Django admin. Configured parents/children can reach a minimal account/status page, while unknown authenticated users and unauthenticated users receive no family-data access.

## Key Decisions Made

| Decision | Choice | Why |
| --- | --- | --- |
| External identity | `django-allauth[socialaccount]` with Google | Matches shape-notes preference and avoids custom OAuth code. |
| Local identity model | Built-in Django `User` plus `Family` and `FamilyMember` | Keeps auth conventional while preserving explicit family scope. |
| Family setup | Django admin | User selected admin setup for the one preconfigured family. |
| Admin exposure | Enable `/admin/` in production | This intentionally changes the prior 404 contract and requires updated tests/docs. |
| Admin authority | Superuser only | Keeps setup authority narrow and separate from parent/child product roles. |
| Unknown Google users | Authenticated but not configured | Safe default: show setup state, deny all family data. |
| Access contract | Central service helpers | Gives future slices one tested place for family and role rules. |
| User-facing proof | Minimal account/status page | Verifies auth and membership before dashboard or entry UI exists. |

## Scope

**In scope:**

- Google OAuth and allauth wiring.
- Django admin exposure and superuser-only setup.
- `family_access` app with `Family` and `FamilyMember`.
- Central access helpers for parent, child, unknown, and unauthenticated cases.
- Minimal protected account/status page.
- Tests and docs for the changed admin/auth/access contract.

**Out of scope:**

- Entry CRUD, classification UI, family dashboard, or child dashboard.
- In-app family/role management for normal users.
- Multiple-family UX.
- Custom OAuth implementation.
- Committed real family data or provider secrets.

## Architecture / Approach

Django/allauth authenticates users through Google and creates or links Django `User` records. `family_access` maps those users to the configured family and role. Views and future product code call `family_access.access` helpers for membership lookup, parent-only mutations, child read checks, and family-scoped query filtering. Django admin is the operator setup surface and is intentionally restricted to superusers.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Google Auth and Admin Wiring | allauth, Google config, `/accounts/`, `/admin/`, and docs alignment | Admin exposure changes a previous production expectation. |
| 2. Family Membership Schema and Admin Setup | `Family` and `FamilyMember` models with admin setup | Overbuilding beyond one preconfigured family. |
| 3. Access Helpers and Account Status Route | reusable access contract and protected status page | Helpers must be adopted by future slices. |
| 4. Contract Verification and Operational Finish | tests, docs, audit/check commands | Missing coverage could let later family-data paths drift. |

**Prerequisites:** Google OAuth client details will be needed for real manual sign-in testing; no provider secrets are committed.
**Estimated effort:** About 3-4 focused implementation sessions across 4 phases.

## Open Risks & Assumptions

- Enabling production admin is accepted and must be secured with superuser-only access and HTTPS.
- Google OAuth configuration details come from the operator environment.
- The project keeps built-in Django `User`; no custom user model is introduced now.
- Future entry slices must use the central helpers for every family-data query and mutation.

## Success Criteria (Summary)

- A configured parent/child can sign in and see correct membership status.
- Unknown authenticated users and unauthenticated users receive no family-data access.
- Tests cover parent access, assigned-child access, other-child denial, unauthenticated denial, unknown authenticated denial, and superuser-only admin access.
