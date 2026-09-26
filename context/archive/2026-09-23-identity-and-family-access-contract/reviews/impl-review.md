<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Identity and Family Access Contract Implementation Plan

- **Plan**: `context/changes/identity-and-family-access-contract/plan.md`
- **Scope**: Full plan
- **Reviewed phases**: 1, 2, 3, 4
- **Date**: 2026-09-24
- **Verdict**: NEEDS ATTENTION
- **Findings**: 0 critical 3 warnings 1 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | PASS |
| Scope Discipline | WARNING |
| Safety & Quality | WARNING |
| Architecture | PASS |
| Pattern Consistency | PASS |
| Success Criteria | WARNING |

## Findings

### F1 — Production can boot with development defaults

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM - real tradeoff; pause to reason through it
- **Dimension**: Safety & Quality
- **Location**: `family_notes/settings.py:42`
- **Detail**: `DJANGO_DEBUG` defaults to `True`, and the development `SECRET_KEY` fallback is rejected only when `DEBUG` is false. If the production environment file is missing or omits `DJANGO_DEBUG`, Django can boot in debug mode with insecure local defaults. `uv run python manage.py check --deploy` under the default environment reports `security.W018` plus secure-cookie/SSL/HSTS warnings.
- **Fix**: Make production fail closed by defaulting `DJANGO_DEBUG` to false, or introduce an explicit environment marker that is required for local development and production validation.
  - Strength: Prevents an auth-enabled production release from silently using development safety settings.
  - Tradeoff: Local setup becomes slightly more explicit because developers may need to set `DJANGO_DEBUG=True` in `.env`.
  - Confidence: HIGH - the behavior is directly visible in `settings.py` and Django's deployment check.
  - Blind spot: The deployed service may already provide a complete env file; this finding is about the fail-open default when it does not.
- **Decision**: FIXED - `DJANGO_DEBUG` now defaults to `False`, so missing production configuration fails closed through the existing secret-key validation.

### F2 — Missing Google OAuth credentials are not rejected in production

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW - quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: `family_notes/settings.py:170`
- **Detail**: `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET` default to empty strings. The docs require populated production values, but the app does not enforce them when `DEBUG` is false, so an auth-enabled release can pass checks and fail only when users attempt Google sign-in.
- **Fix**: Raise `ImproperlyConfigured` when `DEBUG` is false and either Google OAuth variable is missing.
- **Decision**: FIXED - production startup now requires both Google OAuth credentials and fails early with `ImproperlyConfigured` when either is missing.

### F3 — Deployment docs disagree on the canonical production host

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM - real tradeoff; pause to reason through it
- **Dimension**: Success Criteria
- **Location**: `context/changes/deployment/deployment-plan.md:5`
- **Detail**: The deployment plan records `https://inodzik.bieda.it/` and says to use `inodzik.bieda.it`, while `context/changes/deployment/mikrus-runbook.md` uses `familynotes.mikrus.dev`. This can send operators toward inconsistent `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, and Google OAuth callback values.
- **Fix**: Pick the canonical production host and update the deployment plan, runbook, smoke checks, and OAuth redirect instructions to match.
  - Strength: Removes an operator-facing ambiguity before auth is deployed.
  - Tradeoff: Requires confirming which hostname is actually authoritative outside the repository.
  - Confidence: HIGH - both hostnames are present in current tracked deployment docs.
  - Blind spot: The latest production hostname may be known to the operator but not recorded consistently in the repository.
- **Decision**: FIXED - standardized the deployment plan and Google OAuth callback on the confirmed canonical host `familynotes.mikrus.dev`.

### F4 — Roadmap still describes F-01 as in progress

- **Severity**: 👀 OBSERVATION
- **Impact**: 🏃 LOW - quick decision; fix is obvious and narrowly scoped
- **Dimension**: Scope Discipline
- **Location**: `context/foundation/roadmap.md:42`
- **Detail**: The roadmap still marks `identity-and-family-access-contract` as `in-progress` and its baseline says no product models or external identity/roles are wired, even though this change adds `family_access` models, allauth wiring, admin setup, and account status routing. Future agents may plan duplicate foundation work from stale context.
- **Fix**: Update the F-01 roadmap status and baseline after triage or archive, matching the repository's completed implementation state.
- **Decision**: SKIPPED - roadmap synchronization is deferred for the user to handle later.

## Verification

- `uv sync` - PASS: resolved and checked 42 packages.
- `uv run python manage.py check` - PASS: system check identified no issues.
- `uv run python manage.py makemigrations --check --dry-run` - PASS: no changes detected.
- `uv run python manage.py test` - PASS: 25 tests passed.
- `uv run --locked pip-audit` - PASS: no known vulnerabilities found.
- `uv run python manage.py check --deploy` - WARNING: default environment reports `security.W004`, `security.W008`, `security.W012`, `security.W016`, and `security.W018`.
