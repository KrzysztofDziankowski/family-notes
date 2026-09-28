"""Ninety-day raw-data pruning of processed EduVulcan notifications (S-05 Phase 2)."""

import datetime
import json

from django.test import TestCase
from django.urls import reverse

from entries.eduvulcan.conversion import convert_notification, prune_raw_notifications
from entries.eduvulcan.types import OutputKind
from entries.models import Entry, InboundNotification
from family_access.models import AutomationToken
from family_access.test_automation import AutomationFixtureMixin

from .test_notification_intake import sample_payload

Status = InboundNotification.Status
NOW = datetime.datetime(2027, 1, 10, 12, 0, tzinfo=datetime.timezone.utc)
OLD = NOW - datetime.timedelta(days=90)
URL = reverse('automation_notification_submit')


class RawDataPruningTests(AutomationFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.token, self.secret = AutomationToken.issue(self.parent, 'Telefon')

    def post(self, payload):
        return self.client.post(
            URL,
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {self.secret}',
        )

    def intake(self, index=1, **overrides):
        payload = sample_payload(
            notification_id=f'0|pl.example.eduvulcan|{index}|anon',
            message=f'2 października, Biologia (biologia), Child {index}',
            **overrides,
        )
        response = self.post(payload)
        self.assertEqual(response.status_code, 202)
        return InboundNotification.objects.get(pk=response.json()['id']), payload

    def age(self, row, received_at=OLD):
        InboundNotification.objects.filter(pk=row.pk).update(received_at=received_at)

    def processed(self, index=1, received_at=OLD):
        row, payload = self.intake(index)
        result = convert_notification(row.pk)
        self.assertEqual(result.outcome.value, 'processed')
        self.age(row, received_at)
        row.refresh_from_db()
        return row, payload

    def test_old_processed_rows_are_scrubbed_with_empty_sentinels(self):
        row, _ = self.processed()
        identifiers = (row.notification_id, row.content_hash, row.captured_date, row.processed_at)

        self.assertEqual(prune_raw_notifications(now=NOW), 1)

        row.refresh_from_db()
        self.assertEqual((row.title, row.message, row.payload), ('', '', {}))
        self.assertEqual(row.raw_pruned_at, NOW)
        self.assertEqual(row.status, Status.PROCESSED)
        self.assertEqual(
            (row.notification_id, row.content_hash, row.captured_date, row.processed_at),
            identifiers,
        )

    def test_rows_younger_than_ninety_days_are_kept(self):
        row, payload = self.processed(received_at=OLD + datetime.timedelta(seconds=1))

        self.assertEqual(prune_raw_notifications(now=NOW), 0)

        row.refresh_from_db()
        self.assertEqual(row.payload, payload)
        self.assertIsNone(row.raw_pruned_at)

    def test_failed_and_actionable_rows_are_never_pruned(self):
        pending, _ = self.intake(1)
        retrying, _ = self.intake(2)
        processing, _ = self.intake(3)
        failed, _ = self.intake(4)
        InboundNotification.objects.filter(pk=retrying.pk).update(attempt_count=1, next_attempt_at=NOW)
        InboundNotification.objects.filter(pk=processing.pk).update(
            status=Status.PROCESSING, attempt_count=1, lease_expires_at=NOW
        )
        InboundNotification.objects.filter(pk=failed.pk).update(
            status=Status.FAILED, attempt_count=3, last_error_code='database_busy'
        )
        InboundNotification.objects.update(received_at=OLD - datetime.timedelta(days=30))

        self.assertEqual(prune_raw_notifications(now=NOW), 0)

        self.assertFalse(
            InboundNotification.objects.filter(raw_pruned_at__isnull=False).exists()
        )
        self.assertFalse(InboundNotification.objects.filter(title='').exists())

    def test_pruning_is_idempotent_and_bounded_per_batch(self):
        rows = [self.processed(index)[0] for index in (1, 2, 3)]

        self.assertEqual(prune_raw_notifications(now=NOW, limit=2), 2)
        self.assertEqual(prune_raw_notifications(now=NOW + datetime.timedelta(hours=1)), 1)
        self.assertEqual(prune_raw_notifications(now=NOW + datetime.timedelta(days=1)), 0)

        pruned_at = sorted(
            InboundNotification.objects.filter(pk__in=[row.pk for row in rows]).values_list(
                'raw_pruned_at', flat=True
            )
        )
        self.assertEqual(pruned_at, [NOW, NOW, NOW + datetime.timedelta(hours=1)])

    def test_pruned_rows_still_deduplicate_intake(self):
        row, payload = self.processed()
        prune_raw_notifications(now=NOW)

        same_id = self.post({**payload, 'message': 'Inna treść'})
        same_content = self.post({**payload, 'notification_id': 'another-id'})

        self.assertEqual(same_id.json(), {'status': 'accepted', 'id': row.pk})
        self.assertEqual(same_content.json(), {'status': 'accepted', 'id': row.pk})
        self.assertEqual(InboundNotification.objects.count(), 1)
        self.assertEqual(Entry.objects.count(), 1)

    def test_pruned_rows_keep_output_provenance(self):
        row, _ = self.processed()
        entry = Entry.objects.get()

        prune_raw_notifications(now=NOW)

        output = row.conversion_outputs.get()
        self.assertEqual(output.entry, entry)
        self.assertEqual((output.output_index, output.kind), (0, OutputKind.RULE.value))
        self.assertEqual(entry.conversion_output.notification, row)
        self.assertEqual(convert_notification(row.pk).outcome.value, 'not_claimed')
