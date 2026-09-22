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

## Commits and Verification

Recent history uses short imperative summaries such as `Add prd.md` and `Update skills m1l4`; match that style. Before handing off, run the relevant focused tests plus Django checks and the migration check. Run `uv run --locked pip-audit` after dependency changes.
<!-- BEGIN @przeprogramowani/10x-cli -->

## 10xDevs AI Toolkit - Module 2, Lesson 1

Move from sprint-zero setup to project orchestration with the **roadmap chain**:

```
(Module 1 foundation docs) -> /10x-roadmap -> backlog-ready roadmap items
```

`/10x-roadmap` is the lesson focus. `/10x-new` is intentionally introduced in Module 2, Lesson 2, when a selected roadmap item becomes an implementation change folder.

### Task Router - Where to start

| Skill | Use it when |
| --- | --- |
| **Roadmap (lesson focus)** | |
| `/10x-roadmap` | You have `context/foundation/prd.md` and a scaffolded project baseline, and you need a vertical-first MVP roadmap. The skill reads the PRD, inspects the code baseline, uses available foundation docs such as `tech-stack.md`, `infrastructure.md`, and `deploy-plan.md`, then writes `context/foundation/roadmap.md`. Use it BEFORE creating per-change folders or implementation plans. |
| **Re-run upstream if needed** | |
| `/10x-shape` / `/10x-prd` / `/10x-tech-stack-selector` / `/10x-bootstrapper` / `/10x-agents-md` / `/10x-infra-research` | Bundled from Module 1 so foundation contracts can be fixed before roadmap sequencing. If roadmap generation exposes a PRD gap, repair the PRD before pretending the backlog is ready. |

### How the chain hands off

- `/10x-roadmap` bridges product and implementation. It does not choose frameworks, design schemas, or write a per-change implementation plan.
- The output is `context/foundation/roadmap.md`: ordered milestones, vertical slices, bounded foundations, dependencies, unknowns, risk, and backlog handoff fields.
- Roadmap items should receive stable human-readable identifiers in backlog tools. The actual `context/changes/<change-id>/` folder is created in Lesson 2 with `/10x-new`.

### Roadmap boundaries

- Default to vertical slices: user-visible outcomes that cross UI, data, business logic, and integrations.
- Horizontal work is allowed only as a bounded enabler that names the downstream vertical milestone it unlocks.
- Avoid orphan horizontal work such as "build the whole database", "build all API endpoints", or "design the whole UI" before the first user-visible flow.
- Roadmap is not a calendar estimate. Do not invent dates, story points, or sprint velocity unless the user explicitly asks for a separate planning artifact.

### Foundation paths used by this lesson

- `context/foundation/prd.md` - input
- `context/foundation/tech-stack.md` - optional input
- `context/foundation/infrastructure.md` - optional input
- `context/deployment/deploy-plan.md` - optional input
- `context/foundation/roadmap.md` - output
- `context/foundation/lessons.md` - recurring rules and pitfalls
- `docs/reference/contract-surfaces.md` - load-bearing names registry

Skills must not write to `context/archive/`. Archived changes are immutable; if a resolved target path starts with `context/archive/`, abort with: "This change is archived. Open a new change with `/10x-new` instead."

<!-- END @przeprogramowani/10x-cli -->
