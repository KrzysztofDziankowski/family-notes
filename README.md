# FamilyNotes

FamilyNotes is a Django 5.2 application managed with `uv`.

## Requirements

- Python 3.10 or newer
- [`uv`](https://docs.astral.sh/uv/)

## Run locally

Install the locked dependencies:

```bash
uv sync
```

Create your local environment file:

```bash
cp .env.example .env
```

Generate a local Django secret and place it in `DJANGO_SECRET_KEY` in `.env`:

```bash
uv run python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

The `.env` file is loaded automatically and ignored by Git. Store local database
credentials and API keys there; never put real values in `.env.example`.

By default, local development uses `db.sqlite3`, which is also ignored by Git and
requires no credentials. To develop against PostgreSQL, set `DB_ENGINE=postgresql`
in `.env`, uncomment all five `DB_*` settings in that file, and create the named
local database and user first.

Apply the database migrations:

```bash
uv run python manage.py migrate
```

Start the development server:

```bash
uv run python manage.py runserver '[::]:20121'
```

Open <http://[::1]:20121/> in your browser.

## Test authentication locally

In Google Cloud Console, configure the Google Auth Platform consent screen and
create an OAuth client with the **Web application** type. While the app is in
testing mode, add each Google account that may sign in as a test user.

Register this authorized redirect URI for the local server:

```text
http://localhost:20121/accounts/google/login/callback/
```

The scheme, hostname, port, path, and trailing slash must exactly match the URL
used in the browser. Add the client credentials to `.env`:

```dotenv
GOOGLE_OAUTH_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_OAUTH_CLIENT_SECRET=your-client-secret
```

Apply migrations and create a local admin account if needed:

```bash
uv run python manage.py migrate
uv run python manage.py createsuperuser
```

### Create the initial family

Family setup is intentionally limited to Django admin for the MVP:

1. Have each parent and child sign in with Google once. Until configured, each
   account can safely reach `/account/` but sees only the not-configured state.
2. Sign in to `/admin/` with the superuser account created above.
3. Under **Family access**, create the single active `Family` used by the MVP.
4. Create one active `Family member` for each Google user. Select the family,
   set the display name, and assign either the `Parent` or `Child` role.
5. Open `/account/` as each configured user and confirm that the expected display
   name and role appear. An authenticated user without an active membership must
   continue to see only the not-configured state.

Only active superusers may use `/admin/`. Family membership, including the
`Parent` role, never grants admin access. Keep the operator account and all real
OAuth credentials out of tracked files.

To remove someone's access, untick **Active** on their `Family member` (or on the
user). Do not delete users or members: an entry assigned to a member protects it
(`on_delete=RESTRICT`), so admin refuses the delete with a list of the blocking
entries. Deactivation takes effect immediately and keeps those entries attributed.

### Seed a local test family

For manual QA you can seed test users instead of using real Google accounts.
Run this against your local database only. The script refuses to run when
`DJANGO_DEBUG` is off:

```bash
DJANGO_DEBUG=true uv run python manage.py shell < scripts/dev/seed_test_family.py
```

It creates these users, all with the password `test-haslo-123`:

| Username | Role | Family |
| --- | --- | --- |
| `test_rodzic` | parent (Ewa) | Rodzina testowa |
| `test_kasia` | child (Kasia) | Rodzina testowa |
| `test_tymek` | child (Tymek), sibling | Rodzina testowa |
| `test_obcy` | parent (Obcy) | Inna rodzina |

It also adds sample entries: upcoming, today, undated, long text, past
EduVulcan, a sibling's entry, a family-wide entry, and one entry in the other
family. At the end it prints the IDs of the sibling, family-wide and
other-family entries, which the access checks use. Re-running it resets the
test users' passwords and recreates the entries of these two test families.
Other families are not touched.

Sign in at <http://localhost:20121/accounts/login/> with the username and
password, and log out between roles. To test on a phone, start the server with
`runserver 0.0.0.0:20121` and add the computer's LAN IP to
`DJANGO_ALLOWED_HOSTS` in `.env`.

With the local server running, verify these routes:

- <http://localhost:20121/accounts/google/login/> starts Google sign-in for an allowed test user.
- <http://localhost:20121/account/> requires authentication and shows the configured display name and role, or a generic not-configured state.
- <http://localhost:20121/admin/> accepts the credentials created by `createsuperuser`; normal staff and family accounts are denied.
- <http://localhost:20121/healthz/> returns `{"status": "ok"}` while the database is available.
- <http://localhost:20121/healthz/conversion/> returns `{"status": "disabled"}` unless the conversion worker is enabled (see [Convert notifications locally](#convert-notifications-locally)).

For production, register
`https://YOUR_DOMAIN/accounts/google/login/callback/` separately and store the
real credentials only in the protected server environment and password manager.

### Issue an automation token

A parent's phone automation (the script that forwards EduVulcan notifications)
authenticates with a bearer token. Tokens are issued and revoked only in admin:

1. Sign in to `/admin/` as the superuser and open **Family access → Tokeny
   automatyzacji → Add**.
2. Pick an active **parent** member, give the token a name (for example the
   device it will live on) and optionally an expiry, then save.
3. Copy the secret (it starts with `fnat_`) from the page that follows. It is
   shown **once**: only its hash is stored, so it cannot be viewed again. Do not
   refresh that page; a refresh issues a second token (revoke the duplicate).
4. Store the secret only in the phone automation and your password manager.

Check the token end to end:

```bash
curl -i -H "Authorization: Bearer fnat_..." http://localhost:20121/api/automation/ping/
```

A valid token returns `200 {"status": "ok", "token": "<name>"}` and updates
**last used** in admin. Anything else returns `401 {"error": "invalid_token"}`.

To revoke, select the token in the admin list and run **Unieważnij wybrane
tokeny**. Revocation takes effect on the very next request. A token also stops
working when it expires, or when its owner is no longer an active parent.

The phone automation forwards each EduVulcan notification to the intake
endpoint with the same token. The endpoint only stores the notification and
answers `202` straight away; it never classifies in the request:

```bash
curl -i -X POST \
  -H "Authorization: Bearer fnat_..." \
  -H "Content-Type: application/json" \
  -d '{"notification_id": "0|pl.example.eduvulcan|1|anon-1", "title": "Sprawdzian", "message": "Jan Przykładowy: sprawdzian z biologii 28.09", "captured_at_iso": "2026-09-23T08:26:16+02:00"}' \
  http://localhost:20121/api/automation/notifications/
```

A new notification returns `202 {"status": "accepted", "id": <row id>}`.
Repeating the same `notification_id`, or the same title and message captured on
the same day, returns `202` with the existing row's id and stores nothing new.
An invalid body returns `400`, a body over 16 KB returns `413`. The row appears
in admin under **Entries → Powiadomienia przychodzące** with status `pending`
until the conversion worker picks it up (see below).
Use only anonymized payloads for manual tests; real notifications name family
members.

### Convert notifications locally

A `202` means the notification is stored, not that it is already converted.
Conversion runs in a background thread inside each Gunicorn worker process,
never in the request, and only when `EDUVULCAN_WORKER_ENABLED=True`. The thread
is started by the hooks in `gunicorn.conf.py`; `runserver`, tests, and
management commands never start it. To watch pending rows convert locally:

```bash
EDUVULCAN_WORKER_ENABLED=True uv run gunicorn family_notes.wsgi:application \
  --config gunicorn.conf.py --workers 2 --bind '[::1]:20122'
```

On startup, and then every `EDUVULCAN_CONVERSION_SWEEP_INTERVAL_SECONDS`, the
worker converts pending, retry-due, and stale `processing` rows; new intake rows
also wake it right after commit. The remaining tuning variables are listed in
`.env.example`; an invalid number stops startup.

Two health checks exist:

- `/healthz/` returns exactly `{"status": "ok"}` while the database is
  available. It is the release gate and ignores conversion.
- `/healthz/conversion/` returns `200 {"status": "disabled"}` when the worker is
  switched off, `200 {"status": "ok"}` when a worker recorded a heartbeat within
  `EDUVULCAN_WORKER_HEARTBEAT_MAX_AGE_SECONDS`, and
  `503 {"status": "unavailable"}` otherwise. Intake keeps answering `202`
  either way.

Neither health check returns notification data, counts, or error details.

#### Inspect conversion status

Each row in **Entries → Powiadomienia przychodzące** moves through these
statuses:

| Status | Meaning |
| --- | --- |
| `pending` | Stored and waiting for its first attempt, or for a scheduled retry (`next attempt at`). |
| `processing` | One worker holds a lease (`lease expires at`) for the current attempt. |
| `processed` | Its entries were saved; the inline lists every generated entry (a deleted entry leaves an empty link). |
| `failed` | Attempts ran out or the row cannot be converted; it waits for an operator. |

Filter the list by status. Use `attempt count` and `last error code` for
diagnosis; the codes are safe categories such as `provider_timeout`,
`database_busy`, `conversion_error`, `lease_expired`, or `attempts_exhausted`,
never notification text or provider responses. A `processed` row may also keep
a `provider_*` code when repeated provider outages made it fall back to a
general family note.

Fixed school rules convert the known categories (for example the PRD example
`Sprawdzian` becomes a dated calendar entry for the named child). Anything the
rules do not recognise goes to classification, and if that cannot place it, it
becomes an unassigned family note with the notification text, so nothing is
dropped.

#### Requeue failed rows

After fixing the cause (for example a database or provider outage), select the
`failed` rows in the admin list and run **Requeue selected failed
notifications** (superusers only). They return to `pending` with a fresh
attempt budget; other statuses are ignored, and outputs already created are
never duplicated. The next sweep or restart converts them.

#### Retention and restarts

Raw title, message, and payload of `processed` rows are scrubbed after
`EDUVULCAN_RAW_RETENTION_DAYS` (default 90); admin then shows `Raw data
pruned` while IDs, content hashes (for duplicate detection), and output links
remain. `pending`, `processing`, and `failed` rows are never scrubbed. A
restart loses nothing: rows live in the database, the startup sweep converts
pending rows, and a stale `processing` lease is reclaimed once it expires.

#### Troubleshoot without exposing family data

Logs and error codes name only notification IDs, attempt numbers, and codes.
When reporting a problem, quote those, never the admin's title, message, or
payload values, and never a token secret. Only `WARNING` and above reach the
service logs by default, so a healthy conversion is silent; check the admin
status instead.

Neither health check returns notification data, counts, or error details.

#### Inspect conversion status

Each row in **Entries → Powiadomienia przychodzące** moves through these
statuses:

| Status | Meaning |
| --- | --- |
| `pending` | Stored and waiting for its first attempt, or for a scheduled retry (`next attempt at`). |
| `processing` | One worker holds a lease (`lease expires at`) for the current attempt. |
| `processed` | Its entries were saved; the inline lists every generated entry (a deleted entry leaves an empty link). |
| `failed` | Attempts ran out or the row cannot be converted; it waits for an operator. |

Filter the list by status. Use `attempt count` and `last error code` for
diagnosis; the codes are safe categories such as `provider_timeout`,
`database_busy`, `conversion_error`, `lease_expired`, or `attempts_exhausted`,
never notification text or provider responses. A `processed` row may also keep
a `provider_*` code when repeated provider outages made it fall back to a
general family note.

Fixed school rules convert the known categories (for example the PRD example
`Sprawdzian` becomes a dated calendar entry for the named child). Anything the
rules do not recognise goes to classification, and if that cannot place it, it
becomes an unassigned family note with the notification text, so nothing is
dropped.

#### Requeue failed rows

After fixing the cause (for example a database or provider outage), select the
`failed` rows in the admin list and run **Requeue selected failed
notifications** (superusers only). They return to `pending` with a fresh
attempt budget; other statuses are ignored, and outputs already created are
never duplicated. The next sweep or restart converts them.

#### Retention and restarts

Raw title, message, and payload of `processed` rows are scrubbed after
`EDUVULCAN_RAW_RETENTION_DAYS` (default 90); admin then shows
`[pruned]`-style placeholders while IDs, content hashes (for duplicate
detection), and output links remain. `pending`, `processing`, and `failed` rows
are never scrubbed. A restart loses nothing: rows live in the database, the
startup sweep converts pending rows, and a stale `processing` lease is
reclaimed once it expires.

#### Troubleshoot without exposing family data

Logs and error codes name only notification IDs, attempt numbers, and codes.
When reporting a problem, quote those, never the admin's title, message, or
payload columns, and never a token secret. Only `WARNING` and above reach the
service logs by default, so a healthy conversion is silent; check the admin
status instead.

## Verify the project

Run Django's system checks:

```bash
uv run python manage.py check
```

Run the test suite:

```bash
uv run python manage.py test
```

Check whether model changes are missing migrations:

```bash
uv run python manage.py makemigrations --check --dry-run
```

Audit the locked dependencies:

```bash
uv run --locked pip-audit
```

## Deploy to Mikr.us

Follow the [first-deployment runbook](context/changes/deployment/mikrus-runbook.md)
after completing its application-readiness checklist. It separates values copied
from the Mikrus panel, commands run locally, and commands run on the VPS.

After the server is bootstrapped, deploy an approved full commit SHA through the
repository-owned release script:

```bash
ssh familynotes-mikrus sh -s -- "<FULL_COMMIT_SHA>" \
  < scripts/deployment/release.sh
```
