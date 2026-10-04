# Family Membership Management Implementation Plan

## Overview

Implement future-roadmap slice S-14 (PK-16): an authorized family manager can manage the existing members of their family inside the application instead of asking the operator to edit Django admin. The increment lets a manager list members, rename a member, and deactivate or reactivate a member. Adding a person to a family (creating a `FamilyMember`) stays operator-only in Django admin, exactly as today; there is no invitation flow and no self-service joining. Families are still created by the operator, and every user keeps at most one active membership. S-16 removes that limit.

### Decisions

Owner decisions, including the plan-review triage, were applied 2026-10-04. Items marked "assumed" are planning defaults the owner may revisit; they do not block implementation.

1. **A family manager is any active parent of an active family.** No separate "manager" role or flag is introduced. This reuses `is_parent` (`family_access/access.py:24`) and keeps one permission concept. (owner-confirmed 2026-10-04)
2. **Only the operator creates families, in Django admin.** There is no in-app family creation in this increment. (owner-confirmed 2026-10-04)
3. **Adding a person to a family stays operator-only in Django admin.** The operator creates the `FamilyMember` (with its role) in `FamilyMemberAdmin` (`family_access/admin.py:15`). There is no `FamilyInvitation` model, no invite, accept or decline page, and no self-service joining. In-app management covers only existing members. (owner-confirmed 2026-10-04)
4. **A new person gets a `User` through Google first sign-in, then the operator maps it.** This is the S-09 `remove-sign-up-option` contract: username/password sign-up is closed, Google first sign-in still auto-creates the `User`, and the operator links it to a `FamilyMember` in admin. S-14 does not change sign-up or sign-in. (owner-confirmed 2026-10-04)
5. **In-app management is limited to rename, deactivate and reactivate.** Changing the role of an existing member belongs to S-15 (`family-role-management`), which lands next. (owner-confirmed 2026-10-04)
6. **Removing a member means deactivating them (soft).** Rows are never hard-deleted, and a member can be reactivated. Entries use `on_delete=RESTRICT` for assignees (`entries/models.py:34`), and history must survive. (owner-confirmed 2026-10-04)
7. **The last active parent cannot be deactivated, and the check runs under a `Family` row lock.** This prevents a family from losing every manager, including under concurrent changes. A "remaining parent" is an active parent membership whose `User` is also active, because a disabled `User` cannot sign in or use tokens (`family_access/automation.py:54`). Authority is checked after the lock: the actor and target rows are re-read under the lock, so a parent who lost access while waiting cannot act. (owner-confirmed 2026-10-04)
8. **A manager cannot deactivate themselves.** Self-removal would lock the actor out mid-action; another parent or the operator does it instead. (owner-confirmed 2026-10-04)
9. **Deactivating a parent revokes their automation tokens** in the same transaction. Reactivating the parent does not restore those tokens; the operator issues new ones in Django admin (`family_access/admin.py:40`). This matches the PRD guardrail on immediate token revocation. (owner-confirmed 2026-10-04)
10. **The one-active-membership-per-user constraint stays until S-16.** Reactivating a member whose user is already active in another family is refused with a Polish explanation. This keeps `get_active_membership` (`family_access/access.py:6`) unambiguous until S-16. (owner-confirmed 2026-10-04)
11. **The member list tells parents how new people are added.** A short Polish note says that adding a person is done by the family administrator (the operator), so parents do not look for an invite button. (assumed)
12. **Audit uses content-free application logs only:** event, family id, member id and actor id, with no names or emails. There is no audit table. This follows `family_notes/log_safety.py` and the hard rule against secondary storage. (assumed)
13. **New pages follow the S-17 accessibility conventions.** S-17 `accessible-family-flows` lands before this slice and provides `context/foundation/accessibility.md` and the page audit helper `family_notes/a11y_audit.py`. This plan adds audit cases for its pages and does not re-specify the criteria. (owner-confirmed 2026-10-04)
14. **No feature flag, no data backfill, and no Playwright/E2E tests in this slice.** Verification uses Django tests plus a manual pass. (owner-confirmed 2026-10-04)
15. **Any active parent may reactivate any deactivated member, including a parent.** Reactivating a parent restores parent rights, so the parent row's reactivate action sits behind a no-JavaScript Polish confirmation ("Ta osoba odzyska uprawnienia rodzica.") and emits the same id-only log line as every other mutation. Tokens stay revoked. (owner-confirmed 2026-10-04)
16. **A rename cannot create an ambiguous member name.** EduVulcan matching (`entries/eduvulcan/children.py:36-48`, `match_child`) and S-02 short-name resolution key on display names, so `rename_member` refuses a name whose `normalize_child_name(...)` equals that of another active member of the same family. (review triage 2026-10-04)

## Current State Analysis

- Families and memberships are configured only by the operator in Django admin (`family_access/admin.py:8`, `family_access/admin.py:15`), following the F-01 plan (`context/archive/2026-09-23-identity-and-family-access-contract/plan.md:133`). This remains the only way to add a member after this slice.
- First sign-in today: a person signs in with Google through allauth (`family_notes/settings.py:203`, `:429`). Allauth creates a `User`, and `/account/` shows "Twoje członkostwo w rodzinie nie jest jeszcze skonfigurowane." (`family_access/templates/family_access/account_status.html:22`). The operator then creates a `FamilyMember` that links that `User` to the family. S-09 (`context/changes/remove-sign-up-option/plan.md`) closes local sign-up and keeps this Google path; it lands before this slice.
- `FamilyMember` has `user`, `family`, `role` (parent/child), `display_name`, `is_active` and timestamps. A partial unique constraint allows at most one active membership per user (`family_access/models.py:46`). Inactive history rows are allowed (`family_access/tests/test_access.py:76`).
- All family scoping goes through `family_access/access.py`: `get_active_membership` (`:6`), `is_parent` (`:24`) and `scope_queryset_to_family` (`:33`). Product services re-check authorization themselves (`entries/services.py:113`).
- Automation tokens belong to a `FamilyMember` (`family_access/models.py:57`), carry `revoked_at` (`:73`), are issued by the operator in admin (`family_access/admin.py:40`), and are rejected when their owner is not an active parent (`family_access/automation.py:52`).
- EduVulcan conversion matches children by `display_name` among the active children of the notification's family (`entries/eduvulcan/children.py:13`). Renaming or deactivating a child therefore changes automated assignment.
- `family_access` has one web view, `account_status` (`family_access/views.py:8`), and one route (`family_access/urls.py`). There is no in-app membership management.

## Desired End State

An active parent opens "Członkowie rodziny" from the account page and sees the active and inactive members of their own family only, with a note that adding a person is done by the family administrator. They can rename a member and deactivate or reactivate members, subject to the self and last-parent guards. Deactivating a parent revokes that parent's automation tokens. A deactivated member loses web access on their next request and sees the "not configured" account state. Children, members of other families, users without a membership and anonymous users cannot use any management path or learn whether foreign members exist. The new pages pass the S-17 page audit.

### Key Discoveries:

- Assignees use `on_delete=RESTRICT` (`entries/models.py:34`), so deleting a member is not possible without moving entries. Deactivation is the right primitive. Edit forms already keep an inactive assignee (`entries/services.py:91`, `kept_assignee_id`).
- Assignee choices only list active members of the family (`entries/forms.py:84`). Deactivated members disappear from new assignments with no further change.
- Token authentication re-checks `is_parent(token.member)` on every request (`family_access/automation.py:52`). Deactivation would already block tokens, but explicit revocation keeps a later reactivation from silently re-enabling them.
- Reactivation can hit the per-user constraint (`family_access/models.py:46`) when the operator has meanwhile activated the same user in another family, so the service must check first and map an `IntegrityError` to a Polish error.
- The house pattern is function views, explicit services that re-check authorization, Polish copy, `tokens.css` components, and DEBUG-only state galleries (`entries/views.py:249`, `AGENTS.md` UI Conventions).
- No schema change is needed: rename, deactivate and reactivate only update existing `FamilyMember` and `AutomationToken` columns.

## What We're NOT Doing

- No email invitations: no `FamilyInvitation` model, no invite, accept or decline pages, and no invitation acceptance into a family.
- No self-service joining and no in-app creation of `FamilyMember` rows. Adding a person stays operator-only in Django admin.
- No in-app creation, renaming or deactivation of families. The operator keeps using Django admin.
- No role changes for existing members (S-15) and no multi-family membership or context switching (S-16).
- No outbound email and no user search or "existing account" lookup.
- No hard deletion of members and no reassignment of their entries.
- No in-app token issuing; reactivated parents get new tokens from the operator in admin.
- No changes to Django `is_staff` or `is_superuser`. In-app management never grants admin access.
- No audit table and no notification to the affected member.
- No change to the sign-up or sign-in flow (S-09 `remove-sign-up-option` owns that).
- No feature flag, data backfill or Playwright/E2E tests.

## Implementation Approach

Add a `family_access/membership.py` service module. That module is the only in-app write path for membership changes. Each service function takes the acting `FamilyMember` (not the `User`), re-checks that the actor is a parent, resolves the target inside the actor's family (foreign or missing gives the same not-found), and serializes guarded changes by locking the `Family` row. Thin function views in `family_access/views.py` under `/account/family/` render Polish templates built from the existing partials, the S-17 field contract and `tokens.css`. Taking the actor membership rather than the user is deliberate: S-16 can pass the request's chosen family context without changing these signatures.

## Critical Implementation Details

- **State sequencing:** every mutation (rename, deactivate, reactivate, and the S-15 role change) runs in `transaction.atomic()`. It first locks the actor's `Family` row with `select_for_update()`, then re-reads the actor and target rows under the lock and re-checks `is_parent(fresh_actor)` and the target's current state, then counts remaining parents and changes the row. Checks on the request-resolved `actor` object are never the final authority, because another parent may have deactivated or demoted the actor while this request waited on the lock. This makes two parents who deactivate each other at the same moment safe on PostgreSQL. SQLite serializes writers, so tests cover the guard logic rather than real concurrency.

## Phase 1: Membership Services and Guards

### Overview

Add an independently authorized service layer for rename, deactivate and reactivate, with the shared lock and last-parent guard.

### Changes Required:

#### 1. Membership service module

**File**: `family_access/membership.py` (new)

**Intent**: Give in-app membership changes one auditable boundary that does not depend on view checks.

**Contract**:
- `family_members(actor)` returns the actor family's members, active first and then by display name.
- `get_family_member(actor, member_id)` returns one member of the actor's family.
- `rename_member(actor, member_id, display_name)` strips the name, rejects blank or over-length values (max 120, the model limit) with a Polish `ValidationError`, and rejects a name whose `normalize_child_name(...)` (`entries/eduvulcan/children.py:31`) equals that of another active member of the same family ("W rodzinie jest już osoba o takim imieniu.").
- `deactivate_member(actor, member_id)` refuses the actor and the last active parent, sets `is_active=False`, and sets `revoked_at` on the member's unrevoked automation tokens.
- `reactivate_member(actor, member_id)` sets `is_active=True` for a child or a parent (Decision 15). It gives a Polish error when the user already has an active membership elsewhere, and maps a uniqueness violation to the same error.

Every function raises `PermissionDenied` unless `is_parent(actor)`, and raises `FamilyMember.DoesNotExist` for foreign and missing ids alike. For every mutation these checks run on rows re-read under the lock (see §2); a pre-lock check on the request's in-memory `actor` is only a fast path. Every mutation emits one content-free log line (`membership_event=<name> family=<id> member=<id> actor=<id>`).

#### 2. Shared guard helper

**File**: `family_access/membership.py`

**Intent**: S-15 reuses the last-parent guard, so it lives in one named helper.

**Contract**:
- `_lock_family(family_id)` returns the `Family` row locked for update.
- `_relock_members(family, actor_id, member_id)` runs right after `_lock_family` and re-fetches the actor and the target with `FamilyMember.objects.select_for_update().get(pk=..., family_id=family.pk)`. It raises `PermissionDenied` unless `is_parent(fresh_actor)`, and every later state check (target active or inactive, self, role) uses the fresh rows. The mutation saves and returns the fresh target. This mirrors the entry write path, which re-reads under lock (`entries/services.py:126`, `_locked_family_entry`). S-15 and S-16 reuse the same sequence.
- `_ensure_parent_remains(family, *, excluding_member_id)` counts only `role=PARENT, is_active=True, user__is_active=True` members other than the excluded one, and raises a `ValidationError` ("Rodzina musi mieć co najmniej jednego aktywnego rodzica.") when none would remain.
- Django admin edits bypass this lock. That is accepted, because only the operator uses admin.

### Success Criteria:

#### Automated Verification:

- Service tests cover listing, rename, deactivate and reactivate for an active parent, plus denial for a child, an inactive parent, a parent of another family, and a missing actor membership.
- Rename tests reject a blank or over-length display name, and a name that normalizes to another active member's name, with a Polish error and leave the row unchanged.
- Guard tests prove a parent cannot deactivate themselves or the last active parent, that deactivation revokes that member's automation tokens, and that reactivation leaves them revoked.
- Reactivation tests cover reactivating an inactive member and the Polish error when the user is already active in another family.
- Stale-authority tests change the actor's or target's row directly in the database after it was resolved (actor deactivated or demoted; target already reactivated or deactivated) and prove the call raises `PermissionDenied` or the Polish state error with no change.
- A guard test proves a parent whose `User.is_active` is False does not count as a remaining parent, so the last usable parent cannot be deactivated.
- Targeted tests pass: `uv run python manage.py test family_access.tests.test_membership_services`.
- Migration drift check passes with no new migration: `uv run python manage.py makemigrations --check --dry-run`.

#### Manual Verification:

- A reviewer confirms the service log lines contain only ids and event names, with no emails or display names.

**Implementation Note**: After completing this phase and all automated verification passes, pause for manual confirmation before proceeding.

---

## Phase 2: Parent Member-Management UI and Regression

### Overview

Expose the services to active parents through Polish, accessible pages, and prove deactivation interacts correctly with entries, child matching and tokens.

### Changes Required:

#### 1. Routes and views

**File**: `family_access/urls.py`, `family_access/views.py`, `family_access/forms.py` (new)

**Intent**: Follow the parent-only conventions used by entry management (`entries/views.py:86`).

**Contract**:
- `GET /account/family/` (`family_members`) lists members.
- `GET|POST /account/family/members/<pk>/edit/` (`family_member_edit`) changes the display name.
- `POST /account/family/members/<pk>/deactivate/` (`family_member_deactivate`) and `POST /account/family/members/<pk>/reactivate/` (`family_member_reactivate`).

Anonymous users are redirected to login. Authenticated users who are not parents get 403. Foreign and missing ids both give 404. Every POST uses CSRF and redirects back to the list with a Polish `messages` notice. Guard failures re-render the list with the Polish error and change nothing.

#### 2. Templates and navigation

**File**: `family_access/templates/family_access/members.html`, `member_edit.html`, `family_access/templates/family_access/account_status.html`

**Intent**: Reuse the shared field partial (with the S-17 error and hint association), the S-17 error summary and title conventions, and `tokens.css` classes, with no inline styles.

**Contract**: The list shows each member's display name, role ("Rodzic" or "Dziecko") and status, plus the actions allowed. The actor's own row and the last active parent have no deactivate action. Deactivation uses a no-JavaScript `<details>` confirmation that warns that automation tokens will be revoked. Reactivating a parent uses the same kind of confirmation with "Ta osoba odzyska uprawnienia rodzica." (Decision 15); reactivating a child needs no confirmation. The list states in Polish that adding a person to the family is done by the family administrator. The edit page for a child notes that the name is used to match school notifications, and a duplicate-name error is shown through the S-17 error summary. Parents get a "Członkowie rodziny" link from `/account/`. All copy is in Polish.

#### 3. DEBUG state gallery

**File**: `family_access/views.py`, `family_access/templates/family_access/member_states.html`, `family_access/urls.py`

**Intent**: Follow the kitchen-sink convention from `AGENTS.md` for the new views.

**Contract**: `GET /account/family/_states/` exists only under DEBUG, for parents, and uses unsaved synthetic data. It shows a populated list with inactive members, the opened deactivate confirmation, the opened parent-reactivation confirmation, the guard error, the reactivation error, and the edit form with and without errors (including the duplicate-name error). With `DEBUG=False` it returns 404, and it creates no rows.

#### 4. Accessibility audit cases

**File**: `family_access/tests/test_membership_accessibility.py` (new)

**Intent**: Add the new pages to the S-17 audit, as `context/foundation/accessibility.md` requires for new product pages.

**Contract**: Each case renders a real view and calls the S-17 `assert_accessible` from `family_notes/a11y_audit.py`: member list (populated, with a guard error), edit form (valid and invalid), and the account page with the new parent link.

#### 5. Regression

**File**: `family_access/tests/`, `entries/tests/` (only if a regression surfaces)

**Intent**: Show that deactivation interacts correctly with entries, child matching, tokens and the account page.

**Contract**: A deactivated child no longer appears in assignee choices or EduVulcan child snapshots, while existing assigned entries stay readable to parents. A deactivated parent's token gets 401. A deactivated member gets 403 on entry views and sees the "not configured" state on `/account/`. A reactivated member regains access on the next request.

### Success Criteria:

#### Automated Verification:

- View tests cover each route for a parent, a child, an inactive parent, a parent of another family, a user without a membership, and an anonymous user.
- Mutation-denial tests prove the database is unchanged after a 403, a 404 or a guard error.
- Foreign and nonexistent member ids return the same status and show no foreign content.
- Accessibility audit cases pass for the member list, the edit form (valid and invalid) and the account page: `uv run python manage.py test family_access.tests.test_membership_accessibility`.
- State-gallery tests prove DEBUG gating, parent-only access and no database writes.
- View tests prove an inactive parent's row renders the reactivation confirmation with "Ta osoba odzyska uprawnienia rodzica.", an inactive child's row does not, and a parent reactivation emits only the id-only log line.
- Regression tests cover deactivation effects on assignee choices, EduVulcan child snapshots, parent entry visibility, token 401 and the account page, and access restored after reactivation.
- Full tests pass: `uv run python manage.py test`.
- Django checks pass: `uv run python manage.py check`.
- Migration drift check passes: `uv run python manage.py makemigrations --check --dry-run`.

#### Manual Verification:

- At 360px width a parent can rename a member and deactivate and reactivate a child, and sees the guard explanation for themselves and the last parent.
- A keyboard-only pass on the member list and edit page follows the `context/foundation/accessibility.md` checklist.
- The operator adds a new member in Django admin for a user created by Google first sign-in, and that member appears in the in-app list on the next request.

**Implementation Note**: Complete manual verification before implementation review.

---

## Testing Strategy

### Unit Tests:

- Actor authorization and family scoping for every service function.
- Display-name validation on rename.
- Self and last-parent guards (including a disabled `User`), lock-then-re-read authority, and token revocation on deactivation with no restoration on reactivation.
- Duplicate normalized names refused on rename.
- Reactivation refused when the user is active in another family.

### Integration Tests:

- The access matrix for every route, including foreign ids.
- Deactivation effects on assignee choices, EduVulcan child snapshots, automation tokens and the account page.
- S-17 page audit cases for every new page and state.

### Manual Testing Steps:

1. As a seeded parent, open `/account/` → "Członkowie rodziny" and review the list and the "added by the administrator" note.
2. Rename the child and confirm the new name appears in assignee choices.
3. Try to deactivate yourself and the last parent, and confirm both are refused.
4. Deactivate the child, confirm they see "nie jest jeszcze skonfigurowane", then reactivate.
5. With a second parent deactivated, open their reactivate action, read the "Ta osoba odzyska uprawnienia rodzica." confirmation and reactivate them.
6. Retry each action as a child and with a foreign member URL.
7. As the operator, add a member in Django admin and confirm the parent sees them in the list.

## Performance Considerations

Families have about five members, so pagination is unnecessary. The `Family` row lock is held only for a few short statements.

## Migration Notes

No schema or data migration, no backfill and no feature flag. Rollback is to remove the routes, views, templates and service module; existing memberships and tokens are untouched, and any renames or deactivations made in the meantime stay valid `FamilyMember` values the operator can change in admin.

## References

- `context/foundation/prd-v2.md` — PK-16, Access Control Changes, Open Question 17
- `context/foundation/roadmap-future.md` — S-14
- `context/foundation/roadmap-future-questions.md` — S-14 / S-15 / S-16 questions
- `context/archive/2026-09-23-identity-and-family-access-contract/plan.md`
- `context/changes/remove-sign-up-option/plan.md` (S-09, Google first sign-in and admin mapping)
- `context/changes/accessible-family-flows/plan.md` (S-17, `accessibility.md` and `family_notes/a11y_audit.py`)
- `family_access/models.py:24`, `family_access/models.py:46`, `family_access/models.py:57`, `family_access/access.py:6`, `family_access/admin.py:15`
- `family_access/automation.py:52`, `family_access/automation.py:54`, `entries/eduvulcan/children.py:13`, `entries/eduvulcan/children.py:36`, `entries/services.py:126`, `entries/models.py:34`, `entries/forms.py:84`
- Follow-ups: `context/changes/family-role-management/plan.md` (S-15), `context/changes/multiple-family-use/plan.md` (S-16)

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Membership Services and Guards

#### Automated

- [ ] 1.1 Service tests cover listing, rename, deactivate and reactivate for an active parent, plus denial for a child, an inactive parent, a parent of another family, and a missing actor membership.
- [ ] 1.2 Rename tests reject a blank or over-length display name, and a name that normalizes to another active member's name, with a Polish error and leave the row unchanged.
- [ ] 1.3 Guard tests prove a parent cannot deactivate themselves or the last active parent, that deactivation revokes that member's automation tokens, and that reactivation leaves them revoked.
- [ ] 1.4 Reactivation tests cover reactivating an inactive member and the Polish error when the user is already active in another family.
- [ ] 1.5 Targeted tests pass: `uv run python manage.py test family_access.tests.test_membership_services`.
- [ ] 1.6 Migration drift check passes with no new migration: `uv run python manage.py makemigrations --check --dry-run`.
- [ ] 1.8 Stale-authority tests change the actor's or target's row directly in the database after it was resolved (actor deactivated or demoted; target already reactivated or deactivated) and prove the call raises `PermissionDenied` or the Polish state error with no change.
- [ ] 1.9 A guard test proves a parent whose `User.is_active` is False does not count as a remaining parent, so the last usable parent cannot be deactivated.

#### Manual

- [ ] 1.7 A reviewer confirms the service log lines contain only ids and event names, with no emails or display names.

### Phase 2: Parent Member-Management UI and Regression

#### Automated

- [ ] 2.1 View tests cover each route for a parent, a child, an inactive parent, a parent of another family, a user without a membership, and an anonymous user.
- [ ] 2.2 Mutation-denial tests prove the database is unchanged after a 403, a 404 or a guard error.
- [ ] 2.3 Foreign and nonexistent member ids return the same status and show no foreign content.
- [ ] 2.4 Accessibility audit cases pass for the member list, the edit form (valid and invalid) and the account page: `uv run python manage.py test family_access.tests.test_membership_accessibility`.
- [ ] 2.5 State-gallery tests prove DEBUG gating, parent-only access and no database writes.
- [ ] 2.6 Regression tests cover deactivation effects on assignee choices, EduVulcan child snapshots, parent entry visibility, token 401 and the account page, and access restored after reactivation.
- [ ] 2.7 Full tests pass: `uv run python manage.py test`.
- [ ] 2.8 Django checks pass: `uv run python manage.py check`.
- [ ] 2.9 Migration drift check passes: `uv run python manage.py makemigrations --check --dry-run`.
- [ ] 2.13 View tests prove an inactive parent's row renders the reactivation confirmation with "Ta osoba odzyska uprawnienia rodzica.", an inactive child's row does not, and a parent reactivation emits only the id-only log line.

#### Manual

- [ ] 2.10 At 360px width a parent can rename a member and deactivate and reactivate a child, and sees the guard explanation for themselves and the last parent.
- [ ] 2.11 A keyboard-only pass on the member list and edit page follows the `context/foundation/accessibility.md` checklist.
- [ ] 2.12 The operator adds a new member in Django admin for a user created by Google first sign-in, and that member appears in the in-app list on the next request.
