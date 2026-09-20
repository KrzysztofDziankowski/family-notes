---
project: FamilyNotes
version: 1
status: draft
created: 2026-09-20
context_type: greenfield
product_type: web-app
target_scale:
  users: small
  qps: low
  data_volume: small
timeline_budget:
  mvp_weeks: 3
  hard_deadline: 2026-11-04
  after_hours_only: true
---

## Vision & Problem Statement

Family tasks, events, and notes are scattered across a physical notebook and calendar, external calendar and task tools, and information kept in memory. Both parents have to check multiple places, while adding information to existing tools requires too many actions.

The product provides one family space whose primary input is a single, easily accessible text field. A parent may type or use the phone keyboard's dictation capability without completing a multi-field form. The submitted text is classified as a todo, calendar event, or note, including its date and affected family member. Prioritization is not part of the problem. Future integrations may bring in data from external calendar, task, and other sources.

## User & Persona

### Primary persona

Both parents equally organize family information. They reach for the product when a new task, event, or note appears and they need to capture it quickly through a short natural-language instruction.

### Secondary persona

Children read family information relevant to them but do not create, edit, or delete it.

## Success Criteria

### Primary

- A parent can enter a natural-language instruction, review its classification, correct it if needed, and save an entry that is visible to the assigned family member.

### Secondary

- Classification should complete as quickly as possible within the MVP limit of 30 seconds.

### Guardrails

- Family data must not be accessible to anyone outside that family.
- Automatic assignment to a family member may be inaccurate in the MVP, provided the parent can correct it before saving.

## User Stories

### US-01: Parent adds a child's school event from natural language

- **Given** a parent has the application open on their phone
- **When** the parent enters "Michal has a biology test on Monday about the skin"
- **Then** the application proposes an entry for Michal titled "Biology test about the skin", dated Monday, 2026-09-21
- **And** after the parent confirms it, the application displays the same information with confirmation that the entry was added

#### Acceptance Criteria

- The preview identifies Michal as the assigned family member.
- The preview interprets "Monday" as 2026-09-21 for an instruction entered on 2026-09-19.
- The preview includes the entry title.
- The parent can confirm the proposed entry.
- After confirmation, the application shows that the entry was added.

## Functional Requirements

### Accounts and family

- FR-001: A family member can sign in with an external identity account. Priority: must-have
  > Socrates: Counter-argument considered: authentication increases the MVP scope. Resolution: kept because user identification is required for privacy.
- FR-002: A family member can use a preassigned parent or child role in the single configured family. Priority: must-have
  > Socrates: Counter-argument considered: building family and role administration expands the MVP. Resolution: revised; the family and roles are preconfigured, and in-app administration is deferred.

### Entry capture and classification

- FR-003: A parent can submit a natural-language instruction through a single text field. Priority: must-have
  > Socrates: Counter-arguments considered and rejected; the requirement stands as written.
- FR-004: A parent can receive a proposed entry classified by type, date, content, and affected family member. Priority: must-have
  > Socrates: Counter-argument considered: classifying tags adds scope without being necessary for the primary flow. Resolution: revised; automatic tags are removed from the MVP.
- FR-005: A parent can review, correct, and confirm the proposed entry before it is saved. Priority: must-have
  > Socrates: Counter-argument considered: mandatory confirmation weakens the promise of fast capture. Resolution: kept to let the parent correct uncertain classification before saving.

### Entries and views

- FR-006: A parent can create, read, update, and delete family entries and use a shared family view. Priority: must-have
  > Socrates: Counter-argument considered: full CRUD can distract from the product's classification capability. Resolution: kept as required entry lifecycle behavior.
- FR-007: A child can read only entries assigned to that child in a personal view. Priority: must-have
  > Socrates: Counter-arguments considered and rejected; the requirement stands as written.
- FR-008: A member of the single configured family can access only that family's data; people outside it cannot access the data. Priority: must-have
  > Socrates: Counter-argument considered: full multi-family support adds unnecessary scope. Resolution: revised; the MVP supports one configured family while preserving protection from outside access.

## Non-Functional Requirements

- The MVP is usable in Chrome on Android.
- A parent receives either a classified proposal or a follow-up question within 30 seconds of submitting text.
- Data belonging to the configured family is not accessible to people outside that family.
- Text submitted for classification is not used for any purpose other than producing and saving the requested family entry.

## Business Logic

The application classifies a parent's natural-language text as a todo, calendar event, or note and extracts the affected family member and date.

A test or homework entry requires both an affected family member and a date. A calendar entry requires a date, while its time is optional. If a required value is missing, the application asks a follow-up question before presenting the proposal for confirmation.

If no entry type or relevant detail can be recognized, the text is treated as a general note. The rules for other classification cases remain to be defined.

## Access Control

Each member of the single preconfigured family signs in using their own external identity account. Parent and child roles are assigned before the MVP is used; the MVP has no interface for managing members or roles.

- Parent: can create, read, update, and delete all entries belonging to the family.
- Child: can read only entries assigned to that child and cannot create, update, or delete entries.
- Unauthenticated user: cannot access family data.

## Non-Goals

- No custom audio recording or speech-to-text conversion in the MVP; users may type or use the phone keyboard's dictation capability.
- No integrations with external calendar, task, or other sources in the MVP; these are post-MVP extensions.
- No read-only kiosk view or token authentication in the MVP; this is a post-MVP extension.
- No in-app family or role management and no support for multiple families in the MVP; one five-person family is preconfigured.
- No accessibility target beyond default browser behavior in the MVP; explicit accessibility requirements are deferred.
- No response-time target below 30 seconds in the MVP; performance improvements are deferred.

## Open Questions

1. **What validation and follow-up rules apply to classification cases other than tests, homework, and calendar entries?** — Owner: user. Resolution date: later product iteration; not blocking the defined MVP cases.
