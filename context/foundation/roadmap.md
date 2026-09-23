---
project: FamilyNotes
version: 1
status: draft
created: 2026-09-22
updated: 2026-09-23
prd_version: 1
main_goal: speed
top_blocker: capacity
milestone_id: first-family-capture-loop
milestone_seq: 1
milestone_status: open
---

# Roadmap: FamilyNotes

> Derived from `context/foundation/prd.md` (v1), `context/foundation/tech-stack.md`, `context/foundation/infrastructure.md`, and auto-researched codebase baseline.
> Edit-in-place; archive when superseded.
> Slices below are listed in dependency order. The "At a glance" table is the index.

## Milestone

**M-1: First Family Capture Loop** - Status: open

- **Intent:** Deliver the smallest working family information loop: signed-in family members, a parent capture flow, a saved entry, and child-safe visibility. The milestone proves that a parent can turn one natural-language school instruction into family data without exposing that data outside the configured family.
- **Source materials:** `context/foundation/prd.md` (v1)
- **Done when:** every F-NN and S-NN below is `done`.
- **Scope anchors:** FR-001 through FR-008, US-01, NFR family privacy, NFR 30-second classification-or-follow-up boundary, Access Control.

## Vision recap

FamilyNotes replaces scattered family tasks, events, and notes with one shared family space. The first product promise is a single accessible text field where a parent can enter a short natural-language instruction, review the proposed entry, correct it if needed, and save it for the right family member. The MVP stays focused on one preconfigured family and defers external integrations, custom audio capture, multi-family administration, and richer classification cases.

## North star

**S-01: Parent can classify, review, correct, and save one school event** - This is the north star, meaning the smallest end-to-end slice whose successful delivery proves the product's core promise: fast parent capture that becomes child-visible family data.

## At a glance

| ID   | Change ID                            | Outcome (user can ...)                                                    | Prerequisites | PRD refs                         | Status   |
| ---- | ------------------------------------ | ------------------------------------------------------------------------- | ------------- | -------------------------------- | -------- |
| F-01 | identity-and-family-access-contract  | (foundation) family identity, roles, and scoped access contract exist      | -             | FR-001, FR-002, FR-008, Access Control, NFR family privacy | planning |
| F-02 | classification-privacy-boundary      | (foundation) classification can run inside the privacy boundary            | -             | FR-004, Non-Functional Requirements, Business Logic | ready    |
| F-03 | production-health-release-gate       | (foundation) release health can be checked before family data is trusted   | -             | Non-Functional Requirements, `context/foundation/infrastructure.md` | ready    |
| S-01 | first-school-event-capture           | parent can classify, review, correct, and save one school event            | F-01, F-02    | US-01, FR-001, FR-002, FR-003, FR-004, FR-005, FR-008 | proposed |
| S-02 | parent-family-entry-management       | parent can manage saved family entries in a shared family view             | F-01, S-01    | FR-006, FR-008                  | proposed |
| S-03 | child-assigned-entry-view            | child can read only entries assigned to that child                         | F-01, S-01    | FR-007, FR-008                  | proposed |
| S-04 | missing-info-follow-up               | parent gets a follow-up question when required classification data is missing | F-02, S-01 | FR-004, FR-005, Business Logic  | proposed |

## Streams

Navigation aid - groups items that share a Prerequisites chain. Canonical ordering still lives in the dependency graph below; this table is the proposed reading order across parallel tracks.

| Stream | Theme                  | Chain                         | Note                                                             |
| ------ | ---------------------- | ----------------------------- | ---------------------------------------------------------------- |
| A      | Access-controlled data | `F-01` -> `S-01` -> `S-02` -> `S-03` | Drives the shortest path from signed-in family members to safe family visibility. |
| B      | Classification flow    | `F-02` -> `S-04`              | Joins Stream A at `S-01`; keeps classification behavior useful without expanding the first slice. |
| C      | Release confidence     | `F-03`                        | Stays parallel so launch checks do not delay the first product flow longer than necessary. |

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
- **Status:** planning

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
- **Status:** ready

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
- **Status:** ready

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
- **Status:** proposed

### S-02: Parent Family Entry Management

- **Outcome:** parent can create, read, update, and delete saved family entries in a shared family view.
- **Change ID:** parent-family-entry-management
- **PRD refs:** FR-006, FR-008
- **Prerequisites:** F-01, S-01
- **Parallel with:** S-03, S-04
- **Blockers:** -
- **Unknowns:** -
- **Risk:** Sequenced after the first capture flow so CRUD is grounded in real entry data instead of becoming a separate management surface.
- **Status:** proposed

### S-03: Child Assigned Entry View

- **Outcome:** child can read only entries assigned to that child in a personal view.
- **Change ID:** child-assigned-entry-view
- **PRD refs:** FR-007, FR-008
- **Prerequisites:** F-01, S-01
- **Parallel with:** S-02, S-04
- **Blockers:** -
- **Unknowns:** -
- **Risk:** Sequenced once entries exist so child access can be tested against real assigned and unassigned data.
- **Status:** proposed

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

## Backlog Handoff

| Roadmap ID | Change ID                           | Suggested issue title                               | Ready for `/10x-plan` | Notes |
| ---------- | ----------------------------------- | --------------------------------------------------- | --------------------- | ----- |
| F-01       | identity-and-family-access-contract | Establish identity, roles, and family access guard  | yes                   | Unlocks the first capture slice and all family-data paths. |
| F-02       | classification-privacy-boundary     | Establish privacy boundary for classification       | yes                   | Unlocks classified proposal behavior. |
| F-03       | production-health-release-gate      | Establish production health release gate            | yes                   | Can run in parallel with product foundations. |
| S-01       | first-school-event-capture          | Parent captures first school event from text        | no                    | Wait for F-01 and F-02. |
| S-02       | parent-family-entry-management      | Parent manages saved family entries                 | no                    | Wait for F-01 and S-01. |
| S-03       | child-assigned-entry-view           | Child sees only assigned entries                    | no                    | Wait for F-01 and S-01. |
| S-04       | missing-info-follow-up              | Parent receives follow-up for missing required data | no                    | Wait for F-02 and S-01. |

## Open Roadmap Questions

1. **What validation and follow-up rules apply to classification cases other than tests, homework, and calendar entries?** - Owner: user. Block: S-04 future expansion beyond defined MVP cases.

## Parked

- **Custom audio recording or speech-to-text conversion** - Why parked: PRD Non-Goals; users may type or use phone keyboard dictation.
- **External calendar, task, and source integrations** - Why parked: PRD Non-Goals; post-MVP extension.
- **Read-only kiosk view or token authentication** - Why parked: PRD Non-Goals; post-MVP extension.
- **In-app family or role management and multiple-family support** - Why parked: PRD Non-Goals; the MVP uses one preconfigured five-person family.
- **Explicit accessibility targets beyond default browser behavior** - Why parked: PRD Non-Goals; deferred requirement.
- **Response-time target below 30 seconds** - Why parked: PRD Non-Goals; performance improvements are deferred beyond the MVP threshold.

## Milestone History

## Done
