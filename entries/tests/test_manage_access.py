import datetime
"""Access matrix for every parent management path (S-02 phase 3).

Every read and mutation obeys the family-access hard rule: only an active parent
of an active family reaches its own family's entries; everyone else is denied,
and denied mutations leave the database unchanged.
"""

import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from entries.classification.types import EntryType
from entries.models import Entry
from family_access.models import FamilyMember

from .test_classification_service import FamilyFixtureMixin

FOREIGN_SENTINEL = 'SENTINEL-OBCY-WPIS-91fa'
PRIVATE_SENTINEL = 'SENTINEL-PRYWATNY-WPIS-0d4c'


class ManageAccessMatrixTests(FamilyFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.own = Entry.objects.create(date=timezone.localdate(),
            family=self.family,
            entry_type=EntryType.TODO.value,
            content='Własny wpis',
            created_by=self.parent,
        )
        self.foreign = Entry.objects.create(date=timezone.localdate(),
            family=self.other_family,
            entry_type=EntryType.NOTE.value,
            content=FOREIGN_SENTINEL,
            created_by=self.other_family_parent,
        )
        self.unconfigured = get_user_model().objects.create_user(username='unconfigured')

    # -- helpers ---------------------------------------------------------------

    def post_data(self):
        return {
            'entry_type': EntryType.NOTE.value,
            'content': 'Zmieniona treść',
            'date': timezone.localdate().isoformat(),
            'time': '',
            'assigned_member': '',
            'school_item': '',
            'submission_key': str(uuid.uuid4()),
        }

    def requests_for(self, entry):
        """(label, method, url) for every exposed management path on ``entry``."""
        return [
            ('index', 'get', reverse('entries:index')),
            ('create form', 'get', reverse('entries:create')),
            ('create', 'post', reverse('entries:create')),
            ('detail', 'get', reverse('entries:detail', args=[entry.pk])),
            ('edit form', 'get', reverse('entries:edit', args=[entry.pk])),
            ('edit', 'post', reverse('entries:edit', args=[entry.pk])),
            ('delete', 'post', reverse('entries:delete', args=[entry.pk])),
        ]

    def send(self, method, url):
        return getattr(self.client, method)(url, self.post_data() if method == 'post' else None)

    def snapshot(self):
        return sorted(
            Entry.objects.values_list(
                'pk', 'family_id', 'entry_type', 'content', 'date', 'time',
                'assigned_member_id', 'school_item', 'source', 'created_by_id', 'is_private',
                'updated_at',
            )
        )

    def denied_users(self):
        """Users an active parent's management paths must reject with 403."""

        def inactive_parent():
            self.parent.is_active = False
            self.parent.save()
            return self.parent.user

        def inactive_family():
            self.family.is_active = False
            self.family.save()
            return self.parent.user

        return {
            'child': lambda: self.child.user,
            'inactive parent': inactive_parent,
            'parent of inactive family': inactive_family,
            'user without membership': lambda: self.unconfigured,
        }

    # -- matrix ----------------------------------------------------------------

    def test_active_parent_reaches_every_path_for_own_family_entry(self):
        expected = {'get': 200, 'post': 302}
        for label, method, url in self.requests_for(self.own):
            with self.subTest(path=label):
                self.client.force_login(self.parent.user)
                response = self.send(method, url)
                self.assertEqual(response.status_code, expected[method])
        self.assertFalse(Entry.objects.filter(pk=self.own.pk).exists())

    def test_parent_targeting_foreign_entry_gets_404_without_mutation(self):
        self.client.force_login(self.parent.user)
        before = self.snapshot()
        missing = Entry(pk=Entry.objects.order_by('-pk').first().pk + 500)
        entry_paths = ('detail', 'edit form', 'edit', 'delete')

        foreign_responses = {}
        for target, entry in (('foreign', self.foreign), ('missing', missing)):
            for label, method, url in self.requests_for(entry):
                if label not in entry_paths:
                    continue
                with self.subTest(target=target, path=label):
                    response = self.send(method, url)
                    self.assertEqual(response.status_code, 404)
                    self.assertNotContains(response, FOREIGN_SENTINEL, status_code=404)
                    if target == 'foreign':
                        foreign_responses[label] = response.content
                    else:
                        self.assertEqual(response.content, foreign_responses[label])

        self.assertEqual(self.snapshot(), before)

    def test_other_parents_private_entry_is_a_404_like_a_missing_id(self):
        second_parent = self._member('second-parent', FamilyMember.Role.PARENT, 'Paweł')
        private = Entry.objects.create(date=timezone.localdate(),
            family=self.family,
            entry_type=EntryType.NOTE.value,
            content=PRIVATE_SENTINEL,
            created_by=second_parent,
            is_private=True,
        )
        missing = Entry(pk=private.pk + 500)
        self.client.force_login(self.parent.user)
        before = self.snapshot()
        entry_paths = ('detail', 'edit form', 'edit', 'delete')

        missing_responses = {
            label: self.send(method, url).content
            for label, method, url in self.requests_for(missing) if label in entry_paths
        }
        for label, method, url in self.requests_for(private):
            if label not in entry_paths:
                continue
            with self.subTest(path=label):
                response = self.send(method, url)
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.content, missing_responses[label])
        self.assertNotContains(self.client.get(reverse('entries:index')), PRIVATE_SENTINEL)
        self.assertEqual(self.snapshot(), before)

        self.client.force_login(second_parent.user)
        self.assertContains(
            self.client.get(reverse('entries:detail', args=[private.pk])), PRIVATE_SENTINEL
        )

    def test_foreign_entry_never_appears_in_any_window(self):
        self.client.force_login(self.parent.user)
        today = timezone.localdate()
        for offset in (0, -14, -7, 14):
            start = today + datetime.timedelta(days=offset)
            with self.subTest(start=start):
                response = self.client.get(reverse('entries:index'), {'start': start.isoformat()})
                self.assertNotContains(response, FOREIGN_SENTINEL)

    def test_member_filter_never_selects_or_leaks_another_family(self):
        """Phase 4: ``?member`` only selects an active child of the request's own family."""
        foreign_child = self.other_family_child
        Entry.objects.filter(pk=self.foreign.pk).update(assigned_member=foreign_child)
        self.client.force_login(self.parent.user)

        response = self.client.get(reverse('entries:index'), {'member': str(foreign_child.pk)})
        html = response.content.decode()
        self.assertNotContains(response, FOREIGN_SENTINEL)
        self.assertNotIn(f'member={foreign_child.pk}', html)
        self.assertNotIn(f'member-{foreign_child.pk}', html)
        self.assertNotIn('Kuba', html)
        self.assertIn('data-member-key="all" aria-current="page"', html)

        detail = self.client.get(
            reverse('entries:detail', args=[self.own.pk]), {'member': str(foreign_child.pk)}
        )
        self.assertNotContains(detail, f'member={foreign_child.pk}')
        self.assertNotContains(detail, 'name="member"')

        # The other family's parent cannot select our child, and sees only their own rows.
        self.client.force_login(self.other_family_parent.user)
        response = self.client.get(reverse('entries:index'), {'member': str(self.child.pk)})
        html = response.content.decode()
        self.assertContains(response, FOREIGN_SENTINEL)
        self.assertNotContains(response, 'Własny wpis')
        self.assertNotIn(f'member={self.child.pk}', html)
        self.assertNotIn('Michał', html)
        self.assertIn('data-member-key="all" aria-current="page"', html)

    def test_member_filter_does_not_open_the_calendar_to_non_parents(self):
        for name, make_user in self.denied_users().items():
            with self.subTest(user=name):
                self.client.force_login(make_user())
                response = self.client.get(reverse('entries:index'), {'member': str(self.child.pk)})
                self.assertEqual(response.status_code, 403)
                self.parent.refresh_from_db()
                self.family.refresh_from_db()
                self.parent.is_active = True
                self.parent.save()
                self.family.is_active = True
                self.family.save()

    def test_denied_users_get_403_on_every_path_without_mutation(self):
        for name, make_user in self.denied_users().items():
            with self.subTest(user=name):
                user = make_user()
                self.client.force_login(user)
                before = self.snapshot()
                for label, method, url in self.requests_for(self.own):
                    with self.subTest(user=name, path=label):
                        response = self.send(method, url)
                        self.assertEqual(response.status_code, 403)
                        self.assertNotContains(response, 'Własny wpis', status_code=403)
                self.assertEqual(self.snapshot(), before)
                self.parent.refresh_from_db()
                self.family.refresh_from_db()
                self.parent.is_active = True
                self.parent.save()
                self.family.is_active = True
                self.family.save()

    def test_child_is_denied_for_foreign_and_missing_ids_the_same_way(self):
        self.client.force_login(self.child.user)
        for entry in (self.own, self.foreign):
            for label, method, url in self.requests_for(entry):
                with self.subTest(entry=entry.pk, path=label):
                    self.assertEqual(self.send(method, url).status_code, 403)

    def test_anonymous_is_redirected_to_login_without_mutation(self):
        before = self.snapshot()
        for label, method, url in self.requests_for(self.own):
            with self.subTest(path=label):
                response = self.send(method, url)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response['Location'].startswith(reverse('account_login')))
        self.assertEqual(self.snapshot(), before)

    def test_automation_token_header_grants_no_management_access(self):
        before = self.snapshot()
        response = self.client.post(
            reverse('entries:delete', args=[self.own.pk]),
            HTTP_AUTHORIZATION='Bearer fn_live_not-a-session',
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.snapshot(), before)


class ManageLifecycleTests(FamilyFixtureMixin, TestCase):
    """Integration: create → detail → edit → detail → delete → originating list."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.parent.user)

    def test_structured_entry_lifecycle(self):
        response = self.client.post(
            reverse('entries:create'),
            {
                'entry_type': EntryType.TODO.value,
                'content': 'Podpisać zgodę na wycieczkę',
                'date': '2020-01-10',
                'time': '',
                'assigned_member': str(self.child.pk),
                'school_item': '',
                'submission_key': str(uuid.uuid4()),
            },
        )
        entry = Entry.objects.get()
        detail = reverse('entries:detail', args=[entry.pk])
        self.assertRedirects(response, detail, fetch_redirect_response=False)
        page = self.client.get(detail)
        self.assertContains(page, 'Podpisać zgodę na wycieczkę')
        # Without ?start the detail returns to the fortnight holding the entry, on the
        # 14-day grid anchored at today.
        today = timezone.localdate()
        weeks = (datetime.date(2020, 1, 10) - today).days // 14
        window = (today + datetime.timedelta(days=14 * weeks)).isoformat()
        self.assertContains(page, f'<input type="hidden" name="start" value="{window}">', html=True)
        self.assertNotContains(page, 'name="view"')

        response = self.client.post(
            reverse('entries:edit', args=[entry.pk]),
            {
                'entry_type': EntryType.TODO.value,
                'content': 'Podpisać zgodę — poprawione',
                'date': '2020-01-10',
                'time': '07:15',
                'assigned_member': '',
                'school_item': '',
            },
        )
        self.assertRedirects(response, detail, fetch_redirect_response=False)
        self.assertContains(self.client.get(detail), 'Podpisać zgodę — poprawione')

        response = self.client.post(reverse('entries:delete', args=[entry.pk]), {'start': window})
        self.assertRedirects(response, f"{reverse('entries:index')}?start={window}")
        self.assertFalse(Entry.objects.exists())

    def test_eduvulcan_entry_correction_preserves_source_then_deletes(self):
        entry = Entry.objects.create(date=timezone.localdate(),
            family=self.family,
            entry_type=EntryType.NOTE.value,
            content='Informacja ze szkoły',
            source=Entry.Source.EDUVULCAN,
        )

        self.client.post(
            reverse('entries:edit', args=[entry.pk]),
            {
                'entry_type': EntryType.CALENDAR_EVENT.value,
                'content': 'Kartkówka z biologii',
                'date': '2030-05-06',
                'time': '',
                'assigned_member': str(self.child.pk),
                'school_item': 'quiz',
                'school_subject': 'biologia',
            },
        )
        entry.refresh_from_db()
        self.assertEqual(entry.source, Entry.Source.EDUVULCAN)
        self.assertEqual(entry.school_item, 'quiz')
        self.assertEqual(entry.school_subject, 'biologia')
        self.assertContains(
            self.client.get(reverse('entries:detail', args=[entry.pk])), 'EduVulcan'
        )

        self.client.post(reverse('entries:delete', args=[entry.pk]))
        self.assertFalse(Entry.objects.exists())

    def test_capture_saved_entry_appears_in_shared_index_and_detail(self):
        entry = Entry.objects.create(date=timezone.localdate(),
            family=self.family,
            entry_type=EntryType.TODO.value,
            content='Wpis z rozpoznawania',
            created_by=self.parent,
            submission_key=uuid.uuid4(),
        )

        index = self.client.get(reverse('entries:index'))

        today = timezone.localdate().isoformat()
        self.assertContains(
            index,
            f'href="{reverse("entries:detail", args=[entry.pk])}'
            f'?start={today}"',
        )
        self.assertContains(index, 'Wpis z rozpoznawania')
