# Entry date semantics verification

Worktree: `/tmp/family-notes-entry-date-semantics`, branch `feature/entry-date-semantics`.
Baseline: `e05521d`; implementation started 2026-10-06. No production database, service, or provider was contacted for this evidence.

## Synthetic migration evidence

The forward-only migration test covers 66 historical entries across two families, both manual/EduVulcan sources, all three original broad types, all nine recognized school kinds, blank metadata, and unknown metadata. It compares complete rows after adjusting only the expected date/type fields, plus complete notification/output-link rows including a deletion tombstone.

| Before | After |
| --- | --- |
| Null date; created_at `2026-01-01T23:30:00+00:00` | Date `2026-01-02` in Europe/Warsaw |
| Null date; created_at `2026-07-01T23:30:00+00:00` | Date `2026-07-02` in Europe/Warsaw |
| Existing date `2025-03-04` | Same date `2025-03-04` |
| Recognized substitution/room-change kind stored as note/task | Calendar event |
| Recognized grade/lucky-number/late-arrival kind stored as event/task | Note |
| Blank or unknown school metadata | Original broad type unchanged |

Tests prove null writes fail for every broad type after schema enforcement, no application/database date default is added, and the data migration is explicitly irreversible. Existing historical conversion scenarios run forward against a fresh isolated database rather than reversing the normal test database.

Development migration/conversion checks: 24 tests passed. Seed smoke: a fresh disposable SQLite database was migrated and seeded; nine entries were created with zero null dates. Password output was suppressed. PostgreSQL execution remains unverified.

## Automated checks

Focused form/view/access/accessibility checks passed (382 tests). Classification/service/conversion checks passed (305 tests). API/listing/family checks passed (173 tests); additional cross-family checks passed (22 tests). Imported fallback acceptance checks passed (19 tests), and the updated classification acceptance module passed (42 tests, 7 skipped).

The final integrated Django suite passed: 1,452 tests in 70.227 seconds, with 15 expected skips. `manage.py check`, `makemigrations --check --dry-run`, and `git diff --check` also passed.

Deliberate-break verification proved that focused tests fail when each critical behavior is removed, after which every file was restored from the staged green version:

- initial notes no longer receive the local writing date;
- parent list rows expose broad type labels;
- historical backfill uses UTC instead of Europe/Warsaw;
- the automation API serializes entry dates as null.

## Pending manual acceptance

- Keyboard and Android review of date labels, errors, and parent/child lists.
- Human review of the synthetic migration report and creation-date fallback deadlines for historical tasks.
- Installed maintenance deployment support, release-specific production smoke, and PostgreSQL evidence. The current protocol-1 helper migrates before restarting writers and must not deploy this schema.

The change remains implementing until the required manual acceptance is confirmed. No automatic rollback, database restoration, or production deployment is authorized by this work.
