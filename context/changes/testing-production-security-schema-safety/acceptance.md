# Verification and acceptance

## Phase 1 revision — 2026-10-04

At the user's request, shared login state now uses the existing database instead
of Redis. Redis is removed from dependencies, settings, and the current runbook.
No production actions or manual-success declarations were made. The user
authorized committing the verified Phase 1 implementation.
Phases 2–4 have not started; Phase 1 manual confirmation remains pending.

### Implementation

- `family_access 0003_authcacheentry` creates the dedicated authentication-state
  table with a unique key and indexed expiry. Apply it before activating new code.
- Production always uses `DatabaseAuthCache` on the existing default connection.
  Development remains process-local unless `DJANGO_AUTH_DB_CACHE=True` is set.
- Atomic insert-on-conflict implements add/lock acquisition across processes.
  JSON state avoids pickle deserialization. Writes remove only expired rows;
  active histories are never evicted for capacity.
- PostgreSQL statement and lock timeouts are one second for cache operations.
  Connection establishment uses the existing database configuration.
- Cache database errors become a sanitized 503; no local production fallback.
  Targeted operator reset keeps its existing restricted helper interface.

### Automated evidence

- Focused login, database policy, and recovery suite: 39 tests passed.
- `uv run python manage.py test`: 724 tests, passed with eight skips (four
  disposable PostgreSQL checks plus four pre-existing skips). Required database
  checks run separately in the harness; skips do not establish that evidence.
- `uv run python manage.py check`: no issues.
- `uv run python manage.py makemigrations --check --dry-run`: no changes.
- `sh scripts/deployment/tests/family-notes-deploy-test.sh`: passed.
- `sh -n scripts/testing/security-rehearsal.sh`: passed.
- `git diff --check`: passed.
- `uv run --locked pip-audit`: no known vulnerabilities.

- `sh scripts/testing/security-rehearsal.sh admin`: passed on PostgreSQL 17.11,
  with 42 tests plus one stopped-server outage test, no skips. Shared histories,
  independent processes, concurrent atomic add, targeted recovery, persistence
  across PostgreSQL restart, and authentication denial during outage all passed.
- Image: `postgres@sha256:d74eeac9a635390a49bc21bd49fccd973de707e2a53a76ac49b552b8712ec46f`.
  Revision: `78cf5e7722dfe99db700f93b92bc0967eaf0a2d5`, with worktree changes.
- Cleanup completed. The harness uses a home-directory temporary configuration
  because Snap Docker cannot read the host's private `/tmp` files.

### Dependency adjustment retained

The earlier audit found OAuthLib 3.3.1 advisory `PYSEC-2026-4114`. The allauth
minimum remains 65.19.7, permitting fixed OAuthLib 4.0.0. Removing Redis also
removed its transitive async-timeout dependency. The advisory was not suppressed.

### Pending acceptance

- Earlier Redis evidence belongs to the superseded implementation. The current
  PostgreSQL authentication rehearsal does not claim Phase 3 migration/restore
  certification or a match to the production server major.
- Local operator verification of protected login and targeted recovery is pending.
  Follow the deployment runbook's "Admin login protection" section.
- Cache-table migration, nginx/provider client-IP verification, two-worker
  production smoke, and production acceptance remain operator-controlled.
- Obtain Phase 1 manual confirmation before Phase 2, as the approved plan requires.
