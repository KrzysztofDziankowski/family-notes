<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: EduVulcan School Event Intake

- **Plan**: context/changes/eduvulcan-school-event-intake/plan.md
- **Scope**: Full plan (automated rows complete; manual rows pending)
- **Reviewed phases**: 1, 2, 3, 4
- **Date**: 2026-09-28
- **Verdict**: NEEDS ATTENTION
- **Findings**: 0 critical, 4 warnings, 6 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | WARNING |
| Scope Discipline | PASS |
| Safety & Quality | WARNING |
| Architecture | PASS |
| Pattern Consistency | PASS |
| Success Criteria | PASS |

Automated criteria were re-run on 2026-09-28:
- `manage.py test`: 545 tests OK (3 skipped).
- `manage.py check`: no issues.
- `makemigrations --check --dry-run`: no changes.
- The 4 deployment shell tests: PASS.

Manual rows 1.5, 1.6, 2.5, 2.6, 3.5, 3.6 and 4.5–4.7 are pending. None of them is marked complete.

## Findings

### F1 — Code rollback after migration 0003 breaks intake

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Safety & Quality
- **Location**: entries/migrations/0003_notification_conversion.py:32-37; scripts/deployment/family-notes-deploy:155
- **Detail**:
  - Migration 0003 adds `attempt_count` and `last_error_code` as NOT NULL columns. Django drops the default at the database level, and there is no `db_default`.
  - `family-notes-deploy rollback` switches the release symlink but never unapplies migrations.
  - Once rolled back, the previous release's intake does `objects.create()` without these columns. On PostgreSQL that is a NOT NULL violation, so every notification POST returns 500 and the notification is lost.
- **Fix A ⭐ Recommended**: Add a new migration that sets `db_default=0` on `attempt_count` and `db_default=''` on `last_error_code`.
  - Strength: rollback to the previous code becomes safe with no operator steps, and the change is additive.
  - Tradeoff: one more migration, and the models declare both `default` and `db_default`.
  - Confidence: HIGH — Django 5.2 supports `db_default` on PostgreSQL and SQLite.
  - Blind spot: other new nullable or check-constrained columns have not been re-checked against old-code inserts. They are nullable, so they are probably fine.
- **Fix B**: Document in the runbook that a rollback past this release needs `migrate entries 0002` first.
  - Strength: no code change.
  - Tradeoff: destructive. It drops lifecycle and output-link data, and the step relies on the operator remembering it.
  - Confidence: MED.
  - Blind spot: pruned rows stay scrubbed after the reverse migration.
- **Decision**: FIXED (Fix A)

### F2 — Shared heartbeat can report `ok` when no current worker is converting

- **Severity**: ⚠️ WARNING
- **Impact**: 🔬 HIGH — architectural stakes; think carefully before deciding
- **Dimension**: Safety & Quality
- **Location**: entries/eduvulcan/health.py:38-68; entries/eduvulcan/worker.py (heartbeat is written before the lock attempt)
- **Detail**:
  - All processes upsert one heartbeat row, and health is `ok` if that row is younger than 180 s.
  - After a deploy restart, the previous release's heartbeat stays fresh for up to 180 s. This hides new workers that never started, for example because the systemd unit lacks `--config gunicorn.conf.py`.
  - A process whose thread died is also masked by the other process's heartbeats.
  - A process that never holds the lock still writes heartbeats, so `ok` means "a thread is alive", not "conversion is making progress".
- **Fix A ⭐ Recommended**: Key heartbeats per process (hostname + pid) and store the release id. Health then requires a fresh heartbeat from the current release.
  - Strength: detects the deploy-time failure that matters most, where the new release starts no workers.
  - Tradeoff: needs a schema change, cleanup of old heartbeat rows, and more health logic.
  - Confidence: MED — needs a reliable release id at runtime.
  - Blind spot: how the release id is exposed to the process has not been verified.
- **Fix B**: Keep the design, and document in the runbook that operators wait longer than max-age (180 s) after a deploy before trusting `conversion-health`.
  - Strength: zero code.
  - Tradeoff: a process with a dead thread stays masked.
  - Confidence: HIGH.
  - Blind spot: none significant.
- **Decision**: FIXED (Fix A)

### F3 — Lease duration is not validated against the classification deadline

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: family_notes/settings.py (validate_eduvulcan_worker_settings)
- **Detail**:
  - If `EDUVULCAN_CONVERSION_LEASE_SECONDS` ≤ `CLASSIFICATION_DEADLINE_SECONDS`, slow classifications lose their lease.
  - The result is paid-for provider calls thrown away and rows ending `failed/lease_expired`.
  - The defaults (120 s vs 25 s) are safe.
- **Fix**: At startup, fail closed unless the lease exceeds the classification deadline plus a margin.
- **Decision**: FIXED

### F4 — README duplicates an operator block and misdescribes pruned rows

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Adherence
- **Location**: README.md:273-324
- **Detail**:
  - The block from "Neither health check returns…" through the troubleshooting section appears twice (lines 221-272 and 273-324).
  - The second copy says admin shows "`[pruned]`-style placeholders", but the real admin label is "Raw data pruned".
- **Fix**: Delete the duplicate block at lines 273-324.
- **Decision**: FIXED

### F5 — Admin inbox still allows deleting notifications

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: entries/admin.py:76-84
- **Detail**:
  - The docstring says "Read-only inbox", but `has_delete_permission` is not overridden, so a superuser can still delete rows.
  - Deleting a row cascades away its output tombstones and dedup keys.
  - A re-forwarded copy would then be accepted as new and would recreate entries a parent had deleted.
- **Fix**: Return False from `has_delete_permission`, as `ConversionOutputInline` already does.
- **Decision**: FIXED

### F6 — Unexpected exceptions fail rows permanently with no diagnostic hint

- **Severity**: 💡 OBSERVATION
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Safety & Quality
- **Location**: entries/eduvulcan/conversion.py:269-270
- **Detail**:
  - `except Exception` records `conversion_error` as non-retryable and does not log the exception class.
  - A rules bug on one notification shape would mark every such row `failed`.
  - The classifier and general-note fallback would never be tried, and operators would get no clue to the cause.
- **Fix A ⭐ Recommended**: Log `type(exc).__name__`. Also catch unexpected errors from rule parsing and fall through to classification and the general note, as already happens for `ValidationError`.
  - Strength: no information is lost, which matches the plan's "accepted information is not lost" goal.
  - Tradeoff: a real bug may hide behind general notes. The log line still surfaces it.
  - Confidence: MED.
  - Blind spot: the exact boundary of the rule-parsing call has not been checked.
- **Fix B**: Only add the exception class name to the log line.
  - Strength: one-line change.
  - Tradeoff: rows still fail on parser bugs and need a requeue after the fix.
  - Confidence: HIGH.
  - Blind spot: none significant.
- **Decision**: FIXED (Fix A)

### F7 — INFO-level worker logs are dropped in production

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: family_notes/settings.py (no LOGGING setting)
- **Detail**: Sweep, processed, retry, requeue and prune events are logged at INFO. Without a LOGGING configuration only WARNING and above reach journald, so the operational trail is invisible.
- **Fix**: Add a minimal LOGGING configuration that sends the `entries.eduvulcan` logger at INFO to the console. The fields it logs are already privacy-safe.
- **Decision**: FIXED

### F8 — Automation route names changed to namespaced names

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Adherence
- **Location**: family_access/api_urls.py:6; entries/api_urls.py:6
- **Detail**:
  - The plan says the change happens "without changing … route names consumed by callers".
  - `automation_ping` became `automation:ping` and `automation_notification_submit` became `automation:notification_submit`.
  - Only tests used the old names, and the public paths are unchanged.
- **Fix**: Record the accepted rename in the Notes section of change.md.
- **Decision**: FIXED

### F9 — Notifications for an inactive family still create entries

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: entries/services.py (create_automated_entry); entries/eduvulcan/conversion.py:274-278
- **Detail**: For an inactive family the child snapshot is empty, but conversion still saves unassigned entries. The entries stay scoped to the correct family, so nothing leaks between families.
- **Fix**: Confirm this is intended. If not, fail those rows with a safe code such as `family_inactive`.
- **Decision**: ACCEPTED — intended: entries of a deactivated family stay scoped to that family

### F10 — Processed rows keep a stale `last_error_code`

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: entries/eduvulcan/conversion.py:378-379
- **Detail**: A row that timed out on attempt 1 and succeeded on attempt 2 shows `processed` with `last_error_code=provider_timeout` in admin.
- **Fix**: Document in the README status table that the code is historical, or clear it on a clean success.
- **Decision**: FIXED
