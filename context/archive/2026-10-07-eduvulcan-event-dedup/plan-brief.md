# EduVulcan Event Deduplication and Exam Merge — Plan Brief

> Full plan: `context/changes/eduvulcan-event-dedup/plan.md`

## What & Why

EduVulcan re-sends the same school event (new notification id, or a later day) and sends several exam notifications for one lesson, e.g. "Kartkówka: Biologia" and "Sprawdzian: Biologia" seconds apart. Each becomes a separate entry today, cluttering the family list. Conversion should reject duplicates and keep only the highest-ranked exam.

## Starting Point

Intake already drops copies with the same notification id or the same text on the same day. Conversion never compares against existing family entries, so cross-day re-sends and similar exams all become entries.

## Desired End State

A rule-produced event that already exists as a live EduVulcan entry creates nothing. For exams with the same child, date and subject, one entry remains with the highest kind — Praca klasowa > Sprawdzian > Kartkówka — regardless of arrival order. A higher kind upgrades the existing entry in place. Skipped notifications are still `processed` and leave a `duplicate`/`merged` output for the operator.

## Key Decisions Made

| Decision | Choice | Why |
| --- | --- | --- |
| Duplicate definition | Same event, any capture day, any notification id | Catches re-sends the intake hash misses |
| Scope | All fixed-rule outputs (exams, homework, grades, lucky numbers, attendance, timetable changes, remainders) | Owner wants every rule output deduped |
| Undated outputs (grades, remainders) | Duplicate only on the same capture day | Identical grades on different days are legitimate |
| Exam ranking | Kartkówka < Sprawdzian < Praca klasowa; equal or lower is dropped | Matches the requested merge examples |
| Merge mechanics | Upgrade the existing entry in place | Keeps entry id and parent edits to other fields |
| Parent-deleted entries | A re-send recreates them; match on live entries only | Owner chose no schema change |
| Parent-edited entries | No longer match | Consequence of live-field matching; accepted |
| Concurrency | Lock the family row during persist | Burst pairs arrive seconds apart, possibly on two workers |

## Scope

**In scope:** pure matching module, two new output kinds plus constraint migration, an exam-upgrade service, family-locked dedup in `_persist`, unit and database-backed tests.

**Out of scope:** intake changes, classification/general-note dedup, manual entries, backfill of existing duplicates, homework↔exam merging, UI.

## Architecture / Approach

`claim → rules → _persist: lock family → for each new rule proposal: find live EduVulcan candidates → create | skip (duplicate/merged) | upgrade existing → output row → processed`

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Matching rules, output kinds, upgrade service | Tested decision table, migration, service | Normalization or label parsing misses unassigned exams |
| 2. Conversion integration | Dedup inside the atomic persist under a family lock | Concurrency only truly verifiable on PostgreSQL |

**Prerequisites:** completed `eduvulcan-school-event-intake` conversion pipeline.
**Estimated effort:** ~1–2 implementation sessions across two phases.

## Open Risks & Assumptions

- Two genuinely separate same-kind events for one child/subject/day collapse into one (accepted).
- Exam matching relies on the content label prefix produced by the rules; a parent rewording the entry breaks matching (accepted).
- SQLite ignores the row lock; concurrency is guaranteed only on PostgreSQL.

## Success Criteria (Summary)

- Both requested examples leave exactly one entry with the higher kind, in either arrival order.
- A re-send of any rule event on another day with a new id adds no entry.
- Manual entries and other families are never affected.
