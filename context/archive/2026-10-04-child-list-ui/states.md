# 7-state matrix: child list (`/entries/mine/`)

Each `/10x-ui` state cell is either shown (with the evidence that shows it) or
N/A with a reason. Gallery = DEBUG-only `/entries/mine/_states/`, rendered with
`STATES_DATE` (Monday 2026-10-05) as "today" and unsaved synthetic entries.

| State | Status | Evidence |
|---|---|---|
| default | Shown | Gallery states `upcoming` (Dziś, Jutro, Czwartek, Poniedziałek, 26 października, Bez daty) and `past` (Wczoraj, Piątek, Środa, Sobota, 5 września), plus `detail_manual` and `detail_eduvulcan`: `screenshots/child-states-360.png`, `screenshots/child-states-1280.png` |
| hover | Shown (manual) | Hovering a row changes `.fn-entry-row` border to `--fn-color-accent` (`family_notes/static/css/tokens.css`). Hover cannot be captured in a static screenshot; check by hand (plan 1.5) |
| focus-visible | Shown (manual) | Keyboard pass: Tab reaches each mode link (`.fn-tabs a:focus-visible`) and each row link (`.fn-entry-link:focus-visible`) and shows a 2px `--fn-color-focus` outline. `#2f6f5e` gives 5.91:1 on surface and 5.56:1 on bg, so it meets the ≥3:1 non-text contrast rule. Manual check: plan 1.4 |
| disabled | N/A | The view has no form controls, only links, so nothing can be disabled |
| error | Shown | Gallery state `error_forbidden` (`_error.html` with the 403 copy, last section of both gallery screenshots); live 403 for a parent on `/entries/mine/`: `screenshots/error-403-360.png`; live 404 for a foreign or missing entry ID is covered by the error tests (plan 4.3) and manual step 5 |
| empty | Shown | Gallery states `upcoming_empty` and `past_empty` (`.fn-empty`) in both gallery screenshots |
| loading | N/A | The view is fully server-rendered with no client fetch, so there is no loading state |

Related entry point: sign-in page `screenshots/login-360.png` and
`screenshots/login-1280.png`.
