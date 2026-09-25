# Production Health Release Gate — Plan Brief

> Full plan: `context/changes/production-health-release-gate/plan.md`

## What & Why

Turn the existing database-backed `/healthz/` endpoint into a reliable release gate. A deployment is successful only after the restarted Django application reaches PostgreSQL within a strict 30-second readiness window.

## Starting Point

The release workflow already runs Django checks, verifies migration state, creates a database backup, activates the release, and performs one immediate internal health request. A failed request leaves the new release selected without structured diagnostics, while documentation incorrectly implies the previous release remains active until health succeeds.

## Desired End State

The release workflow waits deterministically for internal Django-and-database readiness, exits nonzero when the deadline expires, preserves the activated release and backup for diagnosis, and never rolls back application or database state automatically.

## Key Decisions Made

| Decision | Choice | Why |
| --- | --- | --- |
| Scope | Minimal release gate | Matches roadmap F-03 without expanding into general operations work |
| Gate boundary | Internal Unix-socket readiness | Gives a deterministic Django-and-database signal independent of the provider edge |
| Failure behavior | Stop and diagnose | Avoids running older code against a potentially migrated schema |
| Readiness window | Strict 30-second wall-clock deadline, 2-second retry cadence | Tolerates startup races without leaving an unhealthy release pending indefinitely |
| Evidence | Timestamped console messages and exit status | Fits the existing operator-driven SSH workflow |
| Django warnings | Native exit status with documented HSTS exceptions | Avoids brittle parsing of human-readable output |
| Testing | Dependency-free shell harness | Covers consequential failure paths without adding a framework |

## Scope

**In scope:**

- Strict internal readiness retry/deadline logic.
- Exact validation of the existing `/healthz/` success contract.
- Release failure diagnostics and nonzero exit behavior.
- Dependency-free shell regression tests.
- Root-helper installation and operator documentation updates.

**Out of scope:**

- Automatic application or database rollback.
- Public HTTPS as an automated release gate.
- External monitoring and alerts.
- Scheduled/off-provider backups and restore drills.
- Reboot certification or broader infrastructure hardening.
- Changes to the public `/healthz/` route or product data model.

## Architecture / Approach

A small POSIX shell library owns the retry state machine and exposes a callback-based function that can be tested with fake probes, clocks, and sleeps. The root-owned deployment helper sources that library from a fixed path and supplies the real Unix-socket health probe. The release script remains the orchestrator and declares completion only after the helper succeeds.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Readiness gate and regression harness | Deterministic deadline logic with shell tests | Off-by-one or elapsed-time errors |
| 2. Release integration and failure contract | Privileged helper and release orchestration enforce readiness | Weakening the privilege boundary or masking failure |
| 3. Operator documentation and acceptance | Installation, warning, and production-verification procedures | Installed helper/library drifting from repository versions |

**Prerequisites:** Existing Mikr.us deployment helper, dedicated PostgreSQL, protected production environment, and operator access through the provider console for root-owned helper updates.

**Estimated effort:** Approximately 2–3 implementation sessions across three phases, plus an operator-approved production rehearsal.

## Open Risks & Assumptions

- Direct root SSH is unavailable; installing the new library and refreshed helper requires the authorized provider-console path.
- Migrations remain backward-compatible, but failed readiness still requires a human decision rather than automatic rollback.
- The internal gate intentionally does not prove nginx, Mikr.us routing, DNS, or TLS health.
- Console evidence is durable only when the operator retains the SSH transcript.

## Success Criteria (Summary)

- A healthy release is declared complete only after exact internal Django-and-database readiness succeeds within 30 seconds.
- Transient failures recover through retries; deadline exhaustion exits nonzero with safe diagnostic guidance and no rollback.
- Deterministic tests cover immediate success, recovery, deadline boundaries, transport/HTTP failures, and exhaustion.
