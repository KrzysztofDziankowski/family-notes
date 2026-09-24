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

With the local server running, verify these routes:

- <http://localhost:20121/accounts/google/login/> starts Google sign-in for an allowed test user.
- <http://localhost:20121/account/> requires authentication and shows the configured display name and role, or a generic not-configured state.
- <http://localhost:20121/admin/> accepts the credentials created by `createsuperuser`; normal staff and family accounts are denied.
- <http://localhost:20121/healthz/> returns `{"status": "ok"}` while the database is available.

For production, register
`https://YOUR_DOMAIN/accounts/google/login/callback/` separately and store the
real credentials only in the protected server environment and password manager.

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
