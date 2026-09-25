# Production Health Release Gate Implementation Plan

## Overview

Harden the existing Mikr.us deployment workflow so database-backed application readiness is a mandatory, deterministic release gate. Preserve the current manual approval model, narrow privilege boundary, and human-controlled rollback policy.

## Current State Analysis

`GET /healthz/` already executes `SELECT 1`, returns `200 {"status":"ok"}` when PostgreSQL is reachable, and returns a detail-free `503 {"status":"unavailable"}` on database failure.

The release workflow currently:

1. Resolves an approved commit from `master`.
2. Installs locked production dependencies.
3. Runs Django deployment and migration-drift checks.
4. Creates and verifies a database backup.
5. Runs migrations, collects static files, switches the active symlink, and restarts Gunicorn.
6. Performs one immediate health request.

The final request has no retry window or per-attempt timeout. If it fails, the shell exits without declaring success, but the new release remains active and the output does not clearly state the resulting production state or next diagnostic actions.

## Desired End State

A release is declared successful only when the internal Gunicorn-socket request returns the exact healthy `/healthz/` response before a strict 30-second wall-clock deadline.

Transient startup and database failures are retried every two seconds. Exhaustion leaves the activated release and pre-release backup intact, performs no rollback or database restoration, exits nonzero, and prints timestamped, stage-specific diagnostic guidance.

### Key Discoveries:

- The health endpoint and its detail-free success/failure contract already exist in `family_notes/views.py:10` and `family_notes/tests.py:59`.
- Activation switches `current` before readiness is checked in `scripts/deployment/family-notes-deploy:60`.
- The one-shot post-activation check is invoked from `scripts/deployment/release.sh:66`.
- The runbook already distinguishes internal readiness from public HTTPS verification.
- The documented claim that the previous release remains active until health succeeds does not match current script behavior.

## What We're NOT Doing

- Changing the `/healthz/` route, response schema, authentication, or database query.
- Adding a second liveness endpoint.
- Automatically rolling back application code or restoring the database.
- Starting a candidate service on a second socket or port.
- Making public HTTPS part of the automated gate.
- Adding CI/CD deployment, monitoring providers, alerts, backup scheduling, restore drills, or reboot checks.
- Adding application models, migrations, dependencies, or environment variables.
- Treating the product's 30-second classification target as a health-check latency target.

## Implementation Approach

Extract the retry/deadline state machine into a repository-owned POSIX shell library. Its production installation path remains fixed and root-owned; no environment override or test mode may affect the privileged helper.

The deployment helper supplies a private probe that:

- Connects through the existing Gunicorn Unix socket.
- Sends the configured production host and forwarded HTTPS header.
- Bounds each request so a hung `curl` cannot defeat the overall deadline.
- Requires both successful transport/HTTP status and the exact `{"status": "ok"}` body.

The pure state machine accepts hard-coded caller callbacks for probing, time, and sleeping. The test harness supplies deterministic fake callbacks without touching production paths or privileged operations.

## Critical Implementation Details

The 30-second value is a strict elapsed-time deadline measured from immediately before the first probe. A probe may start only while `elapsed < 30`, and it succeeds only if it completes successfully while `elapsed < 30`; completion at exactly 30 seconds is exhaustion. Check the clock before and after every probe, pass the remaining whole-second budget to the probe callback, cap both its `curl` timeout and the next sleep to that budget, and never start a zero-budget operation. Use UTC epoch seconds from `date` as the production clock. Because POSIX shell has no portable monotonic clock, treat a clock value earlier than the preceding observation as exhaustion and document this conservative fail-closed behavior. The installed retry library and deployment helper form release-gate protocol version `1`. The helper must reject a missing library or any version other than `1`, and the release orchestrator must verify version `1` before creating a release.

## Phase 1: Readiness Gate and Regression Harness

### Overview

Create and verify the reusable readiness state machine independently of root access, systemd, sockets, PostgreSQL, and live production.

### Changes Required:

#### 1. Readiness state machine

**File**: `scripts/deployment/release-gate.sh`

**Intent**: Add a small POSIX shell library that owns readiness timing, retries, and evidence messages without knowing production paths or secrets.

**Contract**: Expose a function receiving probe, clock, and sleep callback names supplied by its trusted caller. It must probe immediately and pass the probe callback the remaining whole-second budget. Before and after each probe, read the clock and reject success unless `elapsed < 30`; a clock regression fails closed as exhaustion. Between failures, sleep for the lesser of two seconds and the remaining budget, then re-check the clock before starting another probe. It must return success on the first probe that completes inside the legal window, return nonzero after deadline exhaustion, and emit timestamped start, retry, success, and exhaustion messages without response bodies or secrets. It must never execute rollback, inspect logs, or mutate release state.

#### 2. Dependency-free regression harness

**File**: `scripts/deployment/tests/release-gate-test.sh`

**Intent**: Exercise the timing and exit contracts deterministically using fake callbacks and temporary state.

**Contract**: Use `/bin/sh`, `mktemp -d`, cleanup traps, and plain shell assertions. Cover immediate success, transient recovery, success at the last legal whole-second observation, rejection at exactly 30 seconds, deadline exhaustion, backward clock movement, transport/HTTP-equivalent failures, remaining-budget propagation, clamped sleep cadence, and absence of retries after success.

### Success Criteria:

#### Automated Verification:

- Shell syntax validation passes for the readiness library and test harness.
- The dependency-free readiness harness passes every success, recovery, timeout, and boundary scenario.

---

## Phase 2: Release Integration and Failure Contract

### Overview

Integrate the tested readiness state machine into the privileged helper and make release completion depend on its result.

### Changes Required:

#### 1. Privileged internal-health integration

**Files**: `scripts/deployment/family-notes-deploy`, `scripts/deployment/release-gate.sh`

**Intent**: Replace the one-shot helper health action with bounded, exact database-backed readiness while retaining fixed production configuration and least privilege.

**Contract**: Source the installed library from a fixed root-owned path such as `/usr/local/libexec/family-notes/release-gate.sh`; do not permit environment or command-line overrides for the library, socket, endpoint, environment file, timeout, or protocol version. Define protocol version `1` in the library, require the helper to compare it with its own expected version before exposing readiness, and fail closed when the library is absent or incompatible. Add a side-effect-free `gate-version` helper action that prints only the verified protocol version; preserve the existing `health` command interface and nonzero failure behavior. Keep deriving the health host from protected `DJANGO_ALLOWED_HOSTS`, accept the remaining whole-second budget from the state machine and use it as the `curl` maximum time for that attempt, validate the exact `{"status": "ok"}` response, and keep `check --deploy` governed by Django's native exit status without parsing warning text.

#### 2. Release orchestration and diagnostics

**Files**: `scripts/deployment/release.sh`, `scripts/deployment/tests/release-test.sh`

**Intent**: Make the readiness result the final release-completion gate and clearly communicate the production state when it fails.

**Contract**: Refactor the orchestration body in `release.sh` into a function that receives command callbacks and path values from its caller. The normal production entry point must supply the existing fixed commands and paths itself; environment variables and command-line arguments must not override them. Permit a source-only switch solely so the unprivileged shell test can load the function without executing the production entry point; this switch must not alter, configure, or invoke the privileged helper. Before fetching or creating a release, call the fixed helper's `gate-version` action and require the exact value `1`; missing, incompatible, or unexpected output must stop the release without mutation. Invoke readiness only after activation and service restart, and print completion only after readiness succeeds. On exhaustion, exit nonzero, identify the attempted release, state that the activated release and backup remain in place, and print explicit `status`, `logs`, and `health` commands for operator-led diagnosis. Do not execute logs automatically, switch the symlink, invoke rollback, reverse migrations, or restore the database. The dependency-free `/bin/sh` harness must supply fake callbacks and temporary paths to prove the production ordering and failure contract without requiring the `deploy` OS account, sudo, root-owned paths, a Git repository, UV, systemd, PostgreSQL, or a live service.

### Success Criteria:

#### Automated Verification:

- Shell syntax validation passes for the library, deployment helper, release script, and test harness.
- Focused Django health tests assert status, parsed JSON, and the exact healthy response bytes `b'{"status": "ok"}'`; the complete Django test suite passes without changing the `/healthz/` contract.
- `scripts/deployment/tests/release-test.sh` proves that exhausted readiness prevents completion, exits nonzero, emits diagnostic guidance, and never invokes rollback; it also proves that success is printed only after activation, restart, and readiness succeed.

#### Manual Verification:

- A local mocked release rehearsal shows timestamped stage output without secrets, response bodies, or automatic log dumping.

**Implementation Note**: After completing this phase and all automated verification passes, pause for human confirmation of the manual rehearsal before proceeding.

---

## Phase 3: Operator Documentation and Acceptance

### Overview

Align the deployment documentation and root installation procedure with the implemented gate, then define the operator-approved production acceptance path.

### Changes Required:

#### 1. Deployment runbook and release record

**Files**: `context/changes/deployment/mikrus-runbook.md`, `context/changes/deployment/deployment-plan.md`

**Intent**: Replace the inaccurate health-gated activation description with the real post-activation stop-and-diagnose contract and document safe installation and verification.

**Contract**: Through the authorized root-capable path, copy the library and helper to root-owned temporary files in their respective destination directories, retain recoverable copies of the installed artifacts, set the staged files' final non-user-writable ownership and permissions, and syntax-check both. Promote the library first with a same-filesystem rename; the old helper remains usable because it does not load the library. Then execute the staged helper's `gate-version` action, which must load the newly installed fixed-path library and report protocol version `1`, before promoting the helper with another same-filesystem rename. Verify installed ownership, permissions, syntax, and `gate-version` output before allowing a release. The new helper must fail closed if the library promotion is incomplete. Document restoration of the retained artifacts if any final verification fails. Also document that direct root SSH remains unavailable and provider-console access is required; describe the strict 30-second internal gate and exact success response; state that gate exhaustion leaves the activated application and backup intact; preserve human-controlled application rollback and database recovery; document the expected HSTS subdomain/preload warnings as accepted consequences of the shared `mikrus.dev` parent domain; keep public HTTPS verification as a manual acceptance step; and record external monitoring, recurring backups, restore drills, rollback rehearsal, and reboot verification as separate follow-up work.

### Success Criteria:

#### Automated Verification:

- Repository verification passes: Django checks, migration drift check, full test suite, readiness harness, and POSIX syntax checks.

#### Manual Verification:

- An authorized operator installs the matched library/helper pair and confirms their ownership, permissions, and syntax on Mikr.us.
- An operator-approved release demonstrates transient retry or immediate readiness, exact internal health success, and completion only after the gate passes.
- A controlled failed-probe rehearsal exits nonzero, preserves the selected release and backup, prints diagnostic commands, performs no rollback, and leaves public HTTPS verification manual.

**Implementation Note**: Production mutation requires explicit operator authorization. If authorization is unavailable, complete the repository work and leave these manual rows pending.

---

## Testing Strategy

### Unit Tests:

- Lock the healthy endpoint's operational wire contract with `response.content == b'{"status": "ok"}'` alongside the existing status and parsed-JSON assertions.
- Verify immediate success performs one probe and no sleeps.
- Verify transient failures retry at two-second intervals.
- Verify success at the last legal whole-second observation returns success and completion at exactly 30 seconds fails.
- Verify the deadline, including backward clock movement, prevents additional probes.
- Verify probe timeouts and sleeps are capped to the remaining budget.
- Verify transport and HTTP-style nonzero results retry identically.
- Verify success and failure evidence excludes probe bodies and secrets.

### Integration Tests:

- Source the orchestration function from `release.sh` in source-only mode and execute it with fake callbacks and temporary paths from `scripts/deployment/tests/release-test.sh`.
- Assert that the production entry point retains its fixed helper and UV paths and does not accept test-supplied overrides.
- Assert that a missing or incompatible `gate-version` response stops orchestration before fetch, worktree creation, backup, or activation.
- Assert readiness failure suppresses the completion message.
- Assert readiness failure exits nonzero and prints operator guidance.
- Assert no rollback command is called.
- Retain existing Django tests for exact healthy and database-unavailable responses.

### Manual Testing Steps:

1. Run a mocked local release rehearsal and inspect stage messages.
2. Install matched root-owned library and helper artifacts through the authorized console path.
3. Run an approved deployment and verify internal readiness precedes completion.
4. Exercise a controlled failed-probe path without interrupting family data access.
5. Verify public HTTPS separately and retain the SSH transcript as release evidence.

## Performance Considerations

The gate adds no runtime request overhead outside deployment. Each probe is individually bounded, and the total elapsed readiness window cannot exceed 30 seconds apart from minimal shell scheduling overhead.

## Migration Notes

No application migration or data conversion is introduced. Existing and future production migrations must remain backward-compatible because an operator may choose an application-only rollback after diagnosis. Database restoration remains a separate human-approved incident operation.

The installed retry library and helper form one operational version and must be updated together before using the revised release script.

## References

- Roadmap scope: `context/foundation/roadmap.md`
- Infrastructure constraints: `context/foundation/infrastructure.md`
- Deployment contract: `context/changes/deployment/deployment-plan.md`
- Operator procedure: `context/changes/deployment/mikrus-runbook.md`
- Health endpoint: `family_notes/views.py:10`
- Health tests: `family_notes/tests.py:59`
- Release orchestration: `scripts/deployment/release.sh:43`
- Privileged helper: `scripts/deployment/family-notes-deploy:41`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles.

### Phase 1: Readiness Gate and Regression Harness

#### Automated

- [x] 1.1 Shell syntax validation passes for the readiness library and test harness.
- [x] 1.2 The dependency-free readiness harness passes every success, recovery, timeout, and boundary scenario.

### Phase 2: Release Integration and Failure Contract

#### Automated

- [ ] 2.1 Shell syntax validation passes for the library, deployment helper, release script, and test harness.
- [ ] 2.2 Focused Django health tests and the complete Django test suite pass without changing the `/healthz/` contract.
- [ ] 2.3 Deployment-script tests prove that exhausted readiness prevents completion, exits nonzero, emits diagnostic guidance, and never invokes rollback.

#### Manual

- [ ] 2.4 A local mocked release rehearsal shows timestamped stage output without secrets, response bodies, or automatic log dumping.

### Phase 3: Operator Documentation and Acceptance

#### Automated

- [ ] 3.1 Repository verification passes: Django checks, migration drift check, full test suite, readiness harness, and POSIX syntax checks.

#### Manual

- [ ] 3.2 An authorized operator installs the matched library/helper pair and confirms their ownership, permissions, and syntax on Mikr.us.
- [ ] 3.3 An operator-approved release demonstrates transient retry or immediate readiness, exact internal health success, and completion only after the gate passes.
- [ ] 3.4 A controlled failed-probe rehearsal exits nonzero, preserves the selected release and backup, prints diagnostic commands, performs no rollback, and leaves public HTTPS verification manual.
