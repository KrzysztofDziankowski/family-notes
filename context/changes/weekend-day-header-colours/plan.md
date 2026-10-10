# Weekend Day Header Colours Implementation Plan

## Overview

Give Saturday and Sunday day headings a pale red background in the parent family calendar and
the child entry list, so weekend days stand out at a glance. Saturday and Sunday share one
weekend colour; weekdays keep their current plain heading.

## Current State Analysis

- The parent calendar renders fourteen day boxes; each heading is
  `parent_day_heading(day, today)` (`entries/listing.py:169`), e.g. "Dziś, sobota 10 października",
  built into `days` by `_index_days` (`entries/views.py:983`) and rendered as
  `<section class="fn-calendar-day"> <h2 class="fn-day-heading">` in
  `entries/templates/entries/_manage_list.html:20-21`.
- The child list groups entries by day via `group_by_day` / `_child_list_context`
  (`entries/views.py:1332`) and renders `<h2 class="fn-day-heading" id="…">` in
  `entries/templates/entries/_child_list_body.html:12`. The undated group ("Bez daty") uses the
  same heading class.
- `.fn-day-heading` is styled in `family_notes/static/css/tokens.css:403`; colours come only from
  `--fn-color-*` tokens (accessibility checklist item 8), and every text/background pair is
  asserted ≥ 4.5:1 in `family_notes/test_tokens_contrast.py`.
- Nothing highlights any particular day today.

## Desired End State

Every Saturday and Sunday heading in the parent calendar (including empty weekend days) and in the
child upcoming/past lists shows a pale red background strip behind the existing dark heading text.
Weekday and "Bez daty" headings are unchanged. The new token passes the contrast suite.

### Key Discoveries:

- Several tests match the literal markup `<h2 class="fn-day-heading">` with no extra attributes
  (`entries/tests/test_manage_views.py:33`, `entries/tests/test_manage_states.py:62,127,183`), so
  the parent calendar must mark the weekend on the day `<section>`, not on the `<h2>`.
- Child tests match `<h2 class="fn-day-heading" id="([^"]+)"` (`entries/tests/test_child_states_view.py:127`,
  `entries/tests/test_child_views.py:253`) and `<h2 class="fn-day-heading"[^>]*>`, so a child-side
  marker must be an attribute placed **after** `id`.
- The DEBUG state galleries reuse `_index_days` and `_child_list_context`
  (`entries/views.py:1458`), so they pick up the flag for free.
- The parent day box already uses a BEM modifier (`fn-calendar-day--empty`), the pattern to follow.

## What We're NOT Doing

- No distinct colours for Saturday vs Sunday (one shared weekend colour, by decision).
- No public holidays (e.g. 11 listopada) — weekend means `weekday() >= 5` only.
- No "today" highlight or other day emphasis.
- No change to heading text, aria labels, or the entry rows.
- No Playwright E2E test: the marker is server-rendered markup fully covered by Django view tests.
- No dark theme (the app is light-only).

## Implementation Approach

Compute the weekend flag on the server next to the heading, expose it in each day/group context
dict, mark the markup, then style both markers with one CSS rule backed by a new token.

## Phase 1: Weekend flag and markup

### Overview

Expose a weekend flag for every dated day heading and mark the weekend in both templates, with
tests, before any visual change.

### Changes Required:

#### 1. Weekend helper

**File**: `entries/listing.py`

**Intent**: One source of truth for "is this calendar day a weekend day", shared by parent and child contexts.

**Contract**: `is_weekend(day: datetime.date) -> bool`, true for Saturday and Sunday (`day.weekday() >= 5`).

#### 2. Context flags

**File**: `entries/views.py`

**Intent**: Carry the flag to the templates.

**Contract**: each dict in `_index_days` gains `'is_weekend': is_weekend(day)`; each dated group in
`_child_list_context` gains `'is_weekend'` from the group's `effective_date`; the undated group
gets `'is_weekend': False`. Update the parameter comments in both templates to name the new key.

#### 3. Parent calendar markup

**File**: `entries/templates/entries/_manage_list.html`

**Intent**: Mark weekend day boxes without touching the `<h2>` markup tests rely on.

**Contract**: the day `<section>` gets the extra class `fn-calendar-day--weekend` when
`day.is_weekend`; it can combine with `fn-calendar-day--empty`. `<h2 class="fn-day-heading">` stays byte-identical.

#### 4. Child list markup

**File**: `entries/templates/entries/_child_list_body.html`

**Intent**: Mark weekend headings in the child list, which has no per-day wrapper.

**Contract**: `<h2 class="fn-day-heading" id="…"{% if group.is_weekend %} data-weekend{% endif %}>` —
the attribute comes after `id` so the existing id-capturing regexes still match.

#### 5. Tests

**Files**: `entries/tests/test_entry_listing.py`, `entries/tests/test_manage_views.py`, `entries/tests/test_child_views.py`

**Intent**: Pin the flag and the markup.

**Contract**: `is_weekend` is false for Friday and Monday and true for Saturday and Sunday; the
parent index marks exactly the Saturday/Sunday `data-day-group` sections with
`fn-calendar-day--weekend` (including an empty weekend day); the child list puts `data-weekend` on
weekend headings only, never on weekday or "Bez daty" headings.

### Success Criteria:

#### Automated Verification:

- New and existing entries tests pass: `uv run python manage.py test entries`
- Django checks pass: `uv run python manage.py check`
- No migrations needed: `uv run python manage.py makemigrations --check --dry-run`

#### Manual Verification:

- Page source of the parent calendar shows `fn-calendar-day--weekend` on Saturday and Sunday boxes only

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 2: Weekend token, CSS and contrast

### Overview

Add the weekend background token and style both markers, guarded by the contrast suite.

### Changes Required:

#### 1. Token

**File**: `family_notes/static/css/tokens.css`

**Intent**: A pale red tint that reads as "weekend", not as an error.

**Contract**: new `--fn-color-weekend-bg` hex token in the first `:root` block (6-digit hex so
`root_tokens` parses it), distinct from `--fn-color-danger-bg`; document its origin in the
"Source of values" comment.

#### 2. Heading rule

**File**: `family_notes/static/css/tokens.css`

**Intent**: Weekend headings get a background strip; text colour stays `--fn-color-text-strong`.

**Contract**: one rule for `.fn-calendar-day--weekend .fn-day-heading, .fn-day-heading[data-weekend]`
setting `background: var(--fn-color-weekend-bg)`, small padding (`--fn-space-1` / `--fn-space-2`)
and `border-radius: var(--fn-radius)`, placed after the base `.fn-day-heading` rule. It must keep
working inside the seven-column and landscape media queries (no overflow in narrow columns).

#### 3. Contrast pair

**File**: `family_notes/test_tokens_contrast.py`

**Intent**: Guard the new text/background pair.

**Contract**: add `('text-strong', 'weekend-bg')` to `TEXT_PAIRS` with a comment naming the weekend heading.

### Success Criteria:

#### Automated Verification:

- Contrast suite passes, including the new pair: `uv run python manage.py test family_notes.test_tokens_contrast`
- Full test suite passes: `uv run python manage.py test`

#### Manual Verification:

- Parent calendar: Saturday and Sunday headings show the pale red strip on a phone (one column), a landscape phone and a wide screen (seven columns), including empty weekend days
- Child upcoming and past lists: weekend headings show the strip; weekday and "Bez daty" headings do not
- Strip does not look like an error panel and text stays readable

---

## Testing Strategy

### Unit Tests:

- `is_weekend` for Friday, Saturday, Sunday, Monday.

### Integration Tests:

- Parent index view: weekend modifier on exactly the weekend `data-day-group` sections, including an empty one.
- Child list view: `data-weekend` only on weekend headings; never on "Bez daty".
- Token contrast pair `text-strong` on `weekend-bg` ≥ 4.5:1.

### Manual Testing Steps:

1. Open the parent calendar in portrait, landscape-phone and wide layouts; confirm the weekend strips.
2. Sign in as a child; check the upcoming and past lists.

## Performance Considerations

None — one `weekday()` call per day.

## Migration Notes

None.

## References

- Change notes: `context/changes/weekend-day-header-colours/change.md`
- Accessibility checklist: `context/foundation/accessibility.md` (item 8, tokens and contrast)
- Similar modifier: `fn-calendar-day--empty` in `entries/templates/entries/_manage_list.html:20`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Weekend flag and markup

#### Automated

- [x] 1.1 New and existing entries tests pass: `uv run python manage.py test entries`
- [x] 1.2 Django checks pass: `uv run python manage.py check`
- [x] 1.3 No migrations needed: `uv run python manage.py makemigrations --check --dry-run`

#### Manual

- [ ] 1.4 Page source of the parent calendar shows `fn-calendar-day--weekend` on Saturday and Sunday boxes only

### Phase 2: Weekend token, CSS and contrast

#### Automated

- [ ] 2.1 Contrast suite passes, including the new pair: `uv run python manage.py test family_notes.test_tokens_contrast`
- [ ] 2.2 Full test suite passes: `uv run python manage.py test`

#### Manual

- [ ] 2.3 Parent calendar: Saturday and Sunday headings show the pale red strip on a phone (one column), a landscape phone and a wide screen (seven columns), including empty weekend days
- [ ] 2.4 Child upcoming and past lists: weekend headings show the strip; weekday and "Bez daty" headings do not
- [ ] 2.5 Strip does not look like an error panel and text stays readable
