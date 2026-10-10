<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Child List UI

- **Plan**: context/changes/child-list-ui/plan.md
- **Scope**: Full plan
- **Reviewed phases**: 1, 2, 3, 4, 5
- **Date**: 2026-10-04
- **Verdict**: NEEDS ATTENTION
- **Findings**: 0 critical, 3 warnings, 6 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | WARNING |
| Scope Discipline | PASS |
| Safety & Quality | PASS |
| Architecture | PASS |
| Pattern Consistency | WARNING |
| Success Criteria | PASS |

Success criteria: all automated rows (1.1–5.4) passed at their phase gates, including deliberate-break checks. The final full suite ran 700 tests, OK (4 skipped), with `check` and `makemigrations --check` clean and the hook proof exiting 2 then 0. All 13 manual rows (1.4–1.6, 2.3, 3.5–3.6, 4.6–4.8, 5.5–5.8) are still pending and left for the user. None were rubber-stamped.

Safety checks that passed: GET `/accounts/logout/` only shows the confirm page (`ACCOUNT_LOGOUT_ON_GET` defaults to False). Off-site `?next=` values are rejected by allauth. The 404 bodies for foreign and missing IDs are byte-identical. The `/` redirect adds no authorization path. `500.html` renders with an empty context. Every allauth page renders in Polish inside the layout, and day grouping adds no queries.

## Findings

### F1 — 404 nav swaps POST logout for a GET link (undocumented drift)

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Plan Adherence
- **Location**: family_notes/templates/404.html:10-13
- **Detail**: The plan says 404 extends `base.html`, and nothing more. The implementation overrides `{% block nav %}` so that "Wyloguj" links (GET) to allauth's logout confirmation page instead of submitting the POST form. The reason is that the CSRF token in the form is re-masked on every response, which made the foreign-entry and missing-entry 404 bodies differ and broke the unchanged test `test_excluded_and_missing_ids_return_identical_404`. The approach is safe, because GET does not log out. The cost is one extra click on 404 pages only, and the decision is recorded only in a template comment.
- **Fix A ⭐ Recommended**: Keep the override and add a note to the plan or `change.md`.
  - Strength: Keeps the 404 indistinguishability rule and its existing test exactly as they are, with no security cost (verified).
  - Tradeoff: Logout behaves differently on 404 pages than everywhere else (an extra confirm step).
  - Confidence: HIGH — the behaviour was verified against allauth 65.19.4 defaults.
  - Blind spot: None significant.
- **Fix B**: Compare 404 bodies in the test with the CSRF token value masked, and drop the nav override.
  - Strength: Gives the same logout UX on every page.
  - Tradeoff: Changes an existing access-matrix test, which the plan said must stay unchanged, and weakens "byte-identical" to "identical modulo token".
  - Confidence: MED — the unmasked secret is the same per session, so the leak risk is nil, but it relaxes a guarded test.
  - Blind spot: Whether anything else depends on byte-identical bodies.
- **Decision**: FIXED via Fix A — the intentional 404 logout behavior is documented in `change.md`.

### F2 — Login hard-codes Google instead of allauth's provider list

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Adherence
- **Location**: family_notes/templates/account/login.html:13-17
- **Detail**: The plan says the page keeps "allauth's other login options exactly as configured". The generic `socialaccount/snippets/login.html` provider list was replaced by a single `{% provider_login_url 'google' %}` button. Google is the only provider today, so nothing is lost now, but a provider added later would be silently hidden.
- **Fix**: Keep it. Add a one-line comment in `login.html` (and optionally in `change.md`) saying that any new provider must be added here.
- **Decision**: FIXED — the Google-only product decision is documented beside the explicit provider button; future providers must be added and reviewed there.

### F3 — Empty meta paragraph on untimed child rows

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: entries/templates/entries/_entry_row.html:19-23
- **Detail**: The plan says the meta line is "omitted otherwise" when `hide_date` is set and there is no time. The child list sets `hide_date` and `hide_assignee` and has no edit link, so an untimed row renders an empty `<p class="fn-entry-meta fn-muted">`. That adds vertical spacing with no content.
- **Fix**: Wrap the `<p>` in a condition so it renders only when it has a time, a date, an assignee or an edit link.
- **Decision**: FIXED — the row now omits the meta paragraph when every meta value is hidden or absent, with a regression assertion in `test_manage_views.py`.

### F4 — Flash messages not rendered on child/account pages

- **Severity**: 💡 OBSERVATION
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Safety & Quality
- **Location**: family_notes/templates/base.html:32
- **Detail**: The new `{% block messages %}` is empty by default, and only the allauth layout fills it. After a child logs in through the new `/` redirect, allauth's "Zalogowano jako …" message is not shown on `/entries/mine/`. It shows up later on the next allauth page; after logout it appears next to "Wylogowano". This predates the change, but the change makes `/` → child list the main flow.
- **Fix**: Render messages by default in base.html's `messages` block (`.fn-panel`), and override the block to empty on manage pages, which already render `_manage_messages.html` themselves.
  - Strength: Login and logout feedback appears where the user lands.
  - Tradeoff: Touches every page that extends base, so check for double rendering on manage pages.
  - Confidence: MED — the manage pages' own message rendering needs checking.
  - Blind spot: Other pages that render messages inline.
- **Decision**: FIXED — later shared-layout work renders messages by default and management pages override the block to avoid duplicates.

### F5 — AGENTS.md rule is broader than the gate and the error pages

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: AGENTS.md:39-40; scripts/hooks/quality_gate.py:59-72
- **Detail**: AGENTS.md bans literal colours and `style=` in all templates, but the hook scans only the 14 allowlisted files, so `_manage_list.html`, `manage_*.html` and `account_status.html` are not checked. "Every Django error page extends the base layout" also does not cover `403_csrf.html` or `400.html`, which still render Django's English defaults. The plan explicitly left 400 and CSRF out of scope.
- **Fix**: Reword both bullets to match reality: "cleaned templates (see LITERAL_TEMPLATES)" and "403/404/500 pages".
- **Decision**: FIXED — the current AGENTS.md wording names cleaned templates and limits the error-page rule to 403/404/500.

### F6 — Literal regex false-positives on hex-like anchors

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: scripts/hooks/quality_gate.py:72
- **Detail**: `#[0-9a-fA-F]{3,8}\b` matches anchors such as `href="#add"`, `#fade` and `#feed` (confirmed for `#add`). It also flags `style=` inside `{# #}` comments. The plan specified this regex, so this is a plan-level gap.
- **Fix**: Add a negative lookbehind so the pattern does not match after `href="` (or require a CSS-value context).
- **Decision**: FIXED — the hook ignores hex-like `href` fragments and Django one-line comments while retaining literal colour checks.

### F7 — Parent list includes the switch partial without `only`

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: entries/templates/entries/_manage_list.html:4
- **Detail**: Every other partial include in this change uses `with … only`. This one passes the whole context into `_list_modes.html`.
- **Fix**: `{% include "entries/_list_modes.html" with modes=modes mode=mode url_name="entries:index" only %}`.
- **Decision**: FIXED — the include now passes `modes`, `mode` and `url_name` explicitly with `only`.

### F8 — Solid focus ring now applies app-wide

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: family_notes/static/css/tokens.css:58
- **Detail**: `--pico-primary-focus` changed from the 25% tint to solid accent, so every Pico button and input (capture and manage forms included) now shows a strong focus ring. This is intended, but it is a global visual change.
- **Fix**: No code change. Cover it in manual check 1.6 (parent list and `/entries/new/`).
- **Decision**: ACCEPTED — the stronger app-wide focus ring is intentional and the completed manual accessibility passes cover the shared controls.

### F9 — 403 copy duplicated; signup link still advertised

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: entries/views.py:854-855, family_notes/templates/403.html:6, family_notes/templates/account/login.html:43
- **Detail**: The gallery error state repeats the 403 strings that 403.html hardcodes, so changing one copy does not change the other. Separately, login keeps allauth's "zarejestruj się" link. Open signup predates this change and has no adapter restriction, but the new page makes it more visible.
- **Fix**: Make 403.html pass its heading and message to `_error.html` from the same constants the gallery uses. Decide separately whether self-signup is part of the product, and track that as its own item, not in this change.
- **Decision**: ACCEPTED — signup was closed by the dedicated `remove-sign-up-option` change and is regression-tested; the stable 403 copy remains duplicated only between the real error page and DEBUG gallery fixture.

## Triage completion — 2026-10-10

All nine findings were rechecked against the current tree. Seven are fixed,
including four resolved by later shared UI/authentication work; two low-risk
observations are accepted as documented above. Focused template, authentication,
hook and Django verification passed before archive.
