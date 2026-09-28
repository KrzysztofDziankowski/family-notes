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
from entries.services import (
    create_family_entry,
    delete_family_entry,
    get_parent_family_entry,
    parent_family_entries,
    save_confirmed_entry,
    update_family_entry,
)

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


class ManagementFixtureMixin(FamilyFixtureMixin):
    """Own-family manual and EduVulcan entries plus a foreign-family entry."""

    def setUp(self):
        super().setUp()
        self.manual_key = uuid.uuid4()
        self.manual = Entry.objects.create(
            family=self.family,
            entry_type=EntryType.CALENDAR_EVENT.value,
            content='Sprawdzian z biologii',
            date=EVENT_DATE,
            assigned_member=self.child,
            school_item=SchoolItemKind.TEST.value,
            source=Entry.Source.MANUAL,
            created_by=self.parent,
            submission_key=self.manual_key,
        )
        self.eduvulcan = Entry.objects.create(
            family=self.family,
            entry_type=EntryType.NOTE.value,
            content='Zastępstwo z fizyki',
            date=EVENT_DATE,
            school_item=SchoolItemKind.SUBSTITUTION.value,
            source=Entry.Source.EDUVULCAN,
        )
        self.foreign = Entry.objects.create(
            family=self.other_family,
            entry_type=EntryType.NOTE.value,
            content=SENTINEL_CONTENT,
            created_by=self.other_family_parent,
        )

    def unauthorized_users(self):
        """Every caller who must be denied; state changes are applied lazily."""
        unconfigured = get_user_model().objects.create_user(username='unconfigured')

        def inactive_parent():
            self.parent.is_active = False
            self.parent.save(update_fields=('is_active',))
            return self.parent.user

        def inactive_family():
            self.family.is_active = False
            self.family.save(update_fields=('is_active',))
            return self.parent.user

        return {
            'anonymous': AnonymousUser,
            'no membership': lambda: unconfigured,
            'child': lambda: self.child.user,
            'inactive member': lambda: self.inactive_child.user,
            'inactive parent': inactive_parent,
            'inactive family': inactive_family,
        }

    def snapshot(self):
        return sorted(
            Entry.objects.values_list(
                'pk', 'family_id', 'entry_type', 'content', 'date', 'time',
                'assigned_member_id', 'school_item', 'source', 'created_by_id',
                'submission_key', 'created_at', 'updated_at',
            )
        )


class ParentFamilyEntriesTests(ManagementFixtureMixin, TestCase):
    def test_parent_sees_only_own_family_entries(self):
        entries = parent_family_entries(self.parent.user)

        self.assertCountEqual(entries, [self.manual, self.eduvulcan])

    def test_lookup_resolves_own_entry_and_hides_foreign_and_missing(self):
        self.assertEqual(get_parent_family_entry(self.parent.user, self.manual.pk), self.manual)
        for entry_id in (self.foreign.pk, 999999):
            with self.subTest(entry_id=entry_id):
                with self.assertRaises(Entry.DoesNotExist):
                    get_parent_family_entry(self.parent.user, entry_id)

    def test_unauthorized_users_are_denied(self):
        for name, get_user in self.unauthorized_users().items():
            with self.subTest(name):
                user = get_user()
                with self.assertRaises(PermissionDenied):
                    parent_family_entries(user)
                with self.assertRaises(PermissionDenied):
                    get_parent_family_entry(user, self.manual.pk)


class CreateFamilyEntryTests(ManagementFixtureMixin, TestCase):
    def create(self, user=None, **overrides):
        values = {
            'entry_type': EntryType.TODO.value,
            'content': 'Kupić zeszyt w kratkę',
            'date': None,
            'time': None,
            'assigned_member': self.other_child,
            'school_item': '',
            'submission_key': uuid.uuid4(),
        }
        values.update(overrides)
        return create_family_entry(user or self.parent.user, **values)

    def test_creates_manual_entry_with_provenance_from_membership(self):
        key = uuid.uuid4()

        entry, created = self.create(submission_key=key)

        self.assertTrue(created)
        entry.refresh_from_db()
        self.assertEqual(entry.family, self.family)
        self.assertEqual(entry.source, Entry.Source.MANUAL)
        self.assertEqual(entry.created_by, self.parent)
        self.assertEqual(entry.submission_key, key)
        self.assertEqual(entry.assigned_member, self.other_child)
        self.assertEqual(entry.entry_type, 'todo')

    def test_same_submission_key_creates_exactly_one_entry(self):
        key = uuid.uuid4()
        before = Entry.objects.count()

        first, first_created = self.create(submission_key=key)
        second, second_created = self.create(submission_key=key, content='Inna treść')

        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Entry.objects.count(), before + 1)
        self.assertEqual(Entry.objects.filter(submission_key=key).count(), 1)
        second.refresh_from_db()
        self.assertEqual(second.content, 'Kupić zeszyt w kratkę')

    def test_unauthorized_users_are_denied_and_nothing_is_written(self):
        before = self.snapshot()
        for name, get_user in self.unauthorized_users().items():
            with self.subTest(name):
                with self.assertRaises(PermissionDenied):
                    self.create(user=get_user())
        self.assertEqual(self.snapshot(), before)

    def test_foreign_or_inactive_assignee_is_rejected_without_write(self):
        before = self.snapshot()
        for member in (self.other_family_child, self.inactive_child):
            with self.subTest(member=member.display_name):
                with self.assertRaises(ValidationError):
                    self.create(assigned_member=member)
        self.assertEqual(self.snapshot(), before)

    def test_invalid_values_are_rejected_without_write(self):
        before = self.snapshot()
        cases = {
            'blank content': {'content': '   '},
            'too long content': {'content': 'x' * 2001},
            'undated event': {'entry_type': EntryType.CALENDAR_EVENT.value},
            'school item type mismatch': {'school_item': SchoolItemKind.TEST.value},
            'school item missing member': {
                'entry_type': EntryType.CALENDAR_EVENT.value,
                'date': EVENT_DATE,
                'school_item': SchoolItemKind.TEST.value,
                'assigned_member': None,
            },
        }
        for name, overrides in cases.items():
            with self.subTest(name):
                with self.assertRaises(ValidationError):
                    self.create(**overrides)
        self.assertEqual(self.snapshot(), before)

    def test_key_owned_by_another_family_is_rejected(self):
        foreign_key = uuid.uuid4()
        self.foreign.submission_key = foreign_key
        self.foreign.save(update_fields=('submission_key',))
        before = self.snapshot()

        with self.assertRaises(ValidationError):
            self.create(submission_key=foreign_key)

        self.assertEqual(self.snapshot(), before)


class UpdateFamilyEntryTests(ManagementFixtureMixin, TestCase):
    def update(self, entry, user=None, **overrides):
        values = {
            'entry_type': EntryType.CALENDAR_EVENT.value,
            'content': 'Kartkówka z chemii',
            'date': EVENT_DATE + datetime.timedelta(days=2),
            'time': datetime.time(10, 0),
            'assigned_member': self.other_child,
            'school_item': SchoolItemKind.QUIZ.value,
        }
        values.update(overrides)
        return update_family_entry(user or self.parent.user, entry.pk, **values)

    def provenance(self, entry):
        entry.refresh_from_db()
        return (
            entry.family_id, entry.source, entry.created_by_id,
            entry.submission_key, entry.created_at,
        )

    def test_updates_editable_fields_and_preserves_provenance(self):
        for entry in (self.manual, self.eduvulcan):
            with self.subTest(source=entry.source):
                provenance = self.provenance(entry)
                previous_updated_at = entry.updated_at

                updated = self.update(entry)

                self.assertEqual(self.provenance(updated), provenance)
                self.assertEqual(updated.entry_type, 'calendar_event')
                self.assertEqual(updated.content, 'Kartkówka z chemii')
                self.assertEqual(updated.date, EVENT_DATE + datetime.timedelta(days=2))
                self.assertEqual(updated.time, datetime.time(10, 0))
                self.assertEqual(updated.assigned_member, self.other_child)
                self.assertEqual(updated.school_item, 'quiz')
                self.assertGreaterEqual(updated.updated_at, previous_updated_at)

        self.eduvulcan.refresh_from_db()
        self.assertEqual(self.eduvulcan.source, Entry.Source.EDUVULCAN)
        self.assertIsNone(self.eduvulcan.created_by)
        self.assertIsNone(self.eduvulcan.submission_key)
        self.manual.refresh_from_db()
        self.assertEqual(self.manual.created_by, self.parent)
        self.assertEqual(self.manual.submission_key, self.manual_key)

    def test_school_item_can_be_cleared(self):
        updated = self.update(
            self.eduvulcan,
            entry_type=EntryType.NOTE.value,
            date=None,
            time=None,
            assigned_member=None,
            school_item='',
        )

        updated.refresh_from_db()
        self.assertEqual(updated.school_item, '')
        self.assertIsNone(updated.date)

    def test_foreign_and_missing_entries_are_not_found_and_unchanged(self):
        before = self.snapshot()
        for entry_id in (self.foreign.pk, 999999):
            with self.subTest(entry_id=entry_id):
                with self.assertRaises(Entry.DoesNotExist):
                    update_family_entry(
                        self.parent.user,
                        entry_id,
                        entry_type=EntryType.NOTE.value,
                        content='Przejęta',
                        date=None,
                        time=None,
                        assigned_member=None,
                        school_item='',
                    )
        self.assertEqual(self.snapshot(), before)

    def test_unauthorized_users_are_denied_and_nothing_changes(self):
        before = self.snapshot()
        for name, get_user in self.unauthorized_users().items():
            with self.subTest(name):
                with self.assertRaises(PermissionDenied):
                    self.update(self.manual, user=get_user())
        self.assertEqual(self.snapshot(), before)

    def test_foreign_or_inactive_assignee_is_rejected_without_mutation(self):
        before = self.snapshot()
        for member in (self.other_family_child, self.inactive_child):
            with self.subTest(member=member.display_name):
                with self.assertRaises(ValidationError):
                    self.update(self.manual, assigned_member=member)
        self.assertEqual(self.snapshot(), before)

    def test_invalid_values_are_rejected_without_mutation(self):
        before = self.snapshot()
        cases = {
            'blank content': {'content': ''},
            'too long content': {'content': 'x' * 2001},
            'undated event': {'date': None},
            'school item type mismatch': {'entry_type': EntryType.NOTE.value},
            'school item missing member': {'assigned_member': None},
        }
        for name, overrides in cases.items():
            with self.subTest(name):
                with self.assertRaises(ValidationError):
                    self.update(self.manual, **overrides)
        self.assertEqual(self.snapshot(), before)


class DeleteFamilyEntryTests(ManagementFixtureMixin, TestCase):
    def test_deletes_only_the_target_row(self):
        for entry in (self.manual, self.eduvulcan):
            with self.subTest(source=entry.source):
                delete_family_entry(self.parent.user, entry.pk)
                self.assertFalse(Entry.objects.filter(pk=entry.pk).exists())

        self.assertEqual(list(Entry.objects.values_list('pk', flat=True)), [self.foreign.pk])

    def test_foreign_and_missing_entries_are_not_found_and_kept(self):
        before = self.snapshot()
        for entry_id in (self.foreign.pk, 999999):
            with self.subTest(entry_id=entry_id):
                with self.assertRaises(Entry.DoesNotExist):
                    delete_family_entry(self.parent.user, entry_id)
        self.assertEqual(self.snapshot(), before)

    def test_unauthorized_users_are_denied_and_nothing_is_deleted(self):
        before = self.snapshot()
        for name, get_user in self.unauthorized_users().items():
            with self.subTest(name):
                with self.assertRaises(PermissionDenied):
                    delete_family_entry(get_user(), self.manual.pk)
        self.assertEqual(self.snapshot(), before)
