#!/bin/sh
set -eu

REPOSITORY=/srv/family-notes/repository/project.git
RELEASES=/srv/family-notes/releases
DEPLOY_HELPER=/usr/local/sbin/family-notes-deploy
UV=/home/deploy/.local/bin/uv

fail() {
    echo "release: $*" >&2
    exit 1
}

if [ "$#" -ne 1 ]; then
    fail "usage: $0 RELEASE_COMMIT"
fi

[ "$(id -un)" = deploy ] || fail "run this script as deploy"
[ -d "$REPOSITORY" ] || fail "repository not found: $REPOSITORY"
[ -x "$UV" ] || fail "uv not found: $UV"
[ -x "$DEPLOY_HELPER" ] || fail "deployment helper not found: $DEPLOY_HELPER"

release_commit=$1
case "$release_commit" in
    [0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ;;
    *) fail "RELEASE_COMMIT must be a full lowercase 40-character Git SHA" ;;
esac

release_id="$(date -u +%Y%m%dT%H%M%SZ)-$(printf '%s' "$release_commit" | cut -c1-12)"
release_dir="$RELEASES/$release_id"
activation_started=false

cleanup() {
    if [ "$activation_started" = false ] && [ -d "$release_dir" ]; then
        git --git-dir="$REPOSITORY" worktree remove --force "$release_dir" || true
    fi
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

echo "Fetching $release_commit"
git --git-dir="$REPOSITORY" fetch --prune origin
git --git-dir="$REPOSITORY" cat-file -e "$release_commit^{commit}" 2>/dev/null \
    || fail "commit is not available from origin: $release_commit"
git --git-dir="$REPOSITORY" merge-base --is-ancestor "$release_commit" refs/heads/master \
    || fail "commit is not reachable from origin/master: $release_commit"

echo "Creating release $release_id"
git --git-dir="$REPOSITORY" worktree add --detach "$release_dir" "$release_commit"

echo "Installing locked production dependencies"
(
    cd "$release_dir"
    "$UV" sync --locked --no-dev
)
chmod -R g+rX "$release_dir"

echo "Running production checks"
sudo -n "$DEPLOY_HELPER" check "$release_id"

echo "Creating the pre-release database backup"
sudo -n "$DEPLOY_HELPER" backup "$release_id"

echo "Activating $release_id"
activation_started=true
sudo -n "$DEPLOY_HELPER" activate "$release_id"

sudo -n "$DEPLOY_HELPER" status
sudo -n "$DEPLOY_HELPER" health

trap - EXIT HUP INT TERM
echo "Deployment completed: $release_id ($release_commit)"
