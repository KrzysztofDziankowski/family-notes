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

## 10xDevs AI Toolkit - Module 3, Lesson 3 (10xDevs 4.0 Hooks)

Treat a hook as a **quality gate the harness runs for the agent**, not a script you hope the agent notices. Hooks run outside the model, so they survive context compaction and forgotten instructions — but only a hook whose signal actually reaches the agent closes the loop:

```
test-plan.md "Quality Gates" -> pick the moment per gate -> /10x-configure-hook -> prove with sample JSON -> watch the agent fix a deliberate error
```

### Task Router - Where to start

| Skill | Use it when |
| --- | --- |
| `/10x-configure-hook` | Turning the gates from `context/foundation/test-plan.md` into agent hooks, fixing hooks that fire but the agent never reacts to, or auditing an existing hook config. It detects the harness from the repo and carries dated per-harness references. |
| `/10x-test-plan --status` | Read the current gates and rollout state. Changing which gates exist belongs to Lesson 1, not here. |
| `/10x-new` -> `/10x-research` -> `/10x-plan` -> `/10x-implement` | A hook surfaced a failure the agent cannot fix with a trivial correction (wrong business logic, flaky integration). Open a change instead of looping the hook. |

### Hook lifecycle

1. **Trigger** — an event in the harness: a tool finished editing a file, the agent is about to end its turn.
2. **Matcher** — narrows which tool calls or files the hook reacts to. Not every harness honours matchers the same way.
3. **Handler** — usually a shell command or script that reads the event payload as JSON on stdin.
4. **Signal** — what the hook returns. The exit code, stderr, stdout and JSON fields mean different things in different harnesses, and only one channel per event actually reaches the agent. **The signal channel differs per harness — check the skill's references before writing or reviewing a hook.**

A hook that runs but sends its message down the wrong channel is the most common failure: the user sees "hook error", the agent sees nothing and keeps going.

### Moments and layers

The slower the check, the rarer the moment:

| Moment | Typical checks | Reaches the agent? |
| --- | --- | --- |
| Per edit | Lint/format of **the edited file only**; related tests if they are fast | Yes, mid-work |
| End of turn (Stop or its equivalent) | Lint + tests for every file changed this turn, whole-project typecheck | Yes, before the agent hands back |
| Pre-commit (git) | Lint + tests on staged files; catches edits made without the agent | No — blocks the commit |
| Pre-push (git) | Heavier suites, e2e that run locally | No — blocks the push |
| CI | Integration, shared state, infrastructure you do not have locally | No — PR feedback |

Local layers do not replace CI; each one saves a CI round-trip. Start with one per-edit lint hook and one end-of-turn typecheck, then add layers when you see what escapes.

### Contract

- Read the gates from the "Quality Gates" section of `context/foundation/test-plan.md` (by title, not section number). A gate the plan explicitly defers stays deferred unless the user overrides it — quote the deferral when you ask.
- Per-edit hooks check only the file that was edited. Never run `--fix` or a linter over the whole project on every edit.
- End-of-turn hooks that can send the agent back must stop after one retry (the harness's "already continued" flag or equivalent), so an unfixable error does not loop.
- Per-edit hooks only see the harness's edit tools; a file rewritten through a shell command skips them. The end-of-turn hook re-checks every file changed this turn (`git diff`), so it is the net for those edits.
- Timeouts are usually in **seconds**. Check the unit before copying a number.
- Prove every hook before trusting it: run the script with a sample payload on a deliberately broken file and on a clean one, then revert the error.
- Never overwrite existing hook config silently. Audit it, name the defects, merge, and show the diff.

### Lesson boundaries

- Do not change the risk strategy or the gate definitions — that is Lesson 1 (`/10x-test-plan`).
- Do not write new tests here — hooks only run the tests Lesson 2 produced.
- Do not write E2E scenarios or browser verification — that is Lesson 4.
- Do not author CI pipelines or install git-hook managers unasked; recommend pre-commit/pre-push gates, let the user decide.

<!-- END @przeprogramowani/10x-cli -->
