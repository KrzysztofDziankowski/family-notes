from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.core.management.base import BaseCommand, CommandError
from family_notes.auth_cache import AuthCacheUnavailable

from family_notes.auth_security import reset_admin_login_limits


class Command(BaseCommand):
    help = 'Reset only an active operator and client IP login limits.'

    def add_arguments(self, parser):
        parser.add_argument('--user-id', required=True, type=int)
        parser.add_argument('--client-ip', required=True)

    def handle(self, *args, **options):
        try:
            reset_admin_login_limits(options['user_id'], options['client_ip'])
        except (ValidationError, AuthCacheUnavailable, DatabaseError):
            raise CommandError('admin_login_limits_reset_failed') from None
        self.stdout.write(f"admin_login_limits_reset_ok user_id={options['user_id']}")
