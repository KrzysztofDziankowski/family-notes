---
change_id: eduvulcan-event-dedup
title: Reject duplicate and merge similar EduVulcan events on automation intake
status: archived
created: 2026-10-07
updated: 2026-10-07
archived_at: 2026-10-07T18:32:05Z
---

## Notes

events from the eduvulcan send via /api/automation/notifications/ can be duplicated.
reject duplicates.
moreover there can be similar events, merge them:
- Kartkówka: Biologia  and Sprawdzian: Biologia -> leave  Sprawdzian: Biologia
- Praca klasowa: Biologia and Kartkówka: Biologia -> leave Praca klasowa: Biologia
