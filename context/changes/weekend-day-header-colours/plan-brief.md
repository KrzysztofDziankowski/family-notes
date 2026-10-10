# Weekend Day Header Colours — Plan Brief

> Full plan: `context/changes/weekend-day-header-colours/plan.md`

## What & Why

Saturday and Sunday day headings (e.g. "Dziś, sobota 10 października") get a pale red background
so weekend days stand out in the family calendar and the child's list.

## Starting Point

Day headings are plain `<h2 class="fn-day-heading">` in the parent 14-day calendar and the child
list; no day is visually emphasised. Colours live only in `tokens.css` and are contrast-tested.

## Desired End State

Every weekend heading in both lists shows a pale red strip behind the unchanged dark text; weekday
and "Bez daty" headings look as before; the new colour passes the 4.5:1 contrast suite.

## Key Decisions Made

| Decision          | Choice                                  | Why (1 sentence)                                                   |
| ----------------- | --------------------------------------- | ------------------------------------------------------------------ |
| Saturday vs Sunday | One shared weekend colour              | User wants weekends distinct from weekdays, not from each other.   |
| Scope             | Parent calendar and child list          | Consistent look wherever `.fn-day-heading` appears.               |
| Style             | Light red tint, existing dark text      | Passes contrast easily and doesn't read as an error panel.        |
| Marker            | Section modifier (parent), `data-weekend` after `id` (child) | Keeps the `<h2>` markup existing tests match unchanged. |
| Tests             | Django unit/view tests + contrast pair, no E2E | Marker is server-rendered; a browser adds no coverage.       |

## Scope

**In scope:** `is_weekend` helper, context flags, two templates, one token + CSS rule, tests.

**Out of scope:** separate Saturday/Sunday colours, public holidays, a "today" highlight, E2E test, dark theme.

## Architecture / Approach

`is_weekend(day)` in `entries/listing.py` → `'is_weekend'` in `_index_days` / `_child_list_context`
→ `fn-calendar-day--weekend` on the parent day `<section>` and `data-weekend` on the child `<h2>` →
one CSS rule using `--fn-color-weekend-bg`.

## Phases at a Glance

| Phase                              | What it delivers                         | Key risk                                    |
| ---------------------------------- | ---------------------------------------- | ------------------------------------------- |
| 1. Weekend flag and markup         | Flag + markers + tests, no visual change | Breaking literal-markup regexes in tests    |
| 2. Weekend token, CSS and contrast | Visible pale red strip, contrast guarded | Strip crowding narrow seven-column layout   |

**Prerequisites:** none.
**Estimated effort:** ~1 short session across 2 phases.

## Open Risks & Assumptions

- Weekend = Saturday/Sunday only; holidays are not coloured.

## Success Criteria (Summary)

- Parents and children see weekend days highlighted at a glance on phone and desktop.
- All tests, including the contrast suite, pass.
