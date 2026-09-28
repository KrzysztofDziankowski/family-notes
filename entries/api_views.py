"""Token-authenticated notification intake: store unchanged, answer fast, never classify."""

import hashlib
import json
import unicodedata

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_POST

from family_access.automation import automation_token_required

from .models import InboundNotification

MAX_BODY_BYTES = 16 * 1024
REQUIRED_TEXT_FIELDS = ('title', 'message', 'notification_id')
MAX_FIELD_LENGTHS = {'title': 255, 'notification_id': 255}


def content_hash(title, message):
    """SHA-256 of title and message after NFC, trimming and whitespace collapsing."""

    def normalize(value):
        return ' '.join(unicodedata.normalize('NFC', value).split())

    text = f'{normalize(title)}\n{normalize(message)}'
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _contains_nul(value):
    if isinstance(value, str):
        return '\x00' in value
    if isinstance(value, dict):
        return any(_contains_nul(k) or _contains_nul(v) for k, v in value.items())
    if isinstance(value, list):
        return any(_contains_nul(item) for item in value)
    return False


def _invalid():
    return JsonResponse({'error': 'invalid_payload'}, status=400)


def _parse_payload(body):
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    # PostgreSQL rejects NUL in text and jsonb columns; SQLite would accept it.
    if _contains_nul(payload):
        return None
    for name in REQUIRED_TEXT_FIELDS:
        value = payload.get(name)
        if not isinstance(value, str) or not value.strip():
            return None
        if len(value) > MAX_FIELD_LENGTHS.get(name, len(value)):
            return None
    captured_iso = payload.get('captured_at_iso')
    try:
        captured_at = parse_datetime(captured_iso) if isinstance(captured_iso, str) else None
    except ValueError:
        # Well-formed but impossible, e.g. 2026-02-30T10:00:00.
        return None
    if captured_at is None:
        return None
    if timezone.is_naive(captured_at):
        captured_at = timezone.make_aware(captured_at)
    return payload, captured_at


@require_POST
@automation_token_required
def submit_notification(request):
    content_length = request.META.get('CONTENT_LENGTH') or '0'
    if (content_length.isdigit() and int(content_length) > MAX_BODY_BYTES) or (
        len(request.body) > MAX_BODY_BYTES
    ):
        return JsonResponse({'error': 'payload_too_large'}, status=413)

    parsed = _parse_payload(request.body)
    if parsed is None:
        return _invalid()
    payload, captured_at = parsed

    family = request.automation_membership.family
    values = {
        'notification_id': payload['notification_id'],
        'content_hash': content_hash(payload['title'], payload['message']),
        'captured_date': timezone.localdate(captured_at),
    }
    duplicate_of = (
        Q(notification_id=values['notification_id'])
        | Q(content_hash=values['content_hash'], captured_date=values['captured_date'])
    )
    existing = (
        InboundNotification.objects.filter(family=family).filter(duplicate_of).order_by('pk').first()
    )
    if existing is None:
        try:
            with transaction.atomic():
                existing = InboundNotification.objects.create(
                    family=family,
                    token=request.automation_token,
                    title=payload['title'],
                    message=payload['message'],
                    captured_at=captured_at,
                    payload=payload,
                    **values,
                )
        except IntegrityError:
            # A concurrent copy won the race; answer with its row.
            existing = (
                InboundNotification.objects.filter(family=family)
                .filter(duplicate_of)
                .order_by('pk')
                .first()
            )
            if existing is None:
                raise
    return JsonResponse({'status': 'accepted', 'id': existing.pk}, status=202)
