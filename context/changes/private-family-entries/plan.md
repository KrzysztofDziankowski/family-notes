# Private Family Entries and Child Entry Creation Implementation Plan

## Overview

Add optional creator-only privacy to family entries, let children create entries for themselves through the existing natural-language capture flow, and add privacy filters to both parent and child calendars. Privacy must be enforced by family-scoped services and queries so direct URLs and the automation API cannot bypass it.

## Current State Analysis

`Entry` already records a nullable `created_by` family membership, but has no privacy field. Parent reads are family-wide; child reads include entries assigned to the active child; automated entry reads return all entries for the token owner's family. These rules are enforced in separate service paths, so privacy must be applied in each path and in direct-entry lookups.

Parents can classify text and confirm proposals. Capture, follow-up, correction, and confirmation routes currently require a parent. Child calendar and detail routes are GET-only. The parent calendar already has a server-rendered child filter whose state is carried through calendar navigation and detail links.

### Key Discoveries:

- `entries/models.py:63-70` has nullable `Entry.created_by`; manual confirmation stores the request membership in `entries/services.py:64-76`, while automated creation leaves it unset.
- `entries/services.py:173-195,346-358` is the core for parent and child list scoping; direct parent and child detail lookups are in `entries/views.py:989-994,1415-1422`.
- The automation API calls the distinct family-wide query in `entries/api_views.py:245-255` and `entries/services.py:364-379`; it must not reveal private entries.
- Parent classification persistence is parent-only (`entries/services.py:26-47,251-287`); the child calendar has no create route (`entries/urls.py:14-23`).
- Calendar filtering and query-string preservation are handled in `entries/views.py:918-987,1047-1059`; the shared filter partial and JavaScript already support no-JavaScript server rendering.
- Existing access tests cover parent management, assigned-child visibility, and automation reads. Extend those patterns to private creator/non-creator and child creation cases.
- Project UI rules require Polish copy, family context fields on POST forms, accessible field rendering, and tokens from `family_notes/static/css/tokens.css`.

## Desired End State

Every entry can be public or private. A private entry is visible only to its recorded creator, including when it is assigned to another family member. This rule applies to lists, direct detail and edit routes, and API reads. Existing entries and automated entries without a human creator remain public.

Children can use the existing natural-language capture, follow-up, correction, and confirmation flow to add tasks, events, and notes assigned only to themselves. The child is recorded as creator. New entries default to public; the creator can set or change privacy without gaining permission to edit or delete other entry fields.

Parent and child calendars offer All, Private, and Not private filters over entries that the current person is already allowed to see. All preserves the usual calendar contents plus the creator's own private entries.

## What We're NOT Doing

- Allowing children to assign entries to another person, edit entry content, or delete entries.
- Allowing parents to read or manage a private entry created by another person, including a child.
- Making creatorless automated entries private or assigning their authorship to an automation token.
- Returning private entries through the automation API.
- Adding family/role administration, external integrations, analytics, or storage of classification input beyond the requested entry flow.

## Implementation Approach

Add a non-null `is_private` flag defaulting to false, then centralize visibility in the family-scoped query/service paths. Keep parent CRUD behavior for visible public entries, but scope private entries to their creator; provide a narrowly authorized privacy update for the creator. Reuse the current classification journey for children while restricting classification candidates and every server-side assignment to the active child. Finally, add the privacy choice and filters to the existing forms and calendars, carrying filter state through navigation and detail return links.

## Critical Implementation Details

The child flow must enforce its membership at every transition, not only when rendering the first capture page. Follow-up, correction, batch confirmation, and idempotent replay must not accept another assignee or return an existing entry created by another family member. Every new POST in `entries` must carry and validate the request family context.

Private reads must be filtered before date grouping and applied to direct-ID queries as well as lists. A non-creator's request for a private entry should resolve like a missing entry. Privacy changes are the only post-creation mutation available to a child; entry content and assignment remain read-only to them.

## Phase 1: Private Entry Model and Access Rules

### Overview

Introduce the privacy field and establish creator-only visibility in every existing read path before exposing privacy controls. Preserve existing family-scoped access and make current rows public by default.

### Changes Required:

#### 1. Entry model and migration

**File**: `entries/models.py`, new `entries/migrations/0011_entry_is_private.py`

**Intent**: Give entries an explicit privacy state while keeping historical and automated rows public. Keep the field non-null so every query has an unambiguous value.

**Contract**: Add `Entry.is_private` as a boolean defaulting to `False`; the migration must preserve all current rows as public and use a database default consistent with the model default.

#### 2. Family-scoped read and mutation services

**File**: `entries/services.py`

**Intent**: Make creator-only access a service/query invariant rather than a presentation rule. Apply it to parent management queries, assigned-child queries, direct entry resolution, and the automation read query.

**Contract**: Parent and child queries include public entries plus private entries whose `created_by` is the request's family-context membership. The automation API returns public entries only. Any privacy-only update authorizes the active family-context membership as the entry creator and changes no other entry field.

#### 3. Parent and child direct-entry views

**File**: `entries/views.py`, `entries/tests/test_private_entries.py`, related access/API test modules

**Intent**: Prevent detail and management URLs from exposing content that list filters omit. Preserve the existing indistinguishable missing/foreign-ID behavior for inaccessible private entries.

**Contract**: Detail, edit, delete, and privacy-update lookups resolve through creator-aware services. Add parent/child/other-child/anonymous/foreign-family coverage, including creator-only access, public visibility, and automation API exclusion.

#### 4. Product requirements

**File**: `context/foundation/prd.md`

**Intent**: Record the accepted privacy contract so the existing family-wide parent and child-read rules no longer contradict implementation scope.

**Contract**: Update entry requirements and access control to state creator-only privacy, public-by-default entries, private API exclusion, and creator-only privacy changes; leave unrelated MVP boundaries intact.

### Success Criteria:

#### Automated Verification:

- `uv run python manage.py test entries.tests.test_private_entries entries.tests.test_manage_access entries.tests.test_child_entries entries.tests.test_entries_api` passes with creator, non-creator, role, family, anonymous, and API cases.
- `uv run python manage.py check` passes.
- `uv run python manage.py makemigrations --check --dry-run` reports no model/migration drift.

#### Manual Verification:

- A parent can open their own private entry, while another parent and the assigned child cannot open its direct URL; each can still open a public entry they are otherwise allowed to see.
- A private entry does not appear in automation API results, and creatorless EduVulcan entries remain public.

**Implementation Note**: After completing this phase and its automated verification, pause for human confirmation that the manual checks are satisfactory before proceeding.

## Phase 2: Child Natural-Language Capture

### Overview

Extend the existing capture journey to active child memberships, retaining review and confirmation while forcing every proposal to the signed-in child. Record the child as creator and default new entries to public.

### Changes Required:

#### 1. Child-authorized classification and persistence

**File**: `entries/classification/service.py`, `entries/services.py`, `entries/views.py`, `entries/urls.py`

**Intent**: Reuse the current natural-language classification flow for children without granting parent-wide assignment or management permissions. Apply the role and family checks again at each service boundary.

**Contract**: Active children may submit text and complete follow-up, correction, and confirmation. The child's own membership is the only permitted assignee and creator; any submitted or classifier-proposed different assignee is rejected or replaced by a server-side self-assignment. Submission replays cannot return another creator's entry.

#### 2. Child capture and review interface

**File**: `entries/templates/entries/child_list.html`, new/reused child capture and review partials, `entries/forms.py`, `entries/tests/test_child_capture_views.py`

**Intent**: Give children a clear path to add entries from their personal view and complete the same Polish review journey parents use. Keep entry fields and assignment rules constrained to child capabilities.

**Contract**: Children can create tasks, calendar events, and notes through classification and confirmation. Each confirmed proposal offers a public-by-default privacy choice. Child-facing forms use the shared `_field.html` and `describe_fields` pattern, include `{% family_context_field %}` on every POST, and provide no controls for assigning another member or editing/deleting saved entries.

#### 3. Requirements and accessibility coverage

**File**: `context/foundation/prd.md`, `entries/tests/test_accessibility.py`

**Intent**: Document the new child capability and ensure each new capture, review, follow-up, error, and saved state follows the established accessible Polish UI contract.

**Contract**: Update child access requirements to allow self-assigned creation while retaining no general edit/delete permission. Add the new product states to the accessibility audit and satisfy the project's WCAG 2.2 AA checklist.

### Success Criteria:

#### Automated Verification:

- `uv run python manage.py test entries.tests.test_child_capture_views entries.tests.test_follow_up_views entries.tests.test_batch_capture_views entries.tests.test_classification_service` passes, including forced self-assignment and replay-boundary cases.
- `uv run python manage.py test entries.tests.test_accessibility` passes for child capture, review, follow-up, invalid, and saved states.
- `uv run python manage.py check` passes.

#### Manual Verification:

- A child can submit text, answer a follow-up, correct a proposal, and confirm task, event, and note entries assigned to themselves; another child's name cannot change the final assignee.
- Confirming without selecting private creates an entry visible under the normal family rules; selecting private makes it visible only to that child.

**Implementation Note**: After completing this phase and its automated verification, pause for human confirmation that the manual checks are satisfactory before proceeding.

## Phase 3: Privacy Controls and Calendar Filters

### Overview

Expose privacy at confirmation and to the creator after saving, then make privacy filtering available on both calendars without bypassing server-side visibility.

### Changes Required:

#### 1. Privacy controls and creator-only updates

**File**: `entries/forms.py`, `entries/services.py`, `entries/views.py`, `entries/urls.py`, entry confirmation/detail templates

**Intent**: Let the creator decide privacy for a new entry and change that choice later. A privacy change must not grant children general entry editing rights or let another family member change an entry's privacy.

**Contract**: Confirmation forms carry a per-entry privacy value through single and batch confirmation. A creator-authorized POST changes only `is_private`; it uses family context and standard CSRF protection, and its UI is shown only to the creator. Parent-created entries remain manageable through the existing parent flow; children receive only a privacy control for their own entries.

#### 2. Parent and child privacy filters

**File**: `entries/views.py`, `entries/templates/entries/_member_filter.html`, `entries/templates/entries/_child_calendar.html`, `entries/templates/entries/_calendar_nav.html`, `family_notes/static/js/member-filter.js`, related filter tests

**Intent**: Let each user filter the entries they can already access, with consistent calendar behavior for parents and children. Keep list visibility enforced by the query even when filters or JavaScript are bypassed.

**Contract**: Both calendars expose All, Private, and Not private states. All is the default and contains public entries plus the creator's private entries. The selected privacy state survives calendar navigation and detail/back links, has a visible and announced current state, and works through server-rendered links without JavaScript.

#### 3. Shared UI and accessibility states

**File**: `entries/templates/entries/_*.html`, `family_notes/static/css/tokens.css`, `entries/tests/test_private_entry_filters.py`, `entries/tests/test_accessibility.py`

**Intent**: Present privacy status and filters in the existing design system without introducing inaccessible or inconsistent controls.

**Contract**: User-facing copy is Polish; templates use existing tokens and shared field/notice patterns, with no literal colors or inline styles. Add accessibility cases for privacy selection, creator-only privacy changes, and both calendar filter states.

### Success Criteria:

#### Automated Verification:

- `uv run python manage.py test entries.tests.test_private_entry_filters entries.tests.test_private_entries entries.tests.test_manage_views entries.tests.test_child_views` passes for default/all/private/not-private states and URL-state preservation.
- `uv run python manage.py test entries.tests.test_accessibility` passes for privacy controls and parent/child calendar filters.
- `uv run python manage.py check` and `uv run python manage.py makemigrations --check --dry-run` pass.

#### Manual Verification:

- A creator can make their entry private and public after saving; a non-creator cannot see or change the private entry, including through a direct URL.
- Parent and child filters show All, Private, and Not private correctly and preserve the selected state across calendar navigation and return from detail.
- Complete the accessibility manual matrix for affected flows and record it in `context/changes/private-family-entries/a11y-verification.md`.

**Implementation Note**: After completing this phase and its automated verification, pause for human confirmation that the manual checks are satisfactory before closing the change.

## Testing Strategy

### Unit Tests:

- Cover privacy filtering in parent, child, and automation query services; creator-only privacy updates; public defaults; creatorless automated rows; and same-family idempotent replay isolation.
- Cover child classification transitions, candidate restriction to self, server-enforced assignment, follow-up/correction/confirmation, and attempted parent, sibling, foreign-family, and anonymous access.
- Cover All / Private / Not private query parameters, invalid values, active filter links, and filter-state preservation through navigation and detail links.

### Integration Tests:

- Exercise a parent-created private entry, a child-created public entry, and a child-created private entry across parent calendar, child calendar, direct detail URLs, parent management routes, and automation API reads.
- Exercise child text capture from submission through saved detail with both public and private choices, including a follow-up-required proposal.

### Manual Testing Steps:

1. As a child, classify and save a task, an event, and a note; confirm each is assigned to the child and defaults to public.
2. Mark one entry private during confirmation, then change its privacy after saving; verify only its creator can read or change privacy.
3. Use All, Private, and Not private on both calendars, navigate between windows and detail, and verify the selected filter is preserved.
4. Verify private entries do not appear in automation API responses and creatorless EduVulcan entries remain public.
5. Complete the accessibility matrix in `context/foundation/accessibility.md` for affected flows and record the result in `a11y-verification.md`.

## Performance Considerations

The configured family is small and the calendars already retrieve a bounded date window. Apply privacy and selected-filter predicates in the database query before date grouping; no cache, analytics, or new background work is needed.

## Migration Notes

Add `is_private` as a non-null boolean with model and database defaults set to false. This keeps existing and creatorless entries public without a data backfill. Keep the migration limited to this field; do not infer ownership for imported entries.

## References

- Product behavior: `context/foundation/prd.md`
- Accessibility rules: `context/foundation/accessibility.md`
- Entry model and creator field: `entries/models.py:63-73`
- Entry access services: `entries/services.py:173-195,346-379`
- Parent and child calendars: `entries/views.py:918-987,1047-1059,1096-1113,1401-1422`
- Automation API: `entries/api_views.py:245-255`
- Existing child read-only contract and tests: `entries/tests/test_child_views.py:95-103`
- Existing parent filter behavior tests: `entries/tests/test_manage_views.py:1312-1348`
- Family POST context field: `entries/templates/entries/_capture_form.html:1-5`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Private Entry Model and Access Rules

#### Automated

- [x] 1.1 `uv run python manage.py test entries.tests.test_private_entries entries.tests.test_manage_access entries.tests.test_child_entries entries.tests.test_entries_api` passes with creator, non-creator, role, family, anonymous, and API cases. — aad4038
- [x] 1.2 `uv run python manage.py check` passes. — aad4038
- [x] 1.3 `uv run python manage.py makemigrations --check --dry-run` reports no model/migration drift. — aad4038

#### Manual

- [ ] 1.4 A parent can open their own private entry, while another parent and the assigned child cannot open its direct URL; each can still open a public entry they are otherwise allowed to see.
- [ ] 1.5 A private entry does not appear in automation API results, and creatorless EduVulcan entries remain public.

### Phase 2: Child Natural-Language Capture

#### Automated

- [x] 2.1 `uv run python manage.py test entries.tests.test_child_capture_views entries.tests.test_follow_up_views entries.tests.test_batch_capture_views entries.tests.test_classification_service` passes, including forced self-assignment and replay-boundary cases. — 6b1878e
- [x] 2.2 `uv run python manage.py test entries.tests.test_accessibility` passes for child capture, review, follow-up, invalid, and saved states. — 6b1878e
- [x] 2.3 `uv run python manage.py check` passes. — 6b1878e

#### Manual

- [ ] 2.4 A child can submit text, answer a follow-up, correct a proposal, and confirm task, event, and note entries assigned to themselves; another child's name cannot change the final assignee.
- [ ] 2.5 Confirming without selecting private creates an entry visible under the normal family rules; selecting private makes it visible only to that child.

### Phase 3: Privacy Controls and Calendar Filters

#### Automated

- [x] 3.1 `uv run python manage.py test entries.tests.test_private_entry_filters entries.tests.test_private_entries entries.tests.test_manage_views entries.tests.test_child_views` passes for default/all/private/not-private states and URL-state preservation.
- [x] 3.2 `uv run python manage.py test entries.tests.test_accessibility` passes for privacy controls and parent/child calendar filters.
- [x] 3.3 `uv run python manage.py check` and `uv run python manage.py makemigrations --check --dry-run` pass.

#### Manual

- [ ] 3.4 A creator can make their entry private and public after saving; a non-creator cannot see or change the private entry, including through a direct URL.
- [ ] 3.5 Parent and child filters show All, Private, and Not private correctly and preserve the selected state across calendar navigation and return from detail.
- [ ] 3.6 Complete the accessibility manual matrix for affected flows and record it in `context/changes/private-family-entries/a11y-verification.md`.
