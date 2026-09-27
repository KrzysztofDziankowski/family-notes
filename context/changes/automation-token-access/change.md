---
change_id: automation-token-access
title: Automation token access
status: implemented
created: 2026-09-27
updated: 2026-09-27
archived_at: null
---

## Notes

<!-- Free-form notes for this change: links, ad-hoc context, decisions that don't belong in research/frame/plan. -->

- 2026-09-27: Added requirement that intake must be fast. Phase 3 stores forwarded notifications in a pre-events table (`InboundNotification`) and returns 202, with no classification in the request. Conversion (rules → LLM → note) through an in-memory queue, with no external dependency, belongs to S-05; see the plan's "S-05 Handoff". Phase 3 plan-reviewed (v2): intake content dedup, migration after S-01, worker startup rules.
