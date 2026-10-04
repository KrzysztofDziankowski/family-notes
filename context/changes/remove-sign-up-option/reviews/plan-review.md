<!-- PLAN-REVIEW-REPORT -->
# Plan Review: Remove Sign-Up Option Implementation Plan

- **Plan**: context/changes/remove-sign-up-option/plan.md
- **Mode**: Deep
- **Date**: 2026-10-04
- **Verdict**: SOUND
- **Triage**: applied 2026-10-04
- **Findings**: 0 critical, 1 warning, 1 observation

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| End-State Alignment | PASS |
| Lean Execution | PASS |
| Architectural Fitness | PASS |
| Blind Spots | PASS |
| Plan Completeness | WARNING |

## Grounding
Grounding: 5/5 paths ✓ (`family_notes/templates/account/login.html`, `family_notes/settings.py`, `family_notes/tests.py`, `family_access/admin.py`, `context/archive/2026-09-23-identity-and-family-access-contract/plan.md`). The new files `family_access/auth_adapters.py` and `family_notes/templates/account/signup_closed.html` do not exist yet, as expected.

allauth claims were verified against the installed version, **65.19.7** (`.venv/lib/python3.10/site-packages/allauth`, matching `uv.lock`):
- `DefaultAccountAdapter.is_open_for_signup` returns `True` (account/adapter.py:304-311).
- `DefaultSocialAccountAdapter.is_open_for_signup` delegates to the account adapter (socialaccount/adapter.py:215-224) ✓.
- `process_signup` raises `SignupClosedException` (socialaccount/internal/flows/signup.py:109-111) ✓.
- `complete_login` renders `account/signup_closed.html` on that exception (flows/login.py:57-63) ✓.
- `/accounts/signup/` is gated in `CloseableSignupMixin.dispatch` before any form processing, so a POST creates nothing and returns a 200 `TemplateResponse` (account/mixins.py:132-152; account/views.py:134-140) ✓.
- The social "complete sign-up" view calls the **social** adapter's `is_open_for_signup` (socialaccount/views.py:52-55), so Assumed Decision 5 holds with the proposed social adapter ✓.
- `allauth.socialaccount.helpers.complete_social_login` exists (helpers.py:73) ✓.
- The only other callers of `is_open_for_signup` are in `allauth.headless`, which is not installed. Login-by-code and passkeys are not configured.
- `signup_closed.html` extends `account/base_entrance.html`, which the project wraps into `base.html` through `family_notes/templates/allauth/layouts/base.html` ✓.

The plan correctly identifies the critical coupling, and its two-adapter design is the right fix. brief↔plan ✓, with a stale header (F2). Progress↔Phase ✓: 6+3 steps match, and phase blocks contain no checkboxes. Cross-plan: S-14 relies on this plan's Google-first-sign-in contract and states it consistently (`family-membership-management/plan.md:14,29`). S-17 audits the login page after S-09 and excludes allauth secondary pages. Neither S-07 nor S-08 touches the auth files, and none of the three plans adds a migration.

## Findings

### F1 — Login copy is already Polish; the absence test can miss it

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Current State Analysis (bullets 1 and 5); Phase 2 item 2 (login page tests); Phase 1 item 3 rationale
- **Detail**: The plan says the sign-up text and allauth's `signup_closed.html` are English. In fact `LANGUAGE_CODE = 'pl'` (settings.py:444), and allauth 65.19.7 ships Polish translations. The login paragraph renders as "Jeżeli nie masz jeszcze konta, to proszę **zarejestruj się**." and the closed page as "Rejestracja zamknięta / Przepraszamy, ale w tej chwili rejestracja jest zamknięta." (`allauth/locale/pl/LC_MESSAGES/django.po:1086-1089, 1296-1301`). The Phase 2 test asserts that the page does not contain `"sign up"` or `"Zarejestruj"` (capital Z). Both checks pass even if the real lowercase "zarejestruj się" text stays on the page, so only the href check guards the change. The Polish override of `signup_closed.html` is still worth doing: it adds the "accounts are created by the family administrator" explanation and a login link. Only its stated rationale is wrong.
- **Fix**: Make the Phase 2 assertion case-insensitive on Polish and English stems: no `account_signup` URL, and none of "zarejestruj", "rejestracj" or "sign up" in `response.content.decode().lower()`. Correct the two Current State claims, and re-justify the override as product copy plus a login link rather than as a translation.
- **Owner input**: no
- **Decision**: FIXED (Fix A)

### F2 — Stale owner-decision text and "blocked" status

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Owner Decisions (2026-10-04); plan-brief "Open Risks & Assumptions"
- **Detail**: The confirmed order in the plan omits S-20 (`roadmap-future.md:43-60`). The brief still says "Implementation is **blocked on owner confirmation** … (roadmap status: blocked)", although the owner decided S-09 on 2026-10-04 (`roadmap-future-questions.md`) and the roadmap row is `planning` with `Blockers: —`.
- **Fix**: Include S-20 in the order and drop the "blocked" sentence from the brief.
- **Owner input**: no
- **Decision**: FIXED (Fix A)
