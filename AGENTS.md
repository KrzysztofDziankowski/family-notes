# Repository Guidelines

FamilyNotes is a Django 5.2 web application managed with `uv`. The repository currently contains the project scaffold; use `@context/foundation/prd.md` for product behavior and `@context/foundation/tech-stack.md` for the delivery assumptions.

## Hard Rules

- Never write to `context/archive/`; archived changes are immutable. If a resolved target is archived, stop and open a new change under `context/changes/`.
- Enforce family-scoped access in every query and mutation. Parents may manage family entries, children may read only entries assigned to them, and unauthenticated users may not access family data; see `@context/foundation/prd.md`.
- Keep classification input limited to producing and saving the requested family entry. Do not add secondary storage, analytics, or training use for that text.
- Keep secrets and deployment-specific values out of source control. Replace the scaffolded development values in `@family_notes/settings.py` with environment-backed configuration before deployment.

## Commands

- `uv sync` installs dependencies from `@uv.lock`.
- `uv run python manage.py runserver` starts the local Django server.
- `uv run python manage.py check` runs Django's system checks.
- `uv run python manage.py test` runs the Django test suite.
- `uv run python manage.py makemigrations --check --dry-run` detects model changes without migrations.
- `uv run --locked pip-audit` audits locked dependencies.

## Project Structure

- `family_notes/` contains project settings, root URLs, and ASGI/WSGI entry points.
- `manage.py` is the Django command entry point and uses `family_notes.settings`.
- `context/foundation/` contains living product and stack decisions. Edit those documents in place when decisions change.
- `context/changes/<change-id>/` contains change-scoped work; follow `@context/changes/README.md`.

## Development Conventions

- Keep `family_notes/` limited to project-wide configuration and URL composition; place product models, views, forms, and tests in their owning Django apps.
- For every data visibility or mutation path, test parent access, assigned-child access, another child's access, and unauthenticated access as applicable.
- Treat the MVP boundaries and unresolved classification cases in `@context/foundation/prd.md` as authoritative; do not silently expand deferred features.

## UI Conventions

- Design tokens and shared component classes live in `@family_notes/static/css/tokens.css`, layered on Pico.
- Before creating markup, check the partials in `entries/templates/entries/_*.html` and `@family_notes/templates/_error.html`. Add new shared classes to `tokens.css`, built from existing tokens.
- No literal colours, inline `style=` attributes or `<style>` blocks in templates; `scripts/hooks/quality_gate.py` flags them in the cleaned templates.
- Every Django error page (403/404/500) extends the base layout.
- DEBUG-only kitchen sinks: `/entries/_states/` (parent capture and management views) and `/entries/mine/_states/` (child views). Add new states there.
- All user-facing copy is in Polish (Django admin excepted).

## Commits and Verification

Recent history uses short imperative summaries such as `Add prd.md` and `Update skills m1l4`; match that style. Before handing off, run the relevant focused tests plus Django checks and the migration check. Run `uv run --locked pip-audit` after dependency changes.
<!-- BEGIN @przeprogramowani/10x-cli -->

## 10xDevs AI Toolkit - Module 3, Lesson 4 (E2E Tests)

**For E2E tests, use the two M3L4 skills in this order:**

1. **`/10x-e2e-setup`** — one-time setup: Playwright config (`webServer`,
   auth `setup` project, `storageState`), a green seed test, and `context/foundation/test-stack.md`.
2. **`/10x-e2e`** — the per-risk loop: risk → explore the running app with
   `playwright-cli` → generate → review against the five anti-patterns →
   re-prompt by name → verify with a deliberate break.

The skills' `references/` carry the full rules, anti-patterns, seed pattern, and
prompt-template.

A few hard rules that hold even before you invoke the skill:

- **Locators:** `getByRole` / `getByLabel` / `getByText` first; `getByTestId`
  only when accessibility attributes are ambiguous. Never CSS selectors, XPath,
  or DOM structure.
- **Never `page.waitForTimeout()`.** Wait for state: `toBeVisible()`,
  `waitForURL()`, `waitForResponse()`.
- **Test independence + cleanup.** Each test runs standalone — its own setup,
  action, assertion, and cleanup; unique ids (timestamp suffix) so parallel runs
  and re-runs don't collide.

Two boundaries to keep straight:

- **DOM (snapshot) is the default.** Vision (`--caps=vision`) is a supplement for
  visual-only risks (layout, z-index, animation); for pixel regression prefer
  deterministic tools (`toHaveScreenshot`, Argos, Lost Pixel). VLM model
  selection/cost is a debugging topic (Lesson 5), not testing.
- **A red test is a signal, not a chore.** A changed selector → update the
  locator in a reviewed diff. A changed business behavior → the test caught a
  bug; never edit the assertion to match it. Fixing failing tests is Lesson 5.

<!-- END @przeprogramowani/10x-cli -->
