---
type: observability-audit
date: 2026-10-04 18:03
mode: audit
commit: f8c46f5
branch: master
dirty_tree: true   # uncommitted fix for the edit/delete 500 (services.py, settings.py django.request logger)
areas: [entry-management, eduvulcan-conversion, plumbing]
area_source: user
runtime_proof: partial   # full test suite run on PostgreSQL 16; no fake-ingest probes (there is no error tracker)
error_tracker: none (gunicorn stderr -> systemd journal)
previous_report: null
findings: { critical: 3, high: 7, medium: 5, low: 1 }
---

# Observability audit — entry management, EduVulcan conversion, plumbing (2026-10-04)

## 1. TL;DR

- **Only two app loggers had a handler.** Everything else, including Django's own
  `django.request` (500s) and `django.security.*`, printed nothing in production, or
  fell through to Python's last-resort handler as a bare message with no level or
  logger name. Today's edit 500 left only an access-log line because of this.
- **"Class name only" is the house style for privacy.** Every caught failure logs
  `error=<ClassName>` and nothing else: no stack, no SQLSTATE. That keeps notification
  text out of logs, but it also makes every caught failure undiagnosable. Two branches
  (`OperationalError`, `DatabaseError` in conversion) don't even log the class.
- **Fallbacks remove the signal.** A rules crash becomes a general note, a service
  `ValidationError` becomes a generic "save failed" form, and a health DB error
  becomes `unavailable`. Each is graceful for users and silent for the responder.
- **Tests and the quality gate run only on SQLite.** PostgreSQL-only behavior (row
  locks, `varchar` limits, NUL bytes, advisory locks, aborted transactions) is never
  exercised before a deploy. That is how the `FOR UPDATE` + nullable join bug shipped.
- **Biggest consequence:** a Postgres-only error inside EduVulcan conversion would
  mark the notification `failed` with `code=database_error` and nothing else. That
  means no class, no stack, and no way to tell a lock bug from a disk-full error.

## 2. Capture model

- **Runtime:** Django 5.2 under gunicorn (2 sync workers, systemd unit `family-notes`,
  see `context/changes/deployment/mikrus-runbook.md`). The EduVulcan conversion worker
  is a thread inside each gunicorn worker, started in `gunicorn.conf.py:15`.
- **Error tracker:** none (in repo).
- **Logging:** `family_notes/settings.py:386` defines one `StreamHandler` (stderr, no
  formatter). Before this audit, only `entries.eduvulcan` and `entries.classification`
  used it. Django's `DEFAULT_LOGGING` routes `django.*` to a console handler gated by
  `require_debug_true`, so with `DEBUG=False` nothing from Django is printed. Loggers
  without a handler (`family_access.automation`, `family_notes.auth_security`) hit
  `logging.lastResort`: WARNING+ only, bare message.
- **Scrubbing:** by convention, not by code. Call sites log `type(exc).__name__`
  instead of the exception (`entries/eduvulcan/conversion.py:270` explains why: messages
  may quote notification text).
- **Deploy identity:** `FAMILY_NOTES_RELEASE_ID` exists (`settings.py`) but is not in
  log lines.

**Assumptions (outside the repo, not findings):**
- gunicorn stderr is captured by journald for the `family-notes` unit (confirmed by
  the user: access-log lines show up in `journalctl -u family-notes`).
- Nobody is alerted on journal lines (unconfirmed; there is no alerting in the repo).

## 3. What reaches the logs (static, verified by reading code; Postgres behavior observed via the test suite)

| Failure shape | Response | journald (before) | Verdict |
|---|---|---|---|
| Unhandled exception in a view | 500 | access line only | **missed** (fixed in working tree) |
| Postgres-only DB error in edit/delete | 500 | access line only | **missed** (fixed in working tree) |
| `DatabaseError` during conversion | n/a (worker) | `code=database_error`, no class | **poor** |
| Unexpected exception during conversion | n/a | `error=RuntimeError`, no stack | **poor** |
| Exception in EduVulcan rules | n/a, falls back to note | class only | **poor** |
| Worker loop exception | n/a | class only, every tick | **poor** |
| Auth cache DB failure | 503 | `authentication_cache_unavailable` (bare, no level) | **poor** |
| `/healthz/` DB failure | 503 | nothing | **missed** |
| CSRF failure / DisallowedHost | 403 / 400 | nothing | **missed** |
| Service-level `ValidationError` on save | 200, form error | nothing | **missed** |

## 4. Systemic root causes

1. **No handler for anything except two app loggers** (`family_notes/settings.py:386-407`).
   Django's defaults print only with `DEBUG`, and other loggers fall to `lastResort`.
   Explains P1, P2, A1, A2.
2. **No content-free way to log a stack.** The privacy rule ("never log the message")
   was implemented as "log only the class name", which also discards the stack and the
   DB error code (SQLSTATE). Explains E1–E5, P5, A1.
3. **Graceful fallbacks without their own signal** (`entries/views.py:210,505,544`,
   `entries/eduvulcan/conversion.py:336`, `entries/eduvulcan/health.py:105`,
   `family_notes/views.py:27`). Explains M2, E3, E7, A2.
4. **SQLite-only test gate** (`scripts/hooks/quality_gate.py:138` runs
   `manage.py test` with the default `DB_ENGINE=sqlite`). Explains M1 and is a standing
   risk for every Postgres-specific code path.

## 5. Findings by area

### Entry management (parent create/edit/delete)

| # | Location | Category | Severity | What happens in production | Fix direction |
|---|---|---|---|---|---|
| M1 | `entries/services.py:218,240` | coverage-gap (DB divergence) | critical | `select_for_update()` on a queryset with `select_related('assigned_member')` → Postgres `NotSupportedError`. Every edit and delete returned 500; no traceback. | **Fixed in working tree:** the lock query has no join. |
| M2 | `entries/views.py:210,505,544` | flattened-response | medium | Service rejects a form-valid save → user sees "save failed", 200, nothing logged. A form/service rule drift would be invisible. | Log a warning with a content-free stack (which check fired). |

### EduVulcan conversion (intake → worker → entries)

| # | Location | Category | Severity | What happens in production | Fix direction |
|---|---|---|---|---|---|
| E1 | `entries/eduvulcan/conversion.py:265-268` | identity-lost | critical | `OperationalError`/`DatabaseError` → row retried or `failed` with `code=database_error`; log has no class, no SQLSTATE, no stack. A Postgres-only bug is indistinguishable from an outage. | Log class + SQLSTATE + stack frames. |
| E2 | `entries/eduvulcan/conversion.py:269-273` | identity-lost | high | Any bug in conversion → `failed`, `error=RuntimeError`; no location. | Same helper. |
| E3 | `entries/eduvulcan/conversion.py:336` | identity-lost | high | Rules crash → silently becomes a general note; log has class only. A rules regression degrades every notification without a findable cause. | Same helper. |
| E4 | `entries/eduvulcan/worker.py:246` | identity-lost | high | Loop crash repeats every tick as `error=X`; no stack. | Same helper. |
| E5 | `entries/eduvulcan/worker.py:381,400` | identity-lost | medium | Wake-up failure → class only (the sweep recovers, so it's latency only). | Same helper. |
| E6 | `entries/eduvulcan/worker.py:108` | swallowed | low | Advisory-unlock failure is silent (the connection close does release the lock). | Log a warning. |
| E7 | `entries/eduvulcan/health.py:105` | swallowed | medium | DB error → `unavailable`, same as a stale heartbeat; nothing logged. | Log a warning with the summary. |

Intake (`entries/api_views.py`) was checked and is fine: 4xx answers are deliberate
input rejections, and the `IntegrityError` race re-raises when it can't resolve.

### Platform / plumbing

| # | Location | Category | Severity | What happens in production | Fix direction |
|---|---|---|---|---|---|
| P1 | `family_notes/settings.py:386` | coverage-gap | critical | Unhandled view exceptions are never printed (`django.request` has no prod handler). | **Fixed in working tree:** `django.request` ERROR → console. |
| P2 | `family_notes/settings.py:386` | coverage-gap | high | `django.security.*` (CSRF, DisallowedHost, SuspiciousOperation) is never printed; `family_access.*`/`family_notes.*` warnings print bare via `lastResort`; their INFO is dropped. | Root logger → console at WARNING. |
| P3 | (no helper anywhere) | identity-lost | high | See root cause 2. | `family_notes/log_safety.py`: class + SQLSTATE + frames, never the message. |
| P4 | `family_notes/settings.py:390` | missing-context | medium | Lines carry no level or logger name, so `journalctl -p err` and grepping by module don't work. | Add a formatter. |
| P5 | `gunicorn.conf.py:22,31` | identity-lost | medium | Worker start failure → class only; conversion silently off until health shows it. | Same helper. |
| A1 | `family_notes/auth_security.py:29` | identity-lost | high | Login 503s log `authentication_cache_unavailable` with no cause (`auth_cache.py:34` raises `from None`). | Log the suppressed context's summary. |
| A2 | `family_notes/views.py:27` | swallowed | medium | `/healthz/` 503 with no cause logged. | Log a warning with the summary. |
| D1 | `scripts/hooks/quality_gate.py:138` | coverage-gap (DB divergence) | high | No Postgres run before release; M1 shipped this way. | Add a Postgres test run (release gate or CI). |

### SQLite vs PostgreSQL sweep

Ran the full suite (743 tests) against PostgreSQL 16 in Docker. After the M1 fix the
only failure is `test_non_postgresql_lock_is_always_acquired`, which is SQLite-only by
design. Checked by hand:

- **Other `select_for_update` calls** (`conversion.py:174,367`): no joins, so safe.
- **`varchar` length:** Postgres enforces it, SQLite doesn't. Intake validates `title`
  and `notification_id` (`api_views.py:30`); the other short columns are code-set enums
  or hashes.
- **NUL bytes:** rejected at intake (`api_views.py:65`).
- **NULL ordering:** the listing uses explicit `nulls_last` (`listing.py:92,102`).
- **`IntegrityError` inside a transaction:** wrapped in its own `atomic()` savepoint
  (`api_views.py:117`, `services.py:52`).
- **Advisory locks:** vendor-gated (`worker.py:95`), but only tested on Postgres.

No other latent divergence was found in tested paths. Untested paths remain unknown
until D1 is addressed.

## 6. Recommended fix order

1. **P1 + P2 + P4 (settings only):** every Django and app warning/error reaches
   journald with level and logger name. Constraint: keep `entries.classification`
   propagating (privacy tests capture at root) without printing twice.
2. **P3 helper, then E1–E5, E7, P5, A1, A2, M2:** one content-free summary everywhere a
   failure is caught. Constraint: never include `str(exc)` or `exc.args`; existing tests
   assert the `error=<Class>` substring, so keep that prefix.
3. **D1:** run the suite on Postgres before release. This needs a Postgres instance
   on the release host or in CI, so it is a separate change.
4. **E6:** a one-line warning.

## 8. Method and limits

- Single-agent audit: the codebase has 54 `except` sites, so I read all of them
  directly instead of fanning out subagents. The classification flow
  (`openai_backend.py:236`) already logs one content-free line per provider call with
  outcome, status and request id. It was judged adequate and not re-audited in depth.
- Runtime: the full test suite was run on PostgreSQL 16
  (`docker run postgres:16`, `DB_ENGINE=postgresql`). No fake-ingest probes, since
  there is no tracker.
- Not verifiable: how journald renders multi-line tracebacks on the Mikrus host.
