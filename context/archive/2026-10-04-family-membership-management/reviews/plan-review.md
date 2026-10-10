<!-- PLAN-REVIEW-REPORT -->
# Plan Review: Family Membership Management Implementation Plan

- **Plan**: context/changes/family-membership-management/plan.md
- **Mode**: Deep
- **Date**: 2026-10-04
- **Verdict**: SOUND
- **Triage**: applied 2026-10-04
- **Findings**: 0 critical, 2 warnings, 2 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| End-State Alignment | PASS |
| Lean Execution | PASS |
| Architectural Fitness | PASS |
| Blind Spots | WARNING |
| Plan Completeness | PASS |

## Grounding
Grounding: 8/8 paths ✓ (`family_access/models.py:46`, `access.py:6/24`, `admin.py:15/40`, `automation.py:52`, `entries/models.py:34` RESTRICT, `entries/forms.py:84`, `entries/eduvulcan/children.py:13`, `account_status.html:22`), 5/5 symbols ✓ (`get_active_membership`, `is_parent`, `scope_queryset_to_family`, `kept_assignee_id`, `AutomationToken.revoked_at`), brief↔plan ✓, Progress↔Phase ✓ (1.1–1.7, 2.1–2.12). `family_notes/a11y_audit.py` does not exist yet; S-17 creates it (expected prerequisite). No schema change confirmed: rename, deactivate and reactivate use existing columns. Cross-plan: S-15 reuses `_lock_family` / `_ensure_parent_remains`; S-16 replaces Decision 10 and its tests (acknowledged in S-16 Phase 2 §2).

## Findings

### F1 — Actor and target are validated before the Family lock (stale authority)

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Blind Spots
- **Location**: Critical Implementation Details; Phase 1 §1–§2 (`deactivate_member`, `reactivate_member`, `_lock_family`, `_ensure_parent_remains`)
- **Detail**: The contract says each function "raises `PermissionDenied` unless `is_parent(actor)`" and resolves the target, then the guarded mutation "first locks the actor's `Family` row ... then counts active parents and changes the row". `is_parent(actor)` (`family_access/access.py:24`) reads attributes of the in-memory `actor` object that the view resolved at the start of the request. Nothing requires re-reading the actor or the target after the lock. Because the guard counts parents from the database after the lock, the last-parent invariant itself holds under READ COMMITTED on PostgreSQL. Actor authority does not hold. Example with parents A, B and C: A deactivates C while C deactivates B. C's request passed `is_parent` before the lock, waits, and then deactivates B after C has already lost access. A is still a parent, so the guard passes. The same stale read applies to the target's `is_active`/`role` (for example, reactivating a member another parent just changed). S-15 (`change_member_role`) and S-16 (the middleware-resolved membership passed as `actor`) inherit this helper, so the fix belongs here. The plan also concedes that SQLite cannot exercise the lock, so nothing proves it is taken.
- **Fix**: Make the helper contract "lock, then re-read". `_lock_family(family_id)` locks the `Family`, and the function then re-fetches the actor and the target from the database (`FamilyMember.objects.select_for_update().get(pk=..., family_id=...)`). It re-checks `is_parent(fresh_actor)` and the target's current state before `_ensure_parent_remains`, and returns or raises from those fresh rows. Add a test that mutates the actor's row between resolution and the call (deactivate or demote it directly in the DB) and asserts `PermissionDenied` with no change. Optionally add a PostgreSQL-only concurrency test (`skipUnless(connection.vendor == 'postgresql')`, two threads) for the cross-deactivation case.
  - Strength: One helper fixes S-14, S-15 and S-16 together; the test is deterministic on SQLite.
  - Tradeoff: Adds one or two extra queries per mutation under the lock (negligible at family scale).
  - Confidence: HIGH — the existing entry write path already re-reads under lock (`entries/services.py` `_locked_family_entry`).
  - Blind spot: Django admin edits bypass the lock entirely (operator-only; acceptable, but worth one line in the plan).
- **Owner input**: no
- **Decision**: FIXED (Fix A)

### F2 — Rename can create ambiguous child names that misroute school notifications

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Blind Spots
- **Location**: Phase 1 §1 `rename_member`; Phase 2 §2 child edit-page note
- **Detail**: The plan notes that EduVulcan matches children by `display_name`. It only adds a hint on the edit page. `match_child` (`entries/eduvulcan/children.py:36-48`) silently picks the newest membership when two active children normalize to the same name, and S-02 short-name resolution keys on display names too. If a parent renames a child to a name equal (after `normalize_child_name`) to another active member's name, school notifications and classifier assignments can land on the wrong child. That child then reads an entry meant for a sibling, which is an in-family privacy leak. Today only the operator can create that state. S-14 gives every parent this ability.
- **Fix**: In `rename_member`, reject a name whose `normalize_child_name(...)` equals that of another active member of the same family, with a Polish `ValidationError`. Add the case to 1.2 and to the edit-form error state.
- **Owner input**: no
- **Decision**: FIXED (Fix A)

### F3 — Last-parent guard counts parents whose User account is disabled

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Blind Spots
- **Location**: Phase 1 §2 `_ensure_parent_remains`
- **Detail**: `_ensure_parent_remains` counts active parent memberships only. A parent whose `User.is_active` is False cannot sign in, and their tokens are refused (`family_access/automation.py:54`). The guard still counts them as a remaining manager, so a family can end up with no usable parent. The in-flight `testing-production-security-schema-safety` Phase 2 makes inactive Users fail closed in `get_active_membership`, so the codebase is moving toward treating such parents as absent.
- **Fix**: Count only `role=PARENT, is_active=True, user__is_active=True` in `_ensure_parent_remains`, and add one guard test.
- **Owner input**: no
- **Decision**: FIXED (Fix A)

### F4 — Any parent can reactivate a deactivated parent, restoring full manager rights

- **Severity**: 💡 OBSERVATION
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Blind Spots
- **Location**: Decision 6; Phase 1 §1 `reactivate_member`
- **Detail**: `reactivate_member` brings a member back with their stored role. For a parent, that restores management, entry CRUD and token eligibility. This includes a parent the operator deactivated in admin for a reason the other parent may not share (for example, a separated co-parent). S-15 Decision 7 refuses role edits on inactive members to avoid "silently reviving a member with new rights". Reactivation revives *old* parent rights with no extra step. Tokens stay revoked, which limits the API side. This is a security/product trade-off, not a bug.
- **Fix A ⭐ Recommended**: Keep reactivation for all roles (consistent with "every active parent is a manager"). Add a Polish confirmation on parent rows ("Ta osoba odzyska uprawnienia rodzica") and keep the id-only log line.
  - Strength: No new rule, and matches the owner decision that all parents are equal.
  - Tradeoff: An operator-level deactivation of a parent can be undone by any other parent.
  - Confidence: MED — depends on how the operator uses deactivation.
  - Blind spot: Real family situations behind operator deactivations are unknown.
- **Fix B**: In-app reactivation allowed only for child members; reactivating a parent stays operator-only in Django admin.
  - Strength: The operator keeps the final say over who holds parent rights.
  - Tradeoff: More operator work, plus one more rule in the UI and tests.
  - Confidence: HIGH — simple service check.
  - Blind spot: None significant.
- **Owner input**: yes
- **Decision**: FIXED (owner: Fix A — any active parent may reactivate a parent after the Polish confirmation "Ta osoba odzyska uprawnienia rodzica", id-only log line)
