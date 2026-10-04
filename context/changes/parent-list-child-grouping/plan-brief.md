# Parent List Child Grouping — Plan Brief

> Full plan: `context/changes/parent-list-child-grouping/plan.md`

## What & Why

S-08 (PK-04, US-04): parents want the family entry list grouped by the child each entry is assigned to, so each child's upcoming matters are easy to scan. Parent-assigned and unassigned entries must stay discoverable.

## Starting Point

`/entries/` renders flat "Z datą"/"Bez daty" (upcoming) or "Minione" (past) sections from the shared `partition_entries` contract (`entries/listing.py:63`). Each row shows its assignee. The child view already does Python-side grouping (by day) after partitioning, which is the precedent for this change.

## Desired End State

The parent list shows one titled group per child, then per parent, then "Cała rodzina". Each group keeps the existing mode ordering. The mode switch, empty state, links, and family isolation are unchanged. Every entry appears exactly once.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
| --- | --- | --- | --- |
| Layout | Grouping replaces the flat list in both modes; no toggle (owner-confirmed 2026-10-04) | This is the smallest change that satisfies US-04 and keeps one layout to maintain. | Owner |
| Group order | Children (by pk) → parents (by pk) → "Cała rodzina" (owner-confirmed 2026-10-04) | Child groups come first as requested, in the same order as the assignee dropdown. | Owner |
| Parent-assigned entries | One group per parent, under their name | Uniform with child groups, and keeps S-07 assignments visible. | Assumed (owner to confirm) |
| Unassigned entries | Own "Cała rodzina" group, last | They stay discoverable without pushing child groups down. | Assumed (owner to confirm) |
| In-group ordering | Existing mode contract unchanged | Reuses the tested `partition_entries` ordering. | Research |
| Row assignee line | Hidden inside groups; the heading names the assignee | The existing `hide_assignee` option removes the duplication. | Research |
| Implementation | Pure `group_by_assignee` helper over partitioned sections | Mirrors `group_by_day`, adds no queries, and keeps scoping in callers. | Research |
| Inactive members | Group heading with " (nieaktywne konto)" | Reuses the existing suffix; entries stay visible. | Assumed (owner to confirm) |

## Scope

**In scope:** a grouping helper with tests, the grouped parent index (both modes), the list partial and the gallery include (`states.html`), the DEBUG gallery grouped states built from one synthetic-member table (reusing S-07's gallery parent), and screenshots.

**Out of scope:** a toggle or filters, the API, child views, detail pages, pagination, per-group counts, and migrations.

## Architecture / Approach

The flow is `parent_family_entries` → `partition_entries` (unchanged) → `group_by_assignee` (new, pure) → `_index_context` → `_manage_list.html`. In the partial, an h2 group contains the `data-list-section` blocks, and rows come from the existing `_entry_row.html` with `hide_assignee=True`. Styling comes from existing token classes; a new class is added to `tokens.css` only if needed.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Assignee grouping contract | Tested pure helper with the agreed order | The order rule is wrong if the owner picks different decisions |
| 2. Grouped parent index and gallery | Grouped UI in both modes, gallery state, screenshots | Heading hierarchy or density at 360 px |

**Prerequisites:** lands after S-07 (confirmed order S-01, S-02, S-20, S-03, S-04, S-05, S-06, S-07, S-08, …) and reuses its gallery parent; S-07's row-scoped parent-assignee assertions move to the group heading.
**Estimated effort:** ~1–2 sessions across 2 phases.

## Open Risks & Assumptions

- Owner review 2026-10-04 confirmed the decisions listed under "Owner Decisions (2026-10-04)" in plan.md; remaining assumed rows stand unless the owner objects.
- Owner decisions from the plan review were applied 2026-10-04 (no toggle; grouping replaces the list in both modes). Rows still marked "Assumed" stand in for PRD Open Questions 1, 5, 12, and 20 and stand unless the owner objects.
- Removing the chronological family-wide view is accepted (owner-confirmed 2026-10-04); revisit after use.
- Existing ordering tests stay valid because unassigned rows land in a single group. The assignee name moves from the row meta to the group heading, which is an intended presentation change.

## Success Criteria (Summary)

- A parent can scan each child's entries under the child's name, in both "Nadchodzące" and "Minione".
- Parent-assigned and unassigned entries remain visible in their own clearly named groups, and no entry is lost or duplicated.
