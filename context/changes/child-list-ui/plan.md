# Child List UI Implementation Plan

## Overview

Fix how users reach the child list `/entries/mine/`, how it responds to interaction, and how it reads, all on the existing Pico + `tokens.css` design system. A signed-in user lands on their role's own list. An anonymous user lands on a styled Polish sign-in page. Errors render inside the app layout. Row focus and hover become visible. The child's list switch and empty state share one component with the parent list. Dated entries are grouped under day headings ("Dziś", "Jutro", weekday, full date).

This is a `/10x-ui` change: one view (child list + its detail) plus global tokens, and the entry points that lead to it. The charges come from `research.md` (`## Charges`, C1–C5).

## Current State Analysis

- Contract variant: **existing design system**. Pico v2.1.1 (`family_notes/static/vendor/pico/pico.min.css`) plus semantic `--fn-*` tokens and `.fn-*` component classes in `family_notes/static/css/tokens.css`, light theme only, loaded by `family_notes/templates/base.html:7-8`. The hardcoded-value scan over the 5 child-view templates returns 0 hits (research, *View → source*).
- C1: `/` renders `family_notes/templates/family_notes/home.html`, a standalone English placeholder with literal colours (`home.html:11,12,29,35,50`). The brand link (`base.html:14`) and "Strona główna" (`account_status.html:24`) point there. Login redirects to `/account/` (`family_notes/settings.py:289`), and logout redirects to `/` (`settings.py:290`).
- C1 (sign-in): no allauth templates are overridden. `/accounts/login/` renders allauth 65.19's bare `allauth/layouts/base.html`, which has no Pico, no tokens and an English "Menu:" list. Password login is in use for local QA users (`scripts/dev/seed_test_family.py:4-9`), and Google is configured (`settings.py:394-403`).
- C1 (header): `base.html:17-25` shows "Konto" and "Wyloguj" with no `user.is_authenticated` check.
- C2: `child_entries` raises `PermissionDenied` for non-children (`entries/services.py:251-253`), and the detail view uses `get_object_or_404` (`entries/views.py:744`). No `403.html`, `404.html` or `500.html` exists in `family_notes/templates/` (template `DIRS`, `settings.py:211`), so Django's English defaults render.
- C3: the child mode switch is a Pico `role="group"` button pair (`entries/templates/entries/_child_list_body.html:6-11`). The parent's is `.fn-manage-tabs` (`entries/templates/entries/_manage_list.html:4-10`, `tokens.css:190-223`). The empty states are `.fn-panel` (`_child_list_body.html:20-22`) and `.fn-manage-empty` (`_manage_list.html:12`, `tokens.css:231-236`).
- C4: `.fn-entry-link` (`tokens.css:158-162`) overrides Pico's `:where(a)` hover variables, so hover changes nothing. Focus uses `--pico-primary-focus` = `--fn-color-accent-focus` = `rgba(47,111,94,0.25)` (`tokens.css:19,55`), which composites to `#cbdbd7` and gives 1.43:1 against `#ffffff`.
- C5: only the undated section has a heading (`_child_list_body.html:13`). Each row repeats the full date in small muted text (`entries/templates/entries/_entry_row.html:17-18`). `partition_entries` (`entries/listing.py`) returns `dated`/`undated` for upcoming and `past` for past, ordered by `effective_date`.
- Kitchen sink: `entries/templates/entries/child_states.html` (DEBUG only, 6 states, view `entries/views.py:770+`). Tests are in `entries/tests/test_child_states_view.py`.

## Desired End State

- `GET /` sends an anonymous user to `/accounts/login/`, an active child to `/entries/mine/`, an active parent to `/entries/`, and a signed-in user without an active membership to `/account/`. A successful login lands on the same role destination unless `?next=` says otherwise.
- `/accounts/login/` and every other allauth page render inside `base.html` with Pico and tokens. The login page has a Polish heading, a prominent Google button first, and allauth's existing password form below it (same auth options as today). An anonymous header shows only the brand.
- 403, 404 and 500 responses render a Polish page in the app's look with a way back to the user's home. 403 and 404 extend `base.html`. 500 is self-contained.
- On the child list, hovering a row visibly changes it. Keyboard focus on a row or on the list switch shows a ring of at least 3:1 contrast against `--fn-color-surface` and `--fn-color-bg`.
- The child and parent lists render the same `_list_modes.html` switch and the same `.fn-empty` empty state.
- The child list groups dated rows under headings. Upcoming uses "Dziś", "Jutro", the weekday for days 2–6, and otherwise "Poniedziałek, 12 października". Past uses "Wczoraj", the weekday for days 2–6 back, and otherwise the full date. A row under a heading shows only its time, if any. The parent list is unchanged apart from the shared switch and empty state.
- The kitchen sink shows the heading groups and an error state. Screenshots at 360px and 1280px are committed in the change folder. `AGENTS.md` carries a UI block. The quality-gate hook flags literal colours and inline styles in the cleaned templates.

Verify with: `uv run python manage.py test`, `uv run python manage.py check`, the hardcoded-value scan returning 0 on the cleaned templates, and a manual review of the screenshots plus a keyboard pass.

### Key Discoveries:

- `get_active_membership` and `is_parent` (`family_access/access.py:6-31`) already decide role. The `/` dispatcher reuses them, and `can_read_assigned_child` stays the only child gate (`entries/services.py:252`).
- Allauth's layout chain is `account/login.html` → `account/base_entrance.html` → `allauth/layouts/entrance.html` → `allauth/layouts/base.html`, using blocks `head_title`, `body`, `content`, `extra_body`. Overriding `allauth/layouts/base.html` in `family_notes/templates/` restyles all of them.
- The parent list's modes come from `_index_context` (`entries/views.py:446-454`, `'modes'` at line 450) with `LIST_MODE_LABELS` (`entries/views.py:397`). The child context (`entries/views.py:712-727`) has no `modes` key yet.
- Django renders `500.html` without a request context, so it cannot rely on `user` or context processors.
- The Django test runner runs with `DEBUG=False`, so `404.html`/`403.html` render in tests through the default handlers.

## What We're NOT Doing

- Opening `/entries/mine/` to parents or changing any access rule. The tested 403/404 matrix (`context/archive/2026-09-28-child-assigned-entry-view/plan.md:154-155`) stays as it is.
- Changing auth methods. The password form, signup and Google stay as allauth configures them; only the templates change.
- Restyling allauth pages other than through the shared layout and `login.html`. Logout confirm and social callback pages get our frame plus Pico defaults.
- Dark mode, a type-scale token, or new colours beyond the focus token.
- Changing the parent list's row layout or grouping (it keeps "Z datą" / "Bez daty" and dates on rows).
- Adding Playwright or any screenshot-test dependency. That belongs to Lesson 4.
- Overriding `400.html` or the CSRF failure page.
- Changing the parent capture flow or the manage detail/edit pages.

## Implementation Approach

The order follows the `/10x-ui` router: token values first, then the shared component, then the one view, then entry points and states. Each later phase builds on contract pieces that already exist. Every visual phase ends with a re-run of the hardcoded-value scan and screenshots at 360px and 1280px of the affected pages.

Hardcoded-value scan (Django templates and CSS; non-Tailwind variant), run on the cleaned templates listed in Phase 5:

```bash
grep -nE '#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(|oklch\(|style=|<style' <templates>
```

## Critical Implementation Details

- **Screenshots without a login script.** The gallery requires a signed-in user, and the Chromium on PATH is a snap that cannot read `/tmp` or `/mnt/c`. Either sign in with a seed user (`scripts/dev/seed_test_family.py`) in a real browser, or render the page HTML with Django's test `Client.force_login` into a file under `$HOME` with `<base href="http://127.0.0.1:8000/">`, while `runserver` serves static files, then run `chromium --headless --screenshot --window-size=360,…`. Copy the PNGs into `context/changes/child-list-ui/screenshots/`. The sign-in page needs no auth.
- **500 page.** Keep `500.html` free of `{% url %}` lookups that could fail and of `user`. Use `{% load static %}` for the two stylesheets and a plain `href="/"` back link.

## Phase 1: Tokens & Interaction States

### Overview

Close C4 at the token layer and prepare the shared class names that Phase 2 uses.

### Changes Required:

#### 1. Focus token and Pico mapping

**File**: `family_notes/static/css/tokens.css`

**Intent**: Add a focus colour that is visible against both surfaces, and route Pico's focus variables through it so links, the list switch and form controls share one ring. Record where the value comes from in the header comment.

**Contract**: New `--fn-color-focus` with at least 3:1 contrast against `--fn-color-surface` (`#ffffff`) and `--fn-color-bg` (`#f7f8fa`). The default is the accent `#2f6f5e`, which gives 5.91:1 and 5.56:1. `--pico-primary-focus` maps to `--fn-color-focus`. `--fn-color-accent-focus` stays only where a soft tint is wanted (`--pico-primary-underline`). Header comment line: "focus = accent, chosen for ≥3:1 non-text contrast (child-list-ui)".

#### 2. Row hover and focus-visible

**File**: `family_notes/static/css/tokens.css`

**Intent**: Make a whole row react to the pointer and show a clear keyboard ring, using tokens only.

**Contract**: `.fn-entry-row` gets a hover state, for example border colour `--fn-color-accent` (a token change, not only a shade). `.fn-entry-link:focus-visible` gets `outline: 2px solid var(--fn-color-focus)` with an offset, so the ring does not depend on Pico's `box-shadow`. No new literals in the file outside `:root`.

#### 3. Shared class names

**File**: `family_notes/static/css/tokens.css`

**Intent**: Rename the parent-only component classes to role-neutral names so both lists can use them (C3), and give tabs a visible focus ring.

**Contract**: `.fn-manage-tabs` becomes `.fn-tabs` (same rules, `tokens.css:189-223`), plus `.fn-tabs a:hover` and `.fn-tabs a:focus-visible` using `--fn-color-focus`. `.fn-manage-empty` becomes `.fn-empty` (`tokens.css:231-236`). Remove `.fn-child-modes` (`tokens.css:271-277`) once Phase 2 no longer uses it. Update `_manage_list.html:4,12` in the same phase so nothing breaks.

### Success Criteria:

#### Automated Verification:

- `uv run python manage.py test` passes
- `grep -rn "fn-manage-tabs\|fn-manage-empty" entries/ family_notes/ family_access/` returns nothing
- Hardcoded-value scan on the 5 child-view templates still returns 0 hits

#### Manual Verification:

- Tabbing through `/entries/mine/` shows a clearly visible ring on each row link and each mode link (360px and 1280px)
- Hovering a row visibly changes its border
- The parent list `/entries/` and capture form `/entries/new/` look unchanged apart from the stronger focus ring

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 2: Shared List Components

### Overview

Close C3: one switch partial and one empty-state markup for both lists.

### Changes Required:

#### 1. List-mode switch partial

**File**: `entries/templates/entries/_list_modes.html` (new), `entries/templates/entries/_manage_list.html`, `entries/templates/entries/_child_list_body.html`

**Intent**: Extract the parent's tab nav into a partial and use it in both lists. This replaces the child's Pico button group.

**Contract**: Parameters `modes` (list of `(key, label)`), `mode`, `url_name`. Renders `<nav class="fn-tabs" aria-label="Rodzaj listy">` with one link per mode, `?view=<key>` for non-default modes and `aria-current="page"` on the current one. Keeps `data-state-part="list-modes"` for the manage gallery tests.

#### 2. Child context carries modes

**File**: `entries/views.py`

**Intent**: Give the child list the same `modes` data the parent list has.

**Contract**: `_child_list_context` (`entries/views.py:712-727`) adds `'modes': [(key, LIST_MODE_LABELS[key]) for key in LIST_MODES]`. The child gallery passes it through as well.

#### 3. Shared empty state

**File**: `entries/templates/entries/_child_list_body.html`, `entries/templates/entries/_manage_list.html`

**Intent**: Both lists render "nothing here" the same way, distinct from the accent-ruled content panel.

**Contract**: `<p class="fn-empty fn-muted" data-empty-state="{{ mode }}">`. The child keeps `data-empty-state` for its tests, and the parent keeps `data-state-part="empty-{{ mode }}"`.

### Success Criteria:

#### Automated Verification:

- `uv run python manage.py test entries` passes, including the updated child-view assertions: no `role="group"`, `aria-current="page"` on the current mode, and `fn-empty` on both empty states
- `grep -n 'role="group"\|role="button"' entries/templates/entries/_child_list_body.html` returns nothing

#### Manual Verification:

- Child list, parent list and both galleries show the same tab switch and the same empty state at 360px and 1280px

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 3: Child Day Headings

### Overview

Close C5: group dated rows on the child list by day under relative headings.

### Changes Required:

#### 1. Day heading helper

**File**: `entries/listing.py`

**Intent**: A pure function that turns a date into the Polish heading for a given mode and `today`, and a grouper that splits an ordered entry list into consecutive day groups by `effective_date`. It stays family- and role-agnostic like the rest of the module.

**Contract**: `day_heading(day, today)` returns a capitalised Polish label. The rule uses `delta = (day - today).days`:
- `0` → "Dziś"; `1` → "Jutro"; `-1` → "Wczoraj"
- `2 ≤ |delta| ≤ 6` → the weekday name, for example "Środa"
- otherwise `"Poniedziałek, 12 października"` (weekday, day, month genitive), with the year added when it differs from `today.year`

`group_by_day(entries, today)` returns a list of `(heading, entries)` in the input order. Polish names come from Django's date formatting with `LANGUAGE_CODE = 'pl'` (`date_format(day, 'l, j E')`), not a hand-written table.

#### 2. Child context and template

**File**: `entries/views.py`, `entries/templates/entries/_child_list_body.html`

**Intent**: The child list renders one `<h2 class="fn-day-heading">` per day group, followed by its rows. "Bez daty" stays as the last section in upcoming.

**Contract**: `_child_list_context` turns the `dated` (upcoming) and `past` sections into day groups using `timezone.localdate()`. The template loops over groups. Each `<ul class="fn-entry-list">` keeps `data-entry-section`.

#### 3. Row without the date

**File**: `entries/templates/entries/_entry_row.html`, `family_notes/static/css/tokens.css`

**Intent**: Under a day heading, the row shows only the time, so the date is not repeated.

**Contract**: New optional parameter `hide_date`. When true, the meta line shows `HH:MM` if `entry.time` is set and is omitted otherwise. The parent list does not pass it, so its rows are unchanged. `.fn-day-heading` reuses the `.fn-child-section-title` rules (rename it), using tokens only.

### Success Criteria:

#### Automated Verification:

- Unit tests in `entries/tests/test_entry_listing.py` for `day_heading` with a fixed `today`: deltas 0, 1, −1, 2, 6, −6, 7, −7, and a date in another year
- Unit test that `group_by_day` keeps input order and groups an undated grade by its `effective_date`
- Child-view tests: upcoming shows "Dziś"/"Jutro" headings with a fixed `today` (`timezone.localdate` patched), past shows "Wczoraj", the parent list still shows full dates on rows
- `uv run python manage.py test` passes

#### Manual Verification:

- On a seeded family (`scripts/dev/seed_test_family.py`), the child list reads as days at 360px: headings stand out over rows, and rows show only times
- Past mode reads newest day first under "Wczoraj"/weekday/date headings

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 4: Entry Points, Sign-in and Error Pages

### Overview

Close C1 and C2: every way into the app lands somewhere styled, Polish and role-appropriate.

### Changes Required:

#### 1. Role-based root

**File**: `family_notes/views.py`, `family_notes/settings.py`, `family_notes/templates/family_notes/home.html` (delete), `family_notes/tests.py`

**Intent**: `/` becomes a redirect to the user's home, and login uses it too, so a signed-in child or parent never sees a placeholder.

**Contract**: `home` returns a redirect. Anonymous users go to `account_login`. Users with an active child membership go to `entries:child_list`. Parents (`is_parent`) go to `entries:index`. Everyone else goes to `account_status`. `LOGIN_REDIRECT_URL = '/'`. `LOGOUT_REDIRECT_URL` stays `/`, so after logout the user lands on the login page. Delete `home.html` and replace `RootRouteTests.test_root_renders_homepage` with the 4-case redirect matrix.

#### 2. Anonymous-aware header

**File**: `family_notes/templates/base.html`

**Intent**: Don't offer "Konto"/"Wyloguj" to someone who is not signed in.

**Contract**: The `{% block nav %}` content renders only when `user.is_authenticated`. The brand link stays and points to `home`.

#### 3. Allauth layout and login page

**File**: `family_notes/templates/allauth/layouts/base.html` (new), `family_notes/templates/account/login.html` (new)

**Intent**: Wrap every allauth page in our base layout. Give the login page a Polish heading and Google as the first, prominent action, while keeping allauth's other login options exactly as configured.

**Contract**: The layout extends `base.html`, maps `head_title` → `title`, renders `messages` in a `.fn-panel`, and exposes `content` and `extra_body`. It drops allauth's English "Menu:". `login.html` keeps allauth's context and conditions (`SOCIALACCOUNT_ENABLED`, `SOCIALACCOUNT_ONLY`, `LOGIN_BY_CODE_ENABLED`, `PASSKEY_LOGIN_ENABLED`, `redirect_field`). It renders "Zaloguj się" as `<h1>`, a "Zaloguj przez Google" button (`{% provider_login_url 'google' %}` with the redirect field preserved) first, and the password form below a divider. All copy is Polish; the allauth `{% trans %}` strings already resolve to Polish under `LANGUAGE_CODE='pl'`.

#### 4. Error pages

**File**: `family_notes/templates/403.html`, `family_notes/templates/404.html`, `family_notes/templates/500.html`, `family_notes/templates/_error.html` (new)

**Intent**: A stray link or a wrong-role URL shows a Polish page in the app's look with a way back, not Django's English default.

**Contract**: `_error.html` takes `heading` and `message` and renders them in a `.fn-panel--danger` with a "Wróć na stronę główną" link to `home`. 403 uses "Brak dostępu" / "Ta strona nie jest dostępna dla Twojego konta.". 404 uses "Nie znaleziono" / "Ta strona nie istnieje albo nie masz do niej dostępu." (identical for missing and foreign entries, which keeps the 404 indistinguishability rule). 403 and 404 extend `base.html`. `500.html` is a standalone document that loads both stylesheets via `{% static %}`, has a brand-only header and a plain `/` link, and uses no context variables.

### Success Criteria:

#### Automated Verification:

- Root redirect matrix test: anonymous → login, child → `/entries/mine/`, parent → `/entries/`, no membership → `/account/`
- Login test: `GET /accounts/login/` uses `account/login.html`, contains `css/tokens.css`, "Zaloguj się" and the Google provider URL, and does not contain "Wyloguj" or "Menu:"
- Error tests: parent `GET /entries/mine/` returns 403 with "Brak dostępu" and the base layout; a foreign-entry detail returns 404 with "Nie znaleziono", with identical bodies for foreign and missing IDs; `render_to_string('500.html')` succeeds with no context and contains `tokens.css`
- Existing access-matrix tests in `entries/tests/test_child_views.py` still pass unchanged
- `uv run python manage.py test` and `uv run python manage.py check` pass

#### Manual Verification:

- Signed out: `/` lands on a styled Polish sign-in page at 360px and 1280px, the Google button comes first, and the header shows only the brand
- Signing in as `test_kasia` lands on `/entries/mine/`, and as `test_rodzic` on `/entries/`
- As `test_rodzic`, typing `/entries/mine/` shows the Polish 403 page with a working way back

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 5: States, Visual Gate and Guard

### Overview

Show every state on one page, take the gate screenshots, and leave the rule and check that keep the next agent on the contract.

### Changes Required:

#### 1. Gallery states

**File**: `entries/views.py` (`child_states`), `entries/templates/entries/child_states.html`, `entries/tests/test_child_states_view.py`

**Intent**: Add the states this change introduced, so one screenshot shows them all.

**Contract**: The gallery uses a fixed `STATES_DATE` as "today" and renders day-heading upcoming (Dziś, Jutro, a weekday, a far date, Bez daty), day-heading past (Wczoraj, a weekday, a far date), both empty states, both details, and an error state (`_error.html` with the 403 copy). It still makes no `Entry` reads or writes. The `data-kitchen-state` markers are extended and tested.

#### 2. 7-state matrix

**File**: `context/changes/child-list-ui/states.md` (new)

**Intent**: Record each `/10x-ui` state cell as shown (with the screenshot or keyboard check that shows it) or N/A with a reason.

**Contract**: The 7 cells:
- **default**: gallery
- **hover**: manual, row border
- **focus-visible**: manual keyboard pass, ring ≥3:1
- **disabled**: N/A, the view has no form controls
- **error**: gallery error state plus the live 403/404
- **empty**: gallery, both modes
- **loading**: N/A, fully server-rendered with no client fetch

#### 3. Screenshots

**File**: `context/changes/child-list-ui/screenshots/` (new)

**Intent**: Visual gate evidence for review.

**Contract**: `child-states-360.png`, `child-states-1280.png`, `login-360.png`, `login-1280.png`, `error-403-360.png`. See Critical Implementation Details for how to take them.

#### 4. Agent rule

**File**: `AGENTS.md` (outside the `<!-- BEGIN @przeprogramowani/10x-cli -->` block, before line 37)

**Intent**: Tell the next agent where the contract lives.

**Contract**: A short `## UI Conventions` section:
- tokens and component classes live in `family_notes/static/css/tokens.css` on top of Pico
- check `entries/templates/entries/_*.html` and `family_notes/templates/_error.html` before creating markup, and add new shared classes to `tokens.css` using existing tokens
- no literal colours, inline `style=` or `<style>` blocks in templates
- every Django error page extends the base layout
- kitchen sinks are at `/entries/_states/` and `/entries/mine/_states/`
- all user-facing copy is in Polish

#### 5. Literal check in the quality gate

**File**: `scripts/hooks/quality_gate.py`, `scripts/hooks/README.md`

**Intent**: A failing check is more reliable than a rule the agent forgot. Flag literals in the templates this change cleaned, at edit time and at end of turn.

**Contract**: A `literal_errors(paths, base)` function, called in `edit` mode on the edited paths and in `stop` mode on the changed paths, the same way `syntax_errors` is. It reports `path:line` for matches of `#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(|oklch\(|style=|<style` only in this allowlist:
- `family_notes/templates/base.html`
- `family_notes/templates/40[34].html`
- `family_notes/templates/500.html`
- `family_notes/templates/_error.html`
- `family_notes/templates/allauth/layouts/base.html`
- `family_notes/templates/account/login.html`
- `entries/templates/entries/{child_list,child_detail,child_states,_child_list_body,_child_entry_detail,_entry_row,_list_modes}.html`

`tokens.css` is never scanned. The feedback channel (stderr + exit 2) is unchanged. Proved with a sample payload on a deliberately broken template and a clean one, then reverted.

### Success Criteria:

#### Automated Verification:

- `uv run python manage.py test entries.tests.test_child_states_view` passes with the new state markers and zero `Entry` queries
- Hardcoded-value scan over the allowlisted templates returns 0 hits
- `echo '{"tool_name":"Edit","tool_input":{"file_path":"entries/templates/entries/_entry_row.html"}}' | python3 scripts/hooks/quality_gate.py edit` exits 2 when a literal `#ff0000` is temporarily added to that file and exits 0 after reverting it
- `uv run python manage.py test`, `uv run python manage.py check` and `uv run python manage.py makemigrations --check --dry-run` pass

#### Manual Verification:

- Gallery screenshots at 360px and 1280px show all states legibly, with no horizontal scroll, Polish copy and token colours only
- Login and 403 screenshots match the app's look
- The `states.md` matrix has every cell shown or N/A with a reason
- The `AGENTS.md` UI block is readable and sits outside the 10x-cli block

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to `/10x-impl-review`.

---

## Testing Strategy

### Unit Tests:

- `day_heading` boundary deltas (0, ±1, ±2, ±6, ±7) and the year rule, with a fixed `today`
- `group_by_day` order and the undated-grade `effective_date` case
- `500.html` renders with no context

### Integration Tests:

- Root redirect matrix (anonymous, child, parent, no membership) and post-login landing
- Login page template, layout and Google URL
- 403/404 bodies and layout, plus 404 body equality for foreign vs missing IDs
- Child list headings with patched `timezone.localdate`; parent list rows unchanged
- Child gallery markers and zero `Entry` queries

### Manual Testing Steps:

1. Signed out, open `/` at 360px: you should land on the styled login page with Google first.
2. Sign in as `test_kasia`: you should land on `/entries/mine/` with day headings, and tabbing should show a visible ring on each row and tab.
3. Switch to "Minione": you should see "Wczoraj"/weekday headings.
4. Sign in as `test_rodzic`: you should land on `/entries/`. Open `/entries/mine/`: you should see the Polish 403 page.
5. Open `/entries/mine/999999/` as a child: you should see the Polish 404 page.
6. Review the gallery screenshots at 360px and 1280px.

## Performance Considerations

Grouping is done in Python over the already-evaluated section lists. There are no extra queries; the child list query count stays the same.

## Migration Notes

No data migrations. Deleting `family_notes/home.html` and changing `LOGIN_REDIRECT_URL` are deploy-safe. Existing sessions simply land on the new `/` redirect.

## References

- Research and charges: `context/changes/child-list-ui/research.md`
- Child view origin: `context/archive/2026-09-28-child-assigned-entry-view/plan.md`
- Parent tabs origin: `context/archive/2026-09-28-parent-family-entry-management/`
- Kitchen-sink pattern: `context/archive/2026-09-27-first-school-event-capture/plan.md`
- Polish copy rule: `context/foundation/lessons.md:16`
- Merge checklist: `.claude/skills/10x-ui/references/ui-quality-checklist.md`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Tokens & Interaction States

#### Automated

- [x] 1.1 `uv run python manage.py test` passes — aef2600
- [x] 1.2 `grep -rn "fn-manage-tabs\|fn-manage-empty" entries/ family_notes/ family_access/` returns nothing — aef2600
- [x] 1.3 Hardcoded-value scan on the 5 child-view templates still returns 0 hits — aef2600

#### Manual

- [ ] 1.4 Tabbing through `/entries/mine/` shows a clearly visible ring on each row link and each mode link (360px and 1280px)
- [ ] 1.5 Hovering a row visibly changes its border
- [ ] 1.6 The parent list `/entries/` and capture form `/entries/new/` look unchanged apart from the stronger focus ring

### Phase 2: Shared List Components

#### Automated

- [x] 2.1 `uv run python manage.py test entries` passes, including the updated child-view assertions: no `role="group"`, `aria-current="page"` on the current mode, and `fn-empty` on both empty states — 1528c6f
- [x] 2.2 `grep -n 'role="group"\|role="button"' entries/templates/entries/_child_list_body.html` returns nothing — 1528c6f

#### Manual

- [ ] 2.3 Child list, parent list and both galleries show the same tab switch and the same empty state at 360px and 1280px

### Phase 3: Child Day Headings

#### Automated

- [x] 3.1 Unit tests in `entries/tests/test_entry_listing.py` for `day_heading` with a fixed `today`: deltas 0, 1, −1, 2, 6, −6, 7, −7, and a date in another year
- [x] 3.2 Unit test that `group_by_day` keeps input order and groups an undated grade by its `effective_date`
- [x] 3.3 Child-view tests: upcoming shows "Dziś"/"Jutro" headings with a fixed `today` (`timezone.localdate` patched), past shows "Wczoraj", the parent list still shows full dates on rows
- [x] 3.4 `uv run python manage.py test` passes

#### Manual

- [ ] 3.5 On a seeded family (`scripts/dev/seed_test_family.py`), the child list reads as days at 360px: headings stand out over rows, and rows show only times
- [ ] 3.6 Past mode reads newest day first under "Wczoraj"/weekday/date headings

### Phase 4: Entry Points, Sign-in and Error Pages

#### Automated

- [ ] 4.1 Root redirect matrix test: anonymous → login, child → `/entries/mine/`, parent → `/entries/`, no membership → `/account/`
- [ ] 4.2 Login test: `GET /accounts/login/` uses `account/login.html`, contains `css/tokens.css`, "Zaloguj się" and the Google provider URL, and does not contain "Wyloguj" or "Menu:"
- [ ] 4.3 Error tests: parent `GET /entries/mine/` returns 403 with "Brak dostępu" and the base layout; a foreign-entry detail returns 404 with "Nie znaleziono", with identical bodies for foreign and missing IDs; `render_to_string('500.html')` succeeds with no context and contains `tokens.css`
- [ ] 4.4 Existing access-matrix tests in `entries/tests/test_child_views.py` still pass unchanged
- [ ] 4.5 `uv run python manage.py test` and `uv run python manage.py check` pass

#### Manual

- [ ] 4.6 Signed out: `/` lands on a styled Polish sign-in page at 360px and 1280px, the Google button comes first, and the header shows only the brand
- [ ] 4.7 Signing in as `test_kasia` lands on `/entries/mine/`, and as `test_rodzic` on `/entries/`
- [ ] 4.8 As `test_rodzic`, typing `/entries/mine/` shows the Polish 403 page with a working way back

### Phase 5: States, Visual Gate and Guard

#### Automated

- [ ] 5.1 `uv run python manage.py test entries.tests.test_child_states_view` passes with the new state markers and zero `Entry` queries
- [ ] 5.2 Hardcoded-value scan over the allowlisted templates returns 0 hits
- [ ] 5.3 `echo '{"tool_name":"Edit","tool_input":{"file_path":"entries/templates/entries/_entry_row.html"}}' | python3 scripts/hooks/quality_gate.py edit` exits 2 when a literal `#ff0000` is temporarily added to that file and exits 0 after reverting it
- [ ] 5.4 `uv run python manage.py test`, `uv run python manage.py check` and `uv run python manage.py makemigrations --check --dry-run` pass

#### Manual

- [ ] 5.5 Gallery screenshots at 360px and 1280px show all states legibly, with no horizontal scroll, Polish copy and token colours only
- [ ] 5.6 Login and 403 screenshots match the app's look
- [ ] 5.7 The `states.md` matrix has every cell shown or N/A with a reason
- [ ] 5.8 The `AGENTS.md` UI block is readable and sits outside the 10x-cli block
