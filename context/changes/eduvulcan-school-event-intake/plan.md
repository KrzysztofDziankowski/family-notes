# EduVulcan School Event Intake Implementation Plan

## Overview

Implement roadmap slice S-05 by converting stored EduVulcan notifications into family-scoped entries outside the request path. Preserve the current fast intake API while adding deterministic school rules, privacy-bounded classification fallback, crash-safe one-to-many output, and an operationally visible in-process worker.

## Current State Analysis

- `POST /api/automation/notifications/` authenticates a parent token, validates a payload of at most 16 KiB, deduplicates it, stores a pending row, and returns `202`.
- `InboundNotification` has lifecycle fields but no attempt schedule, lease, output relationship, or worker.
- `Entry` already supports `source=eduvulcan`, nullable creator and submission key, family scoping, parent correction/deletion, and child visibility.
- Classification currently requires a signed-in parent, although conversion must remain possible after the original token owner changes.
- Production runs two synchronous Gunicorn workers; no external background-job service exists.

### Key Discoveries

- Intake must remain classification-free and use `transaction.on_commit` only to signal committed rows.
- Django row locking must be exercised inside atomic transactions; SQLite cannot validate the PostgreSQL concurrency guarantee.
- Existing listing and management queries automatically surface converted entries when family and assignee are set correctly.
- The archived F-04 handoff requires database sweeps, explicit Gunicorn startup, and PostgreSQL advisory locking rather than `AppConfig.ready()`.

## Desired End State

- Every pending notification is eventually converted into one or more entries or reaches a visible terminal failure.
- Known categories use fixed rules. Unknown or malformed formats use family-scoped classification and then a general-note fallback.
- Output creation and lifecycle updates are atomic and retry-safe.
- Intake continues accepting notifications when workers are unavailable.
- Health checks distinguish disabled, healthy, and stale conversion workers.
- Raw title, message, and payload data are scrubbed after 90 days while deduplication and provenance metadata remain.

## What We're NOT Doing

- No direct login to or scraping of EduVulcan.
- No Celery, Redis, or hosted queue.
- No new token scopes or parent token-management UI.
- No synchronous conversion in the intake request.
- No parent confirmation step for automated entries.
- No changes to the existing raw-notification deduplication definition.
- No storage of notification/classification text for analytics or model training.
- No new parent or child entry views.

## Implementation Approach

Add explicit conversion metadata and an output-link model. A worker claims due rows under a lease, derives ordered output proposals, and saves entries plus links in one transaction. Output indexes are stable within a notification, making retries idempotent even when a notification fans out.

The intake endpoint schedules only a lightweight wake-up after commit. Each Gunicorn process starts its worker explicitly after fork or on first safe runtime initialization. Startup and periodic sweeps find pending, retry-due, and stale-processing rows. PostgreSQL advisory locking limits active conversion globally; database rows remain the recovery source.

## Critical Implementation Details

**Lifecycle:** never start threads from `AppConfig.ready()`. Worker threads need their own database connections and must close them on exit.

**Atomicity:** entry rows, conversion-output links, and the processed status must commit together. A crash before commit creates no visible partial conversion; a retry sees existing output indexes and cannot duplicate them.

**Privacy:** persisted errors and logs contain only notification IDs, status/error codes, and attempt metadata—never titles, messages, classifier payloads, bearer tokens, or family names.

## Phase 1: Conversion Schema and Domain Rules

### Overview

Define durable conversion contracts and deterministic, independently testable proposal generation.

### Changes Required

#### 1. Conversion lifecycle and provenance

**File:** `entries/models.py`, a new `entries` migration

**Intent:** Represent leases, retry scheduling, raw-data retention, and one-to-many output provenance.

**Contract:** Extend `InboundNotification` with `attempt_count`, `next_attempt_at`, `lease_expires_at`, `last_error_code`, and `raw_pruned_at`. Keep existing status values; `failed` is terminal until an operator requeues it. Add `NotificationConversionOutput` with notification, stable `output_index`, output kind, timestamps, and a nullable `entry` FK using `on_delete=SET_NULL`. Enforce uniqueness on `(notification, output_index)` and one output-link owner per generated entry. Parent hard deletion nulls the entry reference but preserves the non-sensitive output tombstone, so a retry treats that index as completed and never recreates it.

#### 2. Fixed-rule proposal generation

**File:** new modules under `entries/eduvulcan/`

**Intent:** Convert known categories without provider calls and return ordered proposals with stable output indexes.

**Contract:** Tests, quizzes, class tests, and homework produce dated calendar-event proposals for the named child. Timetable changes produce one dated child note per valid change. If timetable parsing leaves malformed content, append one unassigned family-note proposal after all valid change proposals. Grades, lucky numbers, and late arrivals produce child notes. Teacher messages produce unassigned family notes dated from the message. Normalize Unicode and whitespace while preserving meaningful Polish text. Resolve yearless dates to the nearest matching date within six months before or after `captured_at`. Match active children by normalized display name, including Polish diacritics. If several match, choose the highest `FamilyMember.pk`; a missing or inactive match yields an unassigned proposal.

#### 3. Family-scoped classification fallback

**File:** `entries/classification/service.py` and related contract tests

**Intent:** Reuse the established privacy boundary without impersonating a user or relying on the original token owner.

**Contract:** Add a family-scoped classification entry point that accepts notification text, reference date, and a snapshot of currently active child memberships. It preserves the existing `store=False`, deadline, validation, sanitized logging, and result contracts. An unusable result becomes a general unassigned note.

#### 4. Anonymized rule corpus

**File:** focused tests under `entries/tests/`

**Intent:** Turn representative local notification shapes into safe regression fixtures.

**Contract:** Fixtures contain invented names and identifiers while preserving category, punctuation, date, and multi-change structures. No file from `eduvulcan-queue/` or real payload value is committed.

### Success Criteria

#### Automated Verification

- Migration and model tests enforce lease, retry, pruning, and output-link constraints.
- Fixed-rule tests cover every PRD category, Polish normalization, nearest-year boundaries, newest-ID child ties, missing children, and malformed input.
- Multi-change tests produce ordered entries for valid segments plus one unassigned remainder note.
- Family-scoped classification tests preserve privacy, active-family scoping, and general-note fallback.

#### Manual Verification

- Review anonymized fixtures against the local sample corpus and confirm that no real names or identifiers remain.
- Review representative Polish entry text for clarity and preservation of notification meaning.

---

## Phase 2: Atomic Conversion Lifecycle

### Overview

Implement crash-safe conversion, bounded retries, stale-work recovery, and retention.

### Changes Required

#### 1. Claiming and leases

**File:** conversion service under `entries/eduvulcan/`

**Intent:** Ensure only one worker owns a notification attempt at a time.

**Contract:** Atomically claim pending or retry-due rows and stale `processing` rows. Each claim increments `attempt_count`, sets `status=processing`, and grants a two-minute lease. A worker that no longer owns the lease cannot commit outputs.

#### 2. Atomic output persistence

**File:** `entries/services.py`, conversion service

**Intent:** Save generated EduVulcan entries through one family-scoped automated write path.

**Contract:** Save `source=eduvulcan`, `created_by=None`, and the stored notification family. Validate assignees against that family and enforce normal entry invariants. Save all entries and ordered output links in the same transaction as `status=processed` and `processed_at`. Existing output indexes are returned unchanged on retry. Partial persistence is impossible: either every proposal lands or none do.

#### 3. Retry and terminal-failure policy

**File:** conversion service and admin integration

**Intent:** Recover temporary failures without endlessly replaying deterministic input.

**Contract:** Retry only provider timeouts/unavailability and transient database contention. Allow three total conversion attempts: immediate, approximately one minute later, and approximately five minutes later. Automated classification disables the backend-owned retry, so the entire conversion lifecycle makes at most three provider calls; manual capture keeps its existing retry behavior. Deterministic parse/validation problems proceed through classifier/general-note fallback rather than retry. Exhausted provider failures save a general unassigned note. Exhausted infrastructure failures become `failed` with a sanitized code. Provide a dedicated requeue action to superusers by granting only the minimum action permission: fields and direct edits remain read-only, add stays forbidden, and family members remain denied. Requeue does not edit payloads or reset output history.

#### 4. Raw-data pruning

**File:** worker maintenance service

**Intent:** Enforce the selected 90-day raw retention without breaking deduplication or provenance.

**Contract:** Periodically scrub processed rows older than 90 days by setting `title=''`, `message=''`, and `payload={}`, then setting `raw_pruned_at`. Failed or still-actionable rows are not pruned. Scrubbing is idempotent, preserves identifiers/hashes required by intake deduplication, and makes admin render an explicit “raw data pruned” state instead of an empty title.

### Success Criteria

#### Automated Verification

- Concurrent and repeated conversion calls create exactly one entry per output index; deleting an entry and retrying preserves its tombstone and does not recreate it.
- A simulated crash before commit leaves no entries or links; the next claim converts successfully.
- Retry timing, a three-provider-call maximum, three-attempt exhaustion, stale two-minute leases, fallback, and action-only admin requeue are covered.
- Ninety-day pruning uses the agreed empty sentinels while retaining deduplication and provenance behavior.

#### Manual Verification

- In admin, a failed row exposes only sanitized diagnostics and can be requeued.
- A processed row remains traceable to its output metadata after raw fields are pruned.

---

## Phase 3: Worker and Intake Integration

### Overview

Connect durable intake to a production-safe in-process worker and expose its health.

### Changes Required

#### 1. Post-commit wake-up

**File:** `entries/api_views.py`

**Intent:** Prompt conversion quickly without adding classification or conversion work to the request.

**Contract:** Newly created rows register an `on_commit` callback that enqueues the row ID when workers are enabled. Duplicate intake responses do not create outputs or reset lifecycle state. Queue failure never changes the successful durable `202`.

#### 2. Worker runtime

**File:** worker module plus explicit Gunicorn/runtime integration

**Intent:** Process wake-ups and database sweeps safely in each application process.

**Contract:** Workers are disabled in tests and configurable through environment-backed settings. Startup performs a sweep; periodic sweeps cover pending, retry-due, and stale-processing rows. PostgreSQL uses a stable advisory lock so only one process actively converts at a time. SQLite follows the same functional service contract without claiming to validate cross-process locking. Worker threads open and close their own database connections. No worker starts during management commands, migrations, or application import. The exact post-fork versus safe lazy-start mechanism remains an explicitly accepted implementation-time decision.

#### 3. Shared worker health

**File:** worker heartbeat model/service and a dedicated conversion-health route

**Intent:** Make disabled or stalled conversion visible without rejecting notification intake.

**Contract:** Active workers update a database heartbeat at a bounded interval. Existing `/healthz/` remains byte-compatible and returns exactly `{"status": "ok"}` on database success for the production release gate. Add `GET /healthz/conversion/`: explicitly disabled conversion returns HTTP 200 with `{"status": "disabled"}`, enabled conversion with no fresh heartbeat returns HTTP 503 with `{"status": "unavailable"}`, and enabled conversion with a fresh heartbeat returns HTTP 200 with `{"status": "ok"}`. Responses contain status codes only, never queue payloads or family data.

#### 4. Configuration and operational contract

**File:** `family_notes/settings.py`, `.env.example`, deployment runbook

**Intent:** Make worker enablement, sweep interval, lease, retry delays, heartbeat freshness, and retention explicit and environment-backed.

**Contract:** Production documentation enables the worker alongside the two existing Gunicorn processes. Add the conversion-health probe to `scripts/deployment/family-notes-deploy` and its shell tests without changing the existing `/healthz/` exact-body gate; update README and the runbook with both checks. Tests pin safe defaults and fail closed on invalid numeric settings.

### Success Criteria

#### Automated Verification

- Intake remains `202`, classification-free, and bounded when enqueueing succeeds, fails, or workers are disabled.
- Worker tests cover startup sweep, periodic sweep, retry-due selection, advisory-lock refusal, and connection cleanup.
- Health tests preserve the exact `/healthz/` body and cover disabled conversion, healthy heartbeat, and stale/missing heartbeat on `/healthz/conversion/`; deployment shell tests cover both probes.
- Existing automation-token and notification-intake contracts remain green.

#### Manual Verification

- Restarting Gunicorn with pending notifications causes them to be swept and converted.
- Stopping conversion activity leaves intake operational while health reports the expected degradation.

---

## Phase 4: Compatibility and Acceptance

### Overview

Finish integration cleanup, operator documentation, and end-to-end acceptance without expanding product scope.

### Changes Required

#### 1. API and test-layout cleanup

**File:** automation API URL composition and family-access tests

**Intent:** Resolve debt explicitly deferred to S-05 while preserving public HTTP paths.

**Contract:** Use one namespaced automation API include while retaining `/api/automation/ping/` and `/api/automation/notifications/`. Move automation tests into the established tests package without changing behavior or route names consumed by callers.

#### 2. Operator documentation

**File:** `README.md` and deployment runbook

**Intent:** Document conversion enablement, status inspection, failed-row requeue, retention, restart recovery, and privacy-safe troubleshooting.

**Contract:** Examples use anonymized payloads. Documentation states that intake acknowledgement does not guarantee immediate conversion and explains health states without exposing raw notification data in commands or logs.

#### 3. US-02 acceptance and regressions

**File:** acceptance and integration tests under `entries/tests/`

**Intent:** Prove the complete product outcome and access boundaries.

**Contract:** The PRD example creates a Mateusz calendar entry titled “Sprawdzian: Język angielski”, dated `2026-10-02`, with `source=eduvulcan`. Resubmission under the existing deduplication rules creates no new inbox row or entry. A parent can inspect, correct, and delete the result. An assigned child can read it; another child and unauthenticated user cannot. Unknown formats become general family notes. Sanitized failures contain no notification text, family names, provider response bodies, or tokens.

### Success Criteria

#### Automated Verification

- Focused EduVulcan, classification, access, intake, worker, and health tests pass.
- Full Django tests and system checks pass.
- Migration consistency check reports no missing migrations.
- Existing public automation paths and response bodies remain compatible.

#### Manual Verification

- An anonymized notification sent with a real local automation token is acknowledged immediately and later appears correctly in parent and assigned-child views.
- On PostgreSQL with two Gunicorn workers, concurrent wake-ups and a restart produce no duplicate outputs.
- Operator review confirms logs, admin diagnostics, and health responses contain no family notification text.

## Testing Strategy

### Unit Tests

- Category parsing, date rollover, child resolution, output ordering, partial timetable parsing, fallback conversion, retry classification, and retention scrubbing.
- Model constraints and automated-entry validation.

### Integration Tests

- Intake commit through worker conversion.
- Concurrent claims and crash recovery.
- Classifier fallback using a family snapshot.
- Parent correction/deletion and child-scoped visibility.
- Disabled, healthy, and stale worker health states.

### Manual Testing Steps

1. Submit anonymized examples for each supported category.
2. Verify multi-change fan-out and malformed remainder handling.
3. Restart workers with pending and processing rows.
4. Exercise a transient provider failure and recovery.
5. Verify PostgreSQL concurrency with two Gunicorn workers.
6. Inspect admin, logs, and health output for privacy leaks.

## Performance Considerations

- Intake remains limited to authentication, validation, deduplication, durable storage, and an in-memory wake-up.
- Global conversion concurrency stays at one, matching low MVP volume and protecting classification/provider capacity.
- Sweeps operate on indexed status and scheduling fields with bounded batches.
- Raw fields are scrubbed after 90 days to respect the small database allowance.

## Migration Notes

- Additive schema changes precede worker enablement.
- Deploy migrations with workers disabled, then enable conversion after the new release is healthy.
- Rollback disables workers first. Existing pending rows and output links remain valid for a forward fix.
- Do not reverse migrations automatically after outputs exist.

## References

- `context/foundation/prd.md` — US-02, FR-010, FR-011, automated school rules.
- `context/foundation/roadmap.md` — S-05 sequencing and runtime handoff.
- `context/archive/2026-09-27-automation-token-access/plan.md` — durable intake and worker constraints.

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles.

### Phase 1: Conversion Schema and Domain Rules

#### Automated

- [x] 1.1 Migration and model tests enforce lease, retry, pruning, and output-link constraints. — 94910bf
- [x] 1.2 Fixed-rule tests cover every PRD category, Polish normalization, nearest-year boundaries, newest-ID child ties, missing children, and malformed input. — 94910bf
- [x] 1.3 Multi-change tests produce ordered entries for valid segments plus one unassigned remainder note. — 94910bf
- [x] 1.4 Family-scoped classification tests preserve privacy, active-family scoping, and general-note fallback. — 94910bf

#### Manual

- [ ] 1.5 Review anonymized fixtures against the local sample corpus and confirm that no real names or identifiers remain.
- [ ] 1.6 Review representative Polish entry text for clarity and preservation of notification meaning.

### Phase 2: Atomic Conversion Lifecycle

#### Automated

- [x] 2.1 Concurrent and repeated conversion calls create exactly one entry per output index; deleting an entry and retrying preserves its tombstone and does not recreate it. — 49e3884
- [x] 2.2 A simulated crash before commit leaves no entries or links; the next claim converts successfully. — 49e3884
- [x] 2.3 Retry timing, a three-provider-call maximum, three-attempt exhaustion, stale two-minute leases, fallback, and action-only admin requeue are covered. — 49e3884
- [x] 2.4 Ninety-day pruning uses the agreed empty sentinels while retaining deduplication and provenance behavior. — 49e3884

#### Manual

- [ ] 2.5 In admin, a failed row exposes only sanitized diagnostics and can be requeued.
- [ ] 2.6 A processed row remains traceable to its output metadata after raw fields are pruned.

### Phase 3: Worker and Intake Integration

#### Automated

- [x] 3.1 Intake remains `202`, classification-free, and bounded when enqueueing succeeds, fails, or workers are disabled. — 0d7dc79
- [x] 3.2 Worker tests cover startup sweep, periodic sweep, retry-due selection, advisory-lock refusal, and connection cleanup. — 0d7dc79
- [x] 3.3 Health tests preserve the exact `/healthz/` body and cover disabled conversion, healthy heartbeat, and stale/missing heartbeat on `/healthz/conversion/`; deployment shell tests cover both probes. — 0d7dc79
- [x] 3.4 Existing automation-token and notification-intake contracts remain green. — 0d7dc79

#### Manual

- [ ] 3.5 Restarting Gunicorn with pending notifications causes them to be swept and converted.
- [ ] 3.6 Stopping conversion activity leaves intake operational while health reports the expected degradation.

### Phase 4: Compatibility and Acceptance

#### Automated

- [x] 4.1 Focused EduVulcan, classification, access, intake, worker, and health tests pass. — 1eeeb2c
- [x] 4.2 Full Django tests and system checks pass. — 1eeeb2c
- [x] 4.3 Migration consistency check reports no missing migrations. — 1eeeb2c
- [x] 4.4 Existing public automation paths and response bodies remain compatible. — 1eeeb2c

#### Manual

- [ ] 4.5 An anonymized notification sent with a real local automation token is acknowledged immediately and later appears correctly in parent and assigned-child views.
- [ ] 4.6 On PostgreSQL with two Gunicorn workers, concurrent wake-ups and a restart produce no duplicate outputs.
- [ ] 4.7 Operator review confirms logs, admin diagnostics, and health responses contain no family notification text.
