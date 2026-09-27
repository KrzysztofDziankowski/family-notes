---
project: FamilyNotes
version: 2
status: draft
created: 2026-09-20
updated: 2026-09-27
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

The product provides one family space whose primary input is a single, easily accessible text field. A parent may type or use the phone keyboard's dictation capability without completing a multi-field form. The submitted text is classified as a todo, calendar event, or note, including its date and affected family member. Prioritization is not part of the problem. School information already reaches the parents as EduVulcan mobile notifications; the MVP lets a parent-owned automation forward those notifications so school events land in the family space without retyping. Other integrations may bring in data from external calendar, task, and other sources in the future.

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
- Automatic assignment to a family member may be inaccurate in the MVP, provided the parent can correct it before saving (manual capture) or after saving (automated school notifications).
- An automation token can only add school entries to its parent's family; it cannot read, change, or delete family data.

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

### US-02: Automation adds a school event from an EduVulcan notification

- **Given** a parent has an active automation token issued for their account
- **When** the parent's automation forwards the EduVulcan notification titled "Sprawdzian" with the message "2 października, Język angielski (j. angielski), Mateusz", captured on 2026-09-23
- **Then** the application saves a calendar entry for Mateusz titled "Sprawdzian: Język angielski", dated 2026-10-02, marked as coming from EduVulcan
- **And** when the same notification content is forwarded again, no second entry is created

#### Acceptance Criteria

- A request without a valid, unrevoked token is rejected and saves nothing.
- The entry is assigned to the child named in the notification.
- The year of "2 października" is inferred from the capture date as 2026.
- The entry is saved without parent confirmation and the parent can later correct or delete it.
- A repeated notification with the same content (even with a different notification id) does not create a duplicate entry.

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
- FR-005: A parent can review, correct, and confirm the proposed entry before it is saved. This applies to text the parent submits; automated school entries follow FR-010. Priority: must-have
  > Socrates: Counter-argument considered: mandatory confirmation weakens the promise of fast capture. Resolution: kept to let the parent correct uncertain classification before saving.

### Entries and views

- FR-006: A parent can create, read, update, and delete family entries and use a shared family view. Priority: must-have
  > Socrates: Counter-argument considered: full CRUD can distract from the product's classification capability. Resolution: kept as required entry lifecycle behavior.
- FR-007: A child can read only entries assigned to that child in a personal view. Priority: must-have
  > Socrates: Counter-arguments considered and rejected; the requirement stands as written.
- FR-008: A member of the single configured family can access only that family's data; people outside it cannot access the data. Priority: must-have
  > Socrates: Counter-argument considered: full multi-family support adds unnecessary scope. Resolution: revised; the MVP supports one configured family while preserving protection from outside access.

### Automated school intake

- FR-009: A parent can have automation tokens issued to and revoked from their account by the application administrator; a token's secret is shown only once, when issued. Priority: must-have
  > Socrates: Counter-argument considered: an in-app token management page for parents. Resolution: revised; tokens are managed only by the administrator, consistent with the MVP having no in-app administration.
- FR-010: A parent's automation can submit a captured EduVulcan notification using that parent's token, and the application saves it as a school entry for the parent's family without a confirmation step. Priority: must-have
  > Socrates: Counter-argument considered: mandatory confirmation (FR-005) should also cover automated entries. Resolution: revised; automated school entries are saved directly and corrected through FR-006, so the automation needs no human in the loop.
- FR-011: Repeated submissions of the same notification — the same notification id, or the same title, message, and child with a different id — do not create duplicate entries. Priority: must-have
  > Socrates: Counter-argument considered: leave duplicates for the parent to delete. Resolution: rejected; captured samples show identical notifications arriving several times within seconds.

## Non-Functional Requirements

- The MVP is usable in Chrome on Android.
- A parent receives either a classified proposal or a follow-up question within 30 seconds of submitting text.
- Data belonging to the configured family is not accessible to people outside that family.
- Text submitted for classification is not used for any purpose other than producing and saving the requested family entry. This includes notification text sent to classification when the school notification rules cannot interpret it.
- An automation token can be revoked, and a revoked token stops working immediately.

## Business Logic

The application classifies a parent's natural-language text as a todo, calendar event, or note and extracts the affected family member and date.

A homework, class test, test, or quiz entry is a calendar event and requires both an affected family member and a date. A substitution or room-change entry is a note and requires a date. Lucky-number, grade, and late-arrival entries are notes without additional required fields. A calendar entry requires a date, while its time is optional. If a required value is missing, the application asks a follow-up question before presenting the proposal for confirmation.

If no entry type or relevant detail can be recognized, the text is treated as a general note.

An EduVulcan notification carries a category title, a short message, a notification id, and a capture time. Known categories are interpreted by fixed school rules; only a notification the rules cannot interpret falls back to classification, and if that also fails it is saved as a general note. The category mapping is:

- "Sprawdzian", "Kartkówka", "Praca klasowa" (test, quiz, class test) and "Zadanie domowe" (homework) → calendar event for the named child on the stated date.
- "Zmiana planu dla <child>" (substitution, room change, teacher absence) → note for the named child on the stated date; one notification may describe more than one change.
- "Ocena" (grade), "Szczęśliwy numerek" (lucky number), "Frekwencja" (late arrival) → note for the named child.
- "Nowa wiadomość" (teacher message) → general family note without an assigned child, dated by the message date.

Dates in notifications omit the year; the year is inferred from the capture time. The child is identified by name as it appears in the notification, including Polish diacritics. Automated entries are marked with EduVulcan as their source.

## Access Control

Each member of the single preconfigured family signs in using their own external identity account. Parent and child roles are assigned before the MVP is used; the MVP has no interface for managing members or roles.

- Parent: can create, read, update, and delete all entries belonging to the family.
- Child: can read only entries assigned to that child and cannot create, update, or delete entries.
- Unauthenticated user: cannot access family data.
- Automation (holding a parent's token): can only add school entries from EduVulcan notifications to that parent's family; it cannot read, update, or delete entries, and it cannot use the signed-in application. Tokens are issued and revoked only by the application administrator.

## Non-Goals

- No custom audio recording or speech-to-text conversion in the MVP; users may type or use the phone keyboard's dictation capability.
- No integrations with external calendar, task, or other sources in the MVP, except intake of EduVulcan school notifications forwarded by a parent's automation; these are post-MVP extensions.
- No read-only kiosk view in the MVP, and no token access beyond adding automated school entries; this is a post-MVP extension.
- No in-app token management page for parents in the MVP; the administrator issues and revokes tokens.
- No reading EduVulcan directly; the product only receives notifications that the parent's own automation forwards.
- No in-app family or role management and no support for multiple families in the MVP; one five-person family is preconfigured.
- No accessibility target beyond default browser behavior in the MVP; explicit accessibility requirements are deferred.
- No response-time target below 30 seconds in the MVP; performance improvements are deferred.

## Open Questions

No open questions currently block the MVP.
