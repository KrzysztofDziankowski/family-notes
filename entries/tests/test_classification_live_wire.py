"""Opt-in live classification check that logs the full OpenAI HTTP exchange.

Sends one instruction through the configured ``OpenAIClassificationBackend``
and shared validation, and asserts the validated result. The OpenAI client
gets ``httpx2`` event hooks that log the complete request (method, URL,
headers, JSON body) and response (status, headers, JSON body) to stderr. The
``Authorization`` header is redacted.

This is the only place family-shaped text is logged, so it is opt-in and
skipped by default: set ``CLASSIFICATION_LIVE_EVAL=1`` with classification
enabled, a key, and a model. Never run it against real family data.

    CLASSIFICATION_LIVE_EVAL=1 uv run python manage.py test \
        entries.tests.test_classification_live_wire
"""

import datetime
import json
import logging
import os
import sys
import unittest

import httpx2
import openai
from django.conf import settings
from django.test import SimpleTestCase

from entries.classification.backends import BackendRequest
from entries.classification.openai_backend import build_openai_backend
from entries.classification.types import (
    ClassificationProposal,
    EntryType,
    SchoolItemKind,
)
from entries.classification.validation import classify_output

logger = logging.getLogger('entries.tests.openai_wire')

INSTRUCTION = 'kasia zadanie domowe jutro z biologii'
MEMBER_NAMES = ('Kasia',)
# Monday, so "jutro" is Tuesday and no weekend logic is involved.
REFERENCE_DATE = datetime.date(2026, 10, 5)
TOMORROW = datetime.date(2026, 10, 6)
REDACTED_HEADERS = {'authorization', 'cookie', 'set-cookie'}


def _headers(headers):
    return '\n'.join(
        f'  {name}: {"***" if name.lower() in REDACTED_HEADERS else value}'
        for name, value in headers.items()
    )


def _body(content: bytes) -> str:
    text = content.decode('utf-8', errors='replace')
    try:
        return json.dumps(json.loads(text), ensure_ascii=False, indent=2)
    except ValueError:
        return text


def log_request(request):
    logger.debug(
        '>>> OpenAI request\n%s %s\n%s\n\n%s',
        request.method,
        request.url,
        _headers(request.headers),
        _body(request.content),
    )


def log_response(response):
    response.read()
    logger.debug(
        '<<< OpenAI response\n%s %s\n%s\n\n%s',
        response.status_code,
        response.request.url,
        _headers(response.headers),
        _body(response.content),
    )


def make_logging_client():
    return openai.OpenAI(
        api_key=settings.OPENAI_API_KEY,
        max_retries=0,
        http_client=httpx2.Client(
            event_hooks={'request': [log_request], 'response': [log_response]},
        ),
    )


@unittest.skipUnless(
    os.getenv('CLASSIFICATION_LIVE_EVAL') == '1',
    'Live provider call is opt-in: set CLASSIFICATION_LIVE_EVAL=1 with '
    'classification enabled, a key, and a model.',
)
class LiveWireClassificationTests(SimpleTestCase):
    def setUp(self):
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter('%(message)s'))
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        self.addCleanup(logger.removeHandler, handler)

    def test_homework_for_tomorrow(self):
        request = BackendRequest(
            submitted_text=INSTRUCTION,
            allowed_member_names=MEMBER_NAMES,
            reference_date=REFERENCE_DATE,
            locale='pl-PL',
        )
        backend = build_openai_backend(client=make_logging_client())
        try:
            output = backend.classify(request)
        finally:
            backend.close()
        logger.debug('=== Backend output\n%r (content=%r, member_name=%r)',
                     output, output.content, output.member_name)

        result = classify_output(request, output, require_school_subject=True)
        logger.debug('=== Validated result\n%r (content=%r, member_name=%r)',
                     result, getattr(result, 'content', None),
                     getattr(result, 'member_name', None))

        self.assertIsInstance(result, ClassificationProposal)
        self.assertEqual(result.entry_type, EntryType.CALENDAR_EVENT)
        self.assertEqual(result.school_item, SchoolItemKind.HOMEWORK)
        self.assertEqual(result.member_name, 'Kasia')
        self.assertEqual(result.date, TOMORROW)
        self.assertIn('biolog', result.content.lower())
