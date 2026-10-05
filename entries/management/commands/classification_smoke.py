"""Operator smoke check for the configured classification provider.

Sends one synthetic Polish school instruction through the configured backend
and shared validation, then prints only safe outcome fields. It uses no
database rows, no family data, and no authenticated user; it proves provider
configuration, privacy settings, and timing, not family authorization.

The operator passes a freshly generated ``--sentinel`` token. It is embedded
in the synthetic instruction but never printed or logged by this command, so
the operator can search application, journald, and nginx logs for it
afterwards and expect no match.
"""

from __future__ import annotations

import re
import time

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from entries.classification.backends import BackendRequest
from entries.classification.openai_backend import build_openai_backend
from entries.classification.types import (
    ClassificationError,
    ClassificationUnavailable,
    UnavailableReason,
)
from entries.classification.validation import classify_output

SMOKE_BUDGET_SECONDS = 30.0
SENTINEL_PATTERN = re.compile(r'^[A-Za-z0-9-]{12,64}$')
SYNTHETIC_MEMBER_NAMES = ('Michał', 'Ewa')

# Monotonic clock seam for tests; production always uses the real clock.
clock = time.monotonic


def synthetic_instruction(sentinel: str) -> str:
    # Sent to OpenAI, so it is Polish. Only synthetic content is allowed here.
    return (
        'Michał ma w poniedziałek sprawdzian z biologii o skórze. '
        f'Kod testowy: {sentinel}.'
    )


class Command(BaseCommand):
    help = (
        'Classify one synthetic instruction with the configured provider and '
        'report only the safe outcome and elapsed time.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--sentinel',
            required=True,
            help='Fresh synthetic token (12-64 letters, digits, or hyphens) to '
            'search for in logs afterwards; it is never printed.',
        )

    def handle(self, *args, sentinel, **options):
        if not SENTINEL_PATTERN.match(sentinel):
            raise CommandError(
                '--sentinel must be 12-64 letters, digits, or hyphens.'
            )
        request = BackendRequest(
            submitted_text=synthetic_instruction(sentinel),
            allowed_member_names=SYNTHETIC_MEMBER_NAMES,
            reference_date=timezone.localdate(),
            locale='pl-PL',
        )

        started_at = clock()
        try:
            backend = build_openai_backend()
            try:
                output = backend.classify(request)
            finally:
                backend.close()
            # Provider health only, not the parent flow: never ask for a subject.
            result = classify_output(request, output, require_school_subject=False)
        except ClassificationError as error:
            result = error.to_result()
        elapsed = clock() - started_at

        self.stdout.write(_describe(result, request, elapsed))
        if isinstance(result, ClassificationUnavailable) and (
            result.reason == UnavailableReason.DISABLED
        ):
            raise CommandError(
                'Classification is disabled or incompletely configured '
                '(enablement, API key, and model are required).'
            )
        if elapsed > SMOKE_BUDGET_SECONDS:
            raise CommandError(
                f'Classification exceeded the {SMOKE_BUDGET_SECONDS:.0f}-second budget.'
            )


def _describe(result, request: BackendRequest, elapsed: float) -> str:
    """Render safe fields only: never content, member names, or the sentinel."""
    fields = [f'outcome={result.kind}']
    if isinstance(result, ClassificationUnavailable):
        fields.append(f'reason={result.reason.value}')
    else:
        fields.append(f'entry_type={result.entry_type.value}')
        fields.append(f'reference_date={request.reference_date.isoformat()}')
        fields.append(f'date={result.date.isoformat() if result.date else "-"}')
        fields.append(f'member_resolved={"yes" if result.member_name else "no"}')
        missing = getattr(result, 'missing_fields', ())
        if missing:
            fields.append('missing=' + ','.join(field.value for field in missing))
    fields.append(f'elapsed_ms={int(round(elapsed * 1000))}')
    fields.append(f'budget_s={SMOKE_BUDGET_SECONDS:.0f}')
    return 'classification smoke ' + ' '.join(fields)
