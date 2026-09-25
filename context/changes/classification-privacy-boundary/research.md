---
date: 2026-09-25T06:53:36+02:00
researcher: Codex
git_commit: 6976bae99e414406304d058483bdbd8e9181537b
branch: master
repository: FamilyNotes
topic: "Classification privacy boundary"
tags: [research, codebase, classification, privacy, family-access]
status: complete
last_updated: 2026-09-25
last_updated_by: Codex
---

# Research: Classification Privacy Boundary

**Date**: 2026-09-25T06:53:36+02:00
**Researcher**: Codex
**Git Commit**: 6976bae99e414406304d058483bdbd8e9181537b
**Branch**: master
**Repository**: FamilyNotes

## Research Question

What product contracts, code integration points, existing safeguards, historical decisions, and unresolved choices define roadmap item F-02, Classification Privacy Boundary?

## Summary

F-02 has a clear product boundary but no runtime implementation in the inspected application. The current requirement is that a parent receives a proposal containing type, date, content, and affected family member, reviews and corrects it before persistence, and receives either a proposal or follow-up within 30 seconds. Submitted classification text may be used to produce and save the requested entry, but not for secondary storage, analytics, or training (`context/foundation/prd.md:75-82`, `context/foundation/prd.md:93-106`, `context/foundation/roadmap.md:87-98`).

At revision `6976bae99e414406304d058483bdbd8e9181537b`, the inspected live schema contains the two family-access models `Family` and `FamilyMember`; it contains no entry or classification model. The inspected routes contain home, account, authentication, admin, and health endpoints, with no entry-submission endpoint (`family_access/models.py:6-50`, `family_notes/urls.py:22-27`). The dependency manifest contains five runtime dependency entries and no classification/provider package (`pyproject.toml:5-11`). Therefore the current privacy boundary is a planning contract, not an enforced application behavior.

The existing access helpers are suitable inputs to the future boundary: they resolve an active user membership, identify a parent, scope a queryset to that membership's family, and reject cross-family or non-child assignment targets (`family_access/access.py:6-51`). A future classification mutation still has to call those helpers, minimize provider input, validate the returned member against the same family, avoid sensitive logging/storage, enforce the 30-second wall-clock outcome, and persist only a parent-confirmed entry.

The active drafts do not settle the provider. They recommend an application-owned backend interface and identify deterministic rules, Jev, and a direct structured-output SDK as candidates, while leaving privacy evidence, Polish-language quality, and deterministic-only adequacy open (`context/changes/classification-privacy-boundary/classification-options-research.md:33-50`, `context/changes/classification-privacy-boundary/classification-options-research.md:63-68`). Those external-provider assertions were not independently refreshed in this codebase research and must be revalidated before a provider decision.

## Detailed Findings

### Settled product and privacy contract

- The accepted capture flow is parent submission through one text field, classification into `todo`, `calendar event`, or `note`, and extraction of date, content, and affected family member (`context/foundation/prd.md:75-82`, `context/foundation/prd.md:100-106`).
- Parent review, correction, and confirmation occur before the proposed entry is saved (`context/foundation/prd.md:38`, `context/foundation/prd.md:81-82`).
- For the defined MVP cases, a test or homework requires an affected member and date; a calendar entry requires a date and may omit time. A missing required value produces a follow-up before proposal confirmation (`context/foundation/prd.md:102-106`). Rules outside tests, homework, and calendar entries remain an explicit nonblocking product question (`context/foundation/prd.md:125-127`).
- The response-time condition runs from text submission to either a classified proposal or a follow-up question and is bounded at 30 seconds. The PRD sets no target below that threshold (`context/foundation/prd.md:93-98`, `context/foundation/prd.md:116-123`).
- The purpose limitation is stated as no use beyond producing and saving the requested entry; the F-02 roadmap text specifically names secondary storage, analytics, and training as prohibited reuse (`context/foundation/prd.md:98`, `context/foundation/roadmap.md:87-98`). The documents do not define whether necessary transient processing or operational metadata counts as use, so the implementation must make that interpretation explicit.
- Family-data access is a separate mandatory boundary: a parent can manage family entries, an assigned child can read its entries without mutation rights, and an unauthenticated user cannot access family data (`context/foundation/prd.md:108-114`).

### Current application surface

- The inspected live domain schema defines `Family` and `FamilyMember`, including parent/child roles, active flags, timestamps, and family/user relations (`family_access/models.py:6-50`). No entry, classification proposal, raw-input, provider-response, or processing-state model appears in the inspected app and migration files.
- `get_active_membership` filters by the authenticated user and active family membership; `require_active_membership` rejects a missing result (`family_access/access.py:6-21`). `is_parent` checks the active parent role (`family_access/access.py:24-30`).
- `scope_queryset_to_family` returns no rows for an absent/inactive membership and otherwise applies a family filter. `can_read_assigned_child` rejects inactive, non-child, and cross-family targets, then permits a parent or that exact child membership (`family_access/access.py:33-51`). These are reusable primitives, not automatic enforcement: the inspected route set has no classification mutation that invokes them (`family_notes/urls.py:22-27`).
- The inspected settings include database and authentication configuration but no provider identifier, model, timeout, retry budget, feature flag, or classification input/output limit (`family_notes/settings.py:24-54`, `family_notes/settings.py:104-140`, `family_notes/settings.py:161-188`). `.env.example` contains a commented placeholder to add an AI-provider key after integration exists (`.env.example:23-29`).
- In the inspected Python application paths, explicit error sanitization is limited to `/healthz/`, which converts a database failure into a generic 503 response (`family_notes/views.py:10-18`). No project `LOGGING` setting or classification logger exists in those paths. This negative finding does not cover third-party defaults or infrastructure outside the repository.

### Enforceable boundary for planning

The existing sources support the following implementation contract; the exact service and model design remain planning work:

1. Authorize an active parent before classification by composing the existing membership and parent checks (`family_access/access.py:6-30`).
2. Derive allowed member candidates from the authenticated membership's family and reject returned or submitted cross-family targets (`family_access/access.py:33-51`; `context/foundation/prd.md:108-114`).
3. Send no more than the submitted instruction and the minimum allowed candidates. Do not create provider conversations, secondary records, analytics events, caches, traces, or exception/log fields containing the submitted text or provider payload (`context/changes/classification-privacy-boundary/classification-options-research.md:41-50`).
4. Return a validated proposal or follow-up within the 30-second product boundary; a timeout, malformed output, refusal, or provider failure must not create a partial family entry (`context/foundation/prd.md:93-106`). The precise retry and failure UX is not yet specified.
5. Persist an entry only after parent review and confirmation, using family-scoped identifiers resolved by application code rather than model-generated database identifiers (`context/foundation/prd.md:81-82`; `context/changes/classification-privacy-boundary/openai-sdk-implementation-doc.md:189`).
6. Verify parent success plus child, other-family, and unauthenticated denial on applicable mutation/read paths, consistent with the repository's access-testing convention (`context/changes/deployment/deployment-plan.md:145-156`).

### Provider and deployment constraints

- No provider SDK or deterministic classification dependency is installed in `pyproject.toml:5-16`; provider variables are likewise deferred until implementation in the deployment plan (`context/changes/deployment/deployment-plan.md:84-92`).
- The current production decision is Mikr.us 3.0 with dedicated Mikrus PostgreSQL, manual SSH releases, and one production instance; it explicitly supersedes the older Railway and shared-PostgreSQL documents (`context/changes/deployment/deployment-plan.md:32-36`, `context/changes/deployment/deployment-plan.md:163-168`).
- The deployment plan starts with one or two synchronous Gunicorn workers and calls for monitoring memory before increasing concurrency (`context/changes/deployment/deployment-plan.md:38-44`). Its OOM procedure reduces concurrency and defers a separate classification worker until observed load justifies it (`context/changes/deployment/deployment-plan.md:118-121`).
- The production logging contract excludes family-entry text and AI-provider payloads, but monitoring and log controls are recorded as pending unless later evidence marks them complete (`context/changes/deployment/deployment-plan.md:123-133`, `context/changes/deployment/deployment-plan.md:158-161`).

## Code References

- `family_access/access.py:6-51` - Active membership, parent-role, family-scope, and assigned-child access primitives.
- `family_access/models.py:6-50` - Current family domain schema.
- `family_notes/urls.py:22-27` - Current route set; no entry or classification endpoint.
- `family_notes/settings.py:24-54` - Environment helpers and security settings; no classifier settings.
- `pyproject.toml:5-16` - Current runtime and development dependencies.
- `.env.example:23-29` - Deferred AI-provider credential placeholder.
- `context/foundation/prd.md:75-114` - Classification, timing, purpose-limitation, and access contracts.
- `context/foundation/roadmap.md:87-98` - F-02 outcome and prohibited secondary reuse.
- `context/changes/deployment/deployment-plan.md:123-133` - Pending monitoring and sensitive-log exclusions.

## Architecture Insights

- Classification is a foundation boundary that later capture slices consume; the roadmap keeps it independent from the entry UI and missing-information slice (`context/foundation/roadmap.md:87-98`, `context/foundation/roadmap.md:115-124`, `context/foundation/roadmap.md:151-161`).
- An application-owned classification interface fits the current absence of provider dependencies and prevents provider response types from becoming product-domain types. This is a recommendation in the active options draft, not an implemented convention (`context/changes/classification-privacy-boundary/classification-options-research.md:33-39`).
- Family identity and scoping already live in `family_access`; the future entry-owning app can depend on those helpers without placing product models in the project-configuration package (`family_access/access.py:6-51`).
- Synchronous WSGI and a small single-instance host make the 30-second budget a request-capacity concern as well as a provider-timeout concern (`context/changes/deployment/deployment-plan.md:32-44`, `context/changes/deployment/deployment-plan.md:118-121`). No load-test result currently quantifies that concern.

## Historical Context (from prior changes)

- **Supported:** the identity plan deliberately excluded entry/classification models and UI while establishing access helpers for future family-data paths (`context/changes/identity-and-family-access-contract/plan.md:9-25`, `context/changes/identity-and-family-access-contract/plan.md:165-191`).
- **Supported with a later override:** `context/foundation/tech-stack.md:8-24` names Railway, while the deployed plan explicitly supersedes that choice with Mikr.us and manual SSH releases (`context/changes/deployment/deployment-plan.md:163-166`).
- **Partially superseded:** `context/foundation/infrastructure.md:14-18` selected Mikr.us with shared PostgreSQL. The Mikr.us VPS choice remains current, but the deployed plan replaces shared PostgreSQL with a separately purchased dedicated Mikrus service (`context/changes/deployment/deployment-plan.md:32-36`, `context/changes/deployment/deployment-plan.md:163-168`).
- **Contradicted:** the scope note says `classification-options-research.md` is stored under F-03, but its inspected path is `context/changes/classification-privacy-boundary/classification-options-research.md` (`context/changes/classification-privacy-boundary/classification-options-research.md:1-3`).
- The inspected `context/archive/` inventory contains its README and no archived classification/provider decision. This negative finding is bounded to the repository inventory at the recorded revision and dirty working tree.

## Related Research

- `context/changes/classification-privacy-boundary/classification-options-research.md` - Candidate implementations, required controls, and unresolved provider gates. Its external assertions are not revalidated by this local research.
- `context/changes/classification-privacy-boundary/openai-sdk-implementation-doc.md` - Draft direct-SDK mechanics and privacy controls. Its model is a placeholder, its timeout values are starting alternatives, and its provider data-control assertions require current official-documentation verification before planning (`context/changes/classification-privacy-boundary/openai-sdk-implementation-doc.md:65-68`, `context/changes/classification-privacy-boundary/openai-sdk-implementation-doc.md:109-125`, `context/changes/classification-privacy-boundary/openai-sdk-implementation-doc.md:191-202`).

## Open Questions

1. Which backend is approved for the MVP, and what current contractual evidence proves its retention, training, region, subprocessor, DPA, and deletion behavior satisfies the purpose limitation?
2. If OpenAI is selected, is Zero Data Retention approved and configured for the production project? `store=False` alone is not treated as sufficient by the active draft (`context/changes/classification-privacy-boundary/openai-sdk-implementation-doc.md:191-202`).
3. Does the selected classifier meet the school-event acceptance case and representative Polish-language cases, including relative dates and family-member names (`context/foundation/prd.md:51-64`)?
4. Is the original submitted instruction the confirmed entry content, or may classification generate rewritten content? The options draft says to preserve submitted text (`context/changes/classification-privacy-boundary/classification-options-research.md:15-19`), while the direct-SDK draft includes provider-generated `content` in its result schema (`context/changes/classification-privacy-boundary/openai-sdk-implementation-doc.md:32-39`).
5. What timeout, retry, cancellation, and user-visible failure contract guarantees a proposal or follow-up within 30 seconds without partial persistence?
6. What validation and follow-up rules apply to todo and note cases beyond the explicitly defined test, homework, and calendar rules (`context/foundation/prd.md:102-106`, `context/foundation/prd.md:125-127`)?
7. Which safe operational metadata may be retained, for how long, and where, while keeping submitted text and provider payloads out of application, nginx, and system logs (`context/changes/deployment/deployment-plan.md:123-133`)?

