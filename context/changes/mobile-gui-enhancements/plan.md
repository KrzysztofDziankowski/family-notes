# Mobile GUI Enhancements Implementation Plan

## Overview

Improve the phone experience by refreshing entry lists when the application resumes, showing the parent's 14-day calendar as two seven-day rows in phone landscape, and expanding relative day headings with weekday and date information.

## Current State Analysis

- Cold PWA launches already navigate to `/` and fetch current server-rendered data. Staleness occurs when an existing page resumes from background or bfcache.
- The service worker never caches family pages; this privacy contract remains unchanged.
- The parent calendar already renders 14 chronological days but uses seven columns only above `80rem`.
- Parent and child headings use separate formatters. Relative headings currently omit the weekday in both views.

## Desired End State

- Resuming a parent or child list online refreshes that same URL once.
- Resuming offline preserves visible content and refreshes after connectivity returns.
- A phone in landscape displays the parent calendar as two rows of seven days without horizontal page scrolling.
- Relative grouped headings in both role views use formats such as `Dziś, czwartek 8 października`.
- Forms, details, confirmation panels, and ordinary row-level dates retain their current formatting.

### Key Discoveries

- Parent list queries already recompute the local day and validate stale windows in `entries/views.py:903-1050`.
- The 14-day calendar and seven-column desktop layout already exist in `entries/templates/entries/_manage_list.html:1-36` and `family_notes/static/css/tokens.css:409-489`.
- Navigations are network-only and never enter the service-worker cache in `family_notes/templates/pwa/sw.js:52-71`.

## What We're NOT Doing

- No refreshes on capture, review, edit, authentication, or detail pages.
- No refresh on every window focus event.
- No redesign of the child list into a calendar.
- No service-worker caching of family content.
- No orientation lock, API, model, migration, or deployment change.
- No expansion of relative wording outside grouped list headings.

## Implementation Approach

Extend the existing parent and child heading formatters only for relative days, add a phone-landscape media rule for the existing parent calendar, and load a small lifecycle script only on the two list pages. The server-rendered routes remain authoritative and the service worker's privacy boundary remains unchanged.

## Critical Implementation Details

A cold launch must not cause a redundant second request. Refresh only after a hidden-to-visible transition or persisted `pageshow`; deduplicate overlapping lifecycle events. If that transition occurs offline, keep the current document and record one pending refresh for the next `online` event.

## Phase 1: Relative Day Headings

### Overview

Make grouped headings explicit in both role views without changing other date displays.

### Changes Required

#### 1. Heading formatting

**File**: `entries/listing.py`

**Intent**: Add weekday and full calendar date to `Dziś`, `Jutro`, and `Wczoraj` headings.

**Contract**: Relative headings use `<relative>, <weekday> <day> <month>`, adding the year when it differs from the reference year. Parent and child formatters share this relative-date invariant. Existing non-relative behavior remains unchanged: the parent calendar retains full dates, while the child list retains weekday-only nearby labels and full dates farther away. Django's active Polish locale remains the source of names.

#### 2. Rendering expectations

**File**: `entries/tests/`

**Intent**: Update parent/child list, state-gallery, and accessibility expectations affected by the heading text.

**Contract**: Parent calendar list labels continue to contain the complete visible heading and assignee name. Each child day heading gains a unique ID, and its entry list references that visible heading with `aria-labelledby`; child tests assert both the relationship and chronological heading order.

### Success Criteria

#### Automated Verification

- Formatter and rendering tests cover expanded relative headings
- Heading accessibility tests pass

#### Manual Verification

- Polish headings and screen-reader labels are verified

**Implementation Note**: Pause after automated checks for manual confirmation before proceeding.

---

## Phase 2: Seven-Day Phone Landscape Calendar

### Overview

Render the existing parent calendar as two chronological rows of seven days on a landscape phone.

### Changes Required

#### 1. Responsive calendar contract

**File**: `family_notes/static/css/tokens.css`

**Intent**: Add a landscape-phone layout while preserving portrait reflow and the existing wide-screen layout.

**Contract**: Base and phone portrait remain one column. Landscape viewports with `orientation: landscape`, a minimum width of `36rem`, and a maximum height of `32rem` use `repeat(7, minmax(0, 1fr))`; narrower landscape viewports retain one column, and the existing `80rem` desktop rule remains. Landscape phone cells reuse compact calendar typography and padding. Existing width, wrapping, token, focus, and unlocked-orientation invariants remain intact, with no horizontal document scrolling.

#### 2. CSS regression contract

**File**: `family_notes/test_tokens_rules.py`

**Intent**: Update structural tests so the deliberate phone-landscape and desktop calendar rules are independently verified.

**Contract**: Tests distinguish base, phone-landscape, and wide-screen rules rather than assuming exactly one media block contains `.fn-calendar`.

### Success Criteria

#### Automated Verification

- Responsive CSS contracts pass
- Calendar structure and accessibility tests pass

#### Manual Verification

- Portrait and landscape reflow is verified on representative phone viewports

**Implementation Note**: Pause after automated checks for manual confirmation before proceeding.

---

## Phase 3: Refresh Lists on Resume

### Overview

Refresh current list content after a genuine app or tab resume without risking form input.

### Changes Required

#### 1. Lifecycle script

**File**: `family_notes/static/js/`

**Intent**: Introduce a dedicated client-side lifecycle module for list freshness.

**Contract**: Initial load and ordinary focus do not reload. A hidden-to-visible transition or persisted `pageshow` reloads the current URL once when online, with overlapping signals deduplicated. Offline resume keeps the document and marks one pending refresh; the next `online` event performs it. Reload preserves the full current URL, including family context. The module uses no browser storage or family-data caching.

#### 2. Template wiring

**File**: `entries/templates/entries/manage_index.html`, `entries/templates/entries/child_list.html`

**Intent**: Load the lifecycle module only on the parent and child list pages through the existing script extension point.

**Contract**: Capture, review, edit, authentication, account, and detail pages do not load or activate resume refresh behavior.

### Success Criteria

#### Automated Verification

- Static-file and template-wiring contracts pass
- PWA privacy and caching contracts remain green

#### Manual Verification

- Cold launch, online resume, offline resume, and form preservation are verified

**Implementation Note**: Pause after automated checks for manual confirmation before proceeding.

---

## Phase 4: Integrated Verification

### Overview

Validate the three behaviors together on browser-sized and installed-PWA flows.

### Changes Required

#### 1. Cross-feature verification

**File**: `entries/tests/`, `family_notes/test_pwa.py`, `family_notes/test_tokens_rules.py`, `family_notes/test_accessibility.py`, and change verification artifacts

**Intent**: Demonstrate that formatting, reflow, refresh lifecycle, privacy, and accessibility contracts work together.

**Contract**: Django tests verify static-file existence, page-specific wiring, formatting, CSS, PWA privacy, and accessibility structure. Browser lifecycle behavior remains in the manual Android/PWA matrix; no new test framework is introduced.

### Success Criteria

#### Automated Verification

- Relevant Django tests and system checks pass
- Migration dry run confirms no model changes

#### Manual Verification

- Android PWA, orientation, and accessibility matrix is completed

**Implementation Note**: Complete the manual matrix before treating the change as implemented.

## Testing Strategy

### Unit Tests

- Verify exact Polish output for today, tomorrow, yesterday, same-year dates, cross-year dates, and locale override.
- Verify static-file existence and that only parent and child list templates load the lifecycle script.

### Integration Tests

- Verify both list pages receive the script while form workflows do not.
- Verify 14 chronological parent day sections, accessible labels, responsive CSS contracts, and unchanged PWA cache restrictions.

### Manual Testing Steps

1. Confirm a cold launch performs only the normal navigation.
2. Resume each list after changing data elsewhere and confirm a single same-URL refresh, including bfcache restoration and overlapping lifecycle signals.
3. Resume offline, confirm content stays visible, reconnect, and confirm one refresh attempt.
4. Check `320px` portrait, confirm `568×320` remains one column, and confirm `667×375` and `844×390` use seven columns.
5. Complete keyboard, zoom, screen-reader, and axe checks from the accessibility matrix.

## Performance Considerations

Each genuine resume performs at most one normal list GET. No polling, partial-fetch API, background interval, or additional browser storage is introduced.

## Migration Notes

No database, data, API, service-worker cache-version, or deployment migration is required.

## References

- Heading and grouping contract: `entries/listing.py:128-170`
- Calendar contract: `family_notes/static/css/tokens.css:409-489`
- PWA privacy contract: `family_notes/templates/pwa/sw.js:52-71`
- Prior calendar plan: `context/changes/parent-entries-calendar-layout/plan.md`
- Accessibility requirements: `context/foundation/accessibility.md`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles.

### Phase 1: Relative Day Headings

#### Automated

- [x] 1.1 Formatter and rendering tests cover expanded relative headings — 30016cd
- [x] 1.2 Heading accessibility tests pass — 30016cd

#### Manual

- [ ] 1.3 Polish headings and screen-reader labels are verified

### Phase 2: Seven-Day Phone Landscape Calendar

#### Automated

- [x] 2.1 Responsive CSS contracts pass
- [x] 2.2 Calendar structure and accessibility tests pass

#### Manual

- [ ] 2.3 Portrait and landscape reflow is verified on representative phone viewports

### Phase 3: Refresh Lists on Resume

#### Automated

- [ ] 3.1 Static-file and template-wiring contracts pass
- [ ] 3.2 PWA privacy and caching contracts remain green

#### Manual

- [ ] 3.3 Cold launch, online resume, offline resume, and form preservation are verified

### Phase 4: Integrated Verification

#### Automated

- [ ] 4.1 Relevant Django tests and system checks pass
- [ ] 4.2 Migration dry run confirms no model changes

#### Manual

- [ ] 4.3 Android PWA, orientation, and accessibility matrix is completed
