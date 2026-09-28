# Parent Family Entry Management — Plan Brief

> Full plan: `context/changes/parent-family-entry-management/plan.md`

## What & Why

Give parents full lifecycle control over saved family entries, as required by FR-006, while maintaining strict family isolation from FR-008. This turns S-01's captured entries into a usable shared family-management surface.

## Starting Point

S-01 already supplies the entry schema, natural-language capture, validation, family-scoped saving, and shared visual tokens. General listing, details, structured creation, editing, and deletion do not exist.

## Desired End State

A parent can browse upcoming or past entries, open details, create directly, correct any editable value—including school subtype—and permanently delete an entry. Automated-entry provenance remains visible and immutable, while children and outsiders cannot access these management paths.

## Key Decisions Made

| Decision | Choice | Why |
| --- | --- | --- |
| Create experience | Structured form plus existing capture | Parents requested a precise direct-entry option without removing the product's primary capture flow. |
| Reading surface | List plus stable detail page | Keeps the timeline compact while providing room for actions and provenance. |
| Default timeline | Upcoming, then undated | Prioritizes current commitments while keeping undated information reachable. |
| History | Separate past mode | Past entries remain manageable without crowding the default view. |
| Editable data | Core fields plus school subtype | Parents can correct both general and school-specific classification. |
| Deletion | Permanent POST with inline HTML disclosure | Provides confirmation without JavaScript or a separate page. |
| Provenance display | Source and timestamps | Explains automated entries and corrections without exposing internal identifiers. |
| Pagination | None for MVP | The PRD explicitly targets one small family and low data volume. |

## Scope

**In scope:**

- Parent-only upcoming/past index and detail pages.
- Structured create, edit, and permanent delete.
- Natural-language capture link.
- School subtype editing.
- Source and timestamp display.
- Full authorization and family-isolation tests.
- Mobile state gallery and screenshot gate.

**Out of scope:**

- Child views, soft delete, undo, audit history, search, filters beyond upcoming/past, pagination, bulk operations, and schema changes.

## Architecture / Approach

Views authenticate the active parent and delegate to family-scoped services. Shared form validation feeds capture, structured creation, and editing. Templates reuse the current Pico/token system; provenance is read-only, and every mutation uses CSRF-protected POST plus POST/redirect/GET.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Management contracts | Reusable forms and secure CRUD services | Validation diverges from capture or provenance is overwritten. |
| 2. CRUD routes and UI | Timeline, detail, create, edit, delete, navigation | A foreign entry leaks through an unscoped lookup. |
| 3. Verification | Access matrix, regressions, mobile visual gate | Happy-path coverage misses a denial or lifecycle case. |

**Prerequisites:** Implemented S-01 entry model/capture and F-01 access helpers.
**Estimated effort:** Approximately 3 implementation sessions across 3 phases.

## Open Risks & Assumptions

- The roadmap status for S-01 is stale, but its implementation and review artifacts show the prerequisite is complete.
- Hard deletion is intentionally irreversible; no audit or recovery requirement exists.
- Existing entries require no migration.
- The small-family volume remains within an unpaginated view.

## Success Criteria (Summary)

- A parent completes structured create, browse, detail, edit, and delete flows on mobile.
- Upcoming, undated, and past entries are partitioned and ordered deterministically.
- Every read and mutation enforces active-parent and family scope, with no foreign-entry disclosure.
- Existing capture, classification, automation intake, and family-access behavior remains green.
