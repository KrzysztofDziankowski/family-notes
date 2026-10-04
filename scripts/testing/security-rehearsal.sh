#!/bin/sh
# Only a harness-created PostgreSQL target; never a caller-supplied database.
set -eu
[ "${1:-}" = admin ] && [ "$#" -eq 1 ] || {
    echo 'usage: security-rehearsal.sh admin' >&2; exit 1;
}
command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1 || {
    echo 'FAIL: a working Docker daemon is required' >&2; exit 1;
}
command -v uv >/dev/null 2>&1 || { echo 'FAIL: uv is required' >&2; exit 1; }
REPO=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$REPO"
umask 077
# Snap-packaged Docker has a private /tmp; a user-owned home directory is visible.
REHEARSAL_DIR=$(mktemp -d "$HOME/family-notes-auth.XXXXXX")
REHEARSAL_CONTAINER=family-notes-auth-$(date +%s)-$$
cleanup() {
    docker rm -f -v "$REHEARSAL_CONTAINER" >/dev/null 2>&1 || true
    rm -rf "$REHEARSAL_DIR"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
REHEARSAL_PASSWORD=$(uv run python -c 'import secrets; print(secrets.token_hex(24))')
printf 'POSTGRES_PASSWORD=%s\n' "$REHEARSAL_PASSWORD" > "$REHEARSAL_DIR/container.env"
docker pull postgres:17 >/dev/null
REHEARSAL_IMAGE=$(docker image inspect postgres:17 --format '{{index .RepoDigests 0}}')
docker run -d --name "$REHEARSAL_CONTAINER" -p 127.0.0.1::5432 \
    --env-file "$REHEARSAL_DIR/container.env" "$REHEARSAL_IMAGE" >/dev/null
ready() {
    REHEARSAL_ATTEMPT=0
    until docker exec "$REHEARSAL_CONTAINER" pg_isready -U postgres >/dev/null 2>&1; do
        REHEARSAL_ATTEMPT=$((REHEARSAL_ATTEMPT + 1))
        [ "$REHEARSAL_ATTEMPT" -lt 30 ] || { echo 'FAIL: PostgreSQL readiness' >&2; return 1; }
        sleep 1
    done
    REHEARSAL_PORT=$(docker port "$REHEARSAL_CONTAINER" 5432/tcp | sed 's/^127\.0\.0\.1://')
    case "$REHEARSAL_PORT" in ''|*[!0-9]*) echo 'FAIL: invalid disposable port' >&2; return 1 ;; esac
    export DB_PORT="$REHEARSAL_PORT"
}
ready
# Nonsuperuser role owns only disposable application/test databases.
printf "CREATE ROLE auth_rehearsal LOGIN CREATEDB PASSWORD '%s';\nCREATE DATABASE auth_rehearsal OWNER auth_rehearsal;\n" \
    "$REHEARSAL_PASSWORD" | docker exec -i "$REHEARSAL_CONTAINER" psql -U postgres -v ON_ERROR_STOP=1 >/dev/null
export DJANGO_DEBUG=True DJANGO_AUTH_DB_CACHE=True DB_ENGINE=postgresql
export DB_HOST=127.0.0.1 DB_NAME=auth_rehearsal DB_USER=auth_rehearsal DB_PASSWORD="$REHEARSAL_PASSWORD"
export CLASSIFICATION_ENABLED=False EDUVULCAN_WORKER_ENABLED=False AUTH_REHEARSAL_REQUIRED=1
printf 'PostgreSQL image: %s\nSource: %s\n' "$REHEARSAL_IMAGE" "$(git rev-parse HEAD)"
docker exec "$REHEARSAL_CONTAINER" psql -U postgres -Atc 'SHOW server_version'
uv run python manage.py test family_notes.test_auth_security \
    family_notes.test_auth_cache_integration.DatabaseOperatorRecoveryTests \
    family_notes.test_auth_cache_integration.DatabaseCacheTests \
    family_notes.test_auth_cache_integration.DatabaseProcessIntegrationTests
uv run python manage.py migrate --noinput >/dev/null
uv run python - <<'PY'
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'family_notes.settings')
django.setup()
from django.core.cache import cache
cache.set('rehearsal_restart_sentinel', [1], 300)
PY
docker restart "$REHEARSAL_CONTAINER" >/dev/null
ready
uv run python - <<'PY'
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'family_notes.settings')
django.setup()
from django.core.cache import cache
assert cache.get('rehearsal_restart_sentinel') == [1]
cache.delete('rehearsal_restart_sentinel')
print('PASS: histories survive process and PostgreSQL restart')
PY
docker stop "$REHEARSAL_CONTAINER" >/dev/null
# No test database can be created with the server stopped; use Django's runner directly.
uv run python - <<'PY'
import django, os, unittest
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'family_notes.settings')
django.setup()
from django.test.utils import setup_test_environment
setup_test_environment()
from family_notes.test_auth_cache_integration import CacheUnavailableIntegrationTests
result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(CacheUnavailableIntegrationTests))
raise SystemExit(not result.wasSuccessful())
PY
printf 'PASS: disposable PostgreSQL authentication rehearsal; cleanup on exit\n'
