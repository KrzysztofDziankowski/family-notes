# Manual verification: mobile-gui-enhancements

- **Date**: 2026-10-08
- **Build**: branch `feature/mobile-gui-enhancements`, Django dev server (`DJANGO_DEBUG=True`, SQLite), seeded with `scripts/dev/seed_test_family.py`
- **Browser**: Chromium via `playwright-cli`; Android emulated as Pixel 7 (mobile UA, touch, DPR 2.625)
- **Not covered**: a physical Android phone with the PWA installed, and a real screen reader (TalkBack/NVDA). Accessible names were checked through the accessibility tree and axe instead.

## 1. Relative day headings

| Check | Result |
|---|---|
| Parent calendar, upcoming (2026-10-08) | `Dziś, czwartek 8 października`, `Jutro, piątek 9 października`, then `Sobota, 10 października` … |
| Parent calendar, past | last day `Wczoraj, środa 7 października` |
| Parent list labels | `Dziś, czwartek 8 października, Kasia` (heading + assignee) |
| Child list, upcoming | `Dziś, czwartek 8 października`, nearby days keep weekday-only (`Sobota`, `Wtorek`) |
| Child lists' accessible names | every `list` is found by `getByRole('list', { name: <visible heading> })` |

## 2. Landscape calendar

| Viewport | Columns | Horizontal scroll |
|---|---|---|
| 320×568 portrait | 1 | no |
| 375×667 portrait | 1 | no |
| 568×320 landscape (below the 36rem floor) | 1 | no |
| 667×375 landscape | 7 (2 rows) | no |
| 844×390 landscape | 7 (2 rows) | no |
| 863×360 Pixel 7 landscape (emulated) | 7 | no |
| 412×839 Pixel 7 portrait (emulated) | 1 | no |
| 1024×768 | 1 | no |
| 1280×800 | 7 | no |

Finding fixed during verification (commit `c148c52`): at 667×375 Pico's 510px `.container` cap left
about 64px per column, so words broke mid-syllable. On a landscape phone, the calendar page's
header and main now use the full width less an 8px gutter, with tighter cell padding. The
longest bold word, `października`, can still wrap inside the word at 667px. `overflow-wrap: anywhere`
allows this, and there is no overflow.

## 3. Refresh on resume

| Check | Result |
|---|---|
| Cold launch | 1 document request, no follow-up reload |
| `blur`/`focus` only | 0 requests, same document |
| hidden → visible | 1 reload of the same URL (`/entries/?view=past` kept) |
| `visibilitychange` + persisted `pageshow` together | 1 reload |
| Offline resume | 0 requests, content stays visible |
| Reconnect (`online`) | 1 reload, same URL |
| Back from a detail page | 1 document request (no double load) |
| Entry added elsewhere, then child list resumes | new entry visible after the refresh |
| Capture form, text typed, then resume signals | text kept, no request, script not loaded |

### Re-run after implementation review (F1, F2)

The script now reloads only after at least 30 s hidden, and only after a `HEAD /healthz/` probe answers `ok`.

| Check | Result |
|---|---|
| Cold launch | 1 document request, no probe |
| `blur`/`focus` only | 0 requests |
| Brief switch (< 30 s) | 0 requests, same document |
| Long switch (≥ 30 s, clock advanced) | 1 `HEAD` probe, then 1 reload of the same URL (`?view=past` kept) |
| Long switch + persisted `pageshow` together | 1 probe, 1 reload |
| Offline (`navigator.onLine` false) | 0 requests, content stays; reconnect → 1 reload, same URL |
| Server unreachable, `navigator.onLine` true | probe fails, 0 reloads, list stays visible; next resume (even brief) → 1 reload |
| Health probe answers 503 | 0 reloads, same document |
| Capture form with typed text, long resume signals | text kept, 0 requests |

## 4. Accessibility

| Check | Result |
|---|---|
| axe-core 4.10.2 (WCAG 2.0/2.1/2.2 A+AA), parent and child lists, both modes, at 320×568, 667×375 and 844×390 | 0 violations |
| Keyboard Tab at 667×375 | skip link → nav → actions → modes → calendar nav → entries in chronological order; focus visible on every stop |
| 400% zoom equivalent (320×256) | 1 column, no horizontal scroll |
| 200% zoom on a 1280×720 desktop (640×360) | 7 columns, no horizontal scroll |
| Orientation | manifest still does not lock orientation (automated `test_manifest_does_not_lock_orientation`) |
