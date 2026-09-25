#!/bin/sh
set -eu

TEST_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT HUP INT TERM
mkdir "$TMP_DIR/releases"

RELEASE_SH_SOURCE_ONLY=1
. "$TEST_DIR/../release.sh"
unset RELEASE_SH_SOURCE_ONLY

mock_git() {
    printf 'git:%s\n' "$1" >>"$TMP_DIR/calls"
    [ "$1" != worktree-add ] || mkdir "$3"
}

mock_uv() {
    printf 'uv\n' >>"$TMP_DIR/calls"
}

mock_helper() {
    printf 'helper:%s\n' "$1" >>"$TMP_DIR/calls"
    [ "$1" != gate-version ] || printf '1\n'
}

mock_clock() {
    printf '20260925T120000Z\n'
}

mock_permissions() {
    printf 'permissions\n' >>"$TMP_DIR/calls"
}

: >"$TMP_DIR/calls"
release_run \
    0123456789abcdef0123456789abcdef01234567 \
    "$TMP_DIR/repository" \
    "$TMP_DIR/releases" \
    mock_git \
    mock_uv \
    mock_helper \
    mock_clock \
    mock_permissions \
    /fixed/family-notes-deploy \
    >"$TMP_DIR/output" 2>&1

printf '%s\n' '--- Stage output ---'
cat "$TMP_DIR/output"

printf '%s\n' '--- Callback trace ---'
cat "$TMP_DIR/calls"

if grep -E 'secret|password|response body|helper:logs' \
    "$TMP_DIR/output" "$TMP_DIR/calls"; then
    printf '%s\n' 'FAIL: sensitive or automatic-log output detected' >&2
    exit 1
fi

printf '%s\n' 'PASS: manual rehearsal output is clean'
