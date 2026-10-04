# Child List UI — Plan Brief

> Full plan: `context/changes/child-list-ui/plan.md`
> Research: `context/changes/child-list-ui/research.md`

## What & Why

The child list `/entries/mine/` already renders from tokens; there are no literal colours. But it is hard to reach, hard to use from the keyboard, and hard to scan:
- `/` is an English placeholder, and the sign-in page is bare allauth HTML.
- Wrong-role and stale links show Django's English error pages.
- Row focus and hover are invisible.
- The list switch duplicates the parent's tabs.
- Every row carries the same weight, so "what's tomorrow" means reading each card's small grey date.

## Starting Point

Pico v2.1.1 plus `family_notes/static/css/tokens.css` (semantic `--fn-*` tokens and `.fn-*` classes, light theme) and shared Django partials in `entries/templates/entries/`. The DEBUG-only kitchen sink `/entries/mine/_states/` renders 6 states. No agent rules file mentions UI.

## Desired End State

- `/` and login send a child to their list, a parent to the family list, and an anonymous user to a styled Polish sign-in page.
- Errors look like the app and offer a way back.
- On the child list, each day gets a heading ("Dziś", "Jutro", a weekday or the full date), and rows show only times.
- Rows show a visible hover and focus state, and both lists share one tab switch and one empty state.
- A rule in `AGENTS.md` and a hook check keep the next agent on the contract.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
| --- | --- | --- | --- |
| Contract variant | Extend existing Pico + `tokens.css` | An existing system beats a new one; no second palette. | Research |
| Signed-in landing | Child → `/entries/mine/`, parent → `/entries/`, no membership → `/account/` | Each role lands on its own list while the tested parent-403 rule stays. | Plan |
| Anonymous landing | `/` → sign-in page | User requirement. | Plan |
| Sign-in styling | Override allauth layout + custom `login.html`, Google first, password form kept | 2 templates style every allauth page without changing auth methods. | Plan |
| Error pages | Polish 403 + 404 (extend base) + self-contained 500 | No reachable page falls back to Django's English default. | Plan |
| Focus colour | `--fn-color-focus` = accent `#2f6f5e` (5.91:1 on surface) | The current 25 %-alpha ring is 1.43:1, below WCAG's 3:1. | Research / Plan |
| List switch & empty state | Shared `_list_modes.html` + `.fn-tabs` / `.fn-empty` for both lists | One component per job, so the next view copies the right one. | Plan |
| Day headings | Dziś / Jutro / Wczoraj, weekday for ±2–6 days, else full date (+year if different) | Matches how a child thinks about this week, with no ambiguous bare weekday further out. | Plan |
| Parent list rows | Unchanged | The heading change is scoped to the child view; the shared row gets an opt-in `hide_date`. | Plan |
| Visual gate | Gallery + headless-Chromium screenshots at 360/1280px, manual review | Same pattern as previous changes, with no new dependency. | Plan |
| Guard | `AGENTS.md` UI block + literal check in `scripts/hooks/quality_gate.py` for cleaned templates | A failing check is more reliable than a rule the agent forgot. | Plan |

## Scope

**In scope:**
- Focus/hover tokens
- The shared tab switch and empty state, used in both lists
- Child day headings
- `/` dispatcher and login redirect
- Anonymous header
- Allauth layout and login page
- 403/404/500 pages
- Gallery states and screenshots
- `states.md` matrix
- `AGENTS.md` rule and hook check

**Out of scope:**
- Access-rule changes
- Auth-method changes
- Dark mode and a type scale
- Parent list grouping
- Playwright
- 400/CSRF pages
- Capture and manage detail/edit pages

## Architecture / Approach

The work follows the `/10x-ui` order: token values → shared component → the one view → entry points and states. Role routing reuses `get_active_membership` / `is_parent`. Day headings come from a pure helper in `entries/listing.py`, with Polish names taken from Django's date formatting. Allauth pages inherit `base.html` through one layout override. Every visual phase re-runs the hardcoded-value scan and takes 360/1280 screenshots.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Tokens & interaction states | Visible focus ring and row hover; shared class names | The stronger Pico focus also changes the capture-form inputs |
| 2. Shared list components | One tab switch and one empty state in both lists | Manage gallery and test markers must survive the rename |
| 3. Child day headings | Dziś/Jutro/weekday/date groups; time-only rows | Date-dependent tests need a fixed `today` |
| 4. Entry points, sign-in, errors | Role redirects, styled Polish login, 403/404/500 | Allauth template blocks and the context-free 500 |
| 5. States, gate, guard | Gallery states, screenshots, `states.md`, `AGENTS.md` rule, hook check | Snap Chromium can't read `/tmp` or `/mnt/c` for screenshots |

**Prerequisites:** local `uv` env, seed family (`scripts/dev/seed_test_family.py`), Chromium on PATH.
**Estimated effort:** ~2–3 sessions across 5 phases.

## Open Risks & Assumptions

- Assumes allauth's `{% trans %}` strings resolve to Polish under `LANGUAGE_CODE='pl'`. Any that don't get Polish overrides in `login.html`.
- The focus colour change is global, so parent forms get the same stronger ring. That is intended, but it is visible outside the child view.
- The visual gate is manual review, not automated regression.

## Success Criteria (Summary)

- A child who opens the app lands on their list, sees today and tomorrow at a glance, and can tab through rows with a visible ring.
- No reachable page (sign-in, 403, 404, 500) shows bare HTML or English.
- The next agent finds the UI rule in `AGENTS.md`, and the hook rejects a literal colour in the cleaned templates.
