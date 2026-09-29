---
change_id: eduvulcan-school-event-intake
title: EduVulcan school event intake
status: impl_reviewed
created: 2026-09-28
updated: 2026-09-29
archived_at: null
---

## Notes

<!-- Free-form notes for this change: links, ad-hoc context, decisions that don't belong in research/frame/plan. -->

- 2026-09-29 (impl-review F8): Phase 4 renamed the automation route names from `automation_ping` and `automation_notification_submit` to `automation:ping` and `automation:notification_submit` as part of the single namespaced include. The public paths `/api/automation/ping/` and `/api/automation/notifications/` are unchanged, and only tests used the old names. The rename is accepted.
- 2026-09-29 (impl-review F9): accepted as intended. A notification stored before its family was deactivated still converts into unassigned entries, scoped to that family.
- 2026-09-29 (manual verification): the owner verified manual rows 1.5, 1.6, 2.5, 2.6, 3.5 and 4.5 on local SQLite with Gunicorn `--workers 1`, and deliberately skipped 3.6 (health degradation), 4.6 (PostgreSQL two-worker concurrency) and 4.7 (operator privacy review). Those rows stay unchecked. Locally, SQLite with `--workers 2` produced `database_busy` retries, because the advisory lock does nothing on SQLite and SQLite transactions use DEFERRED mode. Local tests therefore use one worker, and concurrency is verified only on PostgreSQL.
