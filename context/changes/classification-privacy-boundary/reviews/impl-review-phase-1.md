<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Classification Privacy Boundary Implementation Plan

- **Plan**: context/changes/classification-privacy-boundary/plan.md
- **Scope**: Phase 1 of 4
- **Reviewed phases**: 1
- **Date**: 2026-09-26
- **Verdict**: NEEDS ATTENTION
- **Findings**: 0 critical, 1 warning, 0 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | WARNING |
| Scope Discipline | FAIL |
| Safety & Quality | PASS |
| Architecture | PASS |
| Pattern Consistency | PASS |
| Success Criteria | PASS |

## Verification Evidence

- `uv run python manage.py test entries.tests.test_classification_contract` — PASS; 30 tests ran successfully.
- `uv run python manage.py check` — PASS; no issues identified.
- `uv run python manage.py makemigrations --check --dry-run` — PASS; no changes detected.
- Manual criterion 1.4 — observable evidence supports completion: the public contract imports only Python standard-library types and local provider-neutral modules; no OpenAI SDK types are exposed.

## Findings

### F1 — Unresolved school-item rules were encoded as domain policy

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Scope Discipline
- **Location**: entries/classification/types.py:36
- **Detail**: `SchoolItemKind` defines classification and required-field policy for class tests, quizzes, lucky numbers, grades, substitutions, late arrivals, and room changes, and `validate_output` enforces those rules at `entries/classification/validation.py:73`. Phase 1 requires only tests, homework, calendar entries, and general-note fallback. The plan explicitly excludes a general solution beyond the PRD-defined cases, while `context/foundation/prd.md:127` leaves those additional rules unresolved. This turns open product questions into code and tests without a documented decision.
- **Fix A ⭐ Recommended**: Reduce `SchoolItemKind` and its tests to the PRD-defined test/homework cases, leaving other content to the general-note fallback.
  - Strength: Restores the explicit MVP boundary and avoids treating speculative rules as product policy.
  - Tradeoff: Removes already implemented taxonomy that may later be useful after product decisions are made.
  - Confidence: HIGH — the plan, PRD, and research all identify broader validation as unresolved.
  - Blind spot: A stakeholder may have approved these categories outside the repository, but no such decision is documented in the reviewed evidence.
- **Fix B**: Document and approve the added category rules in the PRD and plan as a deliberate scope expansion.
  - Strength: Preserves the implemented taxonomy and makes the domain behavior reviewable as an explicit product decision.
  - Tradeoff: Expands the MVP contract and requires validating each added rule with the product owner.
  - Confidence: MEDIUM — technically coherent, but correctness depends on product decisions absent from the repository.
  - Blind spot: The current labels and required fields may still be incomplete or incorrect for real family workflows.
- **Decision**: FIXED via Fix B — expanded taxonomy approved and documented in the PRD and plan.
