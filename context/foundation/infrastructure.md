---
project: family-notes
researched_at: 2026-09-21
recommended_platform: Mikr.us 3.0 with shared PostgreSQL
runner_up: Render
context_type: greenfield
tech_stack: Python 3, Django 5.2, WSGI, PostgreSQL, uv
---

# Infrastructure

## Decision

Deploy the FamilyNotes MVP on **Mikrus 3.0** in Finland and use the PostgreSQL database shared by Mikr.us. The user selected this option after reviewing Render, Railway, Fly.io, GCP, AWS, serverless databases, and lower-cost SQL alternatives.

Mikrus 3.0 costs **130 PLN per year** (10.83 PLN/month equivalent) and provides 2 GB RAM and 25 GB SSD. The extra memory over Mikrus 2.1 is appropriate for Django, Gunicorn, deployment operations, and overlapping external AI requests. The application and database remain with one provider, persistent processes are supported for future workers, and the annual cost is substantially lower than managed PaaS alternatives.

This is a cost-and-control decision, not a managed-platform decision. The team owns operating-system updates, process supervision, TLS and proxy configuration, application deployment, monitoring, backups, and recovery. Mikr.us describes its shared database as an auxiliary shared service with a nominal 100 MB per-user allowance and no dedicated resource guarantee. Those constraints are acceptable for the small MVP only if database growth and backups are monitored.

Primary references:

- [Mikrus plans and capabilities](https://mikr.us/)
- [Mikrus Django and shared PostgreSQL guide](https://wiki.mikr.us/django_postgresql/)
- [Shared database limits](https://wiki.mikr.us/wspoldzielone_bazy_danych/)
- [Technical limitations](https://wiki.mikr.us/ograniczenia_techniczne_mikrusa/)
- [Mikrus operating philosophy and backup responsibility](https://mikr.us/idea)

## Interview Inputs

| Question | Answer | Effect on decision |
| --- | --- | --- |
| Persistent connections | Not needed for MVP; may be needed later | A long-lived VPS remains useful for future workers or WebSockets. |
| Cost versus developer experience | Equal | Mikr.us wins on cost but must retain a concrete operations runbook. |
| Existing platform familiarity | None | Familiarity did not break ties. |
| Geographic reach | One client location; global latency unnecessary | A single Finland region is sufficient. |
| Service co-location | Preferred for simplicity | Mikr.us app plus Mikr.us shared PostgreSQL satisfies the preference. |

## Hard-Constraint Screening

The application requires Python, Django 5.2, a WSGI-capable runtime, and a transactional SQL database. PostgreSQL remains the selected database because changing engines yields little savings and would introduce migration risk.

| Platform | Fit | Screening result |
| --- | --- | --- |
| Mikr.us | Native Linux process plus shared PostgreSQL | Keep |
| Render | Native Python/Django plus managed PostgreSQL | Keep |
| Railway | Native Django plus provider-hosted PostgreSQL | Keep; database is explicitly unmanaged |
| GCP Cloud Run + Cloud SQL/Neon | Containerized Django plus PostgreSQL | Keep; larger control surface or two providers |
| Fly.io | Machines plus managed PostgreSQL | Keep; managed database cost is disproportionate |
| Cloudflare Workers | Django support added in Python Workers; D1 adapter has no Django transactions | Drop for this MVP database contract |
| Vercel | Django runs in the Python runtime, which was Beta when checked | Drop; serverless constraints and external database add no benefit |
| Netlify | No first-class Python/Django application runtime | Drop |
| AWS | App Runner/RDS or Lightsail can run the stack | Drop from shortlist due cost and operational surface |

Non-GA status was checked on **2026-09-21**. Vercel's Python runtime was documented as **Beta**. Cloudflare's first-class Django documentation was newly published in September 2026; its D1 Django backend documents transaction rollback as unsupported. Mikr.us advertises MCP access, but a stable public MCP reference and versioned support contract were not found, so it is scored Partial rather than Pass.

## Agent-Friendly Comparison

Scoring uses Pass = 2, Partial = 1, Fail = 0. Platform compatibility and interview preferences take precedence over the numeric score.

| Platform | CLI-first | Managed | Agent-readable docs | Scriptable deploy | Agent integration | Score | Position |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Render | Pass | Pass | Pass | Pass | Pass | 10/10 | Runner-up; strongest operational simplicity |
| GCP Cloud Run + Neon | Pass | Pass | Pass | Pass | Pass | 10/10 | Third; two control planes and more configuration |
| Railway | Pass | Partial | Pass | Pass | Pass | 9/10 | Fourth; PostgreSQL operations remain customer-owned |
| Mikr.us | Partial | Fail | Partial | Partial | Partial | 4/10 | Selected for cost, co-location, and persistent-process flexibility |
| Fly.io | Pass | Pass | Pass | Pass | Partial | 9/10 | Managed PostgreSQL starts far above MVP budget |
| Vercel | Pass | Pass | Pass | Pass | Pass | 10/10 | Runtime was Beta; weaker fit for conventional Django |
| Cloudflare | Pass | Pass | Pass | Pass | Pass | 10/10 | Database transaction mismatch |
| Netlify | Pass | Pass | Pass | Pass | Pass | 10/10 | Runtime mismatch |
| AWS | Pass | Pass | Pass | Pass | Partial | 9/10 | Excess cost and configuration for this MVP |

The matrix makes an important distinction: Mikr.us is usable by an agent because SSH is scriptable, but the agent must create the deployment system that managed platforms provide. Its score therefore reflects platform affordances, not whether an experienced agent can administer Linux.

Research references include [Render's Django guide](https://render.com/docs/deploy-django), [Render CLI](https://render.com/docs/cli), [Railway's Django guide](https://docs.railway.com/guides/django), [Railway pricing](https://docs.railway.com/pricing/plans), [Fly.io pricing](https://fly.io/pricing/), [Google's Django on Cloud Run guide](https://docs.cloud.google.com/python/django/run), [Neon agent tooling](https://neon.com/docs/ai/ai-rules-neon-toolkit), [Cloudflare's Django support](https://developers.cloudflare.com/workers/languages/python/packages/django/), [Vercel's Python runtime](https://vercel.com/docs/functions/runtimes/python), and [Netlify Functions](https://docs.netlify.com/build/functions/get-started/).

## Anti-Bias Cross-Check

### Devil's Advocate

1. Mikr.us is a low-cost LXC VPS service for enthusiasts, not a managed application platform; every missing operational layer becomes project work.
2. Shared PostgreSQL has a nominal 100 MB allowance, shared performance, and no stated resource guarantee, creating an uncertain ceiling for a data-bearing production service.
3. Two gigabytes of RAM is modest once the OS, Gunicorn workers, deployment commands, monitoring, and future background workers coexist.
4. There are no native immutable releases, health-gated traffic switches, or one-command application rollback semantics.
5. Shared IPv4 and platform-specific port exposure complicate networking compared with a PaaS-owned HTTPS endpoint.

### Pre-Mortem

Six months after launch, FamilyNotes became unreliable even though traffic remained small. The initial deployment worked, so operating-system patching and restore drills were postponed. A routine package upgrade later restarted services with an incompatible configuration, and the application stayed unavailable because monitoring only checked the process, not an authenticated database-backed request. Meanwhile, the shared PostgreSQL database had quietly approached its informal 100 MB allowance because old classification records and Django sessions were never pruned. No one noticed: database size was not measured and application logs rotated locally. During recovery, the latest backup turned out to be incomplete and had never been restored in a test environment. The deployment script could reinstall the previous application revision, but a forward-only schema migration prevented that revision from starting. Memory pressure then killed a Gunicorn worker whenever two classification calls overlapped, producing duplicate submissions when users retried. Finally, an agent with unrestricted root SSH attempted an otherwise routine proxy change and temporarily removed external access. The platform itself remained online throughout; the failure came from assuming that cheap co-location also supplied managed operations, reversible releases, tested backups, and least-privilege access.

### Unknown Unknowns

- The shared PostgreSQL service's actual backup retention, restoration procedure, maintenance windows, and noisy-neighbor behavior are not specified publicly.
- The practical memory profile of Django plus concurrent 30-second classification calls on this LXC host is unknown until load-tested.
- The stability and permission boundaries of the advertised Mikr.us MCP integration are not sufficiently documented for production use.
- The behavior of custom-domain TLS and forwarded ports during host migration or recovery needs verification.
- The project's eventual data growth relative to the informal 100 MB shared-database allowance is unknown.

## Operational Story

### Preview

There is no provider-managed preview environment. Pull requests run tests in GitHub Actions. A temporary preview, when genuinely needed, runs as a separate systemd service on an unprivileged port against a separate database; it is removed after review. Production data is never copied into preview.

### Secrets

Production secrets live in a root-owned environment file outside the repository, readable only by the dedicated application user and root. systemd loads it with `EnvironmentFile`. The file contains `SECRET_KEY`, database credentials, external authentication credentials, AI-provider credentials, allowed hosts, and secure-cookie settings. Secrets are never placed in Git, shell history, agent conversation, or MCP configuration.

### Deploy

Deploy over SSH with a non-root deployment account. Each release is checked out into a timestamped directory, dependencies are installed with `uv sync --locked`, Django checks and migrations run, static assets are collected, and a `current` symlink is switched only after verification. Gunicorn runs under systemd as a dedicated unprivileged user. A reverse proxy terminates HTTPS and forwards to Gunicorn. Keep at least three application releases.

The first deployment may require manual account purchase, SSH-key registration, domain configuration, shared PostgreSQL provisioning, and secret entry. No production mutation occurs without the user approving the deployment plan.

### Rollback

Application rollback switches `current` to the preceding release and restarts the systemd service. Every database migration must be backward-compatible with the prior application release. Destructive schema changes use an expand-and-contract sequence and are deferred until a later release. A database backup is taken before migrations, but restoring it is a human-approved incident operation, not an automatic deploy step.

### Logs and Monitoring

Gunicorn writes structured application logs to stdout/stderr for journald. Use `journalctl -u family-notes` for runtime logs and retain enough history to investigate authorization incidents. Add an external HTTPS uptime check and a local health endpoint that verifies application and database readiness without exposing sensitive data. Alert on service failure, disk usage, memory pressure, database errors, certificate expiry, and shared-database size.

### Backups

Run a daily `pg_dump` to Mikr.us backup space and copy a second encrypted backup off-provider. Retain daily backups for 14 days and monthly backups for three months during the MVP. Run and document a restore drill before launch and at least quarterly. A backup is not considered valid until restoration has been verified.

### Access Boundary

Agents may use a deployment account with access to release directories, application logs, and controlled service restart commands. Root access, database deletion, backup deletion, firewall changes, primary-secret rotation, and destructive migrations require explicit human approval. Production database MCP access is not enabled for routine work.

## Risk Register

| Risk | Likelihood | Impact | Mitigation | Source lens |
| --- | --- | --- | --- | --- |
| Shared database reaches its informal 100 MB allowance | Medium | High | Measure weekly; prune sessions; alert at 60/80%; prepare migration to managed PostgreSQL | Research finding |
| Shared database performance or availability degrades | Medium | High | Health checks, retry-safe reads, provider-independent dumps, documented migration path | Unknown unknowns |
| Backup exists but cannot be restored | Medium | Critical | Daily dumps, off-provider encrypted copy, pre-launch and quarterly restore drills | Pre-mortem |
| OS or package maintenance breaks the service | Medium | High | Security update cadence, staged changes, versioned config, health verification | Devil's advocate |
| Irreversible migration defeats application rollback | Medium | Critical | Expand-and-contract migrations and pre-migration backup | Pre-mortem |
| Two concurrent classification requests exhaust memory | Medium | High | Load test, bound Gunicorn workers/timeouts, monitor RSS, cap request concurrency | Unknown unknowns |
| Agent with broad SSH privileges causes an outage | Low | Critical | Dedicated deploy account, constrained sudo, human approval for irreversible actions | Pre-mortem |
| IPv4 forwarding or custom-domain path fails after infrastructure change | Low | High | Document port mapping, monitor public HTTPS, verify recovery procedure | Unknown unknowns |
| Local logs disappear before an authorization incident is investigated | Medium | High | Journald retention policy and optional off-host log shipping | Pre-mortem |
| Mikr.us MCP behavior or permissions change | Medium | Medium | Treat MCP as optional; use SSH and documented scripts as the stable path | Research finding |

## Exit Triggers

Reassess the platform and prefer Render or GCP with managed PostgreSQL when any of these occurs:

- Shared database size exceeds 60 MB or growth projects exhaustion within six months.
- Database reliability or backup recovery cannot meet the application's needs.
- Memory pressure persists after right-sizing Gunicorn and classification concurrency.
- More than one application replica is required.
- Routine operations consume more developer time than the managed-hosting price difference.
- FamilyNotes expands beyond the single-family MVP or gains uptime commitments.

## Next Step

Create a read-only deployment plan in Plan Mode using this document and `context/foundation/tech-stack.md`. The plan must specify manual account gates, SSH hardening, shared PostgreSQL provisioning, domain and TLS setup, systemd and reverse-proxy configuration, versioned releases, migrations, backup/restore verification, monitoring, and rollback tests before making any production change.
