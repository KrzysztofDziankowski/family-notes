# Test Plan

> Phased test rollout for this project. Strategy is frozen at the top
> (§1–§5); cookbook patterns at the bottom (§6) fill in as phases ship.
> Read before writing any new test.
>
> Refresh: re-run `/10x-test-plan --refresh` when stale (see §8).
>
> Last updated: 2026-10-01

## 1. Strategy

Tests follow three non-negotiable principles for this project:

1. **Cost × signal.** The cheapest test that gives a real signal for the
   risk wins. Do not promote to e2e because e2e "feels safer." Do not put a
   vision model on top of a deterministic visual diff that already catches
   the regression.
2. **User concerns are first-class evidence.** Risks anchored in "the team
   is worried about X, and the failure would surface somewhere in an area"
   carry the same weight as PRD lines or hot-spot data.
3. **Risks are scenarios, not code locations.** This plan documents *what
   could fail* and *why we believe it's likely* — drawn from documents,
   interview, and codebase *signal* (churn, structure, test base). It does
   NOT claim to know which line owns the failure. That knowledge is produced
   by `/10x-research` during each rollout phase. If the plan and research
   disagree about where the failure lives, research is the ground truth.

Hot-spot scope used for likelihood weighting: `entries/`, `family_access/`,
`family_notes/`, and `scripts/deployment/`; migrations, tests, vendored/static
assets, documentation, lockfiles, and build output were excluded. The scoped
history contained 52 commits in the preceding 30 days. The leading authored
areas were `entries/templates` (25 changes), `entries/eduvulcan` (12),
`entries/classification` (12), and `scripts/deployment` (7).

## 2. Risk Map

The top failure scenarios are ordered by impact × likelihood. Sources are
evidence that raised a risk, not claims about where its implementation lives.

| # | Risk (failure scenario) | Impact | Likelihood | Source (evidence — not anchor) |
|---|---|---|---|---|
| 1 | An attacker gains privileged access through the publicly reachable production administration surface | High | Medium | interview Q1; archived identity/access slice; deployment contract |
| 2 | A schema migration corrupts family data, weakens constraints, or cannot be deployed safely | High | Medium | interview Q3; roadmap S-04 and S-05 |
| 3 | A family member or automation reads or changes data outside its authority | High | Medium | PRD lines 47–49 and 145–152; roadmap access requirements |
| 4 | An accepted EduVulcan notification is lost, converted twice, or remains unprocessed after interruption | High | High | PRD lines 68–81 and 119–126; roadmap S-05; hot-spot dir `entries/eduvulcan` (12 changes/30d) |
| 5 | Classification saves the wrong child, date, or entry type, or exposes submitted family text | High | High | PRD lines 39–48 and 94–99; hot-spot dir `entries/classification` (12 changes/30d) |

Impact is High when users lose access or data, private data crosses an
authorization boundary, or a core flow silently produces the wrong record.
Likelihood is High for active, churn-heavy work and Medium for explicit owner
concerns or occasionally changed privileged surfaces. High-impact but external
provider outages belong primarily to health monitoring unless research finds a
deterministic application behavior worth testing.

### Risk Response Guidance

| Risk | What would prove protection | Must challenge | Context `/10x-research` must ground | Likely cheapest layer | Anti-pattern to avoid |
|---|---|---|---|---|---|
| #1 | Anonymous, normal, and staff accounts cannot gain administrative privileges, and repeated login abuse has a defined defense | Superuser-only admission alone makes a public admin safe | Authentication path, deployment boundary, and available throttling or audit controls | integration plus production smoke/security configuration | testing admin appearance instead of privilege boundaries |
| #2 | Forward migrations preserve existing rows and constraints under production-like PostgreSQL, with a rehearsed failure-recovery path | `makemigrations --check` proves production deployability | Migration history, database-engine differences, backup, restore, and rollback contract | PostgreSQL migration integration plus deployment rehearsal | SQLite-only confidence or destructive rollback assumptions |
| #3 | Every read and mutation enforces family ownership and least privilege for sessions and automation tokens | Authentication implies authorization | Identity shapes, ownership boundary, query scoping, and mutation paths | Django integration tests using the complete access matrix | happy-path-only tests or copied production predicates |
| #4 | Acknowledged input survives interruption, resumes safely, and repeated delivery produces one intended result | HTTP 202 or eventual success alone proves durable processing | Persisted state, restart behavior, ordering, and idempotency rules | database-backed integration tests | over-mocked worker tests |
| #5 | Requirements-derived examples produce the correct proposal or follow-up without sensitive-data leakage | Current implementation output is an independent oracle | Product rules, provider boundary, error translation, logs, and persisted state | deterministic unit/contract tests plus narrow integration tests | expected values copied from production logic |

## 3. Phased Rollout

Each row is a discrete rollout phase that opens its own change folder. Status
moves through the fixed vocabulary as downstream artifacts land.

| # | Phase name | Goal (one line) | Risks covered | Test types | Status | Change folder |
|---|---|---|---|---|---|---|
| 1 | Production security and schema safety | Prove privileged-access boundaries and production-safe schema evolution | #1, #2, #3 | security integration, PostgreSQL migration rehearsal, deployment smoke | change opened | testing-production-security-schema-safety |
| 2 | Intake and classification resilience | Prove durable idempotent intake and requirements-based classification outcomes | #4, #5 | unit, contract, database integration | not started | — |
| 3 | Quality-gate wiring | Run the established deterministic checks at the cheapest useful lifecycle moments | cross-cutting | local agent gates, CI recommendations | not started | — |

## 4. Stack

The test base is **meaningful**: Django's runner is configured by convention,
with 28 Python test files spread across product, access, and project packages.

| Layer | Tool | Version | Notes |
|---|---|---|---|
| unit + integration | Django `DiscoverRunner`, `TestCase`, and test client | Django 5.2 | Current suite uses database isolation and request-level tests |
| production database | PostgreSQL via psycopg | psycopg 3.3 | Phase 1 must verify production-like migration behavior |
| external API boundary | `unittest.mock` at the transport edge | Python standard library | Keep domain behavior deterministic; do not mock internal policy |
| e2e | none planned | n/a | Current risks have cheaper integration or smoke-test signals |
| visual/accessibility | none planned | n/a | Admin look-and-feel is explicitly outside test-budget scope |

**Stack grounding tools (current session):**
- Docs: Context7 — checked Django 5.2 `TestCase`, transaction isolation, test client, and discovery guidance; checked: 2026-10-01.
- Search: web search available but not used; official versioned documentation was available through Context7; checked: 2026-10-01.
- Runtime/browser: no Playwright/browser MCP used; deterministic request tests and a narrow manual production smoke provide sufficient signal; checked: 2026-10-01.
- Provider/platform: no provider MCP used; provider-side state is not required for the initial rollout design; checked: 2026-10-01.

## 5. Quality Gates

| Gate | Where | Required? | Catches |
|---|---|---|---|
| focused Django unit + integration suites | local + CI | required after §3 Phases 1–2 | policy, contract, and persistence regressions |
| full Django suite and system checks | end of turn + CI | required | cross-feature and configuration regressions |
| migration drift check | end of turn + CI | required | model changes without migrations |
| production-like migration rehearsal | pre-production | required after §3 Phase 1 | unsafe forward migration and recovery assumptions |
| deployment checks and HTTPS/admin smoke | release | required after §3 Phase 1 | unsafe production settings and privilege-boundary regressions |
| per-edit focused check | local agent loop | required after §3 Phase 3 | fast feedback on edited Python files |

Phase 3 turns these declared gates into harness configuration. Git hooks and CI
changes remain recommendations unless separately authorized.

## 6. Cookbook Patterns

How to add new tests in this project. Placeholders are replaced as the relevant
rollout phase ships.

### 6.1 Adding a domain unit test

- TBD — see §3 Phase 2 for requirements-derived classification and intake rules.

### 6.2 Adding a database integration test

- TBD — see §3 Phases 1–2 for family authorization, durability, idempotency, and migration patterns.

### 6.3 Adding a view or API authorization test

- TBD — see §3 Phase 1 for the parent, assigned-child, other-child, automation, and unauthenticated access matrix.

### 6.4 Rehearsing a schema migration

- TBD — see §3 Phase 1 for production-like PostgreSQL migration and recovery behavior.

### 6.5 Adding or changing a quality gate

- TBD — see §3 Phase 3 for per-edit, end-of-turn, release, and CI placement.

### 6.6 Per-rollout-phase notes

- Append short, evidence-based lessons here as each rollout phase completes.

## 7. What We Deliberately Don't Test

- **Django Admin look-and-feel** — spend budget on authorization, secure transport,
  and data integrity rather than cosmetic presentation. Re-evaluate if admin
  becomes a user-facing product surface. (Source: Phase 2 interview Q5.)
- **Django framework internals** — verify FamilyNotes behavior at framework
  boundaries, not Django's own implementation. Re-evaluate only for a documented
  framework regression affecting this application.

## 8. Freshness Ledger

- Strategy (§1–§5) last reviewed: 2026-10-01
- Stack versions last verified: 2026-10-01
- AI-native tool references last verified: 2026-10-01

Refresh (`/10x-test-plan --refresh`) when:

- a new top-3 risk surfaces from the roadmap or archive,
- a recommended tool's `checked:` date is older than three months,
- the project's tech stack changes,
- §7 negative-space no longer matches what the team believes.
