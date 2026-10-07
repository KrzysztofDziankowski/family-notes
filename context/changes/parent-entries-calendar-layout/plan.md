# Parent Entries Calendar Layout Implementation Plan

## Overview

Replace the parent's populated-day list with a navigable, calendar-style 14-day view. Every date receives its own box, including dates without entries. Mobile uses one column; wide screens use seven columns, producing two calendar rows.

## Current State Analysis

The parent list already groups family-scoped entries by day and then assignee, but it emits only dates containing entries. Upcoming and past modes are unbounded, nearby date headings omit the numeric date, and the whole-list empty state replaces the list when no rows exist. Existing uncommitted changes in `_manage_list.html` and `tests/e2e/parent-entry-lands-grouped.spec.ts` belong to the user and must be preserved.

## Desired End State

Parents see exactly 14 dated boxes at a time, can move backward or forward by two weeks, and return from entry details to the same window. Empty days explicitly show `Brak wpisów`; populated days retain day → assignee → entry grouping. The child list and family-access rules remain unchanged.

### Key Discoveries:

- Parent list context is assembled by `_index_days` / `_index_context`, which currently skips empty sections (`entries/views.py:927-969`).
- The shared heading helper intentionally serves parent and child lists, so the expanded date contract should be parent-specific (`entries/listing.py:128-160`).
- `Entry.date` is already required and existing nulls were backfilled, so no schema or data migration is needed (`entries/models.py:32`, `entries/migrations/0008_backfill_entry_dates.py`, `entries/migrations/0009_entry_date_required.py`).
- Parent accessibility tests already enforce the h1 → day h2 → assignee h3 hierarchy (`entries/tests/test_accessibility.py:272-295`).

## What We're NOT Doing

- Changing the child list.
- Adding a month view, drag-and-drop, JavaScript calendar widget, or date-prefilled add action.
- Changing entry models, date validation, classification, automation intake, or family authorization.
- Repairing hypothetical legacy undated rows; date enforcement outside this view belongs to a separate change.
- Overwriting the user's existing template or E2E edits.

## Implementation Approach

Add a parent-only fortnight contract around the existing family-scoped query. A normalized `start=YYYY-MM-DD` parameter selects the first visible date; the view bounds the queryset, synthesizes all 14 day records, and assigns existing rows to those records. Templates then render the fixed sequence as semantic day boxes, while token-based CSS changes from one column to seven columns at a wide breakpoint.

The upcoming default is today through today + 13 days. The past default is today - 14 days through yesterday. Navigation shifts exactly 14 days and cannot cross today's boundary into the other mode. Invalid or out-of-mode `start` values fall back to the relevant default window.

## Critical Implementation Details

Chronology remains left-to-right and top-to-bottom in both modes; historical windows are selected through navigation rather than reversing dates inside the grid. Entry detail links must preserve both `view` and `start`, otherwise the existing back link silently returns parents to the default fortnight.

## Phase 1: Calendar Window Contract

### Overview

Introduce bounded parent-only date windows, navigation state, full date headings, and stable return links without altering the shared child-list contract.

### Changes Required:

#### 1. Parent list range and context

**File**: `entries/views.py`

**Intent**: Normalize the requested fortnight, query only its visible dates, and emit a day record for every date so empty boxes are first-class view state.

**Contract**: Accept optional `start=YYYY-MM-DD`. Upcoming defaults to `[today, today + 13]`; past defaults to `[today - 14, yesterday]`. Invalid values or values crossing the mode boundary use that mode's default. Produce exactly 14 chronological ISO-keyed days. Populated days preserve children → parents → `Cała rodzina` ordering and existing row ordering. Do not emit the legacy `Bez daty` bucket.

#### 2. Parent calendar headings

**File**: `entries/listing.py`

**Intent**: Give each parent day box the requested relative label plus an explicit Polish calendar date without changing child headings.

**Contract**: Provide a parent-specific formatter yielding `Dziś, 7 października`, `Jutro, 8 października`, `Wczoraj, 6 października`, or `<weekday>, <day> <month>`; append the year when it differs from the current year. Continue using Django locale formatting rather than hand-written month names.

#### 3. Navigation and return query

**Files**: `entries/views.py`, parent list/detail templates

**Intent**: Preserve the selected mode and fortnight across previous/next navigation and entry-detail round trips.

**Contract**: Previous and next links shift by 14 days and retain `view`. Omit or disable the link that would cross today's boundary. Mode tabs open each mode's default fortnight. Entry links carry the normalized list query, and `Wróć do listy` restores both `view` and `start`.

### Success Criteria:

#### Automated Verification:

- Parent view tests prove both default 14-day ranges and exact inclusive boundaries.
- Tests cover valid, malformed, and out-of-mode `start` values.
- Tests prove navigation shifts by 14 days and cannot cross today's mode boundary.
- Tests prove family isolation and existing role/access behavior remain unchanged.
- Tests prove detail and back links preserve `view` and `start`.

#### Manual Verification:

- Upcoming initially opens on today and past initially ends on yesterday.
- Moving between fortnights and returning from an entry detail preserves the expected window.

**Implementation Note**: Pause after automated verification for manual confirmation before Phase 2.

---

## Phase 2: Calendar Presentation

### Overview

Render all 14 dates as accessible day boxes, show intentional empty states, and introduce the responsive one-to-seven-column layout.

### Changes Required:

#### 1. Parent calendar markup

**File**: `entries/templates/entries/_manage_list.html`

**Intent**: Make the fixed date sequence visibly calendar-like while retaining semantic day and assignee grouping.

**Contract**: Render one section and h2 for each of the 14 dates. Populated boxes keep assignee h3 headings and labelled lists. Empty boxes contain `Brak wpisów`. Remove the parent whole-list replacement empty state because an empty fortnight still renders 14 boxes. Navigation controls use Polish accessible names `Poprzednie 2 tygodnie` and `Następne 2 tygodnie`. Preserve and adapt the user's uncommitted composite list `aria-label` change.

#### 2. Responsive calendar styling

**File**: `family_notes/static/css/tokens.css`

**Intent**: Add a parent-only calendar grid and day-card treatment without changing shared child-list styling.

**Contract**: Use existing spacing, border, surface, radius, focus, and typography tokens only. Default to one column, including at 320 CSS px, and switch directly to seven equal columns when the viewport is wide enough. Fourteen boxes form two chronological rows. Long entry text and multiple assignee groups must not cause horizontal overflow; no inline styles or literal colors.

#### 3. DEBUG state gallery

**Files**: `entries/views.py`, `entries/templates/entries/states.html`

**Intent**: Keep the existing visual-review surface representative of the new calendar contract.

**Contract**: Include a mixed fortnight with visible empty days, a fully empty fortnight, populated multi-assignee days, and both upcoming and past navigation. Keep the gallery DEBUG-only.

### Success Criteria:

#### Automated Verification:

- Template tests assert exactly 14 ordered day boxes for each window.
- Tests assert relative full-date headings, a regular weekday heading, and a cross-year heading.
- Tests assert populated-day assignee grouping and exactly-once entry rendering.
- Tests assert `Brak wpisów` for empty dates.
- Accessibility tests preserve one h1, sequential h2/h3 hierarchy, labelled lists, and Polish navigation labels.
- Token/style tests reject literal colors and horizontal-overflow regressions.

#### Manual Verification:

- At 320 CSS px, boxes form one readable column without horizontal scrolling.
- At a wide viewport, boxes form seven columns and two rows.
- Empty and populated boxes are visually distinct, readable, and aligned.
- Focus indicators and keyboard navigation remain visible.

**Implementation Note**: Pause after automated verification for the state-gallery screenshot and manual confirmation before Phase 3.

---

## Phase 3: Regression and Acceptance Coverage

### Overview

Update expectations that assume populated dates only and verify the new layout without weakening grouping, access, performance, or browser-level coverage.

### Changes Required:

#### 1. Parent list regression coverage

**Files**: `entries/tests/test_manage_views.py`, `entries/tests/test_manage_states.py`, `entries/tests/test_accessibility.py`

**Intent**: Pin the date-window, rendering, navigation, accessibility, and state-gallery contracts.

**Contract**: Update fixtures and assertions for fixed 14-day output while retaining family isolation, role protection, exactly-once rendering, deterministic order, and bounded query behavior. Child list expectations remain unchanged.

#### 2. Existing browser risk test

**File**: `tests/e2e/parent-entry-lands-grouped.spec.ts`

**Intent**: Reconcile the user's untracked E2E test with expanded headings and the calendar window without replacing its risk coverage.

**Contract**: A parent-created entry for tomorrow appears once in tomorrow's box under the selected child. Locators continue to use accessible roles/labels and the test retains independent cleanup.

### Success Criteria:

#### Automated Verification:

- Focused parent list, state-gallery, and accessibility tests pass.
- Relevant listing, family-isolation, access, and token/style tests pass.
- `uv run python manage.py check` passes.
- `uv run python manage.py makemigrations --check --dry-run` reports no model changes.
- The focused Playwright grouping test passes when the existing E2E environment is available.

#### Manual Verification:

- A parent can inspect upcoming and historical fortnights without losing entries or crossing list-mode boundaries.
- An entry created for tomorrow appears once in tomorrow's box under the correct assignee.
- A fortnight containing no entries still shows all 14 dated boxes.

**Implementation Note**: Complete the final manual acceptance pass before marking the change implemented.

## Testing Strategy

### Unit Tests:

- Date parsing, default ranges, boundary normalization, 14-day shifting, and parent-specific headings.
- Day synthesis for empty, mixed, and fully populated windows.

### Integration Tests:

- Parent family scoping, mode/window navigation, grouping order, query-count bounds, and detail return links.
- Accessibility audits for upcoming, past, mixed, and fully empty calendar states.
- Browser-level creation → grouped-calendar rendering → cleanup risk.

### Manual Testing Steps:

1. Review upcoming and past default windows and navigate at least two fortnights in each permitted direction.
2. Open an entry from a non-default window and confirm the back link restores it.
3. Inspect mixed and fully empty gallery states at 320 CSS px and a wide seven-column viewport.
4. Keyboard through tabs, navigation, entry links, and actions while checking visible focus.

## Performance Considerations

The bounded date filter should reduce rows loaded compared with the current unbounded modes. Day synthesis is fixed at 14 records and must not add per-day or per-assignee queries; retain or tighten the existing query-count assertion.

## Migration Notes

No database migration or data backfill is required. Rollback is limited to the parent context, templates, styles, and tests; persisted entries and URLs without `start` remain compatible.

## References

- Product and access constraints: `context/foundation/prd.md:101-155`
- Accessibility contract: `context/foundation/accessibility.md:17-75`
- Existing parent grouping: `entries/views.py:927-988`
- Shared list behavior: `entries/listing.py:78-185`
- Parent template: `entries/templates/entries/_manage_list.html:1-27`
- Existing UI tokens: `family_notes/static/css/tokens.css:14-41`, `family_notes/static/css/tokens.css:215-233`
- Parent list tests: `entries/tests/test_manage_views.py:769-985`
- State gallery tests: `entries/tests/test_manage_states.py:149-183`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles.

### Phase 1: Calendar Window Contract

#### Automated

- [x] 1.1 Parent view tests prove both default 14-day ranges and exact inclusive boundaries. — b3d4265
- [x] 1.2 Tests cover valid, malformed, and out-of-mode `start` values. — b3d4265
- [x] 1.3 Tests prove navigation shifts by 14 days and cannot cross today's mode boundary. — b3d4265
- [x] 1.4 Tests prove family isolation and existing role/access behavior remain unchanged. — b3d4265
- [x] 1.5 Tests prove detail and back links preserve `view` and `start`. — b3d4265

#### Manual

- [ ] 1.6 Upcoming initially opens on today and past initially ends on yesterday.
- [ ] 1.7 Moving between fortnights and returning from an entry detail preserves the expected window.

### Phase 2: Calendar Presentation

#### Automated

- [x] 2.1 Template tests assert exactly 14 ordered day boxes for each window.
- [x] 2.2 Tests assert relative full-date headings, a regular weekday heading, and a cross-year heading.
- [x] 2.3 Tests assert populated-day assignee grouping and exactly-once entry rendering.
- [x] 2.4 Tests assert `Brak wpisów` for empty dates.
- [x] 2.5 Accessibility tests preserve one h1, sequential h2/h3 hierarchy, labelled lists, and Polish navigation labels.
- [x] 2.6 Token/style tests reject literal colors and horizontal-overflow regressions.

#### Manual

- [ ] 2.7 At 320 CSS px, boxes form one readable column without horizontal scrolling.
- [ ] 2.8 At a wide viewport, boxes form seven columns and two rows.
- [ ] 2.9 Empty and populated boxes are visually distinct, readable, and aligned.
- [ ] 2.10 Focus indicators and keyboard navigation remain visible.

### Phase 3: Regression and Acceptance Coverage

#### Automated

- [ ] 3.1 Focused parent list, state-gallery, and accessibility tests pass.
- [ ] 3.2 Relevant listing, family-isolation, access, and token/style tests pass.
- [ ] 3.3 `uv run python manage.py check` passes.
- [ ] 3.4 `uv run python manage.py makemigrations --check --dry-run` reports no model changes.
- [ ] 3.5 The focused Playwright grouping test passes when the existing E2E environment is available.

#### Manual

- [ ] 3.6 A parent can inspect upcoming and historical fortnights without losing entries or crossing list-mode boundaries.
- [ ] 3.7 An entry created for tomorrow appears once in tomorrow's box under the correct assignee.
- [ ] 3.8 A fortnight containing no entries still shows all 14 dated boxes.
