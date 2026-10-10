# Multiple Family Use — Plan Brief

> Full plan: `context/changes/multiple-family-use/plan.md`

## What & Why

Future-roadmap slice S-16 (PK-16): one person can belong to several families and switch between them. The roadmap risk is that "every view and mutation must use the authorized family context". Today the code relies on a user having exactly one active family, so lifting that limit carelessly would silently write into an arbitrary family.

## Starting Point

A database constraint allows one active membership per user (`family_access/models.py:46`). `get_active_membership(user)` returns `.first()` (`family_access/access.py:6`) and feeds home routing, the account page, all parent and child entry services, classification and the DEBUG galleries. Tokens and the EduVulcan worker are already bound to a family through the token's membership and the notification row.

## Desired End State

A multi-family user picks a family on a chooser, sees its name in the header, and switches with "Zmień rodzinę". Each family behaves exactly like a single-family app with that membership's role. Stale tabs cannot write into the wrong family. Tokens and the worker stay within their family. Single-family users notice nothing.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
| --- | --- | --- | --- |
| Family creation / joining | Operator creates families and every membership (including a second family) in Django admin; no invitations | No self-service grant path. | Owner |
| Accounts | Google first sign-in creates the `User` once (S-09); a second family needs only a second membership | Consistent with the confirmed sign-up policy. | Owner |
| Role scope | Role belongs to each membership (parent in A, child in B is allowed) | Matches the existing model. | Owner |
| Context storage | Session family id, re-validated on every request; chooser when ambiguous; never guess | Guessing could write to the wrong family. | Owner |
| Switching | CSRF POST, then redirect to role home (not the previous URL) | Entry ids do not carry over between families. | Assumed |
| Stale tabs | Hidden `family_context` on every mutation form, checked centrally by `FamilyContextMiddleware` for every unsafe request to `entries`/`family_access`; a mismatch returns a Polish 409 with no write | Covers new forms (S-03, S-04, S-07, S-14, S-15) without a hand-written list. | Owner (owner-confirmed 2026-10-04) |
| Tokens | Bound to one membership; the client never supplies a family | Preserves the MS-01 API contract. | Research |
| Worker | Family comes from the notification row; regression tests only | Already correct (`entries/eduvulcan/conversion.py:283`). | Research |
| Constraint | One active membership per (user, family), migration `0004` | The old constraint implies the new one, so the migration cannot fail. | Research |
| Remembered default | None; choose again after each sign-in | Avoids new preference storage. | Assumed |
| Header indicator | Family name and "Zmień rodzinę" only for multi-family users | Single-family users see no change. | Assumed |
| Old helper | `get_active_membership` deleted; rule: no product function takes a `User` to derive a family; inactive `User` gets no context | Makes it impossible for a call site to keep the ambiguous lookup, including services added by S-03/S-04. | Research |
| Header and error pages | Non-raising `peek_family_context` | Rendering the chooser, logout or an error page never loops or raises. | Review |
| Accessibility | Follow S-17 conventions; add audit cases for the chooser, header and 409 page | S-17 lands first and owns the criteria. | Owner |
| Flags, backfill, E2E | None | Confirmed delivery constraints. | Owner |

## Scope

**In scope:**
- The request family-context contract and middleware, with every caller migrated.
- The constraint swap migration.
- Operator-created second memberships in admin and per-family S-14 reactivation.
- Chooser and switcher, header indicator, and the central stale-tab guard.
- S-17 audit cases for the chooser, header switcher and 409 page.
- The cross-family isolation matrix and token and worker regressions.
- Updates to the seed script and AGENTS.md.

**Out of scope:**
- Invitations and self-service joining of a second family.
- Creating, leaving or merging families in the app.
- Cross-family views or sharing, and the family id in URLs.
- Cross-family tokens and a remembered default family.
- Changes to EduVulcan logic.
- Feature flags, backfill and Playwright/E2E tests.

## Architecture / Approach

The three phases are ordered for safety. Phase 1 is a behavior-neutral refactor while the old constraint still holds: it adds `resolve_family_context(request)`, deletes the user-based helper, and has services take the membership. Phase 2 swaps the constraint, lets the operator add a second membership in admin, and ships the chooser, switcher and stale-tab guard. Phase 3 proves isolation across web, API and worker for a user who is a parent in one family and a child in another.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Request Family Context and Caller Migration | One validated context per request; no user-based lookups remain | A missed call site, including services added by S-03/S-04; mitigated by the deleted helper, a rule-based grep and a review check |
| 2. Constraint Swap, Chooser, Switcher and Stale-Tab Guard | Multiple memberships per user and a safe UX for them | A cross-tab write into the wrong family |
| 3. Cross-Family Isolation Matrix, Automation and Worker Regression | Systematic proof of isolation | Mixed-role edge cases (parent in A, child in B) |

**Prerequisites:** S-01, S-02, S-20, S-03..S-09, S-17 `accessible-family-flows`, S-14 `family-membership-management` and S-15 `family-role-management` implemented.
**Estimated effort:** about 3–4 sessions across 3 phases; Phase 1 touches most entry views and services.

## Open Risks & Assumptions

- Owner decisions, including the plan-review triage, were applied 2026-10-04. The rows marked "Assumed" (switching, remembered default, header indicator) are planning defaults that do not block implementation.
- Rolling back the migration requires deactivating extra memberships first.
- Parallel in-flight changes to `entries/views.py` and `entries/services.py` will conflict with Phase 1's signature changes, so sequence them.

## Success Criteria (Summary)

- A person in two families uses each one independently, and data never crosses families on any path.
- A stale form from another family never writes.
- Single-family users see no change in behavior.
