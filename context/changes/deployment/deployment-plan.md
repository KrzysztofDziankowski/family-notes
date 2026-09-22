# FamilyNotes Mikr.us Integration and Deployment Plan

## Deployment Outcome

Successfully deployed the latest release on 2026-09-22 at
`https://inodzik.bieda.it/` using commit
`513f9854b2d28489abb48873c23e24259f491d25` and release
`20260922T063107Z-513f9854b2d2`. The live stack is nginx on HTTP port `20121`,
Gunicorn under `family-notes.service`, a Unix application socket, Mikrus-managed
public HTTPS, and dedicated Mikrus PostgreSQL. The detailed deployment record and
reusable operational procedure are in `mikrus-runbook.md`.

The active release path is
`/srv/family-notes/releases/20260922T063107Z-513f9854b2d2`. The deployment helper,
service status, exact checked-out commit, internal health endpoint, and public
health endpoint were verified after activation. Before the preceding release, a
verified non-empty database dump was saved as
`/var/backups/family-notes/pre-release-20260922T063107Z-513f9854b2d2.dump`.

Direct root SSH access from the development machine is blocked. Root login rejects
the available SSH identity, so the agent and the `deploy` account cannot install or
repair `/usr/local/sbin/family-notes-deploy`, change sudoers, or modify root-owned
service configuration. These exceptional tasks require the account owner to use
the Mikrus provider console or another explicitly authorized root-capable access
path. Routine releases do not require root login once the root-owned helper and its
narrow sudo rule are installed.

Application serving is complete. Recurring backups, off-provider retention,
external uptime monitoring, alerting, a restore drill, and a tested rollback are
operational follow-ups until separately recorded as complete.

## Summary

Deploy FamilyNotes to Mikr.us 3.0 using a separately purchased dedicated Mikrus PostgreSQL service and a Mikrus-managed HTTPS subdomain. Production releases are human-approved and performed over SSH from the `master` branch; no external CI/CD system receives production credentials. The runtime consists of Django served by Gunicorn under systemd, with nginx serving static files and proxying application traffic.

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
- Use `inodzik.bieda.it`, the hostname configured in `DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS`, backed by nginx listening on plain HTTP at `[::]:20121`. Mikrus terminates public HTTPS; do not install Certbot or configure nginx TLS. The older automatic hostname `ula121-20121.wykr.es` is not an accepted application host and returns HTTP 400.
- Enable Mikr.us backup space if available and choose a separate destination for encrypted off-provider database copies.
- Add the operator's SSH public key before disabling password-based SSH access. Preserve provider console access as the recovery path.
- Treat direct root SSH from the development machine as unavailable. Perform privileged bootstrap and exceptional repair through the Mikrus provider console or another owner-authorized root-capable path; do not broaden the `deploy` account's sudo permissions as a workaround.

## Server Bootstrap

- Create a non-login `familynotes` runtime user and a separate `deploy` user that owns release preparation. Install a root-owned `/usr/local/sbin/family-notes-deploy` helper and grant `deploy` passwordless sudo access to that helper only. The helper validates release IDs and exposes only checks, backup, activation, rollback, status, application-log, and acceptance-reboot operations.
- Install Git, curl, nginx, Python build headers, PostgreSQL client and development libraries, and `uv` from its documented installer.
- Create `/srv/family-notes/releases`, the bare repository at `/srv/family-notes/repository/project.git`, and `/var/www/family-notes/static`. Point `/srv/family-notes/current` at the active versioned release.
- Store production configuration in a root-owned, mode `0600` environment file such as `/etc/family-notes/env`. Never commit or print its values, and do not grant `deploy` read access; the restricted helper loads it and passes the environment only to commands running as `familynotes`.
- Configure a systemd service that runs Gunicorn as `familynotes`, reads the environment file, starts from `/srv/family-notes/current`, disables the unused Gunicorn control socket, restarts on failure, and logs to journald.
- Configure nginx to serve `/static/` and proxy all other requests to `/run/family-notes/gunicorn.sock`. Set `Host`, `X-Real-IP`, `X-Forwarded-For`, and exactly one `X-Forwarded-Proto: https` header explicitly; do not include Debian's conflicting `proxy_params` file.

Required production configuration:

```text
DJANGO_SECRET_KEY
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS
DJANGO_CSRF_TRUSTED_ORIGINS
DJANGO_STATIC_ROOT
DB_ENGINE=postgresql
DB_HOST
DB_PORT
DB_SSLMODE
DB_NAME
DB_USER
DB_PASSWORD
```

Authentication-provider and AI-provider variables are not required until those integrations are implemented. Add their exact names and real values at that time; never deploy placeholders. Store only the restricted application database credentials in this file; dedicated PostgreSQL administrator credentials remain in the password manager and are used only for database administration and recovery.

## Release Procedure

Every production release is initiated from the development machine with
`scripts/deployment/release.sh`, streamed to one SSH session running as `deploy`.
The script records and deploys an explicitly approved full Git commit SHA:

1. Confirm local tests pass and the intended commit is pushed to `master`; record its full SHA.
2. Invoke `ssh familynotes-mikrus sh -s -- "<FULL_COMMIT_SHA>" < scripts/deployment/release.sh` from the repository.
3. The script fetches the bare server repository, creates a detached timestamped worktree for that exact SHA under `/srv/family-notes/releases/`, and runs `uv sync --locked --no-dev`.
4. As `deploy`, invoke the restricted helper's `check` action. It loads `/etc/family-notes/env` and runs the deployment and migration checks as `familynotes` without exposing secrets.
5. As `deploy`, invoke the helper's `backup` action to create a timestamped `pg_dump` and verify that it is non-empty.
6. As `deploy`, invoke the helper's `activate` action. It runs backward-compatible migrations and static collection as `familynotes`, atomically switches `/srv/family-notes/current`, restarts `family-notes.service`, and verifies that it is active.
7. The script verifies service status and the Unix-socket health endpoint. Verify the public health endpoint, inspect journald through the helper, and complete a browser smoke test.
8. Retain the current and at least two prior application releases. Remove older releases only after the new version is stable and its backup has been copied off-provider.

Do not automatically deploy on a push to `master`. Automated CI may run checks without production secrets, but production deployment remains the explicit SSH procedure above.

## Failure Support and Rollback

- **SSH connection failure:** verify the Mikr.us-assigned port, use an SSH host entry with the expected identity and `IdentitiesOnly yes`, then use the provider console if firewall or key changes locked out the operator.
- **Root access required:** direct root SSH from the development machine is blocked. Ask the account owner to run the documented root-only command through the Mikrus provider console or another authorized root-capable session. Do not copy secrets to the `deploy` account or grant unrestricted sudo.
- **Public subdomain failure:** confirm nginx listens on the address family required by Mikrus, the application port matches the provider mapping, DNS/subdomain activation has completed, and plain HTTP works internally before investigating the managed HTTPS layer.
- **Database connection failure:** test with `psql` from the VPS using the same host, port, database, application login, and TLS mode. Check the dedicated service status, source allow-list, credentials, certificate/TLS requirements, connection limit, and storage capacity without exposing passwords in shell history or logs.
- **Failed migration:** stop before switching the active release. Fix forward with a new migration when possible. Never reverse or restore a production database automatically.
- **Failed application start:** inspect `systemctl status`, journald, the environment-file permissions, Gunicorn import errors, and nginx upstream errors. Keep the previous release active until the new health check succeeds.
- **Post-release regression:** atomically repoint `current` to the previous release and restart the service. If the release applied a backward-incompatible schema change, roll forward with a corrective release; database restore requires human approval and a confirmed recovery point.
- **Memory pressure or OOM:** keep worker count low, inspect process RSS and kernel OOM logs, temporarily reduce concurrency, and isolate AI classification into a worker only when observed load justifies it.
- **Database growth:** review dedicated-service storage and connection usage weekly. Alert at 70% of purchased storage or connection capacity and start a capacity increase or cleanup plan at 85%.

## Backups, Monitoring, and Operations

The items in this section remain pending unless a later deployment record marks
them complete:

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
- The homepage renders correctly through nginx, and `/admin/` returns 404 because the Django administration endpoint is intentionally disabled.
- The service survives a process restart and VPS reboot.
- A database dump can be restored into a disposable database and pass a basic integrity check.
- Switching to the previous application release restores service without changing the database.
- Once product views exist, access tests cover parent access, assigned-child access, another child's denial, and unauthenticated denial for every family-data path.

Current acceptance status:

- Confirmed for release `20260922T063107Z-513f9854b2d2`: exact commit `513f9854b2d28489abb48873c23e24259f491d25`; local Django checks, migration check, and all four tests; production deployment check with only the expected HSTS subdomain/preload warnings; verified non-empty database dump; no pending migrations; static collection; active `family-notes` service with two Gunicorn workers; successful deployment-helper health check after service startup; successful internal and public `/healthz/` responses; homepage HTTP 200 over HTTPS after activation; and disabled `/admin/` route returning HTTP 404 over HTTPS.
- Not yet evidenced in the repository: reboot survival, scheduled backup execution, off-provider backup copy, disposable restore drill, external uptime alerting, capacity alerts, and rollback rehearsal.

## Assumptions and Decisions

- This deployed plan supersedes both the older Railway hint in `context/foundation/tech-stack.md` and the shared-PostgreSQL recommendation in `context/foundation/infrastructure.md`; the later operator decision is dedicated Mikrus PostgreSQL.
- Mikr.us 3.0, separately purchased dedicated Mikrus PostgreSQL, manual SSH releases, a Mikrus subdomain, and full MVP secret planning are approved choices.
- The app uses one production instance and one production database for the MVP.
- PostgreSQL runs as a dedicated Mikrus service, not on the application VPS. Its administrative credentials are never loaded by Django or stored on the VPS unless a root-only recovery procedure temporarily requires them.
- Destructive operations, secret rotation, database restoration, DNS changes, and account/billing changes always require direct human approval.
- Direct root SSH access from the development machine is blocked. Initial server configuration and exceptional maintenance therefore require the account owner to use the Mikrus provider console or another explicitly authorized root-capable path. Routine deployment and application rollback are performed from the `deploy` account through the root-owned, narrowly scoped deployment helper and do not require direct root login.
- Provider-specific ports, hostnames, quotas, and subdomain behavior must be confirmed in the Mikr.us panel during setup because they are assigned externally and may change.

## References

- [Mikr.us: Django with PostgreSQL](https://wiki.mikr.us/django_postgresql/)
- [Mikr.us: free VPS subdomain](https://wiki.mikr.us/darmowa_subdomena_dla_vps/)
- [Mikr.us: exposed ports](https://wiki.mikr.us/udostepnione_porty/)
- [Mikr.us: backups](https://wiki.mikr.us/strych_backupy/)
- [Django 5.2 deployment checklist](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/)
- [Gunicorn deployment documentation](https://gunicorn.org/deploy/)
