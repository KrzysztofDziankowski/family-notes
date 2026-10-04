---
date: 2026-10-04T08:53:50+02:00
researcher: Claude Code (claude-opus-5-5)
git_commit: b6120573b27e10f05f34c3299ddc746772eb37cb
branch: master
repository: 10xdev
topic: "Ground Risk #4 of test-plan.md: accepted EduVulcan notification lost, converted twice, or unprocessed after interruption"
tags: [research, eduvulcan, intake, conversion-worker, idempotency, durability, postgresql]
status: complete
last_updated: 2026-10-04
last_updated_by: Claude Code (claude-opus-5-5)
---

# Research: Risk #4 — EduVulcan intake durability and idempotency

**Date**: 2026-10-04T08:53:50+02:00
**Researcher**: Claude Code (claude-opus-5-5)
**Git Commit**: b6120573b27e10f05f34c3299ddc746772eb37cb (working tree: only `context/foundation/roadmap.md` modified; no inspected source file is uncommitted)
**Branch**: master
**Repository**: 10xdev

## Research Question

Ground Risk #4 of `context/foundation/test-plan.md` (§2 Risk Map): "An accepted
EduVulcan notification is lost, converted twice, or remains unprocessed after
interruption". The Risk Response Guidance asks for proof that acknowledged input
survives interruption, resumes safely and that repeated delivery produces one
intended result; it must challenge "HTTP 202 or eventual success alone proves
durable processing"; the cheapest layer is database-backed integration tests; the
anti-pattern is over-mocked worker tests. Where does the failure live, what do
existing tests already prove, and what remains unproven?

## Summary

The implementation already contains a deliberate durability design. The open
question is whether that design has been *proven*, not whether it needs to be
written:

- **Lost after ack — not on the inspected path.** `submit_notification` returns
  202 at `entries/api_views.py:138`, after the insert's `transaction.atomic()`
  block (`:115-127`) has exited. `ATOMIC_REQUESTS` is not set, so that block is
  the outermost transaction (a worker's grep found no setting in the repo). The
  worker wake-up is a post-commit `on_commit(..., robust=True)` that never raises
  (`entries/eduvulcan/worker.py:389-404`). A lost wake-up costs latency only,
  because startup and 60 s sweeps reselect due rows (`worker.py:278-291`,
  `entries/eduvulcan/conversion.py:137-157`).
- **Converted twice — fenced at three levels.**
  1. Intake dedupe by DB unique constraints on `(family, notification_id)` and
     `(family, content_hash, captured_date)` (`entries/models.py:150-157`).
  2. A claim per attempt via `select_for_update`, plus a conditional update
     guarded on `(status, attempt_count)` (`conversion.py:160-208`).
  3. Persistence of all entries, output links and `status=processed` in one
     transaction. That transaction re-checks lease ownership before and after
     writing (`conversion.py:352-417`) and skips `output_index` values that
     already exist, including tombstones (`conversion.py:369-376`;
     `models.py:187-231`).
- **Unprocessed after interruption — recovery exists, but detection is weak.**
  An expired lease makes a `processing` row due again (`conversion.py:139-141`).
  Retries are bounded at 3 attempts with 60 s/300 s delays
  (`conversion.py:53-56`). `failed` is terminal until an operator requeue
  (`conversion.py:470-486`). `/healthz/conversion/` reports only whether some
  current-release heartbeat is fresh (`entries/eduvulcan/health.py:95-107`). That
  heartbeat is written before the conversion lock is attempted
  (`worker.py:240` vs `:259`). No inspected code reports backlog age or the
  number of `failed` rows.
- **Test evidence.** Eight test files contain 159 `test_` methods. The files are
  `entries/tests/test_{notification_intake,conversion_lifecycle,conversion_worker,eduvulcan_acceptance,conversion_health,conversion_models,conversion_retention,conversion_admin}.py`.
  Most use `TestCase`, and a few thread/startup classes use `SimpleTestCase`.
  They cover the single-process functional contract with real services, faking
  only the classifier backend, the clock or an injected crash. The overall approach is not over-mocked; the
  one exception is `WorkerThreadTests`, which patches `run_once` out
  (`entries/tests/test_conversion_worker.py:374`). Every test runs on SQLite (the
  `DB_ENGINE` default, `family_notes/settings.py:229-237`), where
  `select_for_update` is a no-op and the advisory lock always counts as acquired
  (`worker.py:95-96`). Nothing yet proves cross-process behaviour on PostgreSQL;
  manual row 4.6 for exactly that is still unchecked
  (`context/changes/eduvulcan-school-event-intake/plan.md:373`).

So "HTTP 202" here does mean "durably stored". It does **not** mean "will be
converted": that additionally needs a running worker with an available database
and a non-`failed` row. The guidance's challenge therefore holds.

## Detailed Findings

### 1. Intake (acknowledgement side)

- Route `POST /api/automation/notifications/` → `submit_notification`
  (`entries/api_views.py:88-138`). Auth is a bearer automation token
  (`family_access/automation.py:62-75`). The family is taken only from the token.
- Response codes on this path:
  - 413: body over 16 KiB.
  - 400: invalid payload.
  - 401: invalid token.
  - 202 `{"status":"accepted","id":pk}`: for both a new row and a duplicate
    (`:138`). There is no 200 path.
  - Unhandled 500: an `IntegrityError` whose re-query finds no row re-raises
    (`:136-137`); other `DatabaseError`s are not caught.
- Dedupe happens in two places:
  - An application pre-check, `Q(notification_id) | Q(content_hash,
    captured_date)` within the family (`:106-112`).
  - The DB constraints (`models.py:150-157`).
  - A concurrent loser catches `IntegrityError` and answers with the winner's pk
    (`:128-135`).
- The content hash is SHA-256 of NFC-normalized, whitespace-collapsed
  `title\nmessage` (`api_views.py:33-40`). `captured_date` is the
  Europe/Warsaw local date (`:104`).
- **Duplicate of a `failed` row**: the pre-check returns the existing row and
  responds 202 without changing its status (`api_views.py:113-138`). That
  resubmission therefore never revives the notification; only
  `requeue_failed_notifications` does (`conversion.py:470-486`). This is
  consistent with the "terminal until requeue" docstring (`models.py:89-93`).
- **Same id, different content**: on this inspected path, the newer content is
  discarded and no log line is written (`api_views.py:106-113`). FR-011 asks for
  this outcome.

### 2. Conversion lifecycle (`entries/eduvulcan/conversion.py`)

- Due rows are `pending` with a due-or-null `next_attempt_at`, plus `processing`
  rows with an expired lease, in pk order (`:137-157`).
- Claim (`:160-208`):
  - Locks the row (`select_for_update`, `:174`).
  - When `attempt_count >= max_attempts` it marks the row `failed` with
    `lease_expired` (if it was processing) or `attempts_exhausted`
    (`:184-198`).
  - Otherwise it increments `attempt_count`, sets a lease of
    `EDUVULCAN_CONVERSION_LEASE_SECONDS` (default 120), and returns the
    `Claim(attempt, lease_expires_at)` fencing token (`:199-208`).
- Persist (`:352-417`):
  - Runs as one `transaction.atomic()`.
  - Locks the owned row (`:367`) and raises `_LeaseLost` when it is not owned.
  - Skips existing output indexes (`:369-376`).
  - Conditionally sets `processed`; a zero-row update also raises
    `_LeaseLost` (`:400-401`).
- Failure handling (`process_claim`, `:251-273`; `_record_failure`,
  `:420-454`):
  - `OperationalError` is retryable.
  - Other `DatabaseError`s and unexpected exceptions fail the row.
  - A retryable provider failure is retried while `attempt < max_attempts`
    (`:297-301`). After that it falls back to a general note (`:318-322`).
- The classifier call happens outside any transaction while the lease is held
  (`:289-295`). Startup refuses a lease shorter than the classification deadline
  (default 25 s) plus 30 s (`family_notes/settings.py:95-99`, `:311`), so a
  healthy slow call cannot outlive its lease.

### 3. Worker process (`entries/eduvulcan/worker.py`, `gunicorn.conf.py`)

- One daemon thread runs per Gunicorn process. It is started only in
  `post_worker_init` (`gunicorn.conf.py:15-23`). Production runs `--workers 2`
  under systemd with `Restart=on-failure` (`context/changes/deployment/mikrus-runbook.md:445-447`).
- On PostgreSQL a session-level `pg_try_advisory_lock` serializes conversion
  batches (`worker.py:90-121`, `:253-276`). A refused process retries after 5 s
  (`:70`, `:260-271`). One batch can hold the lock for up to 50 rows
  (`conversion.py:58`); no inspected document states that duration.
- `run_once` never raises (`worker.py:231-251`), so the thread survives database
  outages. A graceful `stop()` leaves an in-flight lease to expire rather than
  releasing it (`:160-164`), so a restart during conversion consumes one attempt
  of the 3.
- The worker is disabled by default (`EDUVULCAN_WORKER_ENABLED`,
  `settings.py:333`). In that case rows stay `pending` and are not lost.

### 4. Existing test coverage, mapped to the risk

| Concern | Proven by (all `django.test.TestCase` on SQLite unless noted) | Not proven |
|---|---|---|
| Persist before ack | `test_notification_intake.py:52`, `:65`; wake-up failures still 202 + row stored `test_conversion_worker.py:517`, `:531`, `:543` | Commit-before-202 under a real transaction boundary (`TestCase` wraps everything in one transaction; `captureOnCommitCallbacks` simulates commit) |
| Duplicate by id | `test_notification_intake.py:79`; acceptance `test_eduvulcan_acceptance.py:138` | Direct `IntegrityError` assertion for each intake constraint |
| Duplicate by content, new id | `test_notification_intake.py:96`; next day creates a new row `:109` | — |
| Concurrent duplicates | `test_notification_intake.py:127` (sequential simulation via mocked lookup) | Two real connections inserting concurrently |
| Repeated conversion | `test_conversion_lifecycle.py:265`, `:277`; tombstone `:290`; duplicate intake doesn't reset lease `test_conversion_worker.py:562` | — |
| Crash / lease recovery | crash before commit `test_conversion_lifecycle.py:305`; stale reclaim `:116`; stale exhausted → failed `:145`; lease fencing `:174`, `:194`, `:206`; startup sweep `test_conversion_worker.py:101`, `:133` | Real thread death + another process recovering; process recycled while holding the advisory lock |
| Retry / terminal failure | `test_conversion_lifecycle.py:434-586` (RetryPolicyTests, RequeueServiceTests) | Duplicate submission of a `failed` row stays failed |
| Cross-process locking | advisory lock refusal simulated `test_conversion_worker.py:253`; SQL strings only `:285` | Real `select_for_update` contention and advisory lock on PostgreSQL (both module docstrings say so: `test_conversion_lifecycle.py:1-7`) |
| Stuck-queue detection | heartbeat freshness `test_conversion_health.py:80-135` | Health while rows age in `pending`/`failed`; one of two processes dead |

Anchors in the table come from a coverage worker. I re-checked these:
`test_conversion_lifecycle.py:109, 116, 145, 174, 194, 206, 265, 290, 305`,
`test_notification_intake.py:109, 127`, and `test_conversion_worker.py:374, 562`.

## Code References

- `entries/api_views.py:88-138` — intake view; atomic insert `:115-127`, race fallback `:128-137`, 202 `:138`
- `entries/models.py:88-172` — `InboundNotification`, unique + CHECK constraints `:150-171`
- `entries/models.py:187-231` — `NotificationConversionOutput`, unique `(notification, output_index)` `:223-226`
- `entries/eduvulcan/conversion.py:160-208` — claim with fencing token
- `entries/eduvulcan/conversion.py:352-417` — all-or-nothing persist with lease re-check
- `entries/eduvulcan/conversion.py:470-486` — operator requeue
- `entries/eduvulcan/worker.py:231-276` — loop, lock, sweep; `:389-404` post-commit wake-up
- `entries/eduvulcan/health.py:95-107` — health = any fresh current-release heartbeat
- `gunicorn.conf.py:15-32` — worker start/stop hooks
- `family_notes/settings.py:95-99`, `:229-237`, `:333-350` — lease guard, SQLite default, worker settings

## Architecture Insights

- The DB row is the queue. The in-memory queue only carries wake-ups. This is why
  database-backed integration tests are the right layer: almost every guarantee
  is a DB predicate (conditional update, constraint, transaction). Mocking the DB
  would remove the thing under test.
- Two guarantees rely on PostgreSQL semantics that the SQLite suite cannot
  reach: row locking at claim/persist, and the session advisory lock. The
  conditional-update guard (`conversion.py:181-183`, `:211-219`) is
  vendor-neutral and is what makes the SQLite tests meaningful for single-writer
  ordering.
- Test seams that already exist and can be reused: an explicit `now=` on every
  conversion function; `ConversionWorker(monotonic=..., backend=...)` and
  `run_once` (`worker.py:132-151`, `:231`); `SimulatedCrash(BaseException)`
  (`test_conversion_lifecycle.py:52`).

## Historical Context (from prior changes)

- `context/archive/2026-09-27-automation-token-access/reviews/plan-review.md:27-45`
  — F1: id-only dedupe catches no real duplicates; the content hash was chosen.
  Accepted trade-off: "Two genuinely identical texts on the same day are stored
  once" (`:41`). **Verdict: supported** by `models.py:154-157`.
- `context/changes/eduvulcan-school-event-intake/plan-brief.md:64` — the same-day
  raw-content dedupe "remains authoritative, including its accepted risk of
  collapsing distinct identical notices". **Verdict: supported.**
  `plan.md:38` excludes changes to the dedupe definition.
- `context/changes/eduvulcan-school-event-intake/change.md:16` — the owner
  verified manual rows on SQLite with `--workers 1` and deliberately skipped 3.6
  (health degradation), 4.6 (PostgreSQL two-worker concurrency) and 4.7 (privacy
  review). With `--workers 2` on SQLite they saw `database_busy` retries.
  **Verdict: supported**: rows 3.6, 4.6 and 4.7 are unchecked at
  `plan.md:359`, `:373`, `:374`.
- `context/changes/deployment/mikrus-runbook.md:1108` — "An application rollback
  disables the worker first". **Verdict: partial.** The intent is documented, but
  the §11 rollback steps (`:1112-1131`) and the helper's `rollback`
  (`scripts/deployment/family-notes-deploy:155-160`) only switch the symlink and
  restart. This is a deployment-procedure gap, not a test target for this change.
- `context/changes/deployment/deployment-plan.md:44` ("does not introduce
  background workers") — **Verdict: contradicted** by the S-05 in-process
  worker. This is stale documentation and does not affect correctness.

## Related Research

- `context/changes/testing-production-security-schema-safety/research.md` —
  Phase 1 found the same SQLite-only gap and left "which PostgreSQL harness will
  own … disposable" databases as open question 2 (`:282`). Risk #4's concurrency
  proof needs the same harness.

## Open Questions

1. **PostgreSQL harness (shared with Phase 1).** Real concurrent-claim and
   advisory-lock tests need a disposable PostgreSQL instance, for example
   `DB_ENGINE=postgresql` with a `TransactionTestCase` and two threads or
   connections. Is it created once for Phases 1 and 2, or is manual row 4.6
   accepted as the proof? This is a planning decision.
2. **FR-011 wording vs the accepted dedupe key.** FR-011 says "same title,
   message, and child" with no time window (`context/foundation/prd.md:116`).
   The implemented key adds `captured_date` and has no separate child field
   (`models.py:154-157`).
   - Consequence: identical content resent on the next local day creates a
     second row and second entry. This is tested as intended at
     `test_notification_intake.py:109`.
   - Inference, not verified against captured samples: the child is matched by
     name from the message text, so "same child" is normally implied by "same
     message".
   - Tests should assert the accepted design (plan-brief.md:64), not the PRD
     wording, unless the owner reopens it.
3. **Is "remains unprocessed" a test target or a monitoring target?** The test
   plan routes provider outages to health monitoring (§2). The deterministic
   facts below can be tested cheaply, but whether to add a backlog/failed signal
   is a product/ops choice outside Lesson-2 scope:
   - a duplicate of a `failed` row stays `failed`;
   - health stays `ok` while the queue does not move;
   - a restart during conversion consumes an attempt.
4. **Commit-before-ack proof.** A `TransactionTestCase` would close the gap left
   by `TestCase` wrapping. It needs a hit through the test client and then
   reading the row from a fresh connection or thread. The open choice is whether
   that test belongs in this change's SQLite suite or in the PostgreSQL harness.
