# School Event Details — Plan Brief

> Full plan: `context/changes/school-event-details/plan.md`

## What & Why

Parents want to see which school event type (kartkówka, sprawdzian, praca klasowa or zadanie domowe) a classified entry is, and to correct it during review. Each of these four kinds must also have a date, an assigned family member and a school subject. Anything missing is asked for before confirmation (PK-08, PK-09, US-08, US-09).

## Starting Point

The four school kinds already exist and already require a date and a member (`entries/classification/types.py:43-46`). The capture review form hides the school type (`entries/forms.py:114-118`), while the edit form shows it (`entries/forms.py:169-173`). There is no school subject anywhere. EduVulcan rules already parse the subject but only fold it into the content (`entries/eduvulcan/rules.py:166-181`).

## Desired End State

Capture review shows an editable school type and subject. A school event without a subject triggers a Polish follow-up question ("Z jakiego przedmiotu…?"). Confirm and create refuse to save a school event without a subject; edit requires one only if the entry already had one or the parent sets/changes the school kind. Automated EduVulcan intake keeps working unattended and stores the subject when the notification provides it. Old entries render and read through the API unchanged, and the API also returns `school_subject`.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
| --- | --- | --- | --- |
| School type in review | Visible, editable select with a strict mismatch error, same as the edit form | One consistent control, as PK-08 asks for "reviewing or editing" | Assumed (owner to confirm) |
| Subject vocabulary | Free text, at most 100 characters | EduVulcan gives subjects verbatim, and school lists vary | Owner |
| Where the subject is required | Only the four event kinds, only on parent capture, create and edit | Matches PK-09 without widening it | Assumed (owner to confirm) |
| Existing entries | No backfill; a blank subject stays valid | No data migration risk | Owner |
| Subject on edit | Required only if the entry already had a subject or the parent sets/changes the school kind; always required on capture and manual create | Unrelated edits of automated EduVulcan events never fail (review F1) | Owner |
| Automated intake | Never requires a subject; rules fill it when present; never downgraded to a note | Unattended intake cannot ask questions | Assumed (owner to confirm) |
| API | Additive `school_subject` key | Backward compatible for existing consumers | Assumed (owner to confirm) |
| Missing value handling | Follow-up question before confirmation | Explicit in US-09 | PRD |
| Gating mechanism | `SCHOOL_SUBJECT` in kind `required_fields` plus an explicit `require_school_subject` / `require_subject` flag per caller | `classify_for_family` turns follow-ups into notes (`entries/classification/service.py:369-371`) | Research |
| Rollback safety | `default=''` + `db_default=''` migration | Established pattern (`entries/models.py:133-138`) | Research |

## Scope

**In scope:**
- `Entry.school_subject` column and migration
- `MissingField.SCHOOL_SUBJECT` and its follow-up question
- Classifier schema, validation and merge
- Review, create and edit forms, and the follow-up draft
- Detail pages (parent and child)
- DEBUG state galleries
- Subject from EduVulcan calendar rules
- API key and admin list

**Out of scope:**
- A subject vocabulary or picker
- Backfill
- A subject for grades or timetable changes
- List row and filter changes
- JavaScript show/hide
- Free-text correction (S-03) and multi-entry capture (S-04)

## Architecture / Approach

The subject is added like the existing date and member requirements: once in `SchoolItemKind.required_fields`, then enforced in classifier validation, form validation, follow-up draft reconstruction and service invariants. Each layer receives an explicit parent-versus-automated flag, so the EduVulcan worker and `classify_for_family` never ask for it or reject it. The review form's school item becomes visible and reuses the management form's strict validation.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Subject data model and invariants | Column, migration, `SCHOOL_SUBJECT`, service rule with automated exemption | Accidentally enforcing the rule on automated writes |
| 2. Classification asks for the subject | Schema field, gated validation, answer merge, Polish question | Regressing EduVulcan classified events into notes |
| 3. Parent review and management UI | Visible school type, subject field, follow-up draft, details, galleries | Strict mismatch in review surprising parents who change the type |
| 4. Automated intake and read compatibility | Rule-based subject, API key, admin, full regression | Over-long parsed subjects failing a save (mitigated: left blank) |

**Prerequisites:** none in code. This is slice S-01 with no slice prerequisites; roadmap status is `planning`, and owner decisions from the plan review were applied 2026-10-04. Confirmed order: S-01, S-02, S-20, S-03, S-04, S-05, S-06, S-07, S-08, S-09, S-17, S-14, S-15, S-16. S-01 lands first; S-02, S-20 and S-03 build on its schema field, `INSTRUCTIONS` sentence and `BackendOutput` field.
**Estimated effort:** about 3–4 sessions across 4 phases.

## Open Risks & Assumptions

- Owner review 2026-10-04 confirmed the decisions listed under "Owner Decisions (2026-10-04)" in plan.md; remaining assumed rows stand unless the owner objects.
- Owner decisions from the plan review were applied 2026-10-04 (subject on edit, review F1). Remaining Assumed rows (PRD Questions 1, 9, 12 and 20) stand unless the owner objects.
- `classify_output` gains a required keyword; the smoke command and the skipped live-wire tests must be updated too (review F2).
- Model extraction quality for subjects (inflected forms such as "z matmy") relies on the provider. The parent reviews and can correct the subject before saving.
- Changing the structured schema invalidates scripted adapter fixtures in `test_openai_backend` and `test_classification_acceptance`, which must be updated deliberately, not loosened.

## Success Criteria (Summary)

- Reviewing a classified kartkówka, sprawdzian, praca klasowa or zadanie domowe shows its type and subject, and a missing date, person or subject is asked for before saving.
- EduVulcan school notifications still become calendar entries unattended, now with a subject when available.
- Existing entries, child views and API consumers keep working unchanged.
