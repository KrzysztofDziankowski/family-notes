---
project: FamilyNotes
version: 1
status: draft
created: 2026-10-04
updated: 2026-10-04
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

- **Intent:** Improve family capture correctness and review, while exposing broader post-MVP proposals and their unresolved product decisions.
- **Source materials:** `context/foundation/prd-v2.md` (draft v2).
- **Done when:** after activation and scope confirmation, every included slice is done and the selected release success criteria are met.
- **Scope anchors:** PK-01–PK-10, PK-12–PK-19; US-01–US-10. Audio capture is excluded.
- **Activation boundary:** confirm scope, finish or explicitly abandon the current open milestone, then adopt the agreed tranche into the canonical roadmap. Do not open a second milestone through this file.
- **Framing:** quality and school-event details first are recommendations pending confirmation. Product decisions are the main blocker. Invest in classification correctness, existing-data compatibility, and review clarity; reuse application foundations.

## Vision recap

Parents have recorded improvements to name recognition, school-event details, text submission and correction, assignment, list organization, and mobile classification feedback. They also want one instruction to produce multiple entries. Broader post-MVP proposals remain blocked until their product scope and permissions are defined.

## North star

The north star is the smallest complete user flow that demonstrates the intended improvement. **S-01: Parent can review school event type and supply date, person, and subject** is the proposed first flow. Ordering among independent slices is a recommendation pending owner confirmation.

## At a glance

| ID | Change ID | Outcome (user can …) | Prerequisites | PRD refs | Status |
| --- | --- | --- | --- | --- | --- |
| S-01 | school-event-details | Parent can review the specific school event type and supply required date, person, and subject. | — | PK-08, PK-09, US-08, US-09 | blocked |
| S-02 | classification-short-names | Parent can assign an entry using a short family-member name. | — | PK-01, US-01 | blocked |
| S-03 | free-text-proposal-correction | Parent can correct an existing proposal through free text. | — | PK-10, US-10 | blocked |
| S-04 | multi-entry-text-capture | Parent can review and save several entries from one instruction. | — | PK-05, US-05 | blocked |
| S-05 | enter-text-submission | Parent can submit form text by pressing Enter. | — | PK-07, US-07 | blocked |
| S-06 | mobile-classification-progress | Parent can see background classification activity and its result on a phone. | — | PK-06, US-06 | blocked |
| S-07 | parent-note-assignment | Parent can reliably assign a new note to themselves or another parent in the family. | — | PK-03, US-03 | blocked |
| S-08 | parent-list-child-grouping | Parent can browse family entries grouped by child. | — | PK-04, US-04 | blocked |
| S-09 | remove-sign-up-option | User can sign in through the intended account flow without a sign-up option. | — | PK-02, US-02 | blocked |
| S-10 | parent-token-management | Parent can manage their automation tokens in the application. | — | PK-14 | blocked |
| S-11 | read-only-family-kiosk | Authorized viewer can read permitted family entries in a kiosk view. | — | PK-13 | blocked |
| S-12 | external-source-entry-exchange | Parent can exchange family entries with a selected external calendar, task tool, or source. | — | PK-12 | blocked |
| S-13 | direct-school-source-intake | Parent can receive school entries from direct school-source reading. | — | PK-15 | blocked |
| S-14 | family-membership-management | Authorized family manager can manage family members in the application. | — | PK-16 | blocked |
| S-15 | family-role-management | Authorized family manager can manage roles in the application. | S-14 | PK-16 | blocked |
| S-16 | multiple-family-use | Authorized member can use the application across multiple families. | S-14, S-15 | PK-16 | blocked |
| S-17 | accessible-family-flows | Family member can use the agreed family flows under explicit accessibility criteria. | — | PK-17 | blocked |
| S-18 | faster-classification-feedback | Parent can receive classification feedback within the agreed improved response target. | — | PK-18 | blocked |
| S-19 | zero-retention-classification | Parent can classify entries under an agreed zero-retention guarantee. | — | PK-19 | blocked |

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
- **Parallel with:** S-02, S-03, S-04, S-05, S-06, S-07, S-08, S-09, S-10, S-11, S-12, S-13, S-14, S-15, S-16, S-17, S-18, S-19
- **Blockers:** —
- **Unknowns:**
  - Confirm release scope, compatibility, and the selected first outcome (PRD Questions 1, 12, 20). — Owner: user. Block: yes.
  - PRD Question 9: **Is school event type editable as well as displayed, and where else should it be visible?** — Owner: user. Block: yes for PK-08 editing semantics.
  - PRD Question 10: **What school subject vocabulary is used, and how should existing school entries and automated notifications lacking subject satisfy the new required-subject rule?** — Owner: user. Block: yes for PK-09 compatibility.
- **Risk:** The four school types already exist; show them during review and require subject while preserving existing entries and automated intake.
- **Status:** blocked

### S-02: Parent can assign an entry using a short family-member name

- **Outcome:** Parent can assign an entry using a short family-member name.
- **Change ID:** classification-short-names
- **PRD refs:** PK-01, US-01
- **Prerequisites:** —
- **Parallel with:** S-01, S-03, S-04, S-05, S-06, S-07, S-08, S-09, S-10, S-11, S-12, S-13, S-14, S-15, S-16, S-17, S-18, S-19
- **Blockers:** —
- **Unknowns:**
  - Confirm release scope, compatibility, and the selected first outcome (PRD Questions 1, 12, 20). — Owner: user. Block: yes.
  - PRD Question 2: **Which short names are supported, who maintains their mappings, and what happens when no unique member matches?** — Owner: user. Block: yes for PK-01 beyond the recorded Hania/Hanna example and ambiguity rule.
- **Risk:** Family-scoped ambiguity must be resolved before assigning an entry.
- **Status:** blocked

### S-03: Parent can correct an existing proposal through free text

- **Outcome:** Parent can correct an existing proposal through free text.
- **Change ID:** free-text-proposal-correction
- **PRD refs:** PK-10, US-10
- **Prerequisites:** —
- **Parallel with:** S-01, S-02, S-04, S-05, S-06, S-07, S-08, S-09, S-10, S-11, S-12, S-13, S-14, S-15, S-16, S-17, S-18, S-19
- **Blockers:** —
- **Unknowns:**
  - Confirm release scope, compatibility, and the selected first outcome (PRD Questions 1, 12, 20). — Owner: user. Block: yes.
  - PRD Question 11: **Does free-text correction apply only before saving or also to saved entries, and how does it select a target in a multiple-proposal result?** — Owner: user. Block: yes for PK-10 expansion beyond a single draft proposal.
- **Risk:** Corrections must preserve unmentioned values and the selected proposal.
- **Status:** blocked

### S-04: Parent can review and save several entries from one instruction

- **Outcome:** Parent can review and save several entries from one instruction.
- **Change ID:** multi-entry-text-capture
- **PRD refs:** PK-05, US-05
- **Prerequisites:** —
- **Parallel with:** S-01, S-02, S-03, S-05, S-06, S-07, S-08, S-09, S-10, S-11, S-12, S-13, S-14, S-15, S-16, S-17, S-18, S-19
- **Blockers:** —
- **Unknowns:**
  - Confirm release scope, compatibility, and the selected first outcome (PRD Questions 1, 12, 20). — Owner: user. Block: yes.
  - PRD Question 6: **What timezone and relative-date rules apply to multi-entry instructions, and how are ambiguous dates resolved? Can proposals be confirmed separately, and what happens if only part of a batch saves?** — Owner: user. Block: yes for PK-05 beyond the explicit three-entry example.
- **Risk:** Ambiguous relative dates and partial saves require explicit behavior.
- **Status:** blocked

### S-05: Parent can submit form text by pressing Enter

- **Outcome:** Parent can submit form text by pressing Enter.
- **Change ID:** enter-text-submission
- **PRD refs:** PK-07, US-07
- **Prerequisites:** —
- **Parallel with:** S-01, S-02, S-03, S-04, S-06, S-07, S-08, S-09, S-10, S-11, S-12, S-13, S-14, S-15, S-16, S-17, S-18, S-19
- **Blockers:** —
- **Unknowns:**
  - Confirm release scope, compatibility, and the selected first outcome (PRD Questions 1, 12, 20). — Owner: user. Block: yes.
  - PRD Question 8: **Which text forms submit on Enter, and how should multiline input, keyboard composition, and a newline shortcut behave?** — Owner: user. Block: yes for PK-07 details.
- **Risk:** Submission must account for multiline input and keyboard composition.
- **Status:** blocked

### S-06: Parent can see background classification activity and its result on a phone

- **Outcome:** Parent can see background classification activity and its result on a phone.
- **Change ID:** mobile-classification-progress
- **PRD refs:** PK-06, US-06
- **Prerequisites:** —
- **Parallel with:** S-01, S-02, S-03, S-04, S-05, S-07, S-08, S-09, S-10, S-11, S-12, S-13, S-14, S-15, S-16, S-17, S-18, S-19
- **Blockers:** —
- **Unknowns:**
  - Confirm release scope, compatibility, and the selected first outcome (PRD Questions 1, 12, 20). — Owner: user. Block: yes.
  - PRD Question 7: **What mobile application experience is intended, and must classification continue or report status when the user navigates away, closes the application, or loses connectivity?** — Owner: user. Block: yes for PK-06.
- **Risk:** Background lifecycle expectations determine what progress can promise.
- **Status:** blocked

### S-07: Parent can reliably assign a new note to themselves or another parent in the family

- **Outcome:** Parent can reliably assign a new note to themselves or another parent in the family.
- **Change ID:** parent-note-assignment
- **PRD refs:** PK-03, US-03
- **Prerequisites:** —
- **Parallel with:** S-01, S-02, S-03, S-04, S-05, S-06, S-08, S-09, S-10, S-11, S-12, S-13, S-14, S-15, S-16, S-17, S-18, S-19
- **Blockers:** —
- **Unknowns:**
  - Confirm release scope, compatibility, and the selected first outcome (PRD Questions 1, 12, 20). — Owner: user. Block: yes.
  - PRD Question 4: **Should assigning notes to parents apply to both manual creation and classification, and do any other entry types gain the same assignment choices?** — Owner: user. Block: yes for PK-03 scope boundaries.
- **Risk:** The form already permits parent assignment; verify the complete flow and address only demonstrated gaps, preserving family isolation.
- **Status:** blocked

### S-08: Parent can browse family entries grouped by child

- **Outcome:** Parent can browse family entries grouped by child.
- **Change ID:** parent-list-child-grouping
- **PRD refs:** PK-04, US-04
- **Prerequisites:** —
- **Parallel with:** S-01, S-02, S-03, S-04, S-05, S-06, S-07, S-09, S-10, S-11, S-12, S-13, S-14, S-15, S-16, S-17, S-18, S-19
- **Blockers:** —
- **Unknowns:**
  - Confirm release scope, compatibility, and the selected first outcome (PRD Questions 1, 12, 20). — Owner: user. Block: yes.
  - PRD Question 5: **Where should parent-assigned and unassigned entries appear in a parent list grouped by child, and what ordering is expected?** — Owner: user. Block: yes for PK-04.
- **Risk:** Parent-assigned and unassigned entries must remain discoverable.
- **Status:** blocked

### S-09: User can sign in through the intended account flow without a sign-up option

- **Outcome:** User can sign in through the intended account flow without a sign-up option.
- **Change ID:** remove-sign-up-option
- **PRD refs:** PK-02, US-02
- **Prerequisites:** —
- **Parallel with:** S-01, S-02, S-03, S-04, S-05, S-06, S-07, S-08, S-10, S-11, S-12, S-13, S-14, S-15, S-16, S-17, S-18, S-19
- **Blockers:** —
- **Unknowns:**
  - Confirm release scope, compatibility, and the selected first outcome (PRD Questions 1, 12, 20). — Owner: user. Block: yes.
  - PRD Question 3: **Does removing sign-up remove only a visible option or also registration, and how are new family accounts provisioned through first sign-in?** — Owner: user. Block: yes for PK-02.
- **Risk:** Removing sign-up must not prevent intended family-account provisioning.
- **Status:** blocked

### S-10: Parent can manage their automation tokens in the application

- **Outcome:** Parent can manage their automation tokens in the application.
- **Change ID:** parent-token-management
- **PRD refs:** PK-14
- **Prerequisites:** —
- **Parallel with:** S-01, S-02, S-03, S-04, S-05, S-06, S-07, S-08, S-09, S-11, S-12, S-13, S-14, S-15, S-16, S-17, S-18, S-19
- **Blockers:** —
- **Unknowns:**
  - Confirm release scope, compatibility, and the selected first outcome (PRD Questions 1, 12, 20). — Owner: user. Block: yes.
  - PRD Question 15: **Which token-management actions may parents perform, and how are permitted token capabilities constrained?** — Owner: user. Block: yes for PK-14.
- **Risk:** Token management must preserve owner scoping and immediate revocation.
- **Status:** blocked

### S-11: Authorized viewer can read permitted family entries in a kiosk view

- **Outcome:** Authorized viewer can read permitted family entries in a kiosk view.
- **Change ID:** read-only-family-kiosk
- **PRD refs:** PK-13
- **Prerequisites:** —
- **Parallel with:** S-01, S-02, S-03, S-04, S-05, S-06, S-07, S-08, S-09, S-10, S-12, S-13, S-14, S-15, S-16, S-17, S-18, S-19
- **Blockers:** —
- **Unknowns:**
  - Confirm release scope, compatibility, and the selected first outcome (PRD Questions 1, 12, 20). — Owner: user. Block: yes.
  - PRD Question 14: **Who may use a kiosk, which family entries may it show, and how is access authorized and revoked?** — Owner: user. Block: yes for PK-13; existing family privacy remains binding.
- **Risk:** The viewer and authorization boundary must be defined before family data is displayed.
- **Status:** blocked

### S-12: Parent can exchange family entries with a selected external calendar, task tool, or source

- **Outcome:** Parent can exchange family entries with a selected external calendar, task tool, or source.
- **Change ID:** external-source-entry-exchange
- **PRD refs:** PK-12
- **Prerequisites:** —
- **Parallel with:** S-01, S-02, S-03, S-04, S-05, S-06, S-07, S-08, S-09, S-10, S-11, S-13, S-14, S-15, S-16, S-17, S-18, S-19
- **Blockers:** —
- **Unknowns:**
  - Confirm release scope, compatibility, and the selected first outcome (PRD Questions 1, 12, 20). — Owner: user. Block: yes.
  - PRD Question 13: **Which external calendars, task tools, and other sources are included, and what direction of exchange, ownership, and duplicate rules apply?** — Owner: user. Block: yes for PK-12.
- **Risk:** A concrete first source and exchange direction must be selected before planning.
- **Status:** blocked

### S-13: Parent can receive school entries from direct school-source reading

- **Outcome:** Parent can receive school entries from direct school-source reading.
- **Change ID:** direct-school-source-intake
- **PRD refs:** PK-15
- **Prerequisites:** —
- **Parallel with:** S-01, S-02, S-03, S-04, S-05, S-06, S-07, S-08, S-09, S-10, S-11, S-12, S-14, S-15, S-16, S-17, S-18, S-19
- **Blockers:** —
- **Unknowns:**
  - Confirm release scope, compatibility, and the selected first outcome (PRD Questions 1, 12, 20). — Owner: user. Block: yes.
  - PRD Question 16: **Which information should direct school-source reading retrieve, how is access authorized, and how does it coexist with forwarded notifications?** — Owner: user. Block: yes for PK-15.
- **Risk:** Direct intake must coexist with forwarded notifications without unintended duplicates.
- **Status:** blocked

### S-14: Authorized family manager can manage family members in the application

- **Outcome:** Authorized family manager can manage family members in the application.
- **Change ID:** family-membership-management
- **PRD refs:** PK-16
- **Prerequisites:** —
- **Parallel with:** S-01, S-02, S-03, S-04, S-05, S-06, S-07, S-08, S-09, S-10, S-11, S-12, S-13, S-17, S-18, S-19
- **Blockers:** —
- **Unknowns:**
  - Confirm release scope, compatibility, and the selected first outcome (PRD Questions 1, 12, 20). — Owner: user. Block: yes.
  - PRD Question 17: **Who can create families, manage members and roles, join multiple families, and switch family context?** — Owner: user. Block: yes for PK-16.
- **Risk:** Membership authority must be established before adding administration.
- **Status:** blocked

### S-15: Authorized family manager can manage roles in the application

- **Outcome:** Authorized family manager can manage roles in the application.
- **Change ID:** family-role-management
- **PRD refs:** PK-16
- **Prerequisites:** S-14
- **Parallel with:** S-01, S-02, S-03, S-04, S-05, S-06, S-07, S-08, S-09, S-10, S-11, S-12, S-13, S-17, S-18, S-19
- **Blockers:** —
- **Unknowns:**
  - Confirm release scope, compatibility, and the selected first outcome (PRD Questions 1, 12, 20). — Owner: user. Block: yes.
  - PRD Question 17: **Who can create families, manage members and roles, join multiple families, and switch family context?** — Owner: user. Block: yes for PK-16.
- **Risk:** Role changes must not permit unauthorized privilege escalation.
- **Status:** blocked

### S-16: Authorized member can use the application across multiple families

- **Outcome:** Authorized member can use the application across multiple families.
- **Change ID:** multiple-family-use
- **PRD refs:** PK-16
- **Prerequisites:** S-14, S-15
- **Parallel with:** S-01, S-02, S-03, S-04, S-05, S-06, S-07, S-08, S-09, S-10, S-11, S-12, S-13, S-17, S-18, S-19
- **Blockers:** —
- **Unknowns:**
  - Confirm release scope, compatibility, and the selected first outcome (PRD Questions 1, 12, 20). — Owner: user. Block: yes.
  - PRD Question 17: **Who can create families, manage members and roles, join multiple families, and switch family context?** — Owner: user. Block: yes for PK-16.
- **Risk:** Every view and mutation must use the authorized family context.
- **Status:** blocked

### S-17: Family member can use the agreed family flows under explicit accessibility criteria

- **Outcome:** Family member can use the agreed family flows under explicit accessibility criteria.
- **Change ID:** accessible-family-flows
- **PRD refs:** PK-17
- **Prerequisites:** —
- **Parallel with:** S-01, S-02, S-03, S-04, S-05, S-06, S-07, S-08, S-09, S-10, S-11, S-12, S-13, S-14, S-15, S-16, S-18, S-19
- **Blockers:** —
- **Unknowns:**
  - Confirm release scope, compatibility, and the selected first outcome (PRD Questions 1, 12, 20). — Owner: user. Block: yes.
  - PRD Question 18: **Which explicit accessibility criteria and response-time target below 30 seconds are required, and which interactions must meet them?** — Owner: user. Block: yes for PK-17 and PK-18.
- **Risk:** Named criteria and covered flows are needed to verify improvement.
- **Status:** blocked

### S-18: Parent can receive classification feedback within the agreed improved response target

- **Outcome:** Parent can receive classification feedback within the agreed improved response target.
- **Change ID:** faster-classification-feedback
- **PRD refs:** PK-18
- **Prerequisites:** —
- **Parallel with:** S-01, S-02, S-03, S-04, S-05, S-06, S-07, S-08, S-09, S-10, S-11, S-12, S-13, S-14, S-15, S-16, S-17, S-19
- **Blockers:** —
- **Unknowns:**
  - Confirm release scope, compatibility, and the selected first outcome (PRD Questions 1, 12, 20). — Owner: user. Block: yes.
  - PRD Question 18: **Which explicit accessibility criteria and response-time target below 30 seconds are required, and which interactions must meet them?** — Owner: user. Block: yes for PK-17 and PK-18.
- **Risk:** The improved target must specify the measured interaction and conditions.
- **Status:** blocked

### S-19: Parent can classify entries under an agreed zero-retention guarantee

- **Outcome:** Parent can classify entries under an agreed zero-retention guarantee.
- **Change ID:** zero-retention-classification
- **PRD refs:** PK-19
- **Prerequisites:** —
- **Parallel with:** S-01, S-02, S-03, S-04, S-05, S-06, S-07, S-08, S-09, S-10, S-11, S-12, S-13, S-14, S-15, S-16, S-17, S-18
- **Blockers:** —
- **Unknowns:**
  - Confirm release scope, compatibility, and the selected first outcome (PRD Questions 1, 12, 20). — Owner: user. Block: yes.
  - PRD Question 19: **What zero-retention guarantee is required, and what should happen if it is unavailable?** — Owner: user/operator. Block: yes for PK-19. Original technical input, retained verbatim for downstream routing:
- **Risk:** Unavailability of the retention guarantee must have an explicit product outcome.
- **Status:** blocked

## Backlog Handoff

| Roadmap ID | Change ID | Suggested issue title | Ready for `/10x-plan` | Notes |
| --- | --- | --- | --- | --- |
| S-01 | school-event-details | Parent can review the specific school event type and supply required date, person, and subject | no | Resolve listed questions and activate agreed scope first. |
| S-02 | classification-short-names | Parent can assign an entry using a short family-member name | no | Resolve listed questions and activate agreed scope first. |
| S-03 | free-text-proposal-correction | Parent can correct an existing proposal through free text | no | Resolve listed questions and activate agreed scope first. |
| S-04 | multi-entry-text-capture | Parent can review and save several entries from one instruction | no | Resolve listed questions and activate agreed scope first. |
| S-05 | enter-text-submission | Parent can submit form text by pressing Enter | no | Resolve listed questions and activate agreed scope first. |
| S-06 | mobile-classification-progress | Parent can see background classification activity and its result on a phone | no | Resolve listed questions and activate agreed scope first. |
| S-07 | parent-note-assignment | Parent can reliably assign a new note to themselves or another parent in the family | no | Resolve listed questions and activate agreed scope first. |
| S-08 | parent-list-child-grouping | Parent can browse family entries grouped by child | no | Resolve listed questions and activate agreed scope first. |
| S-09 | remove-sign-up-option | User can sign in through the intended account flow without a sign-up option | no | Resolve listed questions and activate agreed scope first. |
| S-10 | parent-token-management | Parent can manage their automation tokens in the application | no | Resolve listed questions and activate agreed scope first. |
| S-11 | read-only-family-kiosk | Authorized viewer can read permitted family entries in a kiosk view | no | Resolve listed questions and activate agreed scope first. |
| S-12 | external-source-entry-exchange | Parent can exchange family entries with a selected external calendar, task tool, or source | no | Resolve listed questions and activate agreed scope first. |
| S-13 | direct-school-source-intake | Parent can receive school entries from direct school-source reading | no | Resolve listed questions and activate agreed scope first. |
| S-14 | family-membership-management | Authorized family manager can manage family members in the application | no | Resolve listed questions and activate agreed scope first. |
| S-15 | family-role-management | Authorized family manager can manage roles in the application | no | Resolve listed questions and activate agreed scope first. |
| S-16 | multiple-family-use | Authorized member can use the application across multiple families | no | Resolve listed questions and activate agreed scope first. |
| S-17 | accessible-family-flows | Family member can use the agreed family flows under explicit accessibility criteria | no | Resolve listed questions and activate agreed scope first. |
| S-18 | faster-classification-feedback | Parent can receive classification feedback within the agreed improved response target | no | Resolve listed questions and activate agreed scope first. |
| S-19 | zero-retention-classification | Parent can classify entries under an agreed zero-retention guarantee | no | Resolve listed questions and activate agreed scope first. |

## Open Roadmap Questions

1. **What delivery budget, deadline, priorities, release success criteria, and non-goals apply to this collection?** — Owner: user. Block: yes for committing delivery scope. The previous three-week MVP budget is not assumed to cover these additions.
2. **Which short names are supported, who maintains their mappings, and what happens when no unique member matches?** — Owner: user. Block: yes for PK-01 beyond the recorded Hania/Hanna example and ambiguity rule.
3. **Does removing sign-up remove only a visible option or also registration, and how are new family accounts provisioned through first sign-in?** — Owner: user. Block: yes for PK-02.
4. **Should assigning notes to parents apply to both manual creation and classification, and do any other entry types gain the same assignment choices?** — Owner: user. Block: yes for PK-03 scope boundaries.
5. **Where should parent-assigned and unassigned entries appear in a parent list grouped by child, and what ordering is expected?** — Owner: user. Block: yes for PK-04.
6. **What timezone and relative-date rules apply to multi-entry instructions, and how are ambiguous dates resolved? Can proposals be confirmed separately, and what happens if only part of a batch saves?** — Owner: user. Block: yes for PK-05 beyond the explicit three-entry example.
7. **What mobile application experience is intended, and must classification continue or report status when the user navigates away, closes the application, or loses connectivity?** — Owner: user. Block: yes for PK-06.
8. **Which text forms submit on Enter, and how should multiline input, keyboard composition, and a newline shortcut behave?** — Owner: user. Block: yes for PK-07 details.
9. **Is school event type editable as well as displayed, and where else should it be visible?** — Owner: user. Block: yes for PK-08 editing semantics.
10. **What school subject vocabulary is used, and how should existing school entries and automated notifications lacking subject satisfy the new required-subject rule?** — Owner: user. Block: yes for PK-09 compatibility.
11. **Does free-text correction apply only before saving or also to saved entries, and how does it select a target in a multiple-proposal result?** — Owner: user. Block: yes for PK-10 expansion beyond a single draft proposal.
12. **What compatibility and rollout requirements apply to existing records and consumers when these changes are introduced?** — Owner: user. Block: yes before implementation planning.
13. **Which external calendars, task tools, and other sources are included, and what direction of exchange, ownership, and duplicate rules apply?** — Owner: user. Block: yes for PK-12.
14. **Who may use a kiosk, which family entries may it show, and how is access authorized and revoked?** — Owner: user. Block: yes for PK-13; existing family privacy remains binding.
15. **Which token-management actions may parents perform, and how are permitted token capabilities constrained?** — Owner: user. Block: yes for PK-14.
16. **Which information should direct school-source reading retrieve, how is access authorized, and how does it coexist with forwarded notifications?** — Owner: user. Block: yes for PK-15.
17. **Who can create families, manage members and roles, join multiple families, and switch family context?** — Owner: user. Block: yes for PK-16.
18. **Which explicit accessibility criteria and response-time target below 30 seconds are required, and which interactions must meet them?** — Owner: user. Block: yes for PK-17 and PK-18.
19. **What zero-retention guarantee is required, and what should happen if it is unavailable?** — Owner: user/operator. Block: yes for PK-19. Original technical input, retained verbatim for downstream routing:

> **OpenAI Zero Data Retention (ZDR) for classification** - Why parked: owner decision 2026-09-27; the MVP ships classification with `store=False` and sanitized logs only, accepting OpenAI abuse-monitoring retention. Revisit after the MVP: obtain ZDR approval for the production OpenAI project and reintroduce a fail-closed attestation gate (removed from F-02 `classification-privacy-boundary`).

20. **What is the current cost of the recorded workarounds, and which outcome should be delivered first?** — Owner: user. Block: yes for milestone selection; no impact on recording this draft.

21. **When should this future draft be activated, and which tranche belongs in the next milestone?** — Owner: user. Block: roadmap-wide. The current milestone remains open.

## Parked

- **Custom audio recording and speech-to-text conversion** — Why parked: explicitly excluded by the owner; keyboard dictation remains available.
- **Secondary storage, analytics, and training use of classification text** — Why parked: excluded by repository hard rules and the PRD Non-Goals.

## Milestone History

No milestone was opened or closed by this draft. Authoritative history remains in the active roadmap and must be carried forward on activation.

## Done
