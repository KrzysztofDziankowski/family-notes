---
date: 2026-10-04T09:10:10+02:00
researcher: Claude (Opus 5.5) for Krzysztof Dziankowski
git_commit: 199cfdb3e69192ccd7630432afedabe743da3442
branch: master
repository: family-notes
topic: "UI audit of the child list /entries/mine/ against the Pico + tokens.css contract"
tags: [research, ui, child-list, tokens, pico, entries]
status: complete
last_updated: 2026-10-04
last_updated_by: Claude (Opus 5.5)
---

# Research: UI audit of the child list `/entries/mine/`

**Date**: 2026-10-04T09:10:10+02:00
**Researcher**: Claude (Opus 5.5) for Krzysztof Dziankowski
**Git Commit**: 199cfdb3e69192ccd7630432afedabe743da3442
**Branch**: master
**Repository**: family-notes

## Research Question

Run the `/10x-ui` two-way audit (source → views, view → source) for the child list
`/entries/mine/` and its drill-down `/entries/mine/<pk>/`, and produce 3–5 charges with
file, line and the effect on the user, as the input to `/10x-plan`.

## Summary

The view is already built on the existing design system: the hardcoded-value scan over
the five view templates returns 0 hits, and every `--fn-*` token declared in
`family_notes/static/css/tokens.css` is read at least once inside that file. The tokens
are not dead, and the problem is not literal colours.

What is wrong sits elsewhere:

- **The way in and the way out are broken.** `/` is an English placeholder with literal
  colours, which the brand link in every page header points at. A user without an active
  child membership, or anyone following a detail link they may not read, gets Django's
  unstyled English 403/404 page (C1, C2).
- **The same control exists twice.** The child's "Nadchodzące / Minione" switch is a Pico
  button group. The parent list's switch for the same job is `.fn-manage-tabs`. The two
  empty states are also styled differently (C3).
- **Row interaction states are invisible.** `.fn-entry-link` cancels Pico's hover change.
  Keyboard focus falls back to a 25 %-alpha accent ring at about 1.43:1 against the white
  row (C4).
- **Every row has the same visual weight.** Dated entries are not grouped. The date, the
  thing a child scans for, is the lowest-weight text on the row (C5).

The contract variant is **existing design system**: Pico v2.1.1 plus `tokens.css`, light
theme only. The kitchen sink is `child_states.html`, which renders 6 states. No agent
rules file contains UI guidance.

## Charges

| # | Category | Evidence (file:line) | Effect on the user |
| --- | --- | --- | --- |
| C1 | Accidental architecture | `family_notes/templates/base.html:14` (brand → `home`); `family_notes/templates/family_notes/home.html:1-71` (standalone English placeholder, 5 literal colours at lines 11, 12, 29, 35, 50); `family_access/templates/family_access/account_status.html:24` ("Strona główna" → `home`); `family_notes/settings.py:289-290` (login → `/account/`, logout → `/`) | A child who taps "FamilyNotes" in the header of their list lands on "Hello, FamilyNotes! The application is running." That page is in English, has no navigation and no link back. Their list is two taps away, through Konto → "Moje wpisy". |
| C2 | Accidental architecture | `entries/services.py:251-253` (`PermissionDenied` for a non-child); `entries/views.py:744` (`get_object_or_404` for a foreign or missing pk); no `403.html` or `404.html` in `family_notes/templates/` (`DIRS` at `family_notes/settings.py:211`) or in any app template directory | A parent who opens a child's link, or a child following a stale or sibling link, gets Django's built-in unstyled English error page. It has no header, no "Wróć" link and no Polish copy, which breaks the Polish-UI rule in `context/foundation/lessons.md:16`. |
| C3 | Missing shared component | `entries/templates/entries/_child_list_body.html:6-11` (Pico `role="group"` + `role="button"` + `.outline`) vs `entries/templates/entries/_manage_list.html:4-10` + `tokens.css:190-223` (`.fn-manage-tabs`); empty state `_child_list_body.html:20-22` (`.fn-panel`, solid accent rule) vs `_manage_list.html:12` + `tokens.css:231-236` (`.fn-manage-empty`, dashed border) | The same "which list am I looking at" switch looks like two big action buttons for the child and like tabs for the parent. The child's empty message reuses the accent-ruled panel that the detail page uses for content, so "nothing here" looks the same as "here is your entry". |
| C4 | Missing tokens (interaction states) | `tokens.css:158-162` (`.fn-entry-link` sets `color` and `text-decoration: none` directly, which overrides Pico's `:where(a…):hover` variable changes); `tokens.css:19,55` (`--fn-color-accent-focus` = `rgba(47,111,94,0.25)` mapped to `--pico-primary-focus`); Pico `:where(a:not([role=button])):focus-visible { box-shadow: 0 0 0 var(--pico-outline-width) var(--pico-primary-focus) }` with `--pico-outline-width: 0.125rem` | Hovering a row changes nothing, so a mouse user gets no sign that the row is clickable. A keyboard user tabbing through the list gets a 2px ring of `#cbdbd7` on a white `#ffffff` row, a 1.43:1 contrast that is effectively invisible (WCAG 1.4.11 asks for 3:1). The mode switch uses the same focus token through `[role=group]:has([role=button]:focus)`, so it shares the problem. |
| C5 | Accidental architecture (hierarchy) | `_child_list_body.html:12-18` (only the undated section gets a heading, line 13); `_entry_row.html:14-18` (date in `.fn-entry-meta.fn-muted` at 0.875em, after the content); screenshot `context/archive/2026-09-28-child-assigned-entry-view/screenshots/child-states-360.png` (two consecutive rows both end "poniedziałek, 5 października 2026") | To answer "what do I have tomorrow", a child has to read the small grey last line of every card. Several entries on the same day repeat the full date, and nothing separates today from next week. |

## Detailed Findings

### Source → views

- Value source: `family_notes/static/css/tokens.css:10-34` declares 23 `--fn-*` custom
  properties: colours, font, 4 spacing steps, radius and accent-rule width. Lines 37-62 map
  them onto Pico variables. The file header (lines 1-7) records where the values came from.
- Loaded globally by `family_notes/templates/base.html:7-8` (Pico, then tokens).
- Usage check: for each `--fn-*` name at lines 11-33, `var(<name>)` occurs at least once
  in `tokens.css`. No token is unused. Templates reference classes, not variables.
- Class usage per template (count of `fn-*` occurrences / Pico role or variant attributes,
  inspected set only): `_child_list_body.html` 4 / 5, `_entry_row.html` 7 / 0,
  `_child_entry_detail.html` 2 / 0, `child_list.html` 0 / 0, `_manage_list.html` 5 / 0,
  `family_notes/home.html` 0 / 0 with 5 literal-colour lines.
- Shared components are Django partials in `entries/templates/entries/_*.html`. The child
  view reuses `_entry_row.html`, which is shared with the parent list (`_entry_row.html:1-11`
  documents the parameters).
- `family_notes/templates/family_notes/home.html` does not extend `base.html`. It carries
  its own `<style>` block with the same values as the tokens, written as literals
  (`#f7f8fa`, `#20242a`, `#2f6f5e`, `#5d6670`, `#3d454d`). `tokens.css:2` names this page
  as the original source of those values.

### View → source

- Hardcoded-value scan (the `/10x-ui` regex) over `child_list.html`,
  `_child_list_body.html`, `_entry_row.html`, `_child_entry_detail.html` and
  `child_detail.html`: **0 hits**. This is the baseline for later phases.
- Pico primitives used straight in the view: `role="group"`, `role="button"` and `.outline`
  at `_child_list_body.html:7-9`. These are Pico's components, not literals, but they
  duplicate a job that `.fn-manage-tabs` already does (C3).
- `.fn-panel` is used for both the empty state (`_child_list_body.html:20`) and the
  detail article (`_child_entry_detail.html:6`).
- Font-size `0.875em` is written twice in `tokens.css` (lines 167, 181), and `1rem` twice
  (lines 226, 280). There is no type-scale token. This is minor and inside the token file,
  not in a view.

### Entry points (logged out / no data / direct link)

- Logged out: both child routes are `@login_required` (`entries/views.py:730-731` for the
  list, 740-741 for the detail), so the user is redirected to allauth login. After login,
  `LOGIN_REDIRECT_URL = '/account/'` (`settings.py:289`) shows the account status page. For
  a child, its only action there is "Moje wpisy" (`account_status.html:18-20`).
- No data: `_child_list_context` drops empty sections (`entries/views.py:725`). The
  `{% empty %}` branch then renders a Polish message from `CHILD_EMPTY_MESSAGES`
  (`entries/views.py:706-709`). This is a real empty state (C3 concerns only its styling).
- Wrong role: `child_entries` raises `PermissionDenied` for anyone who is not an active
  child (`services.py:251-253`). The access matrix that the archived plan required is
  covered by tests: 403 for parent, inactive and unconfigured users.
  (`context/archive/2026-09-28-child-assigned-entry-view/plan.md:154`). The page shown is
  Django's default, because no `403.html` exists (C2).
- Direct link to a foreign or missing entry: identical 404s by design
  (`plan.md:155`). The body is Django's default `404.html` fallback (C2).
- Loading: the pages are fully server-rendered, and the child templates contain no JS or
  partial fetches (inspected: the 5 view templates + `base.html`). A loading state is
  **N/A** unless the plan adds client-side fetching.
- Disabled: the view has no form controls. **N/A**.

### Interaction states (CSS reading, not rendered)

- Hover on a row: Pico's hover rule sets `--pico-color` and `--pico-text-decoration`
  through `:where()` (zero specificity). `.fn-entry-link` sets `color` and
  `text-decoration` directly (`tokens.css:158-162`), so neither variable takes effect.
  Inference from the cascade, not observed in a browser: no visible hover.
- Focus-visible: row links and mode buttons get a `box-shadow` ring in
  `--pico-primary-focus` = `--fn-color-accent-focus`. Composited over `--fn-color-surface`,
  this is `#cbdbd7`, 1.43:1 against `#ffffff` (computed). For comparison, accent text is
  5.91:1 and muted text is 5.83:1 on the surface (computed).
- The kitchen sink at `child_states.html` cannot show hover or focus. Its 6 states are
  upcoming, past, both empties and two details. It does not render a 403/404 state.

### Agent rules

- `AGENTS.md` and `CLAUDE.md` contain no UI section: a grep for css, pico, token, template
  and style finds only hook-related lines. Nothing tells an agent to use one-off values, so
  there is no rule-caused charge. Nothing points an agent at `tokens.css`,
  the `_*.html` partials or the kitchen sink either. That gap is for the "Make it stick"
  step, not a charge.

## Code References

- `family_notes/static/css/tokens.css:10-34` — semantic token declarations
- `family_notes/static/css/tokens.css:37-62` — mapping onto Pico variables
- `family_notes/static/css/tokens.css:158-162` — `.fn-entry-link` (C4)
- `family_notes/static/css/tokens.css:190-236` — `.fn-manage-tabs`, `.fn-manage-empty` (C3)
- `family_notes/static/css/tokens.css:270-283` — child-view classes
- `family_notes/templates/base.html:7-8,14` — stylesheet order, brand link (C1)
- `family_notes/templates/family_notes/home.html:1-71` — placeholder home (C1)
- `entries/templates/entries/_child_list_body.html:6-23` — mode switch, sections, empty state
- `entries/templates/entries/_entry_row.html:12-22` — shared row
- `entries/templates/entries/_child_entry_detail.html:6-26` — detail body
- `entries/templates/entries/child_states.html:8-18` — kitchen sink
- `entries/templates/entries/_manage_list.html:4-12` — parent tabs and empty state
- `entries/services.py:244-257` — child queryset and 403
- `entries/views.py:706-749` — child context, list and detail views
- `family_notes/settings.py:211,288-290` — template dirs, login and logout redirects

## Architecture Insights

- The contract has both halves: semantic `--fn-*` tokens mapped onto Pico, and
  repo-local partials with `.fn-*` classes. Component classes live in the same file as the
  token values. That is workable at this size, but `tokens.css` is both the value source
  and the component stylesheet.
- Only the light theme is defined (`tokens.css:36-39`, `base.html:2`). Dark mode is out of
  scope.
- The repo has no screenshot-test tool. Playwright is not installed in the uv
  environment, and Chromium is on PATH. Earlier changes used a manual 360px screenshot of
  the kitchen sink as the visual gate.

## Historical Context (from prior changes)

- `context/archive/2026-09-28-child-assigned-entry-view/plan.md:39` — "No new CSS
  framework or JavaScript. Styling uses the existing Pico + `tokens.css` contract." Still
  holds.
- Same plan, line 77 — new layout classes must use existing tokens only, with no new
  colour or spacing values. Supported by the current `tokens.css:270-283`.
- Same plan, line 137 — the mode switch had to mark the current mode with `aria-current`.
  It does (`_child_list_body.html:8-9`). The plan did not require it to share a component
  with the parent tabs, which landed separately in
  `context/archive/2026-09-28-parent-family-entry-management/`. That is where C3 comes from.
- Same plan, line 237 — the 403 for a parent was a tested requirement. Its *presentation*
  was never specified (C2).
- Same plan, lines 196 and 303 — the 360px gallery screenshot was the gate, confirmed by
  the user on 2026-09-28. The view templates have not changed since then (last commit
  touching them is `e23392c`), so that screenshot still shows the current state.
- `context/archive/2026-09-27-first-school-event-capture/` introduced Pico + tokens and the
  kitchen-sink pattern (`tokens.css:2-7` records the value sources).

## Related Research

- Not applicable. No earlier `research.md` covers this view's UI.

## Open Questions

1. **C1 scope.** Restyling `/` is a separate view, which `/10x-ui` treats as its own
   change. The fix that stays inside this change is the entry point: route the brand link
   (or `/` for a signed-in user) to a role-based destination, so a child lands on
   `/entries/mine/`. Should `/` become that redirect, or should the brand link point
   at `/account/`?
2. **C2 scope.** `403.html` and `404.html` are global templates and also affect parent
   routes. Is a single Polish error template extending `base.html` acceptable inside this
   change?
3. **C5 grouping.** Should the list group dated entries by day, with a heading such as
   "Dziś" / "Jutro" / weekday, or should the row instead lead with the date? This
   changes `_entry_row.html`, which the parent list shares.
4. **Focus token value.** C4 needs a new `--fn-color-focus` (or an opaque accent ring) at
   3:1 or more against `--fn-color-surface` and `--fn-color-bg`. The value is not chosen
   yet. The accent itself (5.91:1) would pass.
