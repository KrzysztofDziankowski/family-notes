#!/bin/sh

# Protocol shared by the installed readiness library and privileged helper.
RELEASE_GATE_PROTOCOL_VERSION=1

release_gate_exhausted() {
    release_gate_time=$1
    printf '[epoch=%s] readiness gate exhausted\n' "$release_gate_time" >&2
    return 1
}

release_gate_valid_time() {
    case $1 in
        ''|*[!0-9]*) return 1 ;;
        *) return 0 ;;
    esac
}

# Usage: release_gate_wait PROBE_CALLBACK CLOCK_CALLBACK SLEEP_CALLBACK
#
# The callbacks are supplied by a trusted caller. CLOCK_CALLBACK prints epoch
# seconds, PROBE_CALLBACK accepts the remaining whole-second budget, and
# SLEEP_CALLBACK accepts a whole-second delay.
release_gate_wait() {
    release_gate_probe=$1
    release_gate_clock=$2
    release_gate_sleep=$3

    release_gate_started=$($release_gate_clock) || {
        release_gate_exhausted unknown
        return 1
    }
    release_gate_valid_time "$release_gate_started" || {
        release_gate_exhausted unknown
        return 1
    }

    release_gate_before=$release_gate_started
    release_gate_previous=$release_gate_started
    printf '[epoch=%s] readiness gate started (deadline=30s)\n' "$release_gate_started" >&2

    while :; do
        if [ "$release_gate_before" -lt "$release_gate_previous" ]; then
            release_gate_exhausted "$release_gate_before"
            return 1
        fi

        release_gate_elapsed=$((release_gate_before - release_gate_started))
        if [ "$release_gate_elapsed" -ge 30 ]; then
            release_gate_exhausted "$release_gate_before"
            return 1
        fi
        release_gate_budget=$((30 - release_gate_elapsed))

        # Probe output is deliberately discarded: the gate records state
        # transitions, never response bodies, transport details, or secrets.
        if "$release_gate_probe" "$release_gate_budget" >/dev/null 2>&1; then
            release_gate_probe_ok=true
        else
            release_gate_probe_ok=false
        fi

        release_gate_after=$($release_gate_clock) || {
            release_gate_exhausted unknown
            return 1
        }
        release_gate_valid_time "$release_gate_after" || {
            release_gate_exhausted unknown
            return 1
        }
        if [ "$release_gate_after" -lt "$release_gate_before" ]; then
            release_gate_exhausted "$release_gate_after"
            return 1
        fi

        release_gate_elapsed=$((release_gate_after - release_gate_started))
        if [ "$release_gate_probe_ok" = true ] && [ "$release_gate_elapsed" -lt 30 ]; then
            printf '[epoch=%s] readiness gate succeeded (elapsed=%ss)\n' \
                "$release_gate_after" "$release_gate_elapsed" >&2
            return 0
        fi
        if [ "$release_gate_elapsed" -ge 30 ]; then
            release_gate_exhausted "$release_gate_after"
            return 1
        fi

        release_gate_remaining=$((30 - release_gate_elapsed))
        release_gate_delay=2
        if [ "$release_gate_remaining" -lt "$release_gate_delay" ]; then
            release_gate_delay=$release_gate_remaining
        fi
        printf '[epoch=%s] readiness gate retrying in %ss (remaining=%ss)\n' \
            "$release_gate_after" "$release_gate_delay" "$release_gate_remaining" >&2
        if ! "$release_gate_sleep" "$release_gate_delay"; then
            release_gate_exhausted "$release_gate_after"
            return 1
        fi

        release_gate_before=$($release_gate_clock) || {
            release_gate_exhausted unknown
            return 1
        }
        release_gate_valid_time "$release_gate_before" || {
            release_gate_exhausted unknown
            return 1
        }
        if [ "$release_gate_before" -lt "$release_gate_after" ]; then
            release_gate_exhausted "$release_gate_before"
            return 1
        fi
        release_gate_previous=$release_gate_after
    done
}
