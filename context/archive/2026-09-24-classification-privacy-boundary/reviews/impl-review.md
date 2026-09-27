<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Classification Privacy Boundary Implementation Plan

- **Plan**: context/changes/classification-privacy-boundary/plan.md
- **Scope**: Full plan
- **Reviewed phases**: 1, 2, 3, 4
- **Date**: 2026-09-27
- **Verdict**: NEEDS ATTENTION
- **Findings**: 0 critical, 3 warnings, 4 observations

Supersedes the earlier 2026-09-27 review of phases 1, 3 (phases 2 and 4 were blocked then by the open ZDR item 2.5, now marked SKIPPED as deferred post-MVP).

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | WARNING |
| Scope Discipline | WARNING |
| Safety & Quality | WARNING |
| Architecture | PASS |
| Pattern Consistency | PASS |
| Success Criteria | PASS |

## Verification Evidence

- `uv run python manage.py test` — PASS; 138 tests, OK (3 skipped: opt-in live eval gated by `CLASSIFICATION_LIVE_EVAL=1`).
- `uv run python manage.py check` — PASS; no issues.
- `uv run python manage.py makemigrations --check --dry-run` — PASS; no changes detected.
- `uv run --with pip-audit pip-audit` — PASS; no known vulnerabilities.
- Repository key scan (`git grep 'sk-…'`) — only the test sentinel `sk-SENTINEL-APIKEY-4e1d77`; no real key.
- ZDR removal consistency — no `OPENAI_ZDR_ATTESTED` / attestation references remain in code, settings, `.env.example`, runbook or tests; remaining ZDR mentions are deferral comments.
- Phase 2 contract verified: `responses.parse` with `extra='forbid'` schema, `store=False`, minimal payload, no stateful features, `max_retries=0`, 10s attempt / 25s monotonic deadline, retry only for timeout/connection/429/5xx within budget, safe single-line logging, Polish prompt (lessons rule satisfied).
- Phase 4 contract verified: PRD example with explicit reference date, relative dates, follow-ups, ambiguity, failure cases, virtual-clock deadline test, hygiene scan, synthetic `classification_smoke` command, runbook "Enable Classification" section preserving `--workers 2`, `--timeout 45`, nginx 50s.
- Manual 2.5 — SKIPPED (owner decision, deferred post-MVP; roadmap → Parked). Manual 4.5/4.6 — operator-confirmed (4.6 without ZDR evidence).

## Findings

### F1 — OpenAI client created per request and never closed

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: entries/classification/openai_backend.py:346
- **Detail**: `build_openai_backend()` constructs a new `openai.OpenAI(...)` (own httpx pool) on every `classify_for_parent` call (service.py:94) and nothing calls `close()`. Sockets linger until GC and every request pays a fresh TLS handshake inside the 10s/25s budget.
- **Fix**: Close the client after `classify` (context manager / try-finally around the call when the factory built it), or cache one lazily-built client per process.
- **Decision**: FIXED — added `OpenAIClassificationBackend.close()`; service and `classification_smoke` close a factory-built backend in `finally`; tests cover close on success/failure and no close for injected backends (140 tests OK).

### F2 — No input length bound before sending text to OpenAI

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Safety & Quality
- **Location**: entries/classification/service.py:57
- **Detail**: `submitted_text` is forwarded to the provider without a length cap at the service boundary or in `BackendRequest`; only output is capped (`max_output_tokens=1024`). An authorized parent (or a future view bug) can send arbitrarily large input, costing money and latency against the 25s deadline. The plan did not require a cap, so this is a plan gap rather than drift.
- **Fix A ⭐ Recommended**: Enforce a max length in `classify_for_parent`, returning a safe unavailable/follow-up result without calling the backend.
  - Strength: The service is the single audited boundary (plan Phase 3 intent); every future caller (S-01 view, smoke command) is covered.
  - Tradeoff: Needs a new `UnavailableReason` (or reuse) and a chosen limit; small test addition.
  - Confidence: HIGH — mirrors how authorization is already enforced at this boundary.
  - Blind spot: The right limit (e.g. 1000–2000 chars) is a product decision not yet in the PRD.
- **Fix B**: Defer to S-01 and enforce `max_length` on the capture form, noting it in S-01's plan.
  - Strength: Keeps F-02 closed as implemented; user-facing validation message belongs in the form anyway.
  - Tradeoff: Boundary relies on every caller remembering the limit.
  - Confidence: MED — works if S-01 is the only caller.
  - Blind spot: Management command and future callers are uncovered.
- **Decision**: FIXED via Fix A — `MAX_SUBMITTED_TEXT_LENGTH = 2000` in service.py; over-limit text returns `UnavailableReason.INPUT_TOO_LONG` after authorization and before any query or backend call; boundary tests added (142 tests OK). S-01 form should mirror the limit with a Polish message.

### F3 — Stale ZDR wording remains in plan and runbook

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Adherence
- **Location**: context/changes/classification-privacy-boundary/plan.md:5, :32, :120, :217; context/changes/deployment/mikrus-runbook.md:936
- **Detail**: Plan overview/discoveries still say "enforcing OpenAI ZDR requirements" / "ZDR remains a production prerequisite", and the Phase 2/4 contracts still require ZDR attestation and evidence. Runbook line 936–937 reads "Record the smoke output line, the three sentinel results…" — a dangling list left after removing "ZDR evidence". Code is consistent; only documents are stale.
- **Fix**: Add the "deferred post-MVP" annotation to the four plan lines and change the runbook sentence to "Record the smoke output line and the three sentinel results in the private operator record."
- **Decision**: FIXED — plan lines 5, 32, 120, 217 now carry the post-MVP deferral (every ZDR mention in plan.md is marked deferred); runbook sentence corrected.

### F4 — Unrelated toolkit/gitignore edits bundled into feature commits

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Scope Discipline
- **Location**: AGENTS.md, CLAUDE.md, .gitignore:13 (commit af90c9b)
- **Detail**: The 10x toolkit block in AGENTS.md/CLAUDE.md was swapped from M2L4 to M2L5 text and `.gitignore` gained `eduvulcan-queue/`; neither relates to this change. No functional effect.
- **Fix**: Accept as-is (history already written); keep toolkit churn in separate commits going forward.
- **Decision**: ACCEPTED — history already written; keep toolkit churn in separate commits going forward.

### F5 — Per-attempt SDK timeout is per network phase, not total

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: entries/classification/openai_backend.py:349
- **Detail**: A float `timeout` bounds connect/read/write phases individually, so a trickling attempt can exceed 25s wall clock. Late answers are discarded (openai_backend.py:176-183), and Gunicorn `--timeout 45` still bounds the worker, so impact is a blocked worker, not a leak.
- **Fix**: Accept and note it in the runbook, or pass an `httpx.Timeout` with a shorter connect timeout.
- **Decision**: FIXED — each attempt now uses `openai.Timeout(timeout, connect=min(3.0, timeout))`, so a slow handshake cannot consume the budget; read/write/pool keep the attempt timeout. Residual: httpx read timeout is still per-chunk, so Gunicorn `--timeout 45` remains the hard wall-clock bound. Test added.

### F6 — Infinite deadline passes settings validation

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: family_notes/settings.py (`validate_classification_settings`)
- **Detail**: `CLASSIFICATION_DEADLINE_SECONDS=inf` is accepted (NaN is rejected), silently disabling the deadline.
- **Fix**: Require `math.isfinite` (or an upper bound ≤ 30) for the deadline and attempt timeout.
- **Decision**: SKIPPED

### F7 — Submitted text would be a frame local in an unexpected 500

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: entries/classification/service.py:57
- **Detail**: All `openai.OpenAIError` subclasses are caught correctly, but a non-SDK exception (e.g. SDK response-shape change in `_translate`) would propagate with `submitted_text` in frame locals. Today nothing emits tracebacks with locals (`DEBUG=False`, no `ADMINS`/`LOGGING`), so no current leak.
- **Fix**: Decorate `classify_for_parent` with `@sensitive_variables('submitted_text')` as defense in depth.
- **Decision**: FIXED — `@sensitive_variables('submitted_text')` on `classify_for_parent`.

## Triage Summary

- Fixed: F1, F2 (Fix A), F3, F5, F7 (5)
- Accepted: F4 (1)
- Skipped: F6 (1)
- Post-triage verification: `uv run python manage.py test` — 143 tests OK (3 skipped).
