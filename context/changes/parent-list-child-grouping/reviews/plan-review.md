<!-- PLAN-REVIEW-REPORT -->
# Plan Review: Parent List Child Grouping Implementation Plan

- **Plan**: context/changes/parent-list-child-grouping/plan.md
- **Mode**: Deep
- **Date**: 2026-10-04
- **Verdict**: SOUND
- **Triage**: applied 2026-10-04
- **Findings**: 0 critical, 2 warnings, 2 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| End-State Alignment | PASS |
| Lean Execution | PASS |
| Architectural Fitness | WARNING |
| Blind Spots | PASS |
| Plan Completeness | WARNING |

## Grounding
Grounding: 6/6 paths ✓ (`entries/listing.py`, `entries/views.py`, `entries/templates/entries/_manage_list.html`, `entries/templates/entries/_entry_row.html`, `entries/tests/test_entry_listing.py`, `entries/tests/test_manage_states.py`). 7/7 symbols ✓: `partition_entries` (listing.py:63), `group_by_day` (listing.py:138), `EntrySection`, `INACTIVE_MEMBER_SUFFIX` (forms.py:41), `_index_context`/`_index_sections`/`_synthetic_list` (views.py:452-604), `.fn-manage-section-title`/`.fn-day-heading` (tokens.css:249/295), and `hide_assignee` in the row partial. `_family_entries` uses `select_related('assigned_member')`, so the claim of no extra queries holds. The existing ordering tests use unassigned entries only (`ManageViewMixin.entry`), and `test_rows_show_type_content_schedule_assignee_and_links` asserts only `'Michał'` anywhere in the page, so it survives the move to the heading. The page has an `h1` (`manage_index.html`), so h1>h2>h3 skips no level, which is compatible with S-17's audit. One template consumer is missing from the plan (F1). brief↔plan ✓; stale header text (F4). Progress↔Phase ✓: 2+7 steps match, and phase blocks contain no checkboxes.

## Findings

### F1 — DEBUG gallery include passes `sections=` explicitly and is not in the plan

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 2 — items 2 (list partial) and 3 (DEBUG gallery)
- **Detail**: `entries/templates/entries/states.html:36` renders the partial as `{% include "entries/_manage_list.html" with mode=state.list.mode modes=state.list.modes sections=state.list.sections is_empty=… %}`. Once `_manage_list.html` iterates `groups`, the gallery has no `groups` variable in its context, so every list state renders with no rows and `is_empty=False`. That would show nothing at all, not even the empty message. Phase 2 lists `entries/views.py` and `test_manage_states.py` but never `states.html`. The gallery tests would go red, but the implementer gets no guidance, and the screenshot gate (2.7) depends on this page.
- **Fix**: Add `entries/templates/entries/states.html` to Phase 2 item 3. Pass `groups=state.list.groups` instead of `sections=…`, and update the partial's doc comment ("Parameters: mode, modes, groups, is_empty, empty_message").
- **Owner input**: no
- **Decision**: FIXED (Fix A)

### F2 — Cross-plan: S-07's gallery parent and parent-assignee tests not accounted for

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Architectural Fitness
- **Location**: Phase 2 — items 3 (DEBUG gallery) and 4 (view tests); brief "Prerequisites"
- **Detail**: S-07 `parent-note-assignment` lands just before S-08 in the confirmed order. Its Phase 2 adds a fictional parent to `STATES_MEMBER_CHOICES` (views.py:244) and a parent-assigned note to the `list_upcoming` state through `_synthetic_entry(member=…)`, which builds a role-less `FamilyMember(display_name=…)` (views.py:582-597). S-07 also asserts that the parent index renders the parent assignee's name. S-08 Phase 2 reworks `_synthetic_entry` to carry a role and a synthetic pk, and it hides the row assignee. The plan calls S-08 "independent of S-07" and does not mention:
  - reusing S-07's synthetic parent for the required "one parent group", instead of adding a second fictional parent;
  - keeping `child_states`' use of `STATES_MEMBER_CHOICES[1][1]` (views.py:790) pointing at a child;
  - S-07 index tests that scope the parent's name to a `data-entry-row` element. Those break when the name moves to the group heading, and they need a reviewed locator move, not a weakened assertion.
- **Fix**: Phase 2 item 3 should derive the synthetic members (child ×2, S-07's parent) from one table with role and pk. `STATES_MEMBER_CHOICES` should be generated from the same table, and the S-07 parent-assigned note should land in the parent group. Item 4 should add: "re-run S-07's parent-assignee index tests; any assertion scoped to the row moves to the `data-assignee-group` heading in this diff".
  - Strength: One source of synthetic members, no duplicate parents in the gallery, and S-07's proof survives grouping.
  - Tradeoff: It slightly widens the Phase 2 diff in `entries/views.py`.
  - Confidence: HIGH — both plans name the same functions (S-07 Phase 2 and S-08 Phase 2 item 3).
  - Blind spot: S-01 `school-event-details` also edits `_manage_state_sections` before S-07/S-08, so the exact shape at merge time is unknown.
- **Owner input**: no
- **Decision**: FIXED (Fix A)

### F3 — The family-wide chronological list disappears with no toggle

- **Severity**: 💡 OBSERVATION
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: End-State Alignment
- **Location**: Assumed Decision 1; brief "Open Risks"
- **Detail**: The owner confirmed the group order only. Under Decision 1, grouping replaces the flat list in both modes. A parent who wants to know "what happens tomorrow for anyone" then has to scan every child group, the parent groups and "Cała rodzina". A dated unassigned entry for today renders below all of the children's undated rows. The brief itself flags this as a risk. The answer is user-visible behaviour that the owner has to choose; the code does not decide it.
- **Fix A ⭐ Recommended**: Keep the plan: grouping replaces the flat list, with no toggle. Revisit after use.
  - Strength: The smallest change, one layout, and it matches the US-04 wording.
  - Tradeoff: The family-wide "what's next" view is lost. The automation API is unchanged but is not a UI substitute.
  - Confidence: MEDIUM — no usage evidence either way.
  - Blind spot: How often parents scan across children by date.
- **Fix B**: Add a third list tab ("Wg dziecka" / "Chronologicznie"), or a `?group=` switch that defaults to grouped.
  - Strength: Both reading modes are kept.
  - Tradeoff: Two layouts to maintain and test, more gallery states, and a larger S-17 audit surface.
  - Confidence: HIGH — `_list_modes.html` already supports mode tabs.
  - Blind spot: How it interacts with the existing upcoming/past tabs at 360 px.
- **Owner input**: yes
- **Decision**: FIXED (owner: Fix A — grouping replaces the list in both modes, no toggle)

### F4 — Stale owner-decision text and "blocked" status

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Owner Decisions (2026-10-04); plan-brief "Open Risks & Assumptions" and "Prerequisites"
- **Detail**: The confirmed order in the plan omits S-20 (`roadmap-future.md:43-60` places it third). The brief says implementation is "blocked on owner confirmation (roadmap status: blocked)", but the roadmap row is `planning` with `Blockers: —`. The brief says "independent of S-07", but see F2.
- **Fix**: Include S-20 in the order, drop the "blocked" sentence, and change the prerequisite note to "lands after S-07; reuses its gallery parent".
- **Owner input**: no
- **Decision**: FIXED (Fix A)
