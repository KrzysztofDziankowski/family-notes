# Multiple Family Use Implementation Plan

## Overview

Implement future-roadmap slice S-16 (PK-16): one signed-in person can be an active member of several families and switch between them. Every web view, mutation, classification call, automation token and background conversion must act only in the authorized family context. This is the riskiest PK-16 slice. Today the "one active membership per user" database constraint (`family_access/models.py:46`) lets every code path ask "what is *the* family of this user?" (`family_access/access.py:6`). Removing the constraint without replacing that question everywhere would silently pick an arbitrary family. The plan therefore replaces the user-based lookup with an explicit, validated, per-request family context and removes the old helper so no call site can keep using it.

### Decisions

Owner decisions, including the plan-review triage, were applied 2026-10-04. Items marked "assumed" are planning defaults the owner may revisit; they do not block implementation.

1. **Only the operator creates families and memberships, in Django admin.** A person joins an additional family only when the operator creates a second active `FamilyMember` for their `User` in `FamilyMemberAdmin` (`family_access/admin.py:15`). There is no invitation-based joining and no self-service grant path. (owner-confirmed 2026-10-04)
2. **The role belongs to each membership.** A person can be a parent in one family and a child in another, and the role of the *current* family governs every check. This matches the existing per-membership role model. (owner-confirmed 2026-10-04)
3. **The current family is kept in the session and validated against the database on every request.** One active membership means it is selected automatically. Several active memberships with no valid selection send the user to a family chooser, and the app never guesses. Guessing could write entries into the wrong family. (owner-confirmed 2026-10-04)
4. **Switching family is an explicit CSRF-protected POST from a header link and the chooser, followed by a redirect to the role home page.** It never redirects back to the previous URL, because entry ids from one family are meaningless in another. (assumed)
5. **Every mutation form carries the family id it was rendered for, and the check is enforced centrally.** `FamilyContextMiddleware` compares it with the current context on every unsafe-method request to the `entries` and `family_access` namespaces, so new forms (including those added by S-03, S-04 and S-07) are covered without a hand-written list. A mismatch (a stale tab after switching elsewhere) is refused with a Polish 409 page and nothing is written. A session-based context is otherwise vulnerable to cross-tab mix-ups. (owner-confirmed 2026-10-04)
6. **Automation tokens stay bound to one membership, and therefore one family.** No token works across families, and the API never accepts a family from the client. This preserves the MS-01 "family comes only from the token" contract (`entries/api_views.py:249`). (assumed)
7. **The EduVulcan worker keeps using the family stored on the notification at intake** (`entries/eduvulcan/conversion.py:283`). It needs no user or session context, which is already correct and only needs regression tests. (assumed)
8. **The database constraint becomes "at most one active membership per (user, family)".** The migration cannot fail on existing data, because the old constraint is strictly stronger. (assumed)
9. **The family selection is not remembered across sessions.** After a new sign-in, a multi-family user chooses again. This is the simplest choice and needs no new per-user preference storage. (assumed)
10. **The header shows the current family name and a "Zmień rodzinę" link only for users with more than one active membership.** Single-family users see no change. (assumed)
11. **Sign-up stays as S-09 leaves it.** Google first sign-in creates the `User` once; a second family needs no new account, only a second membership created by the operator. (owner-confirmed 2026-10-04)
12. **The chooser, header indicator and 409 page follow the S-17 accessibility conventions** (`context/foundation/accessibility.md`, `family_notes/a11y_audit.py`); this plan adds audit cases rather than re-specifying them. (owner-confirmed 2026-10-04)
13. **No feature flag, no data backfill, and no Playwright/E2E tests in this slice.** (owner-confirmed 2026-10-04)

## Current State Analysis

- `FamilyMember` allows at most one active membership per user (`family_access/models.py:46`). Inactive history rows are allowed (`family_access/tests/test_access.py:76`).
- `get_active_membership(user)` returns `.first()` of the user's active memberships (`family_access/access.py:6`). It is the single source of family context for:
  - the home redirect (`family_notes/views.py:19`) and the account page (`family_access/views.py:12`);
  - parent services (`entries/services.py:113`, `:139`, `:174`, `:210`, `:246`) and child services (`entries/services.py:257`);
  - classification (`entries/classification/service.py:102`, `:152`);
  - the DEBUG galleries (`entries/views.py:803`).
- `save_confirmed_entry` and the management services take a `user` and resolve the membership themselves (`entries/services.py:22`, `:174`). Forms take a membership and scope their assignee choices with it (`entries/forms.py:84`).
- The automation API gets its family only from `request.automation_membership` (`family_access/automation.py:72`, `entries/api_views.py:100`, `:249`).
- The EduVulcan worker gets the family from `InboundNotification.family` (`entries/eduvulcan/conversion.py:283`), and child snapshots are family-scoped (`entries/eduvulcan/children.py:13`).
- Capture, follow-up and confirm keep their draft state in POSTed form fields, not in the session (`entries/views.py:97`, `:144`, `:203`). A stale tab therefore carries no server-side state, but it would write into whatever family the session currently points to.
- S-14 adds in-app rename, deactivate and reactivate (reactivation is refused when the user is already active elsewhere). S-15 adds role changes. Both take an actor membership, which is ready for context passing. Adding members, including a second membership for the same user, stays operator-only in Django admin.
- `FamilyMemberAdmin` already shows the family column and filters by family (`family_access/admin.py:15-33`). Django model validation runs the conditional `UniqueConstraint` in the admin form, so a duplicate active membership surfaces as a form error rather than an `IntegrityError`.
- S-17 lands before this slice and provides `context/foundation/accessibility.md` and the page audit helper `family_notes/a11y_audit.py`.
- The seed script keys memberships by `user` only (`scripts/dev/seed_test_family.py:36`).

## Desired End State

After the operator gives a person active memberships in families A and B in Django admin, that person signs in, picks a family on the chooser, and uses the app exactly as a single-family user of that family. They can switch through the header at any time. Every entry list, detail, create, edit, delete, capture, classification, member-management and role action applies only to the current family. Submitting a form rendered for A after switching to B is refused without a write. Tokens and the conversion worker stay bound to their own family. Single-family users notice nothing. No code path resolves a family from a `User` without an explicit family id.

### Key Discoveries:

- Removing the constraint alone would make `get_active_membership(...).first()` choose arbitrarily, which is a silent cross-family write risk in every service listed above.
- Services that take `user` re-resolve the context internally. Changing them to take the request-resolved `membership` lets the view's context and the service's context be one validated object, while services still re-check `is_parent` and scope by `membership.family`.
- Entry lookups are already scoped by family (`entries/services.py:126`). A stale entry id from another family returns 404, so the remaining stale-tab risk is *creates* (capture/confirm/create, S-04 batch confirm) and S-14/S-15 actions. The centrally checked hidden family field closes it.
- `_existing_for_key` already rejects an idempotency key that belongs to another family (`entries/services.py:73`).

## What We're NOT Doing

- No invitations, invitation-based joining or self-service joining of a second family; the operator creates every membership in Django admin.
- No in-app family creation, leaving a family, merging families, or moving entries between families.
- No cross-family views (no "all my families" list), and no entry sharing across families.
- No remembered default family across sessions, and no family in the URL path.
- No tokens that span families or accept a client-supplied family.
- No change to EduVulcan conversion logic beyond regression tests.
- No change to roles or guards from S-14/S-15, other than allowing reactivation when the user is active in another family.
- No feature flag, data backfill or Playwright/E2E tests.

## Implementation Approach

Three steps, ordered so the system is never in a state where the constraint is gone but code still asks for "the" family:

1. Introduce the request family-context contract and migrate **every** caller off `get_active_membership(user)` while the old constraint still holds. Behavior is unchanged for single-family users, and the old helper is deleted.
2. Only then swap the database constraint, let the operator add and S-14 reactivate a membership in a second family, and ship the chooser, switcher and stale-tab guard.
3. Prove isolation with a cross-family matrix across web, API and worker.

## Critical Implementation Details

- **Ordering:** the constraint migration must not land before every `get_active_membership` caller is gone. Phase 1 deletes the helper, and Phase 2 adds the migration. A repository grep in Phase 1's success criteria enforces this.
- **Context validation:** the session stores only a family id (`family_access.current_family_id`). On each request it resolves to an active membership of the request user in an *active* family, or it is discarded. A deactivated membership, a deactivated family or a demoted role therefore takes effect on the next request, with no stale cached membership object.
- **Logout and sign-in:** Django rotates or flushes the session at login and logout, so the selection never crosses users.

## Phase 1: Request Family Context and Caller Migration

### Overview

Replace the user-based family lookup with an explicit, request-scoped context and move every product path onto it. The one-membership constraint is still in place.

### Changes Required:

#### 1. Family context contract

**File**: `family_access/access.py`, `family_access/context.py` (new), `family_notes/settings.py`

**Intent**: Give each request exactly one validated family context, or an explicit "choose a family" or "no membership" outcome.

**Contract**:
- `active_memberships(user)` returns the user's active memberships in active families (`is_active=True, family__is_active=True, user__is_active=True`), ordered by family name and then pk. An inactive `User` therefore has no context, which keeps the fail-closed rule that `testing-production-security-schema-safety` Phase 2 adds to `get_active_membership` (reject inactive users independently of authentication middleware).
- `resolve_family_context(request)` returns the current `FamilyMember` and stores its family id in the session:
  - with one active membership, it auto-selects it;
  - with a valid session id, it uses that id;
  - with several memberships and no valid selection, it raises `FamilyContextRequired`;
  - with none (including an inactive `User`), it returns `None`.
- `require_family_context(request)` raises `PermissionDenied` when the result is `None`.
- `peek_family_context(request) -> (membership | None, active_count)` never raises and never redirects. It returns the validated session selection or the single membership, otherwise `None`. The header context processor, the chooser, the logout and login pages and the 403/404/409/500 templates use only this function; only product views call the raising resolver.
- `FamilyContextMiddleware` (added after `AuthenticationMiddleware`) converts `FamilyContextRequired` into a redirect to the chooser (`family_access:select_family`, added in Phase 2; in Phase 1 the exception is unreachable).
- `get_active_membership` and `require_active_membership` are **removed**. `is_parent`, `scope_queryset_to_family` and `can_read_assigned_child` are unchanged.

#### 2. Product services take the context membership

**File**: `entries/services.py`, `entries/classification/service.py`, `family_access/membership.py`

**Intent**: Make the validated context the only family source for service authorization.

**Contract**:
- Rule: no product function in `entries/` or `family_access/` takes a `User` to derive a family. Every parent and child service takes the context membership. The rule covers whatever has merged by implementation time, not a fixed list.
- Known callers today: `require_parent_membership`, `parent_family_entries`, `get_parent_family_entry`, `create_family_entry`, `update_family_entry`, `delete_family_entry`, `save_confirmed_entry`, `child_entries`, `classify_for_parent` and `classify_follow_up_answer`.
- Known additions from earlier slices, as their plans name them: S-03 `free-text-proposal-correction` adds `correct_proposal_for_parent(user, ...)`; S-04 `multi-entry-text-capture` adds `classify_entries_for_parent(user, ...)` and `save_confirmed_entries(user, items)` (with `BatchReviewForm(membership, ...)`); S-07 `parent-note-assignment` adds no `user`-taking service, but its requester identity must come from the context membership passed to `classify_for_parent`. Each switches from `user` to `membership`.
- Each one still re-checks `is_parent` or `can_read_assigned_child` and scopes by `membership.family`.
- S-14/S-15 actor functions already take the actor membership and need no signature change.
- `automation_family_entries` and `create_automated_entry` are unchanged.

#### 3. Views use the context

**File**: `entries/views.py`, `family_access/views.py`, `family_notes/views.py`

**Intent**: Resolve the context once per request and pass it down.

**Contract**:
- Every entries view, every S-14/S-15 view, `account_status`, the DEBUG galleries and `home` call `resolve_family_context(request)` or `require_family_context(request)`, and pass the membership to forms and services.
- `home` routes by the role of the current membership.
- S-15's `MembershipNoticeMiddleware` reads the membership from `peek_family_context` (placed after `FamilyContextMiddleware`), so the changed-role notice applies to the current family's membership only.
- The helper tests in `family_access/tests/test_access.py` (currently `:147-179`) import the deleted helpers; they are rewritten as `resolve_family_context` / `peek_family_context` tests.
- There is no remaining call that derives a family from `request.user` alone, and no view passes `request.user` to a service or form.

### Success Criteria:

#### Automated Verification:

- Context unit tests cover one membership (auto-select), no membership, an inactive membership, an inactive family, an inactive `User`, a session id pointing to a foreign or inactive family (discarded), and an anonymous user.
- No user-based family lookup remains: `grep -rnE "get_active_membership|require_active_membership|family_memberships|FamilyMember\.objects\.filter\(user" --include=*.py entries family_access family_notes | grep -vE "/tests/|/migrations/|family_access/(context|models)\.py"` returns nothing.
- Existing suites pass unchanged in behavior, with the `test_access.py` helper tests rewritten as context tests: `uv run python manage.py test entries family_access family_notes`.
- Django checks pass: `uv run python manage.py check`.
- Migration drift check passes: `uv run python manage.py makemigrations --check --dry-run`.

#### Manual Verification:

- A reviewer confirms no view passes `request.user` to a service or form, and every service added by S-03, S-04 and S-07 takes the context membership.

**Implementation Note**: After completing this phase and all automated verification passes, proceed to Phase 2. This phase is a pure refactor with no user-visible change.

---

## Phase 2: Constraint Swap, Chooser, Switcher and Stale-Tab Guard

### Overview

Allow several active memberships per user and give multi-family users a safe way to choose and switch.

### Changes Required:

#### 1. Constraint migration

**File**: `family_access/models.py`, `family_access/migrations/0004_membership_per_family.py` (generated with `makemigrations family_access --name membership_per_family`)

**Intent**: Allow one active membership per family instead of one per user.

**Contract**: Remove `unique_active_family_membership_per_user`. Add `UniqueConstraint(fields=('user', 'family'), condition=Q(is_active=True), name='unique_active_membership_per_user_family')`. The forward migration always succeeds on existing data. A `RunPython` step has a no-op forward and a reverse that, before the old constraint is restored, raises a clear error listing the user ids (no names or emails) that hold more than one active membership, instead of failing mid-rollback with a raw `IntegrityError`.

#### 2. Operator-created second membership and per-family reactivation

**File**: `family_access/admin.py`, `family_access/membership.py`

**Intent**: Let the operator give a user an active membership in a second family, and let S-14 reactivation follow the same per-family rule.

**Contract**:
- `FamilyMemberAdmin` accepts an active membership in family B for a user already active in family A. A second active row for the same `(user, family)` shows the constraint's validation error in the admin form. Admin copy stays in English.
- The admin validation added by `testing-production-security-schema-safety` (which blocks moving an existing membership to another family) stays in place; the second membership is a new row, not a moved one.
- `reactivate_member` no longer refuses users who are active in another family. It still refuses a duplicate active `(user, family)` row with a Polish error. S-14's "already active elsewhere" message and its tests are replaced accordingly.
- A signed-in user whose session already holds a valid family id keeps that family after the operator adds a second membership, and the header switcher appears on the next request.

#### 3. Chooser and switch routes

**File**: `family_access/urls.py`, `family_access/views.py`, `family_access/templates/family_access/select_family.html`, `family_notes/templates/base.html`

**Intent**: Make choosing and switching explicit, CSRF-protected and visible.

**Contract**:
- `GET /account/family/select/` (`select_family`, login required) lists the user's active memberships: family name and the role in Polish.
- `POST /account/family/select/` takes `family_id` and accepts only one of those memberships. Otherwise it returns 404 and leaves the session unchanged. On success it stores the id and redirects to `home`.
- The chooser, logout, login and admin are exempt from the middleware redirect.
- For users with more than one active membership, `base.html` shows the current family name and a "Zmień rodzinę" link to the chooser. A context processor supplies `current_family` and `family_count` from `peek_family_context`, so rendering any page (including the chooser, logout and error pages) never raises or redirects, and it runs no queries for anonymous users.

#### 4. Stale-tab guard

**File**: `family_access/context.py`, `family_access/templatetags/family_context.py` (new), `entries/templates/entries/`, `family_access/templates/family_access/`, `family_notes/templates/409.html` (new, extends the base layout)

**Intent**: Refuse writes from a form rendered for a different family than the current one, for every current and future form, without a hand-written route list.

**Contract**:
- Enforcement is central, in the same way as `CsrfViewMiddleware` plus `{% csrf_token %}`. `FamilyContextMiddleware.process_view` checks every unsafe-method (POST, PUT, PATCH, DELETE) request from a session-authenticated user whose resolved view is in the `entries` or `family_access` URL namespace. Exempt are the chooser (`family_access:select_family`), allauth, Django admin and `/api/automation/` (token-authenticated, family from the token).
- It compares the posted `family_context` with the current context's family id. On a mismatch it renders the Polish 409 page: "Ta strona dotyczyła innej rodziny. Odśwież ją i spróbuj ponownie." The view and the service are never called.
- A missing field is treated as a mismatch when the user has more than one active membership. With exactly one active membership it is accepted, so forms left open across the deploy do not fail for single-family users.
- A `{% family_context_field %}` template tag renders the hidden field from the current context. Every `method="post"` form in the guarded namespaces includes it, covering today's capture, answer, confirm, create, edit and delete forms, the S-03 correction POST, the S-04 `BatchReviewForm` batch confirm, the S-07 assignment forms, and the S-14/S-15 rename, deactivate, reactivate and role forms.
- There is no per-view `ensure_form_family` call.

#### 5. Accessibility audit cases

**File**: `family_access/tests/test_family_context_accessibility.py` (new)

**Intent**: Add the new pages and the header change to the S-17 audit, as `context/foundation/accessibility.md` requires for new product pages.

**Contract**: Each case renders a real response and calls `assert_accessible` from `family_notes/a11y_audit.py`: the chooser (two memberships, and after an invalid choice), a product page with the header family name and "Zmień rodzinę" link, and the 409 page. The chooser lists families as a labelled radio group or one form per family, and the 409 page extends the base layout with a single `<h1>`.

### Success Criteria:

#### Automated Verification:

- Migration tests use the `MigrationExecutor` pattern from `entries/tests/test_conversion_models.py:255-306` (migrate to `0003`, insert memberships, migrate to `0004`) and prove a user can hold active memberships in two families but not two active memberships in one family, and that the reverse refuses with the offending user ids when duplicates exist.
- Chooser tests cover listing only the user's own active memberships, a foreign or inactive `family_id` returning 404 with the session unchanged, the CSRF requirement, and the redirect to role home.
- Middleware tests prove a multi-family user with no selection is redirected to the chooser from every product route, and that single-family users are never redirected.
- Stale-tab tests walk the URL resolver for the `entries` and `family_access` namespaces and prove every POST route returns 409 and writes nothing when submitted with another family's `family_context` (or none, for a multi-family user), while a missing field is accepted for a single-family user.
- Admin and reactivation tests prove the operator can add an active membership in family B for a user active in A, a duplicate active `(user, family)` row is refused with a form error, and S-14 reactivation succeeds across families.
- Accessibility audit cases pass for the chooser, the header with the family switcher, and the 409 page: `uv run python manage.py test family_access.tests.test_family_context_accessibility`.
- Template tests render every GET page in the guarded namespaces for a multi-family parent and prove each `method="post"` form contains the `family_context` field.
- Context-processor tests prove a multi-family user with no selection can GET the chooser and the logout page and gets a plain 404 page for an unknown URL, with no redirect and no exception.
- Full tests pass: `uv run python manage.py test`.
- Django checks pass: `uv run python manage.py check`.
- Migration drift check passes: `uv run python manage.py makemigrations --check --dry-run`.

#### Manual Verification:

- At 360px width a two-family user picks a family, sees its name in the header, switches, and sees only the other family's entries.
- With two tabs on different families, saving a capture in the stale tab shows the Polish 409 page and creates no entry.
- The operator adds a second membership in Django admin for an existing user, and that user sees the "Zmień rodzinę" link on the next request.
- A keyboard-only pass on the chooser and the header switcher follows the `context/foundation/accessibility.md` checklist.

**Implementation Note**: After completing this phase and all automated verification passes, pause for manual confirmation before proceeding.

---

## Phase 3: Cross-Family Isolation Matrix, Automation and Worker Regression

### Overview

Prove that no web, API or background path can cross the family boundary for a multi-family user.

### Changes Required:

#### 1. Cross-family web matrix

**File**: `entries/tests/test_multi_family_access.py`, `family_access/tests/test_multi_family_access.py`

**Intent**: Systematically cover every route for a user who is a parent in A and a child in B.

**Contract**: For each entries route (index, detail, create, edit, delete, capture, answer, confirm, child list, child detail) and each S-14/S-15 route:
- with context A, B's ids return 404 and lists contain only A's data;
- with context B, parent routes return 403 and the child views show only entries assigned to that membership in B;
- assignee choices and classification candidates come only from the current family;
- denials leave the database unchanged.

#### 2. Automation and worker regression

**File**: `entries/tests/test_entries_api.py`, `entries/tests/test_notification_intake.py`, `entries/tests/test_conversion_worker.py`

**Intent**: Pin the existing family binding of tokens and the worker for multi-family owners.

**Contract**: A token issued to the user's membership in A reads and submits only in A, even after the session switches to B. Notifications submitted with A's token convert into A, with child matching only among A's children. Deactivating the A membership makes the A token return 401 while the user's B membership keeps working.

#### 3. Developer tooling and docs

**File**: `scripts/dev/seed_test_family.py`, `family_access/admin.py`, `AGENTS.md`

**Intent**: Keep local QA and the operator view consistent with multiple memberships.

**Contract**:
- The seed script keys memberships by `(user, family)` and adds one user who is a parent in "Rodzina testowa" and a child in "Inna rodzina".
- `FamilyMemberAdmin` lists the family column (already present) and drops any reliance on a single membership.
- The AGENTS.md hard rule is amended: "resolve family only through the request family context; never from the user alone".

### Success Criteria:

#### Automated Verification:

- The cross-family matrix passes for every listed web route: `uv run python manage.py test entries.tests.test_multi_family_access family_access.tests.test_multi_family_access`.
- Automation and worker regression tests pass: `uv run python manage.py test entries.tests.test_entries_api entries.tests.test_notification_intake entries.tests.test_conversion_worker`.
- Full tests pass: `uv run python manage.py test`.
- Django checks pass: `uv run python manage.py check`.
- Migration drift check passes: `uv run python manage.py makemigrations --check --dry-run`.

#### Manual Verification:

- With the seeded two-family user, a reviewer completes parent capture in one family and the child view in the other, and confirms no data from the other family appears anywhere.
- A reviewer confirms that a single-family user's flows (seeded parent and child) look and behave exactly as before.

**Implementation Note**: Complete manual verification before implementation review.

---

## Testing Strategy

### Unit Tests:

- Context resolution for every membership, session and activity combination.
- Per-family uniqueness under the new constraint.
- The chooser's validation of `family_id`.
- The central stale-tab guard across every POST route found by the URL resolver.
- The non-raising `peek_family_context` for the header and error pages.
- S-17 page audit cases for the chooser, the header switcher and the 409 page.

### Integration Tests:

- Operator adds a second-family membership in admin → switch → isolated data.
- Cross-family route matrix with mixed roles (parent in A, child in B).
- Token and worker binding for multi-family owners.

### Manual Testing Steps:

1. Sign in as the seeded two-family user, confirm the chooser appears, and pick "Rodzina testowa".
2. Create an entry, switch to "Inna rodzina", and confirm it is absent and the child view is shown.
3. Open two tabs on different families and submit a form from the stale one; expect the 409 page.
4. Deactivate the user's membership in one family as that family's parent, and confirm the user is auto-placed in the remaining family on the next request.

## Performance Considerations

Context resolution adds one indexed membership query per request, which is negligible at family scale. The context processor reuses the resolved membership rather than querying again.

## Migration Notes

`0004` swaps one partial unique constraint for another and does not touch data; S-14 and S-15 add no migrations, so it follows `0003_authcacheentry`. There is no backfill and no feature flag. The forward migration cannot fail, because the old constraint implies the new one. Rollback has two parts. First, ensure no user has more than one active membership; an operator deactivates extras in Django admin (the reverse `RunPython` step lists offending user ids if any remain). Then unapply `0004` and revert Phases 2–3. Phase 1 is behavior-neutral and can stay. Existing tokens, entries and notifications keep their family foreign keys and need no backfill.

## References

- `context/foundation/prd-v2.md` — PK-16, Access Control Changes, Guardrails, Open Question 17
- `context/foundation/roadmap-future.md` — S-16 (risk: every view and mutation must use the authorized family context)
- `context/foundation/roadmap-future-questions.md` — S-14 / S-15 / S-16 questions
- `context/changes/remove-sign-up-option/plan.md` (S-09, Google first sign-in and admin mapping)
- `context/changes/testing-production-security-schema-safety/plan.md` (inactive-User rule and admin move validation)
- `context/changes/free-text-proposal-correction/plan.md` (S-03), `context/changes/multi-entry-text-capture/plan.md` (S-04), `context/changes/parent-note-assignment/plan.md` (S-07)
- `context/changes/accessible-family-flows/plan.md` (S-17, `accessibility.md` and `family_notes/a11y_audit.py`)
- Prerequisites: `context/changes/family-membership-management/plan.md` (S-14), `context/changes/family-role-management/plan.md` (S-15)
- `family_access/models.py:46`, `family_access/access.py:6`, `family_access/automation.py:72`, `family_access/admin.py:15`
- `entries/services.py:73`, `entries/services.py:113`, `entries/services.py:257`, `entries/classification/service.py:102`
- `entries/api_views.py:249`, `entries/eduvulcan/conversion.py:283`, `entries/eduvulcan/children.py:13`
- `family_notes/views.py:19`, `scripts/dev/seed_test_family.py:36`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Request Family Context and Caller Migration

#### Automated

- [x] 1.1 Context unit tests cover one membership (auto-select), no membership, an inactive membership, an inactive family, an inactive `User`, a session id pointing to a foreign or inactive family (discarded), and an anonymous user. — e88959e
- [x] 1.2 No user-based family lookup remains: `grep -rnE "get_active_membership|require_active_membership|family_memberships|FamilyMember\.objects\.filter\(user" --include=*.py entries family_access family_notes | grep -vE "/tests/|/migrations/|family_access/(context|models)\.py"` returns nothing. — e88959e
- [x] 1.3 Existing suites pass unchanged in behavior, with the `test_access.py` helper tests rewritten as context tests: `uv run python manage.py test entries family_access family_notes`. — e88959e
- [x] 1.4 Django checks pass: `uv run python manage.py check`. — e88959e
- [x] 1.5 Migration drift check passes: `uv run python manage.py makemigrations --check --dry-run`. — e88959e

#### Manual

- [x] 1.6 A reviewer confirms no view passes `request.user` to a service or form, and every service added by S-03, S-04 and S-07 takes the context membership.

### Phase 2: Constraint Swap, Chooser, Switcher and Stale-Tab Guard

#### Automated

- [x] 2.1 Migration tests use the `MigrationExecutor` pattern from `entries/tests/test_conversion_models.py:255-306` (migrate to `0003`, insert memberships, migrate to `0004`) and prove a user can hold active memberships in two families but not two active memberships in one family, and that the reverse refuses with the offending user ids when duplicates exist. — 5064767
- [x] 2.2 Chooser tests cover listing only the user's own active memberships, a foreign or inactive `family_id` returning 404 with the session unchanged, the CSRF requirement, and the redirect to role home. — 5064767
- [x] 2.3 Middleware tests prove a multi-family user with no selection is redirected to the chooser from every product route, and that single-family users are never redirected. — 5064767
- [x] 2.4 Stale-tab tests walk the URL resolver for the `entries` and `family_access` namespaces and prove every POST route returns 409 and writes nothing when submitted with another family's `family_context` (or none, for a multi-family user), while a missing field is accepted for a single-family user. — 5064767
- [x] 2.5 Admin and reactivation tests prove the operator can add an active membership in family B for a user active in A, a duplicate active `(user, family)` row is refused with a form error, and S-14 reactivation succeeds across families. — 5064767
- [x] 2.6 Accessibility audit cases pass for the chooser, the header with the family switcher, and the 409 page: `uv run python manage.py test family_access.tests.test_family_context_accessibility`. — 5064767
- [x] 2.7 Full tests pass: `uv run python manage.py test`. — 5064767
- [x] 2.8 Django checks pass: `uv run python manage.py check`. — 5064767
- [x] 2.9 Migration drift check passes: `uv run python manage.py makemigrations --check --dry-run`. — 5064767
- [x] 2.14 Template tests render every GET page in the guarded namespaces for a multi-family parent and prove each `method="post"` form contains the `family_context` field. — 5064767
- [x] 2.15 Context-processor tests prove a multi-family user with no selection can GET the chooser and the logout page and gets a plain 404 page for an unknown URL, with no redirect and no exception. — 5064767

#### Manual

- [x] 2.10 At 360px width a two-family user picks a family, sees its name in the header, switches, and sees only the other family's entries.
- [x] 2.11 With two tabs on different families, saving a capture in the stale tab shows the Polish 409 page and creates no entry.
- [x] 2.12 The operator adds a second membership in Django admin for an existing user, and that user sees the "Zmień rodzinę" link on the next request.
- [x] 2.13 A keyboard-only pass on the chooser and the header switcher follows the `context/foundation/accessibility.md` checklist.

### Phase 3: Cross-Family Isolation Matrix, Automation and Worker Regression

#### Automated

- [x] 3.1 The cross-family matrix passes for every listed web route: `uv run python manage.py test entries.tests.test_multi_family_access family_access.tests.test_multi_family_access`. — 98314b6
- [x] 3.2 Automation and worker regression tests pass: `uv run python manage.py test entries.tests.test_entries_api entries.tests.test_notification_intake entries.tests.test_conversion_worker`. — 98314b6
- [x] 3.3 Full tests pass: `uv run python manage.py test`. — 98314b6
- [x] 3.4 Django checks pass: `uv run python manage.py check`. — 98314b6
- [x] 3.5 Migration drift check passes: `uv run python manage.py makemigrations --check --dry-run`. — 98314b6

#### Manual

- [x] 3.6 With the seeded two-family user, a reviewer completes parent capture in one family and the child view in the other, and confirms no data from the other family appears anywhere.
- [x] 3.7 A reviewer confirms that a single-family user's flows (seeded parent and child) look and behave exactly as before.
