# Mandatory Dates and Listing Type Labels — Implementation Plan

## Overview

Keep notes, events, and tasks. Require dates for all entries, hide type labels in parent and child listing views, and retain type selection elsewhere. This replaces the generic-entry proposal and supersedes the initial no-migration decision.

## Current State Analysis

`Entry.date` is nullable; only calendar events have a database date constraint. Notes/tasks and several imported notes are undated. School kinds fix broad types, so changes must coordinate classification, school rules, and write validation. Parent lists already hide type badges; child lists still display them.

Correction forms intentionally accept incomplete drafts. Save validation must become strict without preventing a correction from supplying missing data. Historical migration tests currently reverse the normal test database and need isolation before an irreversible backfill.

## Desired End State

Every saved entry has a date: notes use their writing date, events their occurrence date, tasks their deadline. Existing non-null dates remain unchanged; missing dates become local creation dates. Historical types are aligned to the agreed mapping only when saved school-kind metadata identifies the category; entries without recognized school metadata retain their types. Product lists hide broad type labels; capture/edit/detail retain them.

### Key Discoveries

- `entries/classification/types.py`: school kinds determine type independently of provider output.
- `entries/forms.py`: correction forms bypass schedule completeness intentionally.
- `entries/eduvulcan/rules.py`: source occurrence dates are sometimes removed from titles; retain those details when notes use writing dates.
- `entries/tests/test_conversion_models.py`: migration scenarios currently reverse the main test database.
- `scripts/deployment/family-notes-deploy`: migrations run before service restart, requiring maintenance support before safe rollout.

## What We're NOT Doing

Generic types, historical text-based reclassification, overwriting existing non-null dates, task completion, reminders, new E2E infrastructure, production deployment, or edits to archived documents. The abandoned generic-entry worktree must not be merged.

## Implementation Approach

Implement four approved phases: date rules and school mappings; forms and listing labels; existing-date backfill plus non-null storage; final compatibility and release verification. Deploy the completed change as one release. Preserve family scope, privacy, replay, atomicity, and school requirements throughout.

## Critical Implementation Details

Europe/Warsaw determines local dates. Imported note dates prefer reliable source-writing dates, then capture dates; occurrence dates remain in note text. Processing delays must not redefine writing dates.

Backfill precedes schema enforcement and updates only null dates. Use isolated forward-only migration tests. Do not restart old writers during migration or assume a pre-change release can safely write to the non-null schema.

## Phase 1: Date Rules and School Mappings

### Overview

Date Rules and School Mappings across the existing entry flows.

### Changes Required

**Files:** classification types, validation, correction services and provider prompts; shared entry services; EduVulcan rules and conversion.

**Intent:** Keep three types and give their dates distinct meanings across every producer and save path.

**Contract:**

- Keep `note`, `calendar_event`, and `todo`; introduce no generic type.
- Notes use their writing date. Default new manual notes to the application-local reference date, allow corrections, and preserve dates during ordinary edits.
- Imported notes use source-writing dates only from explicitly recognized formats, initially the existing teacher-message format. Validate calendar dates and resolve omitted years against the local capture date using the existing parser; invalid or unrecognized writing dates fall back to capture date. Apply this provenance rule to every imported note, including classifier output; never accept an unverified provider date as a writing date. Assessment, attendance, and applicable school dates remain in text.
- Events use occurrence dates; tasks use due dates. Missing dates require follow-up before confirmation. Incomplete correction drafts remain allowed; final saves require dates.
- On type changes, keep the selected date, change its label/help, and let the user review or change it.
- Imports unable to ground an event/task date use the existing full-text note fallback dated by source-writing/capture time. Preserve meaningful source occurrence dates in note text.
- Events: homework, class test, test, quiz, substitution, room change, teacher absence. Notes: lucky number, grade, late arrival, teacher message, unrecognized fallback. Update school mappings, fixed rules, and shared validation consistently; teacher absence uses the existing timetable conversion contract without requiring a new school enum.
- Preserve school person/subject requirements and eligible subject-less exemptions, family authority, grounding, member ambiguity, submission replay, output provenance, and atomic saves.

### Success Criteria

#### Automated Verification

- Classification, correction, service, and EduVulcan tests prove date meanings, source-date precedence, school mappings, and missing-date handling.
- Batch and conversion tests prove atomicity, replay stability, and full-text dated fallback preservation.

## Phase 2: Forms and Listings

### Overview

Forms and Listings across the existing entry flows.

### Changes Required

**Files:** entry forms, views, admin, shared row partials, parent/child list templates, and DEBUG galleries.

**Intent:** Explain mandatory dates where users choose types and simplify listing presentation.

**Contract:**

- Require dates in create, confirmation, edit, batch, and admin writes. Correction forms may accept incomplete drafts so corrections can supply dates.
- Use Polish labels “Data zapisania”, “Data wydarzenia”, and “Termin wykonania”; admin copy remains English.
- Keep type selectors, school controls, and detail information outside listings.
- Hide broad type badges in both parent and child upcoming/past lists and galleries. Parent lists already support hiding types; extend child rendering without removing relevant row metadata.
- Preserve day/assignee grouping, content, times, detail/edit links, accessible link context, family-context fields, and existing progress scripts.
- Past tasks leave the main view after their deadline, without an unfinished-task exception.

### Success Criteria

#### Automated Verification

- Form, view, admin, access, and accessibility tests prove required dates and listing-only type hiding.

#### Manual Verification

- Keyboard and Android review confirm date labels, required-date errors, and type-free parent/child lists.

## Phase 3: Backfill and Storage Enforcement

### Overview

Backfill and Storage Enforcement across the existing entry flows.

### Changes Required

**Files:** entry date model declaration, new data/final schema migrations, migration preservation tests, historical conversion-migration test harness, `scripts/dev/seed_test_family.py`, and ordinary ORM test fixture helpers.

**Intent:** Give every existing row a date, align historical types using saved school metadata, and enforce non-null storage.

**Contract:**

- Fill only null dates with the Europe/Warsaw calendar date of each row's `created_at`. Historical undated tasks receive creation dates as fallback deadlines, as approved.
- Preserve every existing non-null date, unrelated field, timestamp, primary key, relationship, output link, and tombstone. Normalize entry_type from recognized saved school_item metadata: homework/class_test/test/quiz/substitution/room_change → calendar_event; lucky_number/grade/late_arrival → note. Leave types unchanged when metadata is blank or unrecognized; do not parse historical text, including teacher-absence/message text, to infer categories.
- Use historical migration models and the migration connection alias. Separate the data backfill from the final non-null schema operation; add no database date default.
- After backfill, make `Entry.date` non-null and mandatory. Leave historical migrations unchanged.
- Date backfill and historical type normalization are explicitly irreversible; do not invent reverse mappings to original nulls or types.
- Update development seed scripts and ordinary ORM fixtures to supply meaningful dates before non-null enforcement. Keep null fixtures only in historical migration scenarios and explicit storage-rejection tests.
- Run historical migration scenarios against fresh isolated disposable databases; never reverse the normal test database through the backfill.
- Stop old application writers before migration and start only date-aware code afterward. Production deployment remains outside implementation scope.

### Success Criteria

#### Automated Verification

- Forward migration tests prove Europe/Warsaw backfill, metadata-based type normalization, preservation of unmapped types, and exact preservation of existing dates, unrelated fields, links, and timestamps.
- Storage tests reject null dates; dated development seeds, ordinary fixtures, isolated historical migration tests, and migration drift checks pass.

#### Manual Verification

- Review synthetic before/after evidence and confirm creation-date fallback deadlines for historical tasks.

## Phase 4: Compatibility and Verification

### Overview

Compatibility and Verification across the existing entry flows.

### Changes Required

**Files:** living product documentation, README/API examples, S-21 roadmap entry, deployment runbook, API and regression tests.

**Intent:** Document changed guarantees and verify the complete release.

**Contract:**

- Preserve REST response shape and the existing set of three type values. Dates become non-null after migration; individual historical entries may change type according to their saved school metadata. Document this deliberate value change for API consumers.
- Retain current filtering, pagination, ordering, lucky-number exclusions, and access boundaries. Account for backfilled entries changing chronological placement; do not retain undated-read promises as final storage guarantees.
- Update documentation, roadmap S-21, API examples, migration evidence, and recovery instructions.
- Verify installed maintenance deployment support stops web and conversion writers before backup/migration; the current helper migrates before restart, so safe maintenance remains a release prerequisite.
- Document forward-fix recovery and an explicit compatibility assessment before code rollback. Do not merge the abandoned generic worktree or perform production deployment.
- Record actual checks; manual checks remain pending until confirmed.

### Success Criteria

#### Automated Verification

- Full Django suite passes: `uv run python manage.py test --noinput`.
- System and migration drift checks pass: `uv run python manage.py check` and `uv run python manage.py makemigrations --check --dry-run`.
- API and regression tests prove unchanged response shape/type values, non-null dates, authorization, and past/upcoming boundaries.

#### Manual Verification

- Review maintenance prerequisites and synthetic migration/release evidence before production rollout.

## Testing Strategy

Cover manual notes/events/tasks, extraction, correction, type changes, batches, edit, admin, and imports. Test writing-date defaults and corrections, Europe/Warsaw midnight boundaries, source-writing/capture precedence, delayed retries, missing schedules, school mappings, atomic rejection, replay, and authorization. Verify listing-only label hiding, retained type controls, date labels, and accessible errors.

Use synthetic mixed-family/source migration fixtures with null and existing dates. Compare all fields except intentionally changed date/type values and all output relationships, reject null dates after migration, and run historical migration scenarios in isolated databases. Preserve existing non-null dates even when they do not follow new writing-date semantics. Test every recognized school-kind mapping, blank/unknown metadata preserving types, and edits of migrated substitutions/room changes without mismatch errors.

Manual acceptance covers keyboard/Android date controls, both list modes, synthetic migration evidence, and maintenance readiness. Use existing Django tests and accessibility helpers; no new browser infrastructure.

## Performance Considerations

No new dependencies or services. Backfill null dates and normalize recognized school kinds using bounded processing where local timezone conversion requires application code. Avoid per-row saves that would alter timestamps, provider calls, or extra listing queries.

## Migration Notes

The owner explicitly authorized migration on 2026-10-06, superseding the earlier no-migration choice. Fill null dates from local creation dates, preserve all existing non-null dates, normalize types only from recognized saved school metadata, then enforce non-null storage without a date default. Backfill is irreversible; original missing-date information and pre-normalization type values can only be recovered from an appropriate backup. Production backup/migration occurs with all writers stopped; recovery is an explicit forward fix, never automatic rollback or restore.

## References

- Owner decisions and four-phase approval, 2026-10-06.
- S-21 in `context/foundation/roadmap-future.md`.
- `entries/classification/types.py`, `validation.py`, `service.py`, and `openai_backend.py`.
- `entries/services.py`, `forms.py`, `models.py`, and `listing.py`.
- `entries/eduvulcan/rules.py` and `conversion.py`.
- `entries/templates/entries/_entry_row.html` and child list partials.
- `entries/tests/test_conversion_models.py`.
- `context/changes/testing-production-security-schema-safety/plan.md`, maintenance deployment prerequisite.
- `context/foundation/lessons.md` and `AGENTS.md`.

## Progress

### Phase 1: Date Rules and School Mappings

#### Automated

- [ ] 1.1 Classification, correction, service, and EduVulcan tests prove date meanings, source-date precedence, school mappings, and missing-date handling.
- [ ] 1.2 Batch and conversion tests prove atomicity, replay stability, and full-text dated fallback preservation.

### Phase 2: Forms and Listings

#### Automated

- [ ] 2.1 Form, view, admin, access, and accessibility tests prove required dates and listing-only type hiding.

#### Manual

- [ ] 2.2 Keyboard and Android review confirm date labels, required-date errors, and type-free parent/child lists.

### Phase 3: Backfill and Storage Enforcement

#### Automated

- [ ] 3.1 Forward migration tests prove Europe/Warsaw backfill, metadata-based type normalization, preservation of unmapped types, and exact preservation of existing dates, unrelated fields, links, and timestamps.
- [ ] 3.2 Storage tests reject null dates; dated development seeds, ordinary fixtures, isolated historical migration tests, and migration drift checks pass.

#### Manual

- [ ] 3.3 Review synthetic before/after evidence and confirm creation-date fallback deadlines for historical tasks.

### Phase 4: Compatibility and Verification

#### Automated

- [ ] 4.1 Full Django suite passes: `uv run python manage.py test --noinput`.
- [ ] 4.2 System and migration drift checks pass: `uv run python manage.py check` and `uv run python manage.py makemigrations --check --dry-run`.
- [ ] 4.3 API and regression tests prove unchanged response shape/type values, non-null dates, authorization, and past/upcoming boundaries.

#### Manual

- [ ] 4.4 Review maintenance prerequisites and synthetic migration/release evidence before production rollout.
