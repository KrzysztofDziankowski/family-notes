<!-- PLAN-REVIEW-REPORT -->
# Plan Review: Mobile GUI Enhancements Implementation Plan

- **Plan**: `context/changes/mobile-gui-enhancements/plan.md`
- **Mode**: Deep
- **Date**: 2026-10-08
- **Verdict**: SOUND
- **Findings**: 1 critical, 3 warnings, 0 observations — all fixed during triage

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| End-State Alignment | PASS |
| Lean Execution | PASS |
| Architectural Fitness | PASS |
| Blind Spots | PASS |
| Plan Completeness | PASS |

## Grounding

Grounding after triage: 8/8 paths ✓, 4/4 symbols ✓, brief↔plan ✓

## Findings

### F1 — Phase 4 names a nonexistent test directory

- **Severity**: ❌ CRITICAL
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 4 — Cross-feature verification
- **Detail**: The original plan named `family_notes/tests/`, but FamilyNotes tests are top-level `family_notes/test_*.py` modules.
- **Fix**: Name `family_notes/test_pwa.py`, `family_notes/test_tokens_rules.py`, and `family_notes/test_accessibility.py` explicitly.
- **Decision**: FIXED

### F2 — Automated lifecycle tests lack an executable harness

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Plan Completeness
- **Location**: Phase 3 and Testing Strategy
- **Detail**: Django tests can verify static references and template wiring but cannot execute visibility, bfcache, offline, or reload behavior.
- **Fix A**: Use the existing Playwright setup for browser-level lifecycle regression coverage.
- **Fix B**: Limit automation to static-file and wiring contracts and move lifecycle behavior to the manual matrix.
- **Decision**: FIXED via Fix B — manual behavior verification

### F3 — Child accessibility contract describes parent-only markup

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: End-State Alignment
- **Location**: Phase 1 — Rendering expectations
- **Detail**: Only the parent calendar currently labels lists with a complete day and assignee label; child lists have visible headings but no list-label relationship.
- **Fix**: Give child headings unique IDs and reference them from their lists with `aria-labelledby`.
- **Decision**: FIXED — child labels intentionally added

### F4 — Small landscape widths have no acceptance boundary

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Blind Spots
- **Location**: Phase 2 and Manual Testing
- **Detail**: A max-height-only rule also matches 480–568px landscape widths, producing approximately 69–81px columns with long Polish headings.
- **Fix A**: Add `min-width: 36rem`; keep smaller landscape phones at one column and verify both sides of the boundary.
- **Fix B**: Keep seven columns at every landscape width and add aggressive compact styling plus smaller acceptance viewports.
- **Decision**: FIXED via Fix A — explicit width floor

## Triage Summary

- Fixed: F1, F2 (Fix B), F3 (expanded child accessibility contract), F4 (Fix A)
- Skipped: none
- Accepted: none
- Dismissed: none
- Verdict after fixes: SOUND
