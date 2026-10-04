# Production Security and Schema Safety — Implementation Plan

## Overview

Complete rollout Phase 1 of `context/foundation/test-plan.md`: protect administrative access, prove family authorization, and rehearse schema upgrades and recovery on PostgreSQL.

Deliver four independently verifiable phases. Keep production changes and acceptance checks operator-controlled.

## Current State Analysis

The custom admin admits active superusers, but its password login has no configured abuse defense. Production uses two Gunicorn workers and Django’s default process-local cache, which cannot share login-limit state.

Family-scoped services and token authentication already provide substantial protection. Remaining gaps include inactive-user service access, unvalidated token issuance, and cross-family relationships submitted through admin.

Migration tests currently default to SQLite. The deployment helper applies migrations while old code remains running. Historical migrations `0003`–`0005` temporarily expose columns incompatible with old notification inserts.

Docker is available locally. PostgreSQL rehearsals use container-owned server/client binaries.

## Desired End State

- Administrative password login uses allauth’s shared rate limits while retaining superuser-only admission.
- An operator can reset only the selected operator/IP login limits through a restricted SSH command.
- Supported session, automation, and admin paths enforce their authorization and relational contracts.
- Disposable PostgreSQL rehearsals prove forward migration, constraints, historical-write compatibility, interrupted migration recovery, and actual dump/restore.
- Releases stop requests and conversion workers before backup and migration. Failure preserves evidence and never automatically reverses schema or restores data.

### Key Discoveries

- `family_notes/admin.py:4` defines the existing admission boundary.
- `family_access/access.py:6` does not independently reject inactive users.
- `family_access/models.py:91` saves issued tokens without invoking validation.
- `entries/admin.py:9` exposes mutable entries without same-family relational validation.
- `scripts/deployment/family-notes-deploy:133` checks only that the backup is nonempty.
- The roadmap’s MS-01 decision permits parent-owned tokens to read their family’s entries; it supersedes the older PRD write-only wording.

## What We're NOT Doing

- MFA enrollment, network-restricted admin access, or new authentication methods.
- Cross-table database triggers, global `save()` validation, or guarantees for arbitrary raw ORM writes.
- EduVulcan durability and classification correctness testing assigned to the two separate Phase 2 changes.
- E2E or visual testing.
- Automated production deployment, database restoration, migration reversal, or rollback.
- Scheduled backups, external monitoring infrastructure, or general deployment modernization.
- Editing archived artifacts.

## Implementation Approach

Use allauth’s protected admin login and a dedicated database cache table in the existing application database. A focused cache backend provides atomic insert-on-conflict locking, bounded PostgreSQL statements, JSON state, and expiry-only cleanup. This supersedes the original Redis decision at the user’s request.

Extend existing feature tests to express the complete access matrix. Add focused application/model/admin validation where supported paths currently bypass invariants.

Use disposable Docker services and synthetic fixtures for PostgreSQL integration evidence. Implement the maintenance release as one locked helper operation so backup, migration, activation, and readiness cannot overlap another deployment.

## Critical Implementation Details

**Login protection:** allauth’s admin wrapper redirects anonymous requests to account login; it does not throttle Django’s original password form in place. Preserve the custom admin admission predicate and prove that anonymous admin POSTs cannot use the old form.

**Recovery targeting:** allauth’s login-limit keys depend on the configured login identifier, site domain, and client-IP bucket. Isolate that version-sensitive integration behind one helper; never reset by guessing database cache keys or flushing the cache.

**Migration ordering:** stop Gunicorn before backup, which also stops its conversion threads. A migration failure may leave earlier migrations committed; automatically restarting old code would therefore be unsafe.

## Phase 1: Admin Protection and Recovery

### Overview

Protect password login across workers and provide the agreed targeted operator recovery path.

### Changes Required

#### 1. Protected login and shared state

**Files:** `family_notes/admin.py`, `family_notes/settings.py`, `pyproject.toml`, `uv.lock`, environment example, new `family_notes/auth_security.py`, `family_notes/auth_cache.py`, and a `family_access` authentication-state migration.

**Intent:** Reuse installed allauth protection and provide consistent limiter state across Gunicorn workers.

**Contract:**

- Wrap the custom site’s login with `secure_admin_login`; retain `SuperuserAdminSite.has_permission`.
- Explicitly retain `login: 30/m/ip` and `login_failed: 10/m/ip,5/300s/key`; preserve other allauth limits.
- Production stores shared login histories and locks in the existing default database, in `family_access_authcacheentry`. No Redis endpoint or service is required. Development can opt in with `DJANGO_AUTH_DB_CACHE=True`.
- Remove the Redis dependency. Use PostgreSQL statement and lock timeouts of one second for cache operations; connection establishment uses the existing database configuration.
- Use a dedicated application key prefix and indexed expiry column. Store JSON histories and booleans, clean only expired rows, and never evict active histories. Prove atomic add under concurrent PostgreSQL processes.
- Cache failures deny new authentication with a fixed, sanitized unavailable response; never fall back to process-local state. Existing authenticated access remains governed by its usual permission checks.
- Trust nginx’s overwritten `X-Real-IP` header. Before production acceptance, verify that nginx resolves the actual client through the Mikrus proxy boundary. Do not trust arbitrary client XFF values.
- Application copy is Polish; operator/admin output is English.

#### 2. Targeted recovery and integration harness

**Files:** new management command `reset_admin_login_limits`, `family_notes/auth_security.py`, `scripts/deployment/family-notes-deploy`, new admin-security tests, new `scripts/testing/security-rehearsal.sh`.

**Intent:** Restore operator access without clearing unrelated protection.

**Contract:**

- Command interface: `reset_admin_login_limits --user-id USER_ID --client-ip CLIENT_IP`.
- Require an existing active superuser, a positive integer ID, and a valid IPv4/IPv6 address.
- Derive the account key from the configured login identity and production site. Clear the selected IP’s `login` and `login_failed` buckets and the operator’s `login_failed` account bucket.
- Document that an IP bucket covers every account sharing that IP; IPv6 follows allauth’s configured prefix.
- Preserve other accounts’ account buckets and other IP buckets. Verify targeted histories were cleared; lock contention or cache failure returns nonzero.
- Restricted helper action: `reset-admin-login USER_ID CLIENT_IP`. Resolve only the current release and invoke only this command as `familynotes`; reject extra arguments and arbitrary command/path options.
- Record fixed outcome codes and user ID without passwords, account identifiers, secrets, cache URLs, or family text.
- Harness mode `admin` starts disposable PostgreSQL and runs shared-state, concurrent-lock, restart, outage, and targeted-reset tests. Missing Docker runtime is a failure, not a skip.

### Success Criteria

#### Automated Verification

- Admin security tests and `sh scripts/testing/security-rehearsal.sh admin` prove admission, login limits, shared state, cache failure, and targeted reset isolation.
- Django checks, migration drift check, and `uv run --locked pip-audit` pass.

#### Manual Verification

- Local operator verification confirms protected admin login and targeted recovery; the runbook records database cache setup and the production client-IP verification procedure.

**Implementation Note:** Obtain manual confirmation for this phase before continuing.

## Phase 2: Family Authorization and Integrity

### Overview

Complete policy evidence and close the agreed supported-path validation gaps.

### Changes Required

#### 1. Targeted validation

**Files:** `family_access/access.py`, `family_access/models.py`, `family_access/admin.py`, `entries/models.py`, `entries/admin.py`.

**Intent:** Make direct service access fail closed and prevent invalid records through issuance and admin forms.

**Contract:**

- `get_active_membership()` rejects inactive users independently of authentication middleware.
- `AutomationToken.issue()` validates before persistence. New issuance requires an active parent membership, active family, and active user. Existing tokens become unusable through the existing request-time authority checks.
- Entry validation rejects non-null assignee or creator relationships belonging to another family.
- Admin forms prohibit newly assigning inactive members while permitting retention of an existing inactive assignee.
- Admin membership edits cannot move a member to another family while existing entry assignments or creator references would become inconsistent.
- Superusers retain global operator visibility. Application validation does not introduce database triggers or unconditional `full_clean()` on every save.
- Check existing relational data before rollout. Report inconsistent record IDs without content; do not silently repair or reassign data.

#### 2. Observable authorization matrix

**Files:** existing tests under `entries/tests/` and `family_access/tests/`, new focused admin/model validation tests, a change-local authorization matrix.

**Intent:** Demonstrate policy through responses, visible data, and mutation non-effects.

**Contract:**

- Cover parent capture, answer, confirmation, CRUD, child list/detail, token notification POST, token entry GET, and forbidden token mutations/UI access.
- Include parent, assigned child, other child, foreign-family member, unauthenticated user, unconfigured user, and inactive authority as applicable.
- Test session/token channel confusion and immediate revocation, expiry, demotion, and member/family/user deactivation.
- Denials assert unchanged rows and absence of foreign content, identifiers, totals, and pagination metadata.
- Preserve indistinguishable missing/foreign detail responses.
- Prove conversion output ownership without expanding into worker durability testing.
- Reuse valid existing feature tests; add missing matrix cells rather than duplicating every assertion.

### Success Criteria

#### Automated Verification

- Focused access, admin, token, and entry suites prove the documented matrix and validation non-effects.
- The full Django suite, system checks, and migration drift check pass.

#### Manual Verification

- Review confirms that every supported operation maps to evidence and that MS-01 token reads remain explicitly permitted.

**Implementation Note:** Obtain manual confirmation for this phase before continuing.

## Phase 3: PostgreSQL Migration and Restore Rehearsals

### Overview

Provide reproducible production-engine evidence without touching production data.

### Changes Required

#### 1. Disposable database harness

**Files:** new `scripts/testing/postgres-rehearsal.sh`, shared testing harness utilities, new `entries/tests/test_postgres_schema_safety.py`.

**Intent:** Run real PostgreSQL transactions, migrations, constraints, and backup tools in isolation.

**Contract:**

- Use a PostgreSQL 17 baseline image; resolve and record its immutable digest before running.
- Certification requires the rehearsal major to match the production server major. A mismatch requires rerunning with the matching major; it never permits tests against production.
- Create unique containers, application-like roles, source databases, and restore databases. Use loopback-only ports and generated disposable credentials.
- Accept only harness-created targets, not arbitrary production DSNs.
- Use container-owned `pg_dump` and `pg_restore`; clean up on success, failure, and interruption.
- Fail explicitly when Docker or readiness is unavailable.
- Run schema-changing scenarios serially with historical migration-state models; restore leaf state after each scenario.

#### 2. Forward, failure, and restore scenarios

**Files:** `entries/tests/test_postgres_schema_safety.py`, existing conversion-model tests, rehearsal script.

**Intent:** Prove preservation and recovery at the actual database boundary.

**Contract:**

- Rehearse empty database → leaves, `entries 0002` → leaves, and `entries 0004` → leaves, including dependent app migrations.
- Preserve synthetic families, memberships, tokens, authentication histories, entries, notifications, heartbeats, output links, and deletion tombstones as applicable.
- Verify named constraints/indexes, defaults, foreign keys, retained values, and sequence continuity.
- Prove historical notification and heartbeat writes against the final schema. Record that intermediate historical schemas require the agreed maintenance window.
- Inject an atomic migration failure after a prior step commits. Prove the failed step leaves no partial changes, earlier work remains recorded, and an explicit forward retry preserves data and reaches leaves.
- Generate a real `pg_dump -Fc` using the application-like role. Restore into a separate empty database using fail-on-error, no-owner, and no-privileges behavior; verify restored objects are owned by the intended role.
- Compare integrity invariants before and after restore, then run migrations/checks. A nonempty archive alone is insufficient.
- Use only synthetic fixtures. Do not copy production dumps into the repository or rehearsal artifacts.

### Success Criteria

#### Automated Verification

- `sh scripts/testing/postgres-rehearsal.sh` passes all upgrade, constraint, interrupted-migration, historical-write, and dump/restore scenarios without required skips.
- Rehearsal output records server/client versions, image digest, source revision, scenario outcomes, and cleanup without exposing credentials or fixture text.

#### Manual Verification

- Review confirms the rehearsal engine matches the recorded production major and that the evidence supports only the scenarios actually executed.

**Implementation Note:** Obtain manual confirmation for this phase before continuing.

## Phase 4: Maintenance Deployment and Acceptance Evidence

### Overview

Make schema upgrades safe under the agreed outage policy and connect Phase 1 evidence to release acceptance.

### Changes Required

#### 1. One serialized maintenance operation

**Files:** `scripts/deployment/family-notes-deploy`, `scripts/deployment/release.sh`, `scripts/deployment/release-gate.sh`, deployment shell tests.

**Intent:** Prevent concurrent deployment commands and preserve a clear recovery state.

**Contract:**

- Add fixed helper action `deploy RELEASE_ID`, holding a root-owned exclusive lock for the complete operation.
- Order: validate/check candidate → check database connectivity → stop Gunicorn and confirm inactivity → dump database → migrate → collect static → switch release pointer → start service → run existing bounded readiness gate.
- Write a root-owned maintenance-state record before stopping. Retain release IDs, completed stage, and backup path; include no secrets.
- Remove the record only after readiness succeeds. Failed attempts retain the candidate release and any completed dump.
- Before pointer switch, stop/backup/migration/static failures leave the old pointer unchanged. Once stopped, the service remains stopped pending explicit recovery.
- After pointer switch, startup/readiness failure retains the candidate pointer and schema. No automatic restart of old code, rollback, migration reversal, or restore.
- Route the release script through this single operation. Print completion only after its successful readiness result.
- Existing standalone backup remains non-disruptive. Prevent standalone activation from bypassing the maintenance operation. Serialize rollback/reset against deployment; require the documented compatibility assessment before code rollback.
- Bump the matched helper/library/script protocol to `2`; reject old helpers before release mutation. Update staging and installation verification together.
- Explicitly propagate shell callback failures instead of relying on `set -e` within conditional function calls.

#### 2. Runbook and test-plan evidence

**Files:** deployment plan/runbook, `context/foundation/test-plan.md`, change-local acceptance record.

**Intent:** Make operator acceptance and Phase 1 completion auditable.

**Contract:**

- Document authentication-state migration, cache outage behavior, trusted client-IP verification, targeted reset, maintenance downtime, and forward-fix recovery.
- Record production PostgreSQL major and migration inventory through read-only checks before certification.
- Require operator-approved installation of protocol-2 artifacts and release-specific smoke checks.
- Smoke checks cover HTTPS, normal/staff denial, superuser admission, limits across workers, targeted reset isolation, and sanitized diagnostics.
- Update rollout Phase 1 status as evidence lands; fill cookbook sections for authorization, database integration, and migration rehearsal.
- Leave Phases 2–3 status and unrelated operations follow-ups untouched.
- Keep production restore and destructive rehearsals outside this change. Local restore proof does not close the separate production-backup restore-drill follow-up.

### Success Criteria

#### Automated Verification

- Deployment shell tests prove ordering, locking, protocol rejection, every failure boundary, retained recovery state, and absence of automatic rollback or secret leakage.
- The full Django suite, system checks, migration drift check, database authentication integration, and PostgreSQL rehearsal pass; dependency audit passes after dependency changes.

#### Manual Verification

- Operator-approved deployment acceptance records protocol-2 installation, maintenance recovery evidence, production HTTPS/admin smoke, client-IP verification, and matching PostgreSQL version.

**Implementation Note:** Complete authorized local work before requesting the concrete production installation/release approval. Do not mark manual acceptance complete without evidence.

## Testing Strategy

### Unit Tests

Validate inactive-user rejection, issuance eligibility, entry relational validation, reset arguments, account-key derivation, and safe error translation.

### Integration Tests

Exercise actual request policy and non-effects, database authentication state across processes, PostgreSQL historical schemas and committed failures, and real archive restoration. Mock transport/process boundaries only where required; do not mock authorization predicates or substitute mocked backup success for restore evidence.

### Manual Testing Steps

1. Review the complete authorization matrix and local operator login/reset behavior.
2. Review synthetic PostgreSQL rehearsal evidence and production-version match.
3. Approve and install the matched deployment artifacts through the existing privileged operator path.
4. Complete the narrowly scoped release smoke and record outcomes.

## Performance Considerations

Login limiting adds bounded operations against the existing database; it does not add cache work to family-data queries. Expiry-only cleanup retains all active protection histories. Database unavailability denies new authentication. Migration/restore scenarios run serially and separately from the fast default SQLite suite.

## Migration Notes

Application/admin validation requires no product schema change. Shared login state adds one dedicated cache-table migration. Existing invalid relationships are reported for explicit correction.

The authentication-state migration and protocol-2 helper must be installed before activating protected login and the revised release procedure. Applied historical migrations remain unchanged. The maintenance window covers intermediate incompatibility.

## References

- Change research: `context/changes/testing-production-security-schema-safety/research.md`
- Strategy: `context/foundation/test-plan.md`
- Authority extension: `context/foundation/roadmap.md`, MS-01
- Deployment contract: `context/changes/deployment/deployment-plan.md` and `mikrus-runbook.md`
- [Allauth admin protection](https://github.com/pennersr/django-allauth/blob/main/docs/common/admin.rst)
- [Allauth rate-limit deployment requirements](https://github.com/pennersr/django-allauth/blob/main/docs/common/rate_limits.rst)
- [Django 5.2 caching](https://docs.djangoproject.com/en/5.2/topics/cache/)
- [Django transaction testing](https://docs.djangoproject.com/en/5.2/topics/testing/tools/)
- [PostgreSQL 17 backup and restore](https://www.postgresql.org/docs/17/backup-dump.html)
- [PostgreSQL atomic ON CONFLICT](https://www.postgresql.org/docs/17/sql-insert.html)

## Progress

### Phase 1: Admin Protection and Recovery

#### Automated

- [x] 1.1 Admin security tests and `sh scripts/testing/security-rehearsal.sh admin` prove admission, login limits, shared state, cache failure, and targeted reset isolation.
- [x] 1.2 Django checks, migration drift check, and `uv run --locked pip-audit` pass.

#### Manual

- [ ] 1.3 Local operator verification confirms protected admin login and targeted recovery; the runbook records database cache setup and the production client-IP verification procedure.

### Phase 2: Family Authorization and Integrity

#### Automated

- [ ] 2.1 Focused access, admin, token, and entry suites prove the documented matrix and validation non-effects.
- [ ] 2.2 The full Django suite, system checks, and migration drift check pass.

#### Manual

- [ ] 2.3 Review confirms that every supported operation maps to evidence and that MS-01 token reads remain explicitly permitted.

### Phase 3: PostgreSQL Migration and Restore Rehearsals

#### Automated

- [ ] 3.1 `sh scripts/testing/postgres-rehearsal.sh` passes all upgrade, constraint, interrupted-migration, historical-write, and dump/restore scenarios without required skips.
- [ ] 3.2 Rehearsal output records server/client versions, image digest, source revision, scenario outcomes, and cleanup without exposing credentials or fixture text.

#### Manual

- [ ] 3.3 Review confirms the rehearsal engine matches the recorded production major and that the evidence supports only the scenarios actually executed.

### Phase 4: Maintenance Deployment and Acceptance Evidence

#### Automated

- [ ] 4.1 Deployment shell tests prove ordering, locking, protocol rejection, every failure boundary, retained recovery state, and absence of automatic rollback or secret leakage.
- [ ] 4.2 The full Django suite, system checks, migration drift check, database authentication integration, and PostgreSQL rehearsal pass; dependency audit passes after dependency changes.

#### Manual

- [ ] 4.3 Operator-approved deployment acceptance records protocol-2 installation, maintenance recovery evidence, production HTTPS/admin smoke, client-IP verification, and matching PostgreSQL version.
