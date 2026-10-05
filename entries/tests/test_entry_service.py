import datetime
import uuid
from unittest import mock

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import RestrictedError
from django.test import TestCase

from entries.classification.types import EntryType, SchoolItemKind
from entries.models import SCHOOL_SUBJECT_MAX_LENGTH, Entry
from entries import services
from entries.services import (
    create_automated_entry,
    create_family_entry,
    delete_family_entry,
    get_parent_family_entry,
    parent_family_entries,
    save_confirmed_entries,
    save_confirmed_entry,
    update_family_entry,
)

from .test_classification_service import FamilyFixtureMixin, TwoParentFixtureMixin

SENTINEL_CONTENT = 'SENTINEL-sprawdzian-z-biologii'
EVENT_DATE = datetime.date(2026, 9, 21)
SCHOOL_EVENT_KINDS = (
    SchoolItemKind.HOMEWORK,
    SchoolItemKind.CLASS_TEST,
    SchoolItemKind.TEST,
    SchoolItemKind.QUIZ,
)
TOO_LONG_SUBJECT = 'x' * (SCHOOL_SUBJECT_MAX_LENGTH + 1)


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
            self.child.delete()

        entry.refresh_from_db()
        self.assertEqual(entry.assigned_member, self.child)


class SaveConfirmedEntryTests(FamilyFixtureMixin, TestCase):
    def save(self, membership='parent', **overrides):
        values = {
            'entry_type': EntryType.CALENDAR_EVENT.value,
            'content': 'Sprawdzian z biologii o skórze',
            'date': EVENT_DATE,
            'time': None,
            'assigned_member': self.child,
            'school_item': SchoolItemKind.TEST.value,
            'school_subject': 'Biologia',
            'submission_key': uuid.uuid4(),
        }
        values.update(overrides)
        return save_confirmed_entry(
            self.parent if membership == 'parent' else membership, **values
        )

    def test_active_parent_creates_manual_entry_for_family(self):
        entry, created = self.save()

        self.assertTrue(created)
        self.assertEqual(entry.family, self.family)
        self.assertEqual(entry.created_by, self.parent)
        self.assertEqual(entry.source, Entry.Source.MANUAL)
        self.assertEqual(entry.assigned_member, self.child)
        self.assertEqual(entry.school_item, 'test')
        self.assertEqual(entry.school_subject, 'Biologia')
        self.assertEqual(Entry.objects.count(), 1)

    def test_school_event_kinds_require_a_subject(self):
        for kind in SCHOOL_EVENT_KINDS:
            for blank in ('', '   '):
                with self.subTest(kind=kind.value, subject=blank):
                    with self.assertRaisesMessage(
                        ValidationError, 'Ten wpis szkolny wymaga przedmiotu.'
                    ):
                        self.save(school_item=kind.value, school_subject=blank)
        self.assertFalse(Entry.objects.exists())

    def test_subject_is_stripped_and_stored_for_each_school_event_kind(self):
        for kind in SCHOOL_EVENT_KINDS:
            with self.subTest(kind=kind.value):
                entry, _ = self.save(school_item=kind.value, school_subject='  Matematyka ')
                entry.refresh_from_db()
                self.assertEqual(entry.school_subject, 'Matematyka')

    def test_subject_is_optional_for_other_entries(self):
        cases = {
            'grade note': {
                'entry_type': EntryType.NOTE.value,
                'school_item': SchoolItemKind.GRADE.value,
            },
            'substitution': {
                'entry_type': EntryType.NOTE.value,
                'school_item': SchoolItemKind.SUBSTITUTION.value,
            },
            'plain event': {'school_item': ''},
            'todo': {'entry_type': EntryType.TODO.value, 'school_item': ''},
        }
        for name, overrides in cases.items():
            with self.subTest(name):
                entry, created = self.save(school_subject='', **overrides)
                self.assertTrue(created)
                self.assertEqual(entry.school_subject, '')

    def test_too_long_subject_is_rejected(self):
        for school_item in (SchoolItemKind.TEST.value, ''):
            with self.subTest(school_item=school_item):
                with self.assertRaisesMessage(ValidationError, 'Przedmiot jest za długi.'):
                    self.save(school_item=school_item, school_subject=TOO_LONG_SUBJECT)
        self.assertFalse(Entry.objects.exists())

    def test_unauthorized_users_are_denied_and_nothing_is_written(self):
        def inactive_parent():
            self.parent.is_active = False
            self.parent.save(update_fields=('is_active',))
            return self.parent

        def inactive_family():
            self.family.is_active = False
            self.family.save(update_fields=('is_active',))
            return self.parent

        cases = {
            'no family context': lambda: None,
            'child': lambda: self.child,
            'inactive parent': inactive_parent,
            'inactive family': inactive_family,
        }
        for name, get_membership in cases.items():
            with self.subTest(name):
                with self.assertRaises(PermissionDenied):
                    self.save(membership=get_membership())
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


class SaveConfirmedEntriesTests(FamilyFixtureMixin, TestCase):
    def item(self, **overrides):
        values = dict(
            entry_type=EntryType.CALENDAR_EVENT.value,
            content='Spotkanie z wychowawczynią',
            date=EVENT_DATE,
            time=datetime.time(18, 0),
            assigned_member=None,
            school_item='',
            school_subject='',
            submission_key=uuid.uuid4(),
        )
        values.update(overrides)
        return values

    def test_saves_every_item_in_order(self):
        items = [self.item(date=EVENT_DATE + datetime.timedelta(days=day)) for day in range(3)]

        entries = save_confirmed_entries(self.parent, items)

        self.assertEqual([entry.date for entry in entries], [item['date'] for item in items])
        self.assertEqual(Entry.objects.count(), 3)
        self.assertEqual({entry.created_by for entry in entries}, {self.parent})

    def test_school_event_keeps_its_subject(self):
        (entry,) = save_confirmed_entries(
            self.parent,
            [self.item(
                school_item=SchoolItemKind.TEST.value,
                school_subject='biologia',
                assigned_member=self.child,
            )],
        )

        self.assertEqual(entry.school_subject, 'biologia')

    def test_a_rejected_item_rolls_back_the_earlier_ones(self):
        cases = {
            'foreign key': lambda: self.item(submission_key=self._foreign_key()),
            'foreign member': lambda: self.item(assigned_member=self.other_family_child),
            'school event without subject': lambda: self.item(
                school_item=SchoolItemKind.TEST.value, assigned_member=self.child
            ),
        }
        for name, bad in cases.items():
            with self.subTest(name):
                with self.assertRaises(ValidationError):
                    save_confirmed_entries(self.parent, [self.item(), bad()])

                self.assertFalse(Entry.objects.filter(family=self.family).exists())

    def _foreign_key(self):
        key = uuid.uuid4()
        Entry.objects.create(
            family=self.other_family, entry_type=EntryType.NOTE.value, content='x',
            submission_key=key,
        )
        return key

    def test_replay_returns_the_saved_entries_and_creates_none(self):
        items = [self.item(), self.item(date=EVENT_DATE + datetime.timedelta(days=1))]
        first = save_confirmed_entries(self.parent, items)

        second = save_confirmed_entries(self.parent, items)

        self.assertEqual(first, second)
        self.assertEqual(Entry.objects.count(), 2)

    def test_empty_or_oversized_batches_are_refused(self):
        for count in (0, 11):
            with self.subTest(count=count):
                with self.assertRaises(ValueError):
                    save_confirmed_entries(self.parent, [self.item() for _ in range(count)])
        self.assertFalse(Entry.objects.exists())

    def test_non_parents_are_refused(self):
        for membership in (None, self.child):
            with self.subTest(membership=membership):
                with self.assertRaises(PermissionDenied):
                    save_confirmed_entries(membership, [self.item()])
        self.assertFalse(Entry.objects.exists())


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
        """Every context membership that must be denied; state changes are applied lazily."""

        def inactive_parent():
            self.parent.is_active = False
            self.parent.save(update_fields=('is_active',))
            return self.parent

        def inactive_family():
            self.family.is_active = False
            self.family.save(update_fields=('is_active',))
            return self.parent

        return {
            'no family context': lambda: None,
            'child': lambda: self.child,
            'inactive member': lambda: self.inactive_child,
            'inactive parent': inactive_parent,
            'inactive family': inactive_family,
        }

    def snapshot(self):
        return sorted(
            Entry.objects.values_list(
                'pk', 'family_id', 'entry_type', 'content', 'date', 'time',
                'assigned_member_id', 'school_item', 'school_subject', 'source', 'created_by_id',
                'submission_key', 'created_at', 'updated_at',
            )
        )


class ParentFamilyEntriesTests(ManagementFixtureMixin, TestCase):
    def test_parent_sees_only_own_family_entries(self):
        entries = parent_family_entries(self.parent)

        self.assertCountEqual(entries, [self.manual, self.eduvulcan])

    def test_lookup_resolves_own_entry_and_hides_foreign_and_missing(self):
        self.assertEqual(get_parent_family_entry(self.parent, self.manual.pk), self.manual)
        for entry_id in (self.foreign.pk, 999999):
            with self.subTest(entry_id=entry_id):
                with self.assertRaises(Entry.DoesNotExist):
                    get_parent_family_entry(self.parent, entry_id)

    def test_unauthorized_users_are_denied(self):
        for name, get_membership in self.unauthorized_users().items():
            with self.subTest(name):
                membership = get_membership()
                with self.assertRaises(PermissionDenied):
                    parent_family_entries(membership)
                with self.assertRaises(PermissionDenied):
                    get_parent_family_entry(membership, self.manual.pk)


class CreateFamilyEntryTests(ManagementFixtureMixin, TestCase):
    def create(self, membership='parent', **overrides):
        values = {
            'entry_type': EntryType.TODO.value,
            'content': 'Kupić zeszyt w kratkę',
            'date': None,
            'time': None,
            'assigned_member': self.other_child,
            'school_item': '',
            'school_subject': '',
            'submission_key': uuid.uuid4(),
        }
        values.update(overrides)
        return create_family_entry(
            self.parent if membership == 'parent' else membership, **values
        )

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
        for name, get_membership in self.unauthorized_users().items():
            with self.subTest(name):
                with self.assertRaises(PermissionDenied):
                    self.create(membership=get_membership())
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
                'school_subject': 'Biologia',
                'assigned_member': None,
            },
            'too long subject': {'school_subject': TOO_LONG_SUBJECT},
        }
        for name, overrides in cases.items():
            with self.subTest(name):
                with self.assertRaises(ValidationError):
                    self.create(**overrides)
        self.assertEqual(self.snapshot(), before)

    def test_school_event_kinds_require_a_subject(self):
        before = self.snapshot()
        for kind in SCHOOL_EVENT_KINDS:
            with self.subTest(kind=kind.value):
                with self.assertRaisesMessage(
                    ValidationError, 'Ten wpis szkolny wymaga przedmiotu.'
                ):
                    self.create(
                        entry_type=EntryType.CALENDAR_EVENT.value,
                        date=EVENT_DATE,
                        school_item=kind.value,
                        school_subject='  ',
                    )
        self.assertEqual(self.snapshot(), before)

    def test_school_event_with_subject_is_created(self):
        for kind in SCHOOL_EVENT_KINDS:
            with self.subTest(kind=kind.value):
                entry, created = self.create(
                    entry_type=EntryType.CALENDAR_EVENT.value,
                    date=EVENT_DATE,
                    school_item=kind.value,
                    school_subject=' Historia ',
                )
                self.assertTrue(created)
                entry.refresh_from_db()
                self.assertEqual(entry.school_subject, 'Historia')

    def test_subject_is_optional_for_other_entries(self):
        entry, created = self.create(
            entry_type=EntryType.NOTE.value,
            school_item=SchoolItemKind.GRADE.value,
            school_subject='',
        )

        self.assertTrue(created)
        self.assertEqual(entry.school_subject, '')

    def test_key_owned_by_another_family_is_rejected(self):
        foreign_key = uuid.uuid4()
        self.foreign.submission_key = foreign_key
        self.foreign.save(update_fields=('submission_key',))
        before = self.snapshot()

        with self.assertRaises(ValidationError):
            self.create(submission_key=foreign_key)

        self.assertEqual(self.snapshot(), before)


class UpdateFamilyEntryTests(ManagementFixtureMixin, TestCase):
    def update(self, entry, membership='parent', **overrides):
        values = {
            'entry_type': EntryType.CALENDAR_EVENT.value,
            'content': 'Kartkówka z chemii',
            'date': EVENT_DATE + datetime.timedelta(days=2),
            'time': datetime.time(10, 0),
            'assigned_member': self.other_child,
            'school_item': SchoolItemKind.QUIZ.value,
            'school_subject': 'Chemia',
        }
        values.update(overrides)
        return update_family_entry(
            self.parent if membership == 'parent' else membership, entry.pk, **values
        )

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
                self.assertEqual(updated.school_subject, 'Chemia')
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
                        self.parent,
                        entry_id,
                        entry_type=EntryType.NOTE.value,
                        content='Przejęta',
                        date=None,
                        time=None,
                        assigned_member=None,
                        school_item='',
                        school_subject='',
                    )
        self.assertEqual(self.snapshot(), before)

    def test_unauthorized_users_are_denied_and_nothing_changes(self):
        before = self.snapshot()
        for name, get_membership in self.unauthorized_users().items():
            with self.subTest(name):
                with self.assertRaises(PermissionDenied):
                    self.update(self.manual, membership=get_membership())
        self.assertEqual(self.snapshot(), before)

    def test_foreign_or_inactive_assignee_is_rejected_without_mutation(self):
        before = self.snapshot()
        for member in (self.other_family_child, self.inactive_child):
            with self.subTest(member=member.display_name):
                with self.assertRaises(ValidationError):
                    self.update(self.manual, assigned_member=member)
        self.assertEqual(self.snapshot(), before)

    def test_unchanged_inactive_assignee_is_kept(self):
        self.manual.assigned_member = self.inactive_child
        self.manual.save(update_fields=('assigned_member',))

        updated = self.update(self.manual, content='Poprawiony tytuł', assigned_member=self.inactive_child)

        updated.refresh_from_db()
        self.assertEqual(updated.assigned_member, self.inactive_child)
        self.assertEqual(updated.content, 'Poprawiony tytuł')

    def test_invalid_values_are_rejected_without_mutation(self):
        before = self.snapshot()
        cases = {
            'blank content': {'content': ''},
            'too long content': {'content': 'x' * 2001},
            'undated event': {'date': None},
            'school item type mismatch': {'entry_type': EntryType.NOTE.value},
            'school item missing member': {'assigned_member': None},
            'too long subject': {'school_subject': TOO_LONG_SUBJECT},
        }
        for name, overrides in cases.items():
            with self.subTest(name):
                with self.assertRaises(ValidationError):
                    self.update(self.manual, **overrides)
        self.assertEqual(self.snapshot(), before)

    def subjectless_school_event(self, kind=SchoolItemKind.TEST, source=Entry.Source.EDUVULCAN):
        return Entry.objects.create(
            family=self.family,
            entry_type=EntryType.CALENDAR_EVENT.value,
            content='Sprawdzian: Biologia',
            date=EVENT_DATE,
            assigned_member=self.child,
            school_item=kind.value,
            source=source,
        )

    def test_unrelated_edit_of_subjectless_school_event_saves_without_subject(self):
        cases = {
            'reassign': {'assigned_member': self.other_child},
            'move date': {'date': EVENT_DATE + datetime.timedelta(days=7)},
            'retitle': {'content': 'Sprawdzian z działu 3'},
        }
        for source in (Entry.Source.EDUVULCAN, Entry.Source.MANUAL):
            for kind in SCHOOL_EVENT_KINDS:
                for name, overrides in cases.items():
                    with self.subTest(source=source, kind=kind.value, edit=name):
                        entry = self.subjectless_school_event(kind, source)
                        values = {
                            'content': entry.content,
                            'date': entry.date,
                            'time': None,
                            'assigned_member': self.child,
                            'school_item': kind.value,
                            'school_subject': '',
                        }
                        values.update(overrides)

                        updated = self.update(entry, **values)

                        updated.refresh_from_db()
                        self.assertEqual(updated.school_item, kind.value)
                        self.assertEqual(updated.school_subject, '')
                        for field, value in overrides.items():
                            self.assertEqual(getattr(updated, field), value)

    def test_clearing_a_stored_subject_is_rejected(self):
        self.manual.school_subject = 'Biologia'
        self.manual.save(update_fields=('school_subject',))
        before = self.snapshot()

        for blank in ('', '   '):
            with self.subTest(subject=blank):
                with self.assertRaisesMessage(
                    ValidationError, 'Ten wpis szkolny wymaga przedmiotu.'
                ):
                    self.update(
                        self.manual, school_item=SchoolItemKind.TEST.value, school_subject=blank
                    )
        self.assertEqual(self.snapshot(), before)

    def test_setting_or_changing_to_a_school_event_kind_requires_a_subject(self):
        subjectless_test = self.subjectless_school_event(SchoolItemKind.TEST)
        plain_event = Entry.objects.create(
            family=self.family,
            entry_type=EntryType.CALENDAR_EVENT.value,
            content='Wywiadówka',
            date=EVENT_DATE,
            assigned_member=self.child,
        )
        before = self.snapshot()
        cases = (
            (subjectless_test, SchoolItemKind.QUIZ),
            (subjectless_test, SchoolItemKind.HOMEWORK),
            (plain_event, SchoolItemKind.TEST),
            (plain_event, SchoolItemKind.CLASS_TEST),
            (self.eduvulcan, SchoolItemKind.QUIZ),
        )
        for entry, kind in cases:
            with self.subTest(entry=entry.content, kind=kind.value):
                with self.assertRaisesMessage(
                    ValidationError, 'Ten wpis szkolny wymaga przedmiotu.'
                ):
                    self.update(
                        entry,
                        date=EVENT_DATE,
                        assigned_member=self.child,
                        school_item=kind.value,
                        school_subject='',
                    )
        self.assertEqual(self.snapshot(), before)

    def test_subject_can_be_added_to_a_subjectless_school_event(self):
        entry = self.subjectless_school_event()

        updated = self.update(
            entry,
            assigned_member=self.child,
            school_item=SchoolItemKind.TEST.value,
            school_subject='  Biologia  ',
        )

        updated.refresh_from_db()
        self.assertEqual(updated.school_subject, 'Biologia')


class CreateAutomatedEntryTests(FamilyFixtureMixin, TestCase):
    def create(self, **overrides):
        values = {
            'entry_type': EntryType.CALENDAR_EVENT.value,
            'content': 'Sprawdzian: Biologia',
            'date': EVENT_DATE,
            'assigned_member_id': self.child.pk,
            'school_item': SchoolItemKind.TEST.value,
        }
        values.update(overrides)
        return create_automated_entry(self.family, **values)

    def test_school_event_without_subject_is_saved_as_calendar_event(self):
        for kind in SCHOOL_EVENT_KINDS:
            for overrides in ({}, {'school_subject': ''}, {'school_subject': '  '}):
                with self.subTest(kind=kind.value, **overrides):
                    entry = self.create(school_item=kind.value, **overrides)

                    entry.refresh_from_db()
                    self.assertEqual(entry.entry_type, EntryType.CALENDAR_EVENT.value)
                    self.assertEqual(entry.school_item, kind.value)
                    self.assertEqual(entry.school_subject, '')
                    self.assertEqual(entry.source, Entry.Source.EDUVULCAN)

    def test_subject_is_stored_stripped(self):
        entry = self.create(school_subject=' Biologia ')

        entry.refresh_from_db()
        self.assertEqual(entry.school_subject, 'Biologia')

    def test_too_long_subject_is_rejected_without_write(self):
        with self.assertRaisesMessage(ValidationError, 'Przedmiot jest za długi.'):
            self.create(school_subject=TOO_LONG_SUBJECT)
        self.assertFalse(Entry.objects.exists())


class DeleteFamilyEntryTests(ManagementFixtureMixin, TestCase):
    def test_deletes_only_the_target_row(self):
        for entry in (self.manual, self.eduvulcan):
            with self.subTest(source=entry.source):
                delete_family_entry(self.parent, entry.pk)
                self.assertFalse(Entry.objects.filter(pk=entry.pk).exists())

        self.assertEqual(list(Entry.objects.values_list('pk', flat=True)), [self.foreign.pk])

    def test_foreign_and_missing_entries_are_not_found_and_kept(self):
        before = self.snapshot()
        for entry_id in (self.foreign.pk, 999999):
            with self.subTest(entry_id=entry_id):
                with self.assertRaises(Entry.DoesNotExist):
                    delete_family_entry(self.parent, entry_id)
        self.assertEqual(self.snapshot(), before)

    def test_unauthorized_users_are_denied_and_nothing_is_deleted(self):
        before = self.snapshot()
        for name, get_membership in self.unauthorized_users().items():
            with self.subTest(name):
                with self.assertRaises(PermissionDenied):
                    delete_family_entry(get_membership(), self.manual.pk)
        self.assertEqual(self.snapshot(), before)


class TwoParentAssigneeServiceTests(TwoParentFixtureMixin, TestCase):
    """S-07: every parent write path persists a parent assignee; foreign ones never."""

    def values(self, member, entry_type=EntryType.NOTE):
        return {
            'entry_type': entry_type.value,
            'content': 'Odebrać paczkę z poczty',
            'date': EVENT_DATE if entry_type == EntryType.CALENDAR_EVENT else None,
            'time': None,
            'assigned_member': member,
            'school_item': '',
            'school_subject': '',
        }

    def test_confirm_and_create_persist_self_and_other_parent(self):
        writers = {
            'save_confirmed_entry': save_confirmed_entry,
            'create_family_entry': create_family_entry,
        }
        for name, write in writers.items():
            for member in (self.parent, self.second_parent):
                for entry_type in (EntryType.NOTE, EntryType.TODO, EntryType.CALENDAR_EVENT):
                    with self.subTest(writer=name, member=member.display_name, type=entry_type):
                        entry, created = write(
                            self.parent,
                            submission_key=uuid.uuid4(),
                            **self.values(member, entry_type),
                        )
                        self.assertTrue(created)
                        entry.refresh_from_db()
                        self.assertEqual(entry.assigned_member, member)
                        self.assertEqual(entry.created_by, self.parent)
                        self.assertEqual(entry.entry_type, entry_type.value)

    def test_update_persists_self_and_other_parent(self):
        entry = Entry.objects.create(
            family=self.family,
            entry_type=EntryType.NOTE.value,
            content='Stary wpis',
            assigned_member=self.child,
            created_by=self.parent,
        )
        for member in (self.second_parent, self.parent):
            for entry_type in (EntryType.NOTE, EntryType.TODO):
                with self.subTest(member=member.display_name, type=entry_type):
                    update_family_entry(
                        self.parent, entry.pk, **self.values(member, entry_type)
                    )
                    entry.refresh_from_db()
                    self.assertEqual(entry.assigned_member, member)

    def test_foreign_and_inactive_parents_are_rejected_without_writes(self):
        entry = Entry.objects.create(
            family=self.family,
            entry_type=EntryType.NOTE.value,
            content='Stary wpis',
            assigned_member=self.second_parent,
            created_by=self.parent,
        )
        before = sorted(Entry.objects.values_list('pk', 'assigned_member_id', 'content'))
        for member in (self.other_family_parent, self.inactive_parent):
            writes = {
                'save_confirmed_entry': lambda: save_confirmed_entry(
                    self.parent, submission_key=uuid.uuid4(), **self.values(member)
                ),
                'create_family_entry': lambda: create_family_entry(
                    self.parent, submission_key=uuid.uuid4(), **self.values(member)
                ),
                'update_family_entry': lambda: update_family_entry(
                    self.parent, entry.pk, **self.values(member)
                ),
            }
            for name, write in writes.items():
                with self.subTest(member=member.display_name, writer=name):
                    with self.assertRaisesMessage(
                        ValidationError, 'Wybrana osoba nie należy do rodziny.'
                    ):
                        write()
                    self.assertEqual(
                        sorted(Entry.objects.values_list('pk', 'assigned_member_id', 'content')),
                        before,
                    )
