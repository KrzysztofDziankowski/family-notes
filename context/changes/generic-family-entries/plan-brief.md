# Generic Family Entries — Plan Brief

> Full plan target: `context/changes/generic-family-entries/plan.md`

## What & Why

Use one entry concept throughout FamilyNotes. Remove broad classification and selection overhead while preserving school information.

## Starting Point

Entries already share storage and chronological browsing. Broad types still control several extraction and validation paths, and old workers can write during the current deployment procedure.

## Desired End State

Every existing and new entry is generic. People review what, who, and when, with school details where relevant. Ordinary entries may remain undated.

## Key Decisions Made

| Decision | Choice | Why |
| --- | --- | --- |
| Existing entries | Convert every row | Explicit owner request |
| New entries | Server assigns generic | Removes broad type decisions |
| Legacy constants | Dormant only | Preserves a future option without active behavior |
| Ordinary dates | Optional | Confirmed during planning |
| School details | Preserve controls and requirements | Retains useful information and validation |
| REST response | Keep shape; type value becomes generic | Limits interface changes |
| Migration reversal | Explicitly irreversible | Original categories cannot be inferred |
| Rollout | Maintenance deployment | Prevents old writers recreating legacy types |

## Scope

**In scope:** generic producers, forms, presentation, admin, data conversion, storage enforcement, compatibility handling, documentation, and verification.

**Out of scope:** task completion, reminders, integrations, future type activation, feature flags, and new E2E infrastructure.

## Architecture / Approach

Update active contracts and producers first, remove UI choices, then convert stored rows and enforce generic-only storage. School metadata supplies its own validation requirements.

## Phases at a Glance

| Phase | Deliverable | Key risk |
| --- | --- | --- |
| 1 | Generic contracts and producers | Accidentally bypassing school validation |
| 2 | Generic forms and presentation | Stale POST fields or leftover controls |
| 3 | Converted data and storage constraint | Loss of unrelated fields or broken migration tests |
| 4 | Verification and release readiness | Old workers writing during migration |

**Prerequisites:** existing capture/correction/batch contracts; PostgreSQL rehearsal and maintenance-deployment work before rollout.

**Estimated effort:** approximately 4–6 focused sessions, excluding prerequisite deployment work and production acceptance.

## Open Risks & Assumptions

- External consumers must tolerate the intentional `"generic"` value; the response structure remains stable.
- Category loss is intentional; no original-type shadow field is added.
- Intermediate phases form one release and are not deployed separately.

## Success Criteria

- All saved entries are generic and broad type controls disappear.
- School requirements, access boundaries, and notification behavior remain correct.
- Migration preserves every non-type field and relationship.

## References

S-21, its change identity, and the full plan’s code and Django documentation references.
