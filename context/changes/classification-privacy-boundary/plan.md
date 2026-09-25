# Classification Privacy Boundary Implementation Plan

## Overview

Introduce a provider-independent, synchronous classification boundary for FamilyNotes. It will transform a parent’s natural-language instruction into a transient validated proposal or follow-up while enforcing family authorization, OpenAI ZDR requirements, a 25-second deadline, and strict non-retention of sensitive content.

## Current State Analysis

The live application has `Family` and `FamilyMember` models plus explicit access helpers, but no entry/classification domain, service abstraction, provider dependency, or classification route. Provider configuration is intentionally deferred in `.env.example`, and production logging currently relies on application logs, journald, and nginx.

The roadmap treats F-02 as an independent foundation that unlocks S-01 and S-04. Entry persistence, confirmation, and user-facing capture belong to those later slices.

## Desired End State

The codebase exposes a tested application service callable by later views:

- It authorizes an active parent before any provider call.
- It supplies OpenAI only the instruction and active same-family display names.
- It produces a typed proposal, follow-up, or unavailable result.
- It rejects invented, inactive, cross-family, or ambiguous member resolutions.
- It completes or fails safely inside a 25-second application deadline.
- It never stores submitted text, provider payloads, or transient proposals.
- Production enablement fails closed unless ZDR is explicitly attested.

### Key Discoveries:

- `family_access/access.py:6-51` provides reusable membership, parent-role, and family-scope primitives.
- `family_access/models.py:19-38` does not enforce unique display names, so names-only resolution needs explicit ambiguity handling.
- `family_notes/settings.py:24-32` establishes environment parsing conventions.
- `pyproject.toml:5-16` currently has no classifier/provider dependency.
- The OpenAI SDK supports `responses.parse`, Pydantic structured output, client/request timeouts, and configurable retries.
- OpenAI data controls distinguish `store=False` from abuse-monitoring retention; approved project/organization ZDR remains a production prerequisite.
- Production uses synchronous Gunicorn with a 45-second worker timeout and nginx’s 50-second read timeout, leaving room for the application’s stricter 25-second deadline.

## What We're NOT Doing

- No entry or proposal database models or migrations.
- No classification HTTP endpoint, form, template, or browser flow.
- No entry confirmation or persistence.
- No provider conversation, response chaining, files, background mode, tracing, cache, or analytics.
- No deterministic, Jev, agent-framework, or local-LLM implementation.
- No general solution for validation rules beyond the PRD’s defined cases.
- No background worker or queue.
- No change to unrelated F-03 planning/review files.

## Implementation Approach

Create an `entries` Django app as the future owner of entry-domain behavior, initially containing classification contracts, orchestration, and tests only. Keep the domain-facing backend protocol independent of OpenAI. Inject the backend and monotonic clock so authorization, timing, and failure behavior can be tested without network access or sleeps.

Use the OpenAI Responses API with strict Pydantic structured output. Disable SDK-managed retries and implement the agreed application retry policy explicitly: a 10-second attempt timeout, at most one retry for transient failures, and a hard 25-second monotonic deadline. Retry only when the remaining budget can contain another attempt and bounded backoff.

## Critical Implementation Details

### Timing and retries

The OpenAI SDK’s defaults exceed the product budget and include automatic retries. Configure SDK retries to zero, own the single retry in application code, and calculate remaining time with a monotonic clock. Never start an attempt that could overrun the 25-second application deadline.

### Names-only member resolution

Only active same-family display names are sent. A returned name must exactly match an allowed name after Unicode-aware trimming of surrounding whitespace, with spelling and case otherwise preserved. If normalization yields duplicate allowed names, member assignment is ambiguous and must become a follow-up rather than selecting by database order.

### Privacy gate

`store=False` is required on every request but is not sufficient by itself. Production classification remains disabled unless an environment-backed ZDR attestation is true and the required provider settings are present.

## Phase 1: Classification Contract

### Overview

Establish provider-independent domain types, validation rules, and an injectable backend seam without network access or persistence.

### Changes Required:

#### 1. Entry application and classification domain

**Files**: `entries/apps.py`, `entries/classification/types.py`, `entries/classification/backends.py`, `family_notes/settings.py`

**Intent**: Create the owning product app and define strict application contracts that later capture flows can use without depending on OpenAI response types.

**Contract**: Register `entries` as an installed Django app without models or migrations. Define `EntryType` values `todo`, `calendar_event`, and `note`; distinct proposal, follow-up, and unavailable result types; a discriminated `ClassificationResult` union; a backend request containing submitted text, allowed member names, reference date, and locale; and a backend protocol returning provider-neutral structured data. Result and failure types must never retain raw provider payloads.

#### 2. Domain validation

**File**: `entries/classification/validation.py`

**Intent**: Validate semantic rules after structured parsing so schema-valid but unsafe or incomplete provider output cannot become an application proposal.

**Contract**: Calendar events require a date; tests and homework require date and affected member; missing required information produces a follow-up; unrecognized content may become a general note; content must be non-empty and supported by submitted information; returned member names must come from the allow-list; duplicate normalized names never resolve automatically; and validation must not persist inputs or include them in exceptions.

### Success Criteria:

#### Automated Verification:

- Domain and validation tests pass for complete proposals, general-note fallback, required-field follow-ups, unknown names, and duplicate-name ambiguity.
- Tests prove domain result and exception representations do not contain submitted text or raw provider payloads.
- Django system checks pass with the new app and no migrations are generated.

#### Manual Verification:

- Review the public classification types and confirm later S-01 code can consume them without importing OpenAI classes.

**Implementation Note**: After completing this phase and all automated verification passes, pause for manual confirmation before proceeding.

---

## Phase 2: OpenAI Privacy Adapter

### Overview

Add the official OpenAI SDK adapter, environment-backed configuration, structured output, explicit timing policy, and sanitized operational logging.

### Changes Required:

#### 1. Dependency and configuration

**Files**: `pyproject.toml`, `uv.lock`, `family_notes/settings.py`, `.env.example`

**Intent**: Add the official SDK and configure classification without committing secrets or accidentally enabling an unapproved production integration.

**Contract**: Add and lock `openai`; configure an enablement flag, API key, structured-output-capable model, ZDR attestation, 25-second deadline, 10-second attempt timeout, and one application retry. Production-enabled configuration must fail closed without the key, model, and ZDR attestation. Local tests may inject a backend without credentials, and validation must never print secrets.

#### 2. Structured-output adapter

**File**: `entries/classification/openai_backend.py`

**Intent**: Convert the minimum application request into a stateless OpenAI Responses API call and translate the validated response into provider-neutral data.

**Contract**: Use `responses.parse` with a strict Pydantic schema and forbidden extra fields; set `store=False`; send only the instruction, allowed names, reference date, locale, and concise classification instructions; avoid Conversations, response chaining, Files, Assistants, Threads, background mode, sensitive metadata, and tracing; and reject refusals, incomplete responses, absent parsed output, and schema-invalid output.

#### 3. Deadline, retry, and safe logging

**File**: `entries/classification/openai_backend.py`

**Intent**: Keep synchronous request time bounded and provide enough operational evidence to diagnose failures without retaining family content.

**Contract**: Disable SDK retries; apply a 10-second timeout and 25-second monotonic deadline; retry once only for timeout, connection, rate-limit, and 5xx failures when the remaining budget permits; do not retry refusal, malformed output, authentication, or other non-transient 4xx failures; normalize failures; and log only provider, safe outcome category, status, request ID, elapsed milliseconds, and attempt count. Create no classification records, analytics, metrics store, or trace.

### Success Criteria:

#### Automated Verification:

- Mocked adapter tests verify strict parsing, `store=False`, the minimal payload, configured model, and absence of stateful OpenAI features.
- Deterministic clock/transport tests cover first-attempt success, eligible retry, insufficient retry budget, exact deadline, timeout, rate limit, connection failure, 5xx, refusal, malformed output, and non-retryable 4xx.
- Log-capture tests use unique sensitive sentinels and prove submitted text, member names, response content, exception bodies, and credentials never appear.
- Locked dependency audit and Django system checks pass.

#### Manual Verification:

- An operator confirms the selected production OpenAI project is approved and configured for ZDR before setting the enablement and ZDR-attestation flags.

**Implementation Note**: After completing this phase and all automated verification passes, pause for manual confirmation before proceeding.

---

## Phase 3: Authorized Orchestration

### Overview

Compose the provider-independent classifier with existing family-access helpers so no unauthorized request reaches OpenAI and no returned member escapes the authenticated family boundary.

### Changes Required:

#### 1. Parent classification service

**File**: `entries/classification/service.py`

**Intent**: Provide the single application entry point later used by S-01 while keeping authorization, candidate selection, provider invocation, and validation in one auditable boundary.

**Contract**: Accept the authenticated user, submitted text, reference date/time, locale, and injected backend; require an active parent before calling the backend; load only active same-family members; send only display names; resolve one exact unique matching membership locally; return a follow-up for duplicate-name ambiguity; reject unknown, inactive, and cross-family results; and return transient domain objects without database writes.

#### 2. Access and orchestration tests

**File**: `entries/tests/test_classification_service.py`

**Intent**: Prove family access is enforced at the service boundary rather than assumed from later views.

**Contract**: Cover active parent success and child, inactive membership/family, unconfigured user, and anonymous denial; verify no backend call for unauthorized users; cover inactive, duplicate, invented, and cross-family candidates; and assert zero classification or entry persistence on every path.

### Success Criteria:

#### Automated Verification:

- The authorization matrix proves only an active parent can invoke the backend and unauthorized attempts make zero provider calls.
- Candidate and resolution tests prove only active same-family names are sent and ambiguous, unknown, inactive, or cross-family results never resolve to a membership.
- Database assertions prove classification success, follow-up, and failure create no persistent records.

#### Manual Verification:

- Review one representative service call and confirm its outbound candidate list contains no database IDs or members from another family.

**Implementation Note**: After completing this phase and all automated verification passes, pause for manual confirmation before proceeding.

---

## Phase 4: Verification and Release Contract

### Overview

Complete representative functional validation and document the privacy/configuration gates required before this foundation can be enabled in production.

### Changes Required:

#### 1. Representative acceptance corpus

**File**: `entries/tests/test_classification_acceptance.py`

**Intent**: Verify the boundary against the defined Polish school-event case and adjacent privacy/failure cases without nondeterministic live calls in the normal suite.

**Contract**: Include the PRD example with explicit reference date and expected Monday; cover Polish relative dates, calendar entries, tests/homework, general notes, missing fields, duplicate names, and invented details; keep normal tests mocked; and make live evaluation opt-in with synthetic data only.

#### 2. Deployment and operator documentation

**Files**: `.env.example`, relevant deployment/runbook configuration documentation

**Intent**: Make production enablement explicit and auditable without exposing secrets or changing the established manual SSH release process.

**Contract**: Document provider key/model, enablement, and ZDR attestation variables; state that `store=False` does not replace ZDR approval; require ZDR evidence; add a synthetic post-release classification smoke check; require sensitive-sentinel log inspection; and preserve the existing release flow, worker count, and proxy timeouts.

### Success Criteria:

#### Automated Verification:

- The representative acceptance suite passes, including the PRD date example and all defined follow-up, ambiguity, and failure cases.
- Full Django tests, Django checks, migration dry-run, and locked dependency audit pass.
- A wall-clock integration test with a controlled fake transport proves every outcome returns within 25 seconds without real sleeps in unit tests.
- A repository scan confirms no real provider key, submitted family text fixture, or provider payload fixture is committed.

#### Manual Verification:

- Using synthetic data, an opt-in production-like smoke test returns a proposal or safe failure within 30 seconds.
- Operator review confirms ZDR evidence, protected environment configuration, and sensitive-sentinel absence from application, journald, and nginx logs.

**Implementation Note**: Phase 4 completes F-02 evidence but does not authorize S-01 entry persistence or UI work.

## Testing Strategy

### Unit Tests:

- Strict result-schema and semantic validation.
- Required date/member and general-note behavior.
- Exact allowed-name resolution and duplicate-name ambiguity.
- Retry eligibility, remaining-budget calculation, and deadline exhaustion.
- Failure normalization and sensitive-data exclusion from exceptions/logs.

### Integration Tests:

- Active-parent orchestration through a fake backend.
- Full family-access denial matrix with proof of zero backend calls.
- OpenAI adapter exercised through a mocked transport.
- Configuration validation for disabled, development, and production-enabled states.
- Zero database writes across success, follow-up, and failure outcomes.

### Manual Testing Steps:

1. Confirm the production OpenAI project has approved and enabled ZDR.
2. Enable classification using protected environment variables without printing values.
3. Submit only a synthetic Polish school instruction.
4. Verify a proposal or safe failure returns inside 30 seconds.
5. Search application, journald, and nginx logs for the synthetic sentinel and verify it is absent.
6. Disable classification again if ZDR evidence or any privacy check is incomplete.

## Performance Considerations

Classification stays synchronous for the low-traffic MVP. The 25-second application deadline remains below Gunicorn’s 45-second and nginx’s 50-second limits. No request caching or background processing is allowed. A separate worker is deferred until observed concurrency or memory pressure justifies it.

## Migration Notes

No database migration or existing-data transformation is expected. Rollback consists of disabling classification and deploying the previous application release; no classification data requires cleanup.

## References

- Related research: `context/changes/classification-privacy-boundary/research.md`
- Options research: `context/changes/classification-privacy-boundary/classification-options-research.md`
- OpenAI implementation research: `context/changes/classification-privacy-boundary/openai-sdk-implementation-doc.md`
- Product contract: `context/foundation/prd.md`
- Roadmap contract: `context/foundation/roadmap.md`
- Access helpers: `family_access/access.py:6-51`
- Family member model: `family_access/models.py:19-38`
- OpenAI structured output: `https://github.com/openai/openai-python/blob/main/examples/responses/structured_outputs.py`
- OpenAI data controls: `https://developers.openai.com/api/docs/guides/your-data`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles.

### Phase 1: Classification Contract

#### Automated

- [ ] 1.1 Domain and validation tests pass for complete proposals, general-note fallback, required-field follow-ups, unknown names, and duplicate-name ambiguity.
- [ ] 1.2 Tests prove domain result and exception representations do not contain submitted text or raw provider payloads.
- [ ] 1.3 Django system checks pass with the new app and no migrations are generated.

#### Manual

- [ ] 1.4 Review the public classification types and confirm later S-01 code can consume them without importing OpenAI classes.

### Phase 2: OpenAI Privacy Adapter

#### Automated

- [ ] 2.1 Mocked adapter tests verify strict parsing, `store=False`, the minimal payload, configured model, and absence of stateful OpenAI features.
- [ ] 2.2 Deterministic clock/transport tests cover first-attempt success, eligible retry, insufficient retry budget, exact deadline, timeout, rate limit, connection failure, 5xx, refusal, malformed output, and non-retryable 4xx.
- [ ] 2.3 Log-capture tests use unique sensitive sentinels and prove submitted text, member names, response content, exception bodies, and credentials never appear.
- [ ] 2.4 Locked dependency audit and Django system checks pass.

#### Manual

- [ ] 2.5 An operator confirms the selected production OpenAI project is approved and configured for ZDR before setting the enablement and ZDR-attestation flags.

### Phase 3: Authorized Orchestration

#### Automated

- [ ] 3.1 The authorization matrix proves only an active parent can invoke the backend and unauthorized attempts make zero provider calls.
- [ ] 3.2 Candidate and resolution tests prove only active same-family names are sent and ambiguous, unknown, inactive, or cross-family results never resolve to a membership.
- [ ] 3.3 Database assertions prove classification success, follow-up, and failure create no persistent records.

#### Manual

- [ ] 3.4 Review one representative service call and confirm its outbound candidate list contains no database IDs or members from another family.

### Phase 4: Verification and Release Contract

#### Automated

- [ ] 4.1 The representative acceptance suite passes, including the PRD date example and all defined follow-up, ambiguity, and failure cases.
- [ ] 4.2 Full Django tests, Django checks, migration dry-run, and locked dependency audit pass.
- [ ] 4.3 A wall-clock integration test with a controlled fake transport proves every outcome returns within 25 seconds without real sleeps in unit tests.
- [ ] 4.4 A repository scan confirms no real provider key, submitted family text fixture, or provider payload fixture is committed.

#### Manual

- [ ] 4.5 Using synthetic data, an opt-in production-like smoke test returns a proposal or safe failure within 30 seconds.
- [ ] 4.6 Operator review confirms ZDR evidence, protected environment configuration, and sensitive-sentinel absence from application, journald, and nginx logs.
