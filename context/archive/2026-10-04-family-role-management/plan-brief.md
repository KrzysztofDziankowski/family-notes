# Family Role Management — Plan Brief

> Full plan: `context/changes/family-role-management/plan.md`

## What & Why

Future-roadmap slice S-15 (PK-16): an authorized family manager changes an existing member's role (parent ↔ child) inside the app. The roadmap risk is privilege escalation, so the plan centres on guards. A child can never change roles, the last parent cannot be demoted, and Django admin rights are never touched.

## Starting Point

Roles are `parent` or `child` (`family_access/models.py:24`) and are set only by the operator in Django admin. Every permission is derived from the role on each request (`family_access/access.py:24`, `:39`). S-14 adds the membership service layer, the `Family` row lock, the last-parent guard and the `/account/family/` pages that this slice extends.

## Desired End State

A parent changes a member's role from that member's edit page after a Polish confirmation. Demoting the last parent is refused, and self-demotion needs an extra confirmation. A demoted parent loses management, entry CRUD and token access on their next request and sees a one-time Polish notice explaining the change. A promoted child gains parent capabilities on their next request.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
| --- | --- | --- | --- |
| Family manager | Any active parent | Same rule as S-14; one permission concept. | Owner |
| Role set | Parent and child only | A new role would multiply access rules across every path. | Assumed |
| Who can change roles | Any active parent, for any active member of their family, in both directions | All parents are equal managers. | Owner |
| Last parent | Cannot be demoted; shares the S-14 guard and `Family` lock | Prevents a family with no manager, even under concurrent changes. | Owner |
| Self-demotion | Explicit confirmation, only when another parent remains | Avoids accidental lockout. | Assumed |
| Children | Never change any role, enforced in the service | Only parents are managers. | Owner |
| Initial role of new members | Set by the operator in Django admin; no invitations | Adding members stays operator-only. | Owner |
| Inactive members | Not editable; reactivate first through S-14 | Avoids reviving a member with new rights. | Assumed |
| Tokens on demotion | All revoked; never restored on promotion; operator re-issues in admin | Tokens are parent-only and revocation must be immediate. | Assumed |
| Django admin flags | Never modified | Keeps the F-01 operator boundary. | Research |
| Effect timing | Next request; no session work | Roles are read per request (`family_access/access.py:6`). | Research |
| Audit | Content-free logs (ids and roles) | Consistent with S-14 and log safety. | Assumed |
| Co-parent removal | Kept as decided; a demoted or deactivated parent sees a Polish notice on their next request; operator recovery runbook in the plan | Transparency and recovery without contradicting "all parents are equal". | Owner (owner-confirmed 2026-10-04) |
| Authority check timing | Actor and target re-read under the `Family` lock before every check | A parent who just lost rights cannot still promote someone. | Review |
| Accessibility | Follow S-17 conventions; add audit cases for the role states | S-17 lands first and owns the criteria. | Owner |
| Flags, backfill, E2E | None | Confirmed delivery constraints. | Owner |

## Scope

**In scope:**
- `change_member_role` service with the escalation guards.
- A separate POST role route with confirmation UI.
- A once-only Polish notice for a demoted or deactivated parent, and an operator recovery runbook.
- DEBUG gallery states.
- S-17 audit cases for the role states.
- An effective-access regression across web views, the API and home routing.

**Out of scope:**
- New roles or capability flags, and changes to staff or superuser flags.
- Editing the role of an inactive member.
- Invitations, self-service joining and in-app member creation (operator-only in admin).
- In-app token issuing on promotion.
- Feature flags, backfill and Playwright/E2E tests.
- Reassigning entries, and multiple families (S-16).

## Architecture / Approach

One new function in `family_access/membership.py` reuses the S-14 `_lock_family` and `_ensure_parent_remains`, so deactivation and demotion can never race each other into a family with no parent. Role changes post to their own route, separate from renaming, and use a no-JavaScript `<details>` confirmation.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Role-Change Service and Escalation Guards | Authorized, race-safe role change with token revocation | A guard placed only in the view could be bypassed |
| 2. Role-Change UI and Effective-Access Regression | Route, confirmation UI, audit cases and the next-request access matrix | A promoted child dropping out of EduVulcan name matching |

**Prerequisites:** S-01, S-02, S-20, S-03..S-09, S-17 `accessible-family-flows` and S-14 `family-membership-management` implemented (service module, lock, guard, pages).
**Estimated effort:** about 1–2 sessions across 2 phases.

## Open Risks & Assumptions

- Owner decisions, including the plan-review triage, were applied 2026-10-04. The rows marked "Assumed" (role set, self-demotion, inactive members, token revocation on demotion, audit) are planning defaults that do not block implementation.
- One parent can still demote or deactivate every co-parent; mitigation is the next-request notice and operator recovery, not prevention (owner-accepted 2026-10-04).
- A demoted parent joins the EduVulcan child snapshot, so a notification naming them (for example a signature) can be auto-assigned to them.
- A promoted child stops being matched by name in EduVulcan conversion (`entries/eduvulcan/children.py:13`), so their school notifications become unassigned proposals.
- A demoted parent keeps any entries assigned to them, which are visible in the child view.

## Success Criteria (Summary)

- Parents can switch a member between parent and child without the operator.
- No sequence of actions leaves a family without an active parent or gives a child a way to change roles.
- A demoted parent's web and token access ends on their next request.
