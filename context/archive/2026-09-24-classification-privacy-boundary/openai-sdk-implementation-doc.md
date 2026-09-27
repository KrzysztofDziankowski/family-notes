# Direct OpenAI SDK Implementation for F-02

## Purpose

This document captures the current official OpenAI Python SDK mechanics needed to implement roadmap item F-02, Classification Privacy Boundary, in FamilyNotes. Documentation was fetched through Context7 using the official library ID `/openai/openai-python` and the OpenAI API documentation ID `/websites/developers_openai_api`.

FamilyNotes uses Python 3.10+, Django 5.2, PostgreSQL, `uv`, and synchronous WSGI. F-02 must provide a privacy-controlled classification boundary for entry type, date, content, and affected family member while completing or returning a follow-up within 30 seconds.

## Dependency

```bash
uv add openai
```

No agent framework is required. Use the official SDK and Pydantic structured output behind an application-owned classification interface.

## Structured result

```python
from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class EntryType(StrEnum):
    TODO = "todo"
    CALENDAR_EVENT = "calendar_event"
    NOTE = "note"


class ClassificationProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_type: EntryType
    date: date | None = None
    content: str = Field(min_length=1)
    affected_member: str | None = None
    follow_up_question: str | None = None
```

The SDK converts the Pydantic model into a JSON schema and exposes the validated result through `response.output_parsed`. Invalid JSON or schema-invalid final output raises a validation error instead of silently yielding an untrusted result.

## Synchronous classification request

```python
from openai import OpenAI


client = OpenAI(
    # OPENAI_API_KEY is read from the environment by default.
    timeout=10.0,
    max_retries=1,
)


class ClassificationUnavailable(RuntimeError):
    pass


def classify_entry(
    submitted_text: str,
    allowed_members: list[str],
) -> ClassificationProposal:
    response = client.responses.parse(
        model="MODEL_FROM_SETTINGS",
        store=False,
        max_output_tokens=300,
        instructions=(
            "Classify a family instruction as todo, calendar_event, or note. "
            "Extract only information supported by the instruction. "
            "affected_member must be one of the supplied allowed members or null. "
            "If required information is missing, return a follow_up_question. "
            "Do not invent dates, people, or content."
        ),
        input=(
            f"Allowed family members: {allowed_members!r}\n"
            f"Instruction: {submitted_text}"
        ),
        text_format=ClassificationProposal,
    )

    if response.status != "completed":
        reason = getattr(response.incomplete_details, "reason", None)
        raise ClassificationUnavailable(
            f"Incomplete classification: {reason}"
        )

    proposal = response.output_parsed
    if proposal is None:
        # Covers refusals and output without a parsed final answer.
        raise ClassificationUnavailable(
            "No classification proposal returned"
        )

    if (
        proposal.affected_member is not None
        and proposal.affected_member not in allowed_members
    ):
        raise ClassificationUnavailable(
            "Unknown affected family member"
        )

    return proposal
```

Keep the model identifier in environment-backed Django settings rather than hard-coding it. Choose a currently available model that supports Structured Outputs during implementation.

## Timeout and retry budget

The SDK default timeout is longer than the PRD's 30-second boundary and must be overridden. Timeouts apply per attempt, and retry backoff adds wall-clock time.

A reasonable starting point is:

```python
client = OpenAI(timeout=10.0, max_retries=1)
```

An alternative with stricter timing is:

```python
client = OpenAI(timeout=25.0, max_retries=0)
```

Verify the full wall-clock duration with an integration test. The request, retry delay, application handling, and HTTP response together must remain within 30 seconds.

## Error handling

```python
import logging

import openai


log = logging.getLogger(__name__)


def safely_classify(text: str, members: list[str]):
    try:
        return classify_entry(text, members)
    except openai.APITimeoutError:
        raise ClassificationUnavailable("Classification timed out")
    except openai.RateLimitError:
        raise ClassificationUnavailable(
            "Classification temporarily unavailable"
        )
    except openai.APIConnectionError:
        raise ClassificationUnavailable(
            "Classification provider unavailable"
        )
    except openai.APIStatusError as exc:
        log.warning(
            "OpenAI classification failed",
            extra={
                "status_code": exc.status_code,
                "request_id": exc.request_id,
            },
        )
        raise ClassificationUnavailable("Classification failed")
    except openai.APIResponseValidationError:
        raise ClassificationUnavailable(
            "Invalid classification response"
        )
```

Safe operational metadata includes the HTTP status and provider request ID. Do not log submitted text, response bodies, proposal content, or exception bodies that might contain family text.

## Business-rule validation

Schema adherence does not prove semantic correctness. Enforce the domain rules after parsing:

```python
def validate_business_rules(
    proposal: ClassificationProposal,
) -> ClassificationProposal:
    requires_date = (
        proposal.entry_type == EntryType.CALENDAR_EVENT
    )

    if requires_date and proposal.date is None:
        if not proposal.follow_up_question:
            raise ClassificationUnavailable(
                "Missing date requires a follow-up question"
            )

    return proposal
```

Do not let the model generate or authorize database identifiers. Supply a small set of permitted family-member values, validate the returned value again, and resolve it to a family-scoped record in application code. Parent review and confirmation remain mandatory before persistence.

## Privacy boundary

Every request must use `store=False`. Do not use Conversations, `previous_response_id`, Files, Assistants, Threads, background mode, or metadata containing family information. Do not enable prompt/response tracing or `OPENAI_LOG=debug` in production.

`store=False` prevents the response from being retained as retrievable application state. It does not independently disable abuse-monitoring retention. OpenAI documents that API inputs and outputs are not used for training by default, while standard API traffic may still be retained for abuse monitoring. Responses API requests are eligible for Zero Data Retention, but the organization or project must be approved and configured for it.

F-02 therefore requires both:

1. the application sends `store=False`; and
2. the production OpenAI project has approved Zero Data Retention.

The first condition is enforceable in code and tests. The second is an external configuration and release prerequisite.

## Verification cases

- Complete school event produces a proposal.
- Polish relative date is interpreted correctly.
- Missing required date produces a follow-up question.
- Missing family member produces the expected incomplete proposal or follow-up.
- An unknown or outside-family name is rejected.
- Unrecognized content falls back to a general note.
- Refusal becomes `ClassificationUnavailable`.
- Incomplete response caused by `max_output_tokens` is rejected.
- Schema-invalid output is rejected.
- Timeout, rate limit, connection failure, and provider 500 are handled.
- `store=False` is present on every provider request.
- Logs never contain submitted text or returned content.
- Total wall-clock duration remains within 30 seconds.

## Official documentation

- [OpenAI Python structured-output example](https://github.com/openai/openai-python/blob/main/examples/responses/structured_outputs.py)
- [OpenAI Python parsing helpers](https://github.com/openai/openai-python/blob/main/helpers.md)
- [OpenAI Python README: timeouts, retries, errors, request IDs](https://github.com/openai/openai-python/blob/main/README.md)
- [OpenAI SDK exception hierarchy](https://github.com/openai/openai-python/blob/main/src/openai/_exceptions.py)
- [OpenAI Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs)
- [OpenAI API data controls](https://developers.openai.com/api/docs/guides/your-data)
