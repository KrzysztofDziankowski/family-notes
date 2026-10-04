---
change_id: testing-production-security-schema-safety
title: Production security and schema safety testing
status: implementing
created: 2026-10-01
updated: 2026-10-04
archived_at: null
---

## Notes

Open a change folder for rollout Phase 1 of context/foundation/test-plan.md: "Production security and schema safety".
Risks covered: #1 unauthorized privileged admin access; #2 unsafe schema migration; #3 cross-family or over-privileged data access. Test types planned: security integration, PostgreSQL migration rehearsal, deployment smoke.
Risk response intent:

- Risk #1: prove anonymous, normal, and staff accounts cannot gain administrative privileges and repeated login abuse has a defined defense.
- Risk #2: prove forward migrations preserve existing rows and constraints under production-like PostgreSQL, with a rehearsed failure-recovery path.
- Risk #3: prove every read and mutation enforces family ownership and least privilege for sessions and automation tokens.

After creating the folder, follow the downstream continuation rule.
