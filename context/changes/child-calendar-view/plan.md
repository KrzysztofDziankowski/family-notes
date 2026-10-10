# Shared Calendar for Parent and Child Implementation Plan

## Overview

Parents and children get one 14-day calendar. The "Nadchodzące"/"Minione" tabs and the
"Poprzednie/Następne 2 tygodnie" links are replaced by three buttons: "Wcześniejsze" / "Dzisiaj" / "Następne".
The child's list (`/entries/mine/`) becomes the same calendar, showing only their own entries.
The parent calendar gets filter buttons, "Wszyscy" plus one per child. The unassigned label
"Cała rodzina" becomes "Ogólne" everywhere.

## Current State Analysis

- **Parent calendar** (`entries:index`, `entries/views.py:1040-1052`): a 14-day window driven by
  `?view=upcoming|past&start=`. Upcoming starts at today and moves only forward; past ends
  yesterday and moves only back (`_default_window_start`, `_calendar_window`,
  `_calendar_navigation`, `entries/views.py:904-956`). Rows are grouped per day and per
  assignee (`_index_days`, `entries/views.py:984`; `split_by_assignee`, `entries/listing.py:194`).
  Lucky numbers are excluded (`entries/views.py:1047-1049`).
- **Mode tabs** `entries/templates/entries/_list_modes.html` (`nav.fn-tabs`, `aria-label="Rodzaj listy"`)
  are included by `_manage_list.html:12` and `_child_list_body.html:9`. The calendar nav is
  `_manage_list.html:13-18`.
- **`view`/`start` are carried** by entry links (`detail_query`, `_entry_row.html:16`), the parent
  detail back link and delete hidden inputs (`_manage_detail.html:39,47-48`), the delete redirect
  (`entries/views.py:1147-1157`), detail window derivation (`entries/views.py:1055-1071`,
  `_window_containing`, `_list_mode_for`), and the DEBUG states gallery
  (`entries/views.py:1192,1282-1323`, `states.html:40-45`).
- **Child list** (`entries/views.py:1334-1384`): every upcoming or every past entry via
  `partition_entries` (`entries/listing.py:78`, its only caller), relative headings
  (`day_heading`/`group_by_day`), a "Bez daty" group, mode-specific empty messages
  (`CHILD_EMPTY_MESSAGES`), lucky numbers excluded (`entries/listing.py:99`). The child detail back
  link only knows `?view=past` (`_child_entry_detail.html:30`). Gallery: `child_states`
  (`entries/views.py:1400-1494`).
- **"Cała rodzina"**: `entries/forms.py:144`, `entries/views.py:525,973`,
  `_entry_row.html:23`, `_manage_detail.html:18`, `_saved_panel.html:23`; comments in
  `entries/listing.py:40`, `entries/services.py:342`, `_manage_list.html`.
- `list-refresh.js` only reloads the current URL, so new query params survive it.

### Key Discoveries:

- `Entry.date` is NOT NULL (`entries/models.py:32`), so the child list's "Bez daty" group can no longer occur.
- Prior decisions being reversed here, by the owner on 2026-10-10:
  - "cannot cross today's boundary" (`context/archive/2026-10-07-parent-entries-calendar-layout/plan.md:34`).
  - "No redesign of the child list into a calendar" (`context/archive/2026-10-08-mobile-gui-enhancements/plan.md:32`).
  - "no filtering" (`context/changes/parent-list-child-grouping/plan.md:49`).
  - Lucky numbers hidden for the child (`context/archive/2026-09-28-child-assigned-entry-view/plan-brief.md:26`).
- Tab a11y pattern to keep: links with `aria-current="page"`, never Pico `role="group"` or button
  groups (`context/archive/2026-10-04-child-list-ui/plan.md:153-154`).
- No helper for "active children of a family" exists. The closest is `entries/forms.py:168-170`
  (`scope_queryset_to_family(FamilyMember.objects.filter(is_active=True), membership)`).
- `scripts/hooks/quality_gate.py:69` lists `_list_modes` and `_child_list_body` among checked templates.

## Desired End State

- `/entries/` and `/entries/mine/` render the same grid of 14 day boxes (full headings such as
  "Dziś, sobota 10 października", "Brak wpisów" on empty days, weekend strip), with a
  "Nawigacja kalendarza" nav of three links:
  - "Wcześniejsze" goes to `start − 14`.
  - "Dzisiaj" goes to the window starting today. It carries `aria-current="page"` when that is
    the current window.
  - "Następne" goes to `start + 14`.
  - Windows cross today freely.
- The child's boxes show only their own entries, lucky numbers included, with no assignee subheading.
- The parent calendar has a "Filtr wpisów" tab nav: "Wszyscy" (default) plus one link per active
  child of the family.
  - Selecting a child shows that child's entries plus unassigned "Ogólne" entries **instantly,
    client-side**: the page holds every row of the window and a script hides the other groups.
  - Links carry `?member=<pk>`, so filtering also works without JavaScript and after a reload.
  - The filter survives navigation, entry links, "Wróć do listy" and delete.
- No "Nadchodzące"/"Minione", no `view` parameter, and no "Cała rodzina" text remain in product code.
- All tests pass. The accessibility audit covers the parent calendar (with and without a
  filter) and the child calendar.

## What We're NOT Doing

- No multi-select filter, no filter on the child view, and no filter buttons for parents' own entries.
- Inactive children get no filter button. Their entries still show under "Wszyscy".
- No undated section: every entry has a date.
- No mapping of legacy `?view=past` links. The `view` param is ignored, so old links open today's window.
- No change to entry ordering inside a day, to assignee grouping in the parent calendar, or to the
  automation/REST API.
- Lucky numbers stay hidden in the parent calendar.
- The E2E spec `tests/e2e/parent-entry-lands-grouped.spec.ts` expects headings without the weekday
  (it may already be failing). Fixing it is out of scope, but it must not regress further: it
  still uses the default `/entries/` window, which still starts today.

## Implementation Approach

The rename goes first and alone. Then the window model is replaced in the parent view, with
helpers written to be shared. Next the child view adopts the shared day grid and navigation, and
the dead list-mode code is deleted. The filter goes last because it threads one more query
parameter through the now-stable navigation. It switches client-side for speed: the server always
renders every row and marks the initial hidden state, so the script and the no-JS path share one
visibility rule.

## Critical Implementation Details

- **Detail without `start`:** the back link must return to the 14-day window containing the entry,
  on the grid anchored at today: `start = today + 14 * floor((date − today) / 14)`. This keeps
  "Wróć do listy" on the window where the entry was clicked when the link carries no `start`
  (create/edit redirects carry none).
- **Validating `start`:** keep the existing ISO/canonical-form and date-range checks from
  `_calendar_window`, but drop the per-mode fallback. Any canonical date in range is valid;
  everything else falls back to today.
- **Validating `member`:** accept only the pk of an active CHILD membership in the request's
  family. Any other value (another family, a parent, an inactive child, junk) silently means
  "Wszyscy", which also prevents leaking other families' member ids.
- **One visibility rule, two places:** the server's initial `hidden` attributes and
  `member-filter.js` must apply the same rule. A group is visible iff no member is selected, or
  its key is `member-<pk>` or `family`. "Brak wpisów" and `fn-calendar-day--empty` follow
  "no visible group in the day". The Django tests pin the server side and the E2E pins the script.

## Phase 1: Rename "Cała rodzina" to "Ogólne"

### Overview

One term for unassigned entries across the app.

### Changes Required:

#### 1. Labels

**Files**: `entries/views.py` (`FAMILY_GROUP_HEADING`, `STATES_MEMBER_CHOICES`), `entries/forms.py` (assignee `empty_label`), `entries/templates/entries/_entry_row.html`, `_manage_detail.html`, `_saved_panel.html`

**Intent**: Replace the visible text "Cała rodzina" with "Ogólne".

**Contract**: the user-facing string only. The group key `GROUP_FAMILY = 'family'` and
`data-assignee-group="family"` stay. Update the comments mentioning the old label
(`entries/listing.py:40`, `entries/services.py:342`, `_manage_list.html` doc comment).

#### 2. Tests

**Files**: `entries/tests/test_manage_views.py`, `test_manage_states.py`, `test_entry_listing.py`, `test_entry_forms.py`, and any capture/saved-panel test asserting the label

**Intent**: Assert "Ogólne" where "Cała rodzina" was asserted. The negative check in
`TwoParentManageViewTests` (`test_manage_views.py:942`) must check "Ogólne" so it stays meaningful.
Add one assertion that the saved panel shows "Ogólne" for an unassigned entry; it had no coverage.

### Success Criteria:

#### Automated Verification:

- Entries tests pass: `uv run python manage.py test entries`
- No "Cała rodzina" left in product code: `grep -rn "Cała rodzina" entries family_access family_notes --include=*.py --include=*.html | grep -v /tests/` returns nothing

#### Manual Verification:

- Parent calendar subheading, the assignee select's empty option and the saved panel read "Ogólne"

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 2: Free 14-day window with Wcześniejsze / Dzisiaj / Następne (parent)

### Overview

Replace the upcoming/past modes in the parent calendar with one window keyed by `start`, plus a
shared three-link navigation.

### Changes Required:

#### 1. Window helpers

**File**: `entries/views.py`

**Intent**: A mode-free window model reusable by parent and child.

**Contract**:
- `_calendar_window(value, today) -> (start, end)`: defaults to `today`. Canonical ISO date in range, else `today`.
- `_window_containing(day, today) -> start`, on the today-anchored 14-day grid.
- `_calendar_query(start)` → `start=<iso>`.
- `_calendar_navigation(url_name, start, today, query_extra='')` → `{previous_url, today_url, next_url, is_today}`.
- Remove `_default_window_start`, `_list_mode_for` and the `mode`/`modes` context keys.
- `index` ignores `view`.
- `detail` derives its window from `?start`, else from the entry's date.
- `delete` reads POST `start` and redirects to `index` with that window.
- `_detail_context` drops `list_mode`.

#### 2. Shared navigation partial

**Files**: new `entries/templates/entries/_calendar_nav.html`; `_manage_list.html`; `family_notes/static/css/tokens.css` (only if spacing for three links needs it)

**Intent**: One nav for both calendars.

**Contract**:
- `<nav class="fn-calendar-nav" aria-label="Nawigacja kalendarza" data-state-part="calendar-nav">`
  with links "Wcześniejsze", "Dzisiaj", "Następne". All three are always present.
- "Dzisiaj" carries `aria-current="page"` when `is_today`.
- `_manage_list.html` drops the `_list_modes.html` include and its inline nav.
- `data-state-part="calendar-{{ mode }}"` becomes `data-state-part="calendar"`.

#### 3. Parent detail and delete

**File**: `entries/templates/entries/_manage_detail.html`

**Intent**: "Wróć do listy" and the delete form carry only `start`.

**Contract**: the back link is `{% url 'entries:index' %}?{{ list_query }}`, where `list_query` is
`start=…`. The hidden `view` input is removed and `start` is kept.

#### 4. States gallery

**Files**: `entries/views.py` (`_synthetic_list`, list/detail states), `entries/templates/entries/states.html`

**Intent**: The gallery shows a today window and an earlier window instead of upcoming/past.

**Contract**: states `list_today` (start = `STATES_DATE`), `list_earlier`
(start = `STATES_DATE − 14`) and `list_empty`. Detail states use the new `_detail_context` signature.

#### 5. Tests

**Files**: `entries/tests/test_manage_views.py` (`IndexOrderingTests`, `EmptyIndexTests`,
`CalendarPresentationTests`, `CalendarWindowTests`, `DetailTests`, `DeleteTests`,
`GroupedIndexTests`), `test_manage_states.py`, `test_manage_access.py`, `test_accessibility.py`
(`ManagementAuditTests`), `test_multi_family_access.py`

**Intent**: Pin the new window model and drop the mode assertions.

**Contract**: new or rewritten tests cover:
- the default window = today..today+13;
- "Wcześniejsze" from the default = today−14..today−1, and from there "Następne" returns to today;
- moving forward and back across today;
- invalid, non-canonical and out-of-range `start` fall back to today;
- `view=past` is ignored;
- "Dzisiaj" has `aria-current` only on the today window;
- the detail back link without `start` returns to the window containing the entry, for both a past and a future entry;
- the delete redirect keeps `start`;
- the accessibility audit of the today and earlier windows (h1, 14 × h2, h3 per assignee).

### Success Criteria:

#### Automated Verification:

- Entries tests pass: `uv run python manage.py test entries`
- Django checks pass: `uv run python manage.py check`
- No list-mode tabs left in the parent calendar: `grep -n "_list_modes\|view=" entries/templates/entries/_manage_list.html entries/templates/entries/_manage_detail.html` returns nothing

#### Manual Verification:

- Parent calendar: "Wcześniejsze", "Dzisiaj" and "Następne" move the window as specified; "Dzisiaj" is highlighted only on today's window
- Opening an entry and clicking "Wróć do listy" returns to the same window; deleting an entry lands on the window it was in

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 3: Child calendar

### Overview

`/entries/mine/` renders the shared calendar with only the child's entries, lucky numbers included,
and no assignee subheadings. The old list code is removed.

### Changes Required:

#### 1. Shared day grid

**Files**: new `entries/templates/entries/_calendar_days.html`; `_manage_list.html`; new or rewritten child body template (replacing `_child_list_body.html`)

**Intent**: One template for the 14 day boxes, used by both views.

**Contract**:
- Parameters: `days`, `detail_url_name`, `detail_query`, `show_groups`.
- With `show_groups`, it renders the existing h3-per-assignee sections. Without it, it renders
  one list per day labelled by the day heading (`aria-labelledby` pointing at a unique heading id).
- Keeps `data-day-group`, `data-weekend`, `fn-calendar-day--empty` and "Brak wpisów".
- Child rows render with `hide_assignee`, `hide_date` and `hide_type`, as today.

#### 2. Child view

**File**: `entries/views.py` (`child_list`, `child_detail`, `child_states`)

**Intent**: The child gets the same window, navigation and day boxes.

**Contract**:
- `child_list` reads `?start` via `_calendar_window` and filters `child_entries(...)` by
  `effective_date` in the window. Lucky numbers are not excluded.
- It builds `days` with the shared builder (one group per day), `parent_day_heading` headings, and
  `_calendar_navigation('entries:child_list', …)`.
- Entry links carry `start`.
- `child_detail`'s back link returns to `?start` or to the window containing the entry (replacing `back_mode`).
- The `child_states` gallery shows a today window, an earlier window and an empty window,
  relative to `STATES_DATE`, plus the detail states.

#### 3. Remove dead list-mode code

**Files**: `entries/listing.py`, `entries/views.py`, `entries/templates/entries/_list_modes.html`, `_child_entry_detail.html`, `scripts/hooks/quality_gate.py`

**Intent**: Delete code with no remaining caller.

**Contract**:
- Remove `UPCOMING`/`PAST`/`LIST_MODES`/`DEFAULT_LIST_MODE`, `normalize_list_mode`,
  `partition_entries`, `EntrySection`, the `SECTION_*` constants, `day_heading`, `group_by_day`
  and `WEEKDAY_HEADING_MAX_DAYS`.
- Remove `LIST_MODE_LABELS`, `UNDATED_DAY_HEADING` and `CHILD_EMPTY_MESSAGES`.
- Delete `_list_modes.html` and the old child body template.
- Keep `with_effective_date`, `parent_day_heading`, `is_weekend` and `split_by_assignee`.
- Update the template list in `quality_gate.py`.
- If `.fn-tabs` CSS is unused after this phase, keep it: Phase 4 reuses it.

#### 4. Tests

**Files**: `entries/tests/test_child_views.py`, `test_child_states_view.py`, `test_entry_listing.py`, `test_accessibility.py` (`ChildAuditTests`), `test_multi_family_access.py`

**Intent**: Pin the child calendar and remove tests of deleted code.

**Contract**: tests cover:
- 14 day boxes with full headings and "Brak wpisów" on empty days;
- only the child's own entries appear: no siblings, no unassigned entries, no other families;
- the child's lucky number appears on its day (replacing the "not in list" assertion at `test_child_views.py:409`);
- no `h3` subheadings;
- the three nav links with today/earlier/next windows;
- entry links carry `start`, and the back link returns to the same window, or to the window containing the entry when `start` is absent;
- weekend `data-weekend` markers still work in both views;
- the accessibility audit of the child today window, earlier window and empty window.

Delete `ListModeTests`, `PartitionTests`, `DayHeadingTests` and `GroupByDayTests`, keeping any
lucky-number or grade effective-date assertions that still apply via `with_effective_date`.

### Success Criteria:

#### Automated Verification:

- Entries tests pass: `uv run python manage.py test entries`
- No list-mode symbols remain: `grep -rn "partition_entries\|normalize_list_mode\|LIST_MODES\|_list_modes\|Nadchodzące\|Minione" entries scripts family_notes --include=*.py --include=*.html` returns nothing
- Full test suite passes: `uv run python manage.py test`

#### Manual Verification:

- Signed in as a child: the calendar looks like the parent's (14 boxes, weekend strip, "Brak wpisów"), with no name subheadings and only own entries, lucky number included
- Child navigation and "Wróć do listy" behave like the parent's, on a phone in portrait and landscape

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 4: Parent filter by child (client-side)

### Overview

"Wszyscy" plus one button per active child narrows the parent calendar to that child plus
"Ogólne". Switching is instant: the page already holds every row of the window, and a small
script shows or hides assignee groups without a request. The same markup works without
JavaScript, because the links carry `?member=` and the server renders the initial hidden state.

### Changes Required:

#### 1. Filter resolution and initial state

**File**: `entries/views.py` (with a small queryset helper in `family_access` or `entries/services.py`, following `entries/forms.py:168-170`)

**Intent**: Resolve `?member` safely and render the matching initial state, always with every row
of the window in the page.

**Contract**:
- A helper returns the active CHILD memberships of the request family, ordered by pk.
- `index` keeps `member` only if its pk is among them; anything else means "Wszyscy".
- Rows are **not** filtered in the query. Each assignee group gets `hidden` when a member is
  selected and the group is neither `member-<pk>` nor `family`.
- Each day's "Brak wpisów" element is always rendered. It is `hidden` when at least one group of
  that day is visible. `fn-calendar-day--empty` follows the same visible-groups rule.
- The context gains `filters` (each with key, label, url, current) and `member_query`
  (`member=<pk>` or empty).

#### 2. Filter nav markup

**Files**: new `entries/templates/entries/_member_filter.html`; `_manage_list.html`; `_calendar_days.html`; `_calendar_nav.html`; `_manage_detail.html`

**Intent**: Real links that also serve as script hooks; the selection is carried everywhere.

**Contract**:
- `<nav class="fn-tabs" aria-label="Filtr wpisów" data-member-filter>`, with one link per filter:
  - `href` = the index URL with the current `start`, plus `member=<pk>` except for "Wszyscy";
  - `data-member-key="all"` or `data-member-key="member-<pk>"`;
  - `aria-current="page"` on the active one.
- One `role="status" aria-live="polite" data-live-region` region per the S-06 live-region contract
  (`context/foundation/accessibility.md`, "Script contracts"), with one hidden state block per
  filter ("Pokazano: wszystkie wpisy", "Pokazano: Kasia i Ogólne", …). It is never under a `hidden` ancestor.
- Calendar nav links and entry links carry `member` when set, and are marked `data-member-link`
  so the script can rewrite them.
- "Wróć do listy" and the delete form/redirect carry `member`; `detail` and `delete` re-validate it.
- A family with no active children renders neither the filter nav nor the live region.
- Add a filtered list state to the states gallery.

#### 3. Filter script

**Files**: new `family_notes/static/js/member-filter.js`; `entries/templates/entries/manage_index.html`

**Intent**: Switch filters instantly, with no request.

**Contract**:
- Loaded with `defer` only on the parent calendar page, the same way `list-refresh.js` is loaded.
- A click on a `[data-member-filter] a` without modifier keys calls `preventDefault()`, then:
  - toggles `hidden` on assignee groups, the per-day "Brak wpisów" and `fn-calendar-day--empty`
    by exactly the server rule from change 1;
  - moves `aria-current`;
  - reveals the matching live-region state;
  - rewrites `member` in every `[data-member-link]` href;
  - updates the address bar with `history.replaceState`, so a reload, the back link and
    `list-refresh.js` keep the filter.
- Ctrl/Cmd/middle clicks are left alone and open the server-rendered link.
- Header comment in the style of `list-refresh.js`. No dependencies, nothing stored in the browser.
- Add a "Member filter (`js/member-filter.js`)" entry to "Script contracts" in `context/foundation/accessibility.md`.

#### 4. Tests

**Files**: `entries/tests/test_manage_views.py`, `test_manage_access.py`, `test_manage_states.py`, `test_accessibility.py`; new `tests/e2e/member-filter.spec.ts`

**Intent**: Pin the server rule and the filter's safety in Django tests. Pin the instant switching
in a browser test: it is behaviour only a browser can show.

**Contract**:
- Django tests cover:
  - "Wszyscy" plus one link per active child, in pk order;
  - no link for parents or inactive children;
  - `member=<child>` renders every row, with sibling and parent groups `hidden`, and the child and
    `family` groups visible;
  - "Brak wpisów" and `fn-calendar-day--empty` follow visible groups;
  - another family's member pk, a parent pk, an inactive child pk or junk all render as "Wszyscy",
    and the page never shows another family's rows;
  - `member` is carried through the calendar nav, entry links, the back link and the delete redirect;
  - `aria-current` is on the active filter;
  - the accessibility audit (including the live-region rule) of a filtered and an unfiltered window.
- E2E (Playwright, seeded `test_rodzic` with children Kasia and Tymek), using its own uniquely
  named entries for each child and cleaning them up afterwards:
  - clicking "Kasia" hides Tymek's entry and keeps Kasia's and an "Ogólne" entry, with no document
    request (`page.on('request')` sees no navigation);
  - the URL gains `member=`;
  - "Następne" then "Wcześniejsze" keep the filter;
  - "Wszyscy" shows Tymek's entry again.

### Success Criteria:

#### Automated Verification:

- Entries tests pass: `uv run python manage.py test entries`
- Full test suite passes: `uv run python manage.py test`
- Django checks pass: `uv run python manage.py check`
- No migrations needed: `uv run python manage.py makemigrations --check --dry-run`
- Filter E2E passes: `npx playwright test tests/e2e/member-filter.spec.ts`

#### Manual Verification:

- Parent calendar: "Wszyscy" plus a button per child; selecting a child shows that child's and "Ogólne" entries instantly, with no page reload; the selection stays when navigating weeks, opening an entry and going back
- With JavaScript disabled, the same buttons still filter (by page load)
- Buttons wrap nicely and stay usable on a phone in portrait and landscape; a screen reader announces the new filter

---

## Testing Strategy

### Unit Tests:

- Window validation and `_window_containing` across today in both directions.
- Member filter resolution (valid child, sibling, parent, inactive child, other family, junk).

### Browser Tests:

- `tests/e2e/member-filter.spec.ts`: instant client-side filtering with no navigation request, URL
  update, filter kept through week navigation, back to "Wszyscy".

### Integration Tests:

- Parent and child calendar views, detail back links, the delete redirect, both galleries.
- The accessibility audit (`entries/tests/test_accessibility.py`) for the parent (unfiltered and
  filtered) and child calendars.

### Manual Testing Steps:

1. As `test_rodzic`: rename visible, navigation, filter per child, back link and delete keep the window and filter.
2. As `test_kasia`: the calendar matches the parent's look, with own entries only and the lucky number visible.
3. Repeat both on a phone in portrait and landscape.

## Performance Considerations

The child view switches from all upcoming or past entries to a bounded 14-day range query, which is
cheaper. The filter adds one small query for the family's children. Filter switching costs no request:
the 14-day window's rows are already on the page.

## Migration Notes

No schema changes. Old bookmarks with `?view=` keep working and open today's window.

## References

- Change notes and decisions: `context/changes/child-calendar-view/change.md`
- Calendar layout decisions: `context/archive/2026-10-07-parent-entries-calendar-layout/plan.md`
- Child list UI and tab a11y: `context/archive/2026-10-04-child-list-ui/plan.md`
- Assignee grouping: `context/changes/parent-list-child-grouping/plan.md`
- Accessibility checklist: `context/foundation/accessibility.md`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Rename "Cała rodzina" to "Ogólne"

#### Automated

- [x] 1.1 Entries tests pass: `uv run python manage.py test entries` — 3a4ec2f
- [x] 1.2 No "Cała rodzina" left in product code: `grep -rn "Cała rodzina" entries family_access family_notes --include=*.py --include=*.html | grep -v /tests/` returns nothing — 3a4ec2f

#### Manual

- [ ] 1.3 Parent calendar subheading, the assignee select's empty option and the saved panel read "Ogólne"

### Phase 2: Free 14-day window with Wcześniejsze / Dzisiaj / Następne (parent)

#### Automated

- [x] 2.1 Entries tests pass: `uv run python manage.py test entries`
- [x] 2.2 Django checks pass: `uv run python manage.py check`
- [x] 2.3 No list-mode tabs left in the parent calendar: `grep -n "_list_modes\|view=" entries/templates/entries/_manage_list.html entries/templates/entries/_manage_detail.html` returns nothing

#### Manual

- [ ] 2.4 Parent calendar: "Wcześniejsze", "Dzisiaj" and "Następne" move the window as specified; "Dzisiaj" is highlighted only on today's window
- [ ] 2.5 Opening an entry and clicking "Wróć do listy" returns to the same window; deleting an entry lands on the window it was in

### Phase 3: Child calendar

#### Automated

- [ ] 3.1 Entries tests pass: `uv run python manage.py test entries`
- [ ] 3.2 No list-mode symbols remain: `grep -rn "partition_entries\|normalize_list_mode\|LIST_MODES\|_list_modes\|Nadchodzące\|Minione" entries scripts family_notes --include=*.py --include=*.html` returns nothing
- [ ] 3.3 Full test suite passes: `uv run python manage.py test`

#### Manual

- [ ] 3.4 Signed in as a child: the calendar looks like the parent's (14 boxes, weekend strip, "Brak wpisów"), with no name subheadings and only own entries, lucky number included
- [ ] 3.5 Child navigation and "Wróć do listy" behave like the parent's, on a phone in portrait and landscape

### Phase 4: Parent filter by child (client-side)

#### Automated

- [ ] 4.1 Entries tests pass: `uv run python manage.py test entries`
- [ ] 4.2 Full test suite passes: `uv run python manage.py test`
- [ ] 4.3 Django checks pass: `uv run python manage.py check`
- [ ] 4.4 No migrations needed: `uv run python manage.py makemigrations --check --dry-run`
- [ ] 4.5 Filter E2E passes: `npx playwright test tests/e2e/member-filter.spec.ts`

#### Manual

- [ ] 4.6 Parent calendar: "Wszyscy" plus a button per child; selecting a child shows that child's and "Ogólne" entries instantly, with no page reload; the selection stays when navigating weeks, opening an entry and going back
- [ ] 4.7 With JavaScript disabled, the same buttons still filter (by page load)
- [ ] 4.8 Buttons wrap nicely and stay usable on a phone in portrait and landscape; a screen reader announces the new filter
