import datetime
import uuid
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import RestrictedError
from django.test import TestCase

from entries.classification.types import EntryType, SchoolItemKind
from entries.models import Entry
from entries import services
from entries.services import save_confirmed_entry

from .test_classification_service import FamilyFixtureMixin

SENTINEL_CONTENT = 'SENTINEL-sprawdzian-z-biologii'
EVENT_DATE = datetime.date(2026, 9, 21)


class EntryModelTests(FamilyFixtureMixin, TestCase):
    def test_calendar_event_requires_date_at_database_level(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Entry.objects.create(
                family=self.family,
                entry_type=EntryType.CALENDAR_EVENT.value,
                content='Wycieczka',
            )

    def test_note_and_todo_without_date_are_accepted(self):
        for entry_type in (EntryType.NOTE, EntryType.TODO):
            with self.subTest(entry_type=entry_type):
                entry = Entry.objects.create(
                    family=self.family,
                    entry_type=entry_type.value,
                    content='Kupić zeszyt',
                )
                self.assertIsNone(entry.date)

    def test_eduvulcan_entry_saves_without_key_or_creator(self):
        entry = Entry.objects.create(
            family=self.family,
            entry_type=EntryType.NOTE.value,
            content='Szczęśliwy numerek 7',
            source=Entry.Source.EDUVULCAN,
        )

        self.assertIsNone(entry.submission_key)
        self.assertIsNone(entry.created_by)
        self.assertEqual(entry.source, 'eduvulcan')

    def test_string_and_repr_never_contain_content(self):
        entry = Entry.objects.create(
            family=self.family,
            entry_type=EntryType.NOTE.value,
            content=SENTINEL_CONTENT,
        )

        self.assertNotIn(SENTINEL_CONTENT, str(entry))
        self.assertNotIn(SENTINEL_CONTENT, repr(entry))

    def test_deleting_family_cascades_entries(self):
        Entry.objects.create(
            family=self.family,
            entry_type=EntryType.NOTE.value,
            content='Notatka',
            assigned_member=self.child,
        )

        self.family.delete()

        self.assertFalse(Entry.objects.exists())

    def test_deleting_assigned_member_or_user_is_restricted(self):
        entry = Entry.objects.create(
            family=self.family,
            entry_type=EntryType.NOTE.value,
            content='Notatka',
            assigned_member=self.child,
        )

        with self.assertRaises(RestrictedError):
            self.child.delete()
        with self.assertRaises(RestrictedError):
            self.child.user.delete()

        entry.refresh_from_db()
        self.assertEqual(entry.assigned_member, self.child)


class SaveConfirmedEntryTests(FamilyFixtureMixin, TestCase):
    def save(self, user=None, **overrides):
        values = {
            'entry_type': EntryType.CALENDAR_EVENT.value,
            'content': 'Sprawdzian z biologii o skórze',
            'date': EVENT_DATE,
            'time': None,
            'assigned_member': self.child,
            'school_item': SchoolItemKind.TEST.value,
            'submission_key': uuid.uuid4(),
        }
        values.update(overrides)
        return save_confirmed_entry(user or self.parent.user, **values)

    def test_active_parent_creates_manual_entry_for_family(self):
        entry, created = self.save()

        self.assertTrue(created)
        self.assertEqual(entry.family, self.family)
        self.assertEqual(entry.created_by, self.parent)
        self.assertEqual(entry.source, Entry.Source.MANUAL)
        self.assertEqual(entry.assigned_member, self.child)
        self.assertEqual(entry.school_item, 'test')
        self.assertEqual(Entry.objects.count(), 1)

    def test_unauthorized_users_are_denied_and_nothing_is_written(self):
        unconfigured = get_user_model().objects.create_user(username='unconfigured')

        def inactive_parent():
            self.parent.is_active = False
            self.parent.save(update_fields=('is_active',))
            return self.parent.user

        def inactive_family():
            self.family.is_active = False
            self.family.save(update_fields=('is_active',))
            return self.parent.user

        cases = {
            'anonymous': AnonymousUser,
            'no membership': lambda: unconfigured,
            'child': lambda: self.child.user,
            'inactive parent': inactive_parent,
            'inactive family': inactive_family,
        }
        for name, get_user in cases.items():
            with self.subTest(name):
                with self.assertRaises(PermissionDenied):
                    self.save(user=get_user())
        self.assertFalse(Entry.objects.exists())

    def test_member_outside_family_or_inactive_is_rejected(self):
        for member in (self.other_family_child, self.inactive_child):
            with self.subTest(member=member.display_name):
                with self.assertRaises(ValidationError):
                    self.save(assigned_member=member)
        self.assertFalse(Entry.objects.exists())

    def test_required_fields_are_enforced(self):
        with self.assertRaises(ValidationError):
            self.save(date=None, school_item='')
        with self.assertRaises(ValidationError):
            self.save(assigned_member=None)
        self.assertFalse(Entry.objects.exists())

    def test_repeat_key_returns_existing_entry_after_member_deactivated(self):
        key = uuid.uuid4()
        first, _ = self.save(submission_key=key)
        self.child.is_active = False
        self.child.save(update_fields=('is_active',))

        second, created = self.save(submission_key=key)

        self.assertFalse(created)
        self.assertEqual(second.pk, first.pk)
        self.assertEqual(Entry.objects.count(), 1)

    def test_same_key_twice_returns_original_unchanged_entry(self):
        key = uuid.uuid4()
        first, first_created = self.save(submission_key=key)

        second, second_created = self.save(
            submission_key=key,
            content='Zmieniona treść',
            date=EVENT_DATE + datetime.timedelta(days=1),
        )

        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(second.pk, first.pk)
        second.refresh_from_db()
        self.assertEqual(second.date, EVENT_DATE)
        self.assertEqual(second.content, 'Sprawdzian z biologii o skórze')
        self.assertEqual(Entry.objects.count(), 1)

    def test_key_owned_by_another_family_is_rejected(self):
        key = uuid.uuid4()
        foreign = Entry.objects.create(
            family=self.other_family,
            entry_type=EntryType.NOTE.value,
            content='Cudza notatka',
            submission_key=key,
        )

        with self.assertRaises(ValidationError):
            self.save(submission_key=key)

        self.assertEqual(Entry.objects.count(), 1)
        self.assertEqual(Entry.objects.get().pk, foreign.pk)

    def test_race_on_create_returns_winning_row(self):
        key = uuid.uuid4()
        winner, _ = self.save(submission_key=key)
        real_lookup = services._existing_for_key
        calls = []

        def miss_first_lookup(membership, submission_key):
            calls.append(submission_key)
            if len(calls) == 1:
                return None  # a concurrent request has not committed yet
            return real_lookup(membership, submission_key)

        with mock.patch.object(services, '_existing_for_key', side_effect=miss_first_lookup):
            entry, created = self.save(submission_key=key)

        self.assertFalse(created)
        self.assertEqual(entry.pk, winner.pk)
        self.assertEqual(len(calls), 2)
        self.assertEqual(Entry.objects.count(), 1)
