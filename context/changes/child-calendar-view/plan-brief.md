# Shared Calendar for Parent and Child — Plan Brief

> Full plan: `context/changes/child-calendar-view/plan.md`

## What & Why

Parents and children should see the same 14-day calendar. Navigation becomes three simple
buttons: "Wcześniejsze", "Dzisiaj" and "Następne". A parent can narrow the calendar to one
child. The unassigned label "Cała rodzina" becomes "Ogólne" everywhere.

## Starting Point

The parent calendar has two modes ("Nadchodzące" moves only forward from today, "Minione" only
backward from yesterday) plus "Poprzednie/Następne 2 tygodnie" links. The child sees a different
list: all upcoming or all past entries, short relative headings, lucky numbers hidden. There is no
filtering.

## Desired End State

Both `/entries/` and `/entries/mine/` show the same 14 day boxes with full headings, "Brak wpisów"
on empty days and the weekend strip. The window moves 14 days at a time across today, and
"Dzisiaj" returns to the window starting today. The child sees only their own entries, lucky
numbers included, without name subheadings. The parent has "Wszyscy" plus one button per child;
the selection survives navigation, opening an entry and deleting one.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) |
| --- | --- | --- |
| Navigation | One free `start` window; Wcześniejsze −14, Dzisiaj = today, Następne +14 | Owner asked for simple date navigation; the today boundary is dropped. |
| Old `?view=` links | Ignored, so they open today's window | Nothing else depends on `view`; no compatibility shim is needed. |
| Child view | Same day grid and navigation as the parent, no name subheading | The child sees only their own entries, so the name adds nothing. |
| Child scope | Only entries assigned to the child | Unchanged access rule (FR-007). |
| Lucky numbers | Shown to the child, still hidden for the parent | Owner decision; reverses the S-03 rule for the child only. |
| Filter model | One child at a time plus "Wszyscy" (default), `?member=<pk>` | Same tab pattern as before; links also work without JS. |
| Filter speed | Client-side: page holds all rows; `member-filter.js` hides other groups, no request | Owner wants instant switching; the server renders the same initial state for no-JS and reloads. |
| Filtered content | That child's entries plus "Ogólne" | Shows everything that concerns the child. |
| Filter buttons | Active children only, no parents | "One button per child"; inactive children stay visible under "Wszyscy". |
| Invalid `member` | Behaves as "Wszyscy" | Never leaks or errors on another family's ids. |
| Rename | "Ogólne" everywhere (calendar, form, row, detail, saved panel) | One term for unassigned entries. |

## Scope

**In scope:** the rename, the window model and three-link nav (shared), the child calendar, removal
of the list-mode code, the parent filter, galleries, and tests including the accessibility audit.

**Out of scope:** multi-select filter, filter on the child view, filters for parents, an undated
section, the legacy `?view` mapping, API changes, fixing the pre-existing E2E heading expectation.

## Architecture / Approach

Window helpers (`_calendar_window`, `_window_containing`, `_calendar_navigation`) lose their mode
and serve both views. A shared `_calendar_nav.html` and a shared `_calendar_days.html`
(`show_groups` flag) render both calendars. The filter adds a validated `member` param that flows
through the nav, entry links, the back link and delete, like `start` does. The server always
renders the full window and marks non-matching groups `hidden`. `member-filter.js` switches
instantly by applying the same rule, rewriting links and the URL (`replaceState`) and announcing
the change in a live region.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Rename to "Ogólne" | One label everywhere | Missing a spot (grep gate) |
| 2. Free window + 3 buttons (parent) | New navigation, back link and delete keep the window | Large test rewrite in manage views |
| 3. Child calendar | Child sees the parent-style calendar; list-mode code removed | Child tests and gallery rewritten; a11y ids |
| 4. Parent child filter (client-side) | Instant "Wszyscy" plus per-child buttons, carried everywhere; E2E test | Server and script visibility rules drifting apart; a foreign member id |

**Prerequisites:** `weekend-day-header-colours` is merged (it is, as `f8b7692`).
**Estimated effort:** ~3–4 sessions across 4 phases.

## Open Risks & Assumptions

- The E2E spec's heading expectation may already be failing; it is tracked separately.
- Dropping the today boundary reverses a recorded calendar-layout decision; the owner confirmed it.

## Success Criteria (Summary)

- A parent and a child see the same-looking calendar and move through it with Wcześniejsze / Dzisiaj / Następne.
- A parent can focus on one child instantly, and the choice sticks while browsing.
- No "Nadchodzące"/"Minione" or "Cała rodzina" left, and all tests including accessibility pass.
