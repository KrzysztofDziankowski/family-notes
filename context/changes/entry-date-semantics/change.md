---
change_id: entry-date-semantics
title: Require meaningful dates and hide types in entry lists
status: impl_reviewed
created: 2026-10-06
updated: 2026-10-07
archived_at: null
---

## Notes

Owner replacement decision, 2026-10-06: dates are mandatory; a note date means when it was written, an event date means when it happens, and a task date means its due date. Hide type in listing views. Keep the three existing types. Introduce no generic type. Subsequent owner decisions authorize a date backfill and non-null schema migration: preserve existing non-null dates and fill missing dates from local created_at. Review triage authorizes normalizing historical types from recognized saved school-kind metadata only, trusting imported writing dates only from recognized source formats, and updating seeds/ordinary test fixtures with dates.

Supersedes the generic-family-entries plan. Its unfinished worktree implementation is abandoned and must not be merged or deployed as part of this change.
