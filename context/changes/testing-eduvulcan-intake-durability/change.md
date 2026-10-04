---
change_id: testing-eduvulcan-intake-durability
title: EduVulcan intake durability and idempotency testing
status: preparing
created: 2026-10-04
updated: 2026-10-04
archived_at: null
---

## Notes

Risk #4 slice of rollout Phase 2 ("Intake and classification resilience") in context/foundation/test-plan.md: an accepted EduVulcan notification is lost, converted twice, or remains unprocessed after interruption.
Risk response intent: prove acknowledged input survives interruption, resumes safely, and repeated delivery produces one intended result, with database-backed integration tests rather than over-mocked worker tests.
Risk #5 (classification correctness and privacy) stays out of this change.
