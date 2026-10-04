"""Database-backed allauth histories and atomic locks, without live-key eviction.

Only application-generated JSON state is accepted; no pickle deserialization.
PostgreSQL is the production backend. SQLite supports fast local regression tests.
"""
import json
from contextlib import contextmanager
from datetime import datetime, timezone

from django.core.cache.backends.base import BaseCache, DEFAULT_TIMEOUT
from django.db import DatabaseError, connections, transaction
from django.utils import timezone as django_timezone


class AuthCacheUnavailable(Exception):
    """Sanitized boundary for database-backed authentication-state failures."""


class DatabaseAuthCache(BaseCache):
    table = 'family_access_authcacheentry'

    def __init__(self, location, params):
        super().__init__(params)

    @contextmanager
    def operation(self):
        try:
            with transaction.atomic(using='default'):
                with connections['default'].cursor() as cursor:
                    if connections['default'].vendor == 'postgresql':
                        cursor.execute("SET LOCAL statement_timeout = '1000ms'")
                        cursor.execute("SET LOCAL lock_timeout = '1000ms'")
                    yield cursor
        except DatabaseError:
            raise AuthCacheUnavailable('Authentication state unavailable.') from None

    def expiry(self, timeout):
        timestamp = self.get_backend_timeout(timeout)
        return datetime.fromtimestamp(timestamp, timezone.utc) if timestamp is not None else None

    def get(self, key, default=None, version=None):
        key = self.make_and_validate_key(key, version=version)
        with self.operation() as cursor:
            cursor.execute(
                f'SELECT value FROM {self.table} WHERE cache_key = %s '
                'AND (expires IS NULL OR expires > %s)', [key, django_timezone.now()],
            )
            row = cursor.fetchone()
        if row is None:
            return default
        try:
            return json.loads(row[0])
        except (ValueError, TypeError):
            raise AuthCacheUnavailable('Authentication state unavailable.') from None

    def write(self, key, value, timeout, version, *, only_if_absent):
        key = self.make_and_validate_key(key, version=version)
        expires = self.expiry(timeout)
        value = json.dumps(value)
        now = django_timezone.now()
        with self.operation() as cursor:
            # Expired histories only. Never discard active protection for capacity.
            cursor.execute(f'DELETE FROM {self.table} WHERE expires <= %s', [now])
            condition = f' WHERE {self.table}.expires <= %s' if only_if_absent else ''
            params = [key, value, expires] + ([now] if only_if_absent else [])
            cursor.execute(
                f'INSERT INTO {self.table} (cache_key, value, expires) VALUES (%s, %s, %s) '
                'ON CONFLICT (cache_key) DO UPDATE SET value = EXCLUDED.value, '
                f'expires = EXCLUDED.expires{condition} RETURNING cache_key', params,
            )
            return cursor.fetchone() is not None

    def add(self, key, value, timeout=DEFAULT_TIMEOUT, version=None):
        return self.write(key, value, timeout, version, only_if_absent=True)

    def set(self, key, value, timeout=DEFAULT_TIMEOUT, version=None):
        return self.write(key, value, timeout, version, only_if_absent=False)

    def delete(self, key, version=None):
        key = self.make_and_validate_key(key, version=version)
        with self.operation() as cursor:
            cursor.execute(f'DELETE FROM {self.table} WHERE cache_key = %s', [key])
            return cursor.rowcount > 0

    def clear(self):
        # Scope clearing to this application's namespace; operator recovery never uses it.
        prefix = self.make_key('', version=self.version)
        with self.operation() as cursor:
            cursor.execute(
                f'DELETE FROM {self.table} WHERE SUBSTR(cache_key, 1, %s) = %s',
                [len(prefix), prefix],
            )
