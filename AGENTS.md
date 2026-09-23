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

## 10xDevs AI Toolkit - Module 2, Lesson 2

Turn one roadmap item into the first implementation cycle with the **change planning chain**:

```
/10x-roadmap -> /10x-new -> /10x-plan -> /10x-plan-review -> /10x-implement
```

`/10x-new`, `/10x-plan`, `/10x-plan-review`, and `/10x-implement` are the lesson focus. `/10x-frame` and `/10x-research` are not required rituals here; they are escalation paths introduced in the next lesson.

### Task Router - Where to start

| Skill | Use it when |
| --- | --- |
| **Change setup (lesson focus)** | |
| `/10x-new <change-id>` | You selected a roadmap item and need a stable change folder. Creates `context/changes/<change-id>/change.md` so planning, implementation, progress, commits, and later review all share one identity. Use AFTER roadmap selection, BEFORE `/10x-plan`. |
| **Planning (lesson focus)** | |
| `/10x-plan <change-id>` | You have a change folder and need a reviewable implementation plan. Reads roadmap context, foundation docs, codebase evidence, and any existing change notes; writes `plan.md` and `plan-brief.md` with phases, file contracts, success criteria, and `## Progress`. |
| **Plan readiness (lesson focus)** | |
| `/10x-plan-review <change-id>` | You have `plan.md` and need a light pre-code readiness check. Use it to catch missing end state, weak contracts, malformed progress, scope drift, or blind spots before code changes begin. |
| **Implementation (lesson focus)** | |
| `/10x-implement <change-id> phase <n>` | You have an approved plan and want to execute one phase with verification, manual gate, commit ritual, and SHA write-back to `## Progress`. |
| **Lifecycle closure** | |
| `/10x-archive <change-id>` | A change is merged or intentionally closed. Move it out of active `context/changes/` into archive state. |

### How the chain hands off

- `/10x-new` creates the durable change identity.
- `/10x-plan` turns that identity into an implementation contract.
- `/10x-plan-review` checks the plan before the agent mutates code.
- `/10x-implement` executes one planned phase, verifies, asks for manual confirmation when needed, commits, and records progress.

### Lesson boundaries

- Plan is the default router after roadmap selection. Start with `/10x-plan` unless the problem is unclear or external evidence is blocking.
- Do not run `/10x-frame + /10x-research` as ceremony for every change.
- Do not turn this lesson into a full end-to-end product build. A checkpoint with a planned and partially or fully implemented stream is valid.
- Code review of the implemented diff belongs to Lesson 3 via `/10x-impl-review`.
- Lifecycle closure via `/10x-archive` after a change is merged or intentionally closed.

### Paths used by this lesson

- `context/foundation/roadmap.md` - upstream roadmap
- `context/changes/<change-id>/change.md` - change identity
- `context/changes/<change-id>/plan.md` - implementation contract
- `context/changes/<change-id>/plan-brief.md` - compressed handoff
- `context/foundation/lessons.md` - recurring rules and pitfalls
- `docs/reference/contract-surfaces.md` - load-bearing names registry

Skills must not write to `context/archive/`. Archived changes are immutable; if a resolved target path starts with `context/archive/`, abort with: "This change is archived. Open a new change with `/10x-new` instead."

<!-- END @przeprogramowani/10x-cli -->
