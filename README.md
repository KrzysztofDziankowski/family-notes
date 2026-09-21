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
uv run python manage.py runserver
```

Open <http://127.0.0.1:8000/> in your browser. The project is currently a Django scaffold, so the default Django startup page is expected.

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
