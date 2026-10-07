"""S-16 cross-family isolation matrix for the entries routes.

Ewa is a parent in "Rodzina testowa" (A) and a child in "Inna rodzina" (B).
With context A she must see and change only A's data; with context B she is
a child who reads only B entries assigned to her B membership.
"""

import uuid
from unittest import mock

from django.contrib.auth import get_user_model
from django.utils import timezone
from django.test import TestCase
from django.urls import reverse

from entries.classification.backends import BackendOutput
from entries.classification.types import EntryType
from entries.models import Entry
from family_access.context import FORM_FIELD, SESSION_KEY
from family_access.models import AutomationToken, Family, FamilyMember

A_ONLY = 'WPIS-RODZINY-A'
B_MINE = 'WPIS-B-DLA-EWY'
B_SIBLING = 'WPIS-B-DLA-KUBY'
B_FAMILY = 'WPIS-B-CALA-RODZINA'


class RecordingBackend:
    """Fake classifier that records the names it was allowed to use."""

    def __init__(self):
        self.requests = []

    def classify(self, request):
        self.requests.append(request)
        return BackendOutput(
            entry_type=EntryType.TODO, content='Kupić zeszyt', grounded=True,
        )

    def close(self):
        pass


class MixedRoleFixtureMixin:
    def setUp(self):
        super().setUp()
        self.family_a = Family.objects.create(name='Rodzina testowa')
        self.family_b = Family.objects.create(name='Inna rodzina')
        self.user = get_user_model().objects.create_user(username='ewa', email='ewa@example.test')
        self.parent_a = self.membership(self.user, self.family_a, FamilyMember.Role.PARENT, 'Ewa')
        self.child_b = self.membership(self.user, self.family_b, FamilyMember.Role.CHILD, 'Ewa')
        self.michal_a = self.member('michal', self.family_a, FamilyMember.Role.CHILD, 'Michał')
        self.tomek_b = self.member('tomek', self.family_b, FamilyMember.Role.PARENT, 'Tomek')
        self.kuba_b = self.member('kuba', self.family_b, FamilyMember.Role.CHILD, 'Kuba')
        self.entry_a = self.entry(self.family_a, A_ONLY, self.michal_a, self.parent_a)
        self.entry_b_mine = self.entry(self.family_b, B_MINE, self.child_b, self.tomek_b)
        self.entry_b_sibling = self.entry(self.family_b, B_SIBLING, self.kuba_b, self.tomek_b)
        self.entry_b_family = self.entry(self.family_b, B_FAMILY, None, self.tomek_b)
        self.client.force_login(self.user)

    def membership(self, user, family, role, display_name):
        return FamilyMember.objects.create(
            user=user, family=family, role=role, display_name=display_name,
        )

    def member(self, username, family, role, display_name):
        user = get_user_model().objects.create_user(
            username=username, email=f'{username}@example.test'
        )
        return self.membership(user, family, role, display_name)

    def entry(self, family, content, assignee, creator):
        return Entry.objects.create(
            date=timezone.localdate(),
            family=family, entry_type=EntryType.TODO.value, content=content,
            assigned_member=assignee, created_by=creator,
        )

    def use(self, family):
        session = self.client.session
        session[SESSION_KEY] = family.pk
        session.save()
        self.family = family

    def post(self, url, data=None):
        return self.client.post(url, {FORM_FIELD: str(self.family.pk), **(data or {})})

    def snapshot(self):
        return (
            sorted(Entry.objects.values_list(
                'pk', 'family_id', 'entry_type', 'content', 'date', 'assigned_member_id',
                'updated_at',
            )),
            sorted(FamilyMember.objects.values_list(
                'pk', 'family_id', 'display_name', 'role', 'is_active',
            )),
            sorted(AutomationToken.objects.values_list('pk', 'revoked_at')),
        )


class ParentContextEntriesTests(MixedRoleFixtureMixin, TestCase):
    """Context A: a parent of A who must never reach B."""

    def setUp(self):
        super().setUp()
        self.use(self.family_a)

    def test_list_shows_only_the_current_family(self):
        for view in ('upcoming', 'past'):
            with self.subTest(view):
                response = self.client.get(reverse('entries:index'), {'view': view})
                self.assertEqual(response.status_code, 200)
                for foreign in (B_MINE, B_SIBLING, B_FAMILY, 'Kuba', 'Tomek'):
                    self.assertNotContains(response, foreign)
        self.assertContains(self.client.get(reverse('entries:index')), A_ONLY)

    def test_other_family_entry_ids_are_404_without_changes(self):
        before = self.snapshot()
        for entry in (self.entry_b_mine, self.entry_b_sibling, self.entry_b_family):
            with self.subTest(entry=entry.content):
                for name in ('entries:detail', 'entries:edit'):
                    response = self.client.get(reverse(name, args=[entry.pk]))
                    self.assertEqual(response.status_code, 404)
                response = self.post(reverse('entries:edit', args=[entry.pk]), {
                    'entry_type': EntryType.NOTE.value, 'content': 'Zmienione',
                })
                self.assertEqual(response.status_code, 404)
                response = self.post(reverse('entries:delete', args=[entry.pk]))
                self.assertEqual(response.status_code, 404)
        self.assertEqual(self.snapshot(), before)

    def test_own_family_entry_is_reachable(self):
        response = self.client.get(reverse('entries:detail', args=[self.entry_a.pk]))

        self.assertContains(response, A_ONLY)

    def test_child_routes_are_forbidden_for_a_parent_context(self):
        for url in (
            reverse('entries:child_list'),
            reverse('entries:child_detail', args=[self.entry_b_mine.pk]),
        ):
            with self.subTest(url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_assignee_choices_come_only_from_the_current_family(self):
        for url in (reverse('entries:create'), reverse('entries:edit', args=[self.entry_a.pk])):
            with self.subTest(url):
                response = self.client.get(url)
                choices = dict(response.context['form'].fields['assigned_member'].choices)
                self.assertIn(self.michal_a.pk, [getattr(k, 'value', k) for k in choices])
                for foreign in (self.child_b, self.tomek_b, self.kuba_b):
                    self.assertNotIn(foreign.pk, [getattr(k, 'value', k) for k in choices])

    def test_create_with_a_member_of_another_family_writes_nothing(self):
        before = self.snapshot()

        response = self.post(reverse('entries:create'), {
            'entry_type': EntryType.NOTE.value,
            'content': 'Nowa notatka', 'date': timezone.localdate().isoformat(),
            'assigned_member': self.kuba_b.pk,
            'submission_key': str(uuid.uuid4()),
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.snapshot(), before)

    def test_classification_candidates_come_only_from_the_current_family(self):
        backend = RecordingBackend()

        with mock.patch(
            'entries.classification.openai_backend.build_openai_backend', return_value=backend
        ):
            response = self.post(reverse('entries:capture'), {'text': 'Kupić zeszyt'})

        self.assertEqual(response.status_code, 200)
        (request,) = backend.requests
        self.assertEqual(set(request.allowed_member_names), {'Ewa', 'Michał'})
        self.assertEqual(request.requester_name, 'Ewa')

    def test_confirm_with_a_member_of_another_family_writes_nothing(self):
        before = self.snapshot()

        response = self.post(reverse('entries:confirm'), {
            'entry_type': EntryType.TODO.value,
            'content': 'Kupić zeszyt', 'date': timezone.localdate().isoformat(),
            'assigned_member': self.kuba_b.pk,
            'submission_key': str(uuid.uuid4()),
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.snapshot(), before)


class ChildContextEntriesTests(MixedRoleFixtureMixin, TestCase):
    """Context B: the same person is only a child of B."""

    def setUp(self):
        super().setUp()
        self.use(self.family_b)

    def test_parent_routes_are_forbidden_and_write_nothing(self):
        before = self.snapshot()
        gets = [
            reverse('entries:index'),
            reverse('entries:capture'),
            reverse('entries:create'),
            reverse('entries:detail', args=[self.entry_b_mine.pk]),
            reverse('entries:edit', args=[self.entry_b_mine.pk]),
        ]
        posts = [
            reverse('entries:capture'),
            reverse('entries:answer'),
            reverse('entries:correct'),
            reverse('entries:confirm'),
            reverse('entries:confirm_batch'),
            reverse('entries:create'),
            reverse('entries:edit', args=[self.entry_b_mine.pk]),
            reverse('entries:delete', args=[self.entry_b_mine.pk]),
            reverse('entries:delete', args=[self.entry_a.pk]),
        ]
        data = {'text': 'Kupić zeszyt', 'entry_type': EntryType.NOTE.value,
                'content': 'Zmienione', 'submission_key': str(uuid.uuid4())}

        for url in gets:
            with self.subTest(get=url):
                self.assertEqual(self.client.get(url).status_code, 403)
        for url in posts:
            with self.subTest(post=url):
                self.assertEqual(self.post(url, data).status_code, 403)
        self.assertEqual(self.snapshot(), before)

    def test_child_list_shows_only_entries_assigned_to_this_membership(self):
        for view in ('upcoming', 'past'):
            with self.subTest(view):
                response = self.client.get(reverse('entries:child_list'), {'view': view})
                self.assertEqual(response.status_code, 200)
                for foreign in (A_ONLY, B_SIBLING, B_FAMILY):
                    self.assertNotContains(response, foreign)
        self.assertContains(self.client.get(reverse('entries:child_list')), B_MINE)

    def test_child_detail_only_for_own_assignment(self):
        own = self.client.get(reverse('entries:child_detail', args=[self.entry_b_mine.pk]))
        self.assertContains(own, B_MINE)

        for entry in (self.entry_b_sibling, self.entry_b_family, self.entry_a):
            with self.subTest(entry=entry.content):
                response = self.client.get(reverse('entries:child_detail', args=[entry.pk]))
                self.assertEqual(response.status_code, 404)

    def test_switching_back_restores_the_parent_view(self):
        self.use(self.family_a)

        response = self.client.get(reverse('entries:index'))

        self.assertContains(response, A_ONLY)
        self.assertNotContains(response, B_MINE)
