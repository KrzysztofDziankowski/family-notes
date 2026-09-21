# FamilyNotes Mikr.us Integration and Deployment Plan

## Summary

Deploy FamilyNotes to Mikr.us 3.0 using a separately purchased dedicated Mikrus PostgreSQL service and a Mikrus-managed HTTPS subdomain. Production releases are human-approved and performed over SSH from the `main` branch; no external CI/CD system receives production credentials. The runtime consists of Django served by Gunicorn under systemd, with nginx serving static files and proxying application traffic.

The first release is a single-instance MVP. It does not introduce background workers, high availability, or production database access through MCP.

## Application Preparation

- Replace scaffold-only production values with environment-backed settings for `SECRET_KEY`, `DEBUG`, allowed hosts, CSRF trusted origins, PostgreSQL, static files, secure cookies, and proxy-aware HTTPS handling.
- Keep safe development defaults where practical, but make production fail fast when a required secret or host configuration is missing.
- Add `gunicorn` and `psycopg[binary]` to the locked application dependencies.
- Add `GET /healthz/`. A healthy response must confirm that Django can execute a minimal database query, return no sensitive details, and use a non-2xx status when the database is unavailable.
- Run production with one or two synchronous Gunicorn workers initially. Set a request timeout above the product's 30-second AI-classification limit and monitor memory before increasing concurrency.

## External Infrastructure Gates

The following steps require the account owner and must complete before the first release:

- Provision a Mikr.us 3.0 VPS and record its SSH hostname, assigned SSH port, public IPv6 address, and exposed HTTP port mapping.
- Open the purchased dedicated Mikrus PostgreSQL service and record its host, port, TLS mode, capacity, administrative credentials, and backup capabilities in a password manager.
- Create a dedicated `family_notes` database owned by a restricted `family_notes_app` login. The application login must not have superuser, database-creation, role-creation, or replication privileges.
- Restrict database network access to the application VPS when the service supports source allow-listing. Never expose PostgreSQL for routine developer access.
- Reserve the final Mikrus subdomain and map it to the application's exposed HTTP port. Use the Mikrus HTTPS layer for the public endpoint; do not install Certbot for this initial setup.
- Enable Mikr.us backup space if available and choose a separate destination for encrypted off-provider database copies.
- Add the operator's SSH public key before disabling password-based SSH access. Preserve provider console access as the recovery path.

## Server Bootstrap

- Create a non-login `familynotes` runtime user and a separate `deploy` user with only the permissions needed to manage releases and restart the application service.
- Install Git, curl, nginx, Python build headers, PostgreSQL client and development libraries, and `uv` from its documented installer.
- Create `/srv/family-notes/releases`, `/srv/family-notes/shared`, and `/var/www/family-notes/static`. Point `/srv/family-notes/current` at the active versioned release.
- Store production configuration in a root-owned, mode `0600` environment file such as `/etc/family-notes/env`. Never commit or print its values.
- Configure a systemd service that runs Gunicorn as `familynotes`, reads the environment file, starts from `/srv/family-notes/current`, restarts on failure, and logs to journald.
- Configure nginx to serve `/static/`, proxy all other requests to Gunicorn on a loopback socket or port, forward the original host and protocol headers, and expose `/healthz/` through the same application path.

Required production configuration:

```text
DJANGO_SECRET_KEY
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS
DJANGO_CSRF_TRUSTED_ORIGINS
DB_HOST
DB_PORT
DB_SSLMODE
DB_NAME
DB_USER
DB_PASSWORD
AUTH_PROVIDER_CLIENT_ID
AUTH_PROVIDER_CLIENT_SECRET
AI_PROVIDER_API_KEY
```

Use the exact authentication and AI-provider variable names introduced by their implementations if they differ. Keep placeholders out of the live environment: an integration that is not yet implemented remains disabled until its real credentials and callback URL are known. Store only the restricted application database credentials in this file; dedicated PostgreSQL administrator credentials remain in the password manager and are used only for database administration and recovery.

## Release Procedure

Every production release is run manually over SSH and records the deployed Git commit:

1. Confirm local tests pass and the intended commit is present on `main`.
2. On the server, fetch the repository and check out that exact commit into a new timestamped directory under `/srv/family-notes/releases/`.
3. Run `uv sync --locked` in the new release.
4. Load the production environment and run `uv run python manage.py check --deploy`.
5. Run `uv run python manage.py makemigrations --check --dry-run`; abort if model changes lack committed migrations.
6. Create a timestamped `pg_dump` before applying migrations and verify that the dump is non-empty.
7. Run `uv run python manage.py migrate --noinput` and `uv run python manage.py collectstatic --noinput`.
8. Atomically switch `/srv/family-notes/current` to the new release and restart the systemd service.
9. Verify the local and public health endpoints, inspect recent journald and nginx errors, and complete a browser smoke test.
10. Retain the current and at least two prior application releases. Remove older releases only after the new version is stable and its backup has been copied off-provider.

Do not automatically deploy on a push to `main`. Automated CI may run checks without production secrets, but production deployment remains the explicit SSH procedure above.

## Failure Support and Rollback

- **SSH connection failure:** verify the Mikr.us-assigned port, use an SSH host entry with the expected identity and `IdentitiesOnly yes`, then use the provider console if firewall or key changes locked out the operator.
- **Public subdomain failure:** confirm nginx listens on the address family required by Mikrus, the application port matches the provider mapping, DNS/subdomain activation has completed, and plain HTTP works internally before investigating the managed HTTPS layer.
- **Database connection failure:** test with `psql` from the VPS using the same host, port, database, application login, and TLS mode. Check the dedicated service status, source allow-list, credentials, certificate/TLS requirements, connection limit, and storage capacity without exposing passwords in shell history or logs.
- **Failed migration:** stop before switching the active release. Fix forward with a new migration when possible. Never reverse or restore a production database automatically.
- **Failed application start:** inspect `systemctl status`, journald, the environment-file permissions, Gunicorn import errors, and nginx upstream errors. Keep the previous release active until the new health check succeeds.
- **Post-release regression:** atomically repoint `current` to the previous release and restart the service. If the release applied a backward-incompatible schema change, roll forward with a corrective release; database restore requires human approval and a confirmed recovery point.
- **Memory pressure or OOM:** keep worker count low, inspect process RSS and kernel OOM logs, temporarily reduce concurrency, and isolate AI classification into a worker only when observed load justifies it.
- **Database growth:** review dedicated-service storage and connection usage weekly. Alert at 70% of purchased storage or connection capacity and start a capacity increase or cleanup plan at 85%.

## Backups, Monitoring, and Operations

- Confirm the dedicated service's provider-managed backup schedule and retention in the Mikrus panel. Treat it as one recovery layer, not the only backup.
- Run a daily PostgreSQL custom-format dump using the restricted application login where permissions allow, with timestamped filenames, retention, encryption for off-provider copies, and failure reporting.
- Perform and document a restore drill into a disposable database before the first production data is trusted, then repeat quarterly and after material schema changes.
- Use systemd and journald for process state and application logs, nginx access/error logs for edge diagnosis, and `/healthz/` for an external uptime check.
- Alert on health-check failure, repeated service restart, VPS disk pressure, backup failure, dedicated PostgreSQL availability, 70%/85% database capacity thresholds, connection saturation, and sustained memory pressure.
- Ensure logs contain no secrets, authorization headers, family-entry text, authentication tokens, or AI-provider payloads.
- Reboot the VPS once during acceptance testing to confirm nginx, PostgreSQL connectivity, and the application service recover automatically.

## Verification and Acceptance

Before deployment:

- `uv run python manage.py check`
- `uv run python manage.py makemigrations --check --dry-run`
- `uv run python manage.py test`
- `uv run --locked pip-audit` after dependency changes

Production acceptance criteria:

- `manage.py check --deploy` reports no unresolved production-critical findings.
- Local and public `/healthz/` checks return success while the database is available and fail without disclosing details when it is unavailable.
- The Mikrus HTTPS URL loads without certificate warnings, redirects or treats HTTP securely as supported by the Mikrus subdomain layer, and Django recognizes proxied requests as secure.
- Static assets load through nginx and `/admin/` renders correctly.
- The service survives a process restart and VPS reboot.
- A database dump can be restored into a disposable database and pass a basic integrity check.
- Switching to the previous application release restores service without changing the database.
- Once product views exist, access tests cover parent access, assigned-child access, another child's denial, and unauthenticated denial for every family-data path.

## Assumptions and Decisions

- `context/foundation/infrastructure.md` supersedes the older Railway deployment hint in `context/foundation/tech-stack.md`.
- Mikr.us 3.0, separately purchased dedicated Mikrus PostgreSQL, manual SSH releases, a Mikrus subdomain, and full MVP secret planning are approved choices.
- The app uses one production instance and one production database for the MVP.
- PostgreSQL runs as a dedicated Mikrus service, not on the application VPS. Its administrative credentials are never loaded by Django or stored on the VPS unless a root-only recovery procedure temporarily requires them.
- Destructive operations, secret rotation, database restoration, DNS changes, and account/billing changes always require direct human approval.
- Provider-specific ports, hostnames, quotas, and subdomain behavior must be confirmed in the Mikr.us panel during setup because they are assigned externally and may change.

## References

- [Mikr.us: Django with PostgreSQL](https://wiki.mikr.us/django_postgresql/)
- [Mikr.us: free VPS subdomain](https://wiki.mikr.us/darmowa_subdomena_dla_vps/)
- [Mikr.us: exposed ports](https://wiki.mikr.us/udostepnione_porty/)
- [Mikr.us: backups](https://wiki.mikr.us/strych_backupy/)
- [Django 5.2 deployment checklist](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/)
- [Gunicorn deployment documentation](https://gunicorn.org/deploy/)
