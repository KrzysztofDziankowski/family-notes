---
change_id: eduvulcan-school-event-intake
title: EduVulcan school event intake
status: impl_reviewed
created: 2026-09-28
updated: 2026-09-28
archived_at: null
---

## Notes

<!-- Free-form notes for this change: links, ad-hoc context, decisions that don't belong in research/frame/plan. -->

- 2026-09-29 (impl-review F8): Phase 4 renamed the automation route names from `automation_ping` and `automation_notification_submit` to `automation:ping` and `automation:notification_submit` as part of the single namespaced include. The public paths `/api/automation/ping/` and `/api/automation/notifications/` are unchanged, and only tests used the old names. The rename is accepted.
- 2026-09-29 (impl-review F9): accepted as intended. A notification stored before its family was deactivated still converts into unassigned entries, scoped to that family.
