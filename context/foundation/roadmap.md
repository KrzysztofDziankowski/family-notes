---
project: FamilyNotes
version: 1
status: draft
created: 2026-09-22
updated: 2026-09-28
prd_version: 2
main_goal: speed
top_blocker: capacity
milestone_id: first-family-capture-loop
milestone_seq: 1
milestone_status: open
---

# Roadmap: FamilyNotes

> Derived from `context/foundation/prd.md` (v2), `context/foundation/tech-stack.md`, `context/foundation/infrastructure.md`, and auto-researched codebase baseline.
> Edit-in-place; archive when superseded.
> Slices below are listed in dependency order. The "At a glance" table is the index.

## Milestone

**M-1: First Family Capture Loop** - Status: open

- **Intent:** Deliver the smallest working family information loop: signed-in family members, a parent capture flow, a saved entry, and child-safe visibility. The milestone proves that a parent can turn one natural-language school instruction into family data without exposing that data outside the configured family.
- **Source materials:** `context/foundation/prd.md` (v2; v2 added automated EduVulcan school intake on 2026-09-27) plus the owner-directed scope extension `MS-01` added on 2026-09-28.
- **Done when:** every F-NN and S-NN below is `done`.
- **Scope anchors:** FR-001 through FR-011, US-01, US-02, NFR family privacy, NFR 30-second classification-or-follow-up boundary, NFR token revocation, Access Control; **MS-01:** an active parent-owned automation token can read all entries belonging to that parent's family through a read-only REST API, while never exposing another family's entries or permitting entry mutation.

## Vision recap

FamilyNotes replaces scattered family tasks, events, and notes with one shared family space. The first product promise is a single accessible text field where a parent can enter a short natural-language instruction, review the proposed entry, correct it if needed, and save it for the right family member. A parent-owned automation can also forward EduVulcan school notifications and read the family's saved entries through a family-scoped, read-only REST API using the parent's token. The MVP stays focused on one preconfigured family and defers other external integrations, custom audio capture, multi-family administration, and richer classification cases.

## North star

**S-01: Parent can classify, review, correct, and save one school event** - This is the north star, meaning the smallest end-to-end slice whose successful delivery proves the product's core promise: fast parent capture that becomes child-visible family data.

## At a glance

| ID   | Change ID                            | Outcome (user can ...)                                                    | Prerequisites | PRD refs                         | Status   |
| ---- | ------------------------------------ | ------------------------------------------------------------------------- | ------------- | -------------------------------- | -------- |
| F-01 | identity-and-family-access-contract  | (foundation) family identity, roles, and scoped access contract exist      | -             | FR-001, FR-002, FR-008, Access Control, NFR family privacy | done        |
| F-02 | classification-privacy-boundary      | (foundation) classification can run inside the privacy boundary            | -             | FR-004, Non-Functional Requirements, Business Logic | done        |
| F-03 | production-health-release-gate       | (foundation) release health can be checked before family data is trusted   | -             | Non-Functional Requirements, `context/foundation/infrastructure.md` | done        |
| F-04 | automation-token-access              | (foundation) a parent's automation can authenticate with an admin-issued, revocable token, and its notifications are stored fast in a pre-events table | F-01 | FR-009, Access Control, NFR token revocation, NFR fast intake | done        |
| S-01 | first-school-event-capture           | parent can classify, review, correct, and save one school event            | F-01, F-02    | US-01, FR-001, FR-002, FR-003, FR-004, FR-005, FR-008 | done        |
| S-02 | parent-family-entry-management       | parent can manage saved family entries in a shared family view             | F-01, S-01    | FR-006, FR-008                  | done     |
| S-03 | child-assigned-entry-view            | child can read only entries assigned to that child                         | F-01, S-01    | FR-007, FR-008                  | done     |
| S-04 | missing-info-follow-up               | parent gets a follow-up question when required classification data is missing | F-02, S-01 | FR-004, FR-005, Business Logic  | proposed |
| S-05 | eduvulcan-school-event-intake        | stored EduVulcan notifications are converted asynchronously into school entries | S-01, F-02, F-04 | US-02, FR-010, FR-011, Business Logic, NFR fast intake | in-progress |
| S-06 | family-entries-rest-api               | parent-owned automation can retrieve all entries of its family through a read-only REST API | F-04, S-01 | MS-01, NFR family privacy, NFR token revocation | planning |

## Streams

Navigation aid - groups items that share a Prerequisites chain. Canonical ordering still lives in the dependency graph below; this table is the proposed reading order across parallel tracks.

| Stream | Theme                  | Chain                         | Note                                                             |
| ------ | ---------------------- | ----------------------------- | ---------------------------------------------------------------- |
| A      | Access-controlled data | `F-01` -> `S-01` -> `S-02` -> `S-03` | Drives the shortest path from signed-in family members to safe family visibility. |
| B      | Classification flow    | `F-02` -> `S-04`              | Joins Stream A at `S-01`; keeps classification behavior useful without expanding the first slice. |
| C      | Release confidence     | `F-03`                        | Stays parallel so launch checks do not delay the first product flow longer than necessary. |
| D      | Token automation       | `F-04` -> `S-05`; `F-04` -> `S-06` | The shared token boundary independently enables school-notification intake and read-only, family-scoped entry retrieval. |

## Baseline

What's already in place in the codebase as of `2026-09-22` (auto-researched + user-confirmed by fallback procedure).
Foundations below assume these are present and do NOT re-scaffold them.

- **Frontend:** partial - Django template exists for a placeholder home screen at `family_notes/templates/family_notes/home.html:64`; no product entry UI yet.
- **Backend / API:** partial - Django root and health routes exist in `family_notes/urls.py:21`; no product entry handlers yet.
- **Data:** partial - database settings support SQLite/PostgreSQL in `family_notes/settings.py:101`; no product models are present.
- **Auth:** partial - Django auth middleware/apps are configured in `family_notes/settings.py:59`; external identity, roles, and route-level family access are not wired.
- **Deploy / infra:** partial - Mikr.us deployment decision and runbook material exist in `context/foundation/infrastructure.md:14`; production delivery is not yet product-ready.
- **Observability:** partial - `/healthz/` checks database connectivity in `family_notes/views.py:10`; broader logging and alerts are not implemented.

## Foundations

### F-01: Identity and Family Access Contract

- **Outcome:** (foundation) family members can be represented with external identity, preassigned parent/child roles, and a single-family access boundary.
- **Change ID:** identity-and-family-access-contract
- **PRD refs:** FR-001, FR-002, FR-008, Access Control, NFR family privacy
- **Unlocks:** S-01, S-02, S-03; access tests for parent, assigned child, other child, and unauthenticated paths
- **Prerequisites:** -
- **Parallel with:** F-02, F-03
- **Blockers:** -
- **Unknowns:** -
- **Risk:** Sequenced first because every family-data path depends on identity and scoped access; the risk is overbuilding family administration that the PRD explicitly defers.
- **Status:** done

### F-02: Classification Privacy Boundary

- **Outcome:** (foundation) classification requests can be made while limiting submitted text to producing and saving the requested family entry.
- **Change ID:** classification-privacy-boundary
- **PRD refs:** FR-004, Non-Functional Requirements, Business Logic
- **Unlocks:** S-01, S-04; verification that submitted classification text is not reused for secondary storage, analytics, or training
- **Prerequisites:** -
- **Parallel with:** F-01, F-03
- **Blockers:** -
- **Unknowns:** -
- **Risk:** Sequenced before the first capture slice because classification input is sensitive; the risk is letting provider details leak into product planning instead of keeping the boundary minimal.
- **Status:** done

### F-03: Production Health Release Gate

- **Outcome:** (foundation) the app has a minimal release health gate for database-backed readiness before family data is trusted in production.
- **Change ID:** production-health-release-gate
- **PRD refs:** Non-Functional Requirements, `context/foundation/infrastructure.md`
- **Unlocks:** release verification path for S-01, S-02, S-03, and S-04
- **Prerequisites:** -
- **Parallel with:** F-01, F-02
- **Blockers:** -
- **Unknowns:** -
- **Risk:** Sequenced as a launch enabler because the chosen infrastructure is self-managed; the risk is turning operations hardening into a broad deployment project instead of a minimal health gate.
- **Status:** done

### F-04: Automation Token Access

- **Outcome:** (foundation) a parent's automation can authenticate with a token issued and revoked by the administrator, and the token acts only on behalf of that parent's family; its notifications are stored fast in a pre-events table (`InboundNotification`, 202 with no classification in the request).
- **Change ID:** automation-token-access
- **PRD refs:** FR-009, Access Control, NFR token revocation, NFR fast intake
- **Unlocks:** S-05; access tests for a valid token, a revoked token, a missing/unknown token, and a token owned by a child or inactive member
- **Prerequisites:** F-01
- **Parallel with:** S-01, S-02, S-03, S-04
- **Blockers:** -
- **Unknowns:** -
- **Risk:** The token is a second authentication path beside the signed-in session; the risk is letting it reach anything other than school intake. Kept admin-only (no parent-facing page) to stay inside the MVP's no-in-app-administration stance.
- **Progress (2026-09-28):** All three phases are implemented and merged to master. Production ping and real-phone intake were verified on 2026-09-27. Impl-reviewed 2026-09-28 (`reviews/impl-review.md`), and triage fixes landed in `9c74c0c`. Intake now answers 400 for impossible dates and NUL characters. Next: `/10x-archive`.
- **Status:** done

## Slices

### S-01: First School Event Capture

- **Outcome:** parent can classify, review, correct, and save one school event from natural-language text.
- **Change ID:** first-school-event-capture
- **PRD refs:** US-01, FR-001, FR-002, FR-003, FR-004, FR-005, FR-008
- **Prerequisites:** F-01, F-02
- **Parallel with:** F-03
- **Blockers:** -
- **Unknowns:** -
- **Risk:** This is the first product proof; keeping it to the school-event case prevents the broader classification question from blocking the core flow.
- **Progress (2026-09-28):** All four phases are implemented and merged to master. This adds the `Entry` model (with a `source` marker, open to S-05), vendored Pico CSS, `tokens.css` and `base.html`. Impl-reviewed 2026-09-28 (`reviews/impl-review.md`), and triage fixes landed in `173ac3a`. Next: `/10x-archive`, which unblocks S-02, S-03, S-04 and S-05.
- **Decision for later slices:** `Entry.assigned_member` is `RESTRICT`. People are deactivated, never deleted (README "Create the initial family"). S-02 deletes entries, not members.
- **Status:** done

### S-02: Parent Family Entry Management

- **Outcome:** parent can create, read, update, and delete saved family entries in a shared family view.
- **Change ID:** parent-family-entry-management
- **PRD refs:** FR-006, FR-008
- **Prerequisites:** F-01, S-01
- **Parallel with:** S-03, S-04
- **Blockers:** -
- **Unknowns:** -
- **Risk:** Sequenced after the first capture flow so CRUD is grounded in real entry data instead of becoming a separate management surface.
- **Status:** done

### S-03: Child Assigned Entry View

- **Outcome:** child can read only entries assigned to that child in a personal view.
- **Change ID:** child-assigned-entry-view
- **PRD refs:** FR-007, FR-008
- **Prerequisites:** F-01, S-01
- **Parallel with:** S-02, S-04
- **Blockers:** -
- **Unknowns:** -
- **Risk:** Sequenced once entries exist so child access can be tested against real assigned and unassigned data.
- **Status:** done

### S-04: Missing Information Follow-Up

- **Outcome:** parent gets a follow-up question before confirmation when required classification data is missing.
- **Change ID:** missing-info-follow-up
- **PRD refs:** FR-004, FR-005, Business Logic
- **Prerequisites:** F-02, S-01
- **Parallel with:** S-02, S-03
- **Blockers:** -
- **Unknowns:**
  - What validation and follow-up rules apply beyond tests, homework, and calendar entries? - Owner: user. Block: no.
- **Risk:** Sequenced after the first capture case so missing-field behavior extends proven classification rather than delaying the initial end-to-end flow.
- **Status:** proposed

### S-05: EduVulcan School Event Intake

- **Outcome:** a parent's automation can forward a captured EduVulcan notification with the parent's token, and it is saved (without confirmation) as a school entry for the named child, deduplicated, and visible in the family and child views.
- **Change ID:** eduvulcan-school-event-intake
- **PRD refs:** US-02, FR-010, FR-011, Business Logic
- **Prerequisites:** S-01, F-02, F-04
- **Parallel with:** S-02, S-03, S-04
- **Blockers:** -
- **Unknowns:**
  - Is the notification title set and message format stable enough for fixed rules, or will fallback classification carry most of the load? - Owner: user. Block: no (fallback to classification, then general note, covers drift).
- **Intake split (2026-09-27):** F-04 owns the fast endpoint and the `InboundNotification` pre-events table (store + 202, dedup by id and same-day content). S-05 converts pending rows outside the request: fixed rules → LLM fallback → general note, via an in-process in-memory queue with no external dependency, with the DB row as the source of truth plus a restart sweep. See F-04 plan "S-05 Handoff".
- **Inherited from F-04/S-01 review (2026-09-28):**
  - `/admin/` stays in English (lessons.md), so the Polish copy in the token/intake admin is to be translated as a follow-up.
  - EduVulcan entries assigned to a child make that member RESTRICT-protected, so deactivate rather than delete.
  - When S-05 next touches these files, move `family_access/test_automation.py` into a `tests/` package and pick one namespace for the `api/automation/` URLs.
- **Risk:** Depends on the entry model shaped by S-01, which must allow a source marker and entries created without a confirmation step. Real sample notifications (gitignored `eduvulcan-queue/`) contain names, so fixtures must be anonymized before they enter the repo. The LLM fallback sends notification text through the F-02 privacy boundary.
- **Status:** in-progress

### S-06: Family Entries REST API

- **Outcome:** an automation holding an active parent's token can retrieve all entries belonging to that parent's family through a read-only REST API.
- **Change ID:** family-entries-rest-api
- **PRD refs:** MS-01, NFR family privacy, NFR token revocation
- **Prerequisites:** F-04, S-01
- **Parallel with:** S-04, S-05
- **Blockers:** -
- **Unknowns:**
  - What response contract and pagination behavior should clients rely on as the number of entries grows? - Owner: user. Block: no; `/10x-plan` should select and document a minimal stable contract.
- **Risk:** This deliberately expands automation-token authority beyond the PRD v2 write-only intake boundary. Every read must be scoped from the authenticated token owner's active parent membership, revoked or invalid tokens must fail closed, foreign-family data must never be distinguishable or returned, and the endpoint must expose no mutation capability.
- **Status:** planning

## Backlog Handoff

| Roadmap ID | Change ID                           | Suggested issue title                               | Ready for `/10x-plan` | Notes |
| ---------- | ----------------------------------- | --------------------------------------------------- | --------------------- | ----- |
| F-01       | identity-and-family-access-contract | Establish identity, roles, and family access guard  | yes                   | Unlocks the first capture slice and all family-data paths. |
| F-02       | classification-privacy-boundary     | Establish privacy boundary for classification       | yes                   | Unlocks classified proposal behavior. |
| F-03       | production-health-release-gate      | Establish production health release gate            | yes                   | Can run in parallel with product foundations. |
| S-01       | first-school-event-capture          | Parent captures first school event from text        | n/a                   | Archived 2026-09-28. |
| S-02       | parent-family-entry-management      | Parent manages saved family entries                 | no                    | Planning started; formally ready once S-01 is archived. |
| S-03       | child-assigned-entry-view           | Child sees only assigned entries                    | no                    | Ready once S-01 is archived. |
| S-04       | missing-info-follow-up              | Parent receives follow-up for missing required data | no                    | Ready once S-01 is archived. |
| F-04       | automation-token-access             | Admin-issued automation tokens for parents          | n/a                   | Archived 2026-09-28. |
| S-05       | eduvulcan-school-event-intake       | Automation forwards EduVulcan notifications as school entries | no          | Ready once S-01 and F-04 are archived; plan against F-04 "S-05 Handoff". |
| S-06       | family-entries-rest-api              | Parent-owned automation retrieves its family's entries through REST | yes       | F-04 and S-01 are done; preserve strict family scoping and read-only token authority. |

## Open Roadmap Questions

1. **What validation and follow-up rules apply to classification cases other than tests, homework, and calendar entries?** - Owner: user. Block: S-04 future expansion beyond defined MVP cases.

## Parked

- **Custom audio recording or speech-to-text conversion** - Why parked: PRD Non-Goals; users may type or use phone keyboard dictation.
- **External calendar, task, and source integrations (other than forwarded EduVulcan notifications)** - Why parked: PRD Non-Goals; post-MVP extension. EduVulcan intake moved into scope in PRD v2 (S-05).
- **Read-only kiosk view** - Why parked: PRD Non-Goals; post-MVP extension. Owner-directed scope anchor MS-01 moves family-entry REST reads by a parent-owned token into S-06, but does not add a kiosk UI or anonymous access.
- **In-app token management page for parents** - Why parked: PRD v2 Non-Goals; tokens are issued and revoked by the administrator.
- **Reading EduVulcan directly (API/scraping)** - Why parked: PRD v2 Non-Goals; the product only receives notifications the parent's automation forwards.
- **In-app family or role management and multiple-family support** - Why parked: PRD Non-Goals; the MVP uses one preconfigured five-person family.
- **Explicit accessibility targets beyond default browser behavior** - Why parked: PRD Non-Goals; deferred requirement.
- **Response-time target below 30 seconds** - Why parked: PRD Non-Goals; performance improvements are deferred beyond the MVP threshold.
- **OpenAI Zero Data Retention (ZDR) for classification** - Why parked: owner decision 2026-09-27; the MVP ships classification with `store=False` and sanitized logs only, accepting OpenAI abuse-monitoring retention. Revisit after the MVP: obtain ZDR approval for the production OpenAI project and reintroduce a fail-closed attestation gate (removed from F-02 `classification-privacy-boundary`).

## Milestone History

## Done

- **F-01: (foundation) family members can be represented with external identity, preassigned parent/child roles, and a single-family access boundary.** — Archived 2026-09-26 → `context/archive/2026-09-23-identity-and-family-access-contract/`. Lesson: —.
- **F-03: (foundation) the app has a minimal release health gate for database-backed readiness before family data is trusted in production.** — Archived 2026-09-26 → `context/archive/2026-09-24-production-health-release-gate/`. Lesson: —.
- **F-02: (foundation) classification requests can be made while limiting submitted text to producing and saving the requested family entry.** — Archived 2026-09-27 → `context/archive/2026-09-24-classification-privacy-boundary/`. Lesson: —.
- **F-04: (foundation) a parent's automation can authenticate with a token issued and revoked by the administrator, and the token acts only on behalf of that parent's family; its notifications are stored fast in a pre-events table (`InboundNotification`, 202 with no classification in the request).** — Archived 2026-09-28 → `context/archive/2026-09-27-automation-token-access/`. Lesson: —.
- **S-01: parent can classify, review, correct, and save one school event from natural-language text.** — Archived 2026-09-28 → `context/archive/2026-09-27-first-school-event-capture/`. Lesson: —.
- **S-03: child can read only entries assigned to that child in a personal view.** — Archived 2026-09-28 → `context/archive/2026-09-28-child-assigned-entry-view/`. Lesson: —.
- **S-02: parent can create, read, update, and delete saved family entries in a shared family view.** — Archived 2026-09-28 → `context/archive/2026-09-28-parent-family-entry-management/`. Lesson: —.
