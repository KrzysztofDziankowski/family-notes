<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Child Assigned Entry View

- **Plan**: context/changes/child-assigned-entry-view/plan.md
- **Scope**: Full plan
- **Reviewed phases**: 1, 2, 3
- **Date**: 2026-09-28
- **Verdict**: NEEDS ATTENTION
- **Findings**: 0 critical, 1 warning, 4 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | PASS |
| Scope Discipline | WARNING |
| Safety & Quality | WARNING |
| Architecture | PASS |
| Pattern Consistency | WARNING |
| Success Criteria | WARNING |

Automated criteria were re-run on 2026-09-28 in the worktree with `DJANGO_DEBUG=true`, and all passed:

- `manage.py test`: 277 tests OK (3 skipped).
- `manage.py check`: no issues.
- `makemigrations --check --dry-run`: no changes.

A trial merge with `feature/parent-family-entry-management` then passed 351 tests. That merge conflicted in `entries/views.py`, `entries/urls.py` and `tokens.css`, where both sides added code at the end of the file; keeping both blocks resolves it.

## Findings

### F1 — Hidden DEBUG gallery answers 405 in production

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: entries/views.py:328
- **Detail**: `@require_GET` runs before the `if not settings.DEBUG: raise Http404` check inside `child_states`. With `DEBUG=False`, a GET returns 404 but a POST returns 405, so a POST shows that the route exists. The existing capture `states` view has no method decorator and returns 404 for every method.
- **Fix**: Drop `@require_GET` from `child_states`, or check the method after the DEBUG check. Add a test that a POST returns 404 when `DEBUG=False`.
- **Decision**: FIXED — @require_GET removed from child_states; test_every_method_is_not_found_without_debug added (fails without the fix).

### F2 — Unplanned `edit_url_name` parameter on the shared row partial

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Scope Discipline
- **Location**: entries/templates/entries/_entry_row.html:8
- **Detail**: The plan's partial contract is `entry`, `detail_url_name` and a hide-assignee flag. The implementation also adds `edit_url_name`, which the coordinator asked for so S-02 could reuse the partial, and `detail_query`, which the back link needs. Both are optional and never used by child templates. Neither is written into the plan.
- **Fix**: Add a short addendum to Phase 1 §2 of the plan that lists the two optional parameters.
- **Decision**: FIXED — added an addendum to Phase 1 §2 of the plan describing edit_url_name and detail_query.

### F3 — Imports placed mid-module with `# noqa: E402`

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: entries/views.py:244-263
- **Detail**: The S-03 imports sit inside the S-03 block rather than in the file header. This was done to keep the merge with S-02 simple, and S-02 did the same. It repeats modules the header already imports from (`django.shortcuts`, `django.views.decorators.http`, `family_access.access`). The repo has no linter, so the `noqa` markers do nothing. No other module in the repo does this.
- **Fix**: After S-02 and S-03 are merged, move both blocks' imports into the header of `entries/views.py` in one follow-up commit.
- **Decision**: QUEUED — follow-ups/review-fixes.md, together with parent-family-entry-management F4.

### F4 — No regression test that entry content is escaped

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: entries/tests/test_child_views.py
- **Detail**: Autoescape is correct today: there is no `|safe`, and `linebreaksbr`/`truncatechars` both escape. But no test saves markup in `content` and checks that the list and detail pages escape it. Content can come from EduVulcan, which is external input, and the row partial is shared with S-02.
- **Fix**: Add one test that saves `<script>x</script>` as content and asserts the escaped form appears in both the child list and child detail responses.
- **Decision**: FIXED — added test_entry_content_is_escaped_in_list_and_detail.

### F5 — Manual criteria ticked from agent checks only

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Success Criteria
- **Location**: plan.md Progress 2.8, 2.9, 3.5, 3.6, 3.7
- **Detail**: The manual rows are `[x]` with the note "agent-verified …; human check pending". The evidence is a headless-Chromium 360px screenshot (`screenshots/child-states-360.png`) and scripted flows. Nobody has checked the flow on a real Android device (3.7) or reviewed it as a person.
- **Fix**: Have a person run 2.8 and 3.7 on a phone, then remove the "human check pending" notes. If anything fails, reopen the row.
- **Decision**: FIXED differently — the manual Progress rows (2.8, 2.9, 3.5–3.7) are unchecked until a person verifies them; the agent-evidence notes are kept. Manual verification confirmed by user on 2026-09-28; rows re-ticked.
