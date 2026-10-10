# Family Membership Management — Plan Brief

> Full plan: `context/changes/family-membership-management/plan.md`

## What & Why

Future-roadmap slice S-14 (PK-16): an authorized family manager manages the existing members of their family inside the app, so renaming someone or removing their access no longer needs the operator to edit Django admin. Adding a person stays operator-only in admin. This is the first of three chained PK-16 slices (S-14 → S-15 roles → S-16 multiple families), delivered after S-01, S-02, S-20, S-03..S-09 and S-17.

## Starting Point

The operator creates the family and links each Google-created `User` to a `FamilyMember` in Django admin (`family_access/admin.py:15`). S-09 closes username/password sign-up and keeps Google first sign-in creating the `User`. A user may have at most one active membership (`family_access/models.py:46`). There is no in-app membership management.

## Desired End State

Any active parent can open "Członkowie rodziny" and see their own family's active and inactive members. From there they can rename a member and deactivate or reactivate members. They cannot deactivate themselves or the last parent. Deactivating a parent revokes their automation tokens. The list explains that new people are added by the family administrator. The new pages pass the S-17 page audit.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
| --- | --- | --- | --- |
| Who is a family manager | Every active parent | Reuses `is_parent` and introduces no new permission concept. | Owner |
| Who creates families | Operator only, in Django admin | Keeps families small and controlled. | Owner |
| How members are added | Operator only, in Django admin; no invitations or self-service joining | Removes the invitation model, pages and email matching entirely. | Owner |
| How a new person gets an account | Google first sign-in creates the `User`; the operator maps it (S-09) | Consistent with the confirmed S-09 sign-up policy. | Owner |
| In-app operations | Rename, deactivate, reactivate; role changes in S-15 | Smallest useful increment over existing members. | Owner |
| Removing a member | Soft deactivation that can be reversed; no hard delete | Entries restrict assignee deletion (`entries/models.py:34`), and history must survive. | Owner |
| Last-parent guard | Enforced under a `Family` row lock; actor and target re-read under the lock; parents with a disabled `User` do not count | Prevents a family with no manager, and stops a parent who just lost access from acting. | Owner |
| Reactivating a parent | Allowed for any active parent, after the Polish confirmation "Ta osoba odzyska uprawnienia rodzica."; id-only log line; tokens stay revoked | All parents are equal managers; the confirmation makes the restored rights explicit. | Owner (owner-confirmed 2026-10-04) |
| Rename collisions | A name that normalizes to another active member's name is refused | EduVulcan and short-name matching key on display names. | Review |
| Self-deactivation | Refused | Avoids locking the actor out mid-action. | Owner |
| Tokens on deactivation | Revoked in the same transaction; operator re-issues in admin | Reactivating a member never silently brings old automation tokens back. | Owner |
| Multiple families | The one-active-membership rule stays; S-16 lifts it | Keeps the current access contract unambiguous. | Owner |
| "How to add someone" note | Polish note on the member list pointing to the administrator | Parents otherwise look for a missing invite button. | Assumed |
| Audit | Content-free logs with ids only | Follows `log_safety` and the rule against secondary storage. | Assumed |
| Accessibility | Follow S-17 conventions; add audit cases for new pages | S-17 lands first and owns the criteria. | Owner |
| Flags, backfill, E2E | None | Confirmed delivery constraints. | Owner |

## Scope

**In scope:**
- `family_access/membership.py` service layer with the lock and last-parent guard.
- Parent pages under `/account/family/` for listing, renaming, deactivating and reactivating.
- A "Członkowie rodziny" link on `/account/`.
- DEBUG state gallery.
- S-17 audit cases for the new pages.
- Full access-matrix and deactivation regression tests.

**Out of scope:**
- Email invitations, invitation acceptance and self-service joining.
- Creating members or families in the app (operator-only in admin).
- Changing roles of existing members (S-15) and multiple families (S-16).
- Outbound email, hard delete, in-app token issuing and an audit table.
- Changes to the sign-up flow (S-09) and Django staff or superuser flags.
- Feature flags, backfill and Playwright/E2E tests.

## Architecture / Approach

One service module owns every in-app membership change. Each function takes the acting membership rather than the user (ready for S-16), re-checks that the actor is a parent, scopes the target to the actor's family (foreign and missing ids are both "not found"), and runs guarded mutations under a locked `Family` row. Thin Polish function views and templates reuse the existing partials, the S-17 field contract and tokens. No schema change.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Membership Services and Guards | Authorized rename, deactivate and reactivate with the shared lock and guard | Two parents deactivating each other concurrently |
| 2. Parent Member-Management UI and Regression | Routes, templates, DEBUG gallery, audit cases and deactivation regression | A foreign id leaking whether it exists; effects of deactivation on EduVulcan child matching |

**Prerequisites:** S-01, S-02, S-20, S-03..S-09 and S-17 `accessible-family-flows` delivered (S-17 provides `context/foundation/accessibility.md` and `family_notes/a11y_audit.py`).
**Estimated effort:** about 1–2 sessions across 2 phases.

## Open Risks & Assumptions

- Owner decisions, including the plan-review triage, were applied 2026-10-04. The rows marked "Assumed" (the "how to add someone" note, audit logging) are planning defaults that do not block implementation.
- An operator deactivation of a parent can be undone by any other active parent (owner-accepted 2026-10-04).
- Renaming or deactivating a child changes EduVulcan name matching (`entries/eduvulcan/children.py:13`).
- Reactivation fails with a Polish error if the operator has meanwhile activated the same user in another family; S-16 relaxes this.

## Success Criteria (Summary)

- A parent renames, deactivates and reactivates family members without the operator.
- A family can never lose its last parent, and a deactivated member immediately loses web and token access.
- Children and other families cannot see or change any membership data.
