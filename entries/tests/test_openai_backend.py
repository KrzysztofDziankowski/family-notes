"""OpenAI adapter tests.

Every test drives a real ``openai.OpenAI`` client through ``httpx2.MockTransport``
so request bodies, SDK error mapping, and response parsing are exercised
exactly as in production, with no network access and no real sleeps. A fake
monotonic clock advances only when the scripted transport or backoff says so.
"""

import dataclasses
import datetime
import json
import logging
import os
import runpy
import traceback
from unittest import mock

import httpx2
import openai
import pydantic
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings

from entries.classification.backends import (
    BackendOutput,
    BackendRequest,
    ClassificationBackend,
    ClassificationBackendError,
)
from entries.classification.openai_backend import (
    INSTRUCTIONS,
    OpenAIClassificationBackend,
    StructuredClassification,
    build_openai_backend,
)
from entries.classification.types import EntryType, SchoolItemKind, UnavailableReason
from family_notes import settings as settings_module
from family_notes.settings import env_number, validate_classification_settings

MODEL = 'gpt-test-structured'
REFERENCE_DATE = datetime.date(2026, 9, 17)
MONDAY = datetime.date(2026, 9, 21)

API_KEY_SENTINEL = 'sk-SENTINEL-APIKEY-4e1d77'
SUBMITTED_SENTINEL = 'SENTINEL-SUBMITTED-a61c0f'
MEMBER_SENTINEL = 'SENTINEL-MEMBER-Zosia-93b2'
OTHER_MEMBER_SENTINEL = 'SENTINEL-MEMBER-Kuba-17ce'
CONTENT_SENTINEL = 'SENTINEL-CONTENT-5f8a21'
ERROR_BODY_SENTINEL = 'SENTINEL-ERRORBODY-c03e9d'
REFUSAL_SENTINEL = 'SENTINEL-REFUSAL-d7714b'
ANSWER_SENTINEL = 'SENTINEL-ANSWER-8b40e2'
QUESTION_SENTINEL = 'SENTINEL-QUESTION-2c9d51'
DATE_SOURCE_SENTINEL = 'SENTINEL-DATESOURCE-71af3e'
SENTINELS = (
    API_KEY_SENTINEL,
    SUBMITTED_SENTINEL,
    MEMBER_SENTINEL,
    OTHER_MEMBER_SENTINEL,
    CONTENT_SENTINEL,
    ERROR_BODY_SENTINEL,
    REFUSAL_SENTINEL,
    ANSWER_SENTINEL,
    QUESTION_SENTINEL,
    DATE_SOURCE_SENTINEL,
)

ALLOWED_REQUEST_FIELDS = {
    'model',
    'instructions',
    'input',
    'text',
    'store',
    'max_output_tokens',
}
STATEFUL_FIELDS = {
    'conversation',
    'previous_response_id',
    'background',
    'metadata',
    'tools',
    'tool_choice',
    'include',
    'prompt',
    'prompt_cache_key',
    'safety_identifier',
    'user',
    'stream',
    'context_management',
}


def make_request(
    text=f'{MEMBER_SENTINEL} ma sprawdzian w poniedziałek {SUBMITTED_SENTINEL}',
    **follow_up,
):
    return BackendRequest(
        submitted_text=text,
        allowed_member_names=(MEMBER_SENTINEL, OTHER_MEMBER_SENTINEL),
        reference_date=REFERENCE_DATE,
        locale='pl-PL',
        **follow_up,
    )


def make_follow_up_request():
    return make_request(
        follow_up_question=f'Kiedy odbędzie się „Sprawdzian {QUESTION_SENTINEL}”?',
        follow_up_answer=f'w poniedziałek {ANSWER_SENTINEL}',
    )


def structured(**overrides):
    values = dict(
        entry_type='calendar_event',
        content=f'Sprawdzian {CONTENT_SENTINEL}',
        grounded=True,
        date=MONDAY.isoformat(),
        date_source='w poniedziałek',
        time='08:00',
        school_item='test',
        member_name=MEMBER_SENTINEL,
    )
    values.update(overrides)
    return values


def response_body(text=None, *, status='completed', refusal=None, incomplete_reason=None):
    if refusal is not None:
        content = [{'type': 'refusal', 'refusal': refusal}]
    else:
        if text is None:
            text = json.dumps(structured(), ensure_ascii=False)
        content = [{'type': 'output_text', 'text': text, 'annotations': []}]
    return {
        'id': 'resp_test',
        'object': 'response',
        'created_at': 1,
        'model': MODEL,
        'status': status,
        'incomplete_details': (
            {'reason': incomplete_reason} if incomplete_reason is not None else None
        ),
        'output': [
            {
                'type': 'message',
                'id': 'msg_test',
                'role': 'assistant',
                'status': 'completed',
                'content': content,
            }
        ],
        'parallel_tool_calls': False,
        'tool_choice': 'auto',
        'tools': [],
        'store': False,
    }


def ok(body=None, request_id='req_ok'):
    return ('response', 200, body if body is not None else response_body(), request_id)


def status_error(code, request_id='req_err'):
    body = {'error': {'message': f'Provider says {ERROR_BODY_SENTINEL}', 'type': 'x'}}
    return ('response', code, body, request_id)


TIMEOUT = ('raise', httpx2.ReadTimeout)
CONNECTION = ('raise', httpx2.ConnectError)


class FakeClock:
    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class ScriptedTransport:
    """Replays (duration, outcome) steps and records every sent request."""

    def __init__(self, clock, steps):
        self.clock = clock
        self.steps = list(steps)
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        step = self.steps.pop(0)
        # A step is (seconds, outcome) or a bare outcome taking no time.
        duration, outcome = (0.0, step) if isinstance(step[0], str) else step
        self.clock.now += duration
        if outcome[0] == 'raise':
            raise outcome[1]('scripted failure', request=request)
        _, code, body, request_id = outcome
        return httpx2.Response(code, json=body, headers={'x-request-id': request_id})

    def bodies(self):
        return [json.loads(request.content) for request in self.requests]

    def timeouts(self):
        return [request.extensions['timeout']['read'] for request in self.requests]

    def connect_timeouts(self):
        return [request.extensions['timeout']['connect'] for request in self.requests]


def make_client(transport):
    return openai.OpenAI(
        api_key=API_KEY_SENTINEL,
        max_retries=0,
        http_client=httpx2.Client(transport=httpx2.MockTransport(transport)),
    )


class BackendHarness:
    def make_backend(self, steps, **options):
        self.clock = FakeClock()
        self.transport = ScriptedTransport(self.clock, steps)
        values = dict(
            client=make_client(self.transport),
            model=MODEL,
            deadline_seconds=25.0,
            attempt_timeout_seconds=10.0,
            max_retries=1,
            retry_backoff_seconds=0.5,
            clock=self.clock,
            sleep=options.pop('sleep', None) or self.clock.sleep,
        )
        values.update(options)
        return OpenAIClassificationBackend(**values)

    def classify_error(self, backend, request=None):
        with self.assertRaises(ClassificationBackendError) as caught:
            backend.classify(request or make_request())
        return caught.exception

    def elapsed(self):
        return self.clock.now - 1000.0


class AdapterRequestTests(BackendHarness, SimpleTestCase):
    def test_backend_satisfies_protocol(self):
        backend = self.make_backend([ok()])

        self.assertIsInstance(backend, ClassificationBackend)

    def test_request_uses_strict_schema_store_false_and_configured_model(self):
        backend = self.make_backend([ok()])

        backend.classify(make_request())

        (request,) = self.transport.requests
        self.assertEqual(request.method, 'POST')
        self.assertEqual(request.url.path, '/v1/responses')
        body = json.loads(request.content)
        self.assertEqual(body['model'], MODEL)
        self.assertIs(body['store'], False)
        self.assertEqual(body['instructions'], INSTRUCTIONS)
        text_format = body['text']['format']
        self.assertEqual(text_format['type'], 'json_schema')
        self.assertIs(text_format['strict'], True)
        schema = text_format['schema']
        self.assertIs(schema['additionalProperties'], False)
        self.assertEqual(set(schema['required']), set(schema['properties']))
        self.assertEqual(
            set(schema['properties']),
            {
                'entry_type',
                'content',
                'grounded',
                'date',
                'date_source',
                'time',
                'school_item',
                'member_name',
            },
        )

    def test_input_is_minimal_payload(self):
        backend = self.make_backend([ok()])

        backend.classify(make_request())

        (body,) = self.transport.bodies()
        self.assertEqual(
            json.loads(body['input']),
            {
                'data_odniesienia': '2026-09-17',
                'dzien_tygodnia': 'czwartek',
                'ustawienia_regionalne': 'pl-PL',
                'dozwolone_osoby': [MEMBER_SENTINEL, OTHER_MEMBER_SENTINEL],
                'polecenie': make_request().submitted_text,
            },
        )

    def test_input_carries_follow_up_question_and_answer_when_answered(self):
        backend = self.make_backend([ok()])
        request = make_follow_up_request()

        backend.classify(request)

        (body,) = self.transport.bodies()
        self.assertEqual(
            json.loads(body['input']),
            {
                'data_odniesienia': '2026-09-17',
                'dzien_tygodnia': 'czwartek',
                'ustawienia_regionalne': 'pl-PL',
                'dozwolone_osoby': [MEMBER_SENTINEL, OTHER_MEMBER_SENTINEL],
                'polecenie': request.submitted_text,
                'pytanie_uzupelniajace': request.follow_up_question,
                'odpowiedz_rodzica': request.follow_up_answer,
            },
        )
        self.assertEqual(body['instructions'], INSTRUCTIONS)
        self.assertIn('odpowiedź rodzica', INSTRUCTIONS)

    def test_follow_up_text_is_excluded_from_request_repr(self):
        text = repr(make_follow_up_request())

        self.assertNotIn(ANSWER_SENTINEL, text)
        self.assertNotIn(QUESTION_SENTINEL, text)

    def test_request_has_no_stateful_openai_features(self):
        backend = self.make_backend([ok()])

        backend.classify(make_request())

        (body,) = self.transport.bodies()
        self.assertEqual(set(body), ALLOWED_REQUEST_FIELDS)
        self.assertFalse(STATEFUL_FIELDS & set(body))

    def test_reasoning_effort_is_sent_only_when_configured(self):
        backend = self.make_backend([ok()], reasoning_effort='low')

        backend.classify(make_request())

        (body,) = self.transport.bodies()
        self.assertEqual(body['reasoning'], {'effort': 'low'})
        self.assertEqual(set(body), ALLOWED_REQUEST_FIELDS | {'reasoning'})

    def test_every_attempt_sends_store_false(self):
        backend = self.make_backend([(10.0, TIMEOUT), (1.0, ok())])

        backend.classify(make_request())

        self.assertEqual([body['store'] for body in self.transport.bodies()], [False, False])

    def test_success_translates_to_provider_neutral_output(self):
        backend = self.make_backend([ok()])

        output = backend.classify(make_request())

        self.assertEqual(
            output,
            BackendOutput(
                entry_type=EntryType.CALENDAR_EVENT,
                content=f'Sprawdzian {CONTENT_SENTINEL}',
                grounded=True,
                date=MONDAY,
                time=datetime.time(8, 0),
                school_item=SchoolItemKind.TEST,
                member_name=MEMBER_SENTINEL,
            ),
        )
        self.assertIs(type(output.entry_type), EntryType)
        self.assertIs(type(output.school_item), SchoolItemKind)

    def test_null_entry_type_and_optional_fields_are_preserved(self):
        text = json.dumps(
            structured(entry_type=None, date=None, time=None, school_item=None, member_name=None)
        )
        backend = self.make_backend([ok(response_body(text))])

        output = backend.classify(make_request())

        self.assertIsNone(output.entry_type)
        self.assertIsNone(output.date)
        self.assertIsNone(output.member_name)

    def test_schema_forbids_extra_fields(self):
        with self.assertRaises(pydantic.ValidationError):
            StructuredClassification.model_validate({**structured(), 'extra': 'x'})

    def test_schema_invalid_outputs_are_malformed(self):
        cases = {
            'extra field': json.dumps({**structured(), 'database_id': 7}),
            'missing field': json.dumps({k: v for k, v in structured().items() if k != 'grounded'}),
            'unknown entry type': json.dumps(structured(entry_type='reminder')),
            'unknown school item': json.dumps(structured(school_item='exam')),
            'invalid date': json.dumps(structured(date='poniedziałek')),
            'not json': f'not json {CONTENT_SENTINEL}',
        }
        for label, text in cases.items():
            with self.subTest(label):
                backend = self.make_backend([ok(response_body(text))])

                error = self.classify_error(backend)

                self.assertEqual(error.reason, UnavailableReason.MALFORMED_OUTPUT)
                self.assertEqual(len(self.transport.requests), 1)

    def test_absent_parsed_output_is_malformed(self):
        body = response_body()
        body['output'] = []
        backend = self.make_backend([ok(body)])

        error = self.classify_error(backend)

        self.assertEqual(error.reason, UnavailableReason.MALFORMED_OUTPUT)

    def test_refusal_is_rejected(self):
        backend = self.make_backend([ok(response_body(refusal=REFUSAL_SENTINEL))])

        error = self.classify_error(backend)

        self.assertEqual(error.reason, UnavailableReason.REFUSED)
        self.assertEqual(len(self.transport.requests), 1)

    def test_incomplete_response_is_rejected(self):
        body = response_body(status='incomplete', incomplete_reason='max_output_tokens')
        backend = self.make_backend([ok(body)])

        error = self.classify_error(backend)

        self.assertEqual(error.reason, UnavailableReason.INCOMPLETE_OUTPUT)
        self.assertEqual(len(self.transport.requests), 1)

    def test_failed_response_status_is_provider_error(self):
        backend = self.make_backend([ok(response_body(status='failed'))])

        error = self.classify_error(backend)

        self.assertEqual(error.reason, UnavailableReason.PROVIDER_ERROR)


class DateGroundingTests(BackendHarness, SimpleTestCase):
    """A date survives only when its ``date_source`` occurs in the parent's text."""

    def classify_with(self, request=None, **overrides):
        backend = self.make_backend([ok(response_body(json.dumps(structured(**overrides))))])
        return backend.classify(request or make_request())

    def test_instructions_forbid_reference_date_as_default(self):
        self.assertIn('nigdy nie używaj daty odniesienia jako domyślnej', INSTRUCTIONS)
        self.assertIn('date_source', INSTRUCTIONS)

    def test_invented_date_without_evidence_is_dropped(self):
        for date_source in (None, '', '   ', '„”'):
            with self.subTest(date_source=date_source):
                output = self.classify_with(
                    make_request(text=f'{MEMBER_SENTINEL} ma kartkówkę z matematyki'),
                    date=REFERENCE_DATE.isoformat(),
                    date_source=date_source,
                )

                self.assertIsNone(output.date)

    def test_date_with_evidence_absent_from_text_is_dropped_other_fields_kept(self):
        output = self.classify_with(date_source='w piątek')

        self.assertIsNone(output.date)
        self.assertEqual(output.time, datetime.time(8, 0))
        self.assertEqual(output.entry_type, EntryType.CALENDAR_EVENT)
        self.assertEqual(output.school_item, SchoolItemKind.TEST)
        self.assertEqual(output.member_name, MEMBER_SENTINEL)
        self.assertTrue(output.grounded)

    def test_date_with_evidence_in_text_is_kept(self):
        request = make_request(text=f'{MEMBER_SENTINEL} ma sprawdzian  W\nPoniedziałek, sala 12')
        for date_source in (
            'w poniedziałek',
            'W PONIEDZIAŁEK',
            '  w   poniedziałek ',
            '„w poniedziałek”',
            'ma sprawdzian w poniedziałek',
        ):
            with self.subTest(date_source=date_source):
                output = self.classify_with(request, date_source=date_source)

                self.assertEqual(output.date, MONDAY)

    def test_follow_up_answer_grounds_the_date(self):
        request = make_request(
            text=f'{MEMBER_SENTINEL} ma sprawdzian',
            follow_up_question='Kiedy odbędzie się „Sprawdzian”?',
            follow_up_answer='W poniedziałek rano',
        )

        output = self.classify_with(request, date_source='w poniedziałek')

        self.assertEqual(output.date, MONDAY)

    def test_follow_up_question_does_not_ground_the_date(self):
        request = make_request(
            text=f'{MEMBER_SENTINEL} ma sprawdzian',
            follow_up_question='Czy to w poniedziałek?',
            follow_up_answer='nie wiem',
        )

        output = self.classify_with(request, date_source='w poniedziałek')

        self.assertIsNone(output.date)

    def test_follow_up_answer_cited_by_key_or_whole_answer_grounds_the_date(self):
        request = make_request(
            text=f'{MEMBER_SENTINEL} ma sprawdzian',
            follow_up_question='Kiedy odbędzie się „Sprawdzian”?',
            follow_up_answer='W poniedziałek',
        )
        for date_source in (
            'odpowiedz_rodzica',
            'odpowiedź_rodzica',
            '„odpowiedz_rodzica”',
            'pytanie_uzupelniajace: Kiedy odbędzie się „Sprawdzian”? odpowiedz_rodzica: w poniedziałek',
        ):
            with self.subTest(date_source=date_source):
                output = self.classify_with(request, date_source=date_source)

                self.assertEqual(output.date, MONDAY)

    def test_question_key_or_answer_key_without_answer_does_not_ground_the_date(self):
        cases = (
            (make_request(
                text=f'{MEMBER_SENTINEL} ma sprawdzian',
                follow_up_question='Kiedy odbędzie się „Sprawdzian”?',
                follow_up_answer='W poniedziałek',
            ), 'pytanie_uzupelniajace'),
            (make_request(
                text=f'{MEMBER_SENTINEL} ma sprawdzian',
                follow_up_question='Kiedy odbędzie się „Sprawdzian”?',
                follow_up_answer='W poniedziałek',
            ), 'Kiedy odbędzie się „Sprawdzian”?'),
            (make_request(text=f'{MEMBER_SENTINEL} ma sprawdzian'), 'odpowiedz_rodzica'),
        )
        for request, date_source in cases:
            with self.subTest(date_source=date_source):
                output = self.classify_with(request, date_source=date_source)

                self.assertIsNone(output.date)

    def test_date_source_is_not_part_of_backend_output(self):
        request = make_request(text=f'{MEMBER_SENTINEL} ma sprawdzian {DATE_SOURCE_SENTINEL}')

        output = self.classify_with(request, date_source=DATE_SOURCE_SENTINEL)

        self.assertEqual(output.date, MONDAY)
        self.assertNotIn('date_source', {field.name for field in dataclasses.fields(output)})
        self.assertNotIn(DATE_SOURCE_SENTINEL, repr(output))


class TimingAndRetryTests(BackendHarness, SimpleTestCase):
    def test_first_attempt_success(self):
        backend = self.make_backend([(2.0, ok())])

        backend.classify(make_request())

        self.assertEqual(len(self.transport.requests), 1)
        self.assertEqual(self.transport.timeouts(), [10.0])
        self.assertEqual(self.clock.sleeps, [])

    def test_eligible_retry_after_timeout_succeeds(self):
        backend = self.make_backend([(10.0, TIMEOUT), (3.0, ok())])

        output = backend.classify(make_request())

        self.assertEqual(output.entry_type, EntryType.CALENDAR_EVENT)
        self.assertEqual(len(self.transport.requests), 2)
        self.assertEqual(self.clock.sleeps, [0.5])
        self.assertEqual(self.transport.timeouts(), [10.0, 10.0])

    def test_transient_failures_are_retried_once(self):
        cases = {
            'timeout': (TIMEOUT, UnavailableReason.TIMEOUT),
            'connection': (CONNECTION, UnavailableReason.CONNECTION_ERROR),
            'rate limit': (status_error(429), UnavailableReason.RATE_LIMITED),
            '500': (status_error(500), UnavailableReason.PROVIDER_ERROR),
            '503': (status_error(503), UnavailableReason.PROVIDER_ERROR),
        }
        for label, (failure, reason) in cases.items():
            with self.subTest(label):
                backend = self.make_backend([(1.0, failure), (1.0, failure)])

                error = self.classify_error(backend)

                self.assertEqual(error.reason, reason)
                self.assertEqual(len(self.transport.requests), 2)
                self.assertEqual(self.clock.sleeps, [0.5])

    def test_transient_failure_then_success(self):
        for failure in (TIMEOUT, CONNECTION, status_error(429), status_error(502)):
            with self.subTest(failure[1]):
                backend = self.make_backend([(1.0, failure), (1.0, ok())])

                output = backend.classify(make_request())

                self.assertEqual(output.school_item, SchoolItemKind.TEST)
                self.assertEqual(len(self.transport.requests), 2)

    def test_timeout_on_both_attempts_stays_inside_deadline(self):
        backend = self.make_backend([(10.0, TIMEOUT), (10.0, TIMEOUT)])

        error = self.classify_error(backend)

        self.assertEqual(error.reason, UnavailableReason.TIMEOUT)
        self.assertEqual(self.elapsed(), 20.5)
        self.assertLessEqual(self.elapsed(), 25.0)

    def test_insufficient_retry_budget_skips_retry(self):
        # 25 - 14.6 = 10.4 < 0.5 backoff + 10 s attempt.
        backend = self.make_backend([(14.6, CONNECTION)])

        error = self.classify_error(backend)

        self.assertEqual(error.reason, UnavailableReason.CONNECTION_ERROR)
        self.assertEqual(len(self.transport.requests), 1)
        self.assertEqual(self.clock.sleeps, [])

    def test_retry_at_exact_budget_ends_exactly_at_deadline(self):
        # 25 - 14.5 = 10.5 == 0.5 backoff + 10 s attempt: the retry fits.
        backend = self.make_backend([(14.5, status_error(500)), (10.0, ok())])

        output = backend.classify(make_request())

        self.assertEqual(output.entry_type, EntryType.CALENDAR_EVENT)
        self.assertEqual(self.elapsed(), 25.0)
        self.assertEqual(self.transport.timeouts(), [10.0, 10.0])

    def test_answer_after_deadline_is_discarded(self):
        backend = self.make_backend([(14.5, status_error(500)), (10.25, ok())])

        error = self.classify_error(backend)

        self.assertEqual(error.reason, UnavailableReason.TIMEOUT)
        self.assertEqual(len(self.transport.requests), 2)

    def test_attempt_timeout_is_capped_by_remaining_budget(self):
        clock_holder = {}

        def oversleep(seconds):
            clock_holder['clock'].sleeps.append(seconds)
            clock_holder['clock'].now += 1.0

        backend = self.make_backend([(14.4, TIMEOUT), (1.0, ok())], sleep=oversleep)
        clock_holder['clock'] = self.clock

        backend.classify(make_request())

        # 25 - 14.4 = 10.6 permits a retry; the backoff overslept by 0.5 s,
        # leaving 9.6 s, so the retry gets 9.6 s instead of the full 10 s.
        first, second = self.transport.timeouts()
        self.assertEqual(first, 10.0)
        self.assertAlmostEqual(second, 9.6)

    def test_first_attempt_timeout_never_exceeds_deadline(self):
        backend = self.make_backend(
            [(1.0, ok())], deadline_seconds=6.0, attempt_timeout_seconds=6.0
        )

        backend.classify(make_request())

        self.assertEqual(self.transport.timeouts(), [6.0])

    def test_connect_timeout_is_a_short_slice_of_the_attempt(self):
        for attempt_timeout, expected_connect in ((10.0, 3.0), (2.0, 2.0)):
            with self.subTest(attempt_timeout=attempt_timeout):
                backend = self.make_backend(
                    [(1.0, ok())], attempt_timeout_seconds=attempt_timeout
                )

                backend.classify(make_request())

                self.assertEqual(self.transport.connect_timeouts(), [expected_connect])
                self.assertEqual(self.transport.timeouts(), [attempt_timeout])

    def test_non_retryable_failures_make_one_attempt(self):
        cases = {
            '400': (status_error(400), UnavailableReason.PROVIDER_ERROR),
            '401 authentication': (status_error(401), UnavailableReason.PROVIDER_ERROR),
            '403': (status_error(403), UnavailableReason.PROVIDER_ERROR),
            '404': (status_error(404), UnavailableReason.PROVIDER_ERROR),
            '422': (status_error(422), UnavailableReason.PROVIDER_ERROR),
            'refusal': (ok(response_body(refusal=REFUSAL_SENTINEL)), UnavailableReason.REFUSED),
            'malformed': (ok(response_body('{}')), UnavailableReason.MALFORMED_OUTPUT),
        }
        for label, (failure, reason) in cases.items():
            with self.subTest(label):
                backend = self.make_backend([(1.0, failure)])

                error = self.classify_error(backend)

                self.assertEqual(error.reason, reason)
                self.assertEqual(len(self.transport.requests), 1)
                self.assertEqual(self.clock.sleeps, [])

    def test_zero_retries_configured(self):
        backend = self.make_backend([(1.0, TIMEOUT)], max_retries=0)

        error = self.classify_error(backend)

        self.assertEqual(error.reason, UnavailableReason.TIMEOUT)
        self.assertEqual(len(self.transport.requests), 1)

    def test_invalid_timing_configuration_is_rejected(self):
        client = object()
        for options in (
            dict(deadline_seconds=0),
            dict(attempt_timeout_seconds=30.0),
            dict(attempt_timeout_seconds=0),
            dict(max_retries=2),
            dict(retry_backoff_seconds=-1),
            dict(model=''),
        ):
            with self.subTest(options):
                values = dict(client=client, model=MODEL)
                values.update(options)
                with self.assertRaises(ValueError):
                    OpenAIClassificationBackend(**values)


class LogPrivacyTests(BackendHarness, SimpleTestCase):
    SCENARIOS = {
        'success': [(1.0, ok(request_id='req_success'))],
        'refusal': [(1.0, ok(response_body(refusal=REFUSAL_SENTINEL), request_id='req_refusal'))],
        'malformed': [(1.0, ok(response_body(f'{{"content": "{CONTENT_SENTINEL}"'), 'req_bad'))],
        'ungrounded date evidence': [
            (1.0, ok(response_body(json.dumps(structured(date_source=DATE_SOURCE_SENTINEL)))))
        ],
        'schema invalid': [
            (1.0, ok(response_body(json.dumps(structured(extra=CONTENT_SENTINEL))), 'req_bad'))
        ],
        '5xx twice': [(1.0, status_error(500, 'req_5a')), (1.0, status_error(500, 'req_5b'))],
        '4xx': [(1.0, status_error(400, 'req_400'))],
        'auth': [(1.0, status_error(401, 'req_401'))],
        'rate limit twice': [(1.0, status_error(429)), (1.0, status_error(429))],
        'timeout twice': [(10.0, TIMEOUT), (10.0, TIMEOUT)],
        'connection twice': [(1.0, CONNECTION), (1.0, CONNECTION)],
    }

    def run_scenario(self, steps):
        backend = self.make_backend(steps)
        error = None
        with self.assertLogs(level=logging.DEBUG) as captured:
            try:
                backend.classify(make_request())
            except ClassificationBackendError as caught:
                error = caught
        rendered = [record.getMessage() for record in captured.records]
        rendered += [
            ''.join(traceback.format_exception(*record.exc_info))
            for record in captured.records
            if record.exc_info
        ]
        return error, captured.records, '\n'.join(rendered)

    def test_sensitive_sentinels_never_logged_or_attached(self):
        for label, steps in self.SCENARIOS.items():
            with self.subTest(label):
                error, _, logs = self.run_scenario(steps)

                for sentinel in SENTINELS:
                    self.assertNotIn(sentinel, logs)
                if error is not None:
                    self.assertIsNone(error.__cause__)
                    self.assertIsNone(error.__context__)
                    exposed = ''.join(
                        traceback.format_exception(type(error), error, error.__traceback__)
                    ) + repr(error) + str(error)
                    for sentinel in SENTINELS:
                        self.assertNotIn(sentinel, exposed)

    def test_grounded_date_evidence_never_logged(self):
        request = make_request(text=f'{MEMBER_SENTINEL} ma sprawdzian {DATE_SOURCE_SENTINEL}')
        backend = self.make_backend(
            [(1.0, ok(response_body(json.dumps(structured(date_source=DATE_SOURCE_SENTINEL)))))]
        )
        with self.assertLogs(level=logging.DEBUG) as captured:
            output = backend.classify(request)

        self.assertEqual(output.date, MONDAY)
        exposed = '\n'.join(record.getMessage() for record in captured.records)
        self.assertNotIn(DATE_SOURCE_SENTINEL, exposed + repr(output))

    def test_follow_up_answer_never_logged_or_attached(self):
        for label in ('success', 'malformed', '5xx twice', 'timeout twice'):
            with self.subTest(label):
                backend = self.make_backend(self.SCENARIOS[label])
                error = None
                with self.assertLogs(level=logging.DEBUG) as captured:
                    try:
                        backend.classify(make_follow_up_request())
                    except ClassificationBackendError as caught:
                        error = caught
                exposed = '\n'.join(record.getMessage() for record in captured.records)
                if error is not None:
                    exposed += repr(error) + str(error)

                self.assertNotIn(ANSWER_SENTINEL, exposed)
                self.assertNotIn(QUESTION_SENTINEL, exposed)

    def test_log_line_contains_only_safe_operational_fields(self):
        _, records, _ = self.run_scenario(self.SCENARIOS['5xx twice'])

        (record,) = [
            record
            for record in records
            if record.name == 'entries.classification.openai_backend'
        ]
        self.assertEqual(record.levelno, logging.WARNING)
        self.assertEqual(
            record.getMessage(),
            'classification provider=openai outcome=provider_error status=500 '
            'request_id=req_5b elapsed_ms=2500 attempts=2',
        )

    def test_success_log_line(self):
        _, records, _ = self.run_scenario(self.SCENARIOS['success'])

        (record,) = [
            record
            for record in records
            if record.name == 'entries.classification.openai_backend'
        ]
        self.assertEqual(record.levelno, logging.INFO)
        self.assertEqual(
            record.getMessage(),
            'classification provider=openai outcome=success status=completed '
            'request_id=req_success elapsed_ms=1000 attempts=1',
        )


FULL_SETTINGS = dict(
    CLASSIFICATION_ENABLED=True,
    OPENAI_API_KEY=API_KEY_SENTINEL,
    OPENAI_CLASSIFICATION_MODEL=MODEL,
    OPENAI_REASONING_EFFORT='',
    CLASSIFICATION_DEADLINE_SECONDS=25.0,
    CLASSIFICATION_ATTEMPT_TIMEOUT_SECONDS=10.0,
    CLASSIFICATION_MAX_RETRIES=1,
)


def default_classification_settings():
    """Evaluate settings.py without a .env file or classification variables.

    Django's live settings reflect the developer's local .env, so defaults are
    read from a fresh evaluation instead.
    """
    with mock.patch('dotenv.load_dotenv'), mock.patch.dict(
        os.environ, {'DJANGO_DEBUG': 'True'}, clear=True
    ):
        values = runpy.run_path(settings_module.__file__)
    return {name: values[name] for name in FULL_SETTINGS}


class BackendFactoryTests(SimpleTestCase):
    def test_default_settings_are_disabled(self):
        with override_settings(**default_classification_settings()):
            with self.assertRaises(ClassificationBackendError) as caught:
                build_openai_backend()

        self.assertEqual(caught.exception.reason, UnavailableReason.DISABLED)

    def test_factory_fails_closed_without_each_requirement(self):
        for name, value in (
            ('CLASSIFICATION_ENABLED', False),
            ('OPENAI_API_KEY', ''),
            ('OPENAI_CLASSIFICATION_MODEL', ''),
        ):
            for debug in (True, False):
                with self.subTest(name, debug=debug), override_settings(
                    DEBUG=debug, **{**FULL_SETTINGS, name: value}
                ):
                    with self.assertRaises(ClassificationBackendError) as caught:
                        build_openai_backend()

                    self.assertEqual(caught.exception.reason, UnavailableReason.DISABLED)
                    self.assertNotIn(API_KEY_SENTINEL, repr(caught.exception))

    @override_settings(**FULL_SETTINGS)
    def test_default_client_disables_sdk_retries_and_uses_attempt_timeout(self):
        backend = build_openai_backend()

        client = backend._client
        self.assertIsInstance(client, openai.OpenAI)
        self.assertEqual(client.max_retries, 0)
        self.assertEqual(client.timeout, 10.0)
        self.assertEqual(backend._model, MODEL)
        self.assertEqual(backend._deadline_seconds, 25.0)
        self.assertEqual(backend._max_retries, 1)

    @override_settings(**FULL_SETTINGS)
    def test_max_retries_override_disables_backend_retry(self):
        clock = FakeClock()
        transport = ScriptedTransport(clock, [(10.0, TIMEOUT), (1.0, ok())])

        backend = build_openai_backend(
            client=make_client(transport), clock=clock, sleep=clock.sleep, max_retries=0
        )
        with self.assertRaises(ClassificationBackendError) as caught:
            backend.classify(make_request())

        self.assertEqual(caught.exception.reason, UnavailableReason.TIMEOUT)
        self.assertEqual(len(transport.requests), 1)
        self.assertEqual(backend._max_retries, 0)

    @override_settings(**FULL_SETTINGS)
    def test_injected_client_is_used(self):
        clock = FakeClock()
        transport = ScriptedTransport(clock, [(1.0, ok())])

        backend = build_openai_backend(
            client=make_client(transport), clock=clock, sleep=clock.sleep
        )
        backend.classify(make_request())

        (body,) = transport.bodies()
        self.assertEqual(body['model'], MODEL)
        self.assertNotIn('reasoning', body)

    @override_settings(**{**FULL_SETTINGS, 'OPENAI_REASONING_EFFORT': 'minimal'})
    def test_configured_reasoning_effort_reaches_the_request(self):
        clock = FakeClock()
        transport = ScriptedTransport(clock, [(1.0, ok())])

        backend = build_openai_backend(
            client=make_client(transport), clock=clock, sleep=clock.sleep
        )
        backend.classify(make_request())

        (body,) = transport.bodies()
        self.assertEqual(body['reasoning'], {'effort': 'minimal'})


class ClassificationSettingsTests(SimpleTestCase):
    def validate(self, **overrides):
        values = dict(
            enabled=True,
            debug=False,
            api_key=API_KEY_SENTINEL,
            model=MODEL,
            deadline_seconds=25.0,
            attempt_timeout_seconds=10.0,
            max_retries=1,
        )
        values.update(overrides)
        validate_classification_settings(**values)

    def test_defaults_are_disabled_and_match_policy(self):
        defaults = default_classification_settings()

        self.assertFalse(defaults['CLASSIFICATION_ENABLED'])
        self.assertEqual(defaults['OPENAI_API_KEY'], '')
        self.assertEqual(defaults['OPENAI_CLASSIFICATION_MODEL'], '')
        self.assertEqual(defaults['OPENAI_REASONING_EFFORT'], '')
        self.assertEqual(defaults['CLASSIFICATION_DEADLINE_SECONDS'], 25.0)
        self.assertEqual(defaults['CLASSIFICATION_ATTEMPT_TIMEOUT_SECONDS'], 10.0)
        self.assertEqual(defaults['CLASSIFICATION_MAX_RETRIES'], 1)

    def test_complete_production_configuration_passes(self):
        self.validate()
        self.validate(reasoning_effort='low')

    def test_disabled_configuration_needs_no_credentials(self):
        self.validate(enabled=False, api_key='', model='')

    def test_debug_enabled_configuration_does_not_block_startup(self):
        self.validate(debug=True, api_key='', model='')

    def test_production_enabled_configuration_fails_closed(self):
        for name, override in (
            ('OPENAI_API_KEY', dict(api_key='')),
            ('OPENAI_CLASSIFICATION_MODEL', dict(model='')),
        ):
            with self.subTest(name):
                with self.assertRaises(ImproperlyConfigured) as caught:
                    self.validate(**override)

                self.assertIn(name, str(caught.exception))
                self.assertNotIn(API_KEY_SENTINEL, str(caught.exception))
                self.assertNotIn(MODEL, str(caught.exception))

    def test_invalid_timing_configuration_fails(self):
        for override in (
            dict(deadline_seconds=0),
            dict(attempt_timeout_seconds=0),
            dict(attempt_timeout_seconds=30.0),
            dict(max_retries=2),
            dict(max_retries=-1),
            dict(reasoning_effort='extreme'),
        ):
            with self.subTest(override), self.assertRaises(ImproperlyConfigured):
                self.validate(**override)

    def test_invalid_number_names_variable_without_value(self):
        name = 'CLASSIFICATION_TEST_NUMBER'
        os.environ[name] = API_KEY_SENTINEL
        try:
            with self.assertRaises(ImproperlyConfigured) as caught:
                env_number(name, 1.0)
        finally:
            del os.environ[name]

        self.assertIn(name, str(caught.exception))
        self.assertNotIn(API_KEY_SENTINEL, str(caught.exception))
        self.assertTrue(caught.exception.__suppress_context__)
