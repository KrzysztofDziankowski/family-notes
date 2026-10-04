# Production Security and Schema Safety — Plan Brief

> Full plan: [plan.md](plan.md)
> Research: [research.md](research.md)

## What & Why

Complete the first test-rollout phase by protecting administrative login, proving family-data authority, and rehearsing safe PostgreSQL upgrades and recovery. Fix the specific supported-path gaps needed for those guarantees.

## Starting Point

Superuser admission and family-scoped request tests already exist. Admin login lacks shared abuse protection, database evidence defaults to SQLite, and deployments migrate while old application code remains active.

## Desired End State

Operators use protected login and a targeted SSH recovery procedure. Family-data access follows an evidenced matrix. Releases briefly stop requests and conversion workers, preserve a backup, and remain recoverable without automatic destructive action.

## Key Decisions Made

| Decision | Choice | Why | Source |
|---|---|---|---|
| Admin defense | Allauth login limits | Reuse installed authentication protection | Plan |
| Shared state | Existing database, atomic cache backend | Provide shared state and atomic operations | User revision, 2026-10-04 |
| Operator recovery | Targeted SSH reset | Recover without flushing unrelated limits | Plan |
| Hardening | Helper, issuance, model/admin validation | Close supported-path gaps without database triggers | Plan |
| Database evidence | Disposable Docker PostgreSQL | Keep rehearsals reproducible and isolated | Plan |
| Upgrade availability | Maintenance window | Avoid historical intermediate-schema incompatibility | Plan |
| Deployment sequencing | One locked helper operation | Serialize the entire maintenance window | Approved phases |
| Automation authority | Intake POST and family entry GET | Preserve the later MS-01 contract | Roadmap/research |

## Scope

**In scope:** admin protection/reset, authorization matrix, targeted validation, PostgreSQL migrations and restore, maintenance deployment, acceptance evidence.

**Out of scope:** MFA, network restriction, database triggers, E2E, Phase 2 resilience work, production restore, automatic rollback, and general monitoring/backup rollout.

## Architecture / Approach

Admin requests enter allauth; limiter histories reside in the existing database. Family services and admin forms enforce their existing authority plus targeted validation. Disposable containers prove database behavior. A locked deployment helper stops Gunicorn before backup and migration, starts the candidate only after successful preparation, and preserves failure evidence.

## Phases at a Glance

| Phase | Delivers | Main risk |
|---|---|---|
| 1. Admin protection | Shared limits and targeted reset | Password abuse and operator lockout |
| 2. Authorization | Complete matrix and validation | Unauthorized access or inconsistent relationships |
| 3. PostgreSQL | Upgrades, failure/retry, actual restore | Data loss or false SQLite confidence |
| 4. Deployment | Maintenance sequencing and acceptance | Old-code writes or unsafe recovery |

**Prerequisites:** working Docker daemon for local evidence; privileged operator path for helper installation and cache-table migration; read-only production version inventory before certification.

**Estimated effort:** roughly 5–8 focused development sessions, plus operator acceptance; a planning estimate, not a delivery commitment.

## Open Risks & Assumptions

- PostgreSQL 17 is the rehearsal baseline, not a claim about production. Certification requires a matching major.
- Mikrus’s actual client-IP boundary requires operational verification.
- Shared login state adds a database table; cache failures intentionally block new authentication.
- Application validation leaves arbitrary raw ORM writes as a trusted bypass.
- Failed migrations may extend downtime until an explicit forward fix.
- Local synthetic restore evidence does not certify production backups.

## Success Criteria (Summary)

- Administrative abuse is limited across workers, and targeted recovery preserves unrelated protection.
- Supported operations enforce family ownership and least privilege.
- PostgreSQL and deployment evidence demonstrate preservation and a defined failure-recovery path.

## References

The full plan and existing research contain code anchors and the official allauth, Django and PostgreSQL documentation used for these decisions.
