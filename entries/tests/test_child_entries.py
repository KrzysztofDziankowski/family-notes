"""``child_entries``: the child-scoped read boundary and its access matrix."""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.test import TestCase

from entries.classification.types import EntryType
from entries.models import Entry
from entries.services import child_entries

from .test_classification_service import FamilyFixtureMixin, TwoParentFixtureMixin


class ChildEntriesTests(FamilyFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.own = self._entry('own', self.family, self.child)
        self.unassigned = self._entry('unassigned', self.family, None)
        self.sibling = self._entry('sibling', self.family, self.other_child)
        self.foreign = self._entry('foreign', self.other_family, self.other_family_child)
        self.inactive_childs = self._entry('inactive', self.family, self.inactive_child)

    def _entry(self, content, family, assigned_member):
        return Entry.objects.create(
            family=family,
            entry_type=EntryType.NOTE.value,
            content=content,
            assigned_member=assigned_member,
        )

    def test_active_child_sees_only_own_entries(self):
        self.assertEqual(list(child_entries(self.child.user)), [self.own])

    def test_each_child_is_scoped_to_themselves(self):
        self.assertEqual(list(child_entries(self.other_child.user)), [self.sibling])
        self.assertEqual(
            list(child_entries(self.other_family_child.user)), [self.foreign]
        )

    def test_assigned_member_is_preloaded(self):
        entries = list(child_entries(self.child.user))

        with self.assertNumQueries(0):
            self.assertEqual(entries[0].assigned_member.display_name, 'Michał')

    def test_unauthorized_callers_are_denied(self):
        unconfigured = get_user_model().objects.create_user(username='unconfigured')

        def inactive_family_child():
            self.family.is_active = False
            self.family.save(update_fields=['is_active'])
            return self.child.user

        cases = {
            'parent': lambda: self.parent.user,
            'inactive child': lambda: self.inactive_child.user,
            'child in inactive family': inactive_family_child,
            'unconfigured user': lambda: unconfigured,
            'anonymous': lambda: AnonymousUser(),
        }
        for name, get_user in cases.items():
            with self.subTest(name):
                with self.assertRaises(PermissionDenied):
                    child_entries(get_user())


class TwoParentChildEntriesTests(TwoParentFixtureMixin, TestCase):
    """S-07: the child read service never returns a parent-assigned entry."""

    def test_parent_assigned_entries_are_never_returned_to_a_child(self):
        own = Entry.objects.create(
            family=self.family, entry_type=EntryType.NOTE.value, content='own',
            assigned_member=self.child,
        )
        for parent in (self.parent, self.second_parent):
            Entry.objects.create(
                family=self.family, entry_type=EntryType.NOTE.value,
                content=f'for {parent.display_name}', assigned_member=parent,
            )

        self.assertEqual(list(child_entries(self.child.user)), [own])
        self.assertEqual(list(child_entries(self.other_child.user)), [])
