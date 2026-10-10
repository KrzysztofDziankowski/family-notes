"""Creator-only entry privacy: services, direct-entry views and the automation API.

A private entry is visible only to its ``created_by`` member, whatever its
assignee or the reader's role. Every inaccessible private ID resolves like a
missing one, and the automation API never returns a private entry.
"""

import datetime
import uuid

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from entries.classification.types import EntryType
from entries.models import Entry
from entries.services import (
    automation_family_entries,
    child_entries,
    create_automated_entry,
    create_family_entry,
    delete_family_entry,
    get_parent_family_entry,
    parent_family_entries,
    save_confirmed_entry,
    set_entry_privacy,
    update_family_entry,
)
from family_access.models import AutomationToken

from .test_classification_service import TwoParentFixtureMixin

EWA_PRIVATE = 'SENTINEL-PRYWATNE-EWY-3c1d'
PAWEL_PRIVATE = 'SENTINEL-PRYWATNE-PAWLA-7b2e'
CHILD_PRIVATE = 'SENTINEL-PRYWATNE-MICHALA-a904'
FOREIGN_PRIVATE = 'SENTINEL-PRYWATNE-OBCE-55e0'


class PrivateEntriesFixtureMixin(TwoParentFixtureMixin):
    """Private and public entries of the shared family, all assigned to the child.

    ``ewa_private`` (by ``parent``), ``pawel_private`` (by ``second_parent``) and
    ``child_private`` (by ``child``) are private; ``public`` (by
    ``second_parent``) and ``eduvulcan`` (no creator) are public.
    """

    def setUp(self):
        super().setUp()
        self.today = timezone.localdate()
        self.ewa_private = self.make_entry(EWA_PRIVATE, self.parent, is_private=True)
        self.pawel_private = self.make_entry(PAWEL_PRIVATE, self.second_parent, is_private=True)
        self.child_private = self.make_entry(CHILD_PRIVATE, self.child, is_private=True)
        self.public = self.make_entry('Publiczny wpis Pawła', self.second_parent)
        self.eduvulcan = self.make_entry(
            'Kartkówka z EduVulcan', None, source=Entry.Source.EDUVULCAN
        )
        self.foreign_private = Entry.objects.create(
            family=self.other_family,
            entry_type=EntryType.NOTE.value,
            content=FOREIGN_PRIVATE,
            date=self.today,
            created_by=self.other_family_parent,
            is_private=True,
        )

    def make_entry(self, content, creator, **values):
        values.setdefault('assigned_member', self.child)
        return Entry.objects.create(
            family=self.family,
            entry_type=EntryType.NOTE.value,
            content=content,
            date=self.today,
            created_by=creator,
            submission_key=uuid.uuid4() if creator else None,
            **values,
        )

    def snapshot(self):
        return sorted(
            Entry.objects.values_list(
                'pk', 'family_id', 'entry_type', 'content', 'date', 'time',
                'assigned_member_id', 'school_item', 'school_subject', 'source',
                'created_by_id', 'submission_key', 'is_private', 'updated_at',
            )
        )

    def missing_pk(self):
        return Entry.objects.order_by('-pk').first().pk + 500


class PrivacyDefaultTests(PrivateEntriesFixtureMixin, TestCase):
    def test_existing_and_new_entries_are_public_by_default(self):
        self.assertFalse(Entry._meta.get_field('is_private').null)
        self.assertIs(Entry._meta.get_field('is_private').db_default, False)

        confirmed, _ = save_confirmed_entry(
            self.parent, entry_type=EntryType.TODO.value, content='Zadanie', date=self.today,
            time=None, assigned_member=None, school_item='', submission_key=uuid.uuid4(),
            school_subject='',
        )
        created, _ = create_family_entry(
            self.parent, entry_type=EntryType.NOTE.value, content='Notatka', date=self.today,
            time=None, assigned_member=None, school_item='', submission_key=uuid.uuid4(),
            school_subject='',
        )
        automated = create_automated_entry(
            self.family, entry_type=EntryType.NOTE.value, content='Z EduVulcan', date=self.today,
        )

        for entry in (confirmed, created, automated):
            with self.subTest(entry=entry.content):
                entry.refresh_from_db()
                self.assertFalse(entry.is_private)


class PrivateReadServiceTests(PrivateEntriesFixtureMixin, TestCase):
    def test_parent_sees_public_and_own_private_entries_only(self):
        self.assertCountEqual(
            parent_family_entries(self.parent),
            [self.ewa_private, self.public, self.eduvulcan],
        )
        self.assertCountEqual(
            parent_family_entries(self.second_parent),
            [self.pawel_private, self.public, self.eduvulcan],
        )

    def test_child_sees_public_assigned_and_own_private_entries_only(self):
        self.assertCountEqual(
            child_entries(self.child), [self.child_private, self.public, self.eduvulcan]
        )
        self.assertEqual(list(child_entries(self.other_child)), [])

    def test_child_read_stays_assignment_scoped_for_own_private_entries(self):
        """The child read stays assignment-scoped: privacy only narrows it."""
        self.make_entry('Prywatne dla Ani', self.child, assigned_member=self.other_child,
                        is_private=True)

        self.assertNotIn('Prywatne dla Ani', [e.content for e in child_entries(self.child)])
        self.assertEqual(list(child_entries(self.other_child)), [])

    def test_private_entry_of_another_member_resolves_like_a_missing_id(self):
        for entry in (self.pawel_private, self.child_private, self.foreign_private):
            with self.subTest(entry=entry.content):
                with self.assertRaises(Entry.DoesNotExist):
                    get_parent_family_entry(self.parent, entry.pk)
        self.assertEqual(get_parent_family_entry(self.parent, self.ewa_private.pk),
                         self.ewa_private)

    def test_automation_read_returns_public_entries_only(self):
        for owner in (self.parent, self.second_parent):
            with self.subTest(owner=owner.display_name):
                self.assertCountEqual(
                    automation_family_entries(owner), [self.public, self.eduvulcan]
                )


class PrivateMutationServiceTests(PrivateEntriesFixtureMixin, TestCase):
    def update(self, membership, entry):
        return update_family_entry(
            membership, entry.pk, entry_type=EntryType.NOTE.value, content='Zmienione',
            date=self.today, time=None, assigned_member=None, school_item='',
            school_subject='',
        )

    def test_non_creator_parent_cannot_update_or_delete_a_private_entry(self):
        before = self.snapshot()
        for entry in (self.pawel_private, self.child_private):
            with self.subTest(entry=entry.content):
                with self.assertRaises(Entry.DoesNotExist):
                    self.update(self.parent, entry)
                with self.assertRaises(Entry.DoesNotExist):
                    delete_family_entry(self.parent, entry.pk)
        self.assertEqual(self.snapshot(), before)

    def test_creator_parent_manages_own_private_entry_and_it_stays_private(self):
        self.update(self.parent, self.ewa_private)
        self.ewa_private.refresh_from_db()
        self.assertEqual(self.ewa_private.content, 'Zmienione')
        self.assertTrue(self.ewa_private.is_private)

        delete_family_entry(self.parent, self.ewa_private.pk)
        self.assertFalse(Entry.objects.filter(pk=self.ewa_private.pk).exists())

    def test_replayed_key_of_another_members_private_entry_is_rejected(self):
        values = dict(
            entry_type=EntryType.NOTE.value, content='Powtórka', date=self.today, time=None,
            assigned_member=None, school_item='', school_subject='',
        )
        before = self.snapshot()
        with self.assertRaises(ValidationError):
            save_confirmed_entry(
                self.parent, submission_key=self.pawel_private.submission_key, **values
            )
        with self.assertRaises(ValidationError):
            create_family_entry(
                self.parent, submission_key=self.child_private.submission_key, **values
            )
        self.assertEqual(self.snapshot(), before)

        entry, created = save_confirmed_entry(
            self.parent, submission_key=self.ewa_private.submission_key, **values
        )
        self.assertEqual((entry, created), (self.ewa_private, False))


class SetEntryPrivacyTests(PrivateEntriesFixtureMixin, TestCase):
    def fields_except_privacy(self, entry):
        entry.refresh_from_db()
        return {
            field.attname: getattr(entry, field.attname)
            for field in Entry._meta.concrete_fields
            if field.attname not in ('is_private', 'updated_at')
        }

    def test_creator_changes_only_privacy(self):
        for creator, entry in (
            (self.parent, self.ewa_private),
            (self.child, self.child_private),
            (self.second_parent, self.public),
        ):
            with self.subTest(creator=creator.display_name):
                before = self.fields_except_privacy(entry)
                was_private = entry.is_private

                set_entry_privacy(creator, entry.pk, is_private=not was_private)

                self.assertEqual(self.fields_except_privacy(entry), before)
                self.assertIs(entry.is_private, not was_private)

    def test_non_creators_are_refused_like_a_missing_id(self):
        def inactive_creator():
            self.parent.is_active = False
            self.parent.save(update_fields=['is_active'])
            return self.parent

        cases = [
            ('other parent', lambda: self.second_parent, self.ewa_private),
            ('assigned child', lambda: self.child, self.ewa_private),
            ('parent on child entry', lambda: self.parent, self.child_private),
            ('child on public entry', lambda: self.child, self.public),
            ('other child', lambda: self.other_child, self.child_private),
            ('creatorless entry', lambda: self.parent, self.eduvulcan),
            ('foreign family', lambda: self.other_family_parent, self.ewa_private),
            ('missing id', lambda: self.parent, Entry(pk=self.missing_pk())),
            ('no family context', lambda: None, self.ewa_private),
            ('inactive creator', inactive_creator, self.ewa_private),
        ]
        for name, get_membership, entry in cases:
            with self.subTest(name):
                before = self.snapshot()
                with self.assertRaises(Entry.DoesNotExist):
                    set_entry_privacy(get_membership(), entry.pk, is_private=False)
                self.assertEqual(self.snapshot(), before)


class ParentPrivateEntryViewTests(PrivateEntriesFixtureMixin, TestCase):
    def edit_data(self):
        return {
            'entry_type': EntryType.NOTE.value,
            'content': 'Zmieniona treść',
            'date': self.today.isoformat(),
            'time': '',
            'assigned_member': '',
            'school_item': '',
        }

    def paths(self, pk):
        return [
            ('detail', 'get', reverse('entries:detail', args=[pk])),
            ('edit form', 'get', reverse('entries:edit', args=[pk])),
            ('edit', 'post', reverse('entries:edit', args=[pk])),
            ('delete', 'post', reverse('entries:delete', args=[pk])),
        ]

    def send(self, method, url):
        return getattr(self.client, method)(url, self.edit_data() if method == 'post' else None)

    def test_creator_parent_opens_own_private_entry(self):
        self.client.force_login(self.parent.user)

        response = self.client.get(reverse('entries:detail', args=[self.ewa_private.pk]))

        self.assertContains(response, EWA_PRIVATE)

    def test_other_private_entries_are_indistinguishable_from_missing_ids(self):
        self.client.force_login(self.parent.user)
        before = self.snapshot()
        missing = {
            label: self.send(method, url).content
            for label, method, url in self.paths(self.missing_pk())
        }
        for entry in (self.pawel_private, self.child_private, self.foreign_private):
            for label, method, url in self.paths(entry.pk):
                with self.subTest(entry=entry.content, path=label):
                    response = self.send(method, url)
                    self.assertEqual(response.status_code, 404)
                    self.assertNotContains(response, entry.content, status_code=404)
                    self.assertEqual(response.content, missing[label])
        self.assertEqual(self.snapshot(), before)

    def test_other_parent_cannot_open_but_still_reads_public_entries(self):
        self.client.force_login(self.second_parent.user)

        self.assertEqual(
            self.client.get(reverse('entries:detail', args=[self.ewa_private.pk])).status_code,
            404,
        )
        for entry in (self.public, self.eduvulcan, self.pawel_private):
            with self.subTest(entry=entry.content):
                self.assertContains(
                    self.client.get(reverse('entries:detail', args=[entry.pk])), entry.content
                )

    def test_calendar_lists_public_and_own_private_entries_only(self):
        self.client.force_login(self.parent.user)

        response = self.client.get(reverse('entries:index'))

        self.assertContains(response, EWA_PRIVATE)
        self.assertContains(response, 'Publiczny wpis Pawła')
        for content in (PAWEL_PRIVATE, CHILD_PRIVATE, FOREIGN_PRIVATE):
            self.assertNotContains(response, content)

    def test_saved_confirmation_never_shows_another_members_private_entry(self):
        self.client.force_login(self.parent.user)
        saved = ','.join(
            str(entry.pk) for entry in (self.pawel_private, self.child_private, self.ewa_private)
        )

        response = self.client.get(reverse('entries:capture'), {'saved': saved})

        self.assertContains(response, EWA_PRIVATE)
        self.assertNotContains(response, PAWEL_PRIVATE)
        self.assertNotContains(response, CHILD_PRIVATE)

    def test_anonymous_is_redirected_to_login(self):
        for label, method, url in self.paths(self.ewa_private.pk):
            with self.subTest(path=label):
                response = self.send(method, url)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response['Location'].startswith(reverse('account_login')))


class ChildPrivateEntryViewTests(PrivateEntriesFixtureMixin, TestCase):
    def detail(self, entry_or_pk):
        pk = getattr(entry_or_pk, 'pk', entry_or_pk)
        return self.client.get(reverse('entries:child_detail', args=[pk]))

    def test_child_opens_own_private_and_public_entries(self):
        self.client.force_login(self.child.user)
        for entry in (self.child_private, self.public, self.eduvulcan):
            with self.subTest(entry=entry.content):
                self.assertContains(self.detail(entry), entry.content)

    def test_parent_private_entry_assigned_to_child_is_a_plain_404(self):
        self.client.force_login(self.child.user)
        missing = self.detail(self.missing_pk())
        for entry in (self.ewa_private, self.pawel_private, self.foreign_private):
            with self.subTest(entry=entry.content):
                response = self.detail(entry)
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.content, missing.content)

    def test_child_calendar_lists_public_and_own_private_entries_only(self):
        self.client.force_login(self.child.user)

        response = self.client.get(reverse('entries:child_list'))

        self.assertContains(response, CHILD_PRIVATE)
        self.assertContains(response, 'Publiczny wpis Pawła')
        for content in (EWA_PRIVATE, PAWEL_PRIVATE, FOREIGN_PRIVATE):
            self.assertNotContains(response, content)

    def test_other_child_cannot_open_a_childs_private_entry(self):
        self.client.force_login(self.other_child.user)

        self.assertEqual(self.detail(self.child_private).status_code, 404)
        self.assertNotContains(self.client.get(reverse('entries:child_list')), CHILD_PRIVATE)

    def test_anonymous_is_redirected_to_login(self):
        response = self.detail(self.child_private)

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response['Location'].startswith(reverse('account_login')))


class PrivateEntriesApiTests(PrivateEntriesFixtureMixin, TestCase):
    def test_api_excludes_private_entries_even_for_their_creator(self):
        _, secret = AutomationToken.issue(self.parent, 'Telefon')

        response = self.client.get(
            reverse('automation:entries_list'), HTTP_AUTHORIZATION=f'Bearer {secret}'
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['count'], 2)
        self.assertCountEqual(
            [record['id'] for record in body['results']], [self.public.pk, self.eduvulcan.pk]
        )
        for content in (EWA_PRIVATE, PAWEL_PRIVATE, CHILD_PRIVATE, FOREIGN_PRIVATE):
            self.assertNotIn(content, response.content.decode())
        self.assertNotIn('is_private', body['results'][0])

    def test_creatorless_eduvulcan_entries_stay_public(self):
        _, secret = AutomationToken.issue(self.second_parent, 'Telefon')
        window = {'date_from': (self.today - datetime.timedelta(days=1)).isoformat()}

        response = self.client.get(
            reverse('automation:entries_list'), window,
            HTTP_AUTHORIZATION=f'Bearer {secret}',
        )

        self.assertIn(self.eduvulcan.pk, [record['id'] for record in response.json()['results']])
