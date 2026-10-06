# Mandatory Dates and Listing Type Labels — Plan Brief

> Full plan: [plan.md](plan.md)

## What & Why

Keep notes, events, and tasks, with dates that explain when each entry belongs. Hide broad type labels in listings while retaining classification and editing controls.

## Starting Point

The shared date field is nullable. Calendar events require dates, but notes/tasks and some imports are undated. Parent lists already hide types; child lists still show them.

## Desired End State

Every entry has a date. Notes use writing dates, events occurrence dates, tasks deadlines. Existing non-null dates stay unchanged; missing dates become local creation dates. Historical types follow recognized saved school metadata; unmapped entries keep their types.

## Key Decisions Made

| Decision | Choice | Why |
| --- | --- | --- |
| Types | Retain note/event/task | Owner decision |
| Manual note dates | Default local writing date; editable | Supports recording and correction |
| Imported note dates | Validated recognized source-writing format, then capture date | Rejects unverified classifier dates and processing-delay drift |
| Event/task dates | Ask when missing | Do not invent schedules |
| Type changes | Keep selected date for review | Preserve user control |
| School events | Homework, class test, test, quiz, substitution, room change, teacher absence | Confirmed one by one |
| School notes | Lucky number, grade, late arrival, teacher message, fallback | Confirmed one by one |
| Existing dates | Preserve non-null values | Explicit owner decision |
| Historical types | Normalize using saved school-kind metadata only | Owner triage decision; avoids guessing from text |
| Missing dates | Local created_at date | Approved backfill; old task deadline fallback |
| Migration | Backfill then non-null column | Every entry must have a date |
| Lists | Hide type labels in parent and child lists | Reduce visible categorization |

## Scope

**In scope:** date rules, school mappings, write validation, forms/admin, listing presentation, migration preservation, compatibility tests, and documentation.

**Out of scope:** generic type, changing existing non-null dates or reclassifying historical text, task completion, reminders, deployment, new E2E infrastructure, or merging abandoned generic code.

## Architecture / Approach

Update producers and save validation, keep correction drafts incomplete when necessary, and clarify date controls. Backfill null dates from Europe/Warsaw creation dates, align historical types from recognized school metadata, and then enforce non-null storage without a date default. Update seeds and ordinary test fixtures with dates. Retain source occurrence dates in note text.

## Phases at a Glance

| Phase | Deliverable | Key risk |
| --- | --- | --- |
| 1 | Date rules and school mappings | Confusing writing dates with occurrence dates |
| 2 | Forms and listing labels | Rejecting incomplete correction drafts prematurely |
| 3 | Backfill and non-null storage | Altering unrelated data or reversing irreversible migration |
| 4 | Compatibility and release verification | Old workers writing during migration |

**Prerequisites:** existing capture/correction/batch/family contracts; safe maintenance support before production rollout.

**Estimated effort:** approximately 3–5 focused sessions plus manual acceptance and release prerequisites.

## Open Risks & Assumptions

- Historical task creation dates become fallback deadlines; existing dates keep their old meaning.
- Occurrence dates must stay in note text when writing dates replace their placement date on new imports.
- Date/type migration is irreversible and requires isolated historical migration tests. Individual API type values may change for recognized school entries.
- Deployment must stop writers; the current helper does not yet provide the required ordering.

## Success Criteria (Summary)

- Every entry has a date with the agreed semantics for new writes.
- Lists hide types while editing/detail retain them.
- Migration preserves existing non-null dates, unmapped types, and unrelated data; full tests and manual review verify behavior.

## References

Owner decisions of 2026-10-06, S-21, and the full plan's source and maintenance prerequisite references.
