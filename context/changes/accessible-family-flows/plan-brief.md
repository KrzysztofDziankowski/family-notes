# Accessible Family Flows — Plan Brief

> Full plan: `context/changes/accessible-family-flows/plan.md`

## What & Why

PK-17 asks for explicit accessibility targets beyond default browser behaviour. This slice adopts WCAG 2.2 AA for the core family flows, fixes the concrete gaps found in the templates and tokens, and makes the target enforceable through automated checks in the Django suite and a recorded manual pass with assistive technology.

## Starting Point

The server-rendered Polish UI (Django + Pico + `tokens.css`) already has `lang="pl"`, landmarks, labelled fields, alert and status panels, and AA text contrast. The audit found these gaps:

- Dangling and duplicated error IDs (`_field.html` uses `-error`, but Django 5.2 references `_error`).
- Hint and error collisions on the review form.
- Near-invisible focus rings on Pico secondary buttons.
- Input borders at about 1.4:1.
- No skip link.
- An error summary that is not linked to the fields.
- No page-level accessibility tests at all.

## Desired End State

Every covered page (sign-in, capture → review → confirm including S-03 correction, S-04 batch and S-06 progress states, follow-up, parent list/detail/create/edit/delete, child list/detail, account status, S-06 `/offline/`, 403/404/500) passes a structural accessibility audit and a token-contrast test in `uv run python manage.py test`. Keyboard and screen-reader users can complete each flow, with recorded evidence. `context/foundation/accessibility.md` tells later slices what they must keep.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
| --- | --- | --- | --- |
| Accessibility standard | WCAG 2.2 Level AA | Current legal and industry baseline; the tokens already aim at AA contrast. | Owner |
| Covered flows | All product pages a family member reaches, incl. S-03/S-04 review states, S-06 progress states and `/offline/`, S-05 Enter-to-submit, and a manifest no-orientation-lock check; excludes admin, allauth secondary pages and DEBUG galleries | Matches the PRD's family flows (as extended by M-2 slices) without expanding into operator UI. | Assumed (owner to confirm) |
| Automated tooling | Django test-client HTML audit (stdlib parser) + token-contrast unit test; axe only manually | No Node or Playwright stack exists; no E2E in this slice is owner-confirmed 2026-10-04. | Owner |
| Live-region audit rule | `role=status/alert` needs visible text, unless it is an `aria-live` + `data-live-region` script-updated region with ≥1 hidden text state block | Supports S-06's reliable live-region pattern and still flags empty static panels. | Research |
| AT matrix | Keyboard/Chrome, NVDA/Firefox, VoiceOver/iOS Safari, TalkBack/Android Chrome, 200% zoom and 320 px reflow | Covers desktop and both phone platforms. | Assumed (owner to confirm) |
| Loading/progress announcements | S-05/S-06 ship first; this slice verifies their markup and scripts against the written contract and may fix them in place, adding no new behaviour | Avoids competing scripts while keeping the AA claim fixable for the capture flow. | Assumed (owner to confirm) |
| Enter hint association | Shared helper adds `<auto_id>-enter-hint` to `aria-describedby` on initial and invalid renders | Screen-reader users must hear that Enter submits (SC 3.3.2). | Research |
| Error announcement without JS | Title prefix "Błąd: " and an error summary linked to the fields | `role="alert"` on a page load is announced unreliably, but titles are always read. | Assumed (owner to confirm) |
| Error ID convention | Use Django's `<auto_id>_error`, one container per field | Django 5.2 already emits that reference automatically. | Research |
| Visual scope | Light theme only; no redesign; S-06 spinner relies on Pico's reduced-motion handling | Keeps the current look; only adds focus, border and skip-link tokens. | Assumed (owner to confirm) |
| Target | Explicit accessibility criteria for family flows | PK-17 / Open Question 18. | PRD |

## Scope

**In scope:**
- Shared field partial: error, hint and readable-date association.
- Skip link, visible focus for every control, 3:1 control borders, and contextual "Edytuj" text.
- Error-aware titles and a linked error summary.
- Reusable page audit and token-contrast tests.
- `accessibility.md` criteria, plus AGENTS.md and test-plan pointers.
- A recorded manual AT pass.

**Out of scope:**
- New JavaScript behaviour and progress indicators (S-05/S-06 own them; only small in-place fixes here).
- Playwright and axe in CI.
- Dark mode and redesign.
- Admin and allauth secondary pages.
- AAA criteria and a formal accessibility statement.
- Removing the sign-up link (S-09).
- Any data or permission change.

## Architecture / Approach

The work stays in the existing no-JavaScript, Pico-plus-tokens architecture. It fixes the shared `_field.html` contract and a single helper that composes `aria-describedby`. It adds accessibility tokens and classes in `tokens.css` and a skip link in `base.html` and `500.html`. A dependency-free `family_notes/a11y_audit.py` parses rendered responses, and new audit test modules call it for every covered flow and state through real views with classification mocked.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Form field error and hint association | Resolvable, unique error, hint and date references in all forms | Existing tests encode the old `-error` ID; that assertion needs a reviewed update |
| 2. Layout, focus and contrast tokens | Skip link, visible focus, 3:1 borders, "Błąd:" titles, linked summary | Pico specificity overriding the focus rules; 404 body identity must hold |
| 3. Automated audit and written criteria | `audit_page` helper, flow-wide audit tests, contrast test, `accessibility.md` | Audit rules too strict or too loose; checked by a deliberate break |
| 4. AT verification pass | `a11y-verification.md` with axe and screen-reader results | Real-device access (iOS, Android) and findings that need extra fixes |

**Prerequisites:** none (roadmap-future S-17 has no prerequisites). The confirmed order (S-01, S-02, S-20, S-03, S-04, S-05, S-06, S-07, S-08, S-09, S-17, S-14, S-15, S-16) places it after S-01–S-09 and S-20, so their new templates are covered (S-03/S-04 review states, S-05 Enter markup, S-06 progress states and `/offline/` have audit cases), and before S-14–S-16, which reuse its audit helper.
**Estimated effort:** about 2–3 sessions for Phases 1–3, plus one manual session for Phase 4.

## Open Risks & Assumptions

- Owner review 2026-10-04 confirmed the decisions listed under "Owner Decisions (2026-10-04)" in plan.md; remaining assumed rows stand unless the owner objects.
- Owner decisions and plan-review fixes were applied 2026-10-04. Every remaining "Assumed (owner to confirm)" row stands in for PRD Open Question 18 (and Q7, Q1/Q12/Q20 where noted) and stands unless the owner objects.
- The stdlib audit covers structure, not rendered behaviour (colour in context, real focus order, announcements). The manual Phase 4 pass is required, not optional.
- Phase 4 may surface extra AA failures, for example target size in entry-row metadata or reflow of `.fn-details` at 320 px. These are fixed within templates, tokens or small in-place S-05/S-06 script fixes, or recorded as follow-ups.
- S-06 ships its progress UI before this slice; its live region must carry the `data-live-region` marker (planned in S-06) for the audit rule to pass. Final S-03/S-04 state names may shift the audit case list.

## Success Criteria (Summary)

- The covered flows pass the automated audit and the contrast tests on every run of the suite.
- Keyboard-only, NVDA, VoiceOver and TalkBack users can complete sign-in, capture → confirm (including Enter-to-submit and progress announcements), follow-up, parent management and the child view, with evidence recorded.
- The accessibility target and checklist are written down where future slices and agents will follow them.
