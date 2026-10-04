---
change_id: testing-classification-correctness-privacy
title: Classification correctness and privacy testing
status: preparing
created: 2026-10-04
updated: 2026-10-04
archived_at: null
---

## Notes

Risk #5 slice of rollout Phase 2 ("Intake and classification resilience") in context/foundation/test-plan.md: classification saves the wrong child, date, or entry type, or exposes submitted family text.
Risk response intent: requirements-derived examples produce the correct proposal or follow-up without sensitive-data leakage, using deterministic unit/contract tests plus narrow integration tests; expected values must not be copied from production logic.
Risk #4 (intake durability) is covered separately by testing-eduvulcan-intake-durability.
