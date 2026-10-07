---
project: FamilyNotes
version: 2
status: draft
created: 2026-10-04
updated: 2026-10-05
prd_version: 2
main_goal: quality
top_blocker: decisions
milestone_id: improved-family-capture
milestone_seq: 2
milestone_status: proposed
---

# Future Roadmap: FamilyNotes

> Derived from `context/foundation/prd-v2.md` and the confirmed codebase baseline.
> Owner-requested separate future draft; the active roadmap remains unchanged and authoritative.
> This is not an open milestone or a downstream status-tracking file. Proposed milestone sequence is provisional until activation.
> All PK-NN and US-NN references refer to prd-v2.md.

## Milestone

**Proposed M-2: Improved Family Capture** — Status: proposed

- **Intent:** Improve family capture correctness and review, mobile capture, accessibility, and in-app family administration.
- **Source materials:** `context/foundation/prd-v2.md` (draft v2); owner replacement decision 2026-10-06 to require type-specific dates and hide types in listing views (S-21).
- **Done when:** after activation and scope confirmation, every included slice is done and the selected release success criteria are met.
- **Scope anchors:** PK-01–PK-10, PK-16 (without invitations), PK-17, PK-20; US-01–US-11. Owner removed PK-12–PK-15, PK-18, PK-19 on 2026-10-04 (see Parked). Audio capture is excluded.
- **Activation boundary:** confirm scope, finish or explicitly abandon the current open milestone, then adopt the agreed tranche into the canonical roadmap. Do not open a second milestone through this file.
- **Framing:** owner confirmed on 2026-10-04 that all remaining slices belong to the next milestone, in the order below; no feature flags, no backfill, no E2E tests yet. The owner replaced S-21 on 2026-10-06: retain three types, require dates on writes, hide types in lists, and backfill missing dates and enforce non-null storage. Product decisions are largely resolved. Invest in classification correctness, existing-data compatibility, and review clarity; reuse application foundations.

## Vision recap

Parents have recorded improvements to name recognition, school-event details, text submission and correction, assignment, list organization, and mobile classification feedback. They also want one instruction to produce multiple entries. On 2026-10-04 the owner kept accessibility and family administration (without invitations) and removed integrations, kiosk, token self-service, direct school reading, response-time and zero-retention work.

## North star

The north star is the smallest complete user flow that demonstrates the intended improvement. **S-01: Parent can review school event type and supply date, person, and subject** comes first.

## At a glance

Confirmed delivery order (owner asked the agent to determine it, 2026-10-04): the classification chain first (S-01, S-02, S-20, S-03, S-04, which share classification files and should merge in sequence), then capture UX (S-05 before S-06: shared busy-flag contract), the cheap list/assignment/sign-in slices (S-07 → S-09), accessibility (S-17) once those templates exist, and family administration last (S-14 → S-16, highest risk; new pages built on S-17's audit helper).

| # | ID | Change ID | Outcome (user can …) | Prerequisites | PRD refs | Status |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | S-01 | school-event-details | Parent can review the specific school event type and supply required date, person, and subject. | — | PK-08, PK-09, US-08, US-09 | planning |
| 2 | S-02 | classification-short-names | Parent can assign an entry using a short family-member name. | — | PK-01, US-01 | planning |
| 3 | S-20 | title-keeps-action-only | Parent sees an entry title that keeps only the action after the person and date are extracted. | S-02 | PK-20, US-11 | planning |
| 4 | S-03 | free-text-proposal-correction | Parent can correct an existing proposal through free text. | — | PK-10, US-10 | planning |
| 5 | S-04 | multi-entry-text-capture | Parent can review and save several entries from one instruction. | S-03 | PK-05, US-05 | planning |
| 6 | S-05 | enter-text-submission | Parent can submit form text by pressing Enter. | — | PK-07, US-07 | planning |
| 7 | S-06 | mobile-classification-progress | Parent can see background classification activity and its result on a phone. | S-05 | PK-06, US-06 | planning |
| 8 | S-07 | parent-note-assignment | Parent can reliably assign a new note to themselves or another parent in the family. | — | PK-03, US-03 | planning |
| 9 | S-08 | parent-list-child-grouping | Parent can browse family entries grouped by child. | — | PK-04, US-04 | planning |
| 10 | S-09 | remove-sign-up-option | User can sign in through the intended account flow without a sign-up option. | — | PK-02, US-02 | planning |
| 11 | S-17 | accessible-family-flows | Family member can use the agreed family flows under explicit accessibility criteria. | — | PK-17 | planning |
| 12 | S-14 | family-membership-management | Authorized family manager can manage family members in the application. | S-17 (soft — reuse audit helper) | PK-16 | planning |
| 13 | S-15 | family-role-management | Authorized family manager can manage roles in the application. | S-14 | PK-16 | planning |
| 14 | S-16 | multiple-family-use | Authorized member can use the application across multiple families. | S-14, S-15 | PK-16 | planning |
| 15 | S-21 | entry-date-semantics | Entries require meaningful dates; family listings hide type labels. | S-01, S-03, S-04, S-20 | Owner decision 2026-10-06 | in-progress |

## Baseline

Researched on 2026-10-04; deployment evidence is repository documentation, not a fresh remote check. The older scaffold-only baseline has been superseded.

- **Frontend:** present — capture, review, follow-up, management, and child views (`entries/urls.py:8`); shared tokens (`family_notes/static/css/tokens.css:1`). Review currently hides school type (`entries/forms.py:114`); management exposes it (`entries/forms.py:169`).
- **Backend / API:** present — parent management and child handlers (`entries/views.py:480`), automation intake and family reads (`entries/api_views.py:88`), and school conversion (`entries/eduvulcan/worker.py:129`).
- **Data:** present — family/member/token models (`family_access/models.py:10`), entries and notifications (`entries/models.py:16`). Four school kinds already exist (`entries/classification/types.py:43`); a school subject is absent. One active membership per user currently constrains multiple-family use (`family_access/models.py:46`).
- **Auth:** present — external identity sign-in (`family_notes/settings.py:298`), family scoping (`family_access/access.py:6`), assigned-child visibility (`entries/services.py:257`). A sign-up link remains (`family_notes/templates/account/login.html:37`). Parent assignment is already permitted by the active-family-member queryset (`entries/forms.py:86`); verify end-to-end behavior before adding functionality.
- **Deploy / infra:** present — operator-confirmed deployment and service setup (`context/changes/deployment/mikrus-runbook.md:18`), release and readiness tooling (`scripts/deployment/release.sh:39`).
- **Observability:** partial — readiness and conversion health (`entries/health_views.py:14`), application logging (`family_notes/settings.py:382`), and worker warnings (`entries/eduvulcan/worker.py:252`); no general error-tracking or alerting integration found. This does not authorize a separate monitoring feature absent from the source PRD.

## Foundations

No new foundations are proposed. Existing application layers are available; each vertical slice integrates the minimum changes needed for its outcome. Current work remains tracked only in the active roadmap.

## Slices

### S-01: Parent can review the specific school event type and supply required date, person, and subject

- **Outcome:** Parent can review the specific school event type and supply required date, person, and subject.
- **Change ID:** school-event-details
- **PRD refs:** PK-08, PK-09, US-08, US-09
- **Prerequisites:** —
- **Parallel with:** S-02, S-03, S-04, S-05, S-06, S-07, S-08, S-09, S-17, S-14, S-15, S-16, S-20
- **Blockers:** —
- **Unknowns:**
  - Resolved 2026-10-04: in next milestone; school subject is free text for now (enum may follow); no backfill; no feature flag. Remaining editing/visibility details are assumed defaults in the plan.
- **Risk:** The four school types already exist; show them during review and require subject while preserving existing entries and automated intake.
- **Plan:** `context/changes/school-event-details/plan.md`
- **Status:** planning

### S-02: Parent can assign an entry using a short family-member name

- **Outcome:** Parent can assign an entry using a short family-member name.
- **Change ID:** classification-short-names
- **PRD refs:** PK-01, US-01
- **Prerequisites:** —
- **Parallel with:** S-01, S-03, S-04, S-05, S-06, S-07, S-08, S-09, S-17, S-14, S-15, S-16
- **Blockers:** —
- **Unknowns:**
  - Resolved 2026-10-04: built-in, code-maintained diminutive dictionary for now.
- **Risk:** Family-scoped ambiguity must be resolved before assigning an entry.
- **Plan:** `context/changes/classification-short-names/plan.md`
- **Status:** planning

### S-20: Parent sees an entry title that keeps only the action after the person and date are extracted

- **Outcome:** Parent sees an entry title that keeps only the action after the person and date are extracted.
- **Change ID:** title-keeps-action-only
- **PRD refs:** PK-20, US-11
- **Prerequisites:** S-02
- **Parallel with:** S-01, S-03, S-04, S-05, S-06, S-07, S-08, S-09, S-17, S-14, S-15, S-16
- **Blockers:** —
- **Unknowns:**
  - Resolved 2026-10-04: owner example "kasia zrobić pranie w piątek" → title "zrobić pranie", date the coming Friday, assigned Kasia. Remaining wording details are assumed defaults in the plan.
- **Risk:** Shares the classification prompt and adapter with S-01–S-04; merge in sequence. Removing words from the title must never drop meaning that was not extracted into another field.
- **Plan:** `context/changes/title-keeps-action-only/plan.md`
- **Status:** planning

### S-03: Parent can correct an existing proposal through free text

- **Outcome:** Parent can correct an existing proposal through free text.
- **Change ID:** free-text-proposal-correction
- **PRD refs:** PK-10, US-10
- **Prerequisites:** —
- **Parallel with:** S-01, S-02, S-05, S-06, S-07, S-08, S-09, S-17, S-14, S-15, S-16, S-20
- **Blockers:** —
- **Unknowns:**
  - Resolved 2026-10-04: correction only before saving; Europe/Warsaw relative-date rules.
- **Risk:** Corrections must preserve unmentioned values and the selected proposal.
- **Plan:** `context/changes/free-text-proposal-correction/plan.md`
- **Status:** planning

### S-04: Parent can review and save several entries from one instruction

- **Outcome:** Parent can review and save several entries from one instruction.
- **Change ID:** multi-entry-text-capture
- **PRD refs:** PK-05, US-05
- **Prerequisites:** S-03
- **Parallel with:** S-01, S-02, S-05, S-06, S-07, S-08, S-09, S-17, S-14, S-15, S-16, S-20
- **Blockers:** —
- **Unknowns:**
  - Resolved 2026-10-04: all-or-nothing batch save; Europe/Warsaw relative-date rules ("w przyszłym tygodniu w poniedziałek" = Monday of next calendar week).
- **Risk:** Ambiguous relative dates and partial saves require explicit behavior.
- **Plan:** `context/changes/multi-entry-text-capture/plan.md`
- **Status:** planning

### S-05: Parent can submit form text by pressing Enter

- **Outcome:** Parent can submit form text by pressing Enter.
- **Change ID:** enter-text-submission
- **PRD refs:** PK-07, US-07
- **Prerequisites:** —
- **Parallel with:** S-01, S-02, S-03, S-04, S-07, S-08, S-09, S-17, S-14, S-15, S-16, S-20
- **Blockers:** —
- **Unknowns:**
  - Resolved 2026-10-04: Enter also submits on a phone's virtual keyboard.
- **Risk:** Submission must account for multiline input and keyboard composition.
- **Plan:** `context/changes/enter-text-submission/plan.md`
- **Status:** planning

### S-06: Parent can see background classification activity and its result on a phone

- **Outcome:** Parent can see background classification activity and its result on a phone.
- **Change ID:** mobile-classification-progress
- **PRD refs:** PK-06, US-06
- **Prerequisites:** S-05
- **Parallel with:** S-01, S-02, S-03, S-04, S-07, S-08, S-09, S-17, S-14, S-15, S-16, S-20
- **Blockers:** —
- **Unknowns:**
  - Resolved 2026-10-04: installable PWA; push notifications deferred to a future change.
- **Risk:** Background lifecycle expectations determine what progress can promise.
- **Plan:** `context/changes/mobile-classification-progress/plan.md`
- **Status:** planning

### S-07: Parent can reliably assign a new note to themselves or another parent in the family

- **Outcome:** Parent can reliably assign a new note to themselves or another parent in the family.
- **Change ID:** parent-note-assignment
- **PRD refs:** PK-03, US-03
- **Prerequisites:** —
- **Parallel with:** S-01, S-02, S-03, S-04, S-05, S-06, S-08, S-09, S-17, S-14, S-15, S-16, S-20
- **Blockers:** —
- **Unknowns:**
  - Resolved 2026-10-04: in next milestone; plan verifies existing behaviour with a two-parent test matrix, and adds "dla mnie" self-reference resolution to the requesting parent (sends the requester's name to classification — owner-approved).
- **Risk:** The form already permits parent assignment; verify the complete flow and address only demonstrated gaps, preserving family isolation.
- **Plan:** `context/changes/parent-note-assignment/plan.md`
- **Status:** planning

### S-08: Parent can browse family entries grouped by child

- **Outcome:** Parent can browse family entries grouped by child.
- **Change ID:** parent-list-child-grouping
- **PRD refs:** PK-04, US-04
- **Prerequisites:** —
- **Parallel with:** S-01, S-02, S-03, S-04, S-05, S-06, S-07, S-09, S-17, S-14, S-15, S-16, S-20
- **Blockers:** —
- **Unknowns:**
  - Resolved 2026-10-04: children first, then each parent, then "Cała rodzina" last.
- **Risk:** Parent-assigned and unassigned entries must remain discoverable.
- **Plan:** `context/changes/parent-list-child-grouping/plan.md`
- **Status:** planning

### S-09: User can sign in through the intended account flow without a sign-up option

- **Outcome:** User can sign in through the intended account flow without a sign-up option.
- **Change ID:** remove-sign-up-option
- **PRD refs:** PK-02, US-02
- **Prerequisites:** —
- **Parallel with:** S-01, S-02, S-03, S-04, S-05, S-06, S-07, S-08, S-17, S-14, S-15, S-16, S-20
- **Blockers:** —
- **Unknowns:**
  - Resolved 2026-10-04: close username/password sign-up; keep first Google sign-in auto-creating a user that the admin maps to a family member.
- **Risk:** Removing sign-up must not prevent intended family-account provisioning.
- **Plan:** `context/changes/remove-sign-up-option/plan.md`
- **Status:** planning

### S-17: Family member can use the agreed family flows under explicit accessibility criteria

- **Outcome:** Family member can use the agreed family flows under explicit accessibility criteria.
- **Change ID:** accessible-family-flows
- **PRD refs:** PK-17
- **Prerequisites:** —
- **Parallel with:** S-01, S-02, S-03, S-04, S-05, S-06, S-07, S-08, S-09, S-14, S-15, S-16, S-20
- **Blockers:** —
- **Unknowns:**
  - Resolved 2026-10-04: target is WCAG 2.2 AA for the covered family flows.
- **Risk:** Named criteria and covered flows are needed to verify improvement.
- **Plan:** `context/changes/accessible-family-flows/plan.md`
- **Status:** planning

### S-14: Authorized family manager can manage family members in the application

- **Outcome:** Authorized family manager can manage family members in the application.
- **Change ID:** family-membership-management
- **PRD refs:** PK-16
- **Prerequisites:** S-17 (soft — reuse audit helper)
- **Parallel with:** S-01, S-02, S-03, S-04, S-05, S-06, S-07, S-08, S-09, S-20
- **Blockers:** —
- **Unknowns:**
  - Resolved 2026-10-04: every active parent is a manager; families created by the operator in admin; no invitation flow — adding members stays in Django admin.
- **Risk:** Membership authority must be established before adding administration.
- **Plan:** `context/changes/family-membership-management/plan.md`
- **Status:** planning

### S-15: Authorized family manager can manage roles in the application

- **Outcome:** Authorized family manager can manage roles in the application.
- **Change ID:** family-role-management
- **PRD refs:** PK-16
- **Prerequisites:** S-14
- **Parallel with:** S-01, S-02, S-03, S-04, S-05, S-06, S-07, S-08, S-09, S-17, S-20
- **Blockers:** —
- **Unknowns:**
  - Resolved 2026-10-04: every active parent may manage roles (see S-14 decisions).
- **Risk:** Role changes must not permit unauthorized privilege escalation.
- **Plan:** `context/changes/family-role-management/plan.md`
- **Status:** planning

### S-16: Authorized member can use the application across multiple families

- **Outcome:** Authorized member can use the application across multiple families.
- **Change ID:** multiple-family-use
- **PRD refs:** PK-16
- **Prerequisites:** S-14, S-15
- **Parallel with:** S-01, S-02, S-03, S-04, S-05, S-06, S-07, S-08, S-09, S-17, S-20
- **Blockers:** —
- **Unknowns:**
  - Resolved 2026-10-04: family context kept in the session with a family chooser; extra memberships created by the operator in admin.
- **Risk:** Every view and mutation must use the authorized family context.
- **Plan:** `context/changes/multiple-family-use/plan.md`
- **Status:** planning

### S-21: Entries require meaningful dates and listings hide type labels

- **Outcome:** Notes use their writing date, events their occurrence date, and tasks their due date. Dates are mandatory on supported creation/edit paths. Parent and child lists hide broad type labels.
- **Change ID:** entry-date-semantics
- **PRD refs:** Owner replacement decision 2026-10-06.
- **Prerequisites:** S-01, S-03, S-04, S-20; integrate current school-detail, classification, correction, and batch contracts.
- **Parallel with:** — (shares classification, validation, services, forms, and listing contracts).
- **Blockers:** Production rollout requires maintenance support that stops old web/conversion writers before backup and migrations.
- **Unknowns:**
  - Resolved 2026-10-06: keep note/event/task; no generic type. Dates are mandatory; backfill nulls from Europe/Warsaw created_at and enforce non-null storage. Preserve existing non-null dates; normalize historical types only from recognized saved school-kind metadata. Notes use writing dates; imported notes prefer source-writing dates then capture dates; events use occurrence dates and tasks deadlines. Type controls outside listings remain available.
- **Risk:** Date defaults must not invent an event schedule or task deadline. Retain school requirements and existing read/API compatibility while preserving existing non-null dates and unmapped types during backfill.
- **Plan:** `context/changes/entry-date-semantics/plan.md`
- **Status:** in-progress

## Backlog Handoff

| Roadmap ID | Change ID | Suggested issue title | Ready for `/10x-plan` | Notes |
| --- | --- | --- | --- | --- |
| S-01 | school-event-details | Parent can review the specific school event type and supply required date, person, and subject | planned | Plan written; owner decisions applied 2026-10-04. |
| S-02 | classification-short-names | Parent can assign an entry using a short family-member name | planned | Plan written; owner decisions applied 2026-10-04. |
| S-20 | title-keeps-action-only | Parent sees an entry title that keeps only the action after the person and date are extracted | planned | Plan written 2026-10-04. |
| S-03 | free-text-proposal-correction | Parent can correct an existing proposal through free text | planned | Plan written; owner decisions applied 2026-10-04. |
| S-04 | multi-entry-text-capture | Parent can review and save several entries from one instruction | planned | Plan written; owner decisions applied 2026-10-04. |
| S-05 | enter-text-submission | Parent can submit form text by pressing Enter | planned | Plan written; owner decisions applied 2026-10-04. |
| S-06 | mobile-classification-progress | Parent can see background classification activity and its result on a phone | planned | Plan written; owner decisions applied 2026-10-04. |
| S-07 | parent-note-assignment | Parent can reliably assign a new note to themselves or another parent in the family | planned | Plan written; owner decisions applied 2026-10-04. |
| S-08 | parent-list-child-grouping | Parent can browse family entries grouped by child | planned | Plan written; owner decisions applied 2026-10-04. |
| S-09 | remove-sign-up-option | User can sign in through the intended account flow without a sign-up option | planned | Plan written; owner decisions applied 2026-10-04. |
| S-17 | accessible-family-flows | Family member can use the agreed family flows under explicit accessibility criteria | planned | Plan written; owner decisions applied 2026-10-04. |
| S-14 | family-membership-management | Authorized family manager can manage family members in the application | planned | Plan written; owner decisions applied 2026-10-04. |
| S-15 | family-role-management | Authorized family manager can manage roles in the application | planned | Plan written; owner decisions applied 2026-10-04. |
| S-16 | multiple-family-use | Authorized member can use the application across multiple families | planned | Plan written; owner decisions applied 2026-10-04. |
| S-21 | entry-date-semantics | Require meaningful dates and hide types in listings | planned | Revised four-phase plan and brief saved 2026-10-06; no generic type; date backfill, metadata-based historical type normalization, and non-null schema authorized; review fixes agreed. |

## Open Roadmap Questions

1. **When is this milestone activated?** — Owner: user. Block: roadmap-wide. M-1 `first-family-capture-loop` is still open (S-04 `missing-info-follow-up` and S-05 `eduvulcan-school-event-intake` in progress); finish or explicitly abandon it, then adopt this tranche into `roadmap.md`.

Resolved 2026-10-04: PRD Questions 1–12, 17, 18 (accessibility part: WCAG 2.2 AA), 20, 21 (see slice Unknowns). Questions 13–16, 18, 19 are void — their slices were removed.

## Parked

- **Owner-removed 2026-10-04 (do not implement):** S-10 `parent-token-management` (PK-14), S-11 `read-only-family-kiosk` (PK-13), S-12 `external-source-entry-exchange` (PK-12), S-13 `direct-school-source-intake` (PK-15), S-18 `faster-classification-feedback` (PK-18), S-19 `zero-retention-classification` (PK-19), and the in-app member invitation flow from PK-16. Their draft plans were deleted.
- **Push notifications for the mobile PWA** — Why parked: owner decision 2026-10-04, future change after S-06.
- **Fixed school-subject vocabulary (enum)** — Why parked: owner decision 2026-10-04; S-01 ships free text first.
- **Playwright E2E tests for these slices** — Why parked: owner decision 2026-10-04; to be added later via `/10x-e2e-setup`.
- **Custom audio recording and speech-to-text conversion** — Why parked: explicitly excluded by the owner; keyboard dictation remains available.
- **Secondary storage, analytics, and training use of classification text** — Why parked: excluded by repository hard rules and the PRD Non-Goals.

## Milestone History

No milestone was opened or closed by this draft. Authoritative history remains in the active roadmap and must be carried forward on activation.

## Done
