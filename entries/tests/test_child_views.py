"""S-03 child routes: list, detail, access matrix and the account entry point."""

import datetime
import re

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from entries.classification.types import EntryType, SchoolItemKind
from entries.models import Entry
from entries.services import save_confirmed_entry

from .test_classification_service import FamilyFixtureMixin

LIST_URL = reverse('entries:child_list')
FORBIDDEN_HREFS = ('/entries/new/', '/entries/confirm/', 'edit', 'delete')


def detail_url(pk):
    return reverse('entries:child_detail', args=[pk])


class ChildViewFixtureMixin(FamilyFixtureMixin):
    def setUp(self):
        super().setUp()
        today = timezone.localdate()
        self.today = today
        self.own_upcoming = self._entry(
            'SENTINEL-OWN-UPCOMING',
            self.child,
            entry_type=EntryType.CALENDAR_EVENT,
            date=today + datetime.timedelta(days=2),
            time=datetime.time(8, 0),
            school_item=SchoolItemKind.TEST.value,
        )
        self.own_undated = self._entry('SENTINEL-OWN-UNDATED', self.child)
        self.own_past = self._entry(
            'SENTINEL-OWN-PAST',
            self.child,
            entry_type=EntryType.CALENDAR_EVENT,
            date=today - datetime.timedelta(days=3),
            source=Entry.Source.EDUVULCAN,
        )
        self.unassigned = self._entry(
            'SENTINEL-UNASSIGNED', None, date=today + datetime.timedelta(days=1)
        )
        self.sibling = self._entry(
            'SENTINEL-SIBLING', self.other_child, date=today + datetime.timedelta(days=1)
        )
        self.foreign = self._entry(
            'SENTINEL-FOREIGN',
            self.other_family_child,
            family=self.other_family,
            date=today + datetime.timedelta(days=1),
        )
        self.excluded = (self.unassigned, self.sibling, self.foreign)

    def _entry(self, content, member, family=None, entry_type=EntryType.NOTE, **fields):
        return Entry.objects.create(
            family=family or self.family,
            entry_type=entry_type.value,
            content=content,
            assigned_member=member,
            **fields,
        )

    def assertNoExcludedContent(self, response):
        body = response.content.decode()
        for entry in self.excluded:
            self.assertNotIn(entry.content, body)

    def assertReadOnly(self, response):
        body = response.content.decode()
        self.assertNotIn('<form', body.split('<main', 1)[1])
        for href in re.findall(r'href="([^"]*)"', body):
            for forbidden in FORBIDDEN_HREFS:
                self.assertNotIn(forbidden, href)
        self.assertNotIn('Dodaj wpis', body)
        self.assertNotIn('Edytuj', body)
        self.assertNotIn('Usuń', body)


class ChildListTests(ChildViewFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.child.user)

    def test_default_list_shows_upcoming_then_undated(self):
        response = self.client.get(LIST_URL)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'entries/child_list.html')
        self.assertContains(response, '<h1>Moje wpisy</h1>', html=True)
        body = response.content.decode()
        self.assertLess(
            body.index('SENTINEL-OWN-UPCOMING'), body.index('SENTINEL-OWN-UNDATED')
        )
        self.assertNotContains(response, 'SENTINEL-OWN-PAST')
        self.assertContains(response, f'href="{detail_url(self.own_upcoming.pk)}"')
        self.assertRegex(body, r'href="/entries/mine/"\s+aria-current="page"')
        self.assertNoExcludedContent(response)
        self.assertReadOnly(response)
        # The child's own list hides the redundant assignee.
        self.assertNotContains(response, 'Michał</span>')

    def test_past_mode_lists_past_entries_with_mode_in_links(self):
        response = self.client.get(LIST_URL, {'view': 'past'})

        self.assertContains(response, 'SENTINEL-OWN-PAST')
        self.assertNotContains(response, 'SENTINEL-OWN-UPCOMING')
        self.assertNotContains(response, 'SENTINEL-OWN-UNDATED')
        self.assertContains(response, f'href="{detail_url(self.own_past.pk)}?view=past"')
        self.assertRegex(
            response.content.decode(), r'href="/entries/mine/\?view=past"\s+aria-current="page"'
        )
        self.assertNoExcludedContent(response)
        self.assertReadOnly(response)

    def test_unknown_view_falls_back_to_upcoming(self):
        response = self.client.get(LIST_URL, {'view': '<script>'})

        self.assertContains(response, 'SENTINEL-OWN-UPCOMING')
        self.assertNotContains(response, 'SENTINEL-OWN-PAST')
        self.assertNotContains(response, '<script>')

    def test_distinct_empty_states(self):
        Entry.objects.filter(assigned_member=self.child).delete()

        upcoming = self.client.get(LIST_URL)
        past = self.client.get(LIST_URL, {'view': 'past'})

        self.assertContains(upcoming, 'Nie masz żadnych nadchodzących wpisów.')
        self.assertContains(upcoming, 'data-empty-state="upcoming"')
        self.assertContains(past, 'Nie masz żadnych minionych wpisów.')
        self.assertContains(past, 'data-empty-state="past"')

    def test_parent_captured_entry_assigned_to_child_appears(self):
        save_confirmed_entry(
            self.parent.user,
            entry_type=EntryType.TODO.value,
            content='SENTINEL-FROM-PARENT',
            date=self.today,
            time=None,
            assigned_member=self.child,
            school_item='',
            submission_key='00000000-0000-4000-8000-000000000001',
        )

        self.assertContains(self.client.get(LIST_URL), 'SENTINEL-FROM-PARENT')

    def test_non_get_methods_are_not_allowed(self):
        for method in ('post', 'put', 'patch', 'delete'):
            with self.subTest(method=method):
                self.assertEqual(getattr(self.client, method)(LIST_URL).status_code, 405)
                self.assertEqual(
                    getattr(self.client, method)(detail_url(self.own_upcoming.pk)).status_code,
                    405,
                )


class ChildDetailTests(ChildViewFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.child.user)

    def test_detail_shows_full_data_without_internal_fields(self):
        self.own_upcoming.content = 'SENTINEL-OWN-UPCOMING ' + 'długa treść ' * 30
        self.own_upcoming.save()

        response = self.client.get(detail_url(self.own_upcoming.pk))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'entries/child_detail.html')
        self.assertContains(response, self.own_upcoming.content.strip())
        self.assertContains(response, 'Wydarzenie')
        self.assertContains(response, '08:00')
        self.assertContains(response, SchoolItemKind.TEST.label)
        self.assertContains(response, 'Ręcznie')
        for hidden in ('Dodane przez', 'Ewa', 'submission', 'utworzono', 'zmieniono'):
            self.assertNotContains(response, hidden)
        self.assertContains(response, f'href="{LIST_URL}" data-back-link')
        self.assertNoExcludedContent(response)
        self.assertReadOnly(response)

    def test_eduvulcan_source_and_past_back_link(self):
        response = self.client.get(detail_url(self.own_past.pk), {'view': 'past'})

        self.assertContains(response, 'EduVulcan')
        self.assertContains(response, f'href="{LIST_URL}?view=past" data-back-link')

    def test_back_link_only_carries_allowlisted_mode(self):
        response = self.client.get(
            detail_url(self.own_past.pk), {'view': 'past"><script>x</script>'}
        )

        self.assertContains(response, f'href="{LIST_URL}" data-back-link')
        self.assertNotContains(response, '<script>x')

    def test_undated_entry_shows_no_date(self):
        response = self.client.get(detail_url(self.own_undated.pk))

        self.assertContains(response, 'Bez daty')
        self.assertNotContains(response, 'Godzina')

    def test_excluded_and_missing_ids_return_identical_404(self):
        missing_pk = Entry.objects.order_by('-pk').first().pk + 100
        responses = {
            'unassigned': self.client.get(detail_url(self.unassigned.pk)),
            'sibling': self.client.get(detail_url(self.sibling.pk)),
            'foreign': self.client.get(detail_url(self.foreign.pk)),
            'missing': self.client.get(detail_url(missing_pk)),
        }
        bodies = set()
        for name, response in responses.items():
            with self.subTest(name):
                self.assertEqual(response.status_code, 404)
                self.assertNoExcludedContent(response)
                bodies.add(response.content)
        self.assertEqual(len(bodies), 1)

    def test_lucky_number_detail_still_resolves(self):
        lucky = self._entry(
            'SENTINEL-LUCKY', self.child, school_item=SchoolItemKind.LUCKY_NUMBER.value
        )

        self.assertEqual(self.client.get(detail_url(lucky.pk)).status_code, 200)
        self.assertNotContains(self.client.get(LIST_URL), 'SENTINEL-LUCKY')


class ChildAccessMatrixTests(ChildViewFixtureMixin, TestCase):
    def test_anonymous_is_redirected_to_login(self):
        for url in (LIST_URL, detail_url(self.own_upcoming.pk)):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse('account_login'), response['Location'])

    def test_non_children_are_forbidden(self):
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
        }
        for name, get_user in cases.items():
            for url in (LIST_URL, detail_url(self.own_upcoming.pk)):
                with self.subTest(name, url=url):
                    self.client.force_login(get_user())
                    response = self.client.get(url)
                    self.assertEqual(response.status_code, 403)
                    self.assertNotContains(response, 'SENTINEL', status_code=403)
            self.family.is_active = True
            self.family.save(update_fields=['is_active'])


class AccountEntryPointTests(FamilyFixtureMixin, TestCase):
    ACCOUNT_URL = reverse('account_status')

    def test_child_sees_my_entries_and_not_capture(self):
        self.client.force_login(self.child.user)

        response = self.client.get(self.ACCOUNT_URL)

        self.assertContains(response, 'Moje wpisy')
        self.assertContains(response, f'href="{LIST_URL}"')
        self.assertNotContains(response, 'Dodaj wpis')

    def test_parent_sees_capture_and_not_my_entries(self):
        self.client.force_login(self.parent.user)

        response = self.client.get(self.ACCOUNT_URL)

        self.assertContains(response, 'Dodaj wpis')
        self.assertNotContains(response, 'Moje wpisy')
        self.assertNotContains(response, f'href="{LIST_URL}"')
