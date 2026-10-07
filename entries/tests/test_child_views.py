"""S-03 child routes: list, detail, access matrix and the account entry point."""

import datetime
import re
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from entries.classification.types import EntryType, SchoolItemKind
from entries.models import Entry
from entries.services import save_confirmed_entry

from .test_classification_service import FamilyFixtureMixin, TwoParentFixtureMixin

LIST_URL = reverse('entries:child_list')
PARENT_LIST_URL = reverse('entries:index')
FIXED_TODAY = datetime.date(2026, 9, 28)  # a Monday
HEADING_PATTERN = re.compile(r'<h2 class="fn-day-heading">([^<]*)</h2>')
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
        self.own_later = self._entry('SENTINEL-OWN-LATER', self.child)
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
        fields.setdefault('date', self.today + datetime.timedelta(days=10))
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

    def assertModeSwitch(self, response, current):
        """The shared tab switch: both modes linked, only ``current`` marked as the page."""
        body = response.content.decode()
        self.assertNotIn('role="group"', body)
        self.assertNotIn('role="button"', body)
        self.assertIn('<nav class="fn-tabs" aria-label="Rodzaj listy"', body)
        links = re.findall(r'<a href="(/entries/mine/[^"]*)"( aria-current="page")?>', body)
        self.assertEqual(
            [href for href, _ in links], ['/entries/mine/', '/entries/mine/?view=past']
        )
        self.assertEqual([href for href, marker in links if marker], [current])

    def test_default_list_shows_upcoming_in_date_order(self):
        response = self.client.get(LIST_URL)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'entries/child_list.html')
        self.assertContains(response, '<h1>Moje wpisy</h1>', html=True)
        body = response.content.decode()
        self.assertLess(
            body.index('SENTINEL-OWN-UPCOMING'), body.index('SENTINEL-OWN-LATER')
        )
        self.assertNotContains(response, 'SENTINEL-OWN-PAST')
        self.assertContains(response, f'href="{detail_url(self.own_upcoming.pk)}"')
        self.assertRegex(body, r'href="/entries/mine/"\s+aria-current="page"')
        self.assertModeSwitch(response, current='/entries/mine/')
        self.assertNoExcludedContent(response)
        self.assertReadOnly(response)
        # The child's own list hides the redundant assignee.
        self.assertNotContains(response, 'Michał</span>')
        self.assertNotContains(response, 'fn-entry-type')

    def test_past_mode_lists_past_entries_with_mode_in_links(self):
        response = self.client.get(LIST_URL, {'view': 'past'})

        self.assertContains(response, 'SENTINEL-OWN-PAST')
        self.assertNotContains(response, 'fn-entry-type')
        self.assertNotContains(response, 'SENTINEL-OWN-UPCOMING')
        self.assertNotContains(response, 'SENTINEL-OWN-LATER')
        self.assertContains(response, f'href="{detail_url(self.own_past.pk)}?view=past"')
        self.assertRegex(
            response.content.decode(), r'href="/entries/mine/\?view=past"\s+aria-current="page"'
        )
        self.assertModeSwitch(response, current='/entries/mine/?view=past')
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
        for response, mode in ((upcoming, 'upcoming'), (past, 'past')):
            with self.subTest(mode=mode):
                self.assertContains(
                    response, f'<p class="fn-empty fn-muted" data-empty-state="{mode}">'
                )
                self.assertNotContains(response, 'class="fn-panel"')

    def test_parent_captured_entry_assigned_to_child_appears(self):
        save_confirmed_entry(
            self.parent,
            entry_type=EntryType.TODO.value,
            content='SENTINEL-FROM-PARENT',
            date=self.today,
            time=None,
            assigned_member=self.child,
            school_item='',
            school_subject='',
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


class ChildDayHeadingTests(ChildViewFixtureMixin, TestCase):
    """Day groups under relative headings, with ``timezone.localdate`` fixed."""

    def setUp(self):
        super().setUp()
        Entry.objects.filter(assigned_member=self.child).delete()
        day = datetime.timedelta(days=1)
        self.today_timed = self._entry(
            'SENTINEL-TODAY', self.child, date=FIXED_TODAY, time=datetime.time(8, 15)
        )
        self.tomorrow_untimed = self._entry(
            'SENTINEL-TOMORROW', self.child, date=FIXED_TODAY + day
        )
        self.later = self._entry('SENTINEL-LATER', self.child, date=FIXED_TODAY + 7 * day)
        self.yesterday = self._entry(
            'SENTINEL-YESTERDAY', self.child, date=FIXED_TODAY - day, time=datetime.time(9, 0)
        )
        self.older = self._entry(
            'SENTINEL-OLDER', self.child, date=FIXED_TODAY - 10 * day
        )
        patcher = mock.patch('entries.views.timezone.localdate', return_value=FIXED_TODAY)
        patcher.start()
        self.addCleanup(patcher.stop)

    def headings(self, response):
        return HEADING_PATTERN.findall(response.content.decode())

    def test_upcoming_groups_all_dates_under_relative_headings(self):
        self.client.force_login(self.child.user)

        response = self.client.get(LIST_URL)

        self.assertEqual(self.headings(response), ['Dziś', 'Jutro', 'Poniedziałek, 5 października'])
        body = response.content.decode()
        order = [
            body.index(marker)
            for marker in ('>Dziś<', 'SENTINEL-TODAY', '>Jutro<', 'SENTINEL-TOMORROW',
                           '>Poniedziałek, 5 października<', 'SENTINEL-LATER')
        ]
        self.assertEqual(order, sorted(order))
        self.assertEqual(
            re.findall(r'data-entry-section="(\w+)"', body), ['dated', 'dated', 'dated']
        )
        # Rows under a day heading show only the time, never the date.
        self.assertContains(response, '<span>08:15</span>', html=True)
        self.assertNotContains(response, 'września')

    def test_past_reads_newest_day_first(self):
        self.client.force_login(self.child.user)

        response = self.client.get(LIST_URL, {'view': 'past'})

        self.assertEqual(
            self.headings(response), ['Wczoraj', 'Piątek, 18 września']
        )
        body = response.content.decode()
        self.assertLess(body.index('SENTINEL-YESTERDAY'), body.index('SENTINEL-OLDER'))
        self.assertContains(response, '<span>09:00</span>', html=True)
        self.assertNotContains(response, 'Bez daty')

    def test_parent_list_uses_the_same_day_headings(self):
        # Owner request 2026-10-05 (S-08): the parent list groups by day like
        # the child view, so its rows also show only the time. Only this
        # class's fixed-date rows stay, so the headings are deterministic.
        Entry.objects.exclude(assigned_member=self.child).delete()
        self.client.force_login(self.parent.user)

        response = self.client.get(PARENT_LIST_URL)
        past = self.client.get(PARENT_LIST_URL, {'view': 'past'})

        self.assertEqual(self.headings(response), ['Dziś', 'Jutro', 'Poniedziałek, 5 października'])
        self.assertEqual(self.headings(past), ['Wczoraj', 'Piątek, 18 września'])
        self.assertContains(response, '<span>08:15</span>', html=True)
        self.assertNotContains(response, 'września')


class ChildDetailTests(ChildViewFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.child.user)

    def test_entry_content_is_escaped_in_list_and_detail(self):
        entry = self._entry('<script>alert(1)</script>', self.child)

        for response in (self.client.get(LIST_URL), self.client.get(detail_url(entry.pk))):
            with self.subTest(path=response.request['PATH_INFO']):
                self.assertNotContains(response, '<script>alert(1)</script>')
                self.assertContains(response, '&lt;script&gt;alert(1)&lt;/script&gt;')

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

    def test_detail_shows_subject_read_only_only_when_set(self):
        without = self.client.get(detail_url(self.own_upcoming.pk))
        self.assertNotContains(without, 'Przedmiot')

        self.own_upcoming.school_subject = 'Matematyka'
        self.own_upcoming.save(update_fields=('school_subject',))
        response = self.client.get(detail_url(self.own_upcoming.pk))

        self.assertContains(response, '<dt>Przedmiot</dt>', html=True)
        self.assertContains(response, '<dd>Matematyka</dd>', html=True)
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

    def test_note_shows_writing_date_without_time(self):
        response = self.client.get(detail_url(self.own_later.pk))

        self.assertNotContains(response, 'Bez daty')
        self.assertContains(response, 'Data')
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


class TwoParentChildIsolationTests(TwoParentFixtureMixin, ChildViewFixtureMixin, TestCase):
    """S-07: an entry assigned to either parent never reaches any child."""

    def setUp(self):
        super().setUp()
        tomorrow = self.today + datetime.timedelta(days=1)
        self.for_author = self._entry('SENTINEL-PARENT-AUTHOR', self.parent, date=tomorrow)
        self.for_other_parent = self._entry('SENTINEL-PARENT-OTHER', self.second_parent)
        self.parent_entries = (self.for_author, self.for_other_parent)

    def test_no_child_lists_a_parent_assigned_entry(self):
        for child in (self.child, self.other_child):
            for params in ({}, {'view': 'past'}):
                with self.subTest(child=child.display_name, params=params):
                    self.client.force_login(child.user)
                    response = self.client.get(LIST_URL, params)
                    self.assertEqual(response.status_code, 200)
                    self.assertNotContains(response, 'SENTINEL-PARENT')

    def test_parent_assigned_detail_is_the_missing_id_404_for_every_child(self):
        missing_pk = Entry.objects.order_by('-pk').first().pk + 100
        for child in (self.child, self.other_child):
            with self.subTest(child=child.display_name):
                self.client.force_login(child.user)
                bodies = set()
                for pk in (*(entry.pk for entry in self.parent_entries), missing_pk):
                    response = self.client.get(detail_url(pk))
                    self.assertEqual(response.status_code, 404)
                    self.assertNotContains(response, 'SENTINEL-PARENT', status_code=404)
                    bodies.add(response.content)
                self.assertEqual(len(bodies), 1)

    def test_anonymous_is_redirected_from_a_parent_assigned_detail(self):
        for entry in self.parent_entries:
            with self.subTest(entry=entry.content):
                response = self.client.get(detail_url(entry.pk))
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse('account_login'), response['Location'])
