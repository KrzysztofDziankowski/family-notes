"""Forward-only mandatory-date migration preservation and storage contract."""

import datetime
import unittest
from uuid import uuid4

from django.db import IntegrityError, transaction

from .migration_database import migration_database, migrate


class EntryDateMigrationTests(unittest.TestCase):
    before = [('entries', '0007_entry_school_subject')]
    after = [('entries', '0009_entry_date_required')]

    def test_backfill_types_dates_and_every_other_field_and_link(self):
        with migration_database() as database:
            alias = database.alias
            apps = migrate(database, self.before)
            Entry = apps.get_model('entries', 'Entry')
            Family = apps.get_model('family_access', 'Family')
            Member = apps.get_model('family_access', 'FamilyMember')
            User = apps.get_model('auth', 'User')
            Notification = apps.get_model('entries', 'InboundNotification')
            Output = apps.get_model('entries', 'NotificationConversionOutput')
            families = [Family.objects.using(alias).create(name=f'Synthetic {i}') for i in range(2)]
            members = [Member.objects.using(alias).create(
                family=family, user=User.objects.using(alias).create(username=f'synthetic{i}'),
                role='parent', display_name=f'Synthetic {i}',
            ) for i, family in enumerate(families)]
            captured = datetime.datetime(2026, 7, 1, 23, 30, tzinfo=datetime.timezone.utc)
            winter = datetime.datetime(2026, 1, 1, 23, 30, tzinfo=datetime.timezone.utc)
            expected_types = {
                'homework': 'calendar_event', 'class_test': 'calendar_event',
                'test': 'calendar_event', 'quiz': 'calendar_event',
                'substitution': 'calendar_event', 'room_change': 'calendar_event',
                'lucky_number': 'note', 'grade': 'note', 'late_arrival': 'note',
            }
            expected = {}
            for index, kind in enumerate([*expected_types, '', 'unknown']):
                for source in ('manual', 'eduvulcan'):
                    for original_type in ('note', 'todo', 'calendar_event'):
                        stamp = captured if index % 2 else winter
                        existing_date = datetime.date(2025, 3, 4)
                        date = existing_date if original_type == 'calendar_event' or source == 'manual' else None
                        member = members[index % 2]
                        row = Entry.objects.using(alias).create(
                            family=member.family, assigned_member=member, created_by=member,
                            entry_type=original_type, school_item=kind,
                            school_subject='Synthetic subject', source=source,
                            content=f'Synthetic {index}', date=date,
                            time=datetime.time(10, 15), submission_key=uuid4(),
                        )
                        Entry.objects.using(alias).filter(pk=row.pk).update(created_at=stamp, updated_at=stamp)
                        values = Entry.objects.using(alias).values().get(pk=row.pk)
                        expected[row.pk] = dict(values, date=date or datetime.date(2026, 7 if index % 2 else 1, 2), entry_type=expected_types.get(kind, original_type))
            notification = Notification.objects.using(alias).create(
                family=families[0], notification_id='synthetic', title='Synthetic',
                message='Synthetic', captured_at=captured, captured_date=captured.date(),
                content_hash='a' * 64, payload={'synthetic': True},
            )
            Output.objects.using(alias).create(notification=notification, entry_id=next(iter(expected)), output_index=0, kind='rule')
            Output.objects.using(alias).create(notification=notification, entry=None, output_index=1, kind='general_note')
            original_links = list(Output.objects.using(alias).order_by('pk').values())
            original_notifications = list(Notification.objects.using(alias).values())
            final_apps = migrate(database, self.after)
            FinalEntry = final_apps.get_model('entries', 'Entry')
            self.assertEqual({row['id']: row for row in FinalEntry.objects.using(alias).values()}, expected)
            self.assertEqual(list(final_apps.get_model('entries', 'NotificationConversionOutput').objects.using(alias).order_by('pk').values()), original_links)
            self.assertEqual(list(final_apps.get_model('entries', 'InboundNotification').objects.using(alias).values()), original_notifications)
            field = FinalEntry._meta.get_field('date')
            self.assertFalse(field.null)
            self.assertFalse(field.blank)
            self.assertFalse(field.has_default())
            self.assertFalse(field.has_db_default())
            for entry_type in ('note', 'todo', 'calendar_event'):
                with self.subTest(entry_type=entry_type):
                    with self.assertRaises(IntegrityError), transaction.atomic(using=alias):
                        FinalEntry.objects.using(alias).create(family_id=families[0].pk, entry_type=entry_type, content='Synthetic rejected', date=None)

    def test_data_migration_is_explicitly_irreversible(self):
        from importlib import import_module
        operation = import_module('entries.migrations.0008_backfill_entry_dates').Migration.operations[0]
        self.assertFalse(operation.reversible)
