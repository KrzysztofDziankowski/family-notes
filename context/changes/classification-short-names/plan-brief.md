# Classification Short Names — Plan Brief

> Full plan: `context/changes/classification-short-names/plan.md`

## What & Why

Parents refer to family members by short names and diminutives ("Hania"), but the family members are stored under their full names ("Hanna"). Classification should assign the entry to the matching member of the parent's own family. If the short name could mean more than one person, the parent should be asked before anyone is assigned (PK-01, US-01).

## Starting Point

Classification sends the model the active family members' display names. It accepts the returned `member_name` only on an exact, case-sensitive allow-list match (`entries/classification/validation.py:61-71`). The result is resolved locally to one family member (`entries/classification/service.py:250-268`). "Hania" therefore either depends on the model silently substituting "Hanna" (even when "Anna" also fits) or fails as an unknown member. The clarification flow for ambiguous members already exists (`AMBIGUOUS_MEMBER`, "Której osoby dotyczy…?").

## Desired End State

"Hania ma jutro dentystę" in a family with Hanna produces a proposal with Hanna preselected. In a family with both Hanna and Anna, the parent is asked who is meant, and nobody is preselected. Answering a member question with a short name works the same way. Inactive and other-family names never resolve. EduVulcan intake is unchanged.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
| --- | --- | --- | --- |
| Source of mappings | Built-in, code-maintained Polish diminutive dictionary | Covers the example without a migration or alias-management UI | Owner |
| Matching rule | Two-tier: exact full or given name (case-insensitive) decides first; dictionary group only when nothing matches exactly; diacritics significant | Predictable; exact names never become questions (review F2) | Assumed (owner to confirm) |
| Ambiguous short name | Existing `AMBIGUOUS_MEMBER` clarification; never pick one | Required by PK-01 | PRD |
| No match | Unchanged (model's allow-listed name, else unknown-member note fallback) | Smallest change; keeps the safety tests | Assumed (owner to confirm) |
| Flows covered | Parent capture and follow-up answers only; not EduVulcan | School systems send full names; automation cannot ask | Assumed (owner to confirm) |
| How the name reaches us | Model returns a transient nominative `member_mention`; resolved locally against active family candidates | Polish inflection; the mention cannot add candidates | Assumed (owner to confirm) |
| Where ambiguity is decided | Locally, in the service, before validation, via a `member_ambiguous` flag | The provider has no way to signal ambiguity; local logic is deterministic | Research |
| Family scoping | Candidates only from `_active_family_members` | Existing isolation boundary (`entries/classification/service.py:243-247`) | Research |
| Follow-up answer | The answer text is matched first; the model's mention only as a fallback | Prevents an endless ambiguity loop (review F1) | Research |
| Release | No migration, no data change, no flag | Code-only and reverts cleanly | Owner |

## Scope

**In scope:**
- `entries/classification/names.py` matcher and dictionary
- `member_mention` in the output schema and `BackendOutput`
- The local resolution step for first classification and follow-up answers
- Ambiguity handling in validation
- Acceptance, service and view tests
- A DEBUG gallery state

**Out of scope:**
- Per-family nicknames or an alias model
- Fuzzy, phonetic or diacritic-insensitive matching
- Changing the no-match outcome
- EduVulcan matching
- Manual create/edit forms
- Any change to the data sent to OpenAI

## Architecture / Approach

The model additionally reports the person as the parent named them, in the nominative case. A pure matcher maps that mention to the family's active candidates. Exactly one match rewrites `member_name` to that member's exact display name. Several matches clear it and flag ambiguity, which validation turns into the existing clarification question. Zero matches leave today's exact allow-list validation in charge. `classify_for_family` does not use this step.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Deterministic short-name matcher | Pure matcher and diminutive dictionary with unit tests | Dictionary gaps for the family's actual names |
| 2. Classification resolves mentions | Schema field, local resolution, ambiguity flag, acceptance corpus | The model's pick overriding the parent's words (mitigated: the mention wins; in follow-ups the answer text wins) |
| 3. Capture flow regression and visual check | View tests, ambiguity gallery state, full regression | None significant; no UI change expected |

**Prerequisites:**
- S-01 (`school-event-details`) lands first; S-02 builds on its `BackendOutput.school_subject`, `require_school_subject` keyword and `_merge_answer` change. Confirmed order: S-01, S-02, S-20, S-03, S-04, S-05, S-06, S-07, S-08, S-09, S-17, S-14, S-15, S-16.
- Roadmap status is `planning`; plan-review fixes were applied 2026-10-04.
- S-20 (`title-keeps-action-only`) consumes S-02's `member_mention`; S-03 (`free-text-proposal-correction`) also extends `BackendOutput` and the adapter tests.

**Estimated effort:** ~2 sessions across 3 phases.

## Open Risks & Assumptions

- Owner review 2026-10-04 confirmed the decisions listed under "Owner Decisions (2026-10-04)" in plan.md; remaining assumed rows stand unless the owner objects.
- Plan-review fixes were applied 2026-10-04. Remaining Assumed rows (PRD Questions 2 and 12) stand unless the owner objects.
- A static dictionary will miss idiosyncratic nicknames. In that case the existing no-match behaviour applies, and the parent can still pick the person in review.
- The model may return a mention in the wrong grammatical case. This only causes a missed match (existing behaviour), never a wrong member, because only active family candidates can be selected.
- Changing the structured schema requires deliberate updates to the scripted adapter fixtures.

## Success Criteria (Summary)

- The recorded example resolves "Hania" to "Hanna" in the parent's family.
- A short name that fits two members always produces a clarification question before assignment.
- No member outside the parent's active family can ever be resolved, and automated intake behaves exactly as before.
