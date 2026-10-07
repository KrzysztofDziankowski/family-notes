<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: EduVulcan Event Deduplication and Exam Merge

- **Plan**: context/changes/eduvulcan-event-dedup/plan.md
- **Scope**: Phase 1 of 2
- **Reviewed phases**: 1
- **Date**: 2026-10-07
- **Verdict**: NEEDS ATTENTION
- **Findings**: 0 critical, 2 warnings, 3 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | PASS |
| Scope Discipline | PASS |
| Safety & Quality | WARNING |
| Architecture | WARNING |
| Pattern Consistency | WARNING |
| Success Criteria | PASS |

Success criteria re-run: `test_eduvulcan_dedup` + `test_entry_service` 90 tests OK; `makemigrations --check --dry-run` no changes; `check` no issues. Phase 1 has no manual items. All planned items MATCH (dedup rules, precedence, tie-break, upgrade content/school_item, output kinds, migration, docstring, service contract); required test coverage present.

## Findings

### F1 — Upgrade service accepts non-exam entries when school_item is None

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: entries/services.py:428-455
- **Detail**: Only `source == eduvulcan` is enforced unconditionally; the entry-type check runs only when `school_item` is set. `upgrade_automated_exam_entry(task_entry, content=..., school_item=None)` overwrites any EduVulcan task/note/grade. Label/kind consistency (`'Kartkówka: X'` with `school_item=TEST`) and rank increase are not checked either. Safe today only because `decide()` is the sole caller.
- **Fix**: Require `entry.entry_type == calendar_event` and an exam label in both existing and new content (`exam_rank`), and, when `school_item` is set, that it equals the new label's kind; add tests for the `school_item=None` non-calendar case and the label/kind mismatch.
- **Decision**: FIXED — upgrade service now requires a calendar event with an exam label (and matching kind), a strictly higher new label, and a school_item matching the new label; tests added

### F2 — Upgrade can overwrite a concurrent parent edit

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Safety & Quality
- **Location**: entries/services.py:451-454 (caller: entries/eduvulcan/conversion.py `_apply`)
- **Detail**: The upgraded content is computed from the entry instance read by the candidate query, and saved without locking or re-reading the entry. The family row lock serializes conversions, but parent edits do not take it, so a parent edit committed between the candidate read and the save is lost.
- **Fix**: Lock the matched entry (`Entry.objects.select_for_update().get(pk=...)`) inside the persist transaction and re-run `decide` against the locked row (or skip the upgrade if its content no longer matches) before saving.
  - Strength: Closes the lost-update window with one extra indexed row lock, inside the transaction that already exists.
  - Tradeoff: A parent edit will wait briefly on the conversion transaction; one extra query per upgrade (rare).
  - Confidence: MED — the window is short (milliseconds, no provider calls inside), so the practical risk is low.
  - Blind spot: Haven't checked the lock order against the parent edit path (entry lock → ?); the plan states notification → family → entry has no inverse path.
- **Decision**: FIXED — via Phase 2 F2: candidates are locked with select_for_update(of=self) before the upgrade

### F3 — Low-level write service depends on the EduVulcan package; private import across modules

- **Severity**: 💡 OBSERVATION
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Architecture
- **Location**: entries/services.py:17, entries/eduvulcan/dedup.py:31
- **Detail**: `services.py` now imports `EXAM_KINDS` from `eduvulcan.dedup`, which pulls in `rules` and `children`; `dedup.py` imports the private `_CALENDAR_CATEGORIES` from `rules` (nothing else crosses modules with underscore names). No import cycle today (verified).
- **Fix**: Move `EXAM_RANKS`/`EXAM_KINDS` next to `SchoolItemKind` in `entries/classification/types.py` and expose the label map from `rules` under a public name.
  - Strength: Keeps `services` independent of the EduVulcan domain and removes the private import.
  - Tradeoff: Small move touching three modules and imports in tests.
  - Confidence: HIGH — mechanical refactor covered by the existing tests.
  - Blind spot: None significant.
- **Decision**: FIXED — EXAM_RANKS/EXAM_KINDS moved to classification/types.py; rules label map renamed CALENDAR_CATEGORIES (public); services no longer imports eduvulcan

### F4 — ExamRank exposes family text in repr

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: entries/eduvulcan/dedup.py:56-61
- **Detail**: `ExamRank.remainder` holds the subject and, for unassigned exams, a child name; a NamedTuple prints it in `repr` (e.g. in tracebacks with locals). `types.py` and `Decision` keep content out of `repr`.
- **Fix**: Make `ExamRank` a frozen dataclass with `field(repr=False)` on `remainder`.
- **Decision**: SKIPPED

### F5 — Exact-duplicate match ignores time and school_subject

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Adherence
- **Location**: entries/eduvulcan/dedup.py:124-141
- **Detail**: Matches the plan's decided fields exactly. A re-send that differs only in `time` (same content/date/member) collapses into the first entry, which keeps the old time. Whether rules can produce that depends on whether the time is reflected in content.
- **Fix**: Leave as decided; revisit only if the corpus shows time-only changes.
- **Decision**: SKIPPED — matches the plan's decided fields
