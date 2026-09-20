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

## Why this stack

FamilyNotes is a small, after-hours web app with a three-week MVP window, external sign-in, family-scoped access, and natural-language classification. Django is the recommended Python starter for web applications and provides authentication, permissions, PostgreSQL integration, migrations, and an admin interface in one conventional framework. Railway keeps application and PostgreSQL provisioning compact, while GitHub Actions with automatic deployment after merge supports a low-maintenance delivery flow. Bootstrapper support for Django is verified, reducing scaffolding risk within the short timeline.
