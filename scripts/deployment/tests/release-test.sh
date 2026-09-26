#!/bin/sh
set -eu

TEST_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
RELEASE_SH_SOURCE_ONLY=1
. "$TEST_DIR/../release.sh"
unset RELEASE_SH_SOURCE_ONLY
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT HUP INT TERM

fail_test() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
assert_contains() { grep -F "$1" "$2" >/dev/null || fail_test "$3"; }
assert_absent() { ! grep -F "$1" "$2" >/dev/null || fail_test "$3"; }
SHA=0123456789abcdef0123456789abcdef01234567

new_case() {
    CASE_DIR="$TMP_DIR/$1"
    mkdir -p "$CASE_DIR/releases"
    : >"$CASE_DIR/calls"
}
fake_git() {
    printf 'git:%s\n' "$1" >>"$CASE_DIR/calls"
    if [ "$1" = worktree-add ]; then mkdir "$3"; fi
    if [ "$1" = worktree-remove ]; then printf 'rollback\n' >>"$CASE_DIR/calls"; fi
}
fake_uv() { printf 'uv\n' >>"$CASE_DIR/calls"; }
fake_permissions() { printf 'permissions\n' >>"$CASE_DIR/calls"; }
fake_clock() { printf '20260925T120000Z\n'; }
fake_helper() {
    printf 'helper:%s\n' "$1" >>"$CASE_DIR/calls"
    case "$1" in
        gate-version)
            [ "${FAKE_GATE_RESULT:-0}" -eq 0 ] || return "$FAKE_GATE_RESULT"
            printf '%s\n' "${FAKE_GATE_VERSION-1}"
            ;;
        health)
            assert_absent 'Deployment completed:' "$CASE_DIR/output" \
                'completion was printed before readiness succeeded'
            return "${FAKE_HEALTH_RESULT:-0}"
            ;;
    esac
}

new_case missing-version
FAKE_GATE_RESULT=1
if release_run "$SHA" "$CASE_DIR/repository" "$CASE_DIR/releases" fake_git fake_uv \
    fake_helper fake_clock fake_permissions /fixed/helper >"$CASE_DIR/output" 2>&1; then
    fail_test 'missing protocol should fail'
fi
assert_absent 'git:' "$CASE_DIR/calls" 'missing protocol mutated release state'

new_case incompatible-version
FAKE_GATE_RESULT=0 FAKE_GATE_VERSION=2
if release_run "$SHA" "$CASE_DIR/repository" "$CASE_DIR/releases" fake_git fake_uv \
    fake_helper fake_clock fake_permissions /fixed/helper >"$CASE_DIR/output" 2>&1; then
    fail_test 'incompatible protocol should fail'
fi
assert_absent 'git:' "$CASE_DIR/calls" 'protocol mismatch mutated release state'

new_case empty-version
FAKE_GATE_VERSION=
if release_run "$SHA" "$CASE_DIR/repository" "$CASE_DIR/releases" fake_git fake_uv \
    fake_helper fake_clock fake_permissions /fixed/helper >"$CASE_DIR/output" 2>&1; then
    fail_test 'empty protocol should fail'
fi
assert_absent 'git:' "$CASE_DIR/calls" 'empty protocol mutated release state'

new_case readiness-failure
FAKE_GATE_VERSION=1 FAKE_HEALTH_RESULT=1
if release_run "$SHA" "$CASE_DIR/repository" "$CASE_DIR/releases" fake_git fake_uv \
    fake_helper fake_clock fake_permissions /fixed/helper >"$CASE_DIR/output" 2>&1; then
    fail_test 'exhausted readiness should fail'
fi
assert_contains 'helper:activate' "$CASE_DIR/calls" 'release was not activated'
assert_contains 'helper:health' "$CASE_DIR/calls" 'readiness was not invoked'
assert_absent 'rollback' "$CASE_DIR/calls" 'readiness failure invoked rollback'
assert_absent 'Deployment completed:' "$CASE_DIR/output" 'failure printed completion'
assert_contains 'activated release and pre-release backup remain in place' "$CASE_DIR/output" 'production state guidance missing'
assert_contains 'sudo -n /fixed/helper status' "$CASE_DIR/output" 'status guidance missing'
assert_contains 'sudo -n /fixed/helper logs' "$CASE_DIR/output" 'logs guidance missing'
assert_contains 'sudo -n /fixed/helper health' "$CASE_DIR/output" 'health guidance missing'

new_case readiness-success
FAKE_HEALTH_RESULT=0
release_run "$SHA" "$CASE_DIR/repository" "$CASE_DIR/releases" fake_git fake_uv \
    fake_helper fake_clock fake_permissions /fixed/helper >"$CASE_DIR/output" 2>&1 \
    || fail_test 'healthy release should succeed'
assert_contains 'Deployment completed:' "$CASE_DIR/output" 'success completion missing'
call_order=$(cat "$CASE_DIR/calls")
case "$call_order" in
    *helper:activate*helper:status*helper:health*) ;;
    *) fail_test 'activation, restart/status, and readiness ordering is wrong' ;;
esac

printf 'PASS: release orchestration harness\n'
