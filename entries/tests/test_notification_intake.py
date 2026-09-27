import inspect
import json
from datetime import date, timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase
from django.urls import resolve, reverse
from django.utils import timezone

from entries import api_views
from entries.models import InboundNotification
from family_access.models import AutomationToken, Family, FamilyMember
from family_access.test_automation import AutomationFixtureMixin

URL = reverse('automation_notification_submit')


def sample_payload(**overrides):
    """Anonymized copy of the phone automation's payload shape (fictional names)."""
    values = {
        'id': '00000000-0000-4000-8000-000000000001',
        'captured_at': 1790000000.0,
        'captured_at_iso': '2026-09-23T08:26:16+02:00',
        'package': 'pl.example.eduvulcan',
        'channel': 'example_channel',
        'title': 'Sprawdzian',
        'tickerText': None,
        'message': 'Jan Przykładowy: sprawdzian z biologii 28.09',
        'notification_id': '0|pl.example.eduvulcan|1|anon-0000000000000000000000000000001',
        'notification_when': None,
    }
    values.update(overrides)
    return values


class NotificationIntakeTests(AutomationFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.token, self.secret = AutomationToken.issue(self.parent, 'Telefon')

    def post(self, payload=None, secret=None, raw=None, client=None):
        body = raw if raw is not None else json.dumps(payload or sample_payload())
        return (client or self.client).post(
            URL,
            data=body,
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {secret or self.secret}',
        )

    def test_valid_notification_is_stored_pending_and_acknowledged(self):
        response = self.post()

        self.assertEqual(response.status_code, 202)
        row = InboundNotification.objects.get()
        self.assertEqual(response.json(), {'status': 'accepted', 'id': row.pk})
        self.assertEqual(row.status, InboundNotification.Status.PENDING)
        self.assertEqual(row.family, self.family)
        self.assertEqual(row.token, self.token)
        self.assertEqual(row.title, 'Sprawdzian')
        self.assertEqual(row.payload, sample_payload())
        self.assertEqual(row.captured_date, date(2026, 9, 23))

    def test_request_path_is_bounded_and_never_classifies(self):
        def fail_if_called(*args, **kwargs):
            raise AssertionError('classification must not run in the intake request')

        with mock.patch(
            'entries.classification.service.classify_for_parent', side_effect=fail_if_called
        ), self.assertNumQueries(6):
            # token lookup, last_used_at update, duplicate lookup,
            # then savepoint + insert + release for the new row.
            response = self.post()

        self.assertEqual(response.status_code, 202)
        self.assertNotIn('classification', inspect.getsource(api_views))

    def test_same_notification_id_is_idempotent_per_family(self):
        first = self.post()
        second = self.post(sample_payload(title='Inny tytuł', message='Inna treść'))

        self.assertEqual(second.status_code, 202)
        self.assertEqual(second.json()['id'], first.json()['id'])
        self.assertEqual(InboundNotification.objects.count(), 1)

        other_family = Family.objects.create(name='Other Family')
        other_parent = self.create_member('other-parent', FamilyMember.Role.PARENT, family=other_family)
        _, other_secret = AutomationToken.issue(other_parent, 'Inny telefon')
        third = self.post(secret=other_secret)

        self.assertEqual(third.status_code, 202)
        self.assertNotEqual(third.json()['id'], first.json()['id'])
        self.assertEqual(InboundNotification.objects.count(), 2)

    def test_same_day_content_under_new_id_is_deduplicated(self):
        first = self.post()
        repeat = self.post(
            sample_payload(
                notification_id='0|pl.example.eduvulcan|2|anon-new-id',
                captured_at_iso='2026-09-23T19:00:00+02:00',
                message='  Jan   Przykładowy:  sprawdzian z biologii 28.09 ',
            )
        )

        self.assertEqual(repeat.json()['id'], first.json()['id'])
        self.assertEqual(InboundNotification.objects.count(), 1)

    def test_same_content_next_day_creates_new_row(self):
        self.post()
        next_day = self.post(
            sample_payload(
                notification_id='0|pl.example.eduvulcan|3|anon-next-day',
                captured_at_iso='2026-09-24T08:00:00+02:00',
            )
        )

        self.assertEqual(next_day.status_code, 202)
        self.assertEqual(InboundNotification.objects.count(), 2)

    def test_captured_date_uses_polish_local_day(self):
        # 00:30 in Warsaw is still the previous day in UTC.
        self.post(sample_payload(captured_at_iso='2026-09-24T00:30:00+02:00'))

        self.assertEqual(InboundNotification.objects.get().captured_date, date(2026, 9, 24))

    def test_race_on_create_returns_winning_row(self):
        winner = self.post().json()['id']
        real_filter = InboundNotification.objects.filter
        calls = []

        def miss_first_lookup(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                return InboundNotification.objects.none()
            return real_filter(*args, **kwargs)

        with mock.patch.object(InboundNotification.objects, 'filter', side_effect=miss_first_lookup):
            response = self.post()

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()['id'], winner)
        self.assertEqual(InboundNotification.objects.count(), 1)

    def test_invalid_payloads_are_rejected_without_storing(self):
        cases = {
            'not json': '{not json',
            'not an object': json.dumps(['a']),
            'missing title': json.dumps({k: v for k, v in sample_payload().items() if k != 'title'}),
            'empty message': json.dumps(sample_payload(message='   ')),
            'non-string id': json.dumps(sample_payload(notification_id=5)),
            'bad date': json.dumps(sample_payload(captured_at_iso='wczoraj')),
            'missing date': json.dumps(sample_payload(captured_at_iso=None)),
        }
        for name, raw in cases.items():
            with self.subTest(name):
                response = self.post(raw=raw)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json(), {'error': 'invalid_payload'})
        self.assertFalse(InboundNotification.objects.exists())

    def test_oversized_body_is_rejected(self):
        response = self.post(sample_payload(message='x' * (17 * 1024)))

        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json(), {'error': 'payload_too_large'})
        self.assertFalse(InboundNotification.objects.exists())

    def test_token_rejections_store_nothing(self):
        AutomationToken.objects.filter(pk=self.token.pk).update(revoked_at=timezone.now())
        expired, expired_secret = AutomationToken.issue(
            self.parent, 'Stary', expires_at=timezone.now() - timedelta(seconds=1)
        )
        _, child_owned_secret = AutomationToken.issue(self.parent, 'Zmieniony')
        for secret in (self.secret, expired_secret, 'fnat_unknown'):
            with self.subTest(secret=secret[:9]):
                response = self.post(secret=secret)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response['WWW-Authenticate'], 'Bearer')

        self.parent.role = FamilyMember.Role.CHILD
        self.parent.save(update_fields=('role',))
        self.assertEqual(self.post(secret=child_owned_secret).status_code, 401)

        response = self.client.post(URL, data=json.dumps(sample_payload()), content_type='application/json')
        self.assertEqual(response.status_code, 401)
        self.assertFalse(InboundNotification.objects.exists())

    def test_get_is_not_allowed_and_route_is_csrf_exempt(self):
        response = self.client.get(URL, HTTP_AUTHORIZATION=f'Bearer {self.secret}')
        self.assertEqual(response.status_code, 405)

        response = self.post(client=self.client_class(enforce_csrf_checks=True))
        self.assertEqual(response.status_code, 202)
        self.assertTrue(resolve(URL).func.csrf_exempt)


class InboundNotificationAdminTests(AutomationFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        token, _ = AutomationToken.issue(self.parent, 'Telefon')
        self.row = InboundNotification.objects.create(
            family=self.family,
            token=token,
            notification_id='anon-1',
            title='Sprawdzian',
            message='Jan Przykładowy: sprawdzian',
            captured_at=timezone.now(),
            captured_date=timezone.localdate(),
            content_hash='0' * 64,
            payload={},
        )

    def test_admin_is_read_only_for_superuser(self):
        superuser = get_user_model().objects.create_superuser(
            username='operator', email='operator@example.test', password='unused'
        )
        self.client.force_login(superuser)

        changelist = self.client.get(reverse('admin:entries_inboundnotification_changelist'))
        self.assertEqual(changelist.status_code, 200)
        self.assertContains(changelist, 'Sprawdzian')
        self.assertEqual(
            self.client.get(reverse('admin:entries_inboundnotification_add')).status_code, 403
        )
        change_url = reverse('admin:entries_inboundnotification_change', args=(self.row.pk,))
        self.client.post(change_url, {'title': 'Zmieniony', 'status': 'processed'})
        self.row.refresh_from_db()
        self.assertEqual(self.row.title, 'Sprawdzian')
        self.assertEqual(self.row.status, 'pending')

    def test_admin_is_denied_to_family_members(self):
        self.client.force_login(self.parent.user)
        url = reverse('admin:entries_inboundnotification_changelist')

        response = self.client.get(url)

        self.assertRedirects(response, f"{reverse('admin:login')}?next={url}")
