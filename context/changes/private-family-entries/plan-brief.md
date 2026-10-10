# Private Family Entries and Child Entry Creation — Plan Brief

> Full plan: `context/changes/private-family-entries/plan.md`

## What & Why

Family members should be able to keep selected entries visible only to the person who created them. Children should also be able to add their own tasks, events, and notes through the app's natural-language capture flow, while assignment and privacy rules remain enforced on the server.

## Starting Point

Entries record a nullable creator, but have no privacy flag. Parents can classify and manage entries; children can only read entries assigned to themselves. Parent and child calendars and the automation API use separate family-scoped read paths.

## Desired End State

Private entries are visible only to their creator in lists, direct links, and API reads. Children can classify and confirm entries that are always assigned to themselves, choose privacy during confirmation, and change their own privacy setting later. Both calendars provide All, Private, and Not private filters over entries the viewer is allowed to see.

## Key Decisions Made

| Decision | Choice | Why | Source |
| --- | --- | --- | --- |
| Private visibility | Only the recorded creator can see a private entry; apply this to direct routes and API reads. | The privacy rule must hold across every read path, not just calendar display. | Plan |
| Child creation flow | Reuse natural-language classification for tasks, events, and notes; force assignment to the active child. | It matches the existing capture experience while preserving self-only assignment. | Plan |
| Private filters | All / Private / Not private on parent and child calendars. | Both roles can filter the entries they are already authorized to see. | Plan |
| Defaults and creatorless entries | New child entries default public; existing and creatorless automated entries remain public. | Preserve family sharing unless a human creator chooses privacy. | Plan |
| Changing privacy later | Allow the creator to change privacy after saving; children still cannot edit or delete entry fields. | A missed or changed privacy choice can be corrected without widening child permissions. | Plan |

## Scope

**In scope:**

- Add a non-null privacy flag, default false, and enforce creator-only visibility in service queries, direct routes, and automation API reads.
- Enable child natural-language capture, follow-up, correction, and confirmation, with server-enforced assignment and authorship.
- Add privacy selection at confirmation, creator-only privacy changes after saving, and calendar filters for both roles.
- Update the PRD, access tests, UI accessibility tests, and manual accessibility record.

**Out of scope:**

- Child assignment to another member, content edits, or deletion.
- Parent access to private entries created by another person.
- Privatizing creatorless automated entries or returning private entries through automation.
- Analytics, secondary text storage, new integrations, or family/role administration.

## Architecture / Approach

The `Entry` model holds the privacy flag and its existing `created_by` membership remains the ownership key. Family-scoped services filter private rows before views render them; a narrow creator-authorized service changes only privacy. Child capture reuses the existing classification journey but restricts candidates, assignment, and creator to the request family membership. Parent and child calendars add server-enforced filter state that survives navigation and detail links.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Private Entry Model and Access Rules | Privacy storage and creator-only read enforcement across views and API. | A missed direct or API read path could leak private content. |
| 2. Child Natural-Language Capture | Child self-assigned capture from text through confirmation. | Existing classification transitions are parent-only and must remain self-scoped. |
| 3. Privacy Controls and Calendar Filters | Confirmation and creator controls plus filters on both calendars. | Filter state must never replace query-level access enforcement. |

**Prerequisites:** Existing Django entry, family-context, classification, and calendar flows; no new service dependency.
**Estimated effort:** About 3 implementation sessions across 3 phases, including access, classification, UI, and accessibility verification.

## Open Risks & Assumptions

- `created_by` is a family membership and can be null; creatorless automated entries therefore remain public and cannot be privatized in this change.
- An entry assigned to a child but made private by a parent is visible only to the parent creator, consistent with the creator-only rule.
- Automation API consumers will no longer receive private entries, including private entries created by the token owner's signed-in membership.
- The classification text continues to be used only to produce and save requested entries, in line with the existing PRD boundary.

## Success Criteria (Summary)

- Non-creators cannot read private content through a calendar, direct URL, edit route, or automation API; public access remains unchanged.
- A child can create tasks, events, and notes via text capture, always assigned to themselves, and can change only the privacy of their own saved entries.
- All / Private / Not private filters work on both calendars, preserve navigation state, and pass the project's automated and manual accessibility checks.
