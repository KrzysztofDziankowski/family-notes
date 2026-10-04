# Free-Text Proposal Correction — Plan Brief

> Full plan: `context/changes/free-text-proposal-correction/plan.md`

## What & Why

This is future roadmap slice S-03 (PK-10, US-10). Today a parent can fix a proposal only by editing form fields. Typing a fix such as „zmień datę na 15 października” is faster on a phone, and it fits the dictation-first capture flow. The correction must change only what it mentions and keep everything else.

## Starting Point

Capture is stateless: classify, then review (a form with hidden values), then confirm (re-validated, idempotent save). The follow-up answer flow already merges a second model call into a draft by taking only the asked fields. That merge-before-validate pattern and the date-grounding check are reused here.

## Desired End State

Every capture review form has a „Popraw opis” box and a „Popraw” button. One model call interprets the correction against the proposal currently on screen, including the parent's manual edits. Only the fields the model lists as changed are applied, and the revised proposal comes back for confirmation with a notice naming the changed fields. A failed or unclear correction leaves the proposal untouched and shows a notice. Nothing is saved until „Zapisz wpis”.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
| --- | --- | --- | --- |
| When correction is available | Only before saving, on the capture review form (owner-confirmed 2026-10-04) | This is the smallest scope that satisfies PK-10; saved entries already have manual edit. | Owner |
| Target in a multi-proposal result | One proposal, chosen in the UI (a correction box per proposal), delivered by S-04 | Deterministic targeting means a correction never lands on the wrong entry. | Assumed (owner to confirm) |
| Correctable fields | Type, title, school type, subject, date, time, person; a school type that does not fit the resulting entry type rejects the correction with a Polish message and the proposal stays unchanged (owner-confirmed 2026-10-04) | PK-10 says "any other entry field", and S-01 makes the school type and subject visible with a strict mismatch rule. | Owner |
| Preserving unmentioned fields | The model returns `changed_fields`; a deterministic merge applies only those | A full-output diff would let the model rewrite fields it was not asked about. | Research |
| Date safety | The new date must be grounded in the correction text; an explicit clear is allowed | This reuses the invented-date protection from follow-up. | Research |
| Relative dates | S-20's `DATE_RULES` reused unchanged (Europe/Warsaw; weeks start Monday; „w przyszłym tygodniu w X” = next calendar week; a bare weekday = next occurrence, so the same weekday = next week's; day and month without year = nearest on or after today); only „a shift counts from the current date” is correction-specific (owner-confirmed 2026-10-04) | This matches Polish usage and keeps one rule set across slices. | Owner |
| Failure / no-op | Keep the proposal, keep the correction text, show a notice; no question round | The parent never loses edits or gets stuck. | Assumed (owner to confirm) |
| Unapplied correction on „Zapisz wpis” | Saving is refused with „Masz niezastosowaną poprawkę — naciśnij „Popraw” albo wyczyść pole.”; nothing is saved (owner-confirmed 2026-10-04) | Nothing is saved that differs from what the parent asked for. | Owner |
| Enter in „Popraw opis” | Triggers „Popraw”; S-05 writes the JS against this slice's stable markup (button `id`, textarea `data-enter-submitter`) (owner-confirmed 2026-10-04) | Phone dictation flow; no JS in this slice. | Owner |
| Upstream contracts | Carry S-01 `school_subject`, S-02 `member_mention` (applied only when the person changes) and run S-20's title guard only when the title changes | Unmentioned fields stay byte-for-byte. | Research |
| State and keys | Posted form only; a fresh `submission_key` on each re-render | Keeps the stateless, idempotent confirm design. | Research |
| Provider input | Current values, display names, the reference date and the correction; never the original instruction | This is the minimum data and keeps the classification-purpose limit. | PRD |

## Scope

**In scope:**
- `ProposalValues` (with S-01 school item and subject), backend request/output fields, the OpenAI correction schema, input and instructions (appending S-20's `DATE_RULES`)
- The `correct_proposal_for_parent` merge service, plus service and adapter tests
- The correction box on the review form (with stable markup for S-05's Enter handling), the `entries:correct` endpoint, notices, the `confirm` refusal of an unapplied correction, and view, access and privacy tests
- DEBUG states sections, a scripted acceptance case, and one live check

**Out of scope:**
- Correcting saved entries; structured create and edit; EduVulcan conversions
- Batch-wide corrections; splitting or adding proposals (per-proposal wiring lives in S-04)
- New school fields (S-01) or `DATE_RULES` wording (S-20); JavaScript (S-05); server-side drafts; schema changes

## Architecture / Approach

```
review form (any capture state) ──„Popraw”──▶ POST /entries/correct/
   ProposalCorrectionForm (format + family scope only)
   → correct_proposal_for_parent(current values, correction)   [one provider call]
       adapter: StructuredCorrection + changed_fields, ungrounded date dropped from changed_fields
       merge: changed fields from output, everything else from current → validate once
   ├─ applied → review form (proposal / follow_up highlights) + „Zaktualizowano: …”
   └─ not applied → same values + kept text + notice
„Zapisz wpis” → POST /entries/confirm/ (unchanged)
```

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Correction classification service | Contract fields, correction schema and prompt, merge service, tests | The model lists the wrong `changed_fields`; mitigated by the deterministic merge, grounding, and the parent's final review. |
| 2. Correction step in the capture review | Correction form, `entries:correct`, partial, view tests | Schedule-rule errors blocking a correction that adds a date; mitigated by the format-only form. |
| 3. States page and live check | Kitchen-sink sections, acceptance case, live run | Live model quality on Polish declension („Tymka” → Tymek). |

**Prerequisites:** S-01, S-02 and S-20 merged (confirmed order S-01, S-02, S-20, S-03, S-04, …). An OpenAI key is needed only for check 3.4. Recommended order: implement before S-04 Phase 3, which reuses this service.
**Estimated effort:** ~2–3 after-hours sessions across 3 phases.

## Open Risks & Assumptions

- Owner review 2026-10-04 confirmed the decisions listed under "Owner Decisions (2026-10-04)" in plan.md; remaining assumed rows stand unless the owner objects.
- Owner decisions from the plan review were applied on 2026-10-04; the roadmap status is `planning`. Remaining "Assumed" rows stand unless the owner objects.
- **Interaction with S-04:** in a multi-proposal review, each proposal has its own correction box that calls this same service for that proposal only. A batch-wide correction is out of scope for both slices.
- The shared `DATE_RULES` constant is created by S-20 (`entries/classification/openai_backend.py`); S-03 and S-04 reuse it unchanged.
- Correction quality depends on the model's `changed_fields`; the parent always reviews the result before saving.
- The correction text is family text and gets the same no-logging and `store=False` handling as the instruction.

## Success Criteria (Summary)

- „zmień datę na 15 października” changes only the date of the proposal on screen, and saving produces one entry with that date.
- A complete general note can be turned into a dated todo by text, keeping its title.
- An unclear correction never changes or loses the proposal.
- „Zapisz wpis” never silently drops a typed but unapplied correction.
