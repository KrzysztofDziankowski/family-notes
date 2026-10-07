"""US-02 end to end: HTTP intake, conversion, and family access (S-05 Phase 4).

The worker thread is disabled in tests, so each test drives the real intake
endpoint and then calls the conversion service directly, as the worker would.
Payloads are anonymized; "Mateusz" is the PRD's own example name.
"""

import datetime
import json
import logging
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from entries.classification.backends import ClassificationBackendError
from entries.classification.types import EntryType, SchoolItemKind, UnavailableReason
from entries.eduvulcan.conversion import (
    ConversionOutcome,
    convert_due_notifications,
    convert_notification,
)
from entries.eduvulcan.types import OutputKind
from entries.models import Entry, InboundNotification, NotificationConversionOutput
from family_access.models import AutomationToken, Family, FamilyMember

PING_PATH = '/api/automation/ping/'
NOTIFICATIONS_PATH = '/api/automation/notifications/'

PRD_TITLE = 'Sprawdzian'
PRD_MESSAGE = '2 października, Język angielski (j. angielski), Mateusz'
PRD_CAPTURED_AT = '2026-09-23T08:26:16+02:00'
FAMILY_NAME = 'Rodzina Testowa'
Status = InboundNotification.Status


def payload(**overrides):
    """The phone automation's payload shape with anonymized values."""
    values = {
        'id': '00000000-0000-4000-8000-0000000000a1',
        'captured_at_iso': PRD_CAPTURED_AT,
        'package': 'pl.example.eduvulcan',
        'title': PRD_TITLE,
        'message': PRD_MESSAGE,
        'notification_id': '0|pl.example.eduvulcan|1|anon-us02-0001',
    }
    values.update(overrides)
    return values


class NeverCalledBackend:
    """Fixed school rules must handle the PRD example without classification."""

    def classify(self, request):
        raise AssertionError('the PRD example must not reach classification')


class RaisingBackend:
    def __init__(self, error):
        self.error = error
        self.calls = 0

    def classify(self, request):
        self.calls += 1
        raise self.error


@override_settings(EDUVULCAN_WORKER_ENABLED=False)
class EduVulcanAcceptanceTestCase(TestCase):
    def setUp(self):
        super().setUp()
        self.family = Family.objects.create(name=FAMILY_NAME)
        self.other_family = Family.objects.create(name='Inna Rodzina')
        self.parent = self._member('parent', FamilyMember.Role.PARENT, 'Ewa')
        self.mateusz = self._member('mateusz', FamilyMember.Role.CHILD, 'Mateusz')
        self.other_child = self._member('other-child', FamilyMember.Role.CHILD, 'Ania')
        self.other_family_parent = self._member(
            'other-parent', FamilyMember.Role.PARENT, 'Tomek', family=self.other_family
        )
        self.token, self.secret = AutomationToken.issue(self.parent, 'Telefon')

    def _member(self, username, role, display_name, family=None):
        user = get_user_model().objects.create_user(
            username=username, email=f'{username}@example.test'
        )
        return FamilyMember.objects.create(
            user=user, family=family or self.family, role=role, display_name=display_name
        )

    def submit(self, body=None, secret=None):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(
                NOTIFICATIONS_PATH,
                data=json.dumps(body or payload()),
                content_type='application/json',
                HTTP_AUTHORIZATION=f'Bearer {secret or self.secret}',
            )

    def submit_and_convert(self, body=None, backend=None):
        response = self.submit(body)
        self.assertEqual(response.status_code, 202)
        row_id = response.json()['id']
        result = convert_notification(row_id, backend=backend or NeverCalledBackend())
        return row_id, result


class PrdExampleTests(EduVulcanAcceptanceTestCase):
    """US-02: the forwarded "Sprawdzian" becomes Mateusz's calendar entry."""

    def test_notification_is_acknowledged_before_any_conversion(self):
        response = self.submit()

        self.assertEqual(response.status_code, 202)
        row = InboundNotification.objects.get()
        self.assertEqual(response.json(), {'status': 'accepted', 'id': row.pk})
        self.assertEqual((row.status, row.attempt_count), (Status.PENDING, 0))
        self.assertFalse(Entry.objects.exists())

    def test_prd_example_creates_mateusz_calendar_entry(self):
        row_id, result = self.submit_and_convert()

        self.assertEqual(result.outcome, ConversionOutcome.PROCESSED)
        entry = Entry.objects.get()
        self.assertEqual(entry.family, self.family)
        self.assertEqual(entry.entry_type, EntryType.CALENDAR_EVENT.value)
        self.assertEqual(entry.content, 'Sprawdzian: Język angielski')
        self.assertEqual(entry.date, datetime.date(2026, 10, 2))
        self.assertIsNone(entry.time)
        self.assertEqual(entry.assigned_member, self.mateusz)
        self.assertEqual(entry.school_item, SchoolItemKind.TEST.value)
        self.assertEqual(entry.source, Entry.Source.EDUVULCAN)
        self.assertIsNone(entry.created_by)
        self.assertEqual(entry.conversion_output.kind, OutputKind.RULE.value)
        row = InboundNotification.objects.get(pk=row_id)
        self.assertEqual((row.status, row.last_error_code), (Status.PROCESSED, ''))

    def test_resubmission_creates_no_new_inbox_row_or_entry(self):
        row_id, _ = self.submit_and_convert()
        repeats = (
            payload(),
            payload(
                notification_id='0|pl.example.eduvulcan|2|anon-us02-0002',
                captured_at_iso='2026-09-23T19:40:00+02:00',
            ),
        )

        for body in repeats:
            with self.subTest(notification_id=body['notification_id']):
                response = self.submit(body)
                self.assertEqual(response.status_code, 202)
                self.assertEqual(response.json(), {'status': 'accepted', 'id': row_id})
        convert_due_notifications(backend=NeverCalledBackend())

        self.assertEqual(InboundNotification.objects.count(), 1)
        self.assertEqual(Entry.objects.count(), 1)
        self.assertEqual(InboundNotification.objects.get().status, Status.PROCESSED)

    def test_request_without_a_valid_token_saves_nothing(self):
        AutomationToken.objects.filter(pk=self.token.pk).update(
            revoked_at=datetime.datetime(2026, 9, 1, tzinfo=datetime.timezone.utc)
        )

        for secret in (self.secret, 'fnat_unknown'):
            with self.subTest(secret=secret[:9]):
                self.assertEqual(self.submit(secret=secret).status_code, 401)
        response = self.client.post(
            NOTIFICATIONS_PATH, data=json.dumps(payload()), content_type='application/json'
        )
        self.assertEqual(response.status_code, 401)
        self.assertFalse(InboundNotification.objects.exists())
        self.assertFalse(Entry.objects.exists())


class ConvertedEntryAccessTests(EduVulcanAcceptanceTestCase):
    """Parents manage the converted entry; only the assigned child may read it."""

    def setUp(self):
        super().setUp()
        self.row_id, _ = self.submit_and_convert()
        self.entry = Entry.objects.get()
        self.unconfigured = get_user_model().objects.create_user(username='unconfigured')

    def edit_data(self, **overrides):
        data = {
            'entry_type': EntryType.CALENDAR_EVENT.value,
            'content': 'Sprawdzian: Język angielski, rozdział 2',
            'date': '2026-10-05',
            'time': '',
            'assigned_member': str(self.mateusz.pk),
            'school_item': SchoolItemKind.TEST.value,
            'school_subject': 'Język angielski',
            'view': '',
        }
        data.update(overrides)
        return data

    def state(self):
        return list(
            Entry.objects.order_by('pk').values_list(
                'pk', 'entry_type', 'content', 'date', 'assigned_member_id', 'source'
            )
        )

    def test_parent_can_inspect_correct_and_delete(self):
        self.client.force_login(self.parent.user)

        detail = self.client.get(reverse('entries:detail', args=[self.entry.pk]))
        self.assertContains(detail, 'Sprawdzian: Język angielski')
        self.assertContains(detail, 'EduVulcan')
        self.assertContains(detail, 'Mateusz')
        self.assertEqual(self.entry.school_subject, 'Język angielski')
        self.assertContains(detail, '<dd>Język angielski</dd>', html=True)

        edit = self.client.post(reverse('entries:edit', args=[self.entry.pk]), self.edit_data())
        self.assertRedirects(edit, reverse('entries:detail', args=[self.entry.pk]))
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.content, 'Sprawdzian: Język angielski, rozdział 2')
        self.assertEqual(self.entry.date, datetime.date(2026, 10, 5))
        self.assertEqual(self.entry.assigned_member, self.mateusz)
        self.assertEqual(self.entry.source, Entry.Source.EDUVULCAN)

        delete = self.client.post(reverse('entries:delete', args=[self.entry.pk]))
        self.assertEqual(delete.status_code, 302)
        self.assertFalse(Entry.objects.exists())

    def test_deleted_entry_is_not_recreated_by_resubmission_or_sweep(self):
        self.client.force_login(self.parent.user)
        self.client.post(reverse('entries:delete', args=[self.entry.pk]))

        response = self.submit()
        convert_due_notifications(backend=NeverCalledBackend())

        self.assertEqual(response.json()['id'], self.row_id)
        self.assertFalse(Entry.objects.exists())
        output = NotificationConversionOutput.objects.get()
        self.assertIsNone(output.entry)

    def test_assigned_child_can_read_it_without_management_access(self):
        self.client.force_login(self.mateusz.user)

        listing = self.client.get(reverse('entries:child_list'), {'view': 'past'})
        upcoming = self.client.get(reverse('entries:child_list'))
        self.assertIn('Sprawdzian: Język angielski', listing.content.decode() + upcoming.content.decode())
        detail = self.client.get(reverse('entries:child_detail', args=[self.entry.pk]))
        self.assertContains(detail, 'Sprawdzian: Język angielski')
        self.assertContains(detail, 'EduVulcan')

        before = self.state()
        for method, url in self.management_requests():
            with self.subTest(url=url):
                self.assertEqual(self.send(method, url).status_code, 403)
        self.assertEqual(self.state(), before)

    def test_another_child_cannot_read_or_manage_it(self):
        self.client.force_login(self.other_child.user)

        detail = self.client.get(reverse('entries:child_detail', args=[self.entry.pk]))
        self.assertEqual(detail.status_code, 404)
        self.assertNotContains(detail, 'Język angielski', status_code=404)
        self.assertNotContains(self.client.get(reverse('entries:child_list')), 'Język angielski')

        before = self.state()
        for method, url in self.management_requests():
            with self.subTest(url=url):
                response = self.send(method, url)
                self.assertEqual(response.status_code, 403)
                self.assertNotContains(response, 'Język angielski', status_code=403)
        self.assertEqual(self.state(), before)

    def test_unauthenticated_user_is_sent_to_login_without_data(self):
        before = self.state()
        urls = [('get', reverse('entries:child_detail', args=[self.entry.pk]))]
        for method, url in urls + self.management_requests():
            with self.subTest(url=url):
                response = self.send(method, url)
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse('account_login'), response['Location'])
        self.assertEqual(self.state(), before)

    def test_other_family_parent_cannot_reach_it(self):
        self.client.force_login(self.other_family_parent.user)

        before = self.state()
        for method, url in self.management_requests():
            with self.subTest(url=url):
                response = self.send(method, url)
                self.assertEqual(response.status_code, 404)
        self.assertEqual(self.state(), before)

    def management_requests(self):
        pk = self.entry.pk
        return [
            ('get', reverse('entries:detail', args=[pk])),
            ('post', reverse('entries:edit', args=[pk])),
            ('post', reverse('entries:delete', args=[pk])),
        ]

    def send(self, method, url):
        if method == 'post':
            return self.client.post(url, self.edit_data(content='Nadpisane'))
        return self.client.get(url)


class UnknownFormatTests(EduVulcanAcceptanceTestCase):
    """A notification no rule recognises still reaches the family as a note."""

    UNKNOWN = payload(
        notification_id='0|pl.example.eduvulcan|5|anon-us02-0005',
        title='Ogłoszenie',
        message='Wycieczka klasowa do muzeum w piątek',
    )

    def test_unknown_format_becomes_a_general_family_note(self):
        backend = RaisingBackend(ClassificationBackendError(UnavailableReason.REFUSED))

        _, result = self.submit_and_convert(self.UNKNOWN, backend=backend)

        self.assertEqual(result.outcome, ConversionOutcome.PROCESSED)
        self.assertEqual(backend.calls, 1)
        entry = Entry.objects.get()
        self.assertEqual(entry.entry_type, EntryType.NOTE.value)
        self.assertEqual(entry.content, 'Ogłoszenie: Wycieczka klasowa do muzeum w piątek')
        self.assertEqual(entry.date, datetime.date(2026, 9, 23))
        self.assertIsNone(entry.assigned_member)
        self.assertEqual(entry.source, Entry.Source.EDUVULCAN)
        self.assertEqual(entry.conversion_output.kind, OutputKind.GENERAL_NOTE.value)

        self.client.force_login(self.parent.user)
        self.assertContains(
            self.client.get(reverse('entries:detail', args=[entry.pk])), 'Wycieczka klasowa'
        )
        self.client.force_login(self.mateusz.user)
        self.assertEqual(
            self.client.get(reverse('entries:child_detail', args=[entry.pk])).status_code, 404
        )

    @override_settings(CLASSIFICATION_ENABLED=False)
    def test_disabled_classification_also_yields_a_general_note(self):
        response = self.submit(self.UNKNOWN)

        result = convert_notification(response.json()['id'])

        self.assertEqual(result.outputs[0].kind, OutputKind.GENERAL_NOTE.value)
        self.assertIsNone(Entry.objects.get().assigned_member)
        self.assertEqual(Entry.objects.get().date, datetime.date(2026, 9, 23))


class SanitizedFailureTests(EduVulcanAcceptanceTestCase):
    """Diagnostics carry IDs and codes only, never family or provider text."""

    SENTINEL = 'SENTINEL-US02-5d1c'
    PROVIDER_BODY = '{"error": {"message": "provider body SENTINEL-PROVIDER-88e2"}}'

    def unknown(self):
        return payload(
            notification_id='0|pl.example.eduvulcan|7|anon-us02-0007',
            title='Ogłoszenie',
            message=f'Zebranie {self.SENTINEL} dla Mateusz',
        )

    def assert_sanitized(self, text):
        for sensitive in (
            self.SENTINEL,
            'SENTINEL-PROVIDER-88e2',
            'provider body',
            'Zebranie',
            'Ogłoszenie',
            'Mateusz',
            'Ewa',
            FAMILY_NAME,
            self.secret,
            self.token.token_hash,
        ):
            self.assertNotIn(sensitive, text)

    def test_unexpected_provider_error_fails_with_a_safe_code_only(self):
        backend = RaisingBackend(RuntimeError(self.PROVIDER_BODY))
        response = self.submit(self.unknown())

        with self.assertLogs('entries.eduvulcan', logging.INFO) as logs:
            result = convert_notification(response.json()['id'], backend=backend)

        self.assertEqual(result.outcome, ConversionOutcome.FAILED)
        row = InboundNotification.objects.get()
        self.assertEqual((row.status, row.last_error_code), (Status.FAILED, 'conversion_error'))
        self.assertEqual(row.error, '')
        self.assertFalse(Entry.objects.exists())
        diagnostics = '\n'.join(logs.output) + row.last_error_code + str(row)
        self.assert_sanitized(diagnostics)
        self.assertIn(f'notification={row.pk}', diagnostics)
        self.assertIn('error=RuntimeError', diagnostics)

    def test_rules_bug_falls_through_to_classification_and_a_general_note(self):
        backend = RaisingBackend(ClassificationBackendError(UnavailableReason.REFUSED))
        row_id = self.submit(self.unknown()).json()['id']

        with mock.patch(
            'entries.eduvulcan.conversion.propose_entries',
            side_effect=RuntimeError(f'rules crashed on {self.SENTINEL} Mateusz'),
        ), self.assertLogs('entries.eduvulcan', logging.INFO) as logs:
            result = convert_notification(row_id, backend=backend)

        self.assertEqual(result.outcome, ConversionOutcome.PROCESSED)
        self.assertEqual(backend.calls, 1)
        row = InboundNotification.objects.get()
        self.assertEqual((row.status, row.last_error_code), (Status.PROCESSED, ''))
        entry = Entry.objects.get()
        self.assertEqual(entry.conversion_output.kind, OutputKind.GENERAL_NOTE.value)
        self.assertIn(self.SENTINEL, entry.content)
        self.assertEqual(entry.date, datetime.date(2026, 9, 23))
        output = '\n'.join(logs.output)
        self.assert_sanitized(output)
        self.assertIn(
            f'rules error: notification={row_id} attempt=1 error=RuntimeError', output
        )
        self.assertNotIn('rules crashed', output)

    def test_unexpected_persistence_error_still_fails_the_row(self):
        row_id = self.submit(self.unknown()).json()['id']

        with mock.patch(
            'entries.eduvulcan.conversion.create_automated_entry',
            side_effect=RuntimeError(self.SENTINEL),
        ), self.assertLogs('entries.eduvulcan', logging.INFO) as logs:
            result = convert_notification(
                row_id,
                backend=RaisingBackend(ClassificationBackendError(UnavailableReason.REFUSED)),
            )

        self.assertEqual(result.outcome, ConversionOutcome.FAILED)
        row = InboundNotification.objects.get()
        self.assertEqual((row.status, row.last_error_code), (Status.FAILED, 'conversion_error'))
        output = '\n'.join(logs.output)
        self.assert_sanitized(output)
        self.assertIn('code=conversion_error error=RuntimeError', output)

    @override_settings(EDUVULCAN_CONVERSION_RETRY_DELAYS_SECONDS=(0, 0))
    def test_exhausted_provider_outage_saves_a_note_with_a_safe_code(self):
        backend = RaisingBackend(ClassificationBackendError(UnavailableReason.TIMEOUT))
        row_id = self.submit(self.unknown()).json()['id']

        with self.assertLogs('entries.eduvulcan', logging.INFO) as logs:
            outcomes = [
                convert_notification(row_id, backend=backend).outcome for _ in range(3)
            ]

        self.assertEqual(
            outcomes,
            [
                ConversionOutcome.RETRY_SCHEDULED,
                ConversionOutcome.RETRY_SCHEDULED,
                ConversionOutcome.PROCESSED,
            ],
        )
        row = InboundNotification.objects.get()
        self.assertEqual((row.status, row.last_error_code), (Status.PROCESSED, 'provider_timeout'))
        self.assertEqual(Entry.objects.get().conversion_output.kind, OutputKind.GENERAL_NOTE.value)
        self.assertEqual(Entry.objects.get().date, datetime.date(2026, 9, 23))
        self.assert_sanitized('\n'.join(logs.output) + row.last_error_code + row.error)

    def test_conversion_health_response_carries_no_notification_data(self):
        self.submit(self.unknown())

        response = self.client.get('/healthz/conversion/')

        self.assertEqual(response.json(), {'status': 'disabled'})
        self.assert_sanitized(response.content.decode())


class AutomationApiCompatibilityTests(EduVulcanAcceptanceTestCase):
    """The namespaced include keeps the public paths and response bodies."""

    def test_route_names_resolve_to_the_unchanged_public_paths(self):
        self.assertEqual(reverse('automation:ping'), PING_PATH)
        self.assertEqual(reverse('automation:notification_submit'), NOTIFICATIONS_PATH)

    def test_public_paths_keep_their_response_bodies(self):
        auth = {'HTTP_AUTHORIZATION': f'Bearer {self.secret}'}

        ping = self.client.get(PING_PATH, **auth)
        self.assertEqual((ping.status_code, ping.json()), (200, {'status': 'ok', 'token': 'Telefon'}))

        rejected = self.client.get(PING_PATH)
        self.assertEqual(
            (rejected.status_code, rejected.json()), (401, {'error': 'invalid_token'})
        )
        self.assertEqual(rejected['WWW-Authenticate'], 'Bearer')

        accepted = self.submit()
        self.assertEqual(accepted.status_code, 202)
        self.assertEqual(
            accepted.json(), {'status': 'accepted', 'id': InboundNotification.objects.get().pk}
        )

        invalid = self.client.post(
            NOTIFICATIONS_PATH, data='{not json', content_type='application/json', **auth
        )
        self.assertEqual((invalid.status_code, invalid.json()), (400, {'error': 'invalid_payload'}))
