<!-- PLAN-REVIEW-REPORT -->
# Plan Review: EduVulcan School Event Intake

- **Plan**: `context/changes/eduvulcan-school-event-intake/plan.md`
- **Mode**: Deep
- **Date**: 2026-09-28
- **Verdict**: SOUND WITH ACCEPTED RISK
- **Findings**: 2 critical, 4 warnings, 0 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| End-State Alignment | PASS |
| Lean Execution | PASS |
| Architectural Fitness | WARNING |
| Blind Spots | PASS |
| Plan Completeness | PASS |

## Grounding

Grounding: 8/8 paths ✓, 6/6 symbols ✓, brief↔plan ✓; Progress contract: 4/4 phases ✓, 25/25 criteria ✓.

## Findings

### F1 — Worker health would break every production release

- **Severity**: ❌ CRITICAL
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: End-State Alignment
- **Location**: Phase 3 — Shared worker health
- **Detail**: The deployed helper accepts only the byte-exact `/healthz/` body `{"status": "ok"}`; adding conversion state would fail every release gate.
- **Fix**: Preserve `/healthz/` and add a separate conversion-health endpoint plus deployment checks and documentation.
- **Decision**: FIXED

### F2 — Parent deletion can erase idempotency provenance

- **Severity**: ❌ CRITICAL
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 1 — Conversion lifecycle and provenance
- **Detail**: Hard deletion requires an explicit nullable output link; otherwise cascade loses the tombstone or restrict breaks parent deletion.
- **Fix**: Use nullable `Entry` FK with `on_delete=SET_NULL`, retain the unique output tombstone, and test delete-then-retry.
- **Decision**: FIXED

### F3 — Worker startup mechanism is left to the implementer

- **Severity**: ⚠️ WARNING
- **Impact**: 🔬 HIGH — architectural stakes; think carefully before deciding
- **Dimension**: Architectural Fitness
- **Location**: Phase 3 — Worker runtime
- **Detail**: The plan permits post-fork or safe lazy startup instead of selecting one concrete Gunicorn integration.
- **Decision**: ACCEPTED — implementation must preserve startup sweeps, dedicated connections, and advisory locking.

### F4 — Three attempts may mean six provider calls

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Blind Spots
- **Location**: Phase 2 — Retry and terminal-failure policy
- **Detail**: The backend already retries once, so three conversion attempts could produce six provider calls.
- **Fix**: Disable backend-owned retry for automated fallback and cap the lifecycle at three provider calls.
- **Decision**: FIXED

### F5 — Raw-data pruning has no concrete stored representation

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Blind Spots
- **Location**: Phase 2 — Raw-data pruning
- **Detail**: Raw fields are non-null and the plan did not define their scrubbed representation.
- **Fix**: Use `title=''`, `message=''`, `payload={}`, preserve deduplication fields, and render an explicit pruned state in admin.
- **Decision**: FIXED

### F6 — Requeue action conflicts with read-only inbox admin

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 2 — Retry and terminal-failure policy
- **Detail**: The inbox admin denies change permission, preventing a normal requeue action.
- **Fix**: Grant superusers only the minimum action permission while keeping fields, add, and direct edits disabled.
- **Decision**: FIXED
