#!/bin/sh
set -eu

TEST_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
HELPER="$TEST_DIR/../family-notes-deploy"
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT HUP INT TERM

FAMILY_NOTES_DEPLOY_SOURCE_ONLY=1
. "$HELPER"
unset FAMILY_NOTES_DEPLOY_SOURCE_ONLY
# Sourcing installed the probe's own traps; restore the harness cleanup.
trap 'rm -rf "$TMP_DIR"' EXIT HUP INT TERM

fail_test() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
assert_eq() { [ "$1" = "$2" ] || fail_test "$3 (expected '$1', got '$2')"; }
assert_contains() { grep -F -- "$1" "$2" >/dev/null || fail_test "$3"; }
assert_absent() { ! grep -F -- "$1" "$2" >/dev/null || fail_test "$3"; }

health_host=family.example.test

# Fake curl: records its arguments, writes FAKE_BODY to --output, prints
# FAKE_CODE for --write-out, and exits with FAKE_CURL_RESULT.
curl() {
    printf '%s\n' "$*" >>"$TMP_DIR/curl-calls"
    fake_output=
    fake_write_out=false
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --output) fake_output=$2; shift ;;
            --write-out) fake_write_out=true; shift ;;
        esac
        shift
    done
    [ -z "$fake_output" ] || printf '%s' "$FAKE_BODY" >"$fake_output"
    [ "$fake_write_out" = false ] || printf '%s' "$FAKE_CODE"
    return "${FAKE_CURL_RESULT:-0}"
}

new_case() {
    CASE_NAME=$1
    : >"$TMP_DIR/curl-calls"
    FAKE_BODY=$2 FAKE_CODE=$3 FAKE_CURL_RESULT=${4:-0}
}

run_database_probe() {
    if health_probe 30 >"$TMP_DIR/output" 2>&1; then echo 0; else echo 1; fi
}

run_conversion_probe() {
    if conversion_health_probe 10 >"$TMP_DIR/output" 2>&1; then echo 0; else echo 1; fi
}

# --- /healthz/ release gate probe keeps its exact-body contract -------------

new_case gate-ok '{"status": "ok"}' 200
assert_eq 0 "$(run_database_probe)" "gate probe must accept the exact body"
assert_contains 'http://localhost/healthz/' "$TMP_DIR/curl-calls" "gate probe URL changed"
assert_absent 'healthz/conversion' "$TMP_DIR/curl-calls" "gate probe must not check conversion"
assert_contains '--fail' "$TMP_DIR/curl-calls" "gate probe must fail on HTTP errors"
assert_contains 'Host: family.example.test' "$TMP_DIR/curl-calls" "gate probe host header missing"

for body in '{"status":"ok"}' '{"status": "disabled"}' '{"status": "ok"} ' 'ok'; do
    new_case gate-body "$body" 200
    assert_eq 1 "$(run_database_probe)" "gate probe accepted a non-exact body: $body"
done

new_case gate-transport '{"status": "ok"}' 000 7
assert_eq 1 "$(run_database_probe)" "gate probe ignored a curl failure"

# --- /healthz/conversion/ probe ---------------------------------------------

new_case conversion-ok '{"status": "ok"}' 200
assert_eq 0 "$(run_conversion_probe)" "healthy conversion should pass"
assert_eq 'conversion health: ok' "$(cat "$TMP_DIR/output")" "healthy conversion output"
assert_contains 'http://localhost/healthz/conversion/' "$TMP_DIR/curl-calls" "conversion probe URL"
assert_contains '--unix-socket /run/family-notes/gunicorn.sock' "$TMP_DIR/curl-calls" "conversion probe socket"
assert_contains 'X-Forwarded-Proto: https' "$TMP_DIR/curl-calls" "conversion probe scheme header"
assert_contains '--max-time 10' "$TMP_DIR/curl-calls" "conversion probe budget"

new_case conversion-disabled '{"status": "disabled"}' 200
assert_eq 0 "$(run_conversion_probe)" "disabled conversion is an explicit, healthy state"
assert_eq 'conversion health: disabled' "$(cat "$TMP_DIR/output")" "disabled conversion output"

new_case conversion-unavailable '{"status": "unavailable"}' 503
assert_eq 1 "$(run_conversion_probe)" "stale conversion must fail"
assert_eq 'conversion health: unavailable' "$(cat "$TMP_DIR/output")" "stale conversion output"

new_case conversion-code-mismatch '{"status": "ok"}' 503
assert_eq 1 "$(run_conversion_probe)" "an ok body with a 503 must fail"
assert_eq 'conversion health: unexpected' "$(cat "$TMP_DIR/output")" "code mismatch output"

new_case conversion-leak '{"status": "ok", "detail": "secret-probe-body"}' 200
assert_eq 1 "$(run_conversion_probe)" "an unexpected body must fail"
assert_eq 'conversion health: unexpected' "$(cat "$TMP_DIR/output")" "unexpected body output"
assert_absent 'secret-probe-body' "$TMP_DIR/output" "conversion probe printed the response body"

new_case conversion-transport '' '' 7
assert_eq 1 "$(run_conversion_probe)" "a transport failure must fail"
assert_eq 'conversion health: unexpected' "$(cat "$TMP_DIR/output")" "transport failure output"

new_case conversion-budget '{"status": "ok"}' 200
if conversion_health_probe 0 >/dev/null 2>&1; then fail_test "a zero budget must fail"; fi
assert_eq 0 "$(wc -l <"$TMP_DIR/curl-calls" | tr -d ' ')" "a zero budget still probed"

# --- The source-only switch cannot bypass the installed helper -------------

if FAMILY_NOTES_DEPLOY_SOURCE_ONLY=1 sh "$HELPER" gate-version >"$TMP_DIR/output" 2>&1; then
    fail_test "executing with the source-only switch must fail"
fi
assert_contains 'source-only mode requires sourcing' "$TMP_DIR/output" "source-only refusal message"

# Every action, including conversion-health, still requires the matched library.
if [ ! -e "$RELEASE_GATE_LIBRARY" ]; then
    if sh "$HELPER" conversion-health >"$TMP_DIR/output" 2>&1; then
        fail_test "conversion-health ran without the release gate library"
    fi
    assert_contains 'release gate library is unavailable' "$TMP_DIR/output" "library guard missing"
fi

# The reset invokes one fixed command in the current release only.
(
    CURRENT="$TMP_DIR/current"
    RELEASES="$TMP_DIR/releases"
    RESET_ID=20261004T120000Z-0123456789ab
    mkdir -p "$RELEASES/$RESET_ID"
    ln -s "$RELEASES/$RESET_ID" "$CURRENT"
    validate_release() {
        [ "$1" = "$RESET_ID" ] || fail_test 'reset selected another release'
        release_dir="$RELEASES/$1"
    }
    load_environment() { :; }
    run_manage() { printf '%s\n' "$@" >"$TMP_DIR/reset-args"; }
    reset_admin_login 42 2001:db8::1
    printf '%s\n' "$RELEASES/$RESET_ID" reset_admin_login_limits \
        --user-id 42 --client-ip 2001:db8::1 >"$TMP_DIR/expected-reset-args"
    cmp -s "$TMP_DIR/reset-args" "$TMP_DIR/expected-reset-args" \
        || fail_test 'reset invocation is not fixed/current-only'
    for bad_id in 0 01 -1 '1;id' '--help'; do
        if (reset_admin_login "$bad_id" 192.0.2.1) >/dev/null 2>&1; then
            fail_test 'reset accepted an invalid ID'
        fi
    done
    for bad_ip in '--help' '127.0.0.1;id' '$(id)' ''; do
        if (reset_admin_login 42 "$bad_ip") >/dev/null 2>&1; then
            fail_test 'reset accepted an unsafe IP argument'
        fi
    done
    if (reset_admin_login 42 192.0.2.1 extra) >/dev/null 2>&1; then
        fail_test 'reset accepted extra arguments'
    fi
    rm "$CURRENT"
    ln -s /tmp/untrusted-release "$CURRENT"
    if (reset_admin_login 42 192.0.2.1) >/dev/null 2>&1; then
        fail_test 'reset accepted an external current target'
    fi
)

printf 'PASS: deployment helper probe and restricted reset harness\n'
