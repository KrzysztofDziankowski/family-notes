#!/bin/sh
set -eu

TEST_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$TEST_DIR/../release-gate.sh"

TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT HUP INT TERM

fail() {
    printf 'FAIL: %s\n' "$*" >&2
    exit 1
}

assert_eq() {
    [ "$1" = "$2" ] || fail "$3 (expected '$1', got '$2')"
}

assert_contains() {
    grep -F "$1" "$2" >/dev/null || fail "$3"
}

new_case() {
    case_name=$1
    shift
    CASE_DIR="$TMP_DIR/$case_name"
    mkdir "$CASE_DIR"
    : >"$CASE_DIR/budgets"
    : >"$CASE_DIR/sleeps"
    printf '%s\n' "$@" >"$CASE_DIR/clocks"
    printf '0\n' >"$CASE_DIR/clock-index"
    printf '0\n' >"$CASE_DIR/probe-index"
}

set_probe_results() {
    printf '%s\n' "$@" >"$CASE_DIR/probe-results"
}

fake_clock() {
    clock_index=$(sed -n '1p' "$CASE_DIR/clock-index")
    clock_index=$((clock_index + 1))
    printf '%s\n' "$clock_index" >"$CASE_DIR/clock-index"
    sed -n "${clock_index}p" "$CASE_DIR/clocks"
}

fake_probe() {
    printf 'secret-probe-body\n'
    printf 'secret-probe-error\n' >&2
    printf '%s\n' "$1" >>"$CASE_DIR/budgets"
    probe_index=$(sed -n '1p' "$CASE_DIR/probe-index")
    probe_index=$((probe_index + 1))
    printf '%s\n' "$probe_index" >"$CASE_DIR/probe-index"
    probe_result=$(sed -n "${probe_index}p" "$CASE_DIR/probe-results")
    return "${probe_result:-1}"
}

fake_sleep() {
    printf '%s\n' "$1" >>"$CASE_DIR/sleeps"
    return "${FAKE_SLEEP_RESULT:-0}"
}

run_success() {
    release_gate_wait fake_probe fake_clock fake_sleep >"$CASE_DIR/output" 2>&1 \
        || fail "$1 should succeed"
}

run_failure() {
    if release_gate_wait fake_probe fake_clock fake_sleep >"$CASE_DIR/output" 2>&1; then
        fail "$1 should fail"
    fi
}

new_case immediate-success 100 100
set_probe_results 0
run_success immediate-success
assert_eq 1 "$(wc -l <"$CASE_DIR/budgets" | tr -d ' ')" "immediate success probe count"
assert_eq 0 "$(wc -l <"$CASE_DIR/sleeps" | tr -d ' ')" "immediate success sleep count"
assert_contains 'readiness gate started' "$CASE_DIR/output" "start evidence missing"
assert_contains 'readiness gate succeeded' "$CASE_DIR/output" "success evidence missing"

new_case transient-recovery 100 100 102 102
set_probe_results 7 0
run_success transient-recovery
assert_eq "30
28" "$(cat "$CASE_DIR/budgets")" "remaining budgets after retry"
assert_eq 2 "$(cat "$CASE_DIR/sleeps")" "normal retry cadence"
assert_contains 'readiness gate retrying' "$CASE_DIR/output" "retry evidence missing"

new_case last-legal-success 100 129
set_probe_results 0
run_success last-legal-success
assert_contains 'elapsed=29s' "$CASE_DIR/output" "last legal success not recorded"

new_case exact-deadline 100 130
set_probe_results 0
run_failure exact-deadline
assert_contains 'readiness gate exhausted' "$CASE_DIR/output" "deadline exhaustion missing"

new_case backward-clock 100 99
set_probe_results 0
run_failure backward-clock
assert_eq 1 "$(wc -l <"$CASE_DIR/budgets" | tr -d ' ')" "clock regression retried"

new_case transport-http-failures 100 100 102 102 104 104
set_probe_results 7 22 0
run_success transport-http-failures
assert_eq 3 "$(wc -l <"$CASE_DIR/budgets" | tr -d ' ')" "nonzero failures were not retried"

new_case clamped-sleep 100 129 130
set_probe_results 1
run_failure clamped-sleep
assert_eq 1 "$(cat "$CASE_DIR/sleeps")" "sleep was not clamped to remaining budget"

new_case failed-sleep 100 100 102 102
set_probe_results 1 0
FAKE_SLEEP_RESULT=1
run_failure failed-sleep
FAKE_SLEEP_RESULT=0
assert_eq 1 "$(wc -l <"$CASE_DIR/budgets" | tr -d ' ')" "failed sleep allowed another probe"
assert_contains 'readiness gate exhausted' "$CASE_DIR/output" "failed sleep exhaustion missing"

new_case post-sleep-backward-clock 100 100 99
set_probe_results 1
run_failure post-sleep-backward-clock
assert_eq 1 "$(wc -l <"$CASE_DIR/budgets" | tr -d ' ')" "post-sleep clock regression retried"
assert_contains 'readiness gate exhausted' "$CASE_DIR/output" "post-sleep regression exhaustion missing"

new_case deadline-exhaustion
: >"$CASE_DIR/clocks"
printf '0\n0\n' >>"$CASE_DIR/clocks"
deadline_second=2
while [ "$deadline_second" -lt 30 ]; do
    printf '%s\n%s\n' "$deadline_second" "$deadline_second" >>"$CASE_DIR/clocks"
    deadline_second=$((deadline_second + 2))
done
printf '30\n' >>"$CASE_DIR/clocks"
set_probe_results 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1
run_failure deadline-exhaustion
assert_eq 15 "$(wc -l <"$CASE_DIR/budgets" | tr -d ' ')" "deadline probe count"
assert_eq 15 "$(wc -l <"$CASE_DIR/sleeps" | tr -d ' ')" "deadline sleep count"

new_case no-retry-after-success 200 200 999
set_probe_results 0 1
run_success no-retry-after-success
assert_eq 1 "$(wc -l <"$CASE_DIR/budgets" | tr -d ' ')" "probe ran after success"
assert_eq 2 "$(cat "$CASE_DIR/clock-index")" "clock ran after success"

for evidence_file in "$TMP_DIR"/*/output; do
    if grep -F 'secret-probe-' "$evidence_file" >/dev/null 2>&1; then
        fail "probe response or secret leaked into evidence"
    fi
done

printf 'PASS: release gate regression harness\n'
