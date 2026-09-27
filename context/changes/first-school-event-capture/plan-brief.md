# First School Event Capture — Plan Brief

> Full plan: `context/changes/first-school-event-capture/plan.md`

## What & Why

Roadmap slice S-01, the north star. A parent types one natural-language instruction (e.g. "Michał ma w poniedziałek sprawdzian z biologii o skórze"), reviews the classified proposal, corrects it if needed, confirms it, and it is saved as a family entry. This slice is the first product proof that fast capture becomes family data (US-01), and it introduces the entry model that S-02, S-03 and S-05 build on.

## Starting Point

F-01 provides families, parent/child roles and scoped-access helpers. F-02 provides `classify_for_parent()`, which returns a transient proposal, follow-up or unavailable result and never writes rows. There is no `Entry` model, no product view, no base template or static assets, and settings are `en-us`/UTC.

## Desired End State

At `/entries/new/` a parent submits text, sees an editable proposal within 30 s, confirms it, and lands on "Dodano wpis" showing the saved entry, with the field ready for the next capture. Exactly one entry is saved per confirmation, even on a double tap. Children and outsiders cannot use the flow. Pages share vendored Pico CSS plus a single token stylesheet, and every state has been screenshotted at phone width.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) |
| --- | --- | --- |
| Proposal state between steps | Stateless editable form; confirm is re-validated server-side | Nothing about the instruction is stored before confirmation, which fits the "no secondary storage" rule. |
| Follow-up / unavailable outcomes | Prefilled form (missing fields highlighted, or a note containing the original text); too-long input shows an error only | The parent is never stuck; S-04 later replaces the follow-up branch with a real question. |
| Entry types in scope | All three (todo, calendar event, note) | Classification already returns them and the general-note fallback is PRD logic; tests focus on US-01. |
| Double confirm | One-time `submission_key` stored uniquely on the entry | Guarantees one entry per proposal and covers the infra doc's retry-duplicate risk. |
| Capture location | Separate `/entries/new/`, linked from account status | Leaves `/` and the login redirect untouched. |
| UI foundation | Pico CSS v2 vendored + `tokens.css` + `base.html` | Classless styling for Django forms with no build step and no third-party request; one token source for later views. |
| S-05 openness | `source` field (`manual`/`eduvulcan`), no stored confirmation flag, nullable key/creator | S-05 can save automated entries on the same model without a schema redesign. |
| Local date | `TIME_ZONE='Europe/Warsaw'`, `LANGUAGE_CODE='pl'` | Relative dates like "w poniedziałek" must use the Polish calendar day. |

## Scope

**In scope:**
- `Entry` model, migration, read-only admin, and a family-scoped idempotent save service
- Capture views, forms and templates for all states (proposal, follow-up, unavailable, invalid, saved)
- Vendored Pico, token stylesheet, base template, Polish locale and Warsaw timezone
- Tests for access, re-validation, idempotency, privacy logs, and the US-01 acceptance case
- A DEBUG-only kitchen sink plus the screenshot gate

**Out of scope:**
- Conversational follow-up question (S-04)
- Entry list, edit or delete (S-02)
- Child view (S-03)
- EduVulcan intake and dedup (S-05)
- Restyling `/`
- A screenshot test harness, CSS build step, JavaScript, or dark mode

## Architecture / Approach

```
GET/POST /entries/new/  --CaptureForm--> classify_for_parent(user, text, localdate)
        └─ proposal | follow_up | unavailable → EntryReviewForm (prefilled + fresh submission_key)
POST /entries/confirm/  --EntryReviewForm (family-scoped, rules re-checked)-->
        save_confirmed_entry() [atomic, idempotent on submission_key] → redirect ?saved=<pk>
```

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Entry model and save service | Table, constraint, admin, family-scoped idempotent writer | Model too narrow for S-05. Mitigated by the source marker and nullable fields. |
| 2. UI foundation | Pico + tokens + `base.html`, Polish locale, Warsaw time zone | Existing English-string tests and allauth pages change language. |
| 3. Capture flow | Classify → review/correct → confirm, with all fallbacks and US-01 acceptance | Tampered hidden fields. Mitigated by full server-side re-validation. |
| 4. Kitchen sink and screenshot gate | Every state on one DEBUG-only page, 360 px screenshots | The gate is manual, and states can drift if partials are copied rather than reused. |

**Prerequisites:** F-01 and F-02 done (archived). An OpenAI key is needed only for the live manual check in 3.11.
**Estimated effort:** ~3–4 after-hours sessions across 4 phases.

## Open Risks & Assumptions

- Switching `LANGUAGE_CODE` to `pl` changes allauth and admin strings; tests that assert English framework text must be updated.
- Pico's look is accepted as the baseline; tokens override colours and fonts only.
- Rolling back `entries 0001` drops saved entries, so it is safe only before real family data exists.
- `assigned_member` uses RESTRICT: deleting a family cascades its entries, but removing a person who has assigned entries is refused until they are reassigned.
- Under `pl`, date and time inputs must pin ISO formats (`%Y-%m-%d`, `%H:%M`), or the phone shows the classified date as empty.
- The relative-date arithmetic is the model's (F-02); the parent corrects it in the review form, which is in scope here.

## Success Criteria (Summary)

- On a phone, a parent turns the US-01 sentence into a saved calendar entry for Michał dated 2026-09-21 and sees "Dodano wpis".
- A double tap or retry never creates a duplicate, and a child or outsider can neither use the flow nor see the entry.
- When classification is down or incomplete, the parent can still save through the prefilled form.
