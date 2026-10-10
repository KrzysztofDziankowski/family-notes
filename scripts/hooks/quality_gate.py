#!/usr/bin/env python3
"""Shared Codex/Claude Code gates; feedback is stderr + exit 2."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import tokenize


def payload():
    try:
        data = json.load(sys.stdin)
        return data if isinstance(data, dict) else {}
    except (ValueError, OSError):
        return {}


def cwd(data):
    value = data.get('cwd')
    path = Path(value) if isinstance(value, str) and value else Path.cwd()
    return path if path.is_dir() else Path.cwd()


def edited_paths(data):
    arguments = data.get('tool_input')
    if not isinstance(arguments, dict):
        return []
    tool = data.get('tool_name')
    if tool in ('Write', 'Edit'):
        value = arguments.get('file_path')
        return [value] if isinstance(value, str) else []
    if tool not in (None, 'apply_patch'):
        return []
    patch = arguments.get('command')
    if not isinstance(patch, str):
        return []
    return re.findall(r'^\*\*\* (?:Update File|Add File|Move to): (.+)$', patch, re.MULTILINE)


def syntax_errors(paths, base):
    errors = []
    for name in dict.fromkeys(paths):
        path = base / name
        if path.suffix != '.py' or not path.is_file():
            continue
        try:
            with tokenize.open(path) as source:
                compile(source.read(), str(path), 'exec')
        except (SyntaxError, UnicodeError, OSError, ValueError) as error:
            errors.append(f'{path}: {error}')
    return errors


# Templates cleaned by the child-list-ui change; they must use tokens.css only.
LITERAL_TEMPLATES = (
    'family_notes/templates/base.html',
    'family_notes/templates/403.html',
    'family_notes/templates/404.html',
    'family_notes/templates/500.html',
    'family_notes/templates/_error.html',
    'family_notes/templates/allauth/layouts/base.html',
    'family_notes/templates/account/login.html',
    *(f'entries/templates/entries/{name}.html' for name in (
        'child_list', 'child_detail', 'child_states', '_child_calendar',
        '_child_entry_detail', '_entry_row', '_calendar_nav', '_calendar_days',
        '_member_filter', 'child_capture', '_capture_body', '_privacy_filter',
        '_privacy_control',
    )),
)
LITERAL_PATTERN = re.compile(
    r'(?<!href=")(?<!href=\')#[0-9a-f]{3,8}\b|rgba?\(|hsla?\(|oklch\(|style=|<style',
    re.IGNORECASE,
)


def literal_template(path):
    text = path.as_posix()
    return any(text == name or text.endswith('/' + name) for name in LITERAL_TEMPLATES)


def literal_errors(paths, base):
    errors = []
    for name in dict.fromkeys(paths):
        path = base / name
        if not literal_template(path) or not path.is_file():
            continue
        try:
            lines = path.read_text(encoding='utf-8').splitlines()
        except (UnicodeError, OSError) as error:
            errors.append(f'{path}: {error}')
            continue
        for number, line in enumerate(lines, 1):
            # Django's one-line comments are documentation, not rendered markup.
            rendered = re.sub(r'{#.*?#}', '', line)
            match = LITERAL_PATTERN.search(rendered)
            if match:
                errors.append(f'{path}:{number}: literal {match.group(0)!r}; '
                              'use tokens.css classes and variables instead')
    return errors


# Git on the /mnt/c SynologyDrive checkout can take ~10 s while tests run.
GIT_TIMEOUT_SECONDS = 30


def run(command, root, env, timeout):
    try:
        result = subprocess.run(command, cwd=root, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=timeout)
        output = result.stdout.decode('utf-8', errors='replace')
        return result.returncode, output
    except subprocess.TimeoutExpired as error:
        output = (error.stdout or b'').decode('utf-8', errors='replace')
        return 2, f'Timed out after {timeout:.1f}s\n{output}'
    except OSError as error:
        return 2, str(error)


def stop_errors(data):
    # One continuation only. Also guard against loops if Cursor imports this hook.
    if data.get('stop_hook_active') is True or data.get('loop_count', 0) != 0:
        return []
    base = cwd(data)
    env = dict(os.environ, NO_COLOR='1', FORCE_COLOR='0', CLASSIFICATION_LIVE_EVAL='0')
    status, output = run(['git', 'rev-parse', '--show-toplevel'], base, env, GIT_TIMEOUT_SECONDS)
    if status:
        return ['Cannot locate repository root:\n' + output]
    root = Path(output.strip())
    paths = []
    for command in (['git', 'diff', '--name-only', '-z', 'HEAD'],
                    ['git', 'ls-files', '--others', '--exclude-standard', '-z']):
        status, output = run(command, root, env, GIT_TIMEOUT_SECONDS)
        if status:
            return ['Cannot collect changed files:\n' + output]
        paths.extend(name for name in output.split('\0') if name)
    if not paths:
        return []
    errors = syntax_errors(paths, root)
    # Importing a syntactically invalid module would only repeat the same error.
    if errors:
        return errors
    errors = literal_errors(paths, root)
    deadline = time.monotonic() + 105
    test_apps = sorted({
        part for name in paths
        for part in ('entries', 'family_access', 'family_notes')
        if name == part or name.startswith(part + '/')
    })
    commands = []
    if test_apps:
        commands.append(['uv', 'run', 'python', 'manage.py', 'test', *test_apps, '--noinput'])
    commands.extend([
        ['uv', 'run', 'python', 'manage.py', 'check'],
        ['uv', 'run', 'python', 'manage.py', 'makemigrations', '--check', '--dry-run'],
    ])
    for command in commands:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            errors.append('Quality gate exceeded its 105s check budget.')
            break
        status, output = run(command, root, env, remaining)
        if status:
            # Keep feedback readable within the harness output limit.
            excerpt = output if len(output) <= 6000 else output[:1500] + '\n...\n' + output[-4500:]
            errors.append(' '.join(command) + f' (exit {status}):\n' + excerpt)
    return errors


def main():
    data = payload()
    mode = sys.argv[1] if len(sys.argv) > 1 else ''
    if mode == 'edit':
        paths, base = edited_paths(data), cwd(data)
        errors = syntax_errors(paths, base) + literal_errors(paths, base)
    elif mode == 'stop':
        errors = stop_errors(data)
    else:
        return 0
    if errors:
        print('Fix these quality-gate failures before finishing:\n' + '\n\n'.join(errors),
              file=sys.stderr)
        return 2
    if mode == 'stop':
        print('{}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
