# Classification Privacy Boundary: Implementation Options

> Scope note: this artifact researches roadmap item **F-02: Classification Privacy Boundary** but is stored under the **F-03: Production Health Release Gate** change at the user's request. The canonical F-02 change folder is `context/changes/classification-privacy-boundary/`.

## Context

FamilyNotes uses Python 3.10+, Django 5.2, PostgreSQL, `uv`, and synchronous WSGI. F-02 requires submitted family text to be used only to produce and save the requested entry. Disabling provider application storage does not necessarily disable abuse-monitoring retention.

## Options

### Direct structured-output SDK

Use an official provider SDK with a Pydantic result behind an application-owned `ClassificationBackend`. This is the smallest practical MVP integration. OpenAI supports Pydantic parsing, timeouts, and bounded retries, but standard abuse-monitoring retention means production use requires approved Zero Data Retention or an explicit PRD revision.

### Jev plus deterministic extraction

Jev returns closed-set choices, yes/no probabilities, and bounded scores. It can decide entry type, select from configured family members, choose among locally extracted date candidates, and signal missing information. It cannot generate arbitrary dates or rewritten content. Preserve the submitted text as content and use `dateparser` locally.

This is a strong functional fit, but the public official material found during research did not document input retention, training use, processing regions, subprocessors, a DPA, or zero-data-retention controls. The pre-1.0 Python package also needs evaluation on representative Polish family instructions. Do not send real family text until both privacy and quality gates pass.

### Fully deterministic local classifier

Combine explicit Python rules and member aliases with `dateparser`; introduce spaCy `Matcher` or `EntityRuler` only if patterns become difficult. This gives the strongest privacy and simplest tests, but natural-language coverage may be limited.

### Pydantic AI or Instructor

Both provide provider abstraction and validated output, but neither improves provider privacy. For one extraction operation they add abstraction without a demonstrated need. Telemetry and retries must exclude sensitive content.

### Local LLM

`llama-cpp-python` or Transformers could keep inference local, but they are a poor fit for the selected 2 GB deployment and its known concurrent-classification memory risk.

## Recommendation

1. Define a narrow `ClassificationBackend` protocol and strict Pydantic result.
2. Implement a deterministic `dateparser` backend for tests and privacy-safe fallback behavior.
3. Evaluate Jev because its closed-choice model maps well to the MVP.
4. Require acceptable written Jev retention, training, regional-processing, subprocessor, and DPA terms before production use.
5. If Jev fails privacy or quality evaluation, use a direct structured-output provider SDK only with approved ZDR.

## Required controls

- Send only the submitted instruction and minimum allowed member/date candidates.
- Never log, trace, cache, or include raw classification text in exceptions.
- Avoid provider conversations, files, assistants, analytics, and background state.
- Treat `store=false` as distinct from contractual retention.
- Validate returned members against the configured family.
- Bound timeouts and retries within 30 seconds.
- Persist only the parent-confirmed entry.
- Test ambiguity, missing fields, out-of-family names, malformed responses, timeouts, and provider unavailability.

## Sources

- [Jev Python package](https://pypi.org/project/jev/)
- [Jev official site](https://jevai.net/)
- [dateparser documentation](https://github.com/scrapinghub/dateparser/blob/master/docs/index.rst)
- [spaCy rule-based matching](https://spacy.io/usage/rule-based-matching)
- [OpenAI structured-output example](https://github.com/openai/openai-python/blob/main/examples/responses/structured_outputs.py)
- [OpenAI API data controls](https://developers.openai.com/api/docs/guides/your-data)
- [Pydantic AI outputs](https://github.com/pydantic/pydantic-ai/blob/v2.0.0/docs/output.md)
- [Instructor documentation](https://python.useinstructor.com/)

## Open decisions

1. Can Jev provide acceptable written privacy and processing terms?
2. Does Jev meet accuracy and calibration requirements on Polish instructions?
3. If no hosted provider satisfies the privacy contract, is deterministic-only classification sufficient or must the PRD change?
4. Reconcile `tech-stack.md` naming Railway with `infrastructure.md` selecting Mikr.us before evaluating local inference capacity.
