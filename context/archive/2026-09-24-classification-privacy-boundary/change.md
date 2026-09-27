---
change_id: classification-privacy-boundary
title: Classification privacy boundary
status: archived
created: 2026-09-24
updated: 2026-09-27
archived_at: 2026-09-27T18:09:31Z
---

## Notes

<!-- Free-form notes for this change: links, ad-hoc context, decisions that don't belong in research/frame/plan. -->

### 2026-09-27 — ZDR deferred until after the MVP (owner decision)

- The production fail-closed gate no longer requires `OPENAI_ZDR_ATTESTED`; it requires only `CLASSIFICATION_ENABLED`, `OPENAI_API_KEY`, and `OPENAI_CLASSIFICATION_MODEL`. The setting was removed from `settings.py`, `.env.example`, the runbook, and tests.
- `store=False`, the minimal payload, and sanitized logging are unchanged. Accepted trade-off: OpenAI may retain API traffic for abuse monitoring.
- Progress 2.5 (ZDR confirmation) and the ZDR-evidence part of 4.6 are marked `[x]` with a SKIPPED annotation: they are out of scope and deferred, not done. 4.6 without ZDR covers protected env configuration and sentinel absence from logs.
- Tracked for later in `context/foundation/roadmap.md` → Parked.
