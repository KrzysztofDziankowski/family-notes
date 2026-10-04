# Multi-Entry Text Capture — Plan Brief

> Full plan: `context/changes/multi-entry-text-capture/plan.md`

## What & Why

This is future roadmap slice S-04 (PK-05, US-05). Today a parent has to repeat an instruction once per date. „Dodaj spotkanie z X dziś, jutro i w przyszłym tygodniu w poniedziałek o 18:00” should instead produce three meeting proposals at 18:00, and all three should be reviewed before anything is saved.

## Starting Point

Capture classifies one instruction into exactly one result. That result goes to the review form, the follow-up question or the note fallback, and `confirm` saves one entry idempotently on `submission_key`. The backend seam returns one output. The model computes relative dates from today's Warsaw date under minimal rules.

## Desired End State

A multi-date instruction opens „Sprawdź wpisy (3)”, with three ticked proposals that share the time and each carry its own date and weekday. The parent can untick proposals, fix fields, or correct one proposal by text (S-03). One „Zapisz wpisy” saves the selected proposals all-or-nothing, and the saved panel lists them. Single-entry instructions behave exactly as today.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
| --- | --- | --- | --- |
| Timezone and relative dates | Europe/Warsaw reference date; weeks start Monday; „w przyszłym tygodniu w X” = next calendar week; a bare weekday = next occurrence, so the same weekday = next week's; a day and month with no year = nearest date on or after today; S-20's `DATE_RULES`, reused unchanged (owner-confirmed 2026-10-04) | This matches Polish usage and the existing contract, with no hand-written parser. | Owner |
| Ambiguous or colliding dates | Missing date highlighted; identical proposals get a non-blocking duplicate hint; nothing is auto-dropped | The Sunday case ("tomorrow" = "next Monday") stays visible and the parent decides. | Assumed (owner to confirm) |
| Confirmation | One review page, an „Uwzględnij” checkbox per proposal, one save action | US-05 asks for every proposal to be reviewed before saving, and it is quick on a phone. | Assumed (owner to confirm) |
| Partial save | All-or-nothing in one transaction (owner-confirmed 2026-10-04); per-proposal keys make a replay idempotent; duplicate keys within a batch are rejected | No half-saved batch for the parent to reconcile. | Owner |
| Batch size | At most 10; more falls back to the note review with a notice | This bounds tokens, page length and runaway expansion. | Assumed (owner to confirm) |
| Missing values in a batch | Highlighted per proposal; no question round (single results keep the question step) | The fields are already on screen, and the follow-up contract stays intact. | Assumed (owner to confirm) |
| Invalid proposal in a batch | The whole instruction falls back to the single-note review | No proposal from rejected model output reaches the parent, and nothing is silently dropped. | Assumed (owner to confirm) |
| Correction target (with S-03) | A per-proposal „Popraw tekstem” box targets that proposal only; only the target is validated; corrections apply only before saving and a non-blank correction blocks „Zapisz wpisy” (owner-confirmed 2026-10-04) | Deterministic targeting; the other proposals are carried through unchanged. | Assumed (owner to confirm) / Owner |
| Per-output pipeline | One shared `_finish_parent_output` (S-02 mention → S-01 subject rule → member resolution) for single, batch and correction; one `_translate_entry` (grounding → S-20 title guard) per entry | Single and batch results cannot diverge. | Research |
| Backend seam | Optional `classify_many`; single-output backends are treated as one-item batches | Existing fakes, follow-up, EduVulcan and the smoke command stay valid. | Research |
| Atomic save | Reuse `save_confirmed_entry` inside an outer `transaction.atomic()` | Savepoints keep its replay handling and add all-or-nothing behaviour. | Research |

## Scope

**In scope:**
- OpenAI list schema, `MULTI_INSTRUCTIONS` (inheriting S-20's `DATE_RULES` once), per-entry `_translate_entry`, `_finish_parent_output`, `classify_entries_for_parent`, cap and fallbacks
- Batch review form, `entries:confirm_batch`, `save_confirmed_entries`, a multi-entry saved panel
- Per-proposal text correction wired to S-03's service and S-03's stable markup for S-05's Enter handling
- DEBUG states sections, the scripted PRD example in the acceptance corpus, the existing corpus re-run through the batch path, and a live check

**Out of scope:**
- Batches for EduVulcan, the REST API or structured create; recurring events
- One-by-one confirmation; partial save; a follow-up question in a batch; batch-wide correction
- A deterministic date parser; server-side drafts; JavaScript; schema changes

## Architecture / Approach

```
POST /entries/new/ → classify_entries_for_parent  [one provider call, list schema]
   ├─ 1 item  → existing proposal / question / unavailable flow (unchanged)
   ├─ >10     → note fallback + cap notice
   └─ 2..10   → state "batch": prefixed EntryReviewForms + „Uwzględnij”
POST /entries/confirm-batch/
   ├─ action=save        → save_confirmed_entries (atomic) → ?saved=a,b,c
   └─ action=correct-<i> → correct_proposal_for_parent(item i) (S-03) → re-render batch
```

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Multi-entry classification boundary | List schema, per-entry translation, shared pipeline, batch service, tests | The list schema regresses single-entry quality; the one-item equivalence tests and the live check guard against it. |
| 2. Batch review and all-or-nothing save | Batch form, endpoint, atomic save, saved panel | A tampered multi-form; mitigated by the count bound, family-scoped fields and service re-validation. |
| 3. Per-proposal free-text correction | `correct-<i>` action using S-03 | Carrying unvalidated sibling proposals through a correction; mitigated by re-validation on save. |
| 4. States page, acceptance, live check | Kitchen-sink sections, PRD example corpus, live run | Live model date arithmetic on edge weekdays. |

**Prerequisites:** S-01, S-02, S-20 and S-03 merged (confirmed order S-01, S-02, S-20, S-03, S-04, …). An OpenAI key is needed only for check 4.4.
**Estimated effort:** ~3–4 after-hours sessions across 4 phases.

## Open Risks & Assumptions

- Owner review 2026-10-04 confirmed the decisions listed under "Owner Decisions (2026-10-04)" in plan.md; remaining assumed rows stand unless the owner objects.
- Owner decisions from the plan review were applied on 2026-10-04; the roadmap status is `planning`. Remaining "Assumed" rows stand unless the owner objects.
- **Interaction with S-03:** correction always targets one proposal chosen in the UI, and the model never selects the target. S-03 lands before S-04.
- `DATE_RULES` is created by S-20 (`entries/classification/openai_backend.py`) and reused unchanged by S-03 and S-04. Changing it alters single-entry date behaviour too.
- With the OpenAI backend, single-entry capture now also uses the list schema; the existing corpus is re-run through the batch path and check 4.4 covers live single-entry quality.
- The model, not code, computes dates. Grounding drops invented dates, and the parent's review with weekday labels is the last guard.
- The whole-batch note fallback on one invalid proposal may feel strict. It is the conservative choice until the owner decides otherwise.

## Success Criteria (Summary)

- The PRD three-meetings instruction yields three proposals at 18:00 with the expected dates, and saving creates exactly the selected entries.
- No batch is ever partially saved, and a double-submit creates nothing new.
- Single-entry capture, follow-up and EduVulcan behaviour are unchanged.
