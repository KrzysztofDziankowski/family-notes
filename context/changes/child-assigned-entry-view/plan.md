# Child Assigned Entry View Implementation Plan

## Overview

Implement roadmap slice S-03 (FR-007, FR-008): a signed-in child gets a read-only personal view, "Moje wpisy", listing only the entries whose `assigned_member` is that child, with a detail page per entry. The slice also introduces the shared time-partition/ordering helper and entry-row partial that S-02 (parent family entry management) will reuse, so both views follow one list contract.

## Current State Analysis

S-01 delivered the `Entry` model, parent capture, Pico CSS with semantic tokens, and a DEBUG-only kitchen-sink page. F-01 delivered the family access contract, including `can_read_assigned_child`, which nothing calls yet. Children can sign in but land on `/account/`, which offers them nothing: the only action link is the parent-only "Dodaj wpis".

S-02 is `plan_reviewed` but not implemented. Its plan defines the upcoming/undated/past ordering and a parent-only `/entries/` index, and explicitly leaves child navigation to S-03. The two slices are parallel on the roadmap, so S-03 must not depend on S-02 code.

## Desired End State

An active child opens `/account/`, follows "Moje wpisy", and sees upcoming entries assigned to them (dated today or later, then undated), with a toggle to past entries. Each row opens a detail page showing the entry's full data. The child cannot create, edit, or delete anything.

Entries assigned to nobody ("Cała rodzina"), to another child, or to another family never appear in the list, and their detail URLs return the same 404 as a nonexistent ID. Parents, inactive or unconfigured members, and anonymous users cannot use the child view.

### Key Discoveries:

- `Entry.assigned_member` is nullable. `null` renders as "Cała rodzina" in `entries/templates/entries/_saved_panel.html:18`, so family-wide entries exist and must be excluded.
- `can_read_assigned_child(membership, assigned_child)` in `family_access/access.py:39` returns true for `membership == assigned_child` only when that member is an active child in an active family. Called with the child's own membership, it is exactly the gate this view needs, and it rejects parents.
- `get_active_membership` (`family_access/access.py:6`) returns `None` for inactive members, inactive families, and unconfigured users.
- The capture views gate on `_require_parent` → `PermissionDenied` (403) after `login_required` (`entries/views.py:40`). The child view mirrors this shape.
- The `(family, date)` index exists (`entries/models.py:77`). Volume is one family, so no pagination is needed.
- `LOGIN_REDIRECT_URL = '/account/'` (`family_notes/settings.py:233`). The account page already branches on role (`family_access/templates/family_access/account_status.html:14`).
- `FamilyFixtureMixin` (`entries/tests/test_classification_service.py:73`) provides two children, an inactive child, and a foreign family, which covers the access matrix.
- S-02's plan (`context/changes/parent-family-entry-management/plan.md`, Phase 2 §2) defines the ordering this slice implements as the shared helper.

## What We're NOT Doing

- No visibility of family-wide (unassigned) entries to children. FR-007 is read literally.
- No create, edit, delete, or capture for children.
- No parent "preview as child" route.
- No change to the login redirect. Children reach the view through `/account/`.
- No parent index, detail, or CRUD. S-02 owns those and reuses the shared helper and partial.
- No pagination, search, or filtering beyond upcoming/past.
- No schema migration.
- No new CSS framework or JavaScript. Styling uses the existing Pico + `tokens.css` contract.

## Implementation Approach

Keep the repository's function-view and explicit-service style. A new module holds the list-mode allowlist and the upcoming/undated/past partition with explicit null ordering. It is family- and role-agnostic, so S-02's parent index can reuse it. A child-scoped service gates on `can_read_assigned_child(membership, membership)` and filters by family and assignee in the queryset. The list and detail views then resolve everything through that queryset, so a foreign ID is indistinguishable from a missing one. Templates share an `_entry_row.html` partial that takes the detail URL name as a parameter.

## Critical Implementation Details

A grade's effective date is the local day of `created_at` (an annotation with `TruncDate` in the current timezone, used only when `date` is null), and partitioning and ordering both use that annotation. The list must not rely on database default null ordering. SQLite and PostgreSQL differ, so time ordering uses `F('time').asc(nulls_last=True)` / `.desc(nulls_last=True)`. Upcoming is two ordered querysets (dated from today, then undated), not one sort, because undated entries order by `updated_at`. "Today" is `timezone.localdate()` (Europe/Warsaw), never the UTC date.

## Phase 1: Shared List Contract and Child-Scoped Query

### Overview

Create the reusable list partition helper and entry-row partial, plus a child-scoped read service with an independent authorization check.

### Changes Required:

#### 1. Shared list partition helper

**File**: `entries/listing.py` (new)

**Intent**: Give S-02 and S-03 one definition of list modes and ordering, so the parent and child views cannot drift.

**Contract**: The list modes are `upcoming` (the default) and `past`. A normalizer maps any other or missing value to `upcoming`. The partition function takes an already-scoped `Entry` queryset, a mode and `today`, and returns ordered sections:
- Upcoming: dated entries with `date >= today`, ordered by date ascending, time ascending with missing times last, then `pk` ascending. Undated entries follow, ordered by `updated_at` descending, then `pk` descending.
- Past: entries with `date < today`, ordered by date descending, time descending with missing times last, then `pk` descending. Undated entries never appear in past.
- Lucky numbers: entries with `school_item = lucky_number` are excluded from both modes. Their detail pages still resolve.
- Grades: an entry with `school_item = grade` and no `date` gets an effective date equal to the application-local day of `created_at`. It is partitioned and ordered as a dated entry (no time) by that effective date, so it moves to past the day after it was created. The stored `date` is never written.

The helper never filters by family, role, or assignee. Scoping is the caller's job.

#### 2. Shared entry-row partial

**File**: `entries/templates/entries/_entry_row.html` (new), `family_notes/static/css/tokens.css`

**Intent**: Render one entry row the same way for parent and child lists.

**Contract**: The partial takes `entry` and `detail_url_name`. It shows the type label, content (`truncatechars:120` in the row, never truncated in detail), the date formatted like `_saved_panel.html` with the time when present, and the assignee or "Cała rodzina", and it links to `detail_url_name` with `entry.pk`. The child list passes a flag to hide the redundant assignee. Any new layout class (for example `.fn-entry-list`) is added to `tokens.css` using existing tokens only. No new colour or spacing values.

*Addendum (impl-review F2, 2026-09-28):* The partial also takes two optional parameters. `edit_url_name` adds an "Edytuj" link to that URL with `entry.pk`; it was added at coordinator request so S-02 can reuse the partial, and child templates never pass it. `detail_query` is a constant query string (`view=past`) appended to the detail link so the back link can return to the same mode. Leaving either one out changes nothing.

#### 3. Child-scoped read service

**File**: `entries/services.py`

**Intent**: A single auditable boundary for what a child may read, independent of view authorization.

**Contract**: `child_entries(user)` resolves the active membership and raises `PermissionDenied` unless `can_read_assigned_child(membership, membership)` is true. It returns `Entry` rows filtered by `family=membership.family` and `assigned_member=membership`, with `select_related('assigned_member')`. Unassigned entries, entries of other children, and entries of other families are never included.

*Plan-review note (F1): the S-02 reuse pointer was added directly to S-02's `plan.md` (Phase 2 §2) during plan review, so this phase no longer edits S-02's `change.md`.*

### Success Criteria:

#### Automated Verification:

- Listing tests prove the exact upcoming/undated/past boundaries (yesterday, today, tomorrow, undated) and deterministic ordering, including missing times and equal-date ties.
- Mode normalization maps unknown, empty, and missing values to `upcoming`.
- Service tests prove an active child sees only their own entries: an unassigned entry, a sibling's entry, and a foreign-family entry are all excluded.
- Service tests prove a parent, an inactive child, a child in an inactive family, an unconfigured user, and an anonymous user all raise `PermissionDenied`.
- Targeted tests pass: `uv run python manage.py test entries.tests.test_entry_listing entries.tests.test_child_entries`.
- Listing tests prove lucky-number entries are absent from both upcoming and past.
- Listing tests prove an undated grade created today appears in upcoming, and one created yesterday appears in past, ordered by its creation day among dated entries, with its stored `date` still empty.

**Implementation Note**: Phase 1 has no manual criteria. Proceed to Phase 2 once automated verification passes.

---

## Phase 2: Child Routes and UI

### Overview

Expose the child list and detail pages, and link them from the account page.

### Changes Required:

#### 1. Routes and views

**File**: `entries/urls.py`, `entries/views.py`

**Intent**: Child-only read paths that follow the capture views' authorization conventions.

**Contract**:
- `GET /entries/mine/` (`entries:child_list`) accepts `view=upcoming|past` through the normalizer.
- `GET /entries/mine/<int:pk>/` (`entries:child_detail`) resolves `pk` only inside `child_entries(user)`.
- Both are GET-only.
- Anonymous users get the `login_required` redirect.
- Authenticated users who are not active children get 403.
- Unassigned, sibling, foreign-family, and nonexistent IDs all return the same 404.
- The list's "today" is `timezone.localdate()`.

#### 2. Templates

**File**: `entries/templates/entries/child_list.html`, `entries/templates/entries/child_detail.html` (new)

**Intent**: Mobile-friendly, read-only pages in Polish, built on Pico and the token classes.

**Contract**:
- The list is titled "Moje wpisy". It has a "Nadchodzące" / "Minione" switch that marks the current mode (`aria-current`), rows rendered through `_entry_row.html` with `detail_url_name='entries:child_detail'`, and distinct Polish empty states for upcoming and past.
- Detail shows the type, the full content, the date, the time when present, the school subtype when present, and the source ("Ręcznie" / "EduVulcan") in `fn-details`. It shows no creator, internal IDs, submission key, or timestamps, and it has no edit, delete, or capture actions.
- Detail links back to the list. The back link carries only an allowlisted `view` value taken from the query string.

#### 3. Account entry point

**File**: `family_access/templates/family_access/account_status.html`

**Intent**: Give a child a destination after sign-in, mirroring the parent's "Dodaj wpis" button.

**Contract**: When the active membership's role is child, render a "Moje wpisy" button linking to `entries:child_list`. The parent rendering is unchanged.

### Success Criteria:

#### Automated Verification:

- Route tests cover list (default, `view=past`, unknown `view`) and detail for an active child, and prove non-GET methods return 405.
- The access matrix covers both routes for anonymous (login redirect), parent, inactive child, inactive family, and unconfigured user (403).
- Detail returns 404 with identical bodies for an unassigned entry, a sibling's entry, a foreign-family entry, and a nonexistent ID, and sentinel content from those entries never appears in any child response.
- List responses contain the child's sentinel entries and none of the excluded ones.
- Account page tests show "Moje wpisy" for a child and not for a parent, and "Dodaj wpis" for a parent and not for a child.
- Rendered child pages contain no links or forms to capture, edit, or delete.
- Relevant tests pass: `uv run python manage.py test entries.tests family_access`.

#### Manual Verification:

- Signed in as a child at phone width: account → "Moje wpisy" → switch to "Minione" → open a row → back returns to the same mode.
- Long content, undated entries, missing times, and both empty states remain readable.

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human before proceeding.

---

## Phase 3: Kitchen Sink and Screenshot Gate

### Overview

Render every child-view state from synthetic data and gate the slice on a phone-width screenshot plus the full check suite.

### Changes Required:

#### 1. Child state gallery

**File**: `entries/views.py`, `entries/urls.py`, `entries/templates/entries/child_states.html` (new)

**Intent**: One page showing every child-view state so visual regressions are visible in a single screenshot, without real family data.

**Contract**:
- `GET /entries/mine/_states/` returns 404 when `DEBUG` is false. Anonymous users are redirected to login. Authenticated users without an active membership get 403. Any authenticated user with an active membership can view it, so a local parent or child account can take the screenshot.
- Unsaved synthetic `Entry` objects (explicit `pk`, `source`, `updated_at`; fictional names as in `STATES_MEMBER_CHOICES`) render these states: upcoming populated (with an undated row, a missing time, and a grade dated by its creation day), past populated, upcoming empty, past empty, manual detail, and EduVulcan detail with a school subtype.
- The page reads and writes no `Entry` rows. The existing capture `_states` page is unchanged.
- Route order places `_states/` before `<int:pk>/`.

#### 2. Screenshot

**File**: `context/changes/child-assigned-entry-view/screenshots/`

**Intent**: The visual gate required by the project contract. There is no screenshot test harness, so the screenshot is taken and reviewed manually.

**Contract**: A 360px-wide full-page screenshot of the gallery is committed here after review.

### Success Criteria:

#### Automated Verification:

- Gallery tests prove DEBUG gating (404 when off), the anonymous redirect, 403 for a signed-in user without an active membership, the expected `data-kitchen-state` markers for all six states, and zero `Entry` queries or writes.
- Full tests pass: `uv run python manage.py test`.
- Django checks pass: `uv run python manage.py check`.
- Migration drift check passes: `uv run python manage.py makemigrations --check --dry-run`.

#### Manual Verification:

- The gallery screenshot at 360px shows all six states legibly, with no horizontal scroll, token accent colours, Polish copy throughout, and the current mode visibly marked.
- The screenshot is committed under `context/changes/child-assigned-entry-view/screenshots/`.
- In Chrome on Android, a real child account sees only its own entries, and a hand-typed detail URL for a sibling's entry shows 404.

**Implementation Note**: Complete manual verification before `/10x-impl-review`.

---

## Testing Strategy

### Unit Tests:

- Partition boundaries at today and ordering with null times, equal dates, and undated `updated_at` ties.
- Mode allowlist normalization.
- Lucky-number exclusion and the grade `created_at` effective date around the midnight boundary in the local timezone.
- `child_entries` scoping and the full unauthorized-caller matrix.

### Integration Tests:

- Account → list → detail → back for an active child, in both modes.
- The access matrix on both routes, with identical 404s for unassigned, sibling, foreign, and missing IDs.
- A parent-captured entry assigned to the child appears in the child's upcoming list. An EduVulcan-source entry assigned to the child shows its source on detail.

### Manual Testing Steps:

1. Sign in as a child, open "Moje wpisy", and check upcoming, undated, and past ordering against known data.
2. Switch to "Minione", open an entry, and go back.
3. Type a sibling's and a family-wide entry's detail URL and confirm 404.
4. Sign in as a parent and confirm `/entries/mine/` returns 403 and the account page shows no "Moje wpisy".
5. Review the gallery at 360px and take the screenshot.

## Performance Considerations

This is a single-family, low-volume app. Two queries per list render (dated and undated) with `select_related`, backed by the existing `(family, date)` index. No pagination or caching.

## Migration Notes

No schema change or data migration. To roll back, remove the new routes, templates, service function, listing module, and account link. S-02 would then need to own the listing module itself.

## References

- `context/foundation/prd.md`: FR-007, FR-008, Access Control
- `context/foundation/roadmap.md`: S-03
- `context/changes/parent-family-entry-management/plan.md`: shared ordering contract (Phase 2 §2)
- `context/archive/2026-09-27-first-school-event-capture/plan.md`: kitchen-sink and screenshot gate pattern
- `family_access/access.py:6`, `family_access/access.py:39`
- `entries/models.py:15`, `entries/views.py:40`, `entries/views.py:127`
- `entries/tests/test_classification_service.py:73`
- `context/foundation/lessons.md`: Polish user-facing copy and `feat(child-assigned-entry-view):` commit prefix

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles.

### Phase 1: Shared List Contract and Child-Scoped Query

#### Automated

- [x] 1.1 Listing tests prove the exact upcoming/undated/past boundaries (yesterday, today, tomorrow, undated) and deterministic ordering, including missing times and equal-date ties. — e37e56b
- [x] 1.2 Mode normalization maps unknown, empty, and missing values to `upcoming`. — e37e56b
- [x] 1.3 Service tests prove an active child sees only their own entries: an unassigned entry, a sibling's entry, and a foreign-family entry are all excluded. — e37e56b
- [x] 1.4 Service tests prove a parent, an inactive child, a child in an inactive family, an unconfigured user, and an anonymous user all raise `PermissionDenied`. — e37e56b
- [x] 1.5 Targeted tests pass: `uv run python manage.py test entries.tests.test_entry_listing entries.tests.test_child_entries`. — e37e56b
- [x] 1.6 Listing tests prove lucky-number entries are absent from both upcoming and past. — e37e56b
- [x] 1.7 Listing tests prove an undated grade created today appears in upcoming, and one created yesterday appears in past, ordered by its creation day among dated entries, with its stored `date` still empty. — e37e56b

### Phase 2: Child Routes and UI

#### Automated

- [x] 2.1 Route tests cover list (default, `view=past`, unknown `view`) and detail for an active child, and prove non-GET methods return 405. — e23392c
- [x] 2.2 The access matrix covers both routes for anonymous (login redirect), parent, inactive child, inactive family, and unconfigured user (403). — e23392c
- [x] 2.3 Detail returns 404 with identical bodies for an unassigned entry, a sibling's entry, a foreign-family entry, and a nonexistent ID, and sentinel content from those entries never appears in any child response. — e23392c
- [x] 2.4 List responses contain the child's sentinel entries and none of the excluded ones. — e23392c
- [x] 2.5 Account page tests show "Moje wpisy" for a child and not for a parent, and "Dodaj wpis" for a parent and not for a child. — e23392c
- [x] 2.6 Rendered child pages contain no links or forms to capture, edit, or delete. — e23392c
- [x] 2.7 Relevant tests pass: `uv run python manage.py test entries.tests family_access`. — e23392c

#### Manual

- [x] 2.8 Signed in as a child at phone width: account → "Moje wpisy" → switch to "Minione" → open a row → back returns to the same mode. (confirmed by user 2026-09-28) — e23392c
- [x] 2.9 Long content, undated entries, missing times, and both empty states remain readable. (confirmed by user 2026-09-28) — e23392c

### Phase 3: Kitchen Sink and Screenshot Gate

#### Automated

- [x] 3.1 Gallery tests prove DEBUG gating (404 when off), the anonymous redirect, 403 for a signed-in user without an active membership, the expected `data-kitchen-state` markers for all six states, and zero `Entry` queries or writes.
- [x] 3.2 Full tests pass: `uv run python manage.py test`.
- [x] 3.3 Django checks pass: `uv run python manage.py check`.
- [x] 3.4 Migration drift check passes: `uv run python manage.py makemigrations --check --dry-run`.

#### Manual

- [x] 3.5 The gallery screenshot at 360px shows all six states legibly, with no horizontal scroll, token accent colours, Polish copy throughout, and the current mode visibly marked. (confirmed by user 2026-09-28)
- [x] 3.6 The screenshot is committed under `context/changes/child-assigned-entry-view/screenshots/`. (confirmed by user 2026-09-28)
- [x] 3.7 In Chrome on Android, a real child account sees only its own entries, and a hand-typed detail URL for a sibling's entry shows 404. (confirmed by user 2026-09-28)
