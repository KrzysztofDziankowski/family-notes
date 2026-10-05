# Parent List Child Grouping Implementation Plan

## Overview

Roadmap-future slice S-08 (PK-04, US-04): group the parent's family entry list (`/entries/`) by the family member each entry is assigned to, with one group per child. Parent-assigned and unassigned ("Cała rodzina") entries must remain discoverable. The change reuses the shared list contract (`entries/listing.py`), the shared row partial, and the existing tokens. It does not change the list modes, their ordering, the API, or child views.

### Owner Decisions (2026-10-04)

- Group order: children first, then one group per parent, then "Cała rodzina" last.
- Grouping replaces the flat list in both modes ("Nadchodzące" and "Minione"), with no chronological toggle (owner-confirmed 2026-10-04; plan-review F3).
- All future-roadmap slices except removed ones are in the next milestone; confirmed order: S-01, S-02, S-20, S-03, S-04, S-05, S-06, S-07, S-08, S-09, S-17, S-14, S-15, S-16. S-08 lands after S-07 and reuses its synthetic gallery parent.
- Ship without feature flags and without backfilling existing data.
- No Playwright/E2E tests in this slice; browser tests will be added later.

Owner decisions from the plan review were applied 2026-10-04. Items below that the owner did not address remain assumed defaults; they stand unless the owner objects.

### Assumed Decisions

1. **Grouping replaces the flat parent list in both modes ("Nadchodzące" and "Minione"); there is no toggle back to a chronological view.** This is the smallest change that satisfies US-04, and a toggle adds a second layout to maintain. (owner-confirmed 2026-10-04; PRD Open Question 5)
2. **Group order: active and inactive children first, then parents, then "Cała rodzina" (unassigned) last** (owner-confirmed 2026-10-04). Members within a role are ordered by member pk, the same order as the assignee dropdown (`entries/forms.py:88`). Children first matches the request, and unassigned last keeps child groups at the top. (PRD Open Question 5)
3. **Each parent-assigned entry appears in its own per-parent group, headed by the parent's display name.** Parents are not merged into one "Rodzice" group. Per-member groups are uniform with child groups and keep S-07 assignments visible. (PRD Open Question 5)
4. **Within a group, the existing mode ordering is unchanged.** In upcoming mode, dated rows (date ascending, then time with missing last, then pk) come before undated rows (`updated_at` descending). In past mode, rows run by date descending. Groups with no rows in the current mode are hidden. (PRD Open Question 5)
5. **Rows inside a group hide the assignee line** (`hide_assignee=True`) because the group heading names the assignee. The date stays on every row. A since-deactivated member's group heading carries the existing " (nieaktywne konto)" suffix. (PRD Open Question 5)
6. **Release scope and compatibility:** HTML parent list only. The automation API order, child views, list-mode URLs, and empty states are unchanged. No migration. (PRD Open Questions 1, 12, 20)

## Current State Analysis

- The parent index partitions the family queryset with `partition_entries` into `dated`/`undated` (upcoming) or `past` sections (`entries/views.py:480-484`, `entries/listing.py:63-110`). It renders flat `<section data-list-section>` blocks with `h2.fn-manage-section-title` (`entries/templates/entries/_manage_list.html`).
- Rows come from `_entry_row.html`, which already supports `hide_assignee` (`entries/templates/entries/_entry_row.html:7`, `:21`). Rows are `select_related('assigned_member')` (`entries/services.py:120-123`), so the assignee role and name are available without extra queries.
- The child list already groups rows in Python after `partition_entries` (`entries/views.py:727-753`, `entries/listing.py:138-145`). That is the pattern to mirror: the helper is pure, keeps input order, and does no scoping.
- Existing ordering tests use unassigned entries only (`entries/tests/test_manage_views.py:119-188`). Under the assumed design, all such entries fall into the single "Cała rodzina" group, so their row-order and `data-list-section` assertions stay valid.
- The DEBUG gallery's list states use synthetic members without roles (`entries/views.py:582-598`, `:676-693`). Grouping needs a role on the synthetic `FamilyMember` and a stable synthetic key. The gallery template passes the list partial its variables explicitly (`entries/templates/entries/states.html:36`: `sections=state.list.sections`), so it must switch to `groups` together with the partial.
- S-07 `parent-note-assignment` lands just before this slice. It adds a fictional parent to `STATES_MEMBER_CHOICES` (`entries/views.py:244`) with a parent-assigned note in the upcoming gallery state, and parent-index tests that assert the parent assignee's name. `child_states` uses `STATES_MEMBER_CHOICES[1][1]` (`entries/views.py:790`) and must keep pointing at a child.
- Tokens provide `.fn-manage-section-title` (h2) and `.fn-day-heading` (`family_notes/static/css/tokens.css:249`, `:295`).

## Desired End State

A parent opening `/entries/` sees one titled group per child that has entries in the current mode, then one per parent with entries, then "Cała rodzina". Each group lists rows in the existing mode order: "Z datą" before "Bez daty" in upcoming mode. The "Nadchodzące"/"Minione" switch, empty state, links, and family isolation behave as before. Every entry in the mode appears exactly once.

### Key Discoveries:

- `partition_entries` must stay scoping-free and ordering-authoritative (`entries/listing.py:1-6`). Grouping is a post-step over its sections.
- `group_by_day` is the precedent for a pure grouping helper that keeps input order (`entries/listing.py:138`).
- `INACTIVE_MEMBER_SUFFIX` already exists for inactive member labels (`entries/forms.py:41`).
- The child view must not change. It uses its own body partial (`entries/templates/entries/_child_list_body.html`).

## What We're NOT Doing

- No chronological/grouped toggle and no per-group collapse or filtering.
- No change to the automation API, the child list, or the detail pages.
- No change to `partition_entries` ordering or lucky-number exclusion.
- No pagination, counts per group, or new JavaScript.
- No schema change.

## Implementation Approach

Add a pure helper in `entries/listing.py` that takes the ordered sections from `partition_entries` and returns assignee groups. Each group holds its own per-section row lists, in the agreed group order. The index view builds its context from that helper. The `_manage_list.html` partial renders groups (h2) containing section blocks and keeps the `data-list-section` hooks. The DEBUG gallery gets role-aware synthetic members and a grouped upcoming state for the screenshot gate.

## Phase 1: Assignee Grouping Contract

### Overview

Define and test the grouping order as a pure function, independent of templates.

### Changes Required:

#### 1. Grouping helper

**File**: `entries/listing.py`

**Intent**: Split already-ordered list sections into assignee groups without re-querying or re-ordering rows.

**Contract**: The new `group_by_assignee(sections)` takes the output of `partition_entries` and evaluates each section once. It returns an ordered list of groups, each with:
- `key`: `'member-<pk>'`, or `'family'` for unassigned entries.
- `member`: the `FamilyMember`, or `None`.
- `sections`: a list of `EntrySection(key, rows_list)`, keeping only non-empty sections, in input section order.

Group order is children (any active state) by member pk, then parents by member pk, then `'family'`. Row order within each section equals input order. Every input row appears in exactly one group. The helper never filters by family, role, or assignee visibility; scoping stays the caller's job, matching the module docstring.

#### 2. Helper tests

**File**: `entries/tests/test_entry_listing.py`

**Intent**: Lock the group order and the order preservation.

**Contract**: The tests cover:
- two children, two parents, and unassigned rows across dated, undated, and past sections;
- an inactive child assignee;
- groups whose only rows are undated;
- an empty input returning `[]`;
- row order inside groups matching `partition_entries`;
- the exact-once property (union of grouped rows equals input rows).

### Success Criteria:

#### Automated Verification:

- Grouping tests prove group order (children, parents, then "Cała rodzina"), input-order preservation, exact-once membership, and empty-section omission.
- Listing tests pass: `uv run python manage.py test entries.tests.test_entry_listing`

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 2: Grouped Parent Index and Gallery

### Overview

Render the parent index grouped by assignee, update the DEBUG gallery, and verify visually.

### Changes Required:

#### 1. Index context

**File**: `entries/views.py` (`_index_context`, `_index_sections`, `index`, `_synthetic_list`)

**Intent**: Feed the template groups instead of flat sections, keeping the mode, modes, empty state, and messages unchanged.

**Contract**: The context gains `groups`: a list of `{key, heading, sections: [{key, label, entries}]}`.
- `heading` is the member's display name, plus `INACTIVE_MEMBER_SUFFIX` for an inactive member, or `'Cała rodzina'` for the family group.
- `label` comes from the existing `SECTION_LABELS`.
- `is_empty` and `empty_message` keep their current meaning.

The `index` view still uses `parent_family_entries` and `partition_entries`, and still adds no queries beyond the existing per-section ones.

#### 2. List partial

**File**: `entries/templates/entries/_manage_list.html`

**Intent**: Show one titled block per assignee, with the mode's sections inside.

**Contract**:
- Each group is a `<section data-assignee-group="{{ group.key }}">` with an `h2.fn-manage-section-title` heading.
- Inside, each non-empty section keeps `data-list-section="{{ section.key }}"`. It shows an `h3` subsection label only in upcoming mode (where "Z datą"/"Bez daty" both exist), styled with an existing token class or a new class added to `tokens.css` from existing tokens.
- Rows reuse `_entry_row.html` with `hide_assignee=True` plus the existing detail and edit links.
- The mode switch and empty state are unchanged.
- No inline styles and no `<style>` blocks.

#### 3. DEBUG gallery

**File**: `entries/views.py` (`STATES_MEMBER_CHOICES`, `_synthetic_entry`, `_manage_state_sections`), `entries/templates/entries/states.html`, `entries/templates/entries/_manage_list.html` (doc comment), `entries/tests/test_manage_states.py`

**Intent**: Let the screenshot gate show grouping with children, a parent, and "Cała rodzina".

**Contract**:
- Synthetic members (two children and S-07's fictional parent) come from one table with display name, role, and a stable synthetic pk. `STATES_MEMBER_CHOICES` is generated from that table, so no second fictional parent is added, and `child_states`' `STATES_MEMBER_CHOICES[1][1]` still names a child.
- `_synthetic_entry` builds its `FamilyMember` from that table, so the helper can group synthetic rows. S-07's parent-assigned note lands in the parent group.
- `states.html:36` passes `groups=state.list.groups` instead of `sections=…`, and the `_manage_list.html` doc comment reads "Parameters: mode, modes, groups, is_empty, empty_message".
- The upcoming list state contains at least two children's groups, one parent group, and the "Cała rodzina" group.
- The past state keeps one group.
- The gallery still touches no database rows and returns 404 with `DEBUG=False`.

#### 4. View tests

**File**: `entries/tests/test_manage_views.py`

**Intent**: Prove grouping in the real index, alongside the existing ordering and isolation guarantees.

**Contract**: New tests assert:
- the `data-assignee-group` sequence (children by pk, parents, then `family`) for both modes;
- the row order within a group;
- that each own-family entry renders exactly once;
- the inactive-member suffix in a group heading.

Existing ordering tests stay unchanged and green: unassigned rows form one group, and `test_rows_show_type_content_schedule_assignee_and_links` still finds the assignee name, which now sits in the group heading. A new assertion pins the heading placement. Foreign-family, lucky-number, child (403), and anonymous cases stay covered.

Re-run S-07's parent-assignee index tests. Any S-07 assertion scoped to a `data-entry-row` element moves to the `data-assignee-group` heading in this reviewed diff; the assertion itself (the parent's name is shown for that entry) is never weakened.

### Success Criteria:

#### Automated Verification:

- View tests prove group sequence, in-group order, exact-once rendering, and the inactive suffix in both modes, and the existing ordering and isolation tests stay green.
- Gallery tests assert the grouped upcoming state renders children, parent, and "Cała rodzina" groups.
- Entries tests pass: `uv run python manage.py test entries.tests`
- Full suite, checks and migration check pass: `uv run python manage.py test`, `uv run python manage.py check`, `uv run python manage.py makemigrations --check --dry-run`

#### Manual Verification:

- At phone width (360 px), a parent sees entries grouped by child, then by parent, then "Cała rodzina", in both list modes, and the heading hierarchy reads clearly.
- An entry reassigned in "Edytuj" moves to the new assignee's group after saving.
- Phone-width screenshots of the grouped upcoming and past gallery states are saved under `context/changes/parent-list-child-grouping/screenshots/`.

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding.

---

## Testing Strategy

### Unit Tests:

- `group_by_assignee` ordering, order preservation, exact-once membership, empty sections, and inactive members.

### Integration Tests:

- Parent index in both modes with mixed assignees, isolation from the foreign family, lucky-number exclusion, and the child/anonymous access matrix unchanged.

### Manual Testing Steps:

1. Create entries for two children, one parent, and unassigned; open `/entries/` and `/entries/?view=past`.
2. Reassign one entry and confirm that it moves groups.
3. Review `/entries/_states/` at 360 px and save screenshots.

## Performance Considerations

Grouping runs in Python over rows already loaded by the existing section queries, with `select_related('assigned_member')`. It adds no extra queries. The list stays unpaginated, as before.

## Migration Notes

None.

## References

- Roadmap item: `context/foundation/roadmap-future.md` (S-08)
- PRD: `context/foundation/prd-v2.md` (PK-04, US-04, Open Question 5)
- Shared list contract: `entries/listing.py:63`
- Grouping precedent: `entries/listing.py:138`, `entries/views.py:727`
- Related slice: `context/changes/parent-note-assignment/plan.md` (parent-assigned entries, gallery parent; lands just before S-08)
- Gallery include: `entries/templates/entries/states.html:36`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Assignee Grouping Contract

#### Automated

- [x] 1.1 Grouping tests prove group order (children, parents, then "Cała rodzina"), input-order preservation, exact-once membership, and empty-section omission. — 553107c
- [x] 1.2 Listing tests pass: `uv run python manage.py test entries.tests.test_entry_listing` — 553107c

### Phase 2: Grouped Parent Index and Gallery

#### Automated

- [x] 2.1 View tests prove group sequence, in-group order, exact-once rendering, and the inactive suffix in both modes, and the existing ordering and isolation tests stay green.
- [x] 2.2 Gallery tests assert the grouped upcoming state renders children, parent, and "Cała rodzina" groups.
- [x] 2.3 Entries tests pass: `uv run python manage.py test entries.tests`
- [x] 2.4 Full suite, checks and migration check pass: `uv run python manage.py test`, `uv run python manage.py check`, `uv run python manage.py makemigrations --check --dry-run`

#### Manual

- [ ] 2.5 At phone width (360 px), a parent sees entries grouped by child, then by parent, then "Cała rodzina", in both list modes, and the heading hierarchy reads clearly.
- [ ] 2.6 An entry reassigned in "Edytuj" moves to the new assignee's group after saving.
- [ ] 2.7 Phone-width screenshots of the grouped upcoming and past gallery states are saved under `context/changes/parent-list-child-grouping/screenshots/`.
