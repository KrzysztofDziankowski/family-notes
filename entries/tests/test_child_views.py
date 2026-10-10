"""S-03 child routes: calendar, detail, access matrix and the account entry point."""

import datetime
import re
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from entries.classification.types import EntryType, SchoolItemKind
from entries.listing import parent_day_heading
from entries.models import Entry
from entries.services import save_confirmed_entry

from .test_classification_service import FamilyFixtureMixin, TwoParentFixtureMixin
from .test_manage_views import DAY_PATTERN, ROW_PATTERN, day_html

LIST_URL = reverse('entries:child_list')
PARENT_LIST_URL = reverse('entries:index')
FIXED_TODAY = datetime.date(2026, 9, 28)  # a Monday
HEADING_PATTERN = re.compile(r'<h2 class="fn-day-heading"[^>]*>([^<]*)</h2>')
NAV_LINK_PATTERN = re.compile(r'<a href="([^"]*)"( aria-current="page")?>([^<]*)</a>')
FORBIDDEN_HREFS = ('/entries/new/', '/entries/confirm/', 'edit', 'delete')
DAY = datetime.timedelta(days=1)


def detail_url(pk):
    return reverse('entries:child_detail', args=[pk])


def days(offset):
    return FIXED_TODAY + offset * DAY


def window(offset):
    return {'start': days(offset).isoformat()}


def nav_html(html):
    start = html.index('<nav class="fn-calendar-nav"')
    return html[start:html.index('</nav>', start)]


class ChildViewFixtureMixin(FamilyFixtureMixin):
    """Fixture rows around a fixed ``timezone.localdate`` (Monday 2026-09-28)."""

    def setUp(self):
        super().setUp()
        patcher = mock.patch('entries.views.timezone.localdate', return_value=FIXED_TODAY)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.today = FIXED_TODAY
        self.own_upcoming = self._entry(
            'SENTINEL-OWN-UPCOMING',
            self.child,
            entry_type=EntryType.CALENDAR_EVENT,
            date=days(2),
            time=datetime.time(8, 0),
            school_item=SchoolItemKind.TEST.value,
        )
        self.own_later = self._entry('SENTINEL-OWN-LATER', self.child)
        self.own_past = self._entry(
            'SENTINEL-OWN-PAST',
            self.child,
            entry_type=EntryType.CALENDAR_EVENT,
            date=days(-3),
            source=Entry.Source.EDUVULCAN,
        )
        self.unassigned = self._entry('SENTINEL-UNASSIGNED', None, date=days(1))
        self.sibling = self._entry('SENTINEL-SIBLING', self.other_child, date=days(1))
        self.foreign = self._entry(
            'SENTINEL-FOREIGN',
            self.other_family_child,
            family=self.other_family,
            date=days(1),
        )
        self.excluded = (self.unassigned, self.sibling, self.foreign)

    def _entry(self, content, member, family=None, entry_type=EntryType.NOTE, **fields):
        fields.setdefault('date', days(10))
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

    def rows(self, html, offset):
        return [int(pk) for pk in ROW_PATTERN.findall(day_html(html, days(offset).isoformat()))]

    def test_default_window_is_fourteen_days_from_today_with_full_headings(self):
        response = self.client.get(LIST_URL)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'entries/child_list.html')
        self.assertContains(response, '<h1>Moje wpisy</h1>', html=True)
        html = response.content.decode()
        self.assertEqual(DAY_PATTERN.findall(html), [days(n).isoformat() for n in range(14)])
        self.assertEqual(
            HEADING_PATTERN.findall(html), [parent_day_heading(days(n), FIXED_TODAY) for n in range(14)]
        )
        self.assertEqual(HEADING_PATTERN.findall(html)[0], 'Dziś, poniedziałek 28 września')
        self.assertEqual(self.rows(html, 2), [self.own_upcoming.pk])
        self.assertEqual(self.rows(html, 10), [self.own_later.pk])
        self.assertNotContains(response, 'SENTINEL-OWN-PAST')
        # Every day without an own entry is an empty box.
        self.assertEqual(html.count('>Brak wpisów</p>'), 12)
        self.assertEqual(html.count('fn-calendar-day--empty'), 12)
        self.assertIn('>Brak wpisów</p>', day_html(html, days(1).isoformat()))
        self.assertIn(f'<section class="fn-calendar-day" data-day-group="{days(2).isoformat()}"', html)
        self.assertIn(
            f'<section class="fn-calendar-day fn-calendar-day--empty" data-day-group="{days(1).isoformat()}"',
            html,
        )
        self.assertNotIn('Brak wpisów', day_html(html, days(2).isoformat()))

    def test_only_own_entries_without_assignee_subheadings(self):
        response = self.client.get(LIST_URL)

        html = response.content.decode()
        self.assertNoExcludedContent(response)
        self.assertReadOnly(response)
        self.assertNotIn('<h3', html)
        self.assertNotIn('data-assignee-group', html)
        self.assertNotIn('Ogólne', html)
        # The child's own calendar hides the redundant assignee and the type.
        self.assertNotContains(response, 'Michał</span>')
        self.assertNotContains(response, 'fn-entry-type')
        self.assertNotContains(response, 'fn-tabs')

    def test_lucky_number_appears_on_its_day(self):
        lucky = self._entry(
            'SENTINEL-LUCKY', self.child, date=days(4),
            school_item=SchoolItemKind.LUCKY_NUMBER.value, source=Entry.Source.EDUVULCAN,
        )

        html = self.client.get(LIST_URL).content.decode()

        self.assertEqual(self.rows(html, 4), [lucky.pk])
        self.assertIn('SENTINEL-LUCKY', day_html(html, days(4).isoformat()))
        # The parent calendar keeps hiding lucky numbers.
        self.client.force_login(self.parent.user)
        self.assertNotContains(self.client.get(PARENT_LIST_URL), 'SENTINEL-LUCKY')

    def test_navigation_links_today_earlier_and_next_windows(self):
        today = self.client.get(LIST_URL).content.decode()
        earlier = self.client.get(LIST_URL, window(-14)).content.decode()

        self.assertIn('aria-label="Nawigacja kalendarza"', today)
        self.assertEqual(
            NAV_LINK_PATTERN.findall(nav_html(today)),
            [
                (f'{LIST_URL}?start={days(-14).isoformat()}', '', 'Wcześniejsze'),
                (f'{LIST_URL}?start={days(0).isoformat()}', ' aria-current="page"', 'Dzisiaj'),
                (f'{LIST_URL}?start={days(14).isoformat()}', '', 'Następne'),
            ],
        )
        self.assertEqual(
            NAV_LINK_PATTERN.findall(nav_html(earlier)),
            [
                (f'{LIST_URL}?start={days(-28).isoformat()}', '', 'Wcześniejsze'),
                (f'{LIST_URL}?start={days(0).isoformat()}', '', 'Dzisiaj'),
                (f'{LIST_URL}?start={days(0).isoformat()}', '', 'Następne'),
            ],
        )
        self.assertEqual(DAY_PATTERN.findall(earlier), [days(n).isoformat() for n in range(-14, 0)])
        self.assertEqual(self.rows(earlier, -3), [self.own_past.pk])
        self.assertNotIn('SENTINEL-OWN-UPCOMING', earlier)
        self.assertNotIn('role="group"', today)
        self.assertNotIn('role="button"', today)

    def test_next_window_and_windows_crossing_today(self):
        far = self._entry('SENTINEL-FAR', self.child, date=days(20))

        later = self.client.get(LIST_URL, window(14)).content.decode()
        crossing = self.client.get(LIST_URL, window(-7)).content.decode()

        self.assertEqual(DAY_PATTERN.findall(later)[0], days(14).isoformat())
        self.assertEqual(self.rows(later, 20), [far.pk])
        self.assertEqual(DAY_PATTERN.findall(crossing), [days(n).isoformat() for n in range(-7, 7)])
        self.assertEqual(self.rows(crossing, -3), [self.own_past.pk])
        self.assertEqual(self.rows(crossing, 2), [self.own_upcoming.pk])

    def test_entry_links_carry_the_window_start(self):
        today = self.client.get(LIST_URL)
        earlier = self.client.get(LIST_URL, window(-14))

        self.assertContains(
            today, f'href="{detail_url(self.own_upcoming.pk)}?start={days(0).isoformat()}"'
        )
        self.assertContains(
            earlier, f'href="{detail_url(self.own_past.pk)}?start={days(-14).isoformat()}"'
        )

    def test_invalid_start_and_legacy_view_fall_back_to_today(self):
        for params in (
            {'start': '<script>'},
            {'start': '2026-9-1'},
            {'start': '0001-01-01'},
            {'view': 'past'},
        ):
            with self.subTest(params=params):
                response = self.client.get(LIST_URL, params)
                html = response.content.decode()
                self.assertEqual(DAY_PATTERN.findall(html)[0], days(0).isoformat())
                self.assertNotContains(response, '<script>')
                self.assertNotContains(response, 'SENTINEL-OWN-PAST')

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
    """Day boxes, their labelled lists and the weekend marker."""

    def setUp(self):
        super().setUp()
        Entry.objects.filter(assigned_member=self.child).delete()
        self.today_timed = self._entry(
            'SENTINEL-TODAY', self.child, date=FIXED_TODAY, time=datetime.time(8, 15)
        )
        self.today_untimed = self._entry('SENTINEL-TODAY-UNTIMED', self.child, date=FIXED_TODAY)
        self.today_early = self._entry(
            'SENTINEL-TODAY-EARLY', self.child, date=FIXED_TODAY, time=datetime.time(7, 0)
        )
        self.tomorrow_untimed = self._entry('SENTINEL-TOMORROW', self.child, date=days(1))
        self.later = self._entry('SENTINEL-LATER', self.child, date=days(7))
        self.yesterday = self._entry(
            'SENTINEL-YESTERDAY', self.child, date=days(-1), time=datetime.time(9, 0)
        )
        self.client.force_login(self.child.user)

    def test_rows_sit_under_their_day_in_time_order_showing_only_the_time(self):
        response = self.client.get(LIST_URL)
        html = response.content.decode()

        today = day_html(html, FIXED_TODAY.isoformat())
        self.assertEqual(
            [int(pk) for pk in ROW_PATTERN.findall(today)],
            [self.today_early.pk, self.today_timed.pk, self.today_untimed.pk],
        )
        order = [
            html.index(marker)
            for marker in ('>Dziś, poniedziałek 28 września<', 'SENTINEL-TODAY',
                           '>Jutro, wtorek 29 września<', 'SENTINEL-TOMORROW',
                           '>Poniedziałek, 5 października<', 'SENTINEL-LATER')
        ]
        self.assertEqual(order, sorted(order))
        self.assertContains(response, '<span>08:15</span>', html=True)
        self.assertNotIn('września', HEADING_PATTERN.sub('', html))
        self.assertNotContains(response, 'SENTINEL-YESTERDAY')

    def test_each_day_has_one_list_labelled_by_its_heading(self):
        for params, offsets in (({}, range(14)), (window(-14), range(-14, 0))):
            with self.subTest(params=params):
                html = self.client.get(LIST_URL, params).content.decode()
                ids = re.findall(r'<h2 class="fn-day-heading" id="([^"]+)"', html)
                self.assertEqual(ids, [f'day-{days(n).isoformat()}' for n in offsets])
                labelled = re.findall(r'<ul [^>]*aria-labelledby="([^"]+)"', html)
                with_rows = [
                    f'day-{key}' for key in DAY_PATTERN.findall(html)
                    if 'data-entry-row' in day_html(html, key)
                ]
                self.assertEqual(labelled, with_rows)
                self.assertEqual(len(ids), len(set(ids)))
                self.assertNotIn('<ul class="fn-entry-list" aria-label=', html)

    def test_only_weekend_boxes_carry_the_weekend_marker_in_both_views(self):
        weekend = [days(n).isoformat() for n in (5, 6, 12, 13)]  # 3-4 and 10-11 October
        for user, url in ((self.child.user, LIST_URL), (self.parent.user, PARENT_LIST_URL)):
            with self.subTest(url=url):
                self.client.force_login(user)
                html = self.client.get(url).content.decode()
                self.assertEqual(
                    re.findall(r'data-day-group="([\w-]+)" data-weekend>', html), weekend
                )
                self.assertEqual(html.count('data-weekend'), len(weekend))

    def test_parent_list_uses_the_same_full_calendar_day_headings(self):
        # Owner request 2026-10-10 (child-calendar-view): the child shows the same
        # 14-day calendar as the parent, with the same full headings.
        Entry.objects.exclude(assigned_member=self.child).delete()
        self.client.force_login(self.parent.user)

        response = self.client.get(PARENT_LIST_URL)
        past = self.client.get(PARENT_LIST_URL, window(-14))

        self.assertEqual(
            HEADING_PATTERN.findall(response.content.decode()),
            [parent_day_heading(days(n), FIXED_TODAY) for n in range(14)],
        )
        self.assertEqual(
            HEADING_PATTERN.findall(past.content.decode()),
            [parent_day_heading(days(n), FIXED_TODAY) for n in range(-14, 0)],
        )
        self.assertEqual(
            HEADING_PATTERN.findall(past.content.decode())[-1], 'Wczoraj, niedziela 27 września'
        )
        self.client.force_login(self.child.user)
        self.assertEqual(
            HEADING_PATTERN.findall(self.client.get(LIST_URL).content.decode()),
            HEADING_PATTERN.findall(response.content.decode()),
        )


class ChildDetailTests(ChildViewFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.child.user)

    def back_link(self, start):
        return f'href="{LIST_URL}?start={start.isoformat()}" data-back-link'

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
        self.assertContains(response, self.back_link(days(0)))
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

    def test_back_link_returns_to_the_window_the_entry_was_opened_from(self):
        response = self.client.get(detail_url(self.own_past.pk), window(-7))

        self.assertContains(response, 'EduVulcan')
        self.assertContains(response, self.back_link(days(-7)))

    def test_back_link_without_start_returns_to_the_window_containing_the_entry(self):
        far = self._entry('SENTINEL-FAR', self.child, date=days(20))
        long_ago = self._entry('SENTINEL-LONG-AGO', self.child, date=days(-15))
        for entry, start in (
            (self.own_upcoming, days(0)),
            (self.own_later, days(0)),
            (self.own_past, days(-14)),
            (far, days(14)),
            (long_ago, days(-28)),
        ):
            with self.subTest(entry=entry.content):
                self.assertContains(self.client.get(detail_url(entry.pk)), self.back_link(start))

    def test_invalid_start_falls_back_to_today(self):
        for value in ('"><script>x</script>', '2026-9-1', '9999-12-31'):
            with self.subTest(value=value):
                response = self.client.get(detail_url(self.own_past.pk), {'start': value})
                self.assertContains(response, self.back_link(days(0)))
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

    def test_lucky_number_detail_resolves_and_returns_to_its_window(self):
        lucky = self._entry(
            'SENTINEL-LUCKY', self.child, school_item=SchoolItemKind.LUCKY_NUMBER.value
        )

        response = self.client.get(detail_url(lucky.pk))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.back_link(days(0)))
        self.assertContains(self.client.get(LIST_URL), 'SENTINEL-LUCKY')


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
        tomorrow = days(1)
        self.for_author = self._entry('SENTINEL-PARENT-AUTHOR', self.parent, date=tomorrow)
        self.for_other_parent = self._entry('SENTINEL-PARENT-OTHER', self.second_parent)
        self.parent_entries = (self.for_author, self.for_other_parent)

    def test_no_child_lists_a_parent_assigned_entry(self):
        for child in (self.child, self.other_child):
            for params in ({}, window(-14), window(14)):
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
