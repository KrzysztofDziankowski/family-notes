# Manual verification

Date: 2026-10-05

## Browser (browser agent B)

Environment: headless Chromium (Playwright 1.x, `/usr/bin/chromium-browser`) against `runserver` (DEBUG on, own SQLite DB seeded with `scripts/dev/seed_test_family.py`), live classification (`gpt-5.4-nano`). Password logins only; no real Google.

- 2.5 PASS — at 360 px as Ewa, upcoming: h2 Kasia → Tymek → Ewa → Ola → Cała rodzina, each with h3 "Z datą"/"Bez daty"; past (after adding past entries for Tymek, Ewa and family): h2 Kasia → Tymek → Ewa → Cała rodzina. No horizontal overflow; hierarchy reads clearly (`screenshots/phone-real-list-upcoming.png`, `phone-real-list-past.png`).
- 2.6 PASS — `PNA-Ola-…` re-assigned from Ola to Tymek in "Edytuj": it now appears under the Tymek group and the Ola group disappears (it was Ola's only upcoming row) (`phone-after-reassign.png`); then reassigned back.
- 2.7 PASS — `screenshots/phone-gallery-grouped-upcoming.png` (Kasia, Tymek, Marta, Cała rodzina) and `phone-gallery-grouped-past.png` (one "Cała rodzina" group, as the plan's gallery contract says).

## Layout change 2026-10-05 (owner request)

Owner request: "entries on parent view should be grouped by date (as on child view) and in each day by assigned person". This replaces the assignee-first layout checked above, so plan rows 2.5 and 2.7 are unticked until re-checked against the new layout.

New layout (both modes): one `<section data-day-group="YYYY-MM-DD|undated">` per day with the child view's `<h2 class="fn-day-heading">` (Dziś / Jutro / weekday / date); upcoming ends with a "Bez daty" day for undated entries, past shows the newest day first. Inside a day, `<section data-assignee-group="member-<pk>|family">` sub-groups with `<h3 class="fn-manage-subsection-title">` in the S-08 order: children (by pk, inactive with suffix), parents (by pk), then "Cała rodzina". Rows keep time order, hide the date and the assignee (only the time shows). The "Z datą" / "Bez daty" section labels are gone.

Screenshot check (headless Chromium, 360 px, `runserver` with DEBUG on the browser-b SQLite DB, logged in as `test_rodzic`):

- `screenshots/day-then-assignee-upcoming.png` — h1 Wpisy rodziny → h2 Dziś (h3 Kasia) → Jutro (Tymek) → Środa (Kasia) → Piątek (Ola, Cała rodzina) → Sobota (Kasia) → Bez daty (Kasia, Ewa, Ola). Child before parent before family in each day; rows show only the time.
- `screenshots/day-then-assignee-past.png` — h2 Sobota (h3 Tymek, Ewa, Cała rodzina) → Piątek (Kasia): newest day first, child → parent → family.
- Both pages: `scrollWidth` 360 (no horizontal overflow); heading hierarchy h1 → h2 → h3 without skips.

Still to re-check by the owner: 2.5 on a real phone and 2.7 against the DEBUG gallery (`/entries/_states/`, now with Kasia, Marta and "Cała rodzina" under "Dziś").
