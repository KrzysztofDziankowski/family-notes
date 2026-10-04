<!-- PLAN-REVIEW-REPORT -->
# Plan Review: Family Role Management Implementation Plan

- **Plan**: context/changes/family-role-management/plan.md
- **Mode**: Deep
- **Date**: 2026-10-04
- **Verdict**: SOUND
- **Triage**: applied 2026-10-04
- **Findings**: 0 critical, 1 warning, 2 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| End-State Alignment | PASS |
| Lean Execution | PASS |
| Architectural Fitness | PASS |
| Blind Spots | WARNING |
| Plan Completeness | PASS |

## Grounding
Grounding: 7/7 paths ✓ (`family_access/models.py:24/114`, `access.py:24/39`, `admin.py:40`, `automation.py:52`, `family_notes/views.py:14`, `entries/eduvulcan/children.py:13`), 4/4 symbols ✓ (`FamilyMember.Role`, `is_parent`, `can_read_assigned_child`, `AutomationToken.clean`), brief↔plan ✓, Progress↔Phase ✓ (1.1–1.6, 2.1–2.11). Escalation review: the role value is validated against `FamilyMember.Role`, children are refused in the service, `User.is_staff`/`is_superuser` are never touched, tokens are revoked on demotion and not restored on promotion, and roles are read per request. No escalation path was found beyond F1's race. No schema change; no migration conflict with S-14/S-16.

## Findings

### F1 — Role-change checks run before the lock (stale actor and target)

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Blind Spots
- **Location**: Phase 1 §1 `change_member_role` contract (bullet order)
- **Detail**: The contract checks `is_parent(actor)`, resolves the target and "refuses an inactive target" *before* "Inside `transaction.atomic()` it locks the family". A privilege grant can therefore be made with stale authority. Parent C, while being demoted or deactivated by parent A, can still promote a child to parent, because C's check passed before C waited on the lock. A target deactivated concurrently can also have its role changed, which breaks Decision 7 ("only active members' roles change"). The last-parent invariant holds because `_ensure_parent_remains` counts from the DB after the lock. The escalation risk is the actor's stale authority. The root cause is in the shared S-14 helper (S-14 review F1).
- **Fix**: Reorder the contract: lock with `_lock_family`, then re-read the actor and target rows, then run every check (`is_parent(fresh_actor)`, target active, role valid/unchanged, `confirm_self`, `_ensure_parent_remains`). Add to 1.2 a test where the actor is demoted or deactivated in the DB after resolution and the promotion is refused with no change.
- **Owner input**: no
- **Decision**: FIXED (Fix A)

### F2 — A single parent can strip every co-parent with no notice and only operator recovery

- **Severity**: 💡 OBSERVATION
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Blind Spots
- **Location**: Decisions 3, 5 and 12; "What We're NOT Doing" (no notification)
- **Detail**: Under "all parents are equal managers", parent A can demote parent B (S-15) or deactivate B (S-14), one after another, until A is the only parent. The guard only keeps *one* parent. B finds out on their next request, with no notice, and only the operator can reverse it. The logs record ids only, and the plan contains no operator runbook. This is a real takeover path in separated or conflicted families. It is within the owner's decision, so the question is only whether to add a safeguard.
- **Fix A ⭐ Recommended**: Keep the behavior as decided. Add an operator recovery note to the plan (find the `membership_event=role_changed` log lines by family id, then restore the role in admin). On the affected user's next request, a demoted parent sees a Polish notice explaining that their role was changed by another parent.
  - Strength: Keeps owner-confirmed equality; the notice is a small template/message change with no new storage beyond the role itself.
  - Tradeoff: Still no prevention, only transparency and recovery.
  - Confidence: MED — notice wording and trigger need a small design choice.
  - Blind spot: How often families have conflicting parents is unknown.
- **Fix B**: Only self-demotion is in-app; demoting *another* parent stays operator-only (promotion stays in-app).
  - Strength: Removes the unilateral takeover path entirely.
  - Tradeoff: Contradicts the 2026-10-04 "both directions" decision and adds operator work.
  - Confidence: HIGH — one service check.
  - Blind spot: S-14 deactivation of another parent remains a parallel path unless restricted too.
- **Owner input**: yes
- **Decision**: FIXED (owner: Fix A — behaviour kept; Polish next-request notice for a demoted or deactivated parent; operator recovery runbook added)

### F3 — Demoted parent enters the EduVulcan child snapshot (untested)

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Blind Spots
- **Location**: Phase 2 §4 Effective-access regression
- **Detail**: The regression covers "a promoted child is no longer in the EduVulcan child snapshot" but not the reverse. `snapshot_active_children` (`entries/eduvulcan/children.py:13-28`) will include a demoted parent, so a school notification that mentions that parent's display name (for example, a signature) can auto-assign to them. The plan's risks list only the promoted-child direction.
- **Fix**: Add "a demoted parent appears in the child snapshot and is matchable by name" to the 2.3 regression and to the Open Risks list.
- **Owner input**: no
- **Decision**: FIXED (Fix A)
