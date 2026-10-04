---
date: 2026-10-04T09:07:56+02:00
researcher: Claude Code (claude-opus-5-5)
git_commit: 199cfdb3e69192ccd7630432afedabe743da3442
branch: master
repository: 10xdev
topic: "Ground Risk #5 of test-plan.md: classification saves the wrong child, date, or entry type, or exposes submitted family text"
tags: [research, classification, openai, eduvulcan, privacy, follow-up, test-oracle]
status: complete
last_updated: 2026-10-04
last_updated_by: Claude Code (claude-opus-5-5)
---

# Research: Risk #5 — classification correctness and privacy

**Date**: 2026-10-04T09:07:56+02:00
**Researcher**: Claude Code (claude-opus-5-5)
**Git Commit**: 199cfdb3e69192ccd7630432afedabe743da3442 (working tree: `context/foundation/roadmap.md` modified; no inspected source file is uncommitted)
**Branch**: master
**Repository**: 10xdev

## Research Question

Ground Risk #5 of `context/foundation/test-plan.md` §2: "Classification saves the
wrong child, date, or entry type, or exposes submitted family text". The guidance
asks for proof that requirements-derived examples produce the correct proposal or
follow-up without sensitive-data leakage. It must challenge "current
implementation output is an independent oracle", and it must ground product
rules, the provider boundary, error translation, logs and persisted state. The
cheapest layer is deterministic unit/contract tests plus narrow integration
tests. The anti-pattern is expected values copied from production logic.

## Summary

The three values in this risk are produced by different mechanisms. The right
oracle and test layer depend on which mechanism owns each value:

| Value | Who decides it | Deterministic oracle possible? |
|---|---|---|
| **Child** | Code. The model returns a name; `validate_output` requires an exact allow-list match after `strip()` (`entries/classification/validation.py:36-38`, `:61-71`). Duplicates become an `AMBIGUOUS_MEMBER` follow-up on the parent path (`:68-69`); the service resolves locally and fails closed (`service.py:250-268`). EduVulcan rules match children deterministically (`entries/eduvulcan/children.py`), and the family classification fallback resolves to the newest matching child (`service.py:373-377`, `:383-388`). | Yes. Already strong. |
| **Entry type / required fields** | Code overrides the model when it returns a school kind: the kind fixes the type and required fields (`validation.py:73-83`; `types.py:36-49`). Without a kind, the model's `todo`/`calendar_event`/`note` is used as returned. `None` becomes a general note (`validation.py:49-50`, `:108-112`). | Yes for the kind→type/required-field table. Model choice of kind/type is not deterministic. |
| **Date** | **The model**, from `data_odniesienia` and `dzien_tygodnia` (`openai_backend.py:110-131`). Code checks only that the model's `date_source` phrase occurs literally in the parent's text (`openai_backend.py:335`, `:359-372`). It does **not** check that the date value matches the phrase. | Only for EduVulcan fixed rules (`rules.py`) and for code-side checks. The manual path has no deterministic oracle today. |

This was a deliberate, documented decision. "The relative-date arithmetic is the
model's (F-02); the parent corrects it in the review form"
(`context/archive/2026-09-27-first-school-event-capture/plan-brief.md:75`;
restated in `context/changes/missing-info-follow-up/plan-brief.md:73`). The
latest review states that the literal-fragment check "does not prove semantic
date correctness" (`context/changes/missing-info-follow-up/plan.md:256`).

Consequences for this risk:

1. **Parent capture path.** Nothing is saved before the parent confirms the
   review form (`entries/views.py:132-135` docstring, `:186-200`). A wrong date
   is a *proposal* error that the parent can correct (FR-005). Saved state
   equals the posted, re-validated form.
2. **EduVulcan classification fallback.** Here a model-produced date, type and
   child are **saved without review** (`entries/eduvulcan/conversion.py:289-316`).
   This only happens for notifications the fixed rules cannot interpret
   (`conversion.py:283-287`). This is the path where the "wrong date saved"
   scenario can occur with no human gate.
3. **The existing offline date assertions are circular.** The acceptance corpus
   says so: "The model does the date arithmetic; these tests assert that the
   reference date and weekday are sent and that the returned date flows
   unchanged into the proposal"
   (`entries/tests/test_classification_acceptance.py:7-9`).
   - Its test data pairs `date_source='w poniedziałek'` (Monday) with
     2026-09-22 and 2026-09-24 (`:240-255`). 2026-09-21 is the PRD's Monday,
     so those are a Tuesday and a Thursday, and the tests pass.
   - The US-01 date 2026-09-21 is verified against a real model only in opt-in
     live tests (`CLASSIFICATION_LIVE_EVAL=1`).

**Privacy is well defended on the inspected paths.**
- `store=False` is set on every request.
- Prompt-injection framing is in the instructions.
- Logging is content-free: one line per call with provider, outcome, status,
  request id, elapsed time and attempts.
- Errors carry `UnavailableReason` codes only.
- Family-text fields are excluded from `repr`, and the service entry points and
  POST parameters are marked sensitive.
- Sentinel-based tests exist.

The remaining exposure surfaces are bounded and mostly accepted:
- OpenAI abuse-monitoring retention, because ZDR was deferred by the owner.
- Raw EduVulcan text in `pending`/`processing`/`failed` rows, which is never
  pruned.
- A few test blind spots, listed below.

## Detailed Findings

### 1. Child resolution

- **Parent path:**
  - The allow-list is the active members of the parent's family, sent as display
    names only (`service.py:110-118`, `:243-247`).
  - Matching is case- and diacritic-sensitive (exact match after `strip()`).
  - An unknown, inactive or other-family name gives `UNKNOWN_MEMBER`.
  - A duplicate display name gives an `AMBIGUOUS_MEMBER` follow-up.
  - Tests: contract `test_classification_contract.py:288`, `:297`, `:307`;
    service `test_classification_service.py:306`, `:317`, `:328`, `:348`
    (anchors from the coverage worker).
- **EduVulcan path:**
  - Fixed rules use case-insensitive matching that still requires diacritics, and
    the newest child wins a tie. Owner-accepted:
    `context/changes/eduvulcan-school-event-intake/plan-brief.md:23`, `:62`.
  - Fallback classification sends de-duplicated child names (`service.py:383-388`).
  - The two paths therefore follow deliberately different policies. No test pins
    the difference as a product decision; the coverage worker reported gap 9.

### 2. Dates

- **Reference date:**
  - Parent path: `timezone.localdate()` with `TIME_ZONE='Europe/Warsaw'`
    (`views.py:102`, `:146`).
  - EduVulcan: the local capture date (`entries/eduvulcan/rules.py:128-134`).
- **Answer step:** the follow-up answer recomputes the reference date at answer
  time (`views.py:146`), not at original submission. If the parent answers after
  local midnight, relative phrases in the *original* instruction are re-sent with
  the new reference date. This is an inference from the code; no test or
  document addresses it.
- **Date grounding** (`openai_backend.py:359-372`):
  - The fragment is compared after casefold, whitespace collapse and quote
    normalization.
  - Diacritics are not folded. A model echo of "w piatek" for "w piątek" drops
    the date, so the parent sees the follow-up or fallback. This fails safe.
  - No check covers weekday consistency, a past date, or `date ≥ reference_date`.
  - Past dates trigger an advisory hint only and do not block confirmation
    (`missing-info-follow-up/plan.md:252`).
- **Time:** `parsed.time` passes through unchecked (`openai_backend.py:336`).
  The prompt asks for time only when it is stated; nothing in code enforces that.
- **EduVulcan fixed rules:** these have literal, requirement-derived tests for
  year inference (±6-month window), year-end crossing and the Warsaw day boundary
  (`test_eduvulcan_rules.py:373-441`, per coverage worker). This is the
  strongest date oracle in the repository.

### 3. Entry type and follow-ups

- **Kind table:** the kind→type/required-field table (`types.py:43-51`) matches
  PRD Business Logic (`context/foundation/prd.md:128-134`):
  - homework, class test, test and quiz → calendar event that requires a date
    and a member;
  - substitution and room change → note that requires a date;
  - lucky number, grade and late arrival → note with no required fields.
- **Contract tests:** `test_classification_contract.py:195-216` encodes this as
  a literal table. `:219` derives its event-kind set from production
  (`k.entry_type`), which is a mild anti-pattern.
- **Follow-up merge:** only missing fields are taken from the answer
  (`service.py:200-215`). A tampered `missing` list is recomputed
  (`test_follow_up_views.py:212`, per worker). Skipping saves nothing; it renders
  a note review form (`views.py:155-161`).

### 4. Privacy boundary

- **Payload** (`openai_backend.py:134-151`):
  - reference date, weekday, locale, allowed names, instruction;
  - on a follow-up only, the question and the answer.
  - Request options: `store=False`, a strict schema, `max_output_tokens=1024`,
    and optional reasoning effort.
  - Not sent: user, metadata or safety identifier.
  - Input caps: 2000 characters for the instruction and 500 for the answer
    (`service.py:64-66`).
- **Logs:** `openai_backend.py:236-248` logs safe fields. The conversion and
  worker loggers log IDs, codes and exception class names only. No
  `logger.exception` and no `str(exc)` were found in these paths (privacy
  worker's sweep).
- **Retention:**
  - Web capture keeps no server-side draft. Text round-trips through hidden form
    fields (`forms.py:275-293`, `:340-357`). On an unavailable outcome the review
    form is pre-filled with the raw text (`forms.py:248`).
  - EduVulcan raw text is pruned after 90 days, but **only for `processed`
    rows** (`conversion.py:489-515`). `failed` rows stay visible to superusers in
    admin indefinitely.
- **ZDR:** deferred until after the MVP by owner decision; OpenAI may retain
  traffic for abuse monitoring
  (`context/archive/2026-09-24-classification-privacy-boundary/change.md:14-19`).
- **Open review findings, still true in code:**
  - F-02 F6: an infinite deadline passes validation (`settings.py:122`, which checks only `> 0`).
  - S-01 F6: the capture view's `text` local is not under
    `@sensitive_variables` (`views.py:82` has `sensitive_post_parameters`
    only). It matters only on a DEBUG technical 500 page.

### 5. Existing test base vs this risk

The coverage worker reviewed ten test files. Its anchors that I re-checked are
`test_classification_acceptance.py:1-12`, `:240-255` and
`test_openai_backend.py:539-547`.

- **Strong:**
  - EduVulcan rules use literal oracles.
  - The kind table is tested.
  - Child allow-list and ambiguity are covered.
  - Follow-up merge and tamper resistance are covered.
  - Form round-trip from correction to save is covered.
  - Sentinel checks cover repr, exceptions and logs.
- **Gaps:**
  1. No deterministic check that a relative or weekday phrase yields the right
     date on the manual or fallback path. All offline dates are scripted fake
     outputs.
  2. Test fixtures with a date that contradicts its evidence pass (`acceptance
     :240-255`; `test_openai_backend.py:539-547` pairs "W piątek" from Thursday
     2026-09-17 with 2026-09-25, while follow-up tests use 2026-09-18).
  3. `timezone.localdate` is mocked in every view test. Nothing tests the
     Warsaw-midnight boundary on the parent path.
  4. Expected values are copied from production or from the fake in these
     places:
     - `test_family_classification.py:147`, `:159` (imports
       `TRANSIENT_UNAVAILABLE_REASONS`);
     - `test_classification_contract.py:219`;
     - `test_classification_acceptance.py:230`, `:317`.
  5. Log-privacy capture details:
     - `entries.eduvulcan` has `propagate=False` (`settings.py:378-382`), so
       root-handler capture misses it.
     - Both app loggers are at INFO level (`:380`, `:388`).
     - Scans read `getMessage()` only.
  6. No test asserts that `confirm` never calls the classifier.
  7. No test of raw-text exposure for `failed` EduVulcan rows. This is
     consistent with the code; whether it is acceptable is undecided.
  8. Live tests are opt-in, nondeterministic and cover few cases. Not a CI gate.

## Code References

- `entries/classification/service.py:84-126` — parent classification, allow-list, local member resolution
- `entries/classification/service.py:313-380` — family (EduVulcan) classification fallback
- `entries/classification/validation.py:45-95` — semantic validation; kind overrides type
- `entries/classification/types.py:36-51` — school-kind table
- `entries/classification/openai_backend.py:110-151` — prompt and payload; `:259-272` request kwargs; `:335-336` date/time translation; `:359-372` date grounding
- `entries/views.py:85-125` capture, `:129-183` answer, `:186-200` confirm
- `entries/forms.py:240-250` — review form initial values (raw text on unavailable)
- `entries/eduvulcan/conversion.py:276-322` — rules → classification → note, saved without review
- `family_notes/settings.py:367-392` — LOGGING

## Architecture Insights

- The backend seam (`ClassificationBackend`, `backends.py:63-67`) is the correct
  fake boundary. Everything downstream of `BackendOutput` (validation, kind
  override, member resolution, follow-up merge, form round-trip, persistence) is
  deterministic and can be checked against literal PRD examples.
- The model's own judgment (date arithmetic, choice of kind/type, extracted
  content) cannot be checked by deterministic tests at all: a scripted fake only
  returns what the test author typed. The cheapest honest options are:
  - code-side invariants that hold for *any* model output, such as the weekday
    of the date matching the weekday named in `date_source`, or the date being
    on or after the reference date for future-tense phrases. These are product
    rules that do not exist today;
  - a small opt-in live evaluation corpus with literal PRD expectations, run
    outside CI.
  Choosing between them is a product/plan decision.
- EduVulcan fixed rules already show the deterministic alternative for
  categories with a known format.

## Historical Context (from prior changes)

- `context/archive/2026-09-27-first-school-event-capture/plan-brief.md:75` —
  "relative-date arithmetic is the model's … the parent corrects it". **Verdict:
  supported** by `openai_backend.py:115-131` and `validation.py`, which contains
  no date-value check.
- `context/changes/missing-info-follow-up/plan.md:250-256` — `date_source`
  literal check added after live checks exposed invented and past dates;
  `gpt-5.4-nano` with effort `none` recommended in `8849d1e`, "This review did
  not independently repeat those paid checks". **Verdict: supported** (commit
  stat confirms docs-only changes, per worker).
- `context/archive/2026-09-24-classification-privacy-boundary/change.md:14-19` —
  ZDR deferred; `store=False`, minimal payload and sanitized logging unchanged.
  **Verdict: supported** (`openai_backend.py:9-14`).
- F-02 `plan-brief.md` still says production stays disabled until ZDR approval
  (per decisions worker: `:22,40,61,63,68`). **Verdict: contradicted** by the
  later `change.md:14-19` decision and by the code.
- `context/changes/deployment/mikrus-runbook.md:860-862` — "No page uses
  classification yet". **Verdict: contradicted**: `views.py:103`, `:166` and
  `conversion.py:289` call it.
- Manual rows: S-05 4.7 (operator privacy review of logs, admin and health) is
  unchecked (`eduvulcan-school-event-intake/plan.md:374`). In F-02, 2.5 and the
  ZDR part of 4.6 are `[x]` with SKIPPED annotations (per decisions worker).

## Related Research

- `context/changes/testing-eduvulcan-intake-durability/research.md` — Risk #4. It
  shares the EduVulcan conversion path; the unreviewed fallback save is where the
  two risks meet.
- `context/archive/2026-09-24-classification-privacy-boundary/research.md` and
  `classification-options-research.md` — original provider and privacy analysis.

## Open Questions

1. **Date oracle.** Should the plan add code-side date invariants (product rules
   that would reject or flag model output), rely on an opt-in live corpus, or
   both? Adding invariants changes production behavior, not just tests, so it
   needs an explicit owner decision.
2. **EduVulcan fallback without review.** Is a model-dated entry saved without
   confirmation acceptable as is (PRD FR-010 accepts after-the-fact correction),
   or should the fallback demand stronger evidence before trusting a date?
3. **Child-matching policy.** The parent and EduVulcan paths differ in case and
   tie handling. Pin both as accepted behavior in tests, or align them?
4. **Raw text in non-processed EduVulcan rows.** Is indefinite retention of
   `failed` rows acceptable, or does the privacy NFR need a cap? This needs an
   owner decision before any test asserts it.
5. **Operator privacy review (S-05 4.7).** Does it belong to this change, or
   should it be done once in production?
