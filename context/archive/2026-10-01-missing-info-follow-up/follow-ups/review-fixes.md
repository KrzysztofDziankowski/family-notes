# Implementation review fixes

Decisions approved during triage on 2026-10-04.

- F1: Require literal parent-text evidence for dates; remove bare answer-key and surrounding-input shortcuts. Add negative regressions for unknown-date, member-only and date-bearing answers, plus a positive Friday answer case.
- F2: Add the implementation addendum documenting shared date-source filtering, past-date hints, gallery additions, model guidance and existing verification.
- F3: Document the owner's screenshot waiver and the absence of saved phone-browser and timed follow-up evidence; preserve historical Progress entries. Do not repeat browser or paid live checks.

## Execution

- F1, F2 and F3 completed; final decisions saved in the implementation review.
- Focused adapter/follow-up suites: 104 tests passed.
- Full suite: 681 tests passed (4 skipped).
- Django checks, migration drift check and diff whitespace check passed.
- Browser checks and paid provider calls were not repeated.
