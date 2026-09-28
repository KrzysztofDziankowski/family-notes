# Parent Family Entry Management Implementation Plan

## Overview

Implement roadmap slice S-02: a parent-only shared family-entry view with direct structured creation, entry details, editing, and permanent deletion. Reuse the existing `Entry` model and family-access contract while preserving provenance and keeping child access in S-03.

## Current State Analysis

S-01 already provides the `Entry` model, natural-language capture, editable confirmation, family-scoped saving, and shared UI tokens. No general list, detail, structured-create, update, or delete routes exist.

The roadmap still marks S-01 `in-progress`, but its change is `impl_reviewed` and every plan criterion is complete. S-02 can therefore treat it as an implemented prerequisite.

## Desired End State

An active parent can browse upcoming family entries, access past entries separately, open a stable detail page, create an entry directly or through natural-language capture, edit manual and EduVulcan entries including their school subtype, and permanently delete an entry after inline confirmation.

Children, inactive or unconfigured members, unauthenticated users, automation tokens, and members of other families cannot use these management paths or learn whether a foreign entry exists.

### Key Discoveries:

- `Entry` already holds the required editable fields and provenance in `entries/models.py:15`.
- The current writer independently checks parent authorization and family assignment in `entries/services.py:13`.
- Existing form validation and family-scoped assignee choices live in `entries/forms.py:40`.
- The current saved-entry lookup scopes by family before resolving a primary key in `entries/views.py:127`.
- FR-006 requires parent CRUD; FR-008 requires strict family isolation.

## What We're NOT Doing

- No child entry view or child-facing navigation; S-03 owns that.
- No family/member administration or multi-family UI.
- No soft deletion, undo, audit log, bulk actions, search, or pagination.
- No changes to classification or EduVulcan intake.
- No schema migration.
- No JavaScript modal or new UI dependency.
- No editing of family, source, creator, submission key, or creation timestamp.

## Implementation Approach

Keep the repository's function-view and explicit-service architecture. Extract reusable entry-field validation from the capture review form, add dedicated structured-create and edit forms, and place family-scoped retrieval and mutations behind independently authorized services. Build parent-only index, detail, create, edit, and delete endpoints using the existing Pico CSS, semantic tokens, and entry partials. Test every path against the complete access and family-isolation matrix.

## Critical Implementation Details

List ordering must be explicit rather than relying on database-specific null ordering. Provenance fields remain immutable during updates, and structured creation retains a hidden idempotency key so retries cannot create duplicate rows. User-selected incompatible type/school-subtype combinations must produce a Polish validation error instead of silently discarding the visible choice.

## Phase 1: Management Contracts and Validation

### Overview

Create reusable form and service contracts for safe structured creation, update, deletion, and family-scoped retrieval.

### Changes Required:

#### 1. Shared entry forms

**File**: `entries/forms.py`

**Intent**: Share field definitions and invariant helpers across capture review, structured creation, and editing without forcing their different compatibility policies into one behavior.

**Contract**: Shared editable fields are type, content, date, time, assignee, and optional school subtype. Assignee choices contain only active members of the parent's family. Content remains stripped, required, and limited to 2,000 characters. Calendar events require a date; school subtypes enforce their required date/member fields and compatible entry type. Capture retains silent clearing of incompatible hidden classifier metadata and its existing missing-field hints. Structured create and edit expose school subtype and reject a visible type/subtype mismatch with a Polish field error. The structured-create form includes a hidden UUID submission key, while the edit form does not. All other user-facing labels and errors remain Polish.

#### 2. Parent management services

**File**: `entries/services.py`

**Intent**: Provide a single auditable boundary for management reads and mutations, independently of view authorization.

**Contract**: A family-scoped parent query returns only entries from the active parent's family. Structured creation sets `family`, `source=manual`, and `created_by` from the active membership and is idempotent on the submission key. Update resolves the target within the parent's family and changes only type, content, date, time, assignee, and school subtype while preserving family, source, creator, submission key, and creation timestamp. Delete resolves the target within the parent's family and permanently deletes only that row. Non-parent callers raise `PermissionDenied`; missing or foreign entry IDs are handled identically by the view as 404. All mutation paths repeat family-assignment and entry validation in the service layer.

### Success Criteria:

#### Automated Verification:

- Form tests cover structured create/edit, Polish errors, active-family assignees, field limits, calendar dates, school subtype compatibility, and required school data.
- Service tests cover own-family create/update/delete and the complete unauthorized-user matrix.
- Structured-create retries with the same submission key produce exactly one entry.
- Updates preserve all provenance fields for manual and EduVulcan entries.
- Foreign-family and inactive assignees are rejected without mutation.
- Targeted tests pass: `uv run python manage.py test entries.tests.test_entry_forms entries.tests.test_entry_service`.

#### Manual Verification:

- Structured create and edit forms render all agreed editable fields with understandable Polish labels.

**Implementation Note**: After completing this phase and all automated verification passes, pause for manual confirmation before proceeding.

---

## Phase 2: Parent CRUD Routes and UI

### Overview

Deliver the shared index, stable detail pages, structured creation, editing, inline delete confirmation, and parent navigation.

### Changes Required:

#### 1. Routes and views

**File**: `entries/urls.py`, `entries/views.py`

**Intent**: Expose parent-only management paths using the same authorization and family-scoping conventions as capture.

**Contract**: Add `GET /entries/` for the shared index, where `view=upcoming` is the default and `view=past` is the only alternate mode; `GET|POST /entries/create/` for structured creation; `GET /entries/<pk>/` for detail; `GET|POST /entries/<pk>/edit/` for editing; and `POST /entries/<pk>/delete/` for permanent deletion. Anonymous users follow Django's login redirect, authenticated non-parents receive 403, and missing or foreign-family IDs both return 404. Create and update redirect to detail. Delete redirects to the allowlisted originating list mode, defaulting to upcoming; arbitrary redirect URLs are never accepted.

#### 2. Index organization and ordering

**File**: `entries/views.py`, management templates

**Intent**: Make current information prominent while keeping history and undated entries reachable.

**Contract**: Upcoming dated entries include the application-local date and future dates, ordered by date ascending, time ascending with missing times last, then primary key. Undated entries follow and order by `updated_at` descending, then primary key descending. Past entries use dates before today and order by date descending, time descending with missing times last, then primary key descending. Ordering tests assert these exact sequences. The index switches clearly between “Nadchodzące” and “Minione” and has distinct empty states. No pagination is introduced.

*Note from S-03 (`child-assigned-entry-view`) plan review: reuse `entries/listing.py` (list modes, partition, and ordering) and `entries/templates/entries/_entry_row.html` from S-03 instead of implementing ordering in `entries/views.py`. If S-03 hasn't landed yet, create them to S-03's contract. The shared contract also hides `lucky_number` entries from lists and dates an undated `grade` by the local day of its `created_at`.*

#### 3. Templates and navigation

**File**: `entries/templates/entries/`, relevant parent navigation templates

**Intent**: Provide mobile-friendly management pages using the established Pico/token contract.

**Contract**: Index rows show type, content, date/time, assignee, and links to detail/edit. Detail shows all entry data, optional school subtype, source, created timestamp, and updated timestamp, but no internal identifiers or creator internals. Detail contains a no-JavaScript HTML disclosure with a Polish warning and CSRF-protected delete form. Create and edit reuse the shared field partial and display errors accessibly. Parent-facing account and capture screens link to the index, which exposes both structured creation and existing natural-language capture. All copy is Polish and code identifiers remain English.

### Success Criteria:

#### Automated Verification:

- Route tests cover index, detail, create, edit, and POST-only delete.
- Index tests prove exact upcoming, undated, and past boundaries and deterministic ordering.
- Parent list/detail responses contain only entries from the parent's family.
- Foreign and nonexistent IDs return the same status and reveal no sentinel content.
- Successful create/update/delete redirects are correct and preserve only an allowlisted list mode.
- Template tests confirm structured-create, capture, edit, and delete actions are present.
- Relevant tests pass: `uv run python manage.py test entries.tests`.

#### Manual Verification:

- At phone width, a parent can browse upcoming and past entries, create one directly, edit it, inspect its provenance, and delete it.
- The inline delete disclosure is clear and usable without JavaScript.
- Long content, undated entries, missing times, and empty list states remain readable.

**Implementation Note**: After completing this phase and all automated verification passes, pause for manual confirmation before proceeding.

---

## Phase 3: Security, Lifecycle, and Visual Verification

### Overview

Close the access-control matrix, protect existing capture behavior, and provide a screenshot-based visual gate for all management states.

### Changes Required:

#### 1. Authorization and regression coverage

**File**: `entries/tests/`, `family_access/tests.py` only if helper coverage must be extended

**Intent**: Prove that every read and mutation obeys the repository's family-access hard rule.

**Contract**: For index, detail, create, edit, and delete as applicable, cover an active parent in the same family, a parent targeting another family's entry, a child, an inactive parent, an inactive family, an authenticated user without membership, and an anonymous user. Mutation-denial tests prove the database remains unchanged.

#### 2. Management state gallery and screenshot gate

**File**: existing DEBUG state view/templates and change screenshot directory

**Intent**: Render representative management states without reading or writing real family data, then inspect them at Android phone width.

**Contract**: DEBUG-only synthetic states cover populated upcoming list, past list, empty list, detail with manual provenance, detail with EduVulcan provenance, create form, invalid form, edit form, and opened delete disclosure. Unsaved detail fixtures assign `source`, `created_at`, and `updated_at` explicitly, and the delete disclosure is rendered open through HTML markup. Synthetic content contains no real family data and creates no `Entry` rows. With `DEBUG=False`, the gallery returns 404; non-parent access remains denied; capture states continue to render unchanged. Save a reviewed phone-width screenshot under the change folder during implementation.

### Success Criteria:

#### Automated Verification:

- Full tests pass: `uv run python manage.py test`.
- Django checks pass: `uv run python manage.py check`.
- Migration drift check passes: `uv run python manage.py makemigrations --check --dry-run`.
- State-gallery tests prove DEBUG gating, parent-only access, expected state markers, and zero database writes.
- Existing capture, classification, notification-intake, and family-access tests remain green.

#### Manual Verification:

- The management state gallery is reviewed at 360px width with no clipping, unreadable metadata, or inaccessible actions.
- Chrome on Android completes list → detail → edit and detail → delete flows.
- A final check confirms a parent cannot infer the existence of a foreign-family entry.

**Implementation Note**: Complete manual verification before implementation review.

---

## Testing Strategy

### Unit Tests:

- Shared validation across capture, structured create, and edit.
- Parent authorization and active-family requirements.
- Family-scoped lookup and assignee validation.
- Idempotent structured creation.
- Immutable provenance during update.
- Deterministic list partitioning and ordering.
- Hard-delete isolation.

### Integration Tests:

- Structured create → detail → edit → detail → delete → originating list.
- Existing natural-language capture → shared index → detail.
- EduVulcan entry → parent correction → preserved source → deletion.
- Full access matrix for every exposed path.
- Foreign-family IDs remain indistinguishable from nonexistent IDs.

### Manual Testing Steps:

1. Sign in as a parent and inspect upcoming, undated, past, and empty states.
2. Create an entry through the structured form and confirm it appears in the correct section.
3. Edit type, school subtype, schedule, and assignee; verify provenance is unchanged.
4. Open and cancel the delete disclosure, then confirm deletion.
5. Repeat detail/edit/delete attempts as a child and with a foreign entry URL.
6. Review every synthetic state at 360px width and in Chrome on Android.

## Performance Considerations

The configured family has low volume, so pagination and caching are unnecessary. List queries should select related assignee data and use the existing `(family, date)` index where applicable. Explicit ordering prevents SQLite/PostgreSQL null-order differences.

## Migration Notes

No database migration or data backfill is expected. Rollback consists of removing the new management routes, forms, services, templates, and tests; existing entries and capture behavior remain compatible.

## References

- `context/foundation/prd.md` — FR-006, FR-008, Access Control
- `context/foundation/roadmap.md` — S-02
- `context/changes/first-school-event-capture/plan.md`
- `entries/models.py:15`
- `entries/services.py:13`
- `entries/forms.py:40`
- `entries/views.py:127`
- `family_access/access.py:6`
- Django 5.2 ModelForm and deletion/CSRF documentation, verified through Context7

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles.

### Phase 1: Management Contracts and Validation

#### Automated

- [x] 1.1 Form tests cover structured create/edit, Polish errors, active-family assignees, field limits, calendar dates, school subtype compatibility, and required school data. — 8cd1ba1
- [x] 1.2 Service tests cover own-family create/update/delete and the complete unauthorized-user matrix. — 8cd1ba1
- [x] 1.3 Structured-create retries with the same submission key produce exactly one entry. — 8cd1ba1
- [x] 1.4 Updates preserve all provenance fields for manual and EduVulcan entries. — 8cd1ba1
- [x] 1.5 Foreign-family and inactive assignees are rejected without mutation. — 8cd1ba1
- [x] 1.6 Targeted tests pass: `uv run python manage.py test entries.tests.test_entry_forms entries.tests.test_entry_service`. — 8cd1ba1

#### Manual

- [x] 1.7 Structured create and edit forms render all agreed editable fields with understandable Polish labels. (agent-verified by rendering forms; human visual check pending) — 8cd1ba1

### Phase 2: Parent CRUD Routes and UI

#### Automated

- [x] 2.1 Route tests cover index, detail, create, edit, and POST-only delete. — b8c94b2
- [x] 2.2 Index tests prove exact upcoming, undated, and past boundaries and deterministic ordering. — b8c94b2
- [x] 2.3 Parent list/detail responses contain only entries from the parent's family. — b8c94b2
- [x] 2.4 Foreign and nonexistent IDs return the same status and reveal no sentinel content. — b8c94b2
- [x] 2.5 Successful create/update/delete redirects are correct and preserve only an allowlisted list mode. — b8c94b2
- [x] 2.6 Template tests confirm structured-create, capture, edit, and delete actions are present. — b8c94b2
- [x] 2.7 Relevant tests pass: `uv run python manage.py test entries.tests`. — b8c94b2

#### Manual

- [x] 2.8 At phone width, a parent can browse upcoming and past entries, create one directly, edit it, inspect its provenance, and delete it. (agent-verified: headless Chromium at 360px mobile viewport on a fictional dev family drove index → Minione → invalid create → create → detail → edit → detail → delete → upcoming list; screenshots in screenshots/phase2-360-*.png; human check pending) — b8c94b2
- [x] 2.9 The inline delete disclosure is clear and usable without JavaScript. (agent-verified: Chromium at 360px with script execution disabled, real mouse events opened the <details> and submitted the CSRF form, redirecting to the list with "Usunięto wpis."; page ships no <script>; human check pending) — b8c94b2
- [x] 2.10 Long content, undated entries, missing times, and empty list states remain readable. (agent-verified: 360px screenshots show wrapped unbroken long content, "Bez daty" section, untimed rows, and the Minione empty state with no horizontal overflow (scrollWidth 360); fixed Pico nav margins clipping the list-mode tabs; human check pending) — b8c94b2

### Phase 3: Security, Lifecycle, and Visual Verification

#### Automated

- [x] 3.1 Full tests pass: `uv run python manage.py test`.
- [x] 3.2 Django checks pass: `uv run python manage.py check`.
- [x] 3.3 Migration drift check passes: `uv run python manage.py makemigrations --check --dry-run`.
- [x] 3.4 State-gallery tests prove DEBUG gating, parent-only access, expected state markers, and zero database writes.
- [x] 3.5 Existing capture, classification, notification-intake, and family-access tests remain green.

#### Manual

- [x] 3.6 The management state gallery is reviewed at 360px width with no clipping, unreadable metadata, or inaccessible actions. (agent-verified: headless Chromium at a 360px mobile viewport rendered /entries/_states/; each of the 9 management states was captured separately (screenshots/phase3-360-gallery-*.png) and inspected — no horizontal overflow (scrollWidth 360), metadata wraps legibly, all actions visible; human check pending)
- [x] 3.7 Chrome on Android completes list → detail → edit and detail → delete flows. (agent-verified: Chromium at a 360px mobile viewport with real mouse events went list → detail → Edytuj → save ("Zapisano zmiany.") → open disclosure → "Usuń na stałe" → upcoming list ("Usunięto wpis."); real Android device check pending)
- [x] 3.8 A final check confirms a parent cannot infer the existence of a foreign-family entry. (agent-verified: as a parent on the dev server, a foreign-family entry ID and a nonexistent ID both returned 404 with bodies identical apart from the echoed path and no sentinel text; automated tests assert byte-identical 404s for detail/edit/delete; human check pending)
