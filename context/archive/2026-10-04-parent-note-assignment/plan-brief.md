# Parent Note Assignment — Plan Brief

> Full plan: `context/changes/parent-note-assignment/plan.md`

## What & Why

S-07 (PK-03, US-03): a parent must be able to assign a new note to themselves or to the other parent, not only to a child. The feature appears to exist already. The goal is to make it *reliable*: prove it end to end, and fix only what the proof shows broken.

## Starting Point

All parent write paths (review, structured create, edit, follow-up) offer every active member of the family as an assignee, parents included (`entries/forms.py:84`). The services check only family and active status (`entries/services.py:91`), and classification sends parent names to the backend (`entries/classification/service.py:243`). No test covers it, though: every fixture family has exactly one parent. Free text such as "dla mnie" yields an unassigned proposal, because the classifier is not told who is asking.

## Desired End State

A two-parent regression matrix proves self and other-parent assignment across create, capture/confirm, edit, list, detail, and API. It also proves that children never see such entries and that foreign-family parents are rejected. The DEBUG gallery shows a parent assignee, so the screenshot gate covers the slice. "dla mnie: kupić mleko" produces "Kupić mleko" assigned to the requesting parent.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
| --- | --- | --- | --- |
| Approach | Verification-first; code changes only for failing tests | The roadmap requires that only demonstrated gaps be fixed, and code inspection shows none. | Research |
| Paths covered | Manual creation, classification review, follow-up, S-03 correction, S-04 batch save | Both share `EntryFieldsForm`, so excluding one would be a regression. | Assumed (owner to confirm) |
| Entry types | All types keep accepting parent assignees | The form is type-agnostic today, and narrowing it to notes would remove behavior. | Assumed (owner to confirm) |
| "dla mnie" self-reference in text | Resolved to the requesting parent via one new payload key `autor_polecenia`, sent on capture and on S-03 corrections ("przypisz mnie"); the title drops the phrase (owner-confirmed 2026-10-04) | The owner wants natural-language self-assignment; the requester's name is already in `dozwolone_osoby`, and member validation is unchanged. | Owner |
| EduVulcan intake | Stays child-only | US-03 covers parent-created notes only. | Assumed (owner to confirm) |
| Dropdown labels | Unchanged display names, no "(ja)" marker | No demonstrated need. | Assumed (owner to confirm) |
| Fixtures | Second parent added locally in new test classes | Avoids churn in exact-member assertions across the suite. | Research |

## Scope

**In scope:** two-parent regression tests at the form, service, classification (incl. follow-up, S-03 correction, S-04 batch), view, API, and child-isolation layers; minimal fixes for failing tests; gallery parent assignee plus a screenshot; self-reference resolution (`autor_polecenia` payload key, Polish instruction, title guard, tests, live check).

**Out of scope:** requester key on follow-up answers or EduVulcan classification (S-03 corrections do get it — owner-confirmed 2026-10-04); any change to member validation; role markers, parent "my entries" view, parent-assigned EduVulcan entries, migrations.

## Architecture / Approach

Phases 1–2 add tests only, on top of the existing contracts: `EntryFieldsForm` (choices), `_validate_entry_invariants` (service guard), `_active_family_members` and `_resolve_member` (classification), `_entry_row.html` (display), and `child_entries` (isolation). A red test is treated as a bug in the owning module and is never fixed by editing the assertion. Phase 3 adds `BackendRequest.requester_name` (set only by the parent capture services), `autor_polecenia` in `build_input`, one Polish INSTRUCTIONS sentence, and a `self_reference` option on S-20's `strip_extracted_phrases`. This changes the data sent to OpenAI (owner-approved 2026-10-04), and the adapter's privacy docstring records it.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Two-parent regression matrix | Proof of self and other-parent assignment and isolation, plus fixes if anything fails | A hidden role assumption surfaces and grows the fix |
| 2. Gallery coverage and manual check | Parent option and row in the DEBUG gallery, phone-width check, screenshot | None significant |
| 3. Self-reference resolves to the requester | "dla mnie" → requesting parent, phrase dropped from title, payload contract updated, live check | Model maps "mi"/"ja" inconsistently; the guard and live check bound it |

**Prerequisites:** S-02, S-20, S-03 and S-04 land first (confirmed order S-01, S-02, S-20, S-03, S-04, S-05, S-06, S-07, S-08, …); Phase 3 builds on S-02's `member_mention` and S-20's title rule and guard. S-08 later groups parent-assigned rows.
**Estimated effort:** ~1–2 sessions across 3 phases.

## Open Risks & Assumptions

- Owner review 2026-10-04 confirmed the decisions listed under "Owner Decisions (2026-10-04)" in plan.md; remaining assumed rows stand unless the owner objects.
- Owner decisions from the plan review were applied 2026-10-04. Rows still marked "Assumed" stand in for PRD Open Questions 1, 4, 12, and 20 and stand unless the owner objects.
- Phase 3 changes the data sent to OpenAI (one key, `autor_polecenia`, holding a name already sent in `dozwolone_osoby`); owner-approved 2026-10-04.
- If the Phase 1 matrix is all green, Phases 1–2 deliver proof and gallery coverage with no production code change; Phase 3 is the slice's only planned production change.

## Success Criteria (Summary)

- A parent can assign a new note to themselves or to the other parent through both the structured form and text capture, and sees that assignee in the list and detail.
- Writing "dla mnie" assigns the proposal to the requesting parent, with the phrase removed from the title.
- Children never see parent-assigned entries, and a parent from another family can never be assigned.
