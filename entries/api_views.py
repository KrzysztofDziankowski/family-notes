"""Token-authenticated automation API.

- Notification intake: store unchanged, answer fast, never classify.
- Family entries read: the token owner's family only, filtered by inclusive
  dates, ordered by ``created_at, id`` and paginated with ``limit + offset``.
"""

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_GET, require_POST

from family_access.automation import automation_token_required

from .eduvulcan.worker import schedule_wakeup
from .models import InboundNotification
from .services import automation_family_entries

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
                # Only a post-commit wake-up for the worker; the row is
                # already durable, so a skipped wake-up waits for a sweep.
                schedule_wakeup(existing.pk)
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


# --- Family entries read (S-06) ----------------------------------------------

DEFAULT_LIMIT = 100
MAX_LIMIT = 500
# At most 18 digits: stays below the 64-bit SQL OFFSET limit and int()'s digit cap.
_UNSIGNED_INT = re.compile(r'[0-9]{1,18}')
_ISO_DATE = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}')
_BOOLEANS = {'true': True, 'false': False}


@dataclass(frozen=True)
class EntriesQuery:
    limit: int = DEFAULT_LIMIT
    offset: int = 0
    date_from: date | None = None
    date_to: date | None = None
    include_undated: bool = True


def _parse_unsigned_int(value):
    if not _UNSIGNED_INT.fullmatch(value):
        return None
    return int(value)


def _parse_iso_date(value):
    if not _ISO_DATE.fullmatch(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        # Well-formed but impossible, e.g. 2026-02-30.
        return None


def parse_entries_query(params):
    """Validate the public query parameters; ``None`` means ``invalid_query``.

    Unknown parameters are ignored for forward compatibility.
    """
    limit = DEFAULT_LIMIT
    if 'limit' in params:
        limit = _parse_unsigned_int(params['limit'])
        if limit is None or not 1 <= limit <= MAX_LIMIT:
            return None
    offset = 0
    if 'offset' in params:
        offset = _parse_unsigned_int(params['offset'])
        if offset is None:
            return None
    bounds = {}
    for name in ('date_from', 'date_to'):
        if name in params:
            bounds[name] = _parse_iso_date(params[name])
            if bounds[name] is None:
                return None
    date_from, date_to = bounds.get('date_from'), bounds.get('date_to')
    if date_from is not None and date_to is not None and date_from > date_to:
        return None
    # Undated entries belong to an unbounded read, not to a date range.
    include_undated = not bounds
    if 'include_undated' in params:
        include_undated = _BOOLEANS.get(params['include_undated'].lower())
        if include_undated is None:
            return None
    return EntriesQuery(limit, offset, date_from, date_to, include_undated)


def _iso_or_none(value):
    return value.isoformat() if value is not None else None


def serialize_entry(entry):
    """Explicit allow-list of entry fields; never family, creator or keys."""
    member = entry.assigned_member
    return {
        'id': entry.pk,
        'entry_type': entry.entry_type,
        'content': entry.content,
        'date': _iso_or_none(entry.date),
        'time': _iso_or_none(entry.time),
        'assigned_member': {'display_name': member.display_name} if member else None,
        'school_item': entry.school_item or None,
        'school_subject': entry.school_subject or None,
        'source': entry.source,
        'created_at': _iso_or_none(entry.created_at),
        'updated_at': _iso_or_none(entry.updated_at),
    }


def entries_page(queryset, query):
    """Envelope for one page; ``count`` is the filtered total before paging."""
    count = queryset.count()
    page = queryset[query.offset:query.offset + query.limit]
    return {
        'count': count,
        'limit': query.limit,
        'offset': query.offset,
        'results': [serialize_entry(entry) for entry in page],
    }


@require_GET
@automation_token_required
def list_family_entries(request):
    query = parse_entries_query(request.GET)
    if query is None:
        return JsonResponse({'error': 'invalid_query'}, status=400)
    # The family comes only from the authenticated token, never from the client.
    queryset = automation_family_entries(
        request.automation_membership,
        date_from=query.date_from,
        date_to=query.date_to,
        include_undated=query.include_undated,
    )
    return JsonResponse(entries_page(queryset, query))
