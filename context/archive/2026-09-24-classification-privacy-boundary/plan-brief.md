# Classification Privacy Boundary — Plan Brief

> Full plan: `context/changes/classification-privacy-boundary/plan.md`
> Research: `context/changes/classification-privacy-boundary/research.md`

## What & Why

Build the privacy-controlled classification foundation used by later entry-capture slices. An authenticated parent’s instruction may be sent to OpenAI only to produce a transient, editable proposal or follow-up; it must not create an entry, secondary record, analytic event, or provider-side application state.

## Starting Point

FamilyNotes already has active-membership, parent-role, and family-scoping helpers in `family_access/access.py`, but no classifier, entry model, classification route, provider dependency, or provider configuration. Production uses synchronous Gunicorn on a small Mikr.us instance.

## Desired End State

Application code can authorize a parent, submit the minimum classification payload, and return a validated proposal, a follow-up for missing or ambiguous information, or a sanitized unavailable result within a 25-second application deadline. The submitted instruction and provider payload remain transient, and no entry is persisted in this change.

## Key Decisions Made

| Decision | Choice | Why | Source |
| --- | --- | --- | --- |
| Provider | OpenAI Responses API with approved ZDR | Best match for Polish natural-language extraction while satisfying the privacy boundary | Plan |
| Architecture | Application-owned backend interface | Prevents provider types from becoming domain contracts | Research |
| Scope | Service boundary only | Keeps F-02 separate from the S-01 capture flow | Plan |
| Content | Grounded concise title | Matches the PRD’s school-event example while remaining parent-editable | Plan |
| Member reference | Allowed display names only | Keeps the provider payload human-readable while local validation owns identity | Plan |
| Timing | 25-second deadline, at most one bounded retry | Leaves response overhead within the 30-second product limit | Plan |
| Operations | Minimal safe logs | Provides diagnostics without retaining family text or provider payloads | Plan |
| Persistence | None before later parent confirmation | Required by the PRD and privacy boundary | Research |

## Scope

**In scope:**

- Classification domain types and backend protocol.
- OpenAI structured-output adapter with `store=False`.
- Active-parent authorization and same-family candidate selection.
- Exact-name, duplicate-name, domain-rule, and grounded-content validation.
- Deadline, retry, sanitized failures, and safe operational logging.
- ZDR/configuration release gate and automated privacy tests.

**Out of scope:**

- HTTP endpoints, forms, templates, or capture UI.
- Entry/proposal database models, migrations, confirmation, or persistence.
- Parent CRUD and child entry views.
- Follow-up conversation state or provider conversations.
- Analytics, tracing, caching, background jobs, and local-LLM/Jev adapters.

## Architecture / Approach

`entries` will own an application-facing classification service and strict result types. The service authorizes the caller through `family_access`, builds the active same-family display-name allow-list, and calls an injectable backend. The OpenAI adapter uses the Responses API and Pydantic structured output. Application validation converts the response into a proposal or follow-up; provider errors become a sanitized unavailable outcome.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Classification contract | Provider-independent types, validation, and backend seam | Letting provider schema leak into domain code |
| 2. OpenAI privacy adapter | Structured output, configuration, deadline, retry, and safe logs | Retention or retry behavior violating the boundary |
| 3. Authorized orchestration | Parent authorization and family-safe member resolution | Names being ambiguous or resolved across families |
| 4. Verification and release contract | Privacy, Polish-language, timing, and production-gate evidence | Enabling production without verified ZDR |

**Prerequisites:** Current F-01 access helpers; OpenAI organization/project eligible for ZDR before production enablement.
**Estimated effort:** Approximately 3–4 focused implementation sessions across four phases.

## Open Risks & Assumptions

- Production classification remains disabled until ZDR is approved, configured, and operator-attested.
- Display names are not guaranteed unique. Duplicate normalized names produce a follow-up rather than arbitrary assignment.
- A concise title is constrained through instructions and representative evaluation; semantic grounding cannot be proven solely by JSON-schema validation.
- Provider outages return a sanitized unavailable result within 25 seconds rather than fabricating a proposal or follow-up.
- Synchronous classification is acceptable for the MVP’s low traffic; no background worker is introduced.

## Success Criteria (Summary)

- Only an active parent can invoke classification, and OpenAI sees only the instruction plus active same-family display names.
- A valid result is returned within the application deadline without persisting raw text, proposals, or provider responses.
- Tests prove safe handling of ambiguity, malformed output, refusal, timeout, retries, provider errors, and sensitive-log leakage.
