---
project: FamilyNotes
version: 2
status: draft
created: 2026-10-04
context_type: brownfield
product_type: web-app
target_scale:
  users: small
  qps: low
  data_volume: small
timeline_budget: null # TODO: delivery budget — see Open Questions
---

# FamilyNotes: Parked Features PRD

Source: 18 proposed items from `context/foundation/roadmap.md`, section `Parked`, read on 2026-10-04. Supporting baseline: `context/foundation/prd.md` (internal version 2) and the roadmap's completed slices, including MS-01. This separate draft does not supersede the active MVP PRD or change the current milestone. Scope IDs below are local to this draft.

## Current System Overview

FamilyNotes is a family information application for parents and children in one preconfigured five-person family. It is a Django 5.2 monolith using Python, Django templates, external identity sign-in, and SQLite locally or PostgreSQL for deployment.

Completed roadmap slices cover family identity and access, single school-event capture, parent entry management, child assigned-entry views, and parent-owned automation reads. The roadmap still marks missing-information follow-up and forwarded school-notification conversion as in progress. The baseline PRD describes notification intake without confirmation, deduplication, and correction after saving; these remain compatibility requirements, rather than an assertion that every pending slice is complete.

Manual capture classifies text as a todo, calendar event, or note and extracts date and family member. Parents review and confirm proposals. Parents manage family entries; children read only their assigned entries. The completed MS-01 extension permits family-scoped entry reads by parent-owned automation, beyond the older PRD's intake-only token description.

## Problem Statement & Motivation

Parents have recorded improvements to name recognition, school-event details, text submission and correction, assignment, list organization, and mobile classification feedback. They also want one instruction to produce multiple entries, and an entry title that keeps only the action once the person and date have been extracted from it. These requests were captured on 2026-10-03 and 2026-10-04.

The remaining included parked items describe post-MVP opportunities previously excluded: additional external sources, kiosk viewing, parent token management, direct school-source reading, family administration, accessibility, faster responses, and stronger classification retention protection. Their presence in this draft records the requested future scope; it does not establish a single delivery commitment. Audio capture is excluded at the owner's request.

The recorded workarounds are keyboard dictation for audio, forwarded school notifications instead of direct reading, administrator-issued tokens, and a preconfigured family. The current classification flow displays a loading page.

# TODO: Quantify the cost of current workarounds and select the first delivery outcome — see Open Questions.

## User & Persona

### Primary persona

Both parents equally organize family information and use short natural-language instructions to capture tasks, events, and notes. The requested changes affect their existing capture and management experience, including use on a phone.

### Secondary persona

Children read entries assigned to them and do not create, edit, or delete entries. Kiosk audiences and users of additional families have not been defined.

## Success Criteria

### Primary

The baseline outcome remains: a parent can enter a natural-language instruction, review its classification, correct it if needed, and save an entry visible to the assigned family member.

The recorded multi-entry example must produce three proposed meetings: today, tomorrow, and Monday of next week, all at 18:00, for review before saving. The recorded short-name example must resolve Hania to the corresponding family member Hanna. The recorded title example "kasia zrobić pranie w piątek" must produce the title "zrobić pranie", the date of the coming Friday, and the assigned member Kasia.

# TODO: Confirm release-level success criteria for all 18 included items — see Open Questions.

### Secondary

The existing target is classification or a follow-up question within 30 seconds. A lower response-time target is requested but no replacement target is specified.

# TODO: Specify the improved response-time and accessibility targets — see Open Questions.

### Guardrails

- Family data remains inaccessible to people outside the authorized family.
- Children retain read-only access to their assigned entries.
- Parents can correct assignments before saving manual entries and after saving automated entries.
- Classification input is used only for producing and saving the requested family entries; no secondary storage, analytics, or training use is added.
- Existing parent-owned automation reads remain family-scoped and read-only; existing intake behavior and immediate token revocation remain protected.

## User Stories

The following stories reformat explicit parked requests without introducing additional behavior. Broader items lacking a concrete scenario remain in Scope of Change and Open Questions.

### US-01: Recognize a short name

- **Given** a parent supplies a family-member name during classification
- **When** the parent uses "Hania" for a member named "Hanna"
- **Then** the proposal matches that family member; an ambiguous match prompts clarification

Previous behavior / delta: Short names become explicitly supported.

### US-02: Remove sign-up

- **Given** a user reaches the application authentication experience
- **When** the user looks for a sign-up option
- **Then** the option to sign up is removed

Previous behavior / delta: The parked request calls for removal; replacement account provisioning is unresolved.

### US-03: Assign notes to parents

- **Given** a parent creates a new note
- **When** the parent assigns it to themselves or another parent in the same family
- **Then** the note can be assigned to that parent, as well as to a child

Previous behavior / delta: The requested assignment choices include parents.

### US-04: Group the parent list by child

- **Given** a parent views the family entry list
- **When** entries are assigned to different children
- **Then** the list groups entries by their assigned child

Previous behavior / delta: The requested parent list gains child grouping.

### US-05: Create three meetings from one instruction

- **Given** a parent submits one text instruction
- **When** the parent enters "Add meeting with X today, tomorrow and next week on Monday at 18:00"
- **Then** three meeting proposals share the time 18:00 and use the three requested dates; all are shown for confirmation before saving

Previous behavior / delta: Manual classification expands beyond a single proposal.

### US-06: See mobile classification activity

- **Given** a parent uses the application on a phone
- **When** classification runs in the background
- **Then** visible progress or activity indicates it is still running, followed by completion or failure feedback

Previous behavior / delta: The recorded current experience shows a loading page.

### US-07: Submit text with Enter

- **Given** a parent enters text in the form
- **When** the parent presses Enter
- **Then** the form submits the text

Previous behavior / delta: Enter submission becomes an explicit requirement.

### US-08: Review school event type

- **Given** a parent reviews or edits a school entry
- **When** the entry is a kartkówka, sprawdzian, praca klasowa, or zadanie domowe
- **Then** the specific school event type is displayed in the form

Previous behavior / delta: The specific school category becomes explicit in the form.

### US-09: Supply required school information

- **Given** a parent submits a school event for classification
- **When** it is a kartkówka, sprawdzian, praca klasowa, or zadanie domowe
- **Then** the proposal has a date, assigned family member, and school subject; missing required values prompt a question before confirmation

Previous behavior / delta: The baseline date/person requirement gains required subject and distinct school types.

### US-10: Correct a complete proposal with text

- **Given** a parent has received a classified proposal, including a complete general note
- **When** the parent enters "zmień datę na 15 października" or another field correction
- **Then** the existing proposal is updated, unmentioned fields are preserved, and the revised proposal is shown for confirmation

Previous behavior / delta: Free-text correction extends beyond missing-information follow-up and structured fields.

### US-11: Keep only the action in the entry title

- **Given** a parent submits an instruction that names the person and the date
- **When** the parent enters "kasia zrobić pranie w piątek"
- **Then** the proposal's title is "zrobić pranie", its date is the coming Friday, and it is assigned to Kasia; the extracted person and date are not repeated in the title

Previous behavior / delta: The entry title no longer repeats the person and date that classification already extracted into their own fields.

## Scope of Change

All parked items except audio capture are included below in original order and wording. Inclusion is proposed future scope, not an assigned priority or an implementation approval. Original parking rationales are retained for traceability.

- [modified] PK-01: **Recognize short names during classification** - Resolve short names and diminutives to the corresponding family member; for example, "Hania" should match a family member named "Hanna". If a name could match more than one member in the current family, ask for clarification before assigning the entry. Why parked: owner-requested future improvement, recorded 2026-10-04; pending implementation planning for family-scoped name matching.
- [removed] PK-02: **Remove the sign-up option** - Remove the option for users to sign up. Why parked: owner-requested change, recorded 2026-10-04; pending implementation planning.
- [modified] PK-03: **Assign new notes to parents as well as children** - Allow a parent to create a note assigned to any parent in the same family, including themselves, as well as to a child. A self-reference in the instruction ("dla mnie", "mi", "ja") assigns the entry to the requesting parent (owner decision 2026-10-04). Why parked: owner-requested future feature, recorded 2026-10-04; pending implementation planning.
- [modified] PK-04: **Group entries by child in the parent view** - Group the parent's family entry list by the child each entry is assigned to. Why parked: owner-requested future feature, recorded 2026-10-04; pending implementation planning.
- [modified] PK-05: **Create multiple entries from one text instruction** - Allow a parent to request several entries at once. For example, "Add meeting with X today, tomorrow and next week on Monday at 18:00" should produce three meeting entries, one for each requested date, with the shared time of 18:00. Present all proposed entries for review and confirmation before saving. Why parked: owner-requested future feature, recorded 2026-10-03; extends the current single-entry classification flow and requires planning for multiple proposals and relative-date interpretation.
- [modified] PK-06: **Show background classification progress on mobile** - The current classification flow shows a loading page. When used as an application on a phone, show a visible progress or activity indicator that makes clear classification is still running in the background, then surface completion or failure. Why parked: owner-requested future feature, recorded 2026-10-03; pending definition of the mobile application experience and implementation planning.
- [modified] PK-07: **Submit form text with Enter** - Pressing Enter in the text input submits the form. Why parked: owner-requested future feature, recorded 2026-10-03; pending implementation planning.
- [modified] PK-08: **Show school event type in the entry form** - Display the specific school event type (kartkówka, sprawdzian, praca klasowa, zadanie domowe) when reviewing or editing an entry. Why parked: owner-requested future feature, recorded 2026-10-03; pending promotion into product requirements and a planned change.
- [modified] PK-09: **Classify school event type and require date, person, and subject** - Recognize kartkówka, sprawdzian, praca klasowa, and zadanie domowe as distinct school event types; each must have a date, an assigned family member, and an assigned school subject. Ask for any missing required value before confirmation. Why parked: owner-requested future feature, recorded 2026-10-03; extends the PRD's existing date/person requirement with a required subject and explicit school event type.
- [modified] PK-10: **Correct a classified proposal using free text** - After the first classification presents a proposal, allow the parent to change its date or any other entry field through free text (for example, "zmień datę na 15 października"). Update the existing proposal, preserve fields not mentioned in the correction, and show the revised proposal for confirmation. This also applies when the initial proposal is a complete general note. Why parked: owner-requested future feature, recorded 2026-10-03; extends correction beyond structured fields and follow-up for missing information.
- [modified] PK-20: **Keep only the action in the classified entry title** - When classification extracts the assigned family member and the date from an instruction, the proposed title keeps only the action in the parent's words, without the name and date phrases. For example, "kasia zrobić pranie w piątek" produces the title "zrobić pranie", the date of the coming Friday, and the assigned member Kasia. Why added: owner-requested improvement, recorded 2026-10-04.
- [new] PK-12: **External calendar, task, and source integrations (other than forwarded EduVulcan notifications)** - Why parked: PRD Non-Goals; post-MVP extension. EduVulcan intake moved into scope in PRD v2 (S-05).
- [new] PK-13: **Read-only kiosk view** - Why parked: PRD Non-Goals; post-MVP extension. Owner-directed scope anchor MS-01 moves family-entry REST reads by a parent-owned token into S-06, but does not add a kiosk UI or anonymous access.
- [new] PK-14: **In-app token management page for parents** - Why parked: PRD v2 Non-Goals; tokens are issued and revoked by the administrator.
- [new] PK-15: **Reading EduVulcan directly (API/scraping)** - Why parked: PRD v2 Non-Goals; the product only receives notifications the parent's automation forwards.
- [new] PK-16: **In-app family or role management and multiple-family support** - Why parked: PRD Non-Goals; the MVP uses one preconfigured five-person family.
- [modified] PK-17: **Explicit accessibility targets beyond default browser behavior** - Why parked: PRD Non-Goals; deferred requirement.
- [modified] PK-18: **Response-time target below 30 seconds** - Why parked: PRD Non-Goals; performance improvements are deferred beyond the MVP threshold.
- [modified] PK-19: **Zero retention of classification text** — Classification text should have zero retention by the classification provider; revisit the previously accepted retention policy after the MVP. The original technical note is quoted in Open Question 19 for downstream routing.

- [preserved] Parent family-entry management, assigned-child visibility, family isolation, and classification-purpose limits remain baseline requirements.
- [preserved] Forwarded school-notification intake and parent-owned family-entry automation reads remain supported.

# TODO: Assign priorities and split these proposals into delivery scope — see Open Questions.

## Constraints & Compatibility

The baseline product is a small web application usable in Chrome on Android. This draft does not yet settle whether the mobile experience changes product type. Existing entry data, family assignments, external identity sign-in, and automation access must remain usable.

Requiring a school subject introduces a compatibility question for previously saved entries and for forwarded school notifications that omit it. The new interactive confirmation rule must be reconciled with existing automated intake without confirmation.

The single configured family remains the baseline until the multiple-family access and administration rules are specified. Removing sign-up must be reconciled with the existing first-sign-in process used to configure family members.

# TODO: Define compatibility requirements for existing records, automation consumers, account provisioning, and rollout or rollback of changed behavior — see Open Questions.

## Business Logic Changes

The application classifies a parent's natural-language text as a todo, calendar event, or note and extracts the affected family member and date.

The existing school rule requires date and family member for homework, class tests, tests, and quizzes. The requested change recognizes kartkówka, sprawdzian, praca klasowa, and zadanie domowe as distinct school types, also requires a school subject, and asks for missing required values before confirmation.

Short names and diminutives resolve within the current family; Hania matches Hanna, and ambiguous matches require clarification before assignment. A note may be assigned to a parent in the same family, including its author, or to a child.

A single instruction may produce multiple proposals. The supplied example produces three meetings at 18:00, one for each requested date, reviewed before saving. Free-text corrections update the existing proposal and preserve fields not mentioned, including when the initial proposal is a complete general note. When the person and date are extracted into their own fields, the title keeps only the action and does not repeat them.

Rules for relative-date ambiguity, partial batch confirmation, general alias coverage, and newly introduced external-source behavior are unresolved.

## Access Control Changes

Removing the sign-up option is requested. The existing external identity sign-in and family provisioning relationship needs clarification before this removal is planned.

Parents continue to manage entries within their own family; assigning a note to another parent does not grant cross-family access. Children retain read-only access to their own assigned entries. Unauthenticated users may not access family data.

Kiosk access, parent-facing token management, family/role management, and multiple-family support introduce permission questions not answered by their parked titles. They do not implicitly authorize anonymous viewing, cross-family reads, or administrative privileges for children. Existing administrator privileges and parent-owned automation boundaries remain the baseline until explicit replacement rules are agreed.

## Non-Goals

- Custom audio recording and speech-to-text conversion are excluded at the owner's request on 2026-10-04; keyboard dictation remains available.
- This document does not implement the parked items, change current milestone status, or mark existing work complete.
- Existing MVP requirements are retained as the baseline; this draft covers proposed additions and modifications.
- Secondary storage, analytics, and training use of classification text remain excluded by the repository's hard rules.

# TODO: Confirm product non-goals for the future scope; previous MVP exclusions are now proposals in this draft and cannot also be treated as permanent exclusions — see Open Questions.

## Open Questions

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
