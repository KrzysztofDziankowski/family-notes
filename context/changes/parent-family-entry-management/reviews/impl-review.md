<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Parent Family Entry Management

- **Plan**: context/changes/parent-family-entry-management/plan.md
- **Scope**: Full plan
- **Reviewed phases**: 1, 2, 3
- **Date**: 2026-09-28
- **Verdict**: NEEDS ATTENTION
- **Findings**: 0 critical, 2 warnings, 5 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | PASS |
| Scope Discipline | PASS |
| Safety & Quality | WARNING |
| Architecture | WARNING |
| Pattern Consistency | WARNING |
| Success Criteria | WARNING |

Automated criteria were re-run on 2026-09-28 in the worktree with `DJANGO_DEBUG=true`:

- `manage.py test`: 330 tests OK (3 skipped).
- `manage.py check`: no issues.
- `makemigrations --check --dry-run`: no changes.

A trial merge with `feature/child-assigned-entry-view` passed 351 tests.

The review covers S-02's own diff (`e37e56b..HEAD`), which reuses `entries/listing.py` and `_entry_row.html` from S-03 as planned. Every deviation the implementer reported was checked and matches the code: delegation to `save_confirmed_entry`, service-level content validation, delete returning to the entry's own list mode, `_mark_invalid_fields`, `novalidate`, and the content label "Tytuł".

## Findings

### F1 — Committed tokens.css ends in 84 NUL bytes

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: family_notes/static/css/tokens.css:269
- **Detail**: Commit b8c94b2 wrote the file with 84 `\0` bytes after the last rule and no final newline. This is the same `/mnt/c` write corruption that damaged the dev SQLite file. Git now treats the file as binary (`Bin 4953 -> 6994`), which has two effects:
  - Diffs of the file are hidden from review.
  - Merges of the file conflict as binary. Merging S-03's CSS additions needs manual reconstruction.

  Browsers probably tolerate it, but the file is corrupted. 8cd1ba1 and master are clean.
- **Fix**: Strip the NUL bytes, end the file with a newline, and confirm `git diff --stat` shows a text diff again.
- **Decision**: FIXED — NUL bytes stripped, final newline added; git diffs tokens.css as text again.

### F2 — Editing an entry silently drops a deactivated assignee

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Safety & Quality
- **Location**: entries/forms.py:179-194 (`EntryEditForm`), entries/forms.py:75 (active-only assignee queryset)
- **Detail**: `EntryEditForm` sets `initial['assigned_member']` to the current assignee, but the choices contain only active members. For an entry assigned to a member who was later deactivated, the select renders with nothing selected. The browser then posts `''`, so any unrelated edit (for example, the title) quietly reassigns the entry to "Cała rodzina". If the school subtype requires an affected member, the parent instead gets an error they cannot resolve without choosing someone else. The roadmap says people are deactivated, never deleted, so this state will occur. No test covers it.
- **Fix A ⭐ Recommended**: In edit only, add the current inactive assignee as a labelled option (e.g. "Kasia (nieaktywna)"). The service accepts it when it equals the entry's existing assignee.
  - Strength: Edits keep the assignee unless the parent changes it, and no data changes silently.
  - Tradeoff: The form and `update_family_entry` each need a small "unchanged inactive assignee" exception, plus tests.
  - Confidence: HIGH. The failure was reproduced in a rollback-only check, and the change stays inside S-02's own form and service.
  - Blind spot: Create must still exclude inactive members; the exception has to be scoped to edit.
- **Fix B**: Keep active-only choices, but when the current assignee is inactive, show a Polish notice on the edit form and require an explicit choice.
  - Strength: Simpler, with no service exception.
  - Tradeoff: The parent must reassign an entry to fix a typo, and entries of deactivated children can't be edited in place.
  - Confidence: MEDIUM. It depends on whether reassignment is acceptable to the product.
  - Blind spot: The product intent for historical entries of deactivated members is unconfirmed.
- **Decision**: FIXED via Fix A — EntryEditForm keeps the current inactive assignee selectable, labelled "(nieaktywne konto)"; update_family_entry validates inside the row lock with kept_assignee_id, so a deactivated member can be kept but never newly assigned. Form, service and view regression tests added (fail without the fix).

### F3 — "No creator internals" test assertion can never fail

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Success Criteria
- **Location**: entries/tests/test_manage_views.py:211-231
- **Detail**: The detail test builds its entry with `created_by=None` and then asserts that the creator's name "Ewa" is absent, so the assertion can never fail. The template is compliant: `_manage_detail.html` never renders `created_by`, the pk or `submission_key`. The guard itself is missing.
- **Fix**: Add a case with `created_by=self.parent` and assert that neither the creator's name nor the `submission_key` appears.
- **Decision**: FIXED — added test_detail_hides_creator_and_submission_key_of_a_manual_entry, with a real second-parent creator.

### F4 — Duplicated parent-membership checks and mid-module imports

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Architecture
- **Location**: entries/services.py:101-105, entries/views.py:40, entries/views.py:250-270
- **Detail**: The parent-membership check exists three times: `services._require_parent_membership`, `views._require_parent`, and the inline check in `save_confirmed_entry`. The S-02 imports also sit mid-module with `# noqa: E402`, a coordination measure for the S-03 merge. S-03 did the same.
- **Fix**: After S-02 and S-03 are merged, move the imports into the header and have `save_confirmed_entry` use `_require_parent_membership`.
- **Decision**: QUEUED — follow-ups/review-fixes.md; do after S-02 and S-03 merge to avoid reintroducing conflicts.

### F5 — Messages partial styles every level as success

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: entries/templates/entries/_manage_messages.html
- **Detail**: S-02 is the first place outside the admin to use `django.contrib.messages`; capture uses `?saved=<pk>`. The partial renders every message as a success panel whatever its level. Today only success messages are added, so this is correct for now but will mislead the next user of the partial.
- **Fix**: Map `message.tags` to the existing `fn-panel--success/--notice/--danger` classes.
- **Decision**: FIXED — _manage_messages.html maps message.tags to fn-panel--success/--notice/--danger (role alert for errors); MessagesPartialTests added.

### F6 — Resubmitting a cached create form recreates a deleted entry

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: entries/services.py:140-172 (`create_family_entry`)
- **Detail**: The idempotency key lives only on the `Entry` row, so deleting the entry deletes the key too. If the parent goes back in the browser to the create form and submits it again, the entry comes back with "Dodano wpis.". This needs a deliberate resubmission, so the impact is low.
- **Fix**: Accept it for the MVP and record it as a known limitation in the plan. A key tombstone isn't worth it at this scale.
- **Decision**: ACCEPTED — documented under "Known Limitations" in plan.md.

### F7 — Manual criteria ticked from agent checks only

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Success Criteria
- **Location**: plan.md Progress 1.7, 2.8-2.10, 3.6-3.8
- **Detail**: The manual rows are `[x]` with the note "agent-verified …; human check pending". The evidence is 14 headless-Chromium 360px screenshots and scripted flows (no-JS delete, edit, 404 parity). Nobody has done the check on a real Android device (3.7) or reviewed it as a person. Screenshots show en-US date inputs, which is a headless-locale artifact.
- **Fix**: Have a person run 2.8 and 3.7 on a phone, then remove the "human check pending" notes.
- **Decision**: FIXED differently — the manual Progress rows (1.7, 2.8–2.10, 3.6–3.8) are unchecked until a person verifies them; the agent-evidence notes are kept.
