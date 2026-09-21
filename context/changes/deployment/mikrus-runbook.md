# FamilyNotes First Deployment on Mikr.us

This is the operator checklist for the first production deployment. Run local
commands on the development machine and server commands after connecting to the
Mikrus VPS. Replace every value written as `<LIKE_THIS>` before running a command.

The initial public URL uses Mikrus's automatic `wykr.es` subdomain. It terminates
HTTPS for the user and forwards plain HTTP to nginx on one of the VPS's assigned
ports. Do not install Certbot for this setup.

## Deployment Progress

Updated 2026-09-21:

- [x] Application pre-deployment readiness implemented locally
- [x] Steps 1-6 completed on Mikrus (reported by the operator)
- [ ] Step 7: create and validate the first versioned release
- [ ] Step 8: configure and start the systemd service
- [ ] Step 9: configure nginx and public routing
- [ ] Step 10: complete production verification and reboot test

## 0. Application Readiness

The application now provides:

- `STATIC_ROOT` controlled by `DJANGO_STATIC_ROOT`
- proxy-aware HTTPS, secure production cookies, SSL redirect, and HSTS settings
- a database-backed `/healthz/` endpoint with detail-free failure responses
- the Git `origin` remote used to publish commits for the Mikrus repository mirror

Before step 7, commit and push these deployment changes, then use that exact full
commit SHA as `<RELEASE_COMMIT>`. Review the output of
`uv run python manage.py check --deploy` under production settings before exposing
the app publicly.

With the initial `wykr.es` host, Django's deployment check is expected to warn
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
| `<APP_PORT>` | choose an assigned general-purpose port, normally `20000 + SERVER_ID` or `30000 + SERVER_ID` |
| `<PUBLIC_HOST>` | `<SERVER_NAME>-<APP_PORT>.wykr.es` |
| `<DB_HOST>` | dedicated PostgreSQL hostname |
| `<DB_PORT>` | dedicated PostgreSQL port, commonly `5432` |
| `<DB_SSLMODE>` | TLS mode required by Mikrus, preferably `require` |
| `<DB_ADMIN_USER>` | administrative login supplied with the service |
| `<DB_NAME>` | `family_notes` unless Mikrus pre-created a fixed database |
| `<DB_USER>` | `family_notes_app` unless Mikrus pre-created a fixed login |
| `<DB_PASSWORD>` | new password for the application login |
| `<REPOSITORY_URL>` | HTTPS or SSH Git clone URL |
| `<RELEASE_COMMIT>` | full Git commit SHA approved for release |

In the Mikrus panel:

1. Open the purchased dedicated PostgreSQL service in the Mikrus panel. Copy its
   hostname, port, TLS requirement, administrative login, and administrative
   password into the password manager. Do not save admin credentials in Django's
   environment file.
2. Confirm `<APP_PORT>` is in the assigned port pool. Additional TCP ports can
   be requested in the panel if both general-purpose ports are occupied.
3. Open `https://<PUBLIC_HOST>/` only after nginx is configured. The dynamic
   `wykr.es` name needs no separate DNS or subdomain setup.
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

Allow only controlled service operations from the deployment account:

```bash
visudo -f /etc/sudoers.d/family-notes-deploy
```

Insert exactly:

```sudoers
deploy ALL=(root) NOPASSWD: /usr/bin/systemctl restart family-notes, /usr/bin/systemctl status family-notes
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
sudo systemctl status family-notes
```

The status command may report that the unit does not exist; successful sudo
authorization is what matters at this point. Do not grant `deploy` unrestricted
sudo access.

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
```

Do not add placeholder auth or AI values. Add those only when their integrations
exist. Protect the file:

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

In the still-open root session, load the protected environment and run the
pre-deploy checks as the runtime user:

```bash
set -a
. /etc/family-notes/env
set +a
cd /srv/family-notes/releases/<RELEASE_ID>
runuser -u familynotes -- .venv/bin/python manage.py check --deploy
runuser -u familynotes -- .venv/bin/python manage.py makemigrations --check --dry-run
```

The root shell passes the loaded environment to the `familynotes` process; the
deployment account never receives direct read access to the secrets file.

Before the first migration, make a database dump in the root session:

```bash
set -a
. /etc/family-notes/env
set +a
install -d -m 0700 /var/backups/family-notes
PGPASSWORD="$DB_PASSWORD" pg_dump -Fc -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$DB_NAME" \
  -f "/var/backups/family-notes/pre-first-deploy.dump"
test -s /var/backups/family-notes/pre-first-deploy.dump
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
ExecStart=/srv/family-notes/current/.venv/bin/gunicorn family_notes.wsgi:application --workers 2 --timeout 45 --bind unix:/run/family-notes/gunicorn.sock --access-logfile - --error-logfile -
Restart=on-failure
RestartSec=5
PrivateTmp=true
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
```

Activate the release, but run database/static setup before starting web traffic:

```bash
ln -sfn /srv/family-notes/releases/<RELEASE_ID> /srv/family-notes/current
systemctl daemon-reload
systemctl enable family-notes
```

Load the same protected environment and run management commands as the application
user:

```bash
set -a
. /etc/family-notes/env
set +a
cd /srv/family-notes/current
runuser -u familynotes -- .venv/bin/python manage.py migrate --noinput
runuser -u familynotes -- .venv/bin/python manage.py collectstatic --noinput
systemctl start family-notes
systemctl status family-notes --no-pager
```

If `collectstatic` fails because `STATIC_ROOT` is missing, stop and fix the app;
do not work around it by serving source directories.

## 9. Configure nginx and the Mikrus URL

Still as root, create `/etc/nginx/sites-available/family-notes`:

```nginx
server {
    listen [::]:<APP_PORT> ipv6only=off;
    server_name <PUBLIC_HOST>;

    client_max_body_size 2m;

    location /static/ {
        alias /var/www/family-notes/static/;
        access_log off;
        expires 1h;
    }

    location / {
        include proxy_params;
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

The `listen [::]:<APP_PORT> ipv6only=off` form accepts both IPv6 and IPv4 traffic.
For `wykr.es`, `<APP_PORT>` must be one of the assigned IPv4-forwarded ports. For
a later dedicated Mikrus subdomain, select this same port and plain HTTP in the
panel; Mikrus still presents HTTPS externally.

## 10. Verify Before Calling the Deployment Complete

On the VPS:

```bash
sudo systemctl is-active family-notes nginx
sudo journalctl -u family-notes -n 100 --no-pager
curl --unix-socket /run/family-notes/gunicorn.sock http://localhost/healthz/
curl -I "http://[::1]:<APP_PORT>/healthz/" -H 'Host: <PUBLIC_HOST>'
```

From the development machine:

```bash
curl -fsS https://<PUBLIC_HOST>/healthz/
curl -I https://<PUBLIC_HOST>/
```

Then verify in a browser that `https://<PUBLIC_HOST>/` has no TLS warning and
loads its CSS. Confirm that `https://<PUBLIC_HOST>/admin/` returns 404. Review
logs for secrets or database passwords before creating real family data.

Finally, reboot once and repeat the checks:

```bash
sudo reboot
```

## 11. Roll Back the Application

In a root session, list releases and identify the previous known-good directory:

```bash
ls -1dt /srv/family-notes/releases/*
readlink -f /srv/family-notes/current
```

Switch only the application release, then verify:

```bash
ln -sfn /srv/family-notes/releases/<PREVIOUS_RELEASE_ID> /srv/family-notes/current
systemctl restart family-notes
systemctl status family-notes --no-pager
curl -fsS https://<PUBLIC_HOST>/healthz/
```

Do not restore the database automatically. If a migration is incompatible with
the previous release, stop and prepare a forward fix. Database restoration is a
separate, human-approved incident procedure.

## 12. Troubleshooting

- **SSH fails:** verify `<SSH_PORT>` against `10000 + SERVER_ID`, force the key
  with `ssh -vvv familynotes-mikrus`, and use the Mikrus console for recovery.
- **502 Bad Gateway:** inspect `systemctl status family-notes`, confirm
  `/run/family-notes/gunicorn.sock` exists, and inspect journald before nginx.
- **400 Bad Request:** `<PUBLIC_HOST>` is missing or misspelled in
  `DJANGO_ALLOWED_HOSTS`.
- **403 CSRF failure:** confirm the public origin is exactly
  `https://<PUBLIC_HOST>` in `DJANGO_CSRF_TRUSTED_ORIGINS`.
- **Static CSS is missing:** run `collectstatic`, verify `STATIC_ROOT` targets
  `/var/www/family-notes/static`, and check nginx file permissions.
- **Database fails:** use interactive `psql`, confirm the Mikrus panel values,
  and check that all `DB_*` variables exist without printing their contents.
- **Public URL times out:** verify nginx listens on `<APP_PORT>`, that the port is
  assigned in the panel, and that `curl` works locally over IPv6.

## References

- [Mikrus Django and PostgreSQL guide](https://wiki.mikr.us/django_postgresql/)
- [Mikrus automatic and dedicated subdomains](https://wiki.mikr.us/darmowa_subdomena_dla_vps/)
- [Mikrus assigned ports](https://wiki.mikr.us/udostepnione_porty/)
- [Mikrus Strych backups](https://wiki.mikr.us/strych_backupy/)
