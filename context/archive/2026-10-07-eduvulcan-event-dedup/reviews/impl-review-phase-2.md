<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: EduVulcan Event Deduplication and Exam Merge

- **Plan**: context/changes/eduvulcan-event-dedup/plan.md
- **Scope**: Phase 2 of 2
- **Reviewed phases**: 2
- **Date**: 2026-10-07
- **Verdict**: NEEDS ATTENTION
- **Findings**: 0 critical, 2 warnings, 4 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | PASS |
| Scope Discipline | PASS |
| Safety & Quality | WARNING |
| Architecture | PASS |
| Pattern Consistency | WARNING |
| Success Criteria | PASS |

Success criteria: `test_conversion_dedup` 11 OK (break-check: red with matching disabled); full suite 1477 OK; `makemigrations --check` and `check` clean. Manual items 2.5–2.7 pending (unchecked, not rubber-stamped). All three planned changes MATCH; the family lock is taken only when rule proposals are pending (documented adaptation). Context: production conversion is already serialized by the worker's global advisory lock (`entries/eduvulcan/worker.py`), so the family lock is defense-in-depth; remaining races are worker vs. web requests.

## Findings

### F1 — Upgrade validation failure falls through to classification and creates a second entry

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Safety & Quality
- **Location**: entries/eduvulcan/conversion.py:356-362, :297-300 (`_try_persist` / `_convert`), `_apply`
- **Detail**: If `upgrade_automated_exam_entry` raises `ValidationError`, the whole persist rolls back, `_try_persist` returns `None`, and `_convert` calls `classify_for_family` (paid provider call). Classification proposals are not deduplicated, so the event that should have merged becomes a second entry. The same rollback also discards sibling proposals' duplicate/merged decisions. Unlikely with today's validators, but silent.
- **Fix**: In `_apply`, catch `ValidationError` from the upgrade, log the class name with the notification id, and record `MERGED` without upgrading; add a test that patches the upgrade to raise and asserts no new entry and no backend call.
  - Strength: The event is still represented by the existing exam entry; no duplicate, no provider cost.
  - Tradeoff: A rejected upgrade leaves the lower-ranked label in place (logged, not surfaced to parents).
  - Confidence: HIGH — narrow, local change; matches the "never lose a notification" spirit of the fallbacks.
  - Blind spot: A catch inside the transaction is safe only because the service validates before writing (verified: all checks precede `save`).
- **Decision**: FIXED — _apply catches the upgrade ValidationError, logs class/ids only, records merged; conversion test added

### F2 — Concurrently deleted matched entry fails the notification permanently

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Safety & Quality
- **Location**: entries/eduvulcan/conversion.py `_candidates` / `_apply` (upgrade at ~:415); related to Phase 1 F2
- **Detail**: Candidates are read without a row lock. If a parent deletes the matched exam entry before the upgrade saves, `save(update_fields=...)` raises `DatabaseError("Save with update_fields did not affect any rows.")`, which `process_claim` records as non-retryable `ERROR_DATABASE` → notification FAILED, though a retry would simply have created the entry. Same root cause as Phase 1 F2 (lost update of a concurrent parent edit).
- **Fix**: Lock candidate rows in `_candidates` with `select_for_update(of=('self',))` (the `of` is required because the captured-date annotation is an outer join on PostgreSQL); a concurrent delete/edit then serializes, and a deleted row is no longer a candidate → CREATE. Resolves Phase 1 F2 too.
  - Strength: One change closes both the lost-update and the failed-delete window; lock order notification → family → entry is unchanged.
  - Tradeoff: Parent edits of matching EduVulcan entries briefly wait on the conversion transaction.
  - Confidence: MED — SQLite ignores the lock, so tests can't prove it; correctness relies on PostgreSQL semantics.
  - Blind spot: Not exercised by any test; the advisory-locked worker means only web-request races matter.
- **Decision**: FIXED — _candidates uses select_for_update(of=('self',)); verified on PostgreSQL 16 (conversion/service suites green)

### F3 — Family lock skipped for classification-only persists

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: entries/eduvulcan/conversion.py:454-459
- **Detail**: A classification persist inserts EduVulcan entries without the family lock, so with two concurrent converters a rule conversion might not see it. Unreachable today (single advisory-locked worker).
- **Fix**: Mention this in the `_persist` docstring (or lock unconditionally — one cheap query).
- **Decision**: SKIPPED

### F4 — Undated candidate scan grows with family history

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: entries/eduvulcan/conversion.py:368-390
- **Detail**: Undated proposals scan all undated EduVulcan entries of the family (via `entry_family_date_idx` with `date IS NULL`) before joining to the capture day; raw pruning keeps entries and links, so the set only grows. Fine at current volumes.
- **Fix**: Leave for now; if needed, start the join from `InboundNotification(family, captured_date)`.
- **Decision**: SKIPPED

### F5 — Duplicated constants/fakes

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: entries/eduvulcan/conversion.py:365 vs entries/eduvulcan/dedup.py:48; entries/tests/test_conversion_dedup.py:31-35 vs entries/tests/test_conversion_worker.py:64
- **Detail**: `_DEDUPLICATED_KINDS` is defined in both modules and can drift; `NoProviderBackend` is redefined in the new test file.
- **Fix**: Make the dedup constant public and import it in `conversion.py`; reuse the existing fake backend.
- **Decision**: SKIPPED

### F6 — Test gaps for documented behaviors

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: entries/tests/test_conversion_dedup.py
- **Detail**: Not covered end to end: duplicates inside one notification collapsing (claimed in the `_persist` docstring), `rule_remainder` dedup, upgrade of an unassigned exam (`school_item=None`), retry after an upgrade. The assertion at :138 checks the fixture (`notification_id` differs), not behavior.
- **Fix**: Add those four tests; drop or keep the fixture assertion as a precondition comment.
- **Decision**: SKIPPED
