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
    status, output = run(['git', 'rev-parse', '--show-toplevel'], base, env, 5)
    if status:
        return ['Cannot locate repository root:\n' + output]
    root = Path(output.strip())
    paths = []
    for command in (['git', 'diff', '--name-only', '-z', 'HEAD'],
                    ['git', 'ls-files', '--others', '--exclude-standard', '-z']):
        status, output = run(command, root, env, 5)
        if status:
            return ['Cannot collect changed files:\n' + output]
        paths.extend(name for name in output.split('\0') if name)
    if not paths:
        return []
    errors = syntax_errors(paths, root)
    # Importing a syntactically invalid module would only repeat the same error.
    if errors:
        return errors
    deadline = time.monotonic() + 270
    commands = [
        ['uv', 'run', 'python', 'manage.py', 'test', '--noinput'],
        ['uv', 'run', 'python', 'manage.py', 'check'],
        ['uv', 'run', 'python', 'manage.py', 'makemigrations', '--check', '--dry-run'],
    ]
    for command in commands:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            errors.append('Quality gate exceeded its 270s check budget.')
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
        errors = syntax_errors(edited_paths(data), cwd(data))
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
