"""Conversion lifecycle and output-provenance schema (S-05 Phase 1).

Database constraints pin the lease, retry, and pruning states of an inbound
notification and the one-to-many, tombstone-preserving output links.
"""

import datetime

from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from entries.api_views import content_hash
from entries.classification.types import EntryType, SchoolItemKind
from entries.eduvulcan.types import OutputKind
from entries.models import Entry, InboundNotification, NotificationConversionOutput
from entries.services import delete_family_entry

from .test_classification_service import FamilyFixtureMixin

CAPTURED_AT = datetime.datetime(2026, 9, 23, 8, 30, tzinfo=datetime.timezone.utc)
NOW = datetime.datetime(2026, 9, 23, 9, 0, tzinfo=datetime.timezone.utc)
Status = InboundNotification.Status


def make_notification(family, index=1, **overrides):
    title = overrides.pop('title', 'Sprawdzian')
    message = overrides.pop('message', f'2 października, Biologia (biologia), Łucja {index}')
    values = dict(
        family=family,
        notification_id=f'0|pl.example.eduvulcan|{index}|anon',
        title=title,
        message=message,
        captured_at=CAPTURED_AT,
        captured_date=CAPTURED_AT.date(),
        content_hash=content_hash(title, message),
        payload={'title': title, 'message': message},
    )
    values.update(overrides)
    return InboundNotification.objects.create(**values)


class InboundLifecycleFieldTests(FamilyFixtureMixin, TestCase):
    def assert_rejected(self, **values):
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_notification(self.family, **values)

    def test_new_row_starts_with_empty_lifecycle_metadata(self):
        row = make_notification(self.family)

        self.assertEqual(row.status, Status.PENDING)
        self.assertEqual(row.attempt_count, 0)
        self.assertIsNone(row.next_attempt_at)
        self.assertIsNone(row.lease_expires_at)
        self.assertEqual(row.last_error_code, '')
        self.assertIsNone(row.raw_pruned_at)

    def test_processing_requires_a_lease(self):
        self.assert_rejected(status=Status.PROCESSING)

        row = make_notification(self.family, status=Status.PROCESSING, lease_expires_at=NOW)
        self.assertEqual(row.lease_expires_at, NOW)

    def test_lease_is_held_only_while_processing(self):
        for status in (Status.PENDING, Status.PROCESSED, Status.FAILED):
            with self.subTest(status=status):
                self.assert_rejected(status=status, lease_expires_at=NOW)

    def test_retry_is_scheduled_only_while_pending(self):
        row = make_notification(self.family, next_attempt_at=NOW, attempt_count=1)
        self.assertEqual(row.next_attempt_at, NOW)

        for status, extra in (
            (Status.PROCESSING, {'lease_expires_at': NOW}),
            (Status.PROCESSED, {}),
            (Status.FAILED, {}),
        ):
            with self.subTest(status=status):
                self.assert_rejected(index=2, status=status, next_attempt_at=NOW, **extra)

    def test_failed_row_keeps_only_a_safe_error_code(self):
        row = make_notification(
            self.family, status=Status.FAILED, attempt_count=3, last_error_code='database_error'
        )

        self.assertEqual(row.last_error_code, 'database_error')
        self.assertEqual(row.attempt_count, 3)
        self.assertEqual(str(row), f'notification #{row.pk} (failed)')

    def test_attempt_count_cannot_be_negative(self):
        self.assert_rejected(attempt_count=-1)

    def test_only_processed_rows_with_scrubbed_text_can_be_pruned(self):
        for status, extra in (
            (Status.PENDING, {}),
            (Status.PROCESSING, {'lease_expires_at': NOW}),
            (Status.FAILED, {}),
        ):
            with self.subTest(status=status):
                self.assert_rejected(
                    status=status, raw_pruned_at=NOW, title='', message='', payload={}, **extra
                )
        with self.subTest('processed with raw text'):
            self.assert_rejected(status=Status.PROCESSED, raw_pruned_at=NOW)

        row = make_notification(
            self.family,
            status=Status.PROCESSED,
            processed_at=NOW,
            raw_pruned_at=NOW,
            title='',
            message='',
            payload={},
        )
        self.assertEqual(row.raw_pruned_at, NOW)

    def test_pruned_row_keeps_deduplication_identifiers(self):
        row = make_notification(self.family, status=Status.PROCESSED, processed_at=NOW)
        original_hash = row.content_hash

        InboundNotification.objects.filter(pk=row.pk).update(
            title='', message='', payload={}, raw_pruned_at=NOW
        )

        row.refresh_from_db()
        self.assertEqual(row.content_hash, original_hash)
        self.assertEqual(row.notification_id, '0|pl.example.eduvulcan|1|anon')
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_notification(self.family, index=1, message='inna treść')


class ConversionOutputTests(FamilyFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.notification = make_notification(self.family)

    def make_entry(self, **overrides):
        values = dict(
            family=self.family,
            entry_type=EntryType.CALENDAR_EVENT.value,
            content='Sprawdzian: Biologia',
            date=datetime.date(2026, 10, 2),
            assigned_member=self.child,
            school_item=SchoolItemKind.TEST.value,
            source=Entry.Source.EDUVULCAN,
        )
        values.update(overrides)
        return Entry.objects.create(**values)

    def link(self, output_index, entry=None, kind=OutputKind.RULE, notification=None):
        return NotificationConversionOutput.objects.create(
            notification=notification or self.notification,
            output_index=output_index,
            kind=kind.value if isinstance(kind, OutputKind) else kind,
            entry=entry,
        )

    def test_one_notification_links_ordered_outputs(self):
        entries = [self.make_entry() for _ in range(3)]
        for index, entry in reversed(list(enumerate(entries))):
            self.link(index, entry)

        outputs = list(self.notification.conversion_outputs.all())

        self.assertEqual([output.output_index for output in outputs], [0, 1, 2])
        self.assertEqual([output.entry for output in outputs], entries)
        self.assertEqual(entries[1].conversion_output.output_index, 1)

    def test_output_index_is_unique_per_notification(self):
        self.link(0, self.make_entry())

        with self.assertRaises(IntegrityError), transaction.atomic():
            self.link(0, self.make_entry())

        other = make_notification(self.family, index=2)
        self.assertEqual(self.link(0, self.make_entry(), notification=other).output_index, 0)

    def test_an_entry_has_at_most_one_output_link(self):
        entry = self.make_entry()
        self.link(0, entry)
        other = make_notification(self.family, index=2)

        with self.assertRaises(IntegrityError), transaction.atomic():
            self.link(1, entry)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.link(0, entry, notification=other)

    def test_several_tombstones_may_have_no_entry(self):
        self.link(0)
        self.link(1)

        self.assertEqual(
            self.notification.conversion_outputs.filter(entry__isnull=True).count(), 2
        )

    def test_output_index_cannot_be_negative(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.link(-1, self.make_entry())

    def test_output_kind_must_be_known(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.link(0, self.make_entry(), kind='invented')

    def test_every_output_kind_is_storable(self):
        for index, kind in enumerate(OutputKind):
            with self.subTest(kind=kind.value):
                self.assertEqual(self.link(index, kind=kind).kind, kind.value)

    def test_parent_deletion_keeps_the_tombstone(self):
        entry = self.make_entry()
        output = self.link(0, entry)

        delete_family_entry(self.parent.user, entry.pk)

        output.refresh_from_db()
        self.assertIsNone(output.entry)
        self.assertEqual(output.output_index, 0)
        self.assertEqual(output.kind, OutputKind.RULE.value)
        self.assertFalse(Entry.objects.filter(pk=entry.pk).exists())
        # The completed index still blocks a second output at the same slot.
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.link(0, self.make_entry())

    def test_deleting_notification_removes_links_but_keeps_entries(self):
        entry = self.make_entry()
        self.link(0, entry)

        self.notification.delete()

        self.assertFalse(NotificationConversionOutput.objects.exists())
        self.assertTrue(Entry.objects.filter(pk=entry.pk).exists())

    def test_string_form_contains_no_notification_text(self):
        output = self.link(0, self.make_entry())

        text = str(output) + repr(output)
        for sensitive in ('Sprawdzian', 'Biologia', 'Łucja', self.child.display_name):
            self.assertNotIn(sensitive, text)


class ConversionMigrationTests(TransactionTestCase):
    """The additive migration keeps stored rows pending with empty metadata."""

    before = [('entries', '0002_inboundnotification')]
    after = [('entries', '0003_notification_conversion')]

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_existing_pending_row_survives_with_defaults(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.before)
        old_apps = executor.loader.project_state(self.before).apps
        Family = old_apps.get_model('family_access', 'Family')
        OldNotification = old_apps.get_model('entries', 'InboundNotification')
        family = Family.objects.create(name='Rodzina Testowa')
        row = OldNotification.objects.create(
            family=family,
            notification_id='anon-1',
            title='Ocena',
            message='Nowa ocena: 5, Plastyka, Łucja',
            captured_at=timezone.now(),
            captured_date=datetime.date(2026, 9, 23),
            content_hash='0' * 64,
            payload={},
        )

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(self.after)
        new_apps = executor.loader.project_state(self.after).apps
        NewNotification = new_apps.get_model('entries', 'InboundNotification')
        migrated = NewNotification.objects.get(pk=row.pk)

        self.assertEqual(migrated.status, 'pending')
        self.assertEqual(migrated.attempt_count, 0)
        self.assertIsNone(migrated.next_attempt_at)
        self.assertIsNone(migrated.lease_expires_at)
        self.assertEqual(migrated.last_error_code, '')
        self.assertIsNone(migrated.raw_pruned_at)
        self.assertFalse(
            new_apps.get_model('entries', 'NotificationConversionOutput').objects.exists()
        )
