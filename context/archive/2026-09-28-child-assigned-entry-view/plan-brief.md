# Child Assigned Entry View — Plan Brief

> Full plan: `context/changes/child-assigned-entry-view/plan.md`

## What & Why

Roadmap slice S-03 (FR-007, FR-008) gives each child a read-only personal view of the entries assigned to them, so family information a parent captured actually reaches the child. The privacy rule is strict: a child sees only entries assigned to them, and nothing else in the family is visible or guessable through this view.

## Starting Point

S-01 saves `Entry` rows with an optional `assigned_member` (where `null` means "Cała rodzina"). F-01 provides `can_read_assigned_child`, which is unused so far. Children can sign in but land on `/account/` with nothing to do. S-02 (parent CRUD) is planned but not built, and its plan already defines the list ordering this slice needs.

## Desired End State

A child opens `/account/`, taps "Moje wpisy", and sees their upcoming entries (dated from today, then undated), can switch to past entries, and can open any row for full detail. Parents, inactive or unconfigured members and anonymous users are denied. A sibling's entry, a family-wide entry, a foreign entry and a nonexistent ID all return the same 404.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) |
| --- | --- | --- |
| Family-wide (unassigned) entries | Not shown to children | FR-007 and Access Control say "only entries assigned to that child", and parent-private notes must not leak. |
| Time organization | Mirror S-02: upcoming (dated today onward, then undated) plus a past toggle | One ordering contract for both views. |
| Per-entry detail | List plus detail page `/entries/mine/<pk>/` | Keeps rows compact on a phone; the ID route is defended by an identical-404 matrix. |
| Landing and audience | "Moje wpisy" link on `/account/`; children only (parents get 403) | Mirrors the parent's "Dodaj wpis" and leaves the login flow unchanged. |
| Overlap with S-02 | S-03 builds the shared `entries/listing.py` and `_entry_row.html`; S-02 reuses them (pointer added to S-02's `plan.md`) | S-03 ships independently with no duplicated ordering logic. |
| Lucky-number notes | Hidden from both list modes (detail still resolves) | They are short-lived and would otherwise pile up as undated noise. |
| Undated grade notes | Effective date = local day of `created_at`, computed in the listing only | Grades sort by when they arrived and move to past the next day, with no data write. |
| Authorization gate | `can_read_assigned_child(membership, membership)` plus a family/assignee-filtered queryset | Reuses F-01's helper; foreign IDs are unreachable by construction. |
| Visual gate | DEBUG-only synthetic child-states page, screenshotted at 360px | Same pattern as S-01; the repo has no screenshot test harness. |

## Scope

**In scope:**
- Shared list partition/ordering helper and entry-row partial
- Child-scoped read service
- Child list (upcoming/past) and detail routes
- "Moje wpisy" link on the account page
- Full access-matrix tests
- DEBUG kitchen sink and a 360px screenshot
- Lucky-number hiding and grade effective-date rule in the shared helper

**Out of scope:**
- Family-wide entries for children
- Any child write action
- Parent "preview as child"
- Login redirect change
- Parent index or CRUD (S-02)
- Pagination or search
- Schema migration
- New CSS or JS dependencies

## Architecture / Approach

The views follow the existing function-view pattern: `login_required`, then an authorization check that raises `PermissionDenied`. Every read goes through `child_entries(user)`, which checks that the caller is an active child and filters by family and `assigned_member = self`. The list passes that queryset to the role-agnostic `listing` helper, which applies explicit null-last time ordering and uses `timezone.localdate()` as "today". Detail resolves `pk` only inside the same queryset, so anything the child may not read is a plain 404. Templates use Pico and existing `tokens.css` classes only.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Shared list contract and child-scoped query | `listing.py` (with lucky-number/grade rules), `_entry_row.html`, `child_entries` | Ordering drift from S-02's spec; null ordering and the `created_at` day annotation differ between SQLite and PostgreSQL |
| 2. Child routes and UI | `/entries/mine/`, `/entries/mine/<pk>/`, account link, access matrix | A 404 that differs between foreign and missing IDs leaks existence |
| 3. Kitchen sink and screenshot gate | DEBUG child-states page, 360px screenshot, full checks | Synthetic states accidentally touching the DB |

**Prerequisites:** F-01 and S-01 are done (archived). A local child account is needed for the manual flow.
**Estimated effort:** about 1–2 sessions across 3 small phases.

## Open Risks & Assumptions

- S-02 is implemented after S-03 and adopts the shared helper. If S-02 lands first with its own ordering, reconcile the two in whichever lands second.
- Children miss family-wide information (for example general teacher messages) until a later slice decides otherwise. This follows the literal FR-007.
- Other undated entries (for example late-arrival notes and undated manual notes) never move to past. Once S-05 lands, their tail in "Nadchodzące" keeps growing. This is an open risk to revisit after S-05.

## Success Criteria (Summary)

- A child sees exactly their own assigned entries, correctly ordered, in upcoming and past, with a readable detail page on a phone.
- No other family member's, family-wide, or foreign entry is visible or distinguishable from a missing one.
- The kitchen-sink screenshot at 360px shows every child-view state legibly in Polish.
