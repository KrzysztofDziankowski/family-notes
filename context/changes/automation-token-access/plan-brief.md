# Automation Token Access — Plan Brief

> Full plan: `context/changes/automation-token-access/plan.md`

## What & Why

A parent's phone automation needs to forward EduVulcan notifications to FamilyNotes without an interactive Google sign-in. This change (roadmap F-04, PRD v2 FR-009) adds bearer tokens that the administrator issues and revokes in Django admin. Each token is tied to one parent and can only act for that parent's family. It gives S-05 (the intake endpoint) the authentication it needs.

## Starting Point

The only authentication path is the Google sign-in session. `family_access` already defines families, memberships and the "active parent" check (`is_parent`), and admin is restricted to superusers. There's no API layer, and no JSON endpoint other than `/healthz/`.

## Desired End State

A superuser issues a named token for a parent in `/admin/`, with an optional expiry. The secret is shown once and only its hash is stored. The phone automation calls `GET /api/automation/ping/` with `Authorization: Bearer <secret>` and gets 200 with the token's name. Any revoked, expired, unknown or wrongly-owned token, or one whose user account is deactivated, gets the same 401. Revoking in admin takes effect on the next request, and admin shows when each token was last used.

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
| Refresh on show-once page | Accepted: Polish no-refresh warning, duplicates are visible and revocable | Keeps the secret out of every store; plan review F2 (Fix B). | Plan review |
| Expiry boundary | Expired when `expires_at <= now`; owner is read-only after issue | Settles the boundary case and stops a live secret being reassigned. | Plan review |
| API framework | None (plain Django views) | One endpoint doesn't justify a new dependency. | Plan |

## Scope

**In scope:**
- `AutomationToken` model and migration in `family_access`
- Admin: issue with show-once secret, list and status, revoke action
- `automation_token_required` decorator and `authenticate_automation_request` helper
- `GET /api/automation/ping/`
- Tests for every accept and reject path
- README runbook section

**Out of scope:**
- In-app token page for parents
- School-entry intake (S-05)
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
```

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Token model and admin issuing | Tokens can be issued (secret shown once), listed and revoked in admin | Secret leaking through admin messages or the change form |
| 2. Bearer token authentication and ping endpoint | Reusable decorator, ping route, full reject-path tests, runbook | A token staying valid after its owner's role or active flag changes |

**Prerequisites:** F-01 (done). Can run in parallel with S-01.
**Estimated effort:** ~1–2 sessions across 2 phases.

## Open Risks & Assumptions

- The production reverse proxy is assumed to forward the `Authorization` header. This is checked manually in Phase 2.
- The ping route is a second token-reachable endpoint. It must stay read-only and return only the token's own name.
- A rollback of the migration drops every issued token, and they would have to be re-issued.

## Success Criteria (Summary)

- An operator can issue a token in admin, see it once, and use it from the phone automation to get a 200 from ping.
- Revoking or expiring a token, or deactivating its parent, blocks the next request with a 401.
- S-05 can protect its intake route by adding one decorator.
