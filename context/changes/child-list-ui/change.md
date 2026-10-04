---
change_id: child-list-ui
title: Child list UI
status: implemented
created: 2026-10-04
updated: 2026-10-04
archived_at: null
---

## Notes

UI change run through `/10x-ui`.

- **View (one):** child list `/entries/mine/` (`entries/templates/entries/child_list.html`, `_child_list_body.html`, shared `_entry_row.html`), with its drill-down `child_detail` (`_child_entry_detail.html`).
- **Token source:** `family_notes/static/css/tokens.css` — semantic `--fn-*` tokens mapped onto Pico (`family_notes/static/vendor/pico/pico.min.css`); shared component classes `.fn-*` live in the same file, shared partials in `entries/templates/entries/_*.html`.
- **Contract variant:** existing design system (Pico + `tokens.css`, light theme only). Extend it; no second palette or library.
- **Kitchen sink:** `entries/templates/entries/child_states.html` at `/entries/mine/_states/` (DEBUG only).
- **Pre-audit (2026-10-04):** hardcoded-value scan on the view files = 0 hits. Agent rules files (`AGENTS.md`, `CLAUDE.md`) have no UI block. Candidate charges for research: non-child user on `/entries/mine/` gets a bare Django 403 (no custom 403/404 template); no home-page entry to the child list; mode switch uses Pico `role="button"` group while the parent list uses `.fn-manage-tabs`; no date grouping/hierarchy for dated rows; focus/hover of `.fn-entry-link` undefined; no loading state.
