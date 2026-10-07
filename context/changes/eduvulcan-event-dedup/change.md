---
change_id: eduvulcan-event-dedup
title: Reject duplicate and merge similar EduVulcan events on automation intake
status: impl_reviewed
created: 2026-10-07
updated: 2026-10-07
archived_at: null
---

## Notes

events from the eduvulcan send via /api/automation/notifications/ can be duplicated.
reject duplicates.
moreover there can be similar events, merge them:
- Kartkówka: Biologia  and Sprawdzian: Biologia -> leave  Sprawdzian: Biologia
- Praca klasowa: Biologia and Kartkówka: Biologia -> leave Praca klasowa: Biologia
