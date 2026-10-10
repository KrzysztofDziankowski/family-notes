# Accessibility verification — private-family-entries

Manual matrix from `context/foundation/accessibility.md`. **Draft: every result is pending; no
manual check has been performed yet.** Record pass/fail with a note per cell.

Automated structural audit: `entries/tests/test_accessibility.py` (`ChildCaptureAuditTests`,
`PrivacyAuditTests`).

| Flow | Keyboard (Chrome) | NVDA + Firefox | VoiceOver + Safari (iOS) | TalkBack + Chrome (Android) | axe DevTools | 200% zoom / 320 px reflow |
| --- | --- | --- | --- | --- | --- | --- |
| Child capture: empty, invalid, proposal with privacy choice, unavailable | pending | pending | pending | pending | pending | pending |
| Child follow-up: question, invalid answer, skip, highlights | pending | pending | pending | pending | pending | pending |
| Child correction failed / correction-invalid, confirm-invalid | pending | pending | pending | pending | pending | pending |
| Child batch review and batch-invalid (per-entry privacy) | pending | pending | pending | pending | pending | pending |
| Child saved state (public and private) | pending | pending | pending | pending | pending | pending |
| Parent review and batch review with the privacy choice | pending | pending | pending | pending | pending | pending |
| Parent calendar „Filtr prywatności” (Wszystkie / Prywatne / Nieprywatne, with and without child filter, JS and no-JS) | pending | pending | pending | pending | pending | pending |
| Child calendar „Filtr prywatności” (Wszystkie / Prywatne / Nieprywatne) | pending | pending | pending | pending | pending | pending |
| Parent detail „Widoczność” control (creator; private and public; after-change message) | pending | pending | pending | pending | pending | pending |
| Child detail „Widoczność” control (creator; private and public; after-change message) | pending | pending | pending | pending | pending | pending |
| Non-creator detail (no privacy control) | pending | pending | pending | pending | pending | pending |
| Filter state preserved: calendar navigation, detail „Wróć do listy”, delete and privacy redirects | pending | pending | pending | pending | pending | pending |
