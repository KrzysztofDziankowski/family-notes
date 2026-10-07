# EduVulcan Event Deduplication and Exam Merge Implementation Plan

## Overview

EduVulcan sometimes re-sends the same school event with a new notification id or on a later day, and sends several exam notifications for one lesson (e.g. "Kartkówka" and "Sprawdzian" for the same child, subject and date seconds apart). Each currently becomes its own entry. This plan makes conversion reject rule-produced duplicates against live EduVulcan entries in the family, and merge exam events so only the highest-ranked kind remains: Kartkówka < Sprawdzian < Praca klasowa.

## Current State Analysis

- Intake (`entries/api_views.py:97-105`) already rejects a notification with the same `notification_id`, or the same normalized title+message on the same capture day, answering `202` with the existing row id. Re-sends on another day, or with different text, pass.
- Conversion (`entries/eduvulcan/conversion.py` `_persist`) only skips output indexes the *same* notification already produced; it never looks at other entries in the family.
- Fixed rules (`entries/eduvulcan/rules.py`) build exam content as `"<Label>: <subject>"`, plus `" — <child>"` when the child is unmatched. Unassigned exams drop `school_item` because exam kinds require a member (`entries/classification/types.py:39,51-53`), so the label prefix in content is the only kind marker common to assigned and unassigned exams.
- The local sample corpus (`eduvulcan-queue/`, gitignored) shows two Sprawdzian+Kartkówka pairs for the same child/subject/date 7–13 s apart, and one exact Sprawdzian re-send — bursts that two workers may convert concurrently on PostgreSQL.
- `NotificationConversionOutput.entry` is a nullable `OneToOneField`; an output with `entry=NULL` already means "nothing to (re)create" for retries. `kind` is guarded by the `conversion_output_known_kind` check constraint built from `OutputKind`.
- `create_automated_entry` (`entries/services.py:374`) is the only automated write path; there is no automated update path.

## Desired End State

- A rule output whose event already exists as a live EduVulcan entry in the family creates no new entry; the notification is still `processed` and records an output of kind `duplicate` with no entry.
- An exam output for the same child, date and subject as a live EduVulcan exam entry:
  - lower or equal rank → no new entry, output kind `merged` with no entry;
  - higher rank → the existing entry is upgraded in place (label in content, and `school_item` when assigned), output kind `merged` with no entry.
- Examples: "Kartkówka: Biologia" then "Sprawdzian: Biologia" → one entry "Sprawdzian: Biologia". "Praca klasowa: Biologia" then "Kartkówka: Biologia" → one entry "Praca klasowa: Biologia". Order of arrival does not change the result.
- Concurrent conversion of a burst in one family is serialized, so a pair never yields two entries on PostgreSQL.

### Key Discoveries:

- Exam label → kind map `_CALENDAR_CATEGORIES` in `entries/eduvulcan/rules.py` is the source of labels to rank.
- `_persist` already runs inside one `transaction.atomic()` with a fenced `select_for_update`; matching and upgrade belong inside that same transaction.
- `NotificationConversionOutput` gives the source notification of a generated entry, hence its `captured_date`, for undated matching — no new column needed.

## What We're NOT Doing

- No change to intake deduplication or its `202` response.
- No deduplication of classification or general-note outputs (only `rule` and `rule_remainder`).
- No matching against manual entries; they are never skipped against or modified.
- No protection for parent-deleted entries: a re-send of an event whose entry a parent deleted creates it again (explicit decision).
- No matching through parent-edited text: if a parent changed an entry's content, date, child or kind, it no longer matches (explicit decision).
- No new column, no backfill or merge of entries created before this change.
- No merging of homework with exams; no UI changes.

## Implementation Approach

A pure matching module decides, for one proposal and the candidate live entries, whether to create, skip as duplicate, skip as merged, or upgrade. `_persist` locks the family row, queries candidate EduVulcan entries for each new rule proposal, applies the decision through a new service function, and records the output. Proposals created earlier in the same transaction are visible to later ones, so duplicates inside one notification collapse too.

### Matching rules (decided)

Normalization: NFC, whitespace collapsed, casefolded (reuse `normalize_text` + `casefold`).

- **Exact duplicate** (all rule outputs): existing EduVulcan entry in the same family with equal `entry_type`, `assigned_member` (both may be NULL), `date`, `school_item`, normalized `content`.
  - Dated proposal: dates are equal.
  - Undated proposal (grades, rule remainders): existing entry is undated and its source notification's `captured_date` equals this notification's `captured_date`.
- **Exam merge** (proposal content starts with "Kartkówka: ", "Sprawdzian: " or "Praca klasowa: "): existing EduVulcan calendar event, same `assigned_member` (NULL allowed), same `date`, content starting with one of the three labels and the same normalized remainder after the label. Rank: Kartkówka 1 < Sprawdzian 2 < Praca klasowa 3. Incoming rank ≤ existing → skip (`merged`); incoming rank > existing → upgrade existing.
- Precedence: the exact-duplicate check runs first (an equal-rank exam re-send → `duplicate`); the exam ranking applies only when nothing matches exactly.
- If several existing entries match, act on the highest-ranked one, ties by lowest id.

## Critical Implementation Details

- **Timing & lifecycle**: lock the family (`Family.objects.select_for_update(no_key=True)` on the row's family) inside `_persist` after the lease check and before matching, so two workers converting a burst serialize. Use `no_key=True`: a plain `FOR UPDATE` would block intake and manual-entry inserts that reference the family for the whole transaction. Lock order notification → family → entry has no inverse path in the codebase. On SQLite it is a no-op, which is acceptable because local runs use one worker (see `eduvulcan-school-event-intake/change.md` notes).

## Phase 1: Matching Rules, Output Kinds and Upgrade Service

### Overview

Pure, unit-testable decision logic plus the schema/service pieces conversion will need.

### Changes Required:

#### 1. Matching module

**File**: `entries/eduvulcan/dedup.py` (new)

**Intent**: Decide what to do with one rule proposal given candidate existing entries, implementing the matching rules above. Keep it free of database writes so it is testable without conversion.

**Contract**: An exam-rank helper returning `(rank, label, normalized remainder)` or `None` for content; a decision function taking the proposal, the notification `captured_date`, and candidate entries (with their source `captured_date`) and returning one of `create`, `duplicate`, `merged`, or `upgrade(entry, new_content, new_school_item)`. Upgraded content is the incoming label + the existing remainder text (keeps any " — <child>" suffix); `new_school_item` is the incoming kind only when the existing entry has an assigned member, otherwise `None`.

#### 2. Output kinds

**File**: `entries/eduvulcan/types.py`, `entries/migrations/0008_*.py`

**Intent**: Record skipped and merged results as provenance.

**Contract**: `OutputKind.DUPLICATE = ('duplicate', 'Duplicate of existing entry')`, `OutputKind.MERGED = ('merged', 'Merged into existing entry')`. Migration updates `NotificationConversionOutput.kind` choices and replaces the `conversion_output_known_kind` constraint. Admin labels stay English. Update the `NotificationConversionOutput` docstring (`entries/models.py`): a NULL `entry` is either a parent-deleted tombstone or a `duplicate`/`merged` output that never owned an entry.

#### 3. Upgrade service

**File**: `entries/services.py`

**Intent**: Second automated write path, used only to upgrade an EduVulcan exam entry.

**Contract**: `upgrade_automated_exam_entry(entry, *, content, school_item)` — refuses (`ValidationError`) unless `entry.source == eduvulcan` and `school_item` is `None` or an exam kind; saves `content`, `school_item`, `updated_at` only. Caller owns the transaction.

### Success Criteria:

#### Automated Verification:

- Matching unit tests pass: `uv run python manage.py test entries.tests.test_eduvulcan_dedup`
- Unit tests cover: both user examples in both arrival orders, equal-rank re-send, homework not merged with exams, unassigned exam merge with child suffix, grade duplicate same capture day vs different day, timetable change duplicate, manual entry ignored, different subject/date/child not matched
- Upgrade service tests pass (rejects manual entries and non-exam kinds): `uv run python manage.py test entries.tests.test_entry_service`
- Migration check is clean: `uv run python manage.py makemigrations --check --dry-run`
- Django checks pass: `uv run python manage.py check`

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human before proceeding to the next phase.

---

## Phase 2: Conversion Integration

### Overview

Wire matching into `_persist` under a family lock and prove it end to end.

### Changes Required:

#### 1. Persist with deduplication

**File**: `entries/eduvulcan/conversion.py`

**Intent**: For each new proposal of kind `rule`/`rule_remainder`, query candidate live EduVulcan entries in the family (same member and date, or undated with their conversion output's notification `captured_date`), ask the matching module, then create the entry, upgrade the existing one, or create a `duplicate`/`merged` output with `entry=NULL`. Classification and general-note proposals keep today's path.

**Contract**: Family row locked before matching; outputs still use the proposal's stable `output_index`, so retries skip them as today. The processed log line additionally reports counts of duplicate and merged outputs (ids and counts only, never text).

#### 2. Conversion tests

**File**: `entries/tests/test_conversion_lifecycle.py` (or new `entries/tests/test_conversion_dedup.py`)

**Intent**: Database-backed proof using anonymized notification text modeled on the sample corpus (no real names).

**Contract**: Scenarios listed in Phase 2 success criteria.

#### 3. Intended update of an existing test

**File**: `entries/tests/test_conversion_worker.py` (`test_first_iteration_is_the_startup_sweep`, ~line 101)

**Intent**: It converts two identical Sprawdzian notifications and expects two entries — the behavior this change deliberately removes. Make the two notifications distinct events (e.g. different subject) so the test keeps checking the startup sweep, not deduplication.

**Contract**: Test still asserts both notifications are processed by the first sweep.

### Success Criteria:

#### Automated Verification:

- Conversion dedup tests pass: `uv run python manage.py test entries.tests.test_conversion_dedup`
- Tests cover: Kartkówka→Sprawdzian leaves one entry "Sprawdzian: Biologia" with `school_item=test`; Praca klasowa→Kartkówka leaves "Praca klasowa: Biologia"; exact re-send on a later day with a new notification id yields one entry and a `duplicate` output; retry of a merged notification creates nothing new; parent-deleted entry is recreated by a re-send; manual entry with identical text is untouched and does not block creation; another family's identical entry does not block creation
- Full EduVulcan suites stay green: `uv run python manage.py test entries`
- Migration check and Django checks pass: `uv run python manage.py makemigrations --check --dry-run && uv run python manage.py check`

#### Manual Verification:

- Locally (one Gunicorn worker), POST "Kartkówka" then "Sprawdzian" for the same child/subject/date to `/api/automation/notifications/`; parent list shows a single "Sprawdzian: …" entry
- Repeat with "Praca klasowa" then "Kartkówka"; only "Praca klasowa: …" remains
- Admin shows `merged`/`duplicate` conversion outputs with empty entry for the skipped notifications

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human.

---

## Testing Strategy

### Unit Tests:

- Matching decision table (Phase 1), including order independence and normalization (case, whitespace, NFC).

### Integration Tests:

- Database-backed conversion through `convert_notification` with fixed `now`, as existing lifecycle tests do.

### Manual Testing Steps:

1. Send the exam pairs above in both orders and check the parent list.
2. Re-send a grade notification with a new id the same day (skipped) and the next day (new entry).
3. Delete a generated entry, re-send its notification with a new id, confirm it reappears.

## Performance Considerations

One extra indexed query per rule proposal (`entry_family_date_idx` covers dated lookups; undated lookups are limited to the family and joined through the output link). The family row lock is held only for the persist transaction, which contains no provider calls.

## Migration Notes

Migration only alters choices and a check constraint; existing rows keep valid kinds. A code-only rollback keeps the widened database constraint, so old code still inserts its own kinds; existing `duplicate`/`merged` rows are only shown as raw values in admin. Reversing the migration requires deleting those rows first.

## References

- Prior change: `context/changes/eduvulcan-school-event-intake/plan.md`
- Conversion persist: `entries/eduvulcan/conversion.py` (`_persist`)
- Rules and labels: `entries/eduvulcan/rules.py` (`_CALENDAR_CATEGORIES`, `_calendar`)
- Intake dedup: `entries/api_views.py:97-105`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Matching Rules, Output Kinds and Upgrade Service

#### Automated

- [x] 1.1 Matching unit tests pass: `uv run python manage.py test entries.tests.test_eduvulcan_dedup` — fc8c939
- [x] 1.2 Unit tests cover: both user examples in both arrival orders, equal-rank re-send, homework not merged with exams, unassigned exam merge with child suffix, grade duplicate same capture day vs different day, timetable change duplicate, manual entry ignored, different subject/date/child not matched — fc8c939
- [x] 1.3 Upgrade service tests pass (rejects manual entries and non-exam kinds): `uv run python manage.py test entries.tests.test_entry_service` — fc8c939
- [x] 1.4 Migration check is clean: `uv run python manage.py makemigrations --check --dry-run` — fc8c939
- [x] 1.5 Django checks pass: `uv run python manage.py check` — fc8c939

### Phase 2: Conversion Integration

#### Automated

- [x] 2.1 Conversion dedup tests pass: `uv run python manage.py test entries.tests.test_conversion_dedup` — dd8cd3f
- [x] 2.2 Tests cover: Kartkówka→Sprawdzian leaves one entry "Sprawdzian: Biologia" with `school_item=test`; Praca klasowa→Kartkówka leaves "Praca klasowa: Biologia"; exact re-send on a later day with a new notification id yields one entry and a `duplicate` output; retry of a merged notification creates nothing new; parent-deleted entry is recreated by a re-send; manual entry with identical text is untouched and does not block creation; another family's identical entry does not block creation — dd8cd3f
- [x] 2.3 Full EduVulcan suites stay green: `uv run python manage.py test entries` — dd8cd3f
- [x] 2.4 Migration check and Django checks pass: `uv run python manage.py makemigrations --check --dry-run && uv run python manage.py check` — dd8cd3f

#### Manual

- [x] 2.5 Locally (one Gunicorn worker), POST "Kartkówka" then "Sprawdzian" for the same child/subject/date to `/api/automation/notifications/`; parent list shows a single "Sprawdzian: …" entry
- [x] 2.6 Repeat with "Praca klasowa" then "Kartkówka"; only "Praca klasowa: …" remains
- [x] 2.7 Admin shows `merged`/`duplicate` conversion outputs with empty entry for the skipped notifications
