# FamilyNotes First Deployment on Mikr.us

This is the operator checklist for the first production deployment. Run local
commands on the development machine and server commands after connecting to the
Mikrus VPS. Replace every value written as `<LIKE_THIS>` before running a command.

The initial public URL uses Mikrus's automatic `wykr.es` subdomain. It terminates
HTTPS for the user and forwards plain HTTP to nginx on one of the VPS's assigned
ports. Do not install Certbot for this setup.

## 0. Do Not Start Until the Application Is Ready

The following items from the deployment plan are not implemented in the current
application yet:

- `STATIC_ROOT` for `collectstatic`
- proxy-aware HTTPS and production cookie settings
- the database-backed `/healthz/` endpoint
- a configured Git remote from which Mikrus can clone the repository

Implement and test these before the first production release. The remaining
steps may be used to prepare the account and VPS, but do not expose the app
publicly until `uv run python manage.py check --deploy` has been reviewed.

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
| `<DB_HOST>` | shared PostgreSQL `Server` value |
| `<DB_PORT>` | `5432`, unless the panel says otherwise |
| `<DB_NAME>` | shared PostgreSQL `Baza` value |
| `<DB_USER>` | shared PostgreSQL `login` value |
| `<DB_PASSWORD>` | shared PostgreSQL `Haslo` value |
| `<REPOSITORY_URL>` | HTTPS or SSH Git clone URL |
| `<RELEASE_COMMIT>` | full Git commit SHA approved for release |

In the Mikrus panel:

1. Open `https://mikr.us/panel/?a=postgres`, request PostgreSQL access, and copy
   the resulting values from the database logs into the password manager.
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

## 5. Verify Shared PostgreSQL Before Saving Secrets

From the VPS, run:

```bash
psql 'host=<DB_HOST> port=<DB_PORT> dbname=<DB_NAME> user=<DB_USER>'
```

Enter `<DB_PASSWORD>` at the prompt, then verify connectivity:

```sql
SELECT current_database(), current_user;
SELECT pg_size_pretty(pg_database_size(current_database()));
\q
```

If it fails, copy the host and login exactly from the Mikrus database logs and
confirm port `5432`. Do not add the password to the command line.

## 6. Create the Production Environment File

Generate a secret locally, not in chat or a committed file:

```bash
uv run python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
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
curl -I https://<PUBLIC_HOST>/admin/login/
```

Then verify in a browser that `https://<PUBLIC_HOST>/admin/login/` has no TLS
warning and loads its CSS. Review logs for secrets or database passwords before
creating real family data.

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
- [Mikrus shared database](https://wiki.mikr.us/wspoldzielone_bazy_danych/)
- [Mikrus Strych backups](https://wiki.mikr.us/strych_backupy/)
