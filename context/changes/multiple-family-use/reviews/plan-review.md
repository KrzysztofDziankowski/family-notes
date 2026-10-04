<!-- PLAN-REVIEW-REPORT -->
# Plan Review: Multiple Family Use Implementation Plan

- **Plan**: context/changes/multiple-family-use/plan.md
- **Mode**: Deep
- **Date**: 2026-10-04
- **Verdict**: SOUND
- **Triage**: applied 2026-10-04
- **Findings**: 0 critical, 4 warnings, 1 observation

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| End-State Alignment | WARNING |
| Lean Execution | PASS |
| Architectural Fitness | PASS |
| Blind Spots | WARNING |
| Plan Completeness | PASS |

## Grounding
Grounding: 9/9 paths ✓ (`family_access/models.py:46`, `access.py:6`, `automation.py:72`, `admin.py:15`, `entries/services.py:73/113/257`, `entries/classification/service.py:102/152`, `entries/api_views.py:100/249`, `entries/eduvulcan/conversion.py:283`, `family_notes/views.py:19`, `scripts/dev/seed_test_family.py:36`), 6/6 symbols ✓, brief↔plan ✓, Progress↔Phase ✓ (1.1–1.5, 2.1–2.13, 3.1–3.7).
Current helper callers (all listed by the plan): `entries/services.py:114,264`, `entries/views.py:803`, `entries/classification/service.py:102,152`, `family_access/views.py:12`, `family_notes/views.py:19`, plus `family_access/tests/test_access.py`.
Token path verified: family comes only from `request.automation_membership` (`entries/api_views.py:100,249`), and owner `is_parent` and `user.is_active` are re-checked per request (`family_access/automation.py:52-54`). Worker path verified: family comes from `InboundNotification.family` (`conversion.py:283`), and the child snapshot is family-scoped (`children.py:13`). No user or session lookup exists on either path. Plan claims ✓.
Migration numbering: `family_access/migrations` ends at `0003_authcacheentry`. S-14 and S-15 add no migrations. S-01 adds `entries/migrations/0007_entry_school_subject.py` (a different app, no conflict). No other planned change adds a `family_access` migration, so `0004` is free.

## Findings

### F1 — Phase 1 caller inventory and grep miss services added by S-03/S-04 and direct lookups

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: End-State Alignment
- **Location**: Phase 1 §2 (named service list), Success criterion 1.2 (grep)
- **Detail**: Phase 1 names the services that switch from `user` to `membership` from today's code. By delivery (after S-01..S-09 and S-17), S-03 adds `classify_entries_for_parent(user, ...)` and `save_confirmed_entries(user, items)` (`context/changes/multi-entry-text-capture/plan.md:111,185`). S-04 adds `correct_proposal_for_parent(user, ...)` (`context/changes/free-text-proposal-correction/plan.md:112`). None of these are listed. Deleting the helper makes any *helper* caller fail loudly, which is good. The grep criterion only matches the two helper names, though. It does not catch a family derived from `request.user.family_memberships...` or `FamilyMember.objects.filter(user=...)`, or a service still taking `user` and resolving through another path. 1.3 ("existing suites pass unchanged") also conflicts with `family_access/tests/test_access.py:147-179`, which imports the deleted helpers and must be rewritten against `resolve_family_context`.
- **Fix**: Replace the named list with a rule: "no product function in `entries/` or `family_access/` takes a `User` to derive a family; every parent/child service takes the context membership". List the known S-03/S-04 additions as examples. Widen 1.2 to `grep -rnE "get_active_membership|require_active_membership|family_memberships|FamilyMember\.objects\.filter\(user" --include=*.py entries family_access family_notes` (expected: no non-test hits outside `context.py`). Add a review check that no service call passes `request.user`. Add "rewrite `test_access.py` helper tests as context tests" to Phase 1.
  - Strength: Rule-based and future-proof against slices merged between planning and implementation.
  - Tradeoff: The broader grep may need a small allow-list (`context.py` itself, the admin).
  - Confidence: HIGH — the S-03/S-04 signatures are explicit in their plans.
  - Blind spot: S-07/S-08 plans were checked only for new `user`-taking services (none found).
- **Owner input**: no
- **Decision**: FIXED (Fix A)

### F2 — Stale-tab guard is an enumerated per-form list that is already incomplete

- **Severity**: ⚠️ WARNING
- **Impact**: 🔬 HIGH — architectural stakes; think carefully before deciding
- **Dimension**: Blind Spots
- **Location**: Phase 2 §4 Stale-tab guard; Success criterion 2.4
- **Detail**: The guard covers "capture, answer, confirm, create, edit, delete and the S-14/S-15 ... forms". By delivery, the S-03 batch confirm (`BatchReviewForm` / `save_confirmed_entries`) and the S-04 correction POST also exist and are not listed. Any POST route added later is unguarded by default. Each view must remember to call `ensure_form_family`, and 2.4 says "each parent mutation" without a mechanism that discovers new ones. A missed route is exactly the roadmap risk ("every view and mutation must use the authorized family context"): a stale tab writes into the session's current family. Second-order effect: "absence → 409" means every form open in a browser during the deploy fails once for all users, including single-family users.
- **Fix A ⭐ Recommended**: Enforce centrally. `FamilyContextMiddleware.process_view` checks `family_context` on every unsafe-method request from a session-authenticated user to the `entries` and `family_access` namespaces (exempting the chooser, allauth, admin and `/api/automation/`). A template tag or partial injects the hidden field into every form. Add a test that walks the URL resolver for those namespaces and asserts that every POST route returns 409 on a mismatched `family_context` and writes nothing.
  - Strength: New POST routes are guarded by default, and the resolver-walk test fails when a form forgets the field.
  - Tradeoff: Middleware gets namespace-aware logic, and form templates must all include the partial.
  - Confidence: HIGH — the same pattern as `CsrfViewMiddleware` plus `{% csrf_token %}`.
  - Blind spot: The deploy-time 409 burst still happens. Accept it, or treat a missing field as a match for single-family users during one release.
- **Fix B**: Keep per-view `ensure_form_family`, update the list to include the S-03/S-04 forms, and add the resolver-walk test only.
  - Strength: Smaller change; matches the plan's current shape.
  - Tradeoff: Safety depends on every future view calling the helper; the test is the only net.
  - Confidence: MED — the test catches omissions only if it enumerates routes, not a fixed list.
  - Blind spot: Non-namespaced POST routes added later.
- **Owner input**: no
- **Decision**: FIXED (owner: Fix A — stale-tab check enforced centrally in `FamilyContextMiddleware`)

### F3 — Header context processor can raise FamilyContextRequired (chooser loop, logout, error pages)

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Blind Spots
- **Location**: Phase 1 §1 (middleware), Phase 2 §3 (context processor, "chooser is exempt")
- **Detail**: The middleware "converts `FamilyContextRequired` into a redirect", which is an exception-based design. The header context processor supplies `current_family` and `family_count` "from the resolved context" on every `base.html` render. If it calls `resolve_family_context`, a multi-family user with no selection hits the exception while rendering the chooser itself (redirect loop), the allauth logout confirmation (cannot log out), the login page, and the 403/404/500 handlers. An exception escaping the 500 handler is particularly bad. "The chooser itself is exempt" does not cover template-time resolution.
- **Fix**: Specify a non-raising `peek_family_context(request) -> (membership | None, active_count)` for the context processor and error pages. Only product views call the raising resolver. Add tests: a multi-family user with no selection can GET the chooser and the logout page, and gets a 404 page without a redirect.
- **Owner input**: no
- **Decision**: FIXED (Fix A)

### F4 — Deleting get_active_membership drops the in-flight "reject inactive User" rule

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Blind Spots
- **Location**: Phase 1 §1 `active_memberships` / `resolve_family_context` contract; criterion 1.1
- **Detail**: `testing-production-security-schema-safety` (status `implementing`, Phase 2 pending) changes `get_active_membership()` so it "rejects inactive users independently of authentication middleware" (its plan, lines 127-132). S-16 deletes that helper. Its replacement contract checks only "active memberships in active families", and the 1.1 test list has no inactive-`User` case. The fail-closed rule would silently disappear. The same change also adds admin validation that blocks moving a membership to another family. S-16 Phase 2 §2 edits `FamilyMemberAdmin` and must keep that rule.
- **Fix**: Add `user.is_active` (and `user__is_active=True` in `active_memberships`) to the context contract. Add an inactive-User case to 1.1. Reference the security change's admin validation in Phase 2 §2 so the admin edit keeps it.
- **Owner input**: no
- **Decision**: FIXED (Fix A)

### F5 — Migration test and reverse path need concrete mechanics

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 2 §1; Success criterion 2.1; Migration Notes
- **Detail**: 2.1 requires proof that "the migration applies to a database with existing memberships". Django's test DB starts migrated, so this needs a migrate-back/forward test. The repository already has one (`entries/tests/test_conversion_models.py:255-306`, `MigrationExecutor`). The reverse migration will fail with a raw `IntegrityError` mid-rollback if any user has two active memberships. The notes document this but give no check. The auto-generated filename will not be `0004_membership_per_family` unless `--name` is used. Numbering itself is fine (see Grounding).
- **Fix**: Name the `MigrationExecutor` pattern in 2.1 (migrate to `0003`, insert rows, migrate to `0004`, assert both constraint behaviors). Add a `RunPython` no-op forward and a reverse that raises a clear error listing the offending user ids (no names) when duplicates exist. Generate with `makemigrations family_access --name membership_per_family`.
- **Owner input**: no
- **Decision**: FIXED (Fix A)
