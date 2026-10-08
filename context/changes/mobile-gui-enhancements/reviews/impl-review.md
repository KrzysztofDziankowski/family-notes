<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Mobile GUI Enhancements Implementation Plan

- **Plan**: context/changes/mobile-gui-enhancements/plan.md
- **Scope**: Full plan
- **Reviewed phases**: 1, 2, 3, 4
- **Date**: 2026-10-08
- **Verdict**: NEEDS ATTENTION
- **Findings**: 0 critical, 2 warnings, 4 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | PASS |
| Scope Discipline | PASS |
| Safety & Quality | WARNING |
| Architecture | PASS |
| Pattern Consistency | PASS |
| Success Criteria | PASS |

Success criteria: `uv run python manage.py test` (1535 tests OK, 15 skipped), `check` (no issues) and `makemigrations --check --dry-run` (no changes) pass on HEAD. The manual rows are backed by `verification.md`, which states that no physical Android PWA or real screen reader was used.

Scope: the landscape-only container widening in `tokens.css` was not in the plan. It was found during manual check 2.3, is documented in `verification.md` and committed separately (`c148c52`). It stays within the plan's intent ("no horizontal document scrolling", compact cells).

## Findings

### F1 — Resume with an unreachable server swaps the list for the offline page

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Safety & Quality
- **Location**: family_notes/static/js/list-refresh.js:22-28
- **Detail**: The only offline check is `navigator.onLine`. It is `true` whenever a network interface is up: just after a phone wakes, on captive-portal Wi-Fi, or with the server down. In those cases `location.reload()` goes through the service worker, which serves the precached offline page at the list URL. The visible list is lost, which contradicts the plan ("Resuming offline preserves visible content"). There is no reload loop, because the offline page does not load the script.
- **Fix A ⭐ Recommended**: Before reloading, send a `HEAD` probe to `/healthz/` with `cache: 'no-store'`. Reload only when it answers `ok`; otherwise keep the page and mark the refresh pending.
  - Strength: Keeps the list exactly when the reload would fail. The service worker returns early for non-GET requests, so the probe always reaches the network.
  - Tradeoff: Adds one tiny request per resume. It carries no family data, and the list GET stays at one.
  - Confidence: HIGH — `/healthz/` already exists, is anonymous and checks the database.
  - Blind spot: A server that dies between the probe and the reload still shows the offline page. The window is very short.
- **Fix B**: Accept the risk and document it in the plan and the script header.
  - Strength: No code change.
  - Tradeoff: Loses content on flaky resumes, which are common on phones.
  - Confidence: MED — depends on how often the user resumes on bad networks.
  - Blind spot: None significant.
- **Decision**: FIXED via Fix A

### F2 — Every tab or app switch reloads, however brief

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Safety & Quality
- **Location**: family_notes/static/js/list-refresh.js:32-39
- **Detail**: `visibilitychange` fires on every desktop tab switch, screen lock, share sheet or picker. Each return does a full reload, which resets screen-reader and keyboard focus to the top and drops a just-shown flash message ("Zapisano"). A page first loaded while hidden (a background tab, prerender) also reloads on its first show, even though its content is seconds old (reviewer note O1).
- **Fix**: Reload only after the page has been hidden for at least 30 seconds, measured with `Date.now()` from the hidden or `pagehide` moment. A pending offline refresh ignores the threshold.
  - Strength: A quick glance at another app keeps focus and messages. A real return to the app, after 30 seconds or more, still refreshes. This also resolves O1.
  - Tradeoff: Data changed elsewhere during a switch shorter than 30 seconds appears only on the next resume or navigation.
  - Confidence: MED — 30 seconds is a judgement call, not a measured value.
  - Blind spot: No real-device usage data on typical switch lengths.
- **Decision**: FIXED

### F3 — The landscape query also matches zoomed or short desktop windows

- **Severity**: 💡 OBSERVATION
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Safety & Quality
- **Location**: family_notes/static/css/tokens.css:471, :500
- **Detail**: In a media query, `rem` means 16px, so the second condition matches any landscape viewport that is at least 576px wide and at most 512px tall. That includes a desktop at 200% zoom (640×360), a short window, or DevTools docked at the bottom. Those viewports now get seven narrow columns where they previously had one. There is no horizontal scroll, so SC 1.4.10 holds.
- **Fix**: Add `and (pointer: coarse)` to pin the rule to touch phones.
  - Strength: Zoomed desktop users keep the single column.
  - Tradeoff: Changes the reviewed contract, which the plan review (F4) settled as a width floor plus a height cap. It would also exclude touch phones used with a mouse or stylus.
  - Confidence: MED.
  - Blind spot: Desktop use at 200% zoom has not been measured.
- **Decision**: ACCEPTED — the plan-reviewed contract stands, and there is no WCAG failure. Revisit if low-vision desktop users report it.

### F4 — Stale aria-label example in the parent calendar partial

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Adherence
- **Location**: entries/templates/entries/_manage_list.html:8
- **Detail**: The comment still shows the old label "Jutro, 8 października, Kasia".
- **Fix**: Update the example to "Jutro, czwartek 8 października, Kasia".
- **Decision**: FIXED

### F5 — `day_heading` builds a pattern it may never use

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: entries/listing.py:151-165
- **Detail**: `pattern` is computed even when the relative branch returns, and the `delta not in RELATIVE_DAY_HEADINGS` guard repeats work the `or` fallback already does. The behaviour is correct and tested. Reviewer note O5 (the view takes the day key from `rows[0]` instead of from `group_by_day`) is correct and costs no queries; it is left as is.
- **Fix**: Return early on a relative day, then choose the non-relative pattern.
- **Decision**: FIXED

### F6 — `family_notes/test_accessibility.py` is listed in Phase 4 but untouched

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Success Criteria
- **Location**: N/A
- **Detail**: The plan names this file, but the diff does not change it. Its existing audit of `entries:child_list` already runs the unique-id and id-reference checks that cover the new `aria-labelledby`. The relationship itself is asserted in `entries/tests/test_child_views.py` and `test_child_states_view.py`.
- **Fix**: None needed; the coverage exists elsewhere.
- **Decision**: ACCEPTED — covered by the existing generic audit plus targeted entries tests.
