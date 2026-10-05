# Generic Family Entries — Implementation Plan

## Overview

Deliver S-21: use `generic` as the only active entry type. Convert every existing entry, remove broad type selection and labels, and retain school details.

Ordinary entries may be undated. Recognized school items retain their existing required fields.

## Current State Analysis

All three types already share one model and date-based browsing. Broad types still influence classification, correction, validation, forms, admin, and EduVulcan conversion.

The baseline suite passed: 1,431 tests, 15 skipped. Django checks and migration checks passed.

## Desired End State

- Every existing and newly saved entry has `entry_type="generic"`.
- Product pages and admin offer no broad type selector. Product pages show no task/event/note badges or detail rows.
- School details remain editable and enforce their existing requirements.
- Undated ordinary entries appear under “Bez daty”; dated entries move to the past when their date passes.
- Family authorization, child read-only access, batch atomicity, and notification deduplication remain intact.

### Key Discoveries

- School validation currently depends on broad type equality; changing storage alone would bypass required-field checks.
- OpenAI’s type schema currently enumerates every `EntryType` constant; retaining dormant constants requires removing that enumeration from active schemas.
- Open proposals travel through POST fields, including hidden fields. Forms opened before deployment need compatible handling.
- Historical migration tests reverse the current database to an earlier schema. A genuinely irreversible conversion requires isolated, forward-only migration tests.

## What We're NOT Doing

- Task completion, reminders, calendar integrations, or reactivating legacy types.
- A shadow field retaining each entry’s original category.
- Feature flags, new browser-test infrastructure, or changes to archived documents.
- Production deployment during implementation or saving this plan.

## Implementation Approach

Prepare the generic schema, update every producer and editor, then convert existing data and enforce generic-only storage. Deploy the completed slice as one release.

Keep legacy enum constants dormant for possible future work. Active choices, provider schemas, validation, and presentation must use only generic entries.

## Critical Implementation Details

**School validation:** requirements must depend directly on school metadata. Preserve the existing subject exemption for automated entries and eligible edits of older subject-less entries.

**Migration ordering:** separate schema preparation, data conversion, and final constraint enforcement. Use historical migration models and the migration’s database alias. Update only `entry_type`.

**Release prerequisite:** the current helper migrates before stopping old workers. Before rollout, complete the maintenance deployment work in `testing-production-security-schema-safety`, phase 4, so web requests and conversion workers stop before backup and migration. A pre-generic application release is not a valid code-only rollback target afterward.

## Phase 1: Generic Contract and Write Paths

### Overview

Make generic the server-owned type throughout extraction and persistence.

### Changes Required

**Files:** classification modules, shared entry services, EduVulcan rules/conversion, entry model, and a new preparation migration.

**Intent:** Eliminate broad-type decisions while preserving meaningful extraction and school validation.

**Contract:**

- Add `EntryType.GENERIC = "generic"` with Polish label “Wpis”.
- Set model and database defaults to generic; expose only generic in active model choices.
- Remove the calendar-event date constraint through a new migration; leave historical migrations unchanged.
- Remove broad type selection from provider schemas, prompts, and correctable fields. Assign generic locally.
- Make manual, confirmed, batch, corrected, fixed-rule, automated, and fallback entries generic.
- Ignore obsolete supplied type values; they cannot control the saved type.
- Validate school requirements independently of broad type. Ordinary entries have no type-derived date requirement.
- Preserve grounding checks, whole-input fallback, selective correction, submission-key replay, and atomic batch saves.
- Retain conversion provenance identifiers such as `general_note`; they describe conversion history rather than the entry taxonomy.

### Success Criteria

#### Automated Verification

- Generic classification, correction, service, and EduVulcan tests pass.
- Django checks and migration drift checks pass.

## Phase 2: Forms and Presentation

### Overview

Present one entry concept across capture, management, child views, and admin.

### Changes Required

**Files:** shared forms, entry views and partials, admin configuration, and affected state galleries.

**Intent:** Remove broad type controls and copy without hiding meaningful school details.

**Contract:**

- Remove broad type fields from visible and hidden form contracts, correction notices, and duplicate comparison.
- Remove broad badges, detail rows, saved-panel labels, and fallback wording. Use Polish entry wording.
- Keep “Element szkolny”, subject, person, date, and time controls.
- Forms opened before deployment may submit obsolete type fields; ignore those fields and rebuild generic proposals while validating all remaining values.
- Recompute follow-up requirements from school metadata and member ambiguity.
- Admin creation and editing always save generic; remove broad type selection and filtering.
- Replace gallery examples based on type mismatches with real content or school-field errors.
- Preserve day → assignee grouping, time-only rows, family-context fields, accessibility associations, and existing submission/progress scripts.

### Success Criteria

#### Automated Verification

- Form, view, admin, access, and accessibility tests pass.

#### Manual Verification

- Keyboard and Android review confirm generic-only controls and copy.

## Phase 3: Existing-Data Migration

### Overview

Convert all saved entries and enforce the final storage invariant.

### Changes Required

**Files:** new entry migrations, migration tests, and the historical conversion-migration test harness.

**Intent:** Convert every entry across all families and sources without recreating records.

**Contract:**

- Run a forward data migration after schema preparation, changing only `entry_type` to `generic`.
- Preserve primary keys, family relationships, content, dates, times, school metadata, provenance, submission keys, and timestamps.
- Preserve notification-output links and deletion tombstones.
- Make the conversion explicitly irreversible; do not invent reverse category mappings.
- Add a subsequent database check named `entry_type_is_generic`.
- Update ordinary test fixtures to generic. Keep legacy values in historical migration fixtures and compatibility tests.
- Run historical migration scenarios against fresh disposable databases; never reverse the main test database through the irreversible conversion.

### Success Criteria

#### Automated Verification

- Forward migration tests prove all rows are generic and all other fields and links are preserved.
- Historical migration tests use isolated databases and generic-only storage rejects legacy writes.

#### Manual Verification

- Review the synthetic before/after report and confirm category loss is intentional.

## Phase 4: Verification and Release Readiness

### Overview

Verify the complete slice and document its public and operational contracts.

### Changes Required

**Files:** API examples, living product documentation, S-21 roadmap details, classification smoke expectations, deployment runbook, and regression tests.

**Intent:** Make the changed type value explicit and provide evidence for deployment.

**Contract:**

- Retain the REST response structure and `entry_type` key; its value becomes `"generic"`.
- Preserve existing filtering, pagination, null values, and token-scoped access. Add no type filter.
- Update product documentation to generic entries while preserving school requirements.
- Update smoke expectations to `entry_type=generic`.
- Extend the existing PostgreSQL rehearsal work with the generic conversion and constraint scenarios.
- Require installed maintenance deployment support before rollout: stop writers → backup → migrations → activate generic-aware code → readiness checks.
- Document forward-fix recovery. Failed migrations or startup must not automatically restart pre-generic code or restore a database.
- Record release smoke results using synthetic inputs and the existing privacy-safe logging policy.

### Success Criteria

#### Automated Verification

- Full Django suite, system checks, and migration drift checks pass.
- Disposable PostgreSQL rehearsal proves conversion, constraints, and failure recovery.

#### Manual Verification

- Maintenance prerequisites and synthetic release smoke results are recorded.

## Testing Strategy

### Unit and Integration Tests

Cover:

- Generic output from every creation, correction, follow-up, and fallback path.
- Undated “Zebranie rodziców” reaching review and saving successfully.
- Missing school date/person/subject still producing the required validation or follow-up.
- Eligible subject-less imported entries remaining editable.
- Old or forged type fields failing to reactivate legacy types.
- Mixed historical types, sources, and families converting with exact preservation of non-type fields.
- Batch rollback, replay, notification deduplication, and deleted-entry tombstones.
- Parent, assigned-child, other-child, foreign-family, unauthenticated, and token access boundaries.
- Absence of broad type controls and labels without banning unrelated wording such as “Rodzaj listy”.

Run focused suites per phase. At completion run:

```bash
uv run python manage.py test --noinput
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
```

### Manual Testing Steps

1. Capture, correct, save, and edit ordinary dated and undated entries.
2. Exercise school follow-ups and subject-less imported-entry edits.
3. Review batch, parent, child, admin, and gallery states.
4. Verify keyboard access and Android presentation.
5. Review migration evidence and perform the documented release smoke after maintenance prerequisites are satisfied.

## Performance Considerations

Use one bulk type update without per-row saves or classification calls. Retain existing indexes and list ordering. This change adds no background service or external dependency.

## Migration Notes

The previous suggestion to preserve historical broad values is superseded: every existing entry becomes generic. Original categories are recoverable only from an appropriate pre-migration backup.

The PostgreSQL rehearsal and maintenance-deployment prerequisites belong to the existing security/schema-safety change. Reuse that work rather than implementing a second deployment mechanism.

## References

- S-21 in `context/foundation/roadmap-future.md`.
- `context/changes/generic-family-entries/change.md`.
- School validation coupling: `entries/services.py:142`.
- Hidden proposal type: `entries/forms.py:682`.
- REST serialization: `entries/api_views.py:213`.
- Maintenance prerequisite: `context/changes/testing-production-security-schema-safety/plan.md`, phases 3–4.
- [Django 5.2 data migrations](https://docs.djangoproject.com/en/5.2/topics/migrations/#data-migrations).
- [Django 5.2 RunPython operations](https://docs.djangoproject.com/en/5.2/ref/migration-operations/#runpython).

## Progress

### Phase 1: Generic Contract and Write Paths

#### Automated

- [ ] 1.1 Generic classification, correction, service, and EduVulcan tests pass.
- [ ] 1.2 Django checks and migration drift checks pass.

### Phase 2: Forms and Presentation

#### Automated

- [ ] 2.1 Form, view, admin, access, and accessibility tests pass.

#### Manual

- [ ] 2.2 Keyboard and Android review confirm generic-only controls and copy.

### Phase 3: Existing-Data Migration

#### Automated

- [ ] 3.1 Forward migration tests prove all rows are generic and all other fields and links are preserved.
- [ ] 3.2 Historical migration tests use isolated databases and generic-only storage rejects legacy writes.

#### Manual

- [ ] 3.3 Review the synthetic before/after report and confirm category loss is intentional.

### Phase 4: Verification and Release Readiness

#### Automated

- [ ] 4.1 Full Django suite, system checks, and migration drift checks pass.
- [ ] 4.2 Disposable PostgreSQL rehearsal proves conversion, constraints, and failure recovery.

#### Manual

- [ ] 4.3 Maintenance prerequisites and synthetic release smoke results are recorded.
