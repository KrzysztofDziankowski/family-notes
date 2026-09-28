# Automation Token Access — Plan Brief

> Full plan: `context/changes/automation-token-access/plan.md`

## What & Why

A parent's phone automation needs to forward EduVulcan notifications to FamilyNotes without an interactive Google sign-in. This change (roadmap F-04, PRD v2 FR-009) adds bearer tokens that the administrator issues and revokes in Django admin. Each token is tied to one parent and can only act for that parent's family. It gives S-05 the authentication it needs. It also adds the fast half of intake: an endpoint that stores each forwarded notification unchanged in a pre-events table and acknowledges it at once. S-05 later converts those rows into events and notes (rules, then LLM) outside the request.

## Starting Point

The only authentication path is the Google sign-in session. `family_access` already defines families, memberships and the "active parent" check (`is_parent`), and admin is restricted to superusers. There's no API layer, and no JSON endpoint other than `/healthz/`.

## Desired End State

A superuser issues a named token for a parent in `/admin/`, with an optional expiry. The secret is shown once and only its hash is stored. The phone automation calls `GET /api/automation/ping/` with `Authorization: Bearer <secret>` and gets 200 with the token's name. Any revoked, expired, unknown or wrongly-owned token, or one whose user account is deactivated, gets the same 401. Revoking in admin takes effect on the next request, and admin shows when each token was last used. `POST /api/automation/notifications/` stores the notification as a `pending` `InboundNotification` and returns 202 without any classification or LLM call. Repeat deliveries are deduplicated at intake, both by `notification_id` and by same-day title+message.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
| --- | --- | --- | --- |
| Management surface | Django admin only | MVP has no in-app administration; admin is already superuser-only. | PRD v2 |
| Tokens per parent | Many, each named | A new token can be issued before the old one is revoked, and one device's token revoked alone. | Plan |
| Expiry | Optional `expires_at` | Lets you time-box test tokens without forcing rotation on the long-running automation. | Plan |
| Usage tracking | `last_used_at` updated on success | Shows in admin whether the automation is actually reaching the server. | Plan |
| Verifiable before S-05 | Reusable decorator + `GET /api/automation/ping/` | Lets you test the real automation now; S-05 reuses the same decorator. | Plan |
| Ping response | `{"status","token": <token name>}` only | The PRD says a token must not read family data. | Plan |
| Secret storage | `fnat_` + 256-bit random secret, SHA-256 hash stored and looked up by hash | Standard for high-entropy tokens; one indexed query per request. | Plan |
| Show-once mechanism | Rendered on the admin add response, not via `messages` | Messages can end up in a cookie or session store. | Plan |
| Failure response | Uniform 401 `invalid_token` + `WWW-Authenticate: Bearer`; reason logged at WARNING without the secret | Doesn't reveal why a token failed, but the operator can still see it in the logs. | Plan |
| Refresh on show-once page | Accepted: Polish no-refresh warning, duplicates are visible and revocable | Keeps the secret out of every store; plan review v1 F2 (Fix B). | Plan review v1 |
| Expiry boundary | Expired when `expires_at <= now`; owner is read-only after issue | Settles the boundary case and stops a live secret being reassigned. | Plan review v1 |
| API framework | None (plain Django views) | Two small endpoints don't justify a new dependency. | Plan |
| Intake speed | Store the raw notification in a pre-events table, return 202; no classification in the request | The automation must get an answer quickly; LLM calls can take up to 30 s. | User, 2026-09-27 |
| Intake dedup | Unique on (family, notification_id) and on (family, content_hash, captured_date) | Real repeats arrive with a new id each time. Accepted risk: two genuinely identical texts on the same day are stored once. | Plan review v2 F1 (Fix B) |
| Split with S-05 | F-04 stores, S-05 converts | The phone gets a fast, durable intake before conversion exists. | User, 2026-09-27 |
| Inbox location | `entries` app, migration `0002` after S-01's `0001_initial` | Keeps it in the entries domain; Phase 3 waits for S-01's migration. | Plan review v2 F2 (Fix B) |
| Conversion order (S-05) | Fixed school rules → LLM fallback → general note | Keeps PRD Business Logic and sends less text to the LLM. | User, 2026-09-27 |
| Processing trigger (S-05) | In-process in-memory queue, no external dependency; DB row is the source of truth, with a sweep for restarts | No broker on a 2 GB VPS; `has_background_jobs: false`. | User, 2026-09-27 |

## Scope

**In scope:**
- `AutomationToken` model and migration in `family_access`
- Admin: issue with show-once secret, list and status, revoke action
- `automation_token_required` decorator and `authenticate_automation_request` helper
- `GET /api/automation/ping/`
- `InboundNotification` pre-events table and `POST /api/automation/notifications/` (store + 202, id and same-day content dedup)
- Tests for every accept and reject path
- README runbook section

**Out of scope:**
- In-app token page for parents
- Converting pre-events into entries, and the in-memory queue and worker (S-05)
- Token scopes
- Rate limiting
- DRF
- A CLI for issuing tokens

## Architecture / Approach

```
phone automation --Bearer fnat_…--> /api/automation/<route>
    automation_token_required
      ├─ parse header → sha256 → AutomationToken (by hash, + member + family)
      ├─ is_usable(now): not revoked, not expired
      ├─ is_parent(member): member, family and parent role all active  (reuses access.py)
      ├─ member.user.is_active
      ├─ update last_used_at
      └─ request.automation_token / automation_membership → view
admin (superuser) → issue() → secret rendered once, hash stored

POST /api/automation/notifications/  (fast path, no LLM)
    automation_token_required → validate JSON → hash content → find-or-create InboundNotification(pending) → 202
    [S-05] on_commit → in-memory queue → worker: rules → LLM → note → entry
```

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Token model and admin issuing | Tokens can be issued (secret shown once), listed and revoked in admin | Secret leaking through admin messages or the change form |
| 2. Bearer token authentication and ping endpoint | Reusable decorator, ping route, full reject-path tests, runbook | A token staying valid after its owner's role or active flag changes |
| 3. Fast notification intake | Pre-events table, 202 intake endpoint, id dedup, read-only admin | Work creeping into the request path (guarded by a pinned query count) |

**Prerequisites:** F-01 (done). Phases 1–2 can run in parallel with S-01. Phase 3 needs S-01's `entries 0001_initial` merged first.
**Estimated effort:** ~2 sessions across 3 phases.

## Open Risks & Assumptions

- The production reverse proxy is assumed to forward the `Authorization` header. This is checked manually in Phase 2.
- The ping route is a second token-reachable endpoint. It must stay read-only and return only the token's own name.
- A rollback of the migration drops every issued token, and they would have to be re-issued.
- Phase 3 is blocked until S-01's migration lands. If S-01 slips, the phone can only ping, not deliver.
- Until S-05 ships, notifications pile up as `pending`. They are kept, not lost, but they don't show up as entries yet.

## Success Criteria (Summary)

- An operator can issue a token in admin, see it once, and use it from the phone automation to get a 200 from ping.
- Revoking or expiring a token, or deactivating its parent, blocks the next request with a 401.
- The phone automation gets 202 for a notification without waiting for classification, and the row is visible in admin.
- S-05 only adds conversion. The route, auth and storage already exist.
