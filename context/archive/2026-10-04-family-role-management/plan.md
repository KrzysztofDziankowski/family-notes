# Family Role Management Implementation Plan

## Overview

Implement future-roadmap slice S-15 (PK-16): an authorized family manager can change the role of an existing family member between parent and child inside the application. Role changes must never allow privilege escalation. A child can never change any role, a family can never lose its last active parent, and nothing in the app touches Django admin rights. The change builds directly on the S-14 membership service layer and its `Family` row lock.

### Decisions

Owner decisions, including the plan-review triage, were applied 2026-10-04. Items marked "assumed" are planning defaults the owner may revisit; they do not block implementation.

1. **A family manager is any active parent.** This is the same rule as S-14. (owner-confirmed 2026-10-04)
2. **The role set stays parent and child.** There is no separate "manager", "guardian" or "admin" role. Introducing a new role would multiply access rules across every entry path. (assumed)
3. **Any active parent can change any active member of their own family in both directions** (child → parent, parent → child). All parents are equal managers. A single parent can therefore demote or deactivate every co-parent; this is kept, with transparency and recovery instead of prevention (Decision 15). (owner-confirmed 2026-10-04)
4. **The last active parent cannot be demoted.** Demotion shares the S-14 last-parent guard and `Family` row lock. (owner-confirmed 2026-10-04)
5. **Self-demotion needs an explicit confirmation** and is allowed only when another active parent remains. This prevents accidental self-lockout. (assumed)
6. **Children never change roles, including their own.** Only parents are managers, and the service checks this independently of the view. (owner-confirmed 2026-10-04)
7. **Only active members' roles change.** An inactive member is reactivated first, through S-14. This avoids silently reviving a member with new rights. (assumed)
8. **A new member's initial role is set by the operator in Django admin when creating the `FamilyMember`.** There are no invitations; S-15 changes roles of existing members only. (owner-confirmed 2026-10-04)
9. **Demoting a parent revokes all of their automation tokens** in the same transaction. Promotion issues no tokens; the operator issues tokens in Django admin (`family_access/admin.py:40`). Tokens are parent-only (`family_access/models.py:114`), and the PRD guardrail requires immediate revocation. (assumed)
10. **Role changes never modify `User.is_staff` or `User.is_superuser`.** The operator remains the only Django admin. This keeps the F-01 admin boundary. (assumed)
11. **Entries assigned to the member stay assigned and unchanged.** The new role applies from the member's next request. Roles are read from the database per request (`family_access/access.py:6`), so no session invalidation is needed. (assumed)
12. **Audit uses content-free logs only:** event, family id, member id, actor id, old role and new role. This is consistent with S-14. (assumed)
13. **The role UI follows the S-17 accessibility conventions** (`context/foundation/accessibility.md`, `family_notes/a11y_audit.py`); this plan adds audit cases rather than re-specifying them. (owner-confirmed 2026-10-04)
14. **No feature flag, no data backfill, and no Playwright/E2E tests in this slice.** (owner-confirmed 2026-10-04)
15. **A demoted or deactivated parent sees a Polish notice on their next request, and the operator has a recovery runbook.** The notice explains what changed and that another parent or the family administrator made the change. It needs no new database storage: the user's own session remembers the membership id and role it last saw. The runbook is in "Operator Recovery Runbook" below. (owner-confirmed 2026-10-04)

## Current State Analysis

- Roles are `FamilyMember.Role.PARENT` and `CHILD` (`family_access/models.py:24`). Today only the operator sets them, in Django admin (`family_access/admin.py:15`).
- Every permission is derived from the role at request time. `is_parent` (`family_access/access.py:24`) gates all parent management (`entries/services.py:113`) and classification (`entries/classification/service.py:102`). `can_read_assigned_child` requires `role == CHILD` (`family_access/access.py:39`). Home routing branches on role (`family_notes/views.py:14`).
- Automation tokens are parent-only at creation (`family_access/models.py:114`) and are rejected at use when the owner is not an active parent (`family_access/automation.py:52`).
- EduVulcan conversion snapshots only active children (`entries/eduvulcan/children.py:13`), so a promoted child stops being matched by name for automated school entries.
- S-14 (`context/changes/family-membership-management/plan.md`) adds `family_access/membership.py` with `_lock_family` and `_ensure_parent_remains`, parent-only views under `/account/family/` (list, rename, deactivate, reactivate), and the DEBUG gallery `/account/family/_states/`. Members are still added only by the operator in Django admin, with their initial role.
- S-17 (`context/changes/accessible-family-flows/plan.md`) lands before S-14 and provides `context/foundation/accessibility.md` and the page audit helper `family_notes/a11y_audit.py` (`audit_page`, `assert_accessible`).

## Desired End State

On a member's edit page an active parent can change that member's role. Promotion and demotion each have a clear Polish confirmation. Demoting the last active parent is refused. Self-demotion needs the extra confirmation and then sends the user to the child home page. A demoted parent's tokens stop working at once, and they lose management and entry CRUD on their next request, where a one-time Polish notice explains the change. The operator can reverse a disputed change by following the recovery runbook. A promoted child gains parent capabilities on their next request. Children, other families' parents and anonymous users cannot change roles or learn whether foreign members exist.

### Key Discoveries:

- Because permissions come from `role` on each request, a role change takes effect immediately with no cache or session work (`family_access/access.py:6`).
- Token rejection after demotion already happens through `is_parent` (`family_access/automation.py:52`). Explicit revocation is still needed so that a later re-promotion does not silently restore old tokens.
- `_ensure_parent_remains` from S-14 is the single guard to reuse. Deactivation and demotion must share it, or two concurrent demotions could leave the family without a parent.

## What We're NOT Doing

- No new roles, permission flags or per-member capability toggles.
- No changes to Django staff or superuser flags, and no in-app admin access.
- No role changes for inactive members.
- No invitations or self-service joining; new members and their initial role are created by the operator in Django admin.
- No in-app token issuing on promotion.
- No reassignment of entries and no change to EduVulcan matching rules.
- No multi-family behavior (S-16).
- No audit table and no outbound notification (email or push) to the affected member; the only notice is the in-app message on their next request (Decision 15).
- No feature flag, data backfill or Playwright/E2E tests.

## Implementation Approach

Add `change_member_role(actor, member_id, new_role, *, confirm_self=False)` to `family_access/membership.py`, reusing the S-14 lock and guard. Extend the S-14 member edit page with a separate role-change form that posts to its own route, so renaming and privilege changes never share one submit. The form follows the S-17 field and error-summary conventions. Tests cover the escalation matrix explicitly and add S-17 audit cases for the new states.

## Phase 1: Role-Change Service and Escalation Guards

### Overview

Add one authorized, race-safe service function for role changes.

### Changes Required:

#### 1. Role-change service

**File**: `family_access/membership.py`

**Intent**: Concentrate every privilege change behind the same lock and last-parent guard used for deactivation.

**Contract**: `change_member_role(actor, member_id, new_role, *, confirm_self=False)` follows these rules, in this order:
- It rejects a role that is not a valid `FamilyMember.Role` value with a Polish `ValidationError`. It may fail fast with `PermissionDenied` when the request's `actor` is not a parent, but that check is not the authority.
- Inside `transaction.atomic()` it locks the family with S-14's `_lock_family`, then re-reads the actor and the target under the lock with S-14's `_relock_members` (foreign or missing target raises `FamilyMember.DoesNotExist`).
- On the fresh rows it raises `PermissionDenied` unless `is_parent(fresh_actor)`, refuses an inactive target with a Polish `ValidationError`, does nothing when the role is unchanged, requires `confirm_self=True` when the target is the actor, and when demoting calls `_ensure_parent_remains(family, excluding_member_id=target.pk)`.
- It saves the role on the fresh target, and on demotion sets `revoked_at` on every unrevoked `AutomationToken` of the target.
- It returns the updated member and emits one content-free log line with old and new role.
- Fresh actor authorization reads and locks `User.is_active` through S-14's
  `_relock_members`; the role change never writes `User` fields and never reads or
  writes `User.is_staff` or `User.is_superuser`.

### Success Criteria:

#### Automated Verification:

- Service tests cover promotion and demotion by an active parent, the unchanged-role no-op, and the invalid-role rejection.
- Escalation tests prove a child cannot change any role (including their own), and that an inactive parent, a parent of another family and a user without a membership are denied with no change.
- Guard tests prove the last active parent cannot be demoted, self-demotion without `confirm_self` is refused, and self-demotion with confirmation succeeds when another parent remains.
- Token tests prove demotion revokes every unrevoked token of the member, and that re-promotion leaves those tokens revoked.
- Tests prove `is_staff` and `is_superuser` are unchanged after every role change.
- Targeted tests pass: `uv run python manage.py test family_access.tests.test_role_services`.
- Stale-authority tests demote or deactivate the actor directly in the database after it was resolved, and deactivate the target the same way, and prove the role change is refused (`PermissionDenied` or the Polish inactive-target error) with no change.

**Implementation Note**: After completing this phase and all automated verification passes, proceed to Phase 2.

---

## Phase 2: Role-Change UI and Effective-Access Regression

### Overview

Expose role changes to parents and prove the new role governs every access path on the next request.

### Changes Required:

#### 1. Route, form and view

**File**: `family_access/urls.py`, `family_access/views.py`, `family_access/forms.py`

**Intent**: Keep privilege changes separate from renaming and protect them with an explicit confirmation.

**Contract**: `POST /account/family/members/<pk>/role/` (`family_member_role`) takes `role` and, for the actor's own row, a required `confirm_self` checkbox. It returns 403 for non-parents and 404 for foreign or missing ids. On success it redirects to the member list with a Polish message, or to `home` after self-demotion. Guard errors re-render the edit page with the Polish error and change nothing.

#### 2. Templates and DEBUG states

**File**: `family_access/templates/family_access/member_edit.html`, `family_access/templates/family_access/member_states.html`

**Intent**: Make the consequences of the change visible before submitting.

**Contract**: The edit page shows the current role and a role-change form inside a no-JavaScript `<details>` confirmation. The role choice is a labelled radio group and the self-demotion checkbox has its own label, per `context/foundation/accessibility.md`. Promotion warns "Ta osoba będzie mogła zarządzać wpisami i członkami rodziny." Demotion warns that automation tokens will be revoked. The actor's own row shows the self-demotion checkbox. The form is hidden when the target is the last active parent, and a Polish explanation replaces it. The DEBUG gallery adds promote, demote, self-demote and last-parent states.

#### 3. Accessibility audit cases

**File**: `family_access/tests/test_membership_accessibility.py`

**Intent**: Add the role states to the S-17 audit, as `context/foundation/accessibility.md` requires for new page states.

**Contract**: Each case renders the real edit view and calls `assert_accessible` from `family_notes/a11y_audit.py`: a child member (promotion form), another parent (demotion form), the actor's own row (self-demotion checkbox), the last active parent (explanation instead of the form), and a guard error.

#### 4. Effective-access regression

**File**: `family_access/tests/test_role_views.py`, `entries/tests/` (only if a regression surfaces)

**Intent**: Prove that a role change takes effect on the next request in every product path.

**Contract**: After demotion the former parent gets 403 on `entries:index`, `entries:capture` and `/account/family/`, their token gets 401, and `home` routes them to `entries:child_list`. After promotion the former child reaches `entries:index` and `/account/family/`, and `home` routes them to `entries:index`. A promoted child is no longer in the EduVulcan child snapshot. A demoted parent appears in the EduVulcan child snapshot (`entries/eduvulcan/children.py:13-28`) and is matchable by display name, so a school notification naming them (for example in a signature) can be auto-assigned to them; the test pins this behavior.

#### 5. Changed-membership notice

**File**: `family_access/notices.py` (new), `family_notes/settings.py`, `family_notes/templates/base.html`

**Intent**: A parent who loses parent rights through another person's action learns what happened on their next request instead of finding pages silently refused.

**Contract**:
- `MembershipNoticeMiddleware`, placed after `MessageMiddleware`, stores in the user's own session `family_access.seen_membership = {"id": <member id>, "role": <role>}` for the active membership it resolves.
- When the stored entry says `parent` and the same membership is now `child`, it queues one Polish `messages.warning`: "Inny rodzic lub administrator rodziny zmienił Twoją rolę na „Dziecko”. Nie możesz już zarządzać wpisami ani członkami rodziny. Jeśli to pomyłka, skontaktuj się z drugim rodzicem lub administratorem rodziny."
- When the stored entry says `parent` and that membership is no longer active, it queues: "Twoje uprawnienia rodzica w tej rodzinie zostały wyłączone przez innego rodzica lub administratora rodziny. Jeśli to pomyłka, skontaktuj się z drugim rodzicem lub administratorem rodziny."
- Each notice is shown once, after which the stored entry is updated or cleared. The self-demotion view updates the stored entry before redirecting, so the actor sees only the success message.
- `base.html` renders queued messages in its `messages` block by default, so the notice appears on the child home page and on `/account/`.
- The notice stores and logs no names or emails. A new sign-in starts a fresh session, so a change made while the user was signed out produces no notice; the "not configured" account state and the child view remain the fallback.
- S-16 keys the stored entry by the membership of the current family context; the contract above stays the same.

### Success Criteria:

#### Automated Verification:

- View tests cover the role route for a parent, a child, an inactive parent, a parent of another family, a user without a membership, and an anonymous user, with no database change on denial.
- Foreign and nonexistent member ids return the same status and show no foreign content.
- Effective-access tests prove the next-request behavior after demotion and promotion across web views, the automation API and home routing.
- Accessibility audit cases pass for the promotion, demotion, self-demotion, last-parent and guard-error states: `uv run python manage.py test family_access.tests.test_membership_accessibility`.
- State-gallery tests prove the new role states render under DEBUG only and write no rows.
- Regression tests prove a demoted parent appears in the EduVulcan child snapshot and is matched by display name.
- Notice tests prove a parent demoted or deactivated by another parent sees the matching Polish notice exactly once on the next request, a self-demoted parent does not see it, and a promotion shows no notice.
- Full tests pass: `uv run python manage.py test`.
- Django checks pass: `uv run python manage.py check`.
- Migration drift check passes: `uv run python manage.py makemigrations --check --dry-run`.

#### Manual Verification:

- At 360px width a parent promotes a seeded child, sees that child reach the parent index, then demotes them back.
- The last-parent explanation and the self-demotion confirmation are clear and usable without JavaScript.
- A keyboard-only pass on the role-change form follows the `context/foundation/accessibility.md` checklist.
- A reviewer follows the Operator Recovery Runbook on a seeded demoted parent and restores their parent role in Django admin.

**Implementation Note**: Complete manual verification before implementation review.

---

## Testing Strategy

### Unit Tests:

- The role-change authorization matrix and validation of the role value.
- The last-parent guard shared with deactivation.
- Token revocation on demotion, and no restoration on promotion.
- Django admin flags never change.

### Integration Tests:

- Promote → access entries index; demote → 403 and token 401 on the next request.
- Self-demotion with confirmation → redirect to the child home page.
- S-17 page audit cases for every role state on the edit page.

### Manual Testing Steps:

1. As a seeded parent with a second seeded parent, demote yourself with confirmation, and confirm you land on the child view.
2. As the remaining sole parent, confirm the role form is replaced by the last-parent explanation.
3. Promote a child, sign in as them, and confirm parent navigation is available.
4. As one of two parents, demote the other; sign in as the demoted parent and confirm the Polish notice appears once.
5. Repeat the role POST as a child and with a foreign member URL; both are refused.

## Operator Recovery Runbook

Use this when a parent reports that another parent demoted or deactivated them and the family wants it reversed.

1. Confirm the request with the affected person and, where possible, the family through an out-of-band channel. The app does not decide family disputes.
2. Find the events in the application logs by family id: `membership_event=role_changed` (S-15, with old and new role) and `membership_event=member_deactivated` (S-14). Each line has `family=`, `member=` and `actor=` ids and no names.
3. In Django admin open Family access → Family members, filter by the family, and open the member with that id.
4. Restore the state: set `Role` back to `Parent` and/or tick `Is active`, then save. Admin edits bypass the in-app `Family` lock, so make one change at a time.
5. Automation tokens revoked by the demotion or deactivation stay revoked. If the parent needs automation again, issue a new token in Family access → Automation tokens and hand it over securely.
6. If one parent keeps removing others against the family's wishes, the operator can demote or deactivate that parent in admin; the in-app last-parent guard does not apply to admin edits, so check that at least one active parent with an active `User` remains.

## Performance Considerations

Negligible: a single-row update plus a token update under a short `Family` row lock.

## Migration Notes

No schema change, no data backfill and no feature flag. Rollback is to remove the route, form and service function. Roles changed in the meantime stay valid `FamilyMember` values.

## References

- `context/foundation/prd-v2.md` — PK-16, Access Control Changes, Open Question 17
- `context/foundation/roadmap-future.md` — S-15
- `context/foundation/roadmap-future-questions.md` — S-14 / S-15 / S-16 questions
- Prerequisite: `context/changes/family-membership-management/plan.md` (S-14)
- Accessibility conventions: `context/changes/accessible-family-flows/plan.md` (S-17)
- `family_access/models.py:24`, `family_access/models.py:114`, `family_access/access.py:24`, `family_access/access.py:39`
- `family_access/admin.py:40`, `family_access/automation.py:52`, `family_notes/views.py:14`, `entries/eduvulcan/children.py:13`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Role-Change Service and Escalation Guards

#### Automated

- [x] 1.1 Service tests cover promotion and demotion by an active parent, the unchanged-role no-op, and the invalid-role rejection. — 4f83108
- [x] 1.2 Escalation tests prove a child cannot change any role (including their own), and that an inactive parent, a parent of another family and a user without a membership are denied with no change. — 4f83108
- [x] 1.3 Guard tests prove the last active parent cannot be demoted, self-demotion without `confirm_self` is refused, and self-demotion with confirmation succeeds when another parent remains. — 4f83108
- [x] 1.4 Token tests prove demotion revokes every unrevoked token of the member, and that re-promotion leaves those tokens revoked. — 4f83108
- [x] 1.5 Tests prove `is_staff` and `is_superuser` are unchanged after every role change. — 4f83108
- [x] 1.6 Targeted tests pass: `uv run python manage.py test family_access.tests.test_role_services`. — 4f83108
- [x] 1.7 Stale-authority tests demote or deactivate the actor directly in the database after it was resolved, and deactivate the target the same way, and prove the role change is refused (`PermissionDenied` or the Polish inactive-target error) with no change. — 4f83108

### Phase 2: Role-Change UI and Effective-Access Regression

#### Automated

- [x] 2.1 View tests cover the role route for a parent, a child, an inactive parent, a parent of another family, a user without a membership, and an anonymous user, with no database change on denial. — 1fed84a
- [x] 2.2 Foreign and nonexistent member ids return the same status and show no foreign content. — 1fed84a
- [x] 2.3 Effective-access tests prove the next-request behavior after demotion and promotion across web views, the automation API and home routing. — 1fed84a
- [x] 2.4 Accessibility audit cases pass for the promotion, demotion, self-demotion, last-parent and guard-error states: `uv run python manage.py test family_access.tests.test_membership_accessibility`. — 1fed84a
- [x] 2.5 State-gallery tests prove the new role states render under DEBUG only and write no rows. — 1fed84a
- [x] 2.12 Regression tests prove a demoted parent appears in the EduVulcan child snapshot and is matched by display name. — 1fed84a
- [x] 2.13 Notice tests prove a parent demoted or deactivated by another parent sees the matching Polish notice exactly once on the next request, a self-demoted parent does not see it, and a promotion shows no notice. — 1fed84a
- [x] 2.6 Full tests pass: `uv run python manage.py test`. — 1fed84a
- [x] 2.7 Django checks pass: `uv run python manage.py check`. — 1fed84a
- [x] 2.8 Migration drift check passes: `uv run python manage.py makemigrations --check --dry-run`. — 1fed84a

#### Manual

- [x] 2.9 At 360px width a parent promotes a seeded child, sees that child reach the parent index, then demotes them back.
- [x] 2.10 The last-parent explanation and the self-demotion confirmation are clear and usable without JavaScript.
- [x] 2.11 A keyboard-only pass on the role-change form follows the `context/foundation/accessibility.md` checklist.
- [x] 2.14 A reviewer follows the Operator Recovery Runbook on a seeded demoted parent and restores their parent role in Django admin.
