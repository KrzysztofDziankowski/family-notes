# EduVulcan School Event Intake — Plan Brief

> Full plan: `context/changes/eduvulcan-school-event-intake/plan.md`

## What & Why

Convert durable EduVulcan notifications into family entries without delaying the existing intake request. Known notification types use deterministic rules; unknown formats use privacy-bounded classification and ultimately become general notes so accepted information is not lost.

## Starting Point

Token-authenticated intake already validates, deduplicates, stores `InboundNotification` rows, and returns `202`. Entry CRUD, family scoping, classification, and EduVulcan source markers exist; conversion workers and crash-safe notification-to-entry provenance do not.

## Desired End State

Stored notifications are converted asynchronously into one or more correctly scoped entries. Conversion survives restarts, avoids duplicate outputs, retries transient failures, exposes worker health, and lets parents correct or delete generated entries.

## Key Decisions Made

| Decision | Choice | Why |
| --- | --- | --- |
| Multi-change notices | One entry per valid change | Makes each timetable change independently usable |
| Partial parsing | Valid entries plus one unassigned remainder note | Preserves structured results without losing malformed text |
| Child matching | Newest active child ID wins normalized-name ties | Deterministic owner-selected behavior |
| Yearless dates | Nearest occurrence within ±6 months | Handles December/January boundaries |
| Provenance | Dedicated output tombstones with nullable `SET_NULL` entry links | Supports one-to-many retries without recreating parent-deleted entries |
| Classification | Family-scoped active-child snapshot | Does not depend on the original token owner remaining active |
| Retries | Transient failures only; three attempts and at most three provider calls | Recovers temporary outages with a firm cost and latency cap |
| Retry timing | Initial, ~1 minute, ~5 minutes | Keeps school information timely |
| Stale work | Two-minute processing lease | Recovers promptly after worker death |
| Retention | Raw fields retained for 90 days, then replaced with empty sentinels | Balances troubleshooting with database limits while preserving deduplication |
| Worker outage | Keep accepting; expose a separate conversion-health endpoint | Preserves durable intake and the existing release-gate contract |
| Worker startup | Post-fork versus safe lazy start delegated to implementation | Accepted architectural risk; both must preserve startup sweeps and locking |

## Scope

**In scope:** fixed EduVulcan rules, classifier fallback, one-to-many conversion, atomic provenance, retry/recovery, worker lifecycle, health reporting, 90-day raw-data pruning, anonymized tests, and operational documentation.

**Out of scope:** direct EduVulcan access, external queue infrastructure, token-management changes, other integrations, parent confirmation for automated entries, and new entry-management UI.

## Architecture / Approach

`POST notification → durable inbox row → on-commit wake-up → worker claim/lease → fixed rules → family-scoped classifier → general-note fallback → atomic entries and output links`

The database remains authoritative. In-memory queues only reduce latency; startup and periodic sweeps recover missed signals.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Conversion contracts | Schema, parsing, family-scoped classification | Incorrect parsing or child assignment |
| 2. Atomic lifecycle | Idempotent fan-out, retries, recovery, pruning | Duplicate or partial outputs |
| 3. Worker integration | Queue, sweeps, locking, health | Gunicorn lifecycle and concurrency |
| 4. Acceptance | Compatibility cleanup, docs, US-02 verification | Production configuration drift |

**Prerequisites:** completed S-01, F-02, and F-04; PostgreSQL production database; OpenAI classification configuration for fallback behavior.

**Estimated effort:** approximately 4–6 implementation sessions across four phases.

## Open Risks & Assumptions

- Fixed parsers must be grounded in anonymized derivatives of the gitignored sample corpus; real names and payloads must never enter source control.
- Newest-member-ID tie-breaking is deterministic but may assign information to the wrong sibling when names collide; this is an explicitly accepted product choice.
- PostgreSQL concurrency behavior needs PostgreSQL-aware verification because SQLite does not enforce row locks.
- The existing same-day raw-content deduplication remains authoritative, including its accepted risk of collapsing distinct identical notices.

## Success Criteria (Summary)

- The US-02 example produces the expected dated EduVulcan entry without confirmation.
- Retries, restarts, deletion, and concurrent workers never create or recreate a duplicate output for the same notification segment.
- Intake remains an immediate `202`, and worker failure is visible without losing submitted notifications.
