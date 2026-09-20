---
bootstrapped_at: 2026-09-20T19:07:31Z
starter_id: django
starter_name: Django
project_name: family-notes
language_family: python
package_manager: uv
cwd_strategy: native-cwd
bootstrapper_confidence: verified
phase_3_status: ok
audit_command: pip-audit
---

## Hand-off

```yaml
---
starter_id: django
package_manager: uv
project_name: family-notes
hints:
  language_family: python
  team_size: solo
  deployment_target: railway
  ci_provider: github-actions
  ci_default_flow: auto-deploy-on-merge
  bootstrapper_confidence: verified
  path_taken: standard
  quality_override: false
  self_check_answers: null
  has_auth: true
  has_payments: false
  has_realtime: false
  has_ai: true
  has_background_jobs: false
---
```

## Why this stack

FamilyNotes is a small, after-hours web app with a three-week MVP window, external sign-in, family-scoped access, and natural-language classification. Django is the recommended Python starter for web applications and provides authentication, permissions, PostgreSQL integration, migrations, and an admin interface in one conventional framework. Railway keeps application and PostgreSQL provisioning compact, while GitHub Actions with automatic deployment after merge supports a low-maintenance delivery flow. Bootstrapper support for Django is verified, reducing scaffolding risk within the short timeline.

## Pre-scaffold verification

| Signal | Value | Severity | Notes |
| --- | --- | --- | --- |
| npm package | not run | n/a | non-JavaScript starter |
| GitHub repo | not run | n/a | card docs URL is Django documentation, not a GitHub repository; no recency signal available |

## Scaffold log

**Resolved invocation**: `django-admin startproject family_notes .`
**Strategy**: native-cwd
**Exit code**: 0
**Pre-flight files-to-touch**: `manage.py`, `family_notes/__init__.py`, `family_notes/asgi.py`, `family_notes/settings.py`, `family_notes/urls.py`, `family_notes/wsgi.py`
**Files written by CLI**: 6
**Pre-existing files preserved**: none of the target paths existed
**Project environment**: `pyproject.toml` and `uv.lock` present; `uv lock --check` resolved 34 packages successfully
**Django system check**: passed with 0 issues
**Migration check**: passed; no model changes detected

## Post-scaffold audit

**Tool**: `uv run --locked pip-audit --format json`
**Summary**: 0 CRITICAL, 0 HIGH, 0 MODERATE, 0 LOW
**Direct vs transitive**: not distinguished by this tool
**Dependencies audited**: 32

#### CRITICAL findings

None.

#### HIGH findings

None.

#### MODERATE findings

None.

#### LOW / INFO findings

None.

**Raw result**: `No known vulnerabilities found`

## Hints recorded but not acted on

| Hint | Value |
| --- | --- |
| bootstrapper_confidence | verified |
| quality_override | false |
| path_taken | standard |
| self_check_answers | null |
| team_size | solo |
| deployment_target | railway |
| ci_provider | github-actions |
| ci_default_flow | auto-deploy-on-merge |
| has_auth | true |
| has_payments | false |
| has_realtime | false |
| has_ai | true |
| has_background_jobs | false |

## Next steps

Next: a future skill will set up agent context (CLAUDE.md, AGENTS.md). For now, your project is scaffolded and verified - happy hacking.

Useful manual steps in the meantime:

- `git init` (if you have not already) to start your own repo history.
- Review any `.scaffold` siblings the conflict policy created and decide which version of each file to keep.
- Address audit findings per your project's risk tolerance - this run found none.
