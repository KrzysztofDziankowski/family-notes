---
change_id: child-calendar-view
title: Shared 14-day calendar for parent and child, with date navigation and child filters
status: implementing
created: 2026-10-10
updated: 2026-10-10
archived_at: null
---

## Notes

Child sees the same 14-day calendar view as the parent, with only their own entries

Decisions already made (2026-10-10, during weekend-day-header-colours):
- No per-person subheading in the child's day boxes (the child sees only their own entries).
- Lucky-number entries are shown in the child calendar (corrected 2026-10-10: both lists hide them
  today; the owner chose to show them to the child; the parent calendar keeps hiding them).
- Scope stays as today: only entries assigned to the child (no "Cała rodzina", no siblings).

Scope update (2026-10-10, from the user):
- Remove the "Nadchodzące" / "Minione" mode buttons. Replace them with "Wcześniejsze" / "Dzisiaj" /
  "Następne": "Wcześniejsze" shows the previous 2 weeks, "Następne" the next 2 weeks, and
  "Dzisiaj" resets the view to the window starting today.
- Parent view: add one filter button per child to show only that child's entries
  (refined in /10x-plan: plus "Ogólne" entries, one child at a time, "Wszyscy" by default).
- Rename the "Cała rodzina" label to "Ogólne". Today it appears in the parent assignee
  subheading (entries/views.py FAMILY_GROUP_HEADING), the assignee select empty label
  (entries/forms.py), the entry row, the detail page, the saved panel and the states gallery.

Open questions: resolved during /10x-plan on 2026-10-10. See plan-brief.md, Key Decisions.
