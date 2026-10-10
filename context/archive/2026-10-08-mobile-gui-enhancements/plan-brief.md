# Mobile GUI Enhancements — Plan Brief

> Full plan: `context/changes/mobile-gui-enhancements/plan.md`

## What & Why

Improve FamilyNotes on phones by keeping entry lists current after app resume, using the available landscape width for a two-week calendar, and making relative day headings unambiguous.

## Starting Point

The application already renders fresh server-side lists, a 14-day parent calendar, and privacy-safe network-only navigation. It lacks resume handling, limits seven-column layout to desktop widths, and omits weekday names from relative headings.

## Desired End State

Parent and child lists refresh once after genuine resume, while offline content remains visible until connectivity returns. The parent calendar shows seven days per row in phone landscape, and grouped relative headings read like `Dziś, czwartek 8 października`.

## Key Decisions Made

| Decision | Choice | Why |
| --- | --- | --- |
| Refresh trigger | Genuine resume and bfcache restoration | Cold launches are already fresh |
| Refresh scope | Parent and child lists only | Forms must retain unsaved input |
| Offline behavior | Keep content and retry online | Previously visible data remains useful |
| Navigation | Preserve the current URL | Retains mode and calendar window |
| Landscape scope | Parent calendar only | Child view is not a 14-day calendar |
| Date scope | Grouped headings in both role views | Adds context without altering other date displays |
| Date wording | `Dziś, czwartek 8 października` | Matches the requested Polish presentation |

## Scope

**In scope:** list-page resume refresh, offline retry, parent phone-landscape calendar from `36rem` width, parent and child relative headings, child heading/list relationships, and relevant accessibility/regression coverage.

**Out of scope:** form-page refresh, child calendar redesign, service-worker family-data caching, orientation locking, non-heading date changes, models, APIs, and deployment configuration.

## Architecture / Approach

Existing server-rendered routes remain authoritative. Python formatters produce heading text, CSS controls the orientation-specific parent layout, and a list-scoped lifecycle script performs guarded same-URL reloads. The service-worker privacy contract is unchanged.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Relative headings | Explicit Polish grouped headings | Locale and cross-year consistency |
| 2. Landscape calendar | Seven columns on landscape phones | Narrow-column reflow |
| 3. Resume refresh | Safe list freshness | Duplicate lifecycle events |
| 4. Verification | Integrated browser evidence | Device-specific PWA behavior |

**Prerequisites:** Existing parent calendar, PWA, and accessibility contracts remain available.

**Estimated effort:** Approximately 2–3 implementation sessions across four phases.

## Open Risks & Assumptions

- `orientation: landscape`, `min-width: 36rem`, and `max-height: 32rem` define the phone-landscape boundary; `568×320` remains one column while `667×375` and wider representative phones use seven.
- Browser lifecycle events can arrive close together, so the implementation must explicitly suppress duplicate reloads.
- Lifecycle behavior is verified manually because Django response tests cannot execute browser suspension, bfcache, connectivity, or reload-count behavior.

## Success Criteria (Summary)

- Both role lists show explicit relative grouped headings.
- The parent calendar shows seven chronological days per landscape row without horizontal scrolling.
- Resumed lists refresh once online and preserve useful visible content offline.
