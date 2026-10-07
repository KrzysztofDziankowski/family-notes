# Parent Entries Calendar Layout — Plan Brief

> Full plan: `context/changes/parent-entries-calendar-layout/plan.md`

## What & Why

The parent entries list will become a navigable two-week calendar. Every day remains visible even when it has no entries, making family plans easier to scan and gaps immediately understandable.

## Starting Point

The parent list already groups entries by day and then assignee, but emits only populated dates. Upcoming and past lists are unbounded, and nearby date headings omit the numeric date.

## Desired End State

Parents see 14 dated boxes at a time, navigate backward or forward by two weeks, and return from entry details to the same window. Empty days show `Brak wpisów`; mobile uses one column and wide screens use seven.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) |
| --- | --- | --- |
| Window size | 14 consecutive days | The requested view covers two weeks at a time. |
| Upcoming default | Today through day +13 | The first box is immediately relevant and predictable. |
| Past default | Day -14 through yesterday | It preserves the boundary between upcoming and past. |
| Navigation | Previous/next by 14 days | Entries outside the initial window remain reachable without huge empty ranges. |
| Wide layout | Seven columns | Two rows resemble a conventional two-week calendar. |
| Narrow layout | One column | It preserves readability at the 320px accessibility target. |
| Empty dates | Show `Brak wpisów` | Intentional emptiness is clear visually and to assistive technology. |
| Undated rows | Omit from this view | Date enforcement outside this view is a separate change. |
| Date headings | Relative label plus full date | It matches the requested `Dziś, 7 października` style. |
| Existing work | Preserve and reconcile | The user's template and E2E edits must not be overwritten. |

## Scope

**In scope:**

- Parent-only 14-day upcoming and past calendar windows.
- ISO `start` query parameter and two-week navigation.
- Stable detail/back links for the selected window.
- Full Polish day headings, empty boxes, responsive 1→7-column styling.
- Parent view, state-gallery, accessibility, and focused E2E coverage.

**Out of scope:**

- Child-list changes, month view, drag-and-drop, or a JavaScript calendar.
- Model, migration, classification, automation, or authorization changes.
- Date-prefilled add actions or legacy-data cleanup.

## Architecture / Approach

The parent view normalizes a `start` date, bounds the existing family-scoped query, and synthesizes exactly 14 chronological day records. The existing template grouping fills populated boxes; empty records render `Brak wpisów`. Parent-only token-based CSS presents one column on narrow screens and seven on wide screens.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Calendar Window Contract | Date bounds, query normalization, navigation, headings, and stable back links | Off-by-one errors around today |
| 2. Calendar Presentation | Fourteen semantic boxes and responsive 1→7-column layout | Dense content in seven-column mode |
| 3. Regression and Acceptance Coverage | View, gallery, accessibility, and E2E verification | Stale populated-date-only assertions |

**Prerequisites:** Existing parent day→assignee grouping; no schema work required.
**Estimated effort:** Approximately 2–3 implementation sessions across 3 phases.

## Open Risks & Assumptions

- Wide seven-column boxes may be compact; correctness and 320px reflow take priority over equal box heights.
- URLs without `start` remain valid and resolve to the mode's default fortnight.
- Current persisted entries have required dates; the legacy undated branch is not part of this UI contract.
- The uncommitted parent template and E2E changes remain user-owned and must be merged carefully.

## Success Criteria (Summary)

- Both modes always render the correct 14-day window and navigate in 14-day increments.
- Empty dates remain visible while populated dates preserve assignee grouping and exactly-once rendering.
- Navigation, detail return paths, accessibility, family isolation, query bounds, and responsive behavior are verified.
