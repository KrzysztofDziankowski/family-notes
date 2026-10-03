---
date: 2026-10-01T22:28:57+02:00
researcher: Codex
git_commit: 4bfba8ea16118975a989979208dbfa4adb6d3b67
branch: master
repository: 10xdev
topic: "Ground rollout Phase 1: production security and schema safety"
tags: [research, security, authorization, postgresql, migrations, deployment]
status: complete
last_updated: 2026-10-01
last_updated_by: Codex
---

# Research: Production security and schema safety

**Date**: 2026-10-01T22:28:57+02:00
**Researcher**: Codex
**Git Commit**: 4bfba8ea16118975a989979208dbfa4adb6d3b67
**Branch**: master
**Repository**: 10xdev

## Research Question

Ground rollout Phase 1 of `context/foundation/test-plan.md` by verifying Risk #1
(administrative privilege boundaries and login-abuse defenses), Risk #2 (safe
PostgreSQL forward migration and failure recovery), and Risk #3 (family ownership
and least privilege across sessions and automation tokens). Verify the response
guidance rather than accepting it as an implementation description.

## Summary

- **Risk #1 is only partly protected.** The installed custom admin site admits an
  active superuser and rejects other identities at the site boundary
  (`family_notes/apps.py:4-5`, `family_notes/admin.py:4-6`). The public deployment
  exposes `/admin/` through its general nginx proxy (`context/changes/deployment/mikrus-runbook.md:484-510`). In the inspected settings, dependencies, and nginx configuration, there is no admin-login throttle, lockout, MFA, or admin-specific network restriction. Superuser-only admission therefore proves authorization, not resistance to repeated password attempts.
- **Risk #2 is not yet proved on the production engine.** Production can select
  PostgreSQL, but the default database is SQLite (`family_notes/settings.py:229-258`).
  The inspected repository has focused migration tests but no PostgreSQL test
  harness. The release path creates a custom-format dump, verifies only that the
  file is non-empty, then applies migrations while the prior application remains
  live (`scripts/deployment/family-notes-deploy:133-153`). A restore drill and
  migration-failure recovery rehearsal are explicitly still follow-up work
  (`context/changes/deployment/mikrus-runbook.md:847-852`).
- **Risk #3 has strong request-path defenses but no single complete proof.** Session
  queries derive an active membership and scope by its family
  (`family_access/access.py:6-36`); automation authentication reloads the token,
  member, family, and user and rejects stale authority (`family_access/automation.py:34-73`).
  Existing feature tests cover many hostile identities, but model/admin bypasses
  and several matrix cells remain. Planning must also preserve the later MS-01
  decision: parent-owned tokens may read their family's entries through one
  read-only API (`context/foundation/roadmap.md:202-212`), superseding the PRD v2
  write-only statements (`context/foundation/prd.md:145-158`).

The Phase 1 response guidance is directionally correct. It needs three refinements:
admin testing must pair authorization with a selected abuse defense; migration
testing must exercise PostgreSQL, intermediate live-upgrade states, and actual
restore; authorization testing must express token authority per endpoint rather
than treating automation as globally write-only.

## Detailed Findings

### Risk #1: administrative privilege and login abuse

#### Observed boundary

`FamilyNotesAdminConfig` replaces Django's default site with
`SuperuserAdminSite` (`family_notes/apps.py:4-5`). Its site-wide predicate requires
`is_active` and `is_superuser`, which is stronger than Django's default active-staff
predicate (`family_notes/admin.py:4-6`). The project mounts the site at the public
`/admin/` route (`family_notes/urls.py:32-40`). Current root-route tests cover an
anonymous redirect, rejection of one active staff non-superuser, and admission of
one active superuser (`family_notes/tests.py:26-57`). They do not directly cover a
normal non-staff user, an inactive superuser, or representative privileged POSTs.

The admin accepts local Django credentials because `ModelBackend` remains enabled
beside allauth (`family_notes/settings.py:283-286`). The runbook proxies the whole
site through one public nginx location and supplies forwarding headers but no
admin-specific access control (`context/changes/deployment/mikrus-runbook.md:484-510`).
Its current production smoke checks HTTPS, anonymous redirect, active-superuser
admission, and normal-family denial (`context/changes/deployment/mikrus-runbook.md:798-802`).

#### Missing abuse defense

Within the inspected application settings, dependency manifest, deployment scripts,
and nginx example, no failed-login threshold, lockout, MFA requirement, IP allowlist,
or admin-specific request limit is configured. Generic nginx and Gunicorn access
logs provide operational traces, but the inspected deployment contract defines no
failed-admin-login alert or evidence threshold.

Current django-allauth documentation says its account rate limits depend on correct
client-IP resolution behind proxies and documents `secure_admin_login` as the wrapper
that extends allauth rate limiting and MFA to the Django admin. The current admin
site is not wrapped that way. This upstream option is evidence of an available
mechanism, not a decision to adopt it; nginx limiting, a maintained lockout package,
network restriction, or allauth protection still requires an explicit design choice
([django-allauth admin security documentation](https://github.com/pennersr/django-allauth/blob/main/docs/common/admin.rst),
[django-allauth rate-limit documentation](https://github.com/pennersr/django-allauth/blob/main/docs/common/rate_limits.rst)).

#### Cheapest useful proof

Use Django integration tests for the site-wide permission matrix and representative
sensitive GET/POST/action paths. Add a deterministic test at the layer where the
chosen login-abuse policy lives. Retain a narrow production smoke for HTTPS routing,
account admission/denial, rate-limit behavior, safe logging, and operator recovery.
Testing admin appearance would not address this risk.

### Risk #2: PostgreSQL forward migration and recovery

#### Schema history and current proof

The schema includes conditional uniqueness for active membership
(`family_access/migrations/0001_initial.py:76-82`), notification deduplication
constraints (`entries/migrations/0002_inboundnotification.py:14-37`), and conversion
indexes/check constraints (`entries/migrations/0003_notification_conversion.py:55-92`).
Migration `0005` adds database defaults so pre-conversion code can insert after a
code-only rollback (`entries/migrations/0005_inbound_notification_db_defaults.py:1-24`).

The focused forward test migrates exactly `entries` 0002 to 0003 and checks one
pending row plus the newly added defaults (`entries/tests/test_conversion_models.py:248-293`).
Final-schema compatibility tests exercise pre-0003 inserts
(`entries/tests/test_conversion_models.py:296-345`). These are useful signals on the
configured test database, but with the default settings they run on SQLite and do
not prove PostgreSQL DDL, constraints, locks, or the complete migration graph.

There is a specific historical live-upgrade hazard worth rehearsing: 0003 adds two
non-null lifecycle columns without persistent database defaults
(`entries/migrations/0003_notification_conversion.py:30-39`), and 0005 adds those
defaults later (`entries/migrations/0005_inbound_notification_db_defaults.py:15-24`).
Because activation runs `migrate` before switching code and restarting the service
(`scripts/deployment/family-notes-deploy:145-153`), old intake code could encounter
the intermediate schema while a database at 0002 advances to the leaf. The inspected
repository does not record the current production migration inventory, so the
scenario may be historical for today's database but remains a valid full-history
rehearsal case.

#### Deployment and recovery contract

The preflight runs Django deployment checks and a migration-drift check, not a
migration plan or rehearsal (`scripts/deployment/family-notes-deploy:124-132`). The
backup command runs `pg_dump -Fc` with the application role and checks that the file
has bytes (`scripts/deployment/family-notes-deploy:133-143`). That condition does not
prove restorable contents, object ownership, constraints, or data integrity.

On readiness failure, the activated release and pre-release dump stay in place;
the automation does not reverse migrations or restore data
(`context/changes/deployment/mikrus-runbook.md:719-739`). Application rollback changes
the release symlink without reversing schema, and an incompatible schema requires a
forward fix or a separate human-approved database recovery
(`context/changes/deployment/mikrus-runbook.md:1112-1133`). This is a sound
non-destructive default, but restore capability and compatibility are not proved.

#### Cheapest useful proof

Use a disposable PostgreSQL instance and run named predecessor-to-leaf rehearsals
with representative rows from both project apps. Verify values, foreign keys,
named uniqueness/check constraints, indexes, and old-code writes. Add a failure
scenario after at least one migration is committed, then prove the documented
forward-fix decision path. Separately restore the actual custom-format dump into a
clean disposable database, migrate/check it, and compare defined integrity
invariants. Keep destructive production rollback outside automation.

### Risk #3: family ownership and least privilege

#### Authority model and request paths

The identity chain is Django user to `FamilyMember` to `Family`; the database permits
at most one active membership per user (`family_access/models.py:23-51`). Session
resolution selects an active membership in an active family, and shared scoping
filters by that membership's family (`family_access/access.py:6-36`). Child reads
also require the same active family and the exact assigned child unless the actor is
a parent (`family_access/access.py:39-51`).

Automation tokens belong to a member and store a digest, expiry/revocation state,
and usage timestamp (`family_access/models.py:57-112`). On each request,
authentication reloads related authority and rejects revoked, expired, demoted,
inactive-member/family, and inactive-user cases before attaching the server-derived
membership (`family_access/automation.py:34-73`). Entry intake and read endpoints
derive family scope from that membership rather than client input
(`entries/api_views.py:86-124`, `entries/api_views.py:242-254`).

Parent session writes re-derive parent authority and family ownership in services;
assignees must be active members of that same family (`entries/services.py:21-64`,
`entries/services.py:91-137`). Child list/detail paths call a service that filters by
both family and assigned membership (`entries/services.py:244-257`). Background
conversion gets authority from each persisted notification's family and resolves
assignees within that family (`entries/eduvulcan/conversion.py:276-295`,
`entries/services.py:284-327`).

#### Existing evidence and gaps

The current suite has substantial feature-local coverage: parent-management denial
and non-effect cases (`entries/tests/test_manage_access.py:53-179`), child ownership
and indistinguishable missing/foreign cases (`entries/tests/test_child_views.py:215-270`),
token lifecycle failures (`family_access/tests/test_automation.py:212-318`), read-API
family separation/channel separation/method denial (`entries/tests/test_entries_api.py:370-482`,
`entries/tests/test_entries_api.py:557-645`), and intake family binding with rejected
tokens writing nothing (`entries/tests/test_notification_intake.py:38-94`,
`entries/tests/test_notification_intake.py:173-191`). These tests do not form one
normalized authority-by-channel-by-operation matrix.

The inspected paths expose four hardening gaps:

1. `AutomationToken.issue()` calls `save()` without `full_clean()`, while parent-only
   issuance exists in `clean()` and admin choice filtering, not a database constraint
   (`family_access/models.py:61-66`, `family_access/models.py:91-119`). Request
   authentication rejects a child-owned token, so this is issuance-integrity debt,
   not a demonstrated endpoint escalation.
2. `Entry.family`, `assigned_member`, and `created_by` are independent foreign keys;
   service code enforces same-family relationships, but direct ORM/admin paths have
   no database equality constraint (`entries/models.py:24-78`). The mutable Entry
   admin is therefore a trusted bypass requiring its own invariant proof
   (`entries/admin.py:9-13`).
3. Session membership resolution checks authentication and membership/family state
   but not `user.is_active` itself (`family_access/access.py:6-14`). Authentication
   backends normally reject inactive users, but the shared helper has no independent
   fail-closed guarantee for direct service use.
4. Token authority is deliberately endpoint-specific. MS-01 authorizes intake POST
   and family-scoped entries GET while denying entry mutation and signed-in UI use
   (`context/foundation/roadmap.md:202-212`). Tests must not encode the older PRD v2
   statement that tokens can never read family data (`context/foundation/prd.md:145-158`).

#### Cheapest useful proof

Build one Django integration matrix covering session parent capture/CRUD, assigned
child list/detail, token intake POST, token entry GET, method-denied token mutations,
session/token channel confusion, conversion ownership, and admin as an explicit
trusted override. For denied cases, assert response, unchanged rows, absence of
foreign sentinels/counts/IDs, and immediate deactivation or revocation. Add focused
model/admin tests for child-token issuance and cross-family relational consistency;
decide during planning whether to harden these with service validation, admin forms,
or PostgreSQL mechanisms.

## Architecture Insights

- Authorization is intentionally derived from server-side identity objects rather
  than submitted family identifiers. Reuse those production predicates in requests;
  tests should assert observable policy and non-effects rather than duplicate the
  predicates as an oracle.
- Deployment follows an expand/contract-compatible, forward-fix posture: schema is
  not automatically reversed when application activation or readiness fails. Phase
  1 should test that posture under PostgreSQL rather than add destructive rollback.
- Admin is a public operator surface and a deliberate superuser bypass. Its risks
  combine authentication abuse, site-wide admission, and data-invariant protection;
  a home-page-only test is insufficient.

## Historical Context

- **Supported with an exception:** the archived automation-token work chose no
  rate limit for high-entropy bearer tokens; that rationale does not cover the
  password-based admin login (`context/archive/2026-09-27-automation-token-access/plan.md:47-57`).
- **Supported:** the conversion implementation added database defaults specifically
  for old-code compatibility after review (`context/changes/eduvulcan-school-event-intake/reviews/impl-review.md:32-52`; `entries/migrations/0005_inbound_notification_db_defaults.py:1-24`).
- **Superseded:** PRD v2 says automation is write-only
  (`context/foundation/prd.md:145-158`); the later owner-directed MS-01 explicitly
  adds a family-scoped read API (`context/foundation/roadmap.md:23-32`,
  `context/foundation/roadmap.md:202-212`).
- **Still open:** the deployment contract lists a disposable restore drill,
  recurring/off-provider backups, application rollback rehearsal, and reboot proof
  as unevidenced follow-ups (`context/changes/deployment/mikrus-runbook.md:847-852`).

## Code References

- `family_notes/admin.py:4-6` — site-wide active-superuser admission predicate.
- `family_notes/settings.py:229-258` — SQLite default and PostgreSQL production configuration.
- `scripts/deployment/family-notes-deploy:124-160` — preflight, dump, migrate/activate, and code-only rollback.
- `entries/tests/test_conversion_models.py:248-345` — focused forward-migration and old-code compatibility proof.
- `family_access/access.py:6-51` — shared session membership and family scoping.
- `family_access/automation.py:34-73` — token lifecycle and authority checks.
- `entries/services.py:21-137` — parent mutation authorization and ownership checks.
- `entries/services.py:244-327` — child reads, automation reads, and automated entry ownership.

## Related Research

No other `research.md` directly covers all three Phase 1 risks. The deployment
runbook and archived access/token plans supplied relevant historical decisions and
are cited above.

## Open Questions for Planning

1. Which concrete admin-login abuse defense will be adopted, and what proxy/IP,
   reset, logging, and operator-lockout contract does it require?
2. Which PostgreSQL harness will own predecessor-to-leaf migration and disposable
   restore rehearsals, and which production predecessor states must be certified?
3. Will token-issuance and cross-family relational gaps be hardened in application
   validation/admin forms, database mechanisms, or both?
4. Should `get_active_membership()` independently reject inactive users to make
   direct service use fail closed, even though normal session authentication already
   rejects them?

These are implementation choices for `/10x-plan`, not missing evidence that blocks
completion of this research.
