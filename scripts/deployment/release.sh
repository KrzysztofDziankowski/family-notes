#!/bin/sh
set -eu

fail() { echo "release: $*" >&2; }

# Callbacks isolate production commands so the orchestration contract can be
# exercised without privileged paths or services.
release_run() {
    release_commit=$1 repository=$2 releases=$3 git_callback=$4 uv_callback=$5
    helper_callback=$6 clock_callback=$7 permissions_callback=$8 helper_display=$9

    case "$release_commit" in
        [0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ;;
        *) fail "RELEASE_COMMIT must be a full lowercase 40-character Git SHA"; return 1 ;;
    esac

    gate_version=$($helper_callback gate-version) || { fail "release gate protocol check failed"; return 1; }
    [ "$gate_version" = 1 ] || { fail "unexpected release gate protocol: $gate_version"; return 1; }

    release_timestamp=$($clock_callback) || { fail "could not generate release timestamp"; return 1; }
    release_id="$release_timestamp-$(printf '%s' "$release_commit" | cut -c1-12)"
    release_dir="$releases/$release_id"
    activation_started=false
    cleanup_release() {
        if [ "$activation_started" = false ] && [ -d "$release_dir" ]; then
            "$git_callback" worktree-remove "$repository" "$release_dir" || true
        fi
    }
    trap cleanup_release EXIT
    trap 'exit 129' HUP
    trap 'exit 130' INT
    trap 'exit 143' TERM

    printf '[release=%s] Fetching %s\n' "$release_id" "$release_commit"
    "$git_callback" fetch "$repository"
    "$git_callback" verify-commit "$repository" "$release_commit" || { fail "commit is not available from origin: $release_commit"; return 1; }
    "$git_callback" verify-master "$repository" "$release_commit" || { fail "commit is not reachable from origin/master: $release_commit"; return 1; }
    printf '[release=%s] Creating release\n' "$release_id"
    "$git_callback" worktree-add "$repository" "$release_dir" "$release_commit"
    printf '[release=%s] Installing locked production dependencies\n' "$release_id"
    "$uv_callback" "$release_dir"
    "$permissions_callback" "$release_dir"
    printf '[release=%s] Running production checks\n' "$release_id"
    "$helper_callback" check "$release_id"
    printf '[release=%s] Creating the pre-release database backup\n' "$release_id"
    "$helper_callback" backup "$release_id"
    printf '[release=%s] Activating release\n' "$release_id"
    activation_started=true
    "$helper_callback" activate "$release_id"
    "$helper_callback" status
    printf '[release=%s] Waiting for database-backed readiness\n' "$release_id"
    if ! "$helper_callback" health; then
        fail "readiness exhausted for release $release_id"
        echo "The activated release and pre-release backup remain in place." >&2
        echo "Inspect service status: sudo -n $helper_display status" >&2
        echo "Inspect service logs: sudo -n $helper_display logs" >&2
        echo "Retry internal health: sudo -n $helper_display health" >&2
        return 1
    fi
    trap - EXIT HUP INT TERM
    printf '[release=%s] Deployment completed: %s (%s)\n' "$release_id" "$release_id" "$release_commit"
}

if [ "${RELEASE_SH_SOURCE_ONLY:-}" = 1 ]; then
    (return 0 2>/dev/null) || { echo "release: source-only mode requires sourcing" >&2; exit 1; }
    return 0
fi

REPOSITORY=/srv/family-notes/repository/project.git
RELEASES=/srv/family-notes/releases
DEPLOY_HELPER=/usr/local/sbin/family-notes-deploy
UV=/home/deploy/.local/bin/uv

production_git() {
    operation=$1 repository=$2
    shift 2
    case "$operation" in
        fetch) git --git-dir="$repository" fetch --prune origin ;;
        verify-commit) git --git-dir="$repository" cat-file -e "$1^{commit}" 2>/dev/null ;;
        verify-master) git --git-dir="$repository" merge-base --is-ancestor "$1" refs/heads/master ;;
        worktree-add) git --git-dir="$repository" worktree add --detach "$1" "$2" ;;
        worktree-remove) git --git-dir="$repository" worktree remove --force "$1" ;;
        *) return 1 ;;
    esac
}
production_uv() { (cd "$1" && "$UV" sync --locked --no-dev); }
production_helper() { sudo -n "$DEPLOY_HELPER" "$@"; }
production_clock() { date -u +%Y%m%dT%H%M%SZ; }
production_permissions() { chmod -R g+rX "$1"; }

[ "$#" -eq 1 ] || { fail "usage: $0 RELEASE_COMMIT"; exit 1; }
[ "$(id -un)" = deploy ] || { fail "run this script as deploy"; exit 1; }
[ -d "$REPOSITORY" ] || { fail "repository not found: $REPOSITORY"; exit 1; }
[ -x "$UV" ] || { fail "uv not found: $UV"; exit 1; }
[ -x "$DEPLOY_HELPER" ] || { fail "deployment helper not found: $DEPLOY_HELPER"; exit 1; }
release_run "$1" "$REPOSITORY" "$RELEASES" production_git production_uv \
    production_helper production_clock production_permissions "$DEPLOY_HELPER"
