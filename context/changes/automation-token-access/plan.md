# Automation Token Access Implementation Plan

## Overview

Give a parent's automation (the phone script that forwards EduVulcan notifications) a second, non-interactive way to authenticate: named, revocable, optionally expiring bearer tokens issued by the administrator in Django admin and bound to one parent membership. Deliver a reusable `automation_token_required` view decorator plus a `GET /api/automation/ping/` check endpoint so the real automation's configuration can be verified now, and S-05 (`eduvulcan-school-event-intake`) can protect its intake route with the same decorator.

It also adds the fast half of intake: `POST /api/automation/notifications/`. This endpoint only stores the forwarded notification unchanged in a pre-events table (`InboundNotification`) and returns `202` straight away. Converting stored rows into calendar events and notes (fixed school rules first, then LLM fallback, then a general note) is S-05's job. S-05 does it outside the request, through an in-process in-memory queue.

Roadmap item: F-04 `automation-token-access` (PRD v2: FR-009, Access Control "Automation", NFR "a revoked token stops working immediately").

## Current State Analysis

- The only authentication path is the Google sign-in session (django-allauth). There is no API layer, no DRF, and no JSON endpoint other than `/healthz/`.
- Family membership and roles live in `family_access`. A membership only counts when the member, their family and (for parents) the role are active. The helpers enforcing this are in `family_access/access.py`.
- Django admin is superuser-only through `SuperuserAdminSite`. Admin is the MVP's only administration surface, and PRD v2 makes it the only place tokens are issued and revoked.
- Lessons: code is written in English, text shown to users is written in Polish, and commits are prefixed `feat(automation-token-access):`.

## Desired End State

- A superuser can issue a token in `/admin/` for a parent member, giving it a name and an optional expiry. The plaintext secret is shown exactly once, on the response page right after saving, and can never be viewed again. Only its SHA-256 hash and a short display prefix are stored.
- Admin lists tokens with name, owner, prefix, created, expires, last used, revoked and a derived status. A "Revoke selected tokens" action sets `revoked_at`.
- `GET /api/automation/ping/` with `Authorization: Bearer <secret>`:
  - a valid token returns `200 {"status": "ok", "token": "<token name>"}` and updates `last_used_at`;
  - any failure returns `401 {"error": "invalid_token"}` with a `WWW-Authenticate: Bearer` header. Failures are: no header, a malformed header, an unknown, revoked or expired token, a non-parent owner, an inactive membership, an inactive family, or an inactive user account.
- A signed-in session without a token still gets 401. Non-GET methods get 405.
- `POST /api/automation/notifications/` with a valid token and a JSON notification stores one `InboundNotification` row with status `pending`, bound to the token and its family. It returns `202 {"status": "accepted", "id": <row id>}` without any classification, LLM or other network call in the request. Resending the same `notification_id`, or the same title and message captured on the same day under a new id, returns `202` with the existing row's id and doesn't create a second row (FR-011). A body that isn't valid JSON, is missing a required field or is over 16 KB is rejected with `400`/`413`, and nothing is stored.
- The full test suite, `manage.py check` and the migration check pass.

### Key Discoveries:

- `family_access/access.py:24` `is_parent(membership)` already checks that the membership is active, its family is active and the role is `PARENT`. Token authentication reuses it instead of re-implementing the checks.
- `family_notes/admin.py:4` `SuperuserAdminSite` restricts all admin use to active superusers, so no extra permission layer is needed for token management.
- `family_access/admin.py:13` shows the admin conventions to follow: `list_display`, `list_filter`, `search_fields`, `autocomplete_fields`, and an `@admin.display` helper.
- `family_access/tests.py:96` (`FamilyMemberAdminAccessTests`) and `:135` (`FamilyAccessHelperTests`) show the test style: `TestCase` classes per concern, with parent, child, inactive and unauthenticated cases.
- `family_notes/urls.py:21` is the URL composition point. Product routes are included from app `urls` modules, following AGENTS.md's rule that "`family_notes/` only composes URLs".
- `eduvulcan-queue/*.json` (gitignored, contains real names) shows the payload the phone automation sends: `id`, `captured_at`, `captured_at_iso`, `package`, `channel`, `title`, `tickerText`, `message`, `notification_id`, `notification_when`. Fixtures in tests must be anonymized.
- `context/foundation/tech-stack.md:19` has `has_background_jobs: false`, and the user chose not to add any external queue dependency. The request path therefore must not depend on a worker. The DB row is the durable record, and S-05's in-memory queue is only a wake-up signal.
- The `entries` app exists (`entries/classification/`, F-02) but has no `models.py` yet. S-01 will add the entry model there.
- `README.md:79` "Create the initial family" is the operator runbook for admin-only setup. The token-issuing steps belong next to it.

## What We're NOT Doing

- No in-app token page for parents (PRD v2 Non-Goals). Tokens are managed only in admin.
- No DRF or other API framework dependency. Plain Django views and a decorator are enough.
- No conversion of stored notifications into entries: no school rules, no LLM call, and no in-memory queue or worker. All of that is S-05. This change stores the raw notification and deduplicates it at intake, by `notification_id` and by same-day content.
- No token scopes or permissions model. Every token has the same single capability, "automation for this parent's family", and each endpoint decides what it allows.
- No rate limiting or lockout. Tokens carry 256 bits of randomness, so brute force isn't a practical threat. Revisit if a public abuse signal appears.
- No reading of family data through a token. The ping response contains only the token's own name.
- No management command or CLI for issuing tokens.

## Implementation Approach

The token model lives in `family_access`, next to the membership it's bound to. The secret is generated server-side with `secrets`, prefixed so it's recognisable (`fnat_`), and stored only as a SHA-256 hex digest. It's looked up by that unique digest. A slow password hash isn't needed for high-entropy random tokens, and an indexed lookup keeps each request to a single query.

Validity is computed in one place (`AutomationToken.is_usable(now)` plus the `is_parent` membership check), so admin status, authentication and tests all agree.

The decorator is the only token entry point. It is CSRF-exempt (there's no cookie session), ignores any session user, and returns a uniform 401 that doesn't reveal why the token failed.

## Critical Implementation Details

- **Show-once without storage.** Don't pass the secret through `messages`. The default message storage can put it in a cookie or session. Instead, override the admin's `response_add` to render a dedicated template containing the secret (Polish copy, per lessons) with no redirect. The secret exists only in that one response. Refreshing that page re-submits the add form and issues a second token. This is accepted, not engineered away: the page warns in Polish not to refresh, and any duplicate shows up in the list and can be revoked. The change form never shows the hash or secret, and they are excluded from the form's fields.
- **Owner must be a parent at authentication time, not only at issue time.** A member's role or active flag can change after a token is issued. The authentication check must re-evaluate `is_parent(token.member)` and `token.member.user.is_active` on every request. `is_parent` does not check the Django user, and the token path bypasses the login check that normally refuses inactive users. Model validation (`clean`) only stops admins issuing tokens to children.
- **Intake must be fast; conversion is never in the request.** The notification endpoint does auth (one lookup and one `UPDATE`), then one `get_or_create` on `InboundNotification`, then returns. It must not import or call anything from `entries/classification/`. A test pins the query count with `assertNumQueries`, so a later change can't quietly add work to the request path. S-05 attaches its queue hook with `transaction.on_commit` after the insert. If the queue is gone (process restart), the row stays `pending` and S-05's worker picks it up by sweeping the table.
- **Last-used update.** Record usage with a queryset `.update(last_used_at=now)` on the token's pk. This avoids a full `save()` that would touch other fields or race a concurrent revoke.

## Phase 1: Token Model and Admin Issuing

### Overview

Add the `AutomationToken` model and its migration. Wire admin so a superuser can issue a token (the secret is shown once), see token status, and revoke tokens.

### Changes Required:

#### 1. Token model

**File**: `family_access/models.py`

**Intent**: Store named automation tokens bound to a parent membership. Only the hash of the secret is stored, and each token has its own expiry, revocation and last-used time.

**Contract**: `AutomationToken` with fields:
- `member` (FK `FamilyMember`, `on_delete=CASCADE`, `related_name='automation_tokens'`, limited to the parent role in admin choices)
- `name` (CharField 120)
- `prefix` (CharField, the first characters of the secret after `fnat_`, for identification)
- `token_hash` (CharField 64, unique)
- `created_at` (auto)
- `expires_at`, `revoked_at`, `last_used_at` (nullable DateTimeFields)

Also:
- A classmethod `issue(member, name, expires_at=None) -> (token, secret)` generates `fnat_` + `secrets.token_urlsafe(32)` and saves only the hash.
- A static `hash_secret(secret) -> str` (SHA-256 hex).
- `is_revoked` and `is_expired(now)`, with expired meaning `expires_at <= now`, and `is_usable(now)` meaning not revoked and not expired.
- `clean()` rejects a non-parent `member`.
- `__str__` returns `"<name> (<prefix>…)"`.

#### 2. Migration

**File**: `family_access/migrations/0002_automationtoken.py`

**Intent**: Create the table. It's additive only, with no data migration.

**Contract**: Generated by `makemigrations family_access`. It adds a unique index on `token_hash`.

#### 3. Admin issuing, listing and revoking

**File**: `family_access/admin.py`, `family_access/templates/admin/family_access/automationtoken/issued.html`

**Intent**: Admin is the only management surface (FR-009). Adding a token calls `AutomationToken.issue` and renders the secret once. The list view shows status at a glance.

**Contract**:
- `AutomationTokenAdmin` registered for `AutomationToken`.
- The add form has only `member` (autocomplete, restricted to active parent members), `name` and `expires_at`.
- The change form keeps `name` and `expires_at` editable. It shows `member`, `prefix` and the timestamps read-only, so a live secret can't be reassigned to another parent, and never shows the hash.
- `save_model` on add issues the token through `issue()` and keeps the secret on the request for that response only.
- `response_add` renders `issued.html`: the secret in Polish, with a warning that it won't be shown again, a warning not to refresh the page ("nie odświeżaj") because that issues another token, and a link back to the list.
- `list_display` shows name, member, prefix, created_at, expires_at, last_used_at, revoked_at and a derived `status` (Aktywny / Wygasły / Unieważniony).
- `list_filter` is on member and revocation.
- An action "Unieważnij wybrane tokeny" sets `revoked_at=now` on tokens not already revoked.

### Success Criteria:

#### Automated Verification:

- Migration is present and consistent: `uv run python manage.py makemigrations --check --dry-run`
- Django checks pass: `uv run python manage.py check`
- Token model and admin tests pass: `uv run python manage.py test family_access`
- Issuing stores only the hash: a test asserts the returned secret starts with `fnat_`, that `token_hash == sha256(secret)`, and that the secret appears nowhere in the saved row
- Model validation rejects a child member: a test asserts `clean()` raises `ValidationError`
- Admin add as superuser returns 200 with the secret in the page body, and the change page for the same token doesn't contain the secret
- The revoke action sets `revoked_at` on selected tokens and leaves already-revoked tokens unchanged
- Non-superuser (parent member) access to the token admin is denied
- The change form renders `member` read-only, and a POST that tries to change it leaves the owner unchanged
- Expiry boundary: a token with `expires_at` equal to now is rejected, and one a second later is usable

#### Manual Verification:

- In local `/admin/`, issue a token for a parent. The secret is shown once, with Polish copy, and reopening the token doesn't show it again
- The member dropdown/autocomplete doesn't offer child members
- The list view shows the correct status after revoking one token and setting a past expiry on another
- Refreshing the issued page shows up as a second token in the list, which can be revoked

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 2: Bearer Token Authentication and Ping Endpoint

### Overview

Add the reusable token authentication helper and decorator, expose `GET /api/automation/ping/`, cover every rejection path with tests, and document how an operator issues a token.

### Changes Required:

#### 1. Authentication helper and decorator

**File**: `family_access/automation.py`

**Intent**: Provide the single entry point for token-authenticated views, so S-05 can protect its intake route with the same checks.

**Contract**:
- `authenticate_automation_request(request) -> AutomationToken | None`. It parses `Authorization: Bearer <secret>` (case-insensitive scheme, exactly one token), looks the token up by `hash_secret`, and requires `is_usable(now)`, `is_parent(token.member)` and `token.member.user.is_active`. It uses `select_related('member__family', 'member__user')` and updates `last_used_at` on success.
- `automation_token_required(view)`:
  - is `csrf_exempt` and ignores `request.user`;
  - on success sets `request.automation_token` and `request.automation_membership`;
  - on failure returns `JsonResponse({'error': 'invalid_token'}, status=401)` with `WWW-Authenticate: Bearer`.
- Failures are logged at WARNING level with the reason and, when the token was found, its `prefix`, but never the secret or header value. There's no LOGGING config, so INFO would never be printed.

#### 2. Ping view and routes

**File**: `family_access/api_views.py`, `family_access/api_urls.py`, `family_notes/urls.py`

**Intent**: Let the operator check the real automation's token and URL end to end before the intake endpoint exists. The response only confirms which token was accepted, and exposes no family data.

**Contract**:
- `ping` is decorated with `require_GET` and `automation_token_required`, and returns `{"status": "ok", "token": request.automation_token.name}`.
- The route is `api/automation/ping/`, named `automation_ping`. It's included as `path('api/automation/', include('family_access.api_urls'))`, and Phase 3 adds a second include of `entries.api_urls` under the same prefix for the intake route.

#### 3. Operator runbook

**File**: `README.md`

**Intent**: Document issuing, storing, testing and revoking a token next to the existing admin-only family setup.

**Contract**: A new subsection after "Create the initial family", titled "Issue an automation token". It covers:
- the admin steps;
- that the secret is shown once;
- a `curl -H "Authorization: Bearer …" …/api/automation/ping/` check;
- revocation, and that revocation takes effect immediately.

### Success Criteria:

#### Automated Verification:

- The full test suite passes: `uv run python manage.py test`
- Django checks pass: `uv run python manage.py check`
- No missing migrations: `uv run python manage.py makemigrations --check --dry-run`
- A valid parent token gets 200 with only `status` and `token`, and `last_used_at` is set
- Each of these gets 401 with the `WWW-Authenticate: Bearer` header and an identical body:
  - no header
  - a non-Bearer scheme
  - an empty or multi-part value
  - an unknown secret
  - a revoked token
  - an expired token
  - a token whose owner became a child
  - an inactive membership
  - an inactive family
  - an inactive Django user account
- A signed-in session user without a token gets 401
- A POST to ping gets 405, and a POST without a CSRF token isn't rejected with 403 (the route is CSRF-exempt; the test uses `Client(enforce_csrf_checks=True)`, because the default test client skips CSRF)
- A revoke followed by an immediate request gets 401 (no caching)
- A rejection is logged at WARNING with the reason, and the log output doesn't contain the secret (`assertLogs`)

#### Manual Verification:

- Locally: issue a token in admin, `curl` ping with it (200), revoke it in admin, `curl` again (401)
- On the deployed instance: the reverse proxy forwards the `Authorization` header, and ping returns 200 with a production token
- Configure the real phone automation with the token and confirm ping succeeds from the device; admin shows `last_used_at` updating

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 3: Fast Notification Intake into the Pre-events Table

### Overview

Accept forwarded EduVulcan notifications as quickly as possible and store them unchanged, so the phone automation gets an immediate acknowledgement and never waits for classification. Processing is left to S-05.

**Prerequisite:** S-01's `entries/migrations/0001_initial.py` must have landed (plan review v2 F2, Fix B). Phases 1–2 don't depend on S-01 and can ship first.

### Changes Required:

#### 1. Pre-events model

**File**: `entries/models.py` (next to S-01's entry model), `entries/migrations/0002_inboundnotification.py`

**Intent**: A durable inbox of raw notifications. Generated by `makemigrations entries` after S-01's migration, so it depends on `entries 0001_initial` and `family_access 0002`. Each row is claimed and converted into an entry later by S-05's worker.

**Contract**: `InboundNotification` with fields:
- `family` (FK `Family`, `on_delete=CASCADE`)
- `token` (FK `AutomationToken`, `on_delete=SET_NULL`, nullable, so revoking or deleting a token keeps its history)
- `notification_id` (CharField 255; real ids are 56–57 chars)
- `title` (CharField 255)
- `message` (TextField)
- `captured_at` (DateTimeField, parsed from `captured_at_iso`, which carries its offset)
- `captured_date` (DateField, `timezone.localdate(captured_at)` in the project time zone)
- `content_hash` (CharField 64): SHA-256 hex of `title + "\n" + message` after Unicode NFC normalization, trimming, and collapsing runs of whitespace to one space. Case and diacritics are kept.
- `payload` (JSONField, the full body as received, so S-05 can reprocess it)
- `status` (CharField choices `pending` / `processing` / `processed` / `failed`, default `pending`, indexed). Only `pending` is written here; the other states are for S-05.
- `received_at` (auto)
- `processed_at` (nullable)
- `error` (TextField, blank)

Two constraints implement FR-011 at intake:
- `UniqueConstraint(fields=['family', 'notification_id'])`
- `UniqueConstraint(fields=['family', 'content_hash', 'captured_date'])`

The second one is needed because, in the captured samples, every repeated notification arrived with a new `notification_id` (45 ids, 39 distinct contents). The child is named inside the title or message, so title+message covers FR-011's "same title, message, and child". **Accepted risk (plan review v2 F1, Fix B):** two genuinely different notifications with identical text on the same day, such as two identical grade messages, are stored once. The second one is acknowledged with 202 and dropped.

#### 2. Intake view and route

**File**: `entries/api_views.py`, `entries/api_urls.py`, `family_notes/urls.py`

**Intent**: The only write path open to a token. It's fast, idempotent, and never classifies.

**Contract**:
- `submit_notification` is decorated with `require_POST` and `automation_token_required`.
- It rejects a body over 16 KB (`413 {"error": "payload_too_large"}`) before parsing. It parses JSON and requires non-empty string `title`, `message`, `notification_id` and a parseable ISO `captured_at_iso`; anything else gets `400 {"error": "invalid_payload"}`.
- It computes `content_hash` and `captured_date`, then looks for an existing row in the family matching `Q(notification_id=…) | Q(content_hash=…, captured_date=…)`. If none exists, it creates one inside `transaction.atomic()`. On `IntegrityError` (a concurrent copy won the race, which is expected because copies arrive seconds apart), it repeats the lookup and returns that row.
- It returns `202 {"status": "accepted", "id": row.id}` for both new and duplicate rows. The response contains no family data.
- The route is `api/automation/notifications/`, named `automation_notification_submit`, included through a second `path('api/automation/', include('entries.api_urls'))` in `family_notes/urls.py`.

#### 3. Admin visibility

**File**: `entries/admin.py`

**Intent**: Let the operator confirm the phone is delivering, and later see what S-05 did with each row.

**Contract**: A read-only `InboundNotificationAdmin` (no add or change) with `list_display` of received_at, family, token, title, status, and `list_filter` on status and family.

#### 4. Runbook

**File**: `README.md`

**Contract**: The "Issue an automation token" section gets a `curl -X POST … /api/automation/notifications/` example with an anonymized payload, and explains that the row appears in admin as `pending` until S-05 processing exists.

### Success Criteria:

#### Automated Verification:

- The full test suite passes: `uv run python manage.py test`
- No missing migrations: `uv run python manage.py makemigrations --check --dry-run`
- A valid token and payload get 202 with only `status` and `id`, and one `pending` row bound to the token's family and token
- The request path is bounded: `assertNumQueries` pins the query count for a new notification, and a test patches `entries.classification.service.classify_for_parent` so that it fails the test if it's called
- Sending the same `notification_id` twice gets 202 with the same id and leaves one row. The same `notification_id` from another family's token creates its own row
- The same title and message under a new `notification_id` on the same `captured_date` gets 202 with the existing id and leaves one row. Whitespace-only differences count as the same content. The same content on the next day creates a new row. An `IntegrityError` raised on create (simulated race) returns 202 with the winning row's id
- Invalid JSON, a missing or empty required field, and an unparseable `captured_at_iso` each get 400 with nothing stored. A body over 16 KB gets 413
- Every token rejection path from Phase 2 gets 401 here too, with no row stored. GET gets 405. The route is CSRF-exempt
- Admin for `InboundNotification` is read-only and denied to non-superusers

#### Manual Verification:

- Local `curl` POST with an anonymized sample returns 202 at once, and the row shows as `pending` in admin
- The real phone automation, pointed at the deployed endpoint, gets 202 and its notifications appear in admin, with no duplicates for repeated deliveries
- The README intake `curl` example, run as written with an anonymized payload, returns 202

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful.

## S-05 Handoff: Converting Pre-events

These decisions were made here so S-05 plans against them. They are not built in this change.

- **Conversion order** (PRD Business Logic): fixed school category rules first, then LLM classification through the F-02 privacy boundary, and if that fails, a general note. Each result is saved as an entry with source EduVulcan and no confirmation step (FR-010). FR-011 is already enforced at intake (one row per id and per same-day content), so conversion is one entry per row, and parallel workers can't turn two copies into two entries.
- **Queue:** an in-process, in-memory queue (`queue.Queue` plus one daemon worker thread per Gunicorn process), with no external dependency. The DB row is the source of truth:
  - the intake view enqueues the row id through `transaction.on_commit`;
  - at startup and on a periodic sweep, the worker re-enqueues `pending` rows and rows stuck in `processing` past a timeout;
  - a row is claimed with a conditional `UPDATE … SET status='processing' WHERE id=… AND status='pending'`, so several Gunicorn workers never process it twice.
- **Worker startup and concurrency** (plan review v2 F3):
  - The worker thread starts from Gunicorn's `post_fork` hook (or lazily on the first request), never from `AppConfig.ready()`, which also runs under `migrate`, `test` and every management command, and never before a `--preload` fork, which would lose the thread.
  - Startup is gated by a setting (e.g. `INBOUND_WORKER_ENABLED`) that is off in tests. Tests call the processing function directly.
  - At most one conversion runs at a time across all processes (a PG advisory lock around the claim-and-convert step), so LLM memory use doesn't grow with the Gunicorn worker count.
- **Risks S-05 must address:** queued ids are lost on restart (the sweep covers this); LLM concurrency on the 2 GB VPS (one worker thread per process, with a bounded Gunicorn worker count); failed rows are kept with `error` for retry; processed rows are pruned against the 100 MB shared-DB allowance.

---

## Testing Strategy

### Unit Tests:

- `AutomationToken.issue`: prefix format, hash-only storage, unique hashes across issues
- `is_usable`: revoked, expired (past `expires_at`), no expiry, future expiry
- `clean()`: parent accepted, child rejected
- `authenticate_automation_request`: header parsing edge cases, and every membership state via `is_parent`

### Integration Tests:

- Admin: add flow as superuser (secret shown once), change page hides the secret, revoke action, non-superuser denied
- Ping through the Django test client: every 200 and 401 path listed in Phase 2, session-only user, method restriction, CSRF exemption, revoke-then-request
- Notification intake: 202 new and duplicate, per-family id dedup, same-day content dedup and next-day distinct, race on create, 400/413 validation, 401 paths, bounded query count, no classification call

### Manual Testing Steps:

1. Create a superuser and the family per README, then issue a token for a parent in `/admin/` and copy the secret.
2. `curl -i -H "Authorization: Bearer <secret>" http://localhost:20121/api/automation/ping/` returns 200 with the token name.
3. Revoke the token in admin and repeat the request: 401.
4. Issue a token with a past expiry and repeat the request: 401.
5. On production, repeat step 2 through the public URL to confirm the proxy forwards `Authorization`.
6. `curl -i -X POST -H "Authorization: Bearer <secret>" -H "Content-Type: application/json" -d @anonymized-sample.json http://localhost:20121/api/automation/notifications/` returns 202 at once. Repeat it: same id, and still one `pending` row in admin.

## Performance Considerations

Each authenticated request makes one indexed lookup by `token_hash` (joined to member and family) and one single-row `UPDATE` for `last_used_at`. That's negligible at a single family's scale.

Notification intake adds one `get_or_create` (a select, plus an insert for a new id) on top of that, and makes no external calls. The phone automation gets a response in database round-trip time instead of LLM time (up to the 30-second classification limit). This is the reason the pre-events table exists.

## Migration Notes

Additive migration (a new table), with no changes to existing data. Rolling back means unapplying `family_access 0002`, which drops all tokens. Any issued tokens would then have to be re-issued.

Phase 3 adds `entries 0002_inboundnotification` (a new table). It depends on S-01's `entries 0001_initial` and on `family_access 0002`, so Phase 3 starts only after S-01's migration is on master. Rolling back means unapplying `entries 0002`, which drops every stored notification, including any not yet processed. S-01's rollback of `entries 0001` would have to unapply `entries 0002` first.

## References

- PRD: `context/foundation/prd.md` v2 (FR-009, Access Control, Non-Functional Requirements)
- Roadmap: `context/foundation/roadmap.md` F-04, and consumer S-05 `eduvulcan-school-event-intake`
- Membership checks: `family_access/access.py:24`
- Admin conventions: `family_access/admin.py:13`, `family_notes/admin.py:4`
- Test conventions: `family_access/tests.py:96`, `family_access/tests.py:135`
- Operator runbook: `README.md:79`
- Notification payload shape: `eduvulcan-queue/*.json` (gitignored; keys only)
- PRD NFR: automation intake is acknowledged without waiting for classification

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Token Model and Admin Issuing

#### Automated

- [x] 1.1 Migration is present and consistent: `uv run python manage.py makemigrations --check --dry-run` — 1b67e08
- [x] 1.2 Django checks pass: `uv run python manage.py check` — 1b67e08
- [x] 1.3 Token model and admin tests pass: `uv run python manage.py test family_access` — 1b67e08
- [x] 1.4 Issuing stores only the hash — 1b67e08
- [x] 1.5 Model validation rejects a child member — 1b67e08
- [x] 1.6 Admin add shows the secret once; change page does not contain it — 1b67e08
- [x] 1.7 Revoke action sets `revoked_at` and leaves already-revoked tokens unchanged — 1b67e08
- [x] 1.8 Non-superuser access to token admin is denied — 1b67e08
- [x] 1.12 Change form keeps member read-only — 1b67e08
- [x] 1.13 Expiry boundary: expires_at equal to now is rejected — 1b67e08

#### Manual

- [x] 1.9 Local admin issue shows the secret once in Polish and never again — 1b67e08
- [x] 1.10 Member choices exclude child members — 1b67e08
- [x] 1.11 List status reflects revoked and expired tokens — 1b67e08
- [x] 1.14 Refreshing the issued page creates a visible, revocable duplicate — 1b67e08

### Phase 2: Bearer Token Authentication and Ping Endpoint

#### Automated

- [x] 2.1 The full test suite passes: `uv run python manage.py test` — cda3c03
- [x] 2.2 Django checks pass: `uv run python manage.py check` — cda3c03
- [x] 2.3 No missing migrations: `uv run python manage.py makemigrations --check --dry-run` — cda3c03
- [x] 2.4 Valid parent token gets 200 with only status and token, and last_used_at is set — cda3c03
- [x] 2.5 Every rejection path gets a uniform 401 with WWW-Authenticate: Bearer — cda3c03
- [x] 2.6 Signed-in session user without a token gets 401 — cda3c03
- [x] 2.7 POST to ping gets 405 and the route is CSRF-exempt — cda3c03
- [x] 2.8 Revoke followed by an immediate request gets 401 — cda3c03
- [x] 2.12 Rejection logged at WARNING without the secret — cda3c03

#### Manual

- [x] 2.9 Local curl ping: 200, revoke, then 401 — cda3c03
- [ ] 2.10 Deployed proxy forwards Authorization and ping returns 200
- [ ] 2.11 Real phone automation ping succeeds and last_used_at updates

### Phase 3: Fast Notification Intake into the Pre-events Table

#### Automated

- [x] 3.1 The full test suite passes: `uv run python manage.py test`
- [x] 3.2 No missing migrations: `uv run python manage.py makemigrations --check --dry-run`
- [x] 3.3 Valid token and payload get 202 and one pending row bound to the family and token
- [x] 3.4 Request path bounded: pinned query count and no classification call
- [x] 3.5 Duplicate notification_id is idempotent per family
- [x] 3.6 Invalid payload gets 400, oversized gets 413, nothing stored
- [x] 3.7 Token rejection paths get 401, GET gets 405, route is CSRF-exempt
- [x] 3.8 InboundNotification admin is read-only and superuser-only
- [x] 3.11 Same-day identical content under a new notification_id is deduplicated

#### Manual

- [x] 3.9 Local curl POST returns 202 at once and the row is pending in admin
- [ ] 3.10 Real phone automation delivers to production with no duplicate rows
- [x] 3.12 README intake curl example returns 202 as written
