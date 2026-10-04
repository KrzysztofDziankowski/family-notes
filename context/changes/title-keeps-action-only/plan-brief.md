# Entry Title Keeps Only the Action — Plan Brief

> Full plan: `context/changes/title-keeps-action-only/plan.md`

## What & Why

When a parent types "kasia zrobić pranie w piątek", the person and date are extracted into their own fields, but the title can still repeat them. The owner wants the title to be just the action — "zrobić pranie" — with the date set to Friday and the entry assigned to Kasia (PRD v2 PK-20, US-11).

## Starting Point

The OpenAI schema describes the title only as "a concise entry text based on the instruction" and the instructions never say to leave the person or date out (`entries/classification/openai_backend.py:78-80`, `:110-131`). The adapter already verifies the date phrase (`date_source`) against the parent's text, then discards it.

## Desired End State

For the owner example, the review form shows "Zrobić pranie", the coming Friday and Kasia — whether the model returns a clean title or echoes the name and date. Other titles, school entries (which keep their subject, e.g. "Kartkówka z matematyki") and the general-note fallback behave as before.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
| --- | --- | --- | --- |
| Example behaviour | "kasia zrobić pranie w piątek" → "zrobić pranie", Friday, Kasia | Owner's stated requirement. | Owner |
| Order | S-01, S-02, S-20, S-03, S-04, … ; S-20 creates shared `DATE_RULES` in `entries/classification/openai_backend.py` | Same prompt file; later slices reuse it unchanged. | Owner |
| Delivery | No flag, no backfill, no E2E | Owner decision for this milestone. | Owner |
| Title casing | First letter capitalized ("Zrobić pranie") | Matches existing titles like "Kupić prezent dla babci". | Assumed (owner to confirm) |
| What is removed | Only the assigned person's name (only when it matches a family member) and the accepted date/time phrase | Other names and details carry meaning not stored elsewhere. | Assumed (owner to confirm) |
| School subject in title | Stays ("Kartkówka z matematyki") | List rows do not show `school_subject`. | Owner |
| "w piątek" on a Friday | Friday of next week (reference + 7 days), never today; explicit in `DATE_RULES` and tested | Bare weekday = next occurrence after today. | Owner |
| Paths covered | All classification, incl. EduVulcan | One shared prompt; school titles unaffected. | Assumed (owner to confirm) |
| Safety net | Conservative deterministic guard after the prompt fix | Models sometimes ignore wording; guard never empties a title. | Research |

## Scope

**In scope:** title rule and `DATE_RULES` in the prompt contract; a pure guard stripping a leading assignee name and a trailing accepted date phrase; adapter-path and unit tests; an opt-in live test.

**Out of scope:** general-note fallback, diminutives (S-02), text corrections (S-03), rewriting saved entries, grammar changes to the action, E2E tests.

## Architecture / Approach

Prompt contract (`openai_backend.py`) → model returns `content`, `date`/`date_source`, `member_name` → adapter grounds the date → new `title.strip_extracted_phrases` removes leftover name/date → unchanged validation and review form.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Prompt contract | Title rule + shared `DATE_RULES` sent to OpenAI | Wording the model actually follows |
| 2. Title guard | Deterministic cleanup + acceptance tests for the owner example | Over-stripping meaningful words |
| 3. Live check | Opt-in live test + manual review-form check | Real-model variance |

**Prerequisites:** S-01 and S-02 (unconditional; S-20 uses S-02's `member_mention` and `match_mention`). Confirmed order: S-01, S-02, S-20, S-03, S-04, S-05, S-06, S-07, S-08, S-09, S-17, S-14, S-15, S-16. Roadmap status is `planning`; owner decisions were applied 2026-10-04. S-07 will later extend the guard so "dla mnie" counts as an assignee reference; the guard takes a sequence of references to allow that.
**Estimated effort:** ~1 session across 3 phases.

## Open Risks & Assumptions

- Owner decisions were applied 2026-10-04 (example, order, delivery, same-weekday rule, subject stays in the title); the rows marked "Assumed (owner to confirm)" stand unless the owner objects.
- S-04's plan still says it may create `DATE_RULES` and appends it to `MULTI_INSTRUCTIONS`; it should reuse S-20's constant and not re-append it.
- If the general-note fallback is what produced the long title (model returned no type), this slice does not change it; Phase 3's live check will show which path the real model takes.

## Success Criteria (Summary)

- "kasia zrobić pranie w piątek" → review form shows "Zrobić pranie", the coming Friday and Kasia.
- Titles never lose names or details that were not extracted into another field.
- No regressions in school, follow-up or EduVulcan classification.
