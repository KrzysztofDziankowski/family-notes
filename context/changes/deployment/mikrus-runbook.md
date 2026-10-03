# FamilyNotes First Deployment on Mikr.us

This is the operator checklist for the first production deployment. Run local
commands on the development machine and server commands after connecting to the
Mikrus VPS. Replace every value written as `<LIKE_THIS>` before running a command.

The public URL uses the dedicated Mikrus subdomain `familynotes.mikrus.dev`.
Mikrus terminates HTTPS for the user and forwards plain HTTP to nginx on one of
the VPS's assigned ports. Do not install Certbot for this setup.

## Deployment Progress

Updated 2026-09-26:

- [x] Application pre-deployment readiness implemented locally
- [x] Steps 1-6 completed on Mikrus (reported by the operator)
- [x] Step 7: first versioned release created and validated
- [x] Step 8: systemd service configured and running
- [x] Step 9: nginx serving HTTP on port `20121` behind Mikrus HTTPS
- [x] Step 10: production deployment verified (reported by the operator)
- [x] Dedicated public hostname changed to `familynotes.mikrus.dev`
- [x] Matched release-gate library and helper (protocol `1`) installed through the
  provider console
- [x] Release gate acceptance recorded (approved release and failed-probe
  rehearsal; reported by the operator)

### First Deployment Record

The operator confirmed a successful production deployment on 2026-09-21:

| Item | Deployed value |
| --- | --- |
| Public URL | `https://familynotes.mikrus.dev/` |
| VPS | `ula121` |
| Internal nginx listener | HTTP on `[::]:20121` |
| Release | `20260921T203945Z-ea1ff26284aa` |
| Application service | `family-notes.service` using Gunicorn 26.2.0 |
| Application socket | `/run/family-notes/gunicorn.sock` |
| Database | Dedicated Mikrus PostgreSQL with restricted application credentials |
| TLS | Terminated by the Mikrus subdomain frontend |

The final deployment required `--no-control-socket` for Gunicorn and explicit
nginx proxy headers to avoid contradictory HTTP/HTTPS scheme values. Those fixes
are incorporated in this runbook for subsequent releases.

## 0. Application Readiness

The application now provides:

- `STATIC_ROOT` controlled by `DJANGO_STATIC_ROOT`
- proxy-aware HTTPS, secure production cookies, SSL redirect, and HSTS settings
- a database-backed `/healthz/` endpoint with detail-free failure responses
- Google authentication configured through environment variables, with
  `/account/` as the protected membership-status route
- `/admin/` as an intentionally enabled, superuser-only setup surface
- the Git `origin` remote used to publish commits for the Mikrus repository mirror

Before step 7, commit and push these deployment changes, then use that exact full
commit SHA as `<RELEASE_COMMIT>`. Review the output of
`uv run python manage.py check --deploy` under production settings before exposing
the app publicly.

With the `mikrus.dev` host, Django's deployment check is expected to warn
about `SECURE_HSTS_INCLUDE_SUBDOMAINS` and `SECURE_HSTS_PRELOAD`. Leave both off:
the parent domain is shared with other Mikrus users and is not controlled by
FamilyNotes. The application still sends HSTS for its own host through
`SECURE_HSTS_SECONDS`.

## 1. Record Values from the Mikrus Panel

Create a private password-manager entry, not a repository file, with:

| Runbook name | Value from Mikrus |
| --- | --- |
| `<SERVER_NAME>` | VPS name, for example `srv123` |
| `<SERVER_ID>` | numeric VPS ID |
| `<SSH_HOST>` | SSH hostname shown in the panel |
| `<SSH_PORT>` | normally `10000 + SERVER_ID` |
| `<APP_PORT>` | `20121` |
| `<PUBLIC_HOST>` | `familynotes.mikrus.dev` |
| `<DB_HOST>` | dedicated PostgreSQL hostname |
| `<DB_PORT>` | dedicated PostgreSQL port, commonly `5432` |
| `<DB_SSLMODE>` | TLS mode required by Mikrus, preferably `require` |
| `<DB_ADMIN_USER>` | administrative login supplied with the service |
| `<DB_NAME>` | `family_notes` unless Mikrus pre-created a fixed database |
| `<DB_USER>` | `family_notes_app` unless Mikrus pre-created a fixed login |
| `<DB_PASSWORD>` | new password for the application login |
| `<GOOGLE_OAUTH_CLIENT_ID>` | Google OAuth web client ID for FamilyNotes |
| `<GOOGLE_OAUTH_CLIENT_SECRET>` | Google OAuth web client secret for FamilyNotes |
| `<REPOSITORY_URL>` | HTTPS or SSH Git clone URL |
| `<RELEASE_COMMIT>` | full Git commit SHA approved for release |

In the Mikrus panel:

1. Open the purchased dedicated PostgreSQL service in the Mikrus panel. Copy its
   hostname, port, TLS requirement, administrative login, and administrative
   password into the password manager. Do not save admin credentials in Django's
   environment file.
2. Confirm port `20121` is in the assigned port pool. Additional TCP ports can
   be requested in the panel if both general-purpose ports are occupied.
3. In the Mikrus subdomain panel, assign `familynotes.mikrus.dev` to this VPS,
   select port `20121`, and use plain HTTP for the backend protocol. Open
   `https://<PUBLIC_HOST>/` only after nginx is configured and the subdomain is
   active.
4. Request Strych access in the panel's **Backup** section. This provides 200 MB
   of shared backup space; it is not the only backup destination.

## 2. Configure SSH on the Development Machine

Generate a dedicated key if one does not already exist:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/familynotes_mikrus -C familynotes-mikrus
```

Add this host entry to `~/.ssh/config`:

```sshconfig
Host familynotes-mikrus
    HostName <SSH_HOST>
    Port <SSH_PORT>
    User root
    IdentityFile ~/.ssh/familynotes_mikrus
    IdentitiesOnly yes
```

Install the public key using the initial password supplied by Mikrus:

```bash
ssh-copy-id -i ~/.ssh/familynotes_mikrus.pub familynotes-mikrus
ssh familynotes-mikrus
```

Keep the current root session open while testing any SSH configuration change.
Provider console access is the recovery path if SSH stops working.

On the current production VPS, direct root SSH from the development machine is
unavailable: root login rejects the available identity. Every root-only task,
including installing or updating the deployment helper and release-gate library,
requires the account owner to use the Mikrus provider console or another
explicitly authorized root-capable path. Do not broaden the `deploy` account's
sudo rule as a workaround.

## 3. Bootstrap the VPS as Root

Inspect the operating system, available storage, and memory first:

```bash
cat /etc/os-release
df -h
free -h
```

Install system packages:

```bash
apt update
apt upgrade
apt install -y ca-certificates curl git nginx libpq-dev postgresql-client python3-dev
```

Create separate deployment and runtime users:

```bash
adduser --disabled-password --gecos '' deploy
useradd --system --home-dir /srv/family-notes --shell /usr/sbin/nologin familynotes
install -d -o deploy -g familynotes -m 2775 /srv/family-notes/releases
install -d -o deploy -g familynotes -m 2775 /srv/family-notes/repository
install -d -o familynotes -g familynotes -m 0755 /var/www/family-notes/static
install -d -o root -g root -m 0700 /etc/family-notes
usermod -aG familynotes deploy
```

Install the repository-owned release-gate library and deployment helper as a
matched root-owned pair. Direct root SSH from the development machine is no
longer available: root login rejects the available identity, so this and every
later helper update must run as root in the Mikrus provider console (or another
owner-authorized root-capable path). Follow
[Install or Update the Release Gate Pair](#install-or-update-the-release-gate-pair).
On a fresh server, first install the `deploy` SSH key (below) so the files can be
staged over SSH, and skip the commands that retain or restore previously
installed artifacts because none exist yet. Validate the installed pair before
granting sudo access. After the pair is installed, routine deployments do not
require root access.

Allow `deploy` to invoke only this validated helper as root:

```bash
visudo -f /etc/sudoers.d/family-notes-deploy
```

Insert exactly:

```sudoers
deploy ALL=(root) NOPASSWD: /usr/local/sbin/family-notes-deploy
```

Validate the sudoers file before ending the root session:

```bash
chmod 0440 /etc/sudoers.d/family-notes-deploy
visudo -cf /etc/sudoers.d/family-notes-deploy
```

Install the same SSH public key for `deploy`:

```bash
install -d -o deploy -g deploy -m 0700 /home/deploy/.ssh
cp /root/.ssh/authorized_keys /home/deploy/.ssh/authorized_keys
chown deploy:deploy /home/deploy/.ssh/authorized_keys
chmod 0600 /home/deploy/.ssh/authorized_keys
```

Change the local SSH host entry from `User root` to `User deploy`, then verify a
new connection before closing the root session:

```bash
ssh familynotes-mikrus
sudo -n /usr/local/sbin/family-notes-deploy status
```

The status command may report that the unit does not exist; successful sudo
authorization is what matters at this point. Confirm that unrestricted sudo is
denied with `sudo -n true`; do not grant `deploy` direct access to the production
environment file or general root commands.

## 4. Install uv and Prepare Repository Access

Run as `deploy`:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
~/.local/bin/uv --version
git clone --mirror git@github.com:KrzysztofDziankowski/family-notes.git /srv/family-notes/repository/project.git
```

For a private SSH repository, create a read-only deploy key for the `deploy`
account and register its public half with the Git provider before cloning:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/familynotes_repo -C familynotes-mikrus-deploy
cat ~/.ssh/familynotes_repo.pub
```

Add a host entry selecting that key in `/home/deploy/.ssh/config`; do not copy a
developer's personal Git key onto the server.

## 5. Configure Dedicated Mikrus PostgreSQL

The selected database is the separately purchased dedicated PostgreSQL service,
not Mikrus shared PostgreSQL and not PostgreSQL installed on the application VPS.
Do not install the `postgresql` server package on the VPS. The
`postgresql-client` package installed in step 3 is sufficient.

### Confirm access from the VPS

Connect using the administrative details delivered with the purchased service:

```bash
psql 'host=<DB_HOST> port=<DB_PORT> dbname=postgres user=<DB_ADMIN_USER> sslmode=<DB_SSLMODE>'
```

Enter the administrative password at the prompt. Do not place it in the command
or `/etc/family-notes/env`. In `psql`, inspect the server and current privileges:

```sql
SELECT version();
SELECT current_user, current_database();
SELECT rolcreatedb, rolcreaterole
FROM pg_roles
WHERE rolname = current_user;
```

If `rolcreatedb` and `rolcreaterole` are both `true`, create the dedicated
FamilyNotes role and database below. If either required privilege is `false`,
use the Mikrus panel to create them or ask Mikrus support to provision database
`family_notes` owned by login `family_notes_app`; do not grant the application
administrative privileges as a workaround.

### Create the application role and database

Still in the administrative `psql` session, create a login without database or
role administration privileges:

```sql
CREATE ROLE family_notes_app
    WITH LOGIN
    NOSUPERUSER
    NOCREATEDB
    NOCREATEROLE
    NOINHERIT
    NOREPLICATION;
\password family_notes_app
```

At the password prompts, enter a new random password generated in your password
manager. The `\password` command avoids putting the plaintext password in SQL
history. Save it as `<DB_PASSWORD>` in the password manager.

Create a UTF-8 database owned by that role and remove default public access:

```sql
CREATE DATABASE family_notes
    WITH OWNER family_notes_app
    ENCODING 'UTF8'
    TEMPLATE template0;
REVOKE ALL ON DATABASE family_notes FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE family_notes TO family_notes_app;
\q
```

If Mikrus supplied a fixed database or application login with the dedicated
service, do not try to recreate it. Record those supplied values as `<DB_NAME>`
and `<DB_USER>`, confirm that the login is not an administrator, and continue
with the verification below.

### Verify the application login

Connect from the VPS as the application user. The password is entered
interactively:

```bash
psql 'host=<DB_HOST> port=<DB_PORT> dbname=<DB_NAME> user=<DB_USER> sslmode=<DB_SSLMODE>'
```

Verify identity, privileges, storage visibility, and object creation:

```sql
SELECT current_user, current_database();
SELECT rolsuper, rolcreatedb, rolcreaterole
FROM pg_roles
WHERE rolname = current_user;
SELECT pg_size_pretty(pg_database_size(current_database()));
CREATE TABLE deployment_permission_test (id integer PRIMARY KEY);
DROP TABLE deployment_permission_test;
\q
```

The three role flags must all be `false`, and both table statements must succeed.
If the connection fails, verify the dedicated service's host, port, TLS mode, and
network allow-list in the Mikrus panel. Allow only the application VPS where the
service supports source restrictions; do not expose PostgreSQL publicly for
developer access.

## 6. Create the Production Environment File

Generate a secret on the VPS using Python's standard library. This command does
not require Django or an initialized project environment:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(50))"
```

On the VPS, open the environment file as root:

```bash
sudoedit /etc/family-notes/env
```

Insert real values. Environment files use plain `KEY=value` syntax; quote a
value with double quotes if it contains spaces or `#`:

```dotenv
DJANGO_SECRET_KEY=<GENERATED_PRODUCTION_SECRET>
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=<PUBLIC_HOST>
DJANGO_CSRF_TRUSTED_ORIGINS=https://<PUBLIC_HOST>
DJANGO_STATIC_ROOT=/var/www/family-notes/static
DB_ENGINE=postgresql
DB_HOST=<DB_HOST>
DB_PORT=<DB_PORT>
DB_SSLMODE=<DB_SSLMODE>
DB_NAME=<DB_NAME>
DB_USER=<DB_USER>
DB_PASSWORD=<DB_PASSWORD>
GOOGLE_OAUTH_CLIENT_ID=<GOOGLE_OAUTH_CLIENT_ID>
GOOGLE_OAUTH_CLIENT_SECRET=<GOOGLE_OAUTH_CLIENT_SECRET>
```

Register `https://<PUBLIC_HOST>/accounts/google/login/callback/` as the authorized
Google OAuth redirect URI. Keep the real client ID and secret only in this
protected file and the password manager. Do not add placeholder AI values:
natural-language classification stays disabled by default and its variables are
added only through [Enable Classification](#enable-classification). Before deploying authentication, confirm
that both Google variables are populated with the production web client values
without printing them. Protect the file:

```bash
sudo chown root:root /etc/family-notes/env
sudo chmod 0600 /etc/family-notes/env
```

## 7. Create the First Versioned Release

Run as `deploy` and use the full approved commit SHA:

```bash
RELEASE_ID="$(date -u +%Y%m%dT%H%M%SZ)-$(printf '%s' '<RELEASE_COMMIT>' | cut -c1-12)"
git --git-dir=/srv/family-notes/repository/project.git fetch --prune origin
git --git-dir=/srv/family-notes/repository/project.git worktree add --detach "/srv/family-notes/releases/$RELEASE_ID" '<RELEASE_COMMIT>'
cd "/srv/family-notes/releases/$RELEASE_ID"
~/.local/bin/uv sync --locked --no-dev
```

Allow the runtime user to read this release without making it writable:

```bash
chmod -R g+rX "/srv/family-notes/releases/$RELEASE_ID"
```

Run the protected pre-deploy checks through the deployment helper:

```bash
sudo -n /usr/local/sbin/family-notes-deploy check "$RELEASE_ID"
```

The helper passes the protected environment to the `familynotes` process; the
deployment account never receives direct read access to the secrets file.

Before the first migration, make and verify a database dump:

```bash
sudo -n /usr/local/sbin/family-notes-deploy backup "$RELEASE_ID"
```

## 8. Configure systemd

Return to the still-open root session. Create
`/etc/systemd/system/family-notes.service`:

```ini
[Unit]
Description=FamilyNotes Django application
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=familynotes
Group=familynotes
WorkingDirectory=/srv/family-notes/current
EnvironmentFile=/etc/family-notes/env
RuntimeDirectory=family-notes
RuntimeDirectoryMode=0755
ExecStart=/srv/family-notes/current/.venv/bin/gunicorn family_notes.wsgi:application --config gunicorn.conf.py --workers 2 --timeout 45 --bind unix:/run/family-notes/gunicorn.sock --no-control-socket --access-logfile - --error-logfile -
Restart=on-failure
RestartSec=5
PrivateTmp=true
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
```

`--config gunicorn.conf.py` loads the release's Gunicorn hooks from the
working directory. The file only adds hooks: the EduVulcan conversion worker
starts in each of the two worker processes when `EDUVULCAN_WORKER_ENABLED=True`
(see [Enable EduVulcan Conversion](#enable-eduvulcan-conversion)); the
command-line options above still decide workers, timeout, and binding. A unit
created before this option existed must be updated (`systemctl edit --full
family-notes`, then `systemctl daemon-reload`) before conversion is enabled.
Gunicorn also discovers `gunicorn.conf.py` in its working directory, but keep the
option explicit.

During the one-time bootstrap, enable the service without starting it:

```bash
systemctl daemon-reload
systemctl enable family-notes
```

Return to the `deploy` session and activate the release. The helper runs
migrations and static collection as `familynotes`, switches the `current`
symlink, restarts the service, and verifies that it is active:

```bash
sudo -n /usr/local/sbin/family-notes-deploy activate "$RELEASE_ID"
sudo -n /usr/local/sbin/family-notes-deploy status
```

If `collectstatic` fails because `STATIC_ROOT` is missing, stop and fix the app;
do not work around it by serving source directories.

## 9. Configure nginx and the Mikrus URL

Still as root, create `/etc/nginx/sites-available/family-notes`:

```nginx
server {
    listen [::]:20121 ipv6only=off;
    server_name <PUBLIC_HOST>;

    client_max_body_size 2m;

    location /static/ {
        alias /var/www/family-notes/static/;
        access_log off;
        expires 1h;
    }

    location / {
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_pass http://unix:/run/family-notes/gunicorn.sock;
        proxy_connect_timeout 5s;
        proxy_read_timeout 50s;
    }
}
```

Enable only the intended site and validate before reloading:

```bash
sudo ln -s /etc/nginx/sites-available/family-notes /etc/nginx/sites-enabled/family-notes
sudo rm /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl enable nginx
sudo systemctl reload nginx
```

The `listen [::]:20121 ipv6only=off` directive accepts both IPv6 and IPv4 traffic.
This nginx server is HTTP-only: do not add `ssl`, certificate paths, a port `443`
listener, or Certbot. Mikrus accepts public HTTPS for `<PUBLIC_HOST>` and forwards
plain HTTP to port `20121`, as configured for `familynotes.mikrus.dev` in the
subdomain panel.

## Install or Update the Release Gate Pair

The privileged helper `/usr/local/sbin/family-notes-deploy` sources the readiness
library from the fixed path `/usr/local/libexec/family-notes/release-gate.sh`.
Together they form release-gate protocol version `1` and must always be installed
from the same repository commit. There is no environment or command-line override
for either path. The new helper fails closed before running any action when the
library is missing (`family-notes-deploy: release gate library is unavailable`)
or reports a different protocol (`family-notes-deploy: incompatible release gate
protocol`). The release script calls the helper's `gate-version` action before it
fetches or creates anything and stops unless the output is exactly `1`, so an
incomplete or mismatched installation blocks releases without mutating
production.

Install the pair before running the revised `scripts/deployment/release.sh`. A
helper installed before this change has no `gate-version` action, so the revised
script stops with `release: release gate protocol check failed`.

The helper revision that adds the `conversion-health` action keeps protocol `1`
and the unchanged `health` gate. Install it with the same procedure (the library
file is unchanged but is reinstalled as part of the matched pair); until then,
`conversion-health` reports `usage` and the direct socket `curl` in
[Enable EduVulcan Conversion](#enable-eduvulcan-conversion) is the fallback.

### Stage the files as `deploy`

From the repository on the development machine, at the approved commit, record
the checksums and copy both files into a private staging directory owned by
`deploy`:

```bash
sha256sum scripts/deployment/release-gate.sh scripts/deployment/family-notes-deploy
ssh familynotes-mikrus 'install -d -m 0700 ~/gate-staging'
ssh familynotes-mikrus 'cat > ~/gate-staging/release-gate.sh' \
  < scripts/deployment/release-gate.sh
ssh familynotes-mikrus 'cat > ~/gate-staging/family-notes-deploy' \
  < scripts/deployment/family-notes-deploy
```

The staged copies are writable by `deploy`, so root never executes or promotes
them in place.

### Install as root through the provider console

Open a root shell in the Mikrus provider console and define the paths:

```bash
SRC=/home/deploy/gate-staging
LIB=/usr/local/libexec/family-notes/release-gate.sh
HELPER=/usr/local/sbin/family-notes-deploy
install -d -o root -g root -m 0755 /usr/local/libexec/family-notes
```

Copy both files into root-owned temporary files in their destination
directories, so each later rename stays on one filesystem, with their final
ownership and permissions. Then compare the checksums with the values recorded
on the development machine and syntax-check both staged files:

```bash
install -o root -g root -m 0644 "$SRC/release-gate.sh" "$LIB.new"
install -o root -g root -m 0755 "$SRC/family-notes-deploy" "$HELPER.new"
sha256sum "$LIB.new" "$HELPER.new"
/bin/sh -n "$LIB.new"
/bin/sh -n "$HELPER.new"
```

Stop and remove both `.new` files if a checksum differs or a syntax check fails.

Retain recoverable copies of the currently installed artifacts in the same
directories. Skip the library copy when no library has been installed yet:

```bash
cp -p "$HELPER" "$HELPER.previous"
[ ! -e "$LIB" ] || cp -p "$LIB" "$LIB.previous"
```

Promote the library first with a same-filesystem rename. The installed helper
keeps working during this step: a helper installed before this change does not
load the library, and a helper of the same protocol accepts the new library.

```bash
mv -f "$LIB.new" "$LIB"
```

Run the staged helper's `gate-version` action. It loads the newly installed
library from the fixed path and must print exactly `1`. Only then promote the
helper with another same-filesystem rename:

```bash
"$HELPER.new" gate-version
mv -f "$HELPER.new" "$HELPER"
```

If `gate-version` prints anything else or fails, do not promote the helper;
remove `$HELPER.new` and restore the library as described below.

### Verify before allowing a release

Still as root, confirm ownership, permissions, syntax, and the protocol version:

```bash
stat -c '%U:%G %a %n' /usr/local/libexec/family-notes "$LIB" "$HELPER"
/bin/sh -n "$LIB"
/bin/sh -n "$HELPER"
"$HELPER" gate-version
```

Expected: the directory and both files are owned by `root:root`, the directory and
helper are mode `755`, the library is mode `644`, both syntax checks are silent,
and `gate-version` prints `1`. Then, as `deploy` (on a fresh server, after the
sudo rule in step 3 exists), confirm the sudo path reports the same version and
remove the staging directory:

```bash
sudo -n /usr/local/sbin/family-notes-deploy gate-version
rm -rf ~/gate-staging
```

Keep `$HELPER.previous` and `$LIB.previous` until the next approved release
passes its readiness gate.

### Restore the retained artifacts if verification fails

If any final verification fails, restore the retained helper first (it does not
depend on the new library), then the library, and remove leftovers:

```bash
mv -f "$HELPER.previous" "$HELPER"
if [ -e "$LIB.previous" ]; then mv -f "$LIB.previous" "$LIB"; else rm -f "$LIB"; fi
rm -f "$LIB.new" "$HELPER.new"
/bin/sh -n "$HELPER"
```

A restored pre-change helper has no `gate-version` action, so the revised release
script refuses to run until a matched pair is installed successfully. Do not work
around this by editing the release script or the sudo rule.

## Automated Subsequent Releases

After the one-time server bootstrap is complete and the matched release-gate pair
is installed, use the repository-owned release script for every deployment. From
the development machine, confirm the approved commit is pushed, then stream the
script to a single SSH session as `deploy`:

```bash
RELEASE_COMMIT="$(git rev-parse HEAD)"
git merge-base --is-ancestor "$RELEASE_COMMIT" origin/master
ssh familynotes-mikrus sh -s -- "$RELEASE_COMMIT" \
  < scripts/deployment/release.sh
```

The script requires a full commit SHA and first requires the helper's
`gate-version` action to print exactly `1`. It then confirms that the commit is
reachable from the server's freshly fetched `master`, creates a timestamped
detached worktree, installs locked production dependencies, runs deployment and
migration checks, creates a verified database dump, applies migrations, collects
static files, switches the active release, restarts the service, prints the
service status, and runs the internal readiness gate. Protected operations go
through `/usr/local/sbin/family-notes-deploy`; the SSH session itself never runs
as root and cannot read `/etc/family-notes/env`.

### Internal readiness gate

Activation switches `current` and restarts the service before readiness is
checked; the previous release does not stay active while the new one is tested.
The release is declared complete only when the gate passes, which the script
reports as `[release=<RELEASE_ID>] Deployment completed: <RELEASE_ID> (<RELEASE_COMMIT>)`.

The gate is the helper's `health` action. It sends `GET /healthz/` through
`/run/family-notes/gunicorn.sock` with the first host from `DJANGO_ALLOWED_HOSTS`
and `X-Forwarded-Proto: https`. An attempt succeeds only when `curl` reports
success and the body is exactly `{"status": "ok"}`, which the endpoint returns
only after a successful database query. Failed attempts, including connection
errors, `503 {"status": "unavailable"}`, and unexpected bodies, are retried every
two seconds.

The window is a strict 30-second deadline measured from immediately before the
first attempt, using UTC epoch seconds. An attempt may start only while less than
30 seconds have elapsed and counts only if it also completes before 30 seconds;
each `curl` attempt and each sleep is capped to the remaining whole-second
budget. A system clock that moves backward is treated as exhaustion. The gate
prints only timestamped state transitions, never response bodies or secrets:

```text
[epoch=<EPOCH>] readiness gate started (deadline=30s)
[epoch=<EPOCH>] readiness gate retrying in 2s (remaining=<N>s)
[epoch=<EPOCH>] readiness gate succeeded (elapsed=<N>s)
[epoch=<EPOCH>] readiness gate exhausted
```

### When the gate is exhausted

If the script fails before activation, it removes the incomplete worktree. Once
activation starts, it never removes the release. When readiness is exhausted, the
script exits nonzero without the completion message and prints:

```text
release: readiness exhausted for release <RELEASE_ID>
The activated release and pre-release backup remain in place.
Inspect service status: sudo -n /usr/local/sbin/family-notes-deploy status
Inspect service logs: sudo -n /usr/local/sbin/family-notes-deploy logs
Retry internal health: sudo -n /usr/local/sbin/family-notes-deploy health
```

The script does not read logs automatically, switch the symlink back, invoke
`rollback`, reverse migrations, or restore the database. The newly activated
release stays live and the pre-release dump stays at
`/var/backups/family-notes/pre-release-<RELEASE_ID>.dump`. Run the printed
commands, then decide whether to roll forward with a corrective release or use the
human-controlled [application rollback](#11-roll-back-the-application). Database
restoration remains a separate, human-approved incident procedure.

Public HTTPS is not part of the automated gate. After every release, verify it
manually as described in step 10.

EduVulcan conversion health is not part of the gate either. A release can be
healthy while conversion is disabled or stalled; intake keeps accepting
notifications and the rows wait in the database. Check it separately with the
helper's `conversion-health` action (step 10).

## 10. Verify Before Calling the Deployment Complete

On the VPS:

```bash
sudo -n /usr/local/sbin/family-notes-deploy gate-version
sudo -n /usr/local/sbin/family-notes-deploy status
systemctl is-active nginx
sudo -n /usr/local/sbin/family-notes-deploy logs
sudo -n /usr/local/sbin/family-notes-deploy health
curl --unix-socket /run/family-notes/gunicorn.sock \
  -H 'Host: <PUBLIC_HOST>' \
  -H 'X-Forwarded-Proto: https' \
  http://localhost/healthz/
curl -I "http://[::1]:20121/healthz/" -H 'Host: <PUBLIC_HOST>'
```

`gate-version` must print `1`, and the `health` action runs the same 30-second
readiness gate used by the release script, ending in `readiness gate succeeded`.

Then check the conversion worker with a single probe of `/healthz/conversion/`:

```bash
sudo -n /usr/local/sbin/family-notes-deploy conversion-health
```

It prints only `conversion health: <STATE>`. `disabled` (worker switched off)
and `ok` (a worker process of the active release recorded a heartbeat within
`EDUVULCAN_WORKER_HEARTBEAT_MAX_AGE_SECONDS`) exit `0`; `unavailable` (enabled
but no fresh heartbeat from the active release) and `unexpected` (transport
error or any other response) exit nonzero. After enabling conversion, `ok` is
expected within a few seconds of the restart, because each worker records a
heartbeat as it starts. Heartbeats of the previous release never count, so
`ok` right after a release proves that the new release's workers started.

The release script's gate proves internal, database-backed readiness only. Public
HTTPS remains a manual acceptance step. From the development machine:

```bash
curl -fsS https://<PUBLIC_HOST>/healthz/
curl -I https://<PUBLIC_HOST>/
```

The public health response must be `{"status": "ok"}`. The production
`check --deploy` output is expected to include the `SECURE_HSTS_INCLUDE_SUBDOMAINS`
and `SECURE_HSTS_PRELOAD` warnings; they are accepted consequences of the shared
`mikrus.dev` parent domain (see step 0) and do not block a release. Any other
deployment-check finding must be resolved.

Then verify in a browser that `https://<PUBLIC_HOST>/` has no TLS warning and
loads its CSS. Confirm that `https://<PUBLIC_HOST>/admin/` is served only over
HTTPS, redirects an anonymous visitor to login, allows an active superuser to
enter, and denies normal family members. The admin is an operator-only setup
surface and must not be used by normal family members.

Complete the one-family setup in admin, then verify that a configured parent and
child each see the expected display name and role at
`https://<PUBLIC_HOST>/account/`. Sign in with an account that has no active
membership and confirm that it sees only the generic not-configured state and no
family data.

Review application, nginx, and system logs after these checks. They must contain
no secrets, OAuth tokens, authorization headers, database passwords, family-entry
text, or AI-provider payloads.

Finally, reboot once and repeat the checks:

```bash
sudo -n /usr/local/sbin/family-notes-deploy reboot
```

Reboot survival is not yet evidenced for this deployment; record it separately
when performed (see [Separate follow-up work](#separate-follow-up-work)).

### Release gate acceptance

Production changes in this subsection require explicit operator authorization.
Record the SSH transcript of each run as release evidence.

1. **Installation:** an authorized operator installs the matched library and
   helper through the provider console and records the `stat`, `/bin/sh -n`, and
   `gate-version` results from
   [Verify before allowing a release](#verify-before-allowing-a-release).
2. **Approved release:** run an operator-approved release. The transcript must
   show either an immediate `readiness gate succeeded` or one or more
   `readiness gate retrying` lines followed by success, and the
   `Deployment completed` line only after the gate succeeded.
3. **Controlled failed-probe rehearsal:** with operator approval, and without
   interrupting family access to data, rehearse a failed probe (for example a
   release whose readiness cannot succeed in a planned window). The script must
   exit nonzero, print `readiness exhausted for release <RELEASE_ID>` and the three
   diagnostic commands, leave `readlink -f /srv/family-notes/current` pointing at
   the attempted release, leave its `pre-release-<RELEASE_ID>.dump` in place, and
   invoke no rollback. Recovery and public HTTPS verification stay manual.
   `/var/backups/family-notes` is `root:root` mode `0700`, so `deploy` cannot list
   it; confirm the dump from the path the helper prints after the backup stage,
   or as root in the provider console with `ls -l` on that path.

### Separate follow-up work

The release gate does not cover these items. Track each as separate work until a
deployment record marks it complete: external uptime monitoring and alerting,
recurring scheduled backups with off-provider copies, a disposable restore drill,
an application rollback rehearsal, and VPS reboot verification.

## Enable Classification

Natural-language classification (OpenAI Responses API) ships disabled. Enabling
it is a separate, operator-approved configuration change; it does not alter the
release script, the Gunicorn worker count (`--workers 2`), the Gunicorn
`--timeout 45`, or the nginx `proxy_read_timeout 50s`. The application enforces
its own 25-second classification deadline inside those limits. No page uses
classification yet, so until entry capture ships, the smoke check below is the
only production caller.

### 1. Accept the data-retention trade-off

The application sends `store=False` on every request. **`store=False` does not
replace Zero Data Retention (ZDR)**: it only prevents the response from being
kept as retrievable application state, while standard API traffic may still be
retained by OpenAI for abuse monitoring. ZDR is deferred until after the MVP
(see the roadmap's post-MVP section), so enabling classification now accepts
that retention.

Record in the private operator record (password manager or deployment notes
outside this repository), never the key itself: the date, the operator, the
OpenAI organization and project used in production, and the selected
structured-output-capable model name.

### 2. Configure the protected environment

Create a project-scoped API key for the production OpenAI project and store it
in the password manager. As root in the provider console, add the variables to the
protected environment file:

```bash
sudoedit /etc/family-notes/env
```

```dotenv
CLASSIFICATION_ENABLED=True
OPENAI_API_KEY=<OPENAI_API_KEY>
OPENAI_CLASSIFICATION_MODEL=<OPENAI_CLASSIFICATION_MODEL>
```

| Variable | Meaning |
| --- | --- |
| `CLASSIFICATION_ENABLED` | Master switch; `False` disables every provider call. |
| `OPENAI_API_KEY` | Project key of the production OpenAI project. Secret. |
| `OPENAI_CLASSIFICATION_MODEL` | A model that supports Structured Outputs with the Responses API. Recommended: `gpt-5.4-nano` with `OPENAI_REASONING_EFFORT=none`. |
| `OPENAI_REASONING_EFFORT` | Required in practice for reasoning models (for example `low` for the gpt-5 family); leave empty for non-reasoning models. Otherwise `reason=incomplete_output`. |
| `CLASSIFICATION_DEADLINE_SECONDS` | Optional; default `25`. Keep it at or below 25. |
| `CLASSIFICATION_ATTEMPT_TIMEOUT_SECONDS` | Optional; default `10`. |
| `CLASSIFICATION_MAX_RETRIES` | Optional; default `1` (`0` or `1` only). |

Leave the three timing variables unset unless a reviewed change says otherwise.
Never set `OPENAI_LOG=debug` or any provider tracing in production. Keep the file
`root:root` mode `0600` and confirm the values are present without printing them:

```bash
stat -c '%U:%G %a %n' /etc/family-notes/env
awk -F= '/^(CLASSIFICATION_ENABLED|OPENAI_API_KEY|OPENAI_CLASSIFICATION_MODEL)=/ { print $1, (length($2) ? "set" : "EMPTY") }' /etc/family-notes/env
```

With `DJANGO_DEBUG=False`, enabling classification without the key or model
stops Django at startup, naming only the missing variables. As
`deploy`, confirm the configuration passes that fail-closed check against the
active release:

```bash
sudo -n /usr/local/sbin/family-notes-deploy check "$(basename "$(readlink -f /srv/family-notes/current)")"
```

The service reads the environment file only when it starts. Apply the change
with the next approved release, or as root with
`systemctl restart family-notes` followed by
`sudo -n /usr/local/sbin/family-notes-deploy health` as `deploy`.

### 3. Run the synthetic classification smoke check

Run this after every release that is deployed with classification enabled. It
sends one synthetic Polish school instruction (no family data, no database
rows) through the configured provider, validation, and timing policy, and prints
only safe fields. The instruction contains a fresh sentinel that the command
never prints or logs. As root in the provider console:

```bash
SENTINEL="SMOKE-$(python3 -c 'import secrets; print(secrets.token_hex(8))')"
SMOKE_STARTED="$(date '+%Y-%m-%d %H:%M:%S')"
( set -a; . /etc/family-notes/env; set +a
  cd /srv/family-notes/current
  runuser -u familynotes -- .venv/bin/python manage.py classification_smoke \
    --sentinel "$SENTINEL" 2>&1 | systemd-cat -t family-notes-classification-smoke )
journalctl -t family-notes-classification-smoke --since "$SMOKE_STARTED" --no-pager
```

The output is routed through journald on purpose, so the log inspection below
covers it. Expected result, within 30 seconds (`elapsed_ms` at most `30000`):

```text
classification smoke outcome=proposal entry_type=calendar_event reference_date=<TODAY> date=<NEXT_MONDAY> member_resolved=yes elapsed_ms=<N> budget_s=30
```

`outcome=follow_up` is also acceptable. `outcome=unavailable reason=<CODE>` is a
safe failure: it satisfies the timing requirement, but investigate the reason
(for example `timeout`, `rate_limited`, or `provider_error`) before relying on
classification. A `CommandError` about disabled configuration or the 30-second
budget fails the check.

### 4. Inspect logs for the sentinel

The sentinel must not appear in application, journald, or nginx logs:

```bash
journalctl --since "$SMOKE_STARTED" --no-pager | grep -cF -- "$SENTINEL"
journalctl -u family-notes --since "$SMOKE_STARTED" --no-pager | grep -cF -- "$SENTINEL"
grep -rlF -- "$SENTINEL" /var/log/nginx/ || echo 'sentinel absent from nginx logs'
```

Both counts must be `0` and no nginx log file may be listed. The application's
only classification log line has the form
`classification provider=openai outcome=<CODE> status=<STATUS> request_id=<ID> elapsed_ms=<N> attempts=<N>`;
any submitted text, member names, response content, provider payloads, or
credentials in logs are a privacy incident. Record the smoke output line and
the three sentinel results in the private operator record.

### Disable classification

If the smoke check fails or the sentinel appears in any log, set
`CLASSIFICATION_ENABLED=False` in `/etc/family-notes/env`, restart the service as
root, and confirm `health` as `deploy`. Classification stores no data, so
disabling it (and, if needed, rolling back the application release) requires no
data cleanup.

## Enable EduVulcan Conversion

Stored EduVulcan notifications are converted into entries by a background
thread inside each Gunicorn worker process. It ships disabled
(`EDUVULCAN_WORKER_ENABLED=False`); enabling it is an operator-approved
configuration change that keeps the two Gunicorn workers, `--timeout 45`, and
the release gate unchanged. With both processes enabled, a PostgreSQL advisory
lock lets only one of them convert at a time; the other keeps its own heartbeat
and takes over when the lock is free. Each process's heartbeat carries the
release it runs: the name of the resolved release directory
(`/srv/family-notes/releases/<RELEASE_ID>`), because Django resolves the
`current` symlink. Do not set `FAMILY_NOTES_RELEASE_ID` in
`/etc/family-notes/env` or the unit; the environment is shared by every
release, so a fixed value would let an old release's heartbeats count. Conversion calls classification only for
notifications that the fixed school rules do not recognise, so the
[Enable Classification](#enable-classification) prerequisites apply to those; with
classification disabled they become general family notes.

### 1. Deploy the schema with the worker disabled

Release the commit containing the conversion migrations through the normal
release script while `EDUVULCAN_WORKER_ENABLED` is absent or `False`. The
readiness gate must succeed, and `conversion-health` must print
`conversion health: disabled`. Confirm the systemd `ExecStart` includes
`--config gunicorn.conf.py` (step 8).

### 2. Enable the worker

As root in the provider console, add to `/etc/family-notes/env`:

```dotenv
EDUVULCAN_WORKER_ENABLED=True
```

| Variable | Default | Meaning |
| --- | --- | --- |
| `EDUVULCAN_WORKER_ENABLED` | `False` | Master switch for the conversion thread. |
| `EDUVULCAN_CONVERSION_SWEEP_INTERVAL_SECONDS` | `60` | Seconds between database sweeps for pending, retry-due, and stale rows. |
| `EDUVULCAN_CONVERSION_BATCH_SIZE` | `50` | Rows per sweep (and per pruning batch). |
| `EDUVULCAN_CONVERSION_LEASE_SECONDS` | `120` | How long one attempt owns a row before another sweep may reclaim it; must be at least `CLASSIFICATION_DEADLINE_SECONDS` + 30. |
| `EDUVULCAN_CONVERSION_MAX_ATTEMPTS` | `3` | Total attempts before a row fails or falls back to a general note. |
| `EDUVULCAN_CONVERSION_RETRY_DELAYS_SECONDS` | `60,300` | Delays before attempt 2 and attempt 3. |
| `EDUVULCAN_RAW_RETENTION_DAYS` | `90` | Age after which raw title, message, and payload of processed rows are scrubbed (hourly). |
| `EDUVULCAN_WORKER_HEARTBEAT_SECONDS` | `30` | How often an active worker records its heartbeat. |
| `EDUVULCAN_WORKER_HEARTBEAT_MAX_AGE_SECONDS` | `180` | Heartbeat age after which `/healthz/conversion/` stops counting a process; must exceed the heartbeat interval. Rows older than ten times this are deleted hourly. |

Leave the tuning variables unset unless a reviewed change says otherwise. An
invalid number (not a positive whole number), or a lease shorter than the
classification deadline plus 30 seconds, stops Django at startup and names only
the variable, so run the helper's `check` action against the active release
first, then restart as root and verify as `deploy`:

```bash
sudo -n /usr/local/sbin/family-notes-deploy check "$(basename "$(readlink -f /srv/family-notes/current)")"
systemctl restart family-notes              # as root
sudo -n /usr/local/sbin/family-notes-deploy health
sudo -n /usr/local/sbin/family-notes-deploy conversion-health
```

`health` must end in `readiness gate succeeded` and `conversion-health` must
print `conversion health: ok`. If the helper does not yet have the
`conversion-health` action, probe the socket directly; the expected body is
exactly `{"status": "ok"}`:

```bash
curl -sS --unix-socket /run/family-notes/gunicorn.sock \
  -H 'Host: <PUBLIC_HOST>' -H 'X-Forwarded-Proto: https' \
  http://localhost/healthz/conversion/
```

### 3. Confirm restart recovery

Restarting the service sweeps immediately: each worker process converts pending,
retry-due, and stale `processing` rows as it starts, so rows received while the
worker was stopped are not lost. In admin, **Entries → Powiadomienia
przychodzące** shows each row's status, attempt count, and a safe error code
only. Logs name notification IDs, attempt numbers, and codes, never
notification text or family names; inspect them with
`sudo -n /usr/local/sbin/family-notes-deploy logs`.

### 4. Inspect status and requeue failed rows

Intake's `202` only acknowledges durable storage; it does not mean the
notification is already converted. With the worker enabled, a new row is
normally converted within seconds, and at the latest by the next sweep
(`EDUVULCAN_CONVERSION_SWEEP_INTERVAL_SECONDS`), after a provider retry delay
(`60,300` seconds), or after the next restart.

In admin, filter **Entries → Powiadomienia przychodzące** by status:

- `pending` — waiting for its first attempt or a scheduled retry
  (`next attempt at`).
- `processing` — a worker holds a lease until `lease expires at`; a lease that
  outlives a crash is reclaimed by the next sweep.
- `processed` — entries saved; the inline lists each generated entry, and an
  empty entry link means a parent deleted it (it is never recreated).
- `failed` — terminal until an operator requeues it.

`last error code` holds a safe category only: `provider_<reason>` (for example
`provider_timeout`), `database_busy`, `database_error`, `conversion_error`,
`lease_expired`, `attempts_exhausted`, `empty_notification`, or
`invalid_output`. A `processed` row with a `provider_*` code fell back to a
general family note after the provider stayed unavailable.

To retry `failed` rows after fixing the cause, a superuser selects them and runs
**Requeue selected failed notifications**. They return to `pending` with a
fresh attempt budget, keep their payload and existing outputs, and are
converted by the next sweep; rows in other statuses are ignored.

Raw title, message, and payload of `processed` rows are scrubbed hourly once
they are older than `EDUVULCAN_RAW_RETENTION_DAYS` (default `90`); admin then
shows `Raw data pruned`. Notification IDs, content hashes, and output links stay,
so duplicate detection still works. `pending`, `processing`, and `failed` rows are
never scrubbed, so requeue does not lose data.

Manual checks use anonymized payloads only (fictional names, as in the README
`curl` example). Do not paste real notification text, admin title or message
values, or token secrets into shells, tickets, or chat; quote notification IDs,
statuses, and error codes instead.

### Disable conversion

Set `EDUVULCAN_WORKER_ENABLED=False`, restart as root, and confirm `health`
and `conversion-health` (`disabled`) as `deploy`. Intake keeps storing
notifications as `pending`; they are converted after the worker is enabled
again. An application rollback disables the worker first; pending rows and
conversion outputs stay valid for a forward fix, and migrations are never
reversed automatically.

## 11. Roll Back the Application

As `deploy`, list releases and identify the previous known-good directory:

```bash
ls -1dt /srv/family-notes/releases/*
readlink -f /srv/family-notes/current
```

Switch only the application release through the restricted helper, then verify:

```bash
sudo -n /usr/local/sbin/family-notes-deploy rollback <PREVIOUS_RELEASE_ID>
sudo -n /usr/local/sbin/family-notes-deploy status
sudo -n /usr/local/sbin/family-notes-deploy health
curl -fsS https://<PUBLIC_HOST>/healthz/
```

Rollback is always an operator decision; neither the release script nor the
readiness gate invokes it. Do not restore the database automatically. If a migration is incompatible with
the previous release, stop and prepare a forward fix. Database restoration is a
separate, human-approved incident procedure.

## 12. Troubleshooting

- **SSH fails:** verify `<SSH_PORT>` against `10000 + SERVER_ID`, force the key
  with `ssh -vvv familynotes-mikrus`, and use the Mikrus console for recovery.
- **502 Bad Gateway:** inspect `systemctl status family-notes`, confirm
  `/run/family-notes/gunicorn.sock` exists, and inspect journald before nginx.
- **Gunicorn control server permission error:** add `--no-control-socket` to the
  systemd `ExecStart` command. FamilyNotes does not use `gunicornc`; disabling
  its separate management socket does not affect the application socket.
- **Contradictory scheme headers:** remove `include proxy_params` from the nginx
  location and set the four proxy headers shown in step 9 explicitly. Debian's
  default include derives `X-Forwarded-Proto` as internal HTTP, conflicting with
  the required external `https` value.
- **400 Bad Request:** `<PUBLIC_HOST>` is missing or misspelled in
  `DJANGO_ALLOWED_HOSTS`. Direct Gunicorn socket checks must also send
  `Host: <PUBLIC_HOST>` instead of the URL's `localhost` host.
- **403 CSRF failure:** confirm the public origin is exactly
  `https://<PUBLIC_HOST>` in `DJANGO_CSRF_TRUSTED_ORIGINS`.
- **Static CSS is missing:** run `collectstatic`, verify `STATIC_ROOT` targets
  `/var/www/family-notes/static`, and check nginx file permissions.
- **Database fails:** use interactive `psql`, confirm the Mikrus panel values,
  and check that all `DB_*` variables exist without printing their contents.
- **Public URL times out:** verify nginx listens on port `20121`, that the port is
  assigned in the panel, and that `curl` works locally over IPv6.
- **`release gate library is unavailable` or `incompatible release gate
  protocol`:** the helper and library are not a matched pair. Reinstall both from
  one commit through the provider console, or restore the retained artifacts, as
  in [Install or Update the Release Gate Pair](#install-or-update-the-release-gate-pair).
- **`release: release gate protocol check failed` or `unexpected release gate
  protocol`:** the release stopped before fetching or creating a release. Check
  `sudo -n /usr/local/sbin/family-notes-deploy gate-version`; it must print `1`.
- **`conversion health: unavailable`:** the worker is enabled but no process of
  the active release recorded a heartbeat within the max age. Intake still works. Confirm the unit's
  `ExecStart` includes `--config gunicorn.conf.py`, then inspect `logs` for
  `EduVulcan conversion` warnings (for example `error=<CLASS>`, or
  `worker not started` from the Gunicorn hook).
  A database outage also reports `unavailable`; check `health` first.
- **Notifications stay `pending` or turn `failed`:** check `conversion-health`
  first (`disabled` means the worker is switched off; rows wait safely). For
  `failed` rows read only `last error code` and `attempt count` in admin:
  `database_*` points to the database, `provider_*` to classification (see
  [Enable Classification](#enable-classification)), and `lease_expired` to a
  worker that repeatedly died or overran its lease. Fix the cause, then
  requeue as in step 4 of
  [Enable EduVulcan Conversion](#enable-eduvulcan-conversion). The
  `EduVulcan conversion` lines in `logs` (from `INFO` up) show sweeps, processed
  rows, scheduled retries, and failures with their notification ID, attempt,
  and code; an unexpected failure also names the exception class
  (`error=<CLASS>`).
- **`readiness exhausted for release`:** the new release is active and its backup
  is in place. Run the printed `status`, `logs`, and `health` commands, then choose
  a forward fix or the manual application rollback.

## References

- [Mikrus Django and PostgreSQL guide](https://wiki.mikr.us/django_postgresql/)
- [Mikrus automatic and dedicated subdomains](https://wiki.mikr.us/darmowa_subdomena_dla_vps/)
- [Mikrus assigned ports](https://wiki.mikr.us/udostepnione_porty/)
- [Mikrus Strych backups](https://wiki.mikr.us/strych_backupy/)
