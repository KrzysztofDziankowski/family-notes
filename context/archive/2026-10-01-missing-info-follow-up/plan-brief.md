# Missing Information Follow-Up — Plan Brief

> Full plan: `context/changes/missing-info-follow-up/plan.md`

## What & Why

Roadmap slice S-04. The PRD says that when a required value is missing, the application asks a follow-up question before presenting the proposal for confirmation. S-01 left a placeholder: a follow-up result goes straight to the review form with the missing field highlighted. This slice turns that into a real question the parent answers in free text, keeping capture conversational and fast.

## Starting Point

Classification already detects missing values (date; person; ambiguous person) using the PRD rules, and returns a transient follow-up result. The capture flow keeps no state between steps: the draft travels in form fields, and `confirm` re-validates everything before saving.

## Desired End State

"Kasia ma kartkówkę z matematyki" leads to the question „Kiedy jest „Kartkówka z matematyki”?” with one text field, „Dalej” and „Pomiń”. Answering „w piątek” shows the normal proposal with the date filled in. An unhelpful answer or a provider failure shows the S-01 highlighted review form. „Pomiń” shows the review form prefilled as a note. Nothing is saved before confirmation, and each screen meets the 30-second NFR.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) |
| --- | --- | --- |
| How the parent answers | Free text, classified again together with the original instruction and the question | Keeps the single-text-field, dictation-friendly experience. |
| Several missing values | One combined question and one answer field | At most one extra round-trip and the simplest state handling. |
| What the answer may change | Only the missing values; type, title, school item, time and known values come from the first draft | The answer cannot silently rewrite something the parent wasn't asked about. |
| Still missing or provider failure | Fall back to the S-01 highlighted review form (notice on failure); no second question | Bounded to one extra model call; the parent is never stuck. |
| Skip | „Pomiń” → review form prefilled as a note, keeping the known date/time/person and dropping the school item; the parent still confirms | Nothing is lost when the information is unknown, and FR-005 confirmation still applies. |
| Draft between steps | Untrusted hidden fields; missing list recomputed on the server; confirm re-validates | Matches S-01's "nothing stored before confirmation" rule. |
| Provider input | Optional `pytanie_uzupelniajace` / `odpowiedz_rodzica` keys, absent when there is no follow-up | Requests without a follow-up stay identical to today, so the privacy surface doesn't change. |

## Scope

**In scope:**
- Backend request fields, OpenAI input and instructions, and the `classify_follow_up_answer` merge service
- Polish question copy, the answer form, the `question`/`skipped` states and the `entries/answer/` endpoint
- Service, adapter, view, access and privacy tests, plus an acceptance-style answer case
- DEBUG states page sections, 360 px screenshots and one live OpenAI check

**Out of scope:**
- New follow-up rules beyond the PRD (roadmap open question stays open)
- A second question round, or re-classifying the whole instruction
- Follow-ups for EduVulcan intake (it keeps saving general notes)
- Server-side draft storage, JavaScript, schema changes
- Telling apart two members with the same display name

## Architecture / Approach

```
POST /entries/new/ → classify_for_parent
   ├─ proposal / unavailable → review form (unchanged)
   └─ follow_up → question state (FollowUpAnswerForm: hidden text + draft, visible answer)
POST /entries/answer/
   ├─ action=skip → review form as note (+ notice)
   └─ classify_follow_up_answer(text, draft, answer)  [one provider call, merge missing only]
        ├─ proposal → review form
        ├─ still missing → highlighted review form
        └─ unavailable → highlighted review form from draft (+ notice)
POST /entries/confirm/ → unchanged, idempotent save
```

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Follow-up answer classification | Request fields, adapter input, merge service, tests | Unrelated fields in the answer's result veto it. Mitigated by merging first (draft + asked fields only) and validating once. |
| 2. Question step in the capture flow | Answer form, `question`/`skipped` states, `entries/answer/`, view tests | Tampered hidden draft. Mitigated by family-scoped fields and confirm re-validation. |
| 3. States page and screenshot gate | Kitchen-sink sections, 360 px screenshots, live check | Manual gate; live relative-date answers depend on the model. |

**Prerequisites:** F-02 and S-01 done (archived). An OpenAI key only for the live check in 3.4.
**Estimated effort:** ~2–3 after-hours sessions across 3 phases.

## Open Risks & Assumptions

- Two family members with the same display name can't be told apart by a typed answer. That case falls back to the review form, where both appear under the same label (an existing S-01 limitation).
- Relative dates in the answer are computed by the model from the reference date. The parent can correct them in the review form.
- Changing the S-01 follow-up branch changes the existing follow-up view test, which is updated in phase 2.
- A time given in the answer („w piątek o 8:00”) is not taken, because time is never a missing field. The parent adds it in the review form (accepted in plan review).
- The answer is family text and gets the same no-logging and no-retention handling as the instruction.

## Success Criteria (Summary)

- A parent answers one question in free text and reaches a complete proposal that saves exactly one entry.
- An unknown answer, a provider failure or a skip never leaves the parent stuck, and nothing is saved without confirmation.
- Requests without a follow-up send exactly the same data to OpenAI as before.
