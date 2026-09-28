<!-- PLAN-REVIEW-REPORT -->
# Plan Review: Automation Token Access (v2, focus: Phase 3 fast intake)

- **Plan**: context/changes/automation-token-access/plan.md
- **Mode**: Deep
- **Date**: 2026-09-27
- **Verdict**: REVISE → SOUND after triage
- **Findings**: 0 critical, 2 warnings, 2 observations
- **Previous review**: `reviews/plan-review-v1.md` (Phases 1–2)

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| End-State Alignment | PASS |
| Lean Execution | PASS |
| Architectural Fitness | WARNING |
| Blind Spots | WARNING |
| Plan Completeness | WARNING |

## Grounding

7/7 paths ✓, 3/3 symbols ✓ (`is_parent`, `Family`, `EntriesConfig`), brief↔plan ✓, Progress↔Phase ✓. Aggregate sample check over 45 `eduvulcan-queue` payloads (no content read): `notification_id` is a str of 56–57 chars and all 45 are unique; 39 distinct title+message values; max body 510 B; `captured_at_iso` carries a +02:00 offset.

## Findings

### F1 — Deduplicating by id catches none of the real duplicates

- **Severity**: ⚠️ WARNING
- **Impact**: 🔬 HIGH — architectural stakes; think carefully before deciding
- **Dimension**: Blind Spots
- **Location**: Phase 3 §1, S-05 Handoff
- **Detail**: In the samples, every repeated notification has a new `notification_id`, so the (family, notification_id) constraint catches none of them. The per-process workers in the handoff could convert two copies at the same time and create duplicate entries, which breaks FR-011.
- **Fix A ⭐ Recommended**: `content_hash` at intake (not unique), plus serialized conversion with windowed dedup in S-05.
  - Strength: No rejection logic in the fast path; also caps LLM concurrency.
  - Tradeoff: Serial conversion.
  - Confidence: HIGH — the sample stats show the problem directly.
  - Blind spot: Window length not set.
- **Fix B**: Unique (family, content_hash, captured_date) at intake.
  - Strength: Duplicates never reach the table.
  - Tradeoff: Two genuinely identical texts on the same day are stored once.
  - Confidence: MED — only 45 samples.
  - Blind spot: Normalizing the text.
- **Decision**: FIXED (Fix B). The accepted false-positive risk is recorded in plan Phase 3 §1 and the brief.

### F2 — Phase 3 and S-01 both create entries/0001

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Architectural Fitness
- **Location**: Phase 3 §1, Migration Notes
- **Detail**: The S-01 plan creates `entries/0001_initial` and said F-04 doesn't touch `entries`. Phase 3 also created `entries/0001`, which would leave two leaf migrations.
- **Fix A ⭐ Recommended**: Put the model in `family_access` (0003).
  - Strength: No dependency on S-01.
  - Tradeoff: Weaker domain placement.
  - Confidence: HIGH
  - Blind spot: None significant.
- **Fix B**: Keep it in `entries` as `0002`, after S-01's `0001_initial`.
  - Strength: Domain placement.
  - Tradeoff: Phase 3 waits for S-01.
  - Confidence: HIGH
  - Blind spot: S-01's timeline.
- **Decision**: FIXED (Fix B). The Phase 3 prerequisite is added, and the S-01 plan note (first-school-event-capture/plan.md:17) is updated.

### F3 — The in-memory worker's startup isn't specified

- **Severity**: 💡 OBSERVATION
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Blind Spots
- **Location**: S-05 Handoff
- **Detail**: `AppConfig.ready()` also runs under migrate, test and management commands; a thread started before a `--preload` fork is lost; and each Gunicorn worker adds another concurrent LLM caller on 2 GB RAM.
- **Fix**: Start the worker from Gunicorn's `post_fork` hook or lazily, gated by a setting, with at most one conversion at a time (advisory lock).
- **Decision**: FIXED

### F4 — Small gaps in the plan's precision

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 2 §2, Phase 3
- **Detail**: `notification_id` length was 64 while real ids are 56–57 chars; the patch target wasn't named; the README step had no criterion; the Phase 2 route wording disagreed with Phase 3.
- **Fix**: CharField(255); patch `entries.classification.service.classify_for_parent`; manual item 3.12; Phase 2 wording aligned.
- **Decision**: FIXED
