# Agent quality gates

Source: `context/foundation/test-plan.md`, **Quality Gates** (2026-10-01).
Configured for Codex (`.codex/hooks.json`, `.agents/.10x-cli-manifest.json`)
and Claude Code (`.claude/settings.json`, `.claude/.10x-cli-manifest.json`).
Both call `scripts/hooks/quality_gate.py`; no dependencies were added.

| Event | Check | Timeout |
|---|---|---|
| Codex `PostToolUse`, `apply_patch` | Python syntax on each existing `.py` named by patch headers, including rename destinations | 30 s |
| Claude `PostToolUse`, `Write` / `Edit` | Python syntax on the edited `.py`, using `tool_input.file_path` | 30 s |
| Both `PostToolUse` (same entries) | Design-token literals in an edited allowlisted template | 30 s |
| Both `Stop` | Syntax on changed/untracked `.py`; changed-app Django tests; system checks; migration drift | 120 s |

Commands at Stop:

```sh
# The hook runs tests only for changed product apps.
uv run python manage.py test <changed-app> --noinput
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
```

The runner disables opt-in provider calls (`CLASSIFICATION_LIVE_EVAL=0`),
disables colored output, and preserves other environment configuration.
It collects staged and unstaged changes against HEAD plus untracked files,
including edits performed through shell commands. This sweeps the working
tree, including pre-existing changes; it cannot distinguish each agent's edits.
With no changes it runs no checks. Deleted/non-Python files skip syntax checks.
Syntax failures stop early; otherwise all three Django checks run and their
failures are aggregated. Tests are skipped when no product app changed.
Checks share a 105 s budget within the 120 s timeout. The full suite belongs
in CI or pre-push, not the Stop hook.

Feedback uses **stderr and exit 2** for both harnesses. Successful Stop output
is `{}`. `stop_hook_active: true` permits finishing after one corrective turn;
remaining failures must be reported by the agent. The runner also guards
`loop_count` if another harness imports the Claude configuration.

## Template literal check

`literal_errors(paths, base)` runs next to `syntax_errors`: on the edited
paths per edit and on the changed paths at Stop. It reports `path:line` for
`#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(|oklch\(|style=|<style` only in the
templates cleaned by `context/changes/child-list-ui/` (`LITERAL_TEMPLATES` in
`quality_gate.py`): `family_notes/templates/{base,403,404,500,_error}.html`,
`family_notes/templates/allauth/layouts/base.html`,
`family_notes/templates/account/login.html` and
`entries/templates/entries/{child_list,child_detail,child_states,_child_list_body,_child_entry_detail,_entry_row,_list_modes}.html`.
Paths match relative or absolute. `tokens.css` and other templates are never
scanned. Colours and inline styles belong in `family_notes/static/css/tokens.css`.
At Stop, literal hits do not skip the Django checks; their failures are
aggregated. Feedback stays stderr + exit 2.

Proof (2026-10-04, `_entry_row.html` changed temporarily, then restored):

```text
Claude Edit, relative path, clean template: exit 0, no output
Claude Edit, relative path, '#ff0000' appended: exit 2; stderr names _entry_row.html:25
Claude Edit, absolute path, '#ff0000' appended: exit 2; stderr names _entry_row.html:25
Claude Write from entries/ cwd, 'style=' appended: exit 2; stderr names _entry_row.html:25
Claude Edit after restoring the file: exit 0, no output
Claude Edit tokens.css / README.md: exit 0, no output
```

## Audit and decisions

- No previous project or user hook configuration was found for either harness;
  no entries or orphan scripts were replaced or removed.
- The existing repository-hygiene test treated all JSON files as fixtures.
  Its suffix check now exempts only `.codex/hooks.json` and
  `.claude/settings.json`; payload and provider-key scans still cover them.
- No configured linter, static typechecker, or git-hook manager exists. The
  per-edit gate checks Python syntax, not style or type correctness.
- No explicit agent-gate deferral was found. The per-edit gate is conditional
  on rollout Phase 3; invoking this setup configures that declared gate.
- Production-like migration rehearsal and deployment/HTTPS/admin smoke stay
  at pre-production/release. Git hooks and CI were not configured.
- Baseline in the original checkout: 677 tests, 4 skipped, exit 0; 95.741 s
  test time / 135.86 s wall time. System checks and migration drift: exit 0.
  The required full-suite gate therefore needs more than the 120 s example.

## Loading and verification

Codex: open `/hooks`, review and trust both definitions. Re-trust after changes.
Project trust alone does not approve hook definitions. If edits produce no
feedback, inspect both entries in `/hooks`: enabled hooks with `untrusted`
status are discovered but skipped. Review and trust the `PostToolUse` and
`Stop` commands from `.codex/hooks.json`, then repeat the syntax-error probe
with `apply_patch`. Do not treat a manual script invocation as proof of
automatic delivery.

Diagnosis on 2026-10-04, using Codex CLI 0.158.0 `hooks/list`: both project
hooks were discovered with `enabled: true`, `trustStatus: untrusted`, no
warnings and no errors. The `hooks` feature was already enabled and the
project was trusted. No matcher, feature flag or command change was needed;
the remaining activation step is review and trust in `/hooks`.

Claude Code: restart the session and inspect `/hooks` for both project entries;
use its debug log to confirm event matching and feedback delivery.

The configs and shell commands target the current Linux/WSL execution host.
Native Windows commands have not been configured or proven.

Ask each agent to introduce and fix a Python syntax error, then a failing
existing test assertion. Finally introduce a syntax error through a shell
write and verify Stop sends the agent back. Static type errors alone are not
covered because this repository has no static typechecker.

Hook scripts and payload signals can be proven locally; actual model reactions
still require hooks to be loaded in the harness. Checks cannot prove browser
rendering, family forms and navigation, production authorization configuration,
real OpenAI classification quality, or EduVulcan delivery/restart behavior.
Use the plan's integration/release checks and browser verification when needed.

Recommended git gates (not written): pre-commit syntax on staged Python plus
focused Django tests and migration drift; pre-push full Django tests/system
checks and existing deployment shell tests. Production PostgreSQL migration
rehearsal remains a pre-production check.

References checked 2026-10-03:
[Codex hooks](https://learn.chatgpt.com/docs/hooks),
[Claude Code hooks](https://code.claude.com/docs/en/hooks).
Payload fields, stderr/exit-2 signals and seconds-based timeouts agree with the
skill references. Shared root resolution uses Git, including from subdirectories
and worktrees, instead of Claude's session-start project directory.

## Proof results (2026-10-03)

Deliberate errors were introduced only in isolated copies of real source and
existing tests, then restored. The copy used synthetic development settings
rather than copying secrets. Both configured Stop commands ran the full
677-test suite (4 opt-in tests skipped), system checks and migration drift.
Live harness event delivery remains subject to loading/trust as described above.

```text
Codex broken source: exit 2, 0.1s; stderr names validation.py
Claude Write broken source: exit 2, 0.1s; stderr names validation.py
Claude Edit broken source: exit 2, 0.1s; stderr names validation.py
Codex multifile second file broken: exit 2, 0.1s; stderr names validation.py
Codex rename destination: exit 2, 0.1s; stderr names validation.py
Codex subdirectory cwd: exit 2, 0.1s; stderr names validation.py
Shell edit caught by Stop: exit 2, 0.1s; stderr names validation.py
Stop retry with source still broken: exit 0, 0.1s; no blocking output
Claude Write clean source: exit 0, 0.1s; no blocking output
Claude Edit clean source: exit 0, 0.1s; no blocking output
Codex clean source: exit 0, 0.1s; no blocking output
Codex skip README.md: exit 0, 0.1s; no blocking output
Claude skip README.md: exit 0, 0.2s; no blocking output
Codex skip missing-file.py: exit 0, 0.1s; no blocking output
Claude skip missing-file.py: exit 0, 0.1s; no blocking output
Pathless/non-edit payload '{}': exit 0, 0.1s; no blocking output
Pathless/non-edit payload 'not json': exit 0, 0.1s; no blocking output
Pathless/non-edit payload '': exit 0, 0.1s; no blocking output
Pathless/non-edit payload 'null': exit 0, 0.1s; no blocking output
Pathless/non-edit payload '[]': exit 0, 0.1s; no blocking output
Pathless/non-edit payload '{"tool_input":null}': exit 0, 0.1s; no blocking output
Pathless/non-edit payload '{"tool_name":"Read","tool_input":{"file_path":"manage.py"}}': exit 0, 0.1s; no blocking output
Pathless/non-edit payload '{"tool_input":{"command":"no patch headers"}}': exit 0, 0.1s; no blocking output
Stop no changed files: exit 0, 0.1s; no blocking output
Stop failing behavioural test: exit 2, 86.3s; stderr names deliberate hook behavioural proof
Codex actual configured Stop command / clean full suite: exit 0, 132.3s; stdout {}
Claude actual configured Stop command / clean full suite: exit 0, 149.4s; stdout {}
Stop empty/malformed {}, not json, empty stdin, null, []: each exit 0, stdout {}
Stop untracked syntax error: exit 2, stderr names new_source.py
Stop staged syntax error: exit 2, stderr names new_source.py
Codex configured per-edit command from entries/: exit 0, no output
Claude configured per-edit command from entries/: exit 0, no output
RepositoryHygieneTests in original checkout: 4 tests, exit 0
Original checkout final system check: exit 0, no issues
Original checkout final migration drift check: exit 0, no changes
JSON configs / Python syntax / git diff --check: success
```
