"""Parent family entry management views (S-02): routes, index wiring, CRUD and redirects.

The effective-date, heading and grouping helpers themselves are covered by
``test_entry_listing``; these tests prove the index renders them through the shared contract.
"""

import datetime
import re
import uuid

from django.contrib.messages import constants
from django.contrib.messages.storage.base import Message
from django.db import connection
from django.template.loader import render_to_string
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from entries.classification.types import EntryType, SchoolItemKind
from entries.listing import parent_day_heading
from entries.models import Entry
from family_access.models import FamilyMember

from .test_classification_service import FamilyFixtureMixin, TwoParentFixtureMixin

INDEX_URL = reverse('entries:index')
CREATE_URL = reverse('entries:create')
FOREIGN_SENTINEL = 'SENTINEL-OBCA-RODZINA-4b2d'
ROW_PATTERN = re.compile(r'data-entry-row="(\d+)"')
DAY_PATTERN = re.compile(r'data-day-group="([\w-]+)"')
GROUP_PATTERN = re.compile(r'data-assignee-group="([\w-]+)"')
DAY_HEADING_PATTERN = re.compile(r'<h2 class="fn-day-heading">([^<]*)</h2>')
# A visible "Brak wpisów" (it is always rendered, ``hidden`` while the day shows a group).
EMPTY_DAY = 'data-day-empty>Brak wpisów</p>'
GROUP_HEADING_PATTERN = re.compile(r'<h3 class="fn-manage-subsection-title">([^<]*)</h3>')


def _block(html, marker, start):
    end = html.find(marker, start + 1)
    return html[start:end if end != -1 else len(html)]


def day_html(html, key):
    """The rendered ``data-day-group`` block with ``key`` (ISO date or "undated")."""
    return _block(html, 'data-day-group="', html.index(f'data-day-group="{key}"'))


def group_html(day, key):
    """The ``data-assignee-group`` block with ``key`` inside one day's block."""
    return _block(day, 'data-assignee-group="', day.index(f'data-assignee-group="{key}"'))


def group_heading(day, key):
    return GROUP_HEADING_PATTERN.search(group_html(day, key)).group(1)


def detail_url(pk):
    return reverse('entries:detail', args=[pk])


def edit_url(pk):
    return reverse('entries:edit', args=[pk])


def delete_url(pk):
    return reverse('entries:delete', args=[pk])


class ManageViewMixin(FamilyFixtureMixin):
    def setUp(self):
        super().setUp()
        self.today = timezone.localdate()
        self.client.force_login(self.parent.user)

    def entry(self, content='Wpis', family=None, **fields):
        values = dict(
            family=family or self.family,
            date=self.days(10),
            entry_type=EntryType.TODO.value,
            content=content,
            created_by=self.parent,
        )
        values.update(fields)
        return Entry.objects.create(**values)

    def days(self, offset):
        return self.today + datetime.timedelta(days=offset)

    def earlier(self):
        """Query of the "Wcześniejsze" window from the default one: today-14..today-1."""
        return {'start': self.days(-14).isoformat()}

    def rendered_rows(self, response):
        return [int(pk) for pk in ROW_PATTERN.findall(response.content.decode())]

    def form_data(self, **overrides):
        data = {
            'entry_type': EntryType.CALENDAR_EVENT.value,
            'content': 'Zebranie z wychowawcą',
            'date': self.days(3).isoformat(),
            'time': '17:30',
            'assigned_member': str(self.child.pk),
            'school_item': '',
            'school_subject': '',
        }
        data.update(overrides)
        return data


class RouteTests(ManageViewMixin, TestCase):
    """2.1: every management route responds and delete is POST-only."""

    def test_get_routes_render_for_parent(self):
        entry = self.entry()
        cases = {
            'index': (INDEX_URL, 'entries/manage_index.html'),
            'create': (CREATE_URL, 'entries/manage_form.html'),
            'detail': (detail_url(entry.pk), 'entries/manage_detail.html'),
            'edit': (edit_url(entry.pk), 'entries/manage_form.html'),
        }
        for name, (url, template) in cases.items():
            with self.subTest(route=name):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, template)

    def test_delete_is_post_only(self):
        entry = self.entry()

        response = self.client.get(delete_url(entry.pk))

        self.assertEqual(response.status_code, 405)
        self.assertTrue(Entry.objects.filter(pk=entry.pk).exists())

    def test_read_only_routes_reject_post(self):
        entry = self.entry()
        for url in (INDEX_URL, detail_url(entry.pk)):
            with self.subTest(url=url):
                self.assertEqual(self.client.post(url).status_code, 405)

    def test_child_is_forbidden_and_anonymous_is_redirected_to_login(self):
        self.client.force_login(self.child.user)
        self.assertEqual(self.client.get(INDEX_URL).status_code, 403)

        self.client.logout()
        response = self.client.get(INDEX_URL)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('account_login'), response['Location'])


class IndexOrderingTests(ManageViewMixin, TestCase):
    """2.2: the index renders the shared partition with exact boundaries and order."""

    def setUp(self):
        super().setUp()
        e = self.entry
        self.today_late = e('Dziś wieczorem', date=self.today, time=datetime.time(19, 0))
        self.today_untimed = e('Dziś bez godziny', date=self.today)
        self.today_early = e('Dziś rano', date=self.today, time=datetime.time(7, 30))
        self.tomorrow = e('Jutro', date=self.days(1), time=datetime.time(8, 0))
        self.next_week = e('Za tydzień', date=self.days(7))
        self.later_old = e('Późniejszy starszy')
        self.later_new = e('Późniejszy nowszy')
        Entry.objects.filter(pk=self.later_old.pk).update(
            updated_at=timezone.now() - datetime.timedelta(days=2)
        )
        self.yesterday_untimed = e('Wczoraj bez godziny', date=self.days(-1))
        self.yesterday_noon = e('Wczoraj w południe', date=self.days(-1), time=datetime.time(12))
        self.last_month = e('Miesiąc temu', date=self.days(-30), time=datetime.time(9))
        self.lucky = e(
            'Szczęśliwy numerek',
            date=self.today,
            entry_type=EntryType.NOTE.value,
            school_item=SchoolItemKind.LUCKY_NUMBER.value,
        )
        self.foreign = e(FOREIGN_SENTINEL, family=self.other_family, date=self.today)

    def test_default_window_orders_entries_in_exact_order(self):
        response = self.client.get(INDEX_URL)

        self.assertEqual(
            self.rendered_rows(response),
            [
                self.today_early.pk,
                self.today_late.pk,
                self.today_untimed.pk,
                self.tomorrow.pk,
                self.next_week.pk,
                self.later_old.pk,
                self.later_new.pk,
            ],
        )
        self.assertEqual(
            DAY_PATTERN.findall(response.content.decode()),
            [self.days(offset).isoformat() for offset in range(14)],
        )
        self.assertContains(response, 'aria-current="page">Dzisiaj<')

    def test_earlier_window_lists_the_previous_fortnight_in_exact_order(self):
        response = self.client.get(INDEX_URL, self.earlier())

        self.assertEqual(
            self.rendered_rows(response),
            [self.yesterday_noon.pk, self.yesterday_untimed.pk],
        )
        self.assertEqual(
            DAY_PATTERN.findall(response.content.decode()),
            [self.days(offset).isoformat() for offset in range(-14, 0)],
        )
        self.assertNotContains(response, 'aria-current="page">Dzisiaj<')

    def test_view_parameter_is_ignored(self):
        default = self.client.get(INDEX_URL)
        for view in ('past', 'upcoming', 'everything'):
            with self.subTest(view=view):
                response = self.client.get(INDEX_URL, {'view': view})

                self.assertEqual(self.rendered_rows(response), self.rendered_rows(default))
                self.assertEqual(response.context['days'][0]['key'], self.today.isoformat())
                self.assertNotIn('mode', response.context)
                self.assertNotIn('modes', response.context)
                self.assertNotContains(response, 'view=')

    def test_index_shows_only_own_family_entries(self):
        """2.3"""
        for params in ({}, self.earlier()):
            with self.subTest(params=params):
                response = self.client.get(INDEX_URL, params)
                self.assertNotContains(response, FOREIGN_SENTINEL)
                self.assertNotIn(self.foreign.pk, self.rendered_rows(response))
                self.assertNotIn(self.lucky.pk, self.rendered_rows(response))

    def test_rows_show_title_time_and_detail_link_only(self):
        self.tomorrow.assigned_member = self.child
        self.tomorrow.save()

        response = self.client.get(INDEX_URL)

        self.assertContains(
            response,
            f'href="{detail_url(self.tomorrow.pk)}?start={self.today.isoformat()}"',
        )
        # Owner 2026-10-05: no type label and no "Edytuj" on list rows; editing
        # stays on the detail page.
        self.assertNotContains(response, f'href="{edit_url(self.tomorrow.pk)}"')
        self.assertNotContains(response, 'fn-entry-type')
        self.assertContains(response, 'Michał')
        # S-08: the day heading carries the date and the assignee sub-heading
        # the assignee; the row shows only the time.
        html = response.content.decode()
        tomorrow = day_html(html, self.days(1).isoformat())
        self.assertEqual(
            DAY_HEADING_PATTERN.findall(tomorrow),
            [parent_day_heading(self.days(1), self.today)],
        )
        self.assertEqual(group_heading(tomorrow, f'member-{self.child.pk}'), 'Michał')
        row = group_html(tomorrow, f'member-{self.child.pk}')
        self.assertIn(f'data-entry-row="{self.tomorrow.pk}"', row)
        self.assertIn('<span>08:00</span>', row)
        self.assertNotIn('<span>Michał</span>', row)
        later = day_html(html, self.days(10).isoformat())
        self.assertEqual(
            DAY_HEADING_PATTERN.findall(later),
            [parent_day_heading(self.days(10), self.today)],
        )
        self.assertNotIn('Bez daty</span>', html)


class EmptyIndexTests(ManageViewMixin, TestCase):
    def test_empty_fortnight_still_renders_fourteen_empty_day_boxes(self):
        self.entry(FOREIGN_SENTINEL, family=self.other_family, date=self.today)
        for params, offsets in (({}, range(14)), (self.earlier(), range(-14, 0))):
            with self.subTest(params=params):
                response = self.client.get(INDEX_URL, params)
                html = response.content.decode()

                self.assertEqual(
                    DAY_PATTERN.findall(html),
                    [self.days(offset).isoformat() for offset in offsets],
                )
                self.assertEqual(html.count(EMPTY_DAY), 14)
                self.assertEqual(html.count('fn-calendar-day fn-calendar-day--empty'), 14)
                self.assertNotContains(response, 'data-entry-row')
                self.assertNotContains(response, FOREIGN_SENTINEL)
                self.assertNotContains(response, 'fn-empty')
                self.assertContains(response, 'data-state-part="calendar"')


class CalendarPresentationTests(ManageViewMixin, TestCase):
    def test_only_dates_without_entries_show_brak_wpisow(self):
        first = self.entry('Pierwszy', date=self.days(1), assigned_member=self.child)
        second = self.entry('Drugi', date=self.days(1))
        later = self.entry('Później', date=self.days(9))

        html = self.client.get(INDEX_URL).content.decode()

        for offset in range(14):
            with self.subTest(offset=offset):
                day = day_html(html, self.days(offset).isoformat())
                populated = offset in (1, 9)
                self.assertEqual(EMPTY_DAY in day, not populated)
                self.assertEqual(
                    f'fn-calendar-day--empty" data-day-group="{self.days(offset).isoformat()}"' in html,
                    not populated,
                )
        rows = ROW_PATTERN.findall(html)
        for entry in (first, second, later):
            with self.subTest(entry=entry.content):
                self.assertEqual(rows.count(str(entry.pk)), 1)
        self.assertEqual(
            GROUP_PATTERN.findall(day_html(html, self.days(1).isoformat())),
            [f'member-{self.child.pk}', 'family'],
        )

    def test_only_saturday_and_sunday_boxes_carry_the_weekend_marker(self):
        saturday = next(self.days(offset) for offset in range(14) if self.days(offset).weekday() == 5)
        self.entry('Sobota', date=saturday)

        for params, offsets in (({}, range(14)), (self.earlier(), range(-14, 0))):
            with self.subTest(params=params):
                html = self.client.get(INDEX_URL, params).content.decode()

                weekend = [
                    self.days(offset).isoformat()
                    for offset in offsets
                    if self.days(offset).weekday() >= 5
                ]
                self.assertEqual(len(weekend), 4)
                self.assertEqual(
                    re.findall(r'data-day-group="([\w-]+)" data-weekend>', html), weekend
                )
                self.assertEqual(html.count('data-weekend'), 4)

    def test_assignee_lists_are_labelled_with_day_and_assignee(self):
        self.entry('Pierwszy', date=self.days(1), assigned_member=self.child)

        html = self.client.get(INDEX_URL).content.decode()

        heading = parent_day_heading(self.days(1), self.today)
        self.assertIn(
            f'<ul class="fn-entry-list" aria-label="{heading}, Michał">',
            day_html(html, self.days(1).isoformat()),
        )

    def nav_html(self, response):
        html = response.content.decode()
        start = html.index('<nav class="fn-calendar-nav"')
        return html[start:html.index('</nav>', start)]

    def test_navigation_always_shows_three_polish_links(self):
        today = self.client.get(INDEX_URL)
        earlier = self.client.get(INDEX_URL, self.earlier())

        self.assertContains(
            today,
            '<nav class="fn-calendar-nav" aria-label="Nawigacja kalendarza" '
            'data-state-part="calendar-nav">',
        )
        self.assertEqual(
            re.findall(r'<a href="([^"]*)"[^>]*>([^<]*)</a>', self.nav_html(today)),
            [
                (f'{INDEX_URL}?start={self.days(-14).isoformat()}', 'Wcześniejsze'),
                (f'{INDEX_URL}?start={self.today.isoformat()}', 'Dzisiaj'),
                (f'{INDEX_URL}?start={self.days(14).isoformat()}', 'Następne'),
            ],
        )
        self.assertEqual(
            re.findall(r'<a href="([^"]*)"[^>]*>([^<]*)</a>', self.nav_html(earlier)),
            [
                (f'{INDEX_URL}?start={self.days(-28).isoformat()}', 'Wcześniejsze'),
                (f'{INDEX_URL}?start={self.today.isoformat()}', 'Dzisiaj'),
                (f'{INDEX_URL}?start={self.today.isoformat()}', 'Następne'),
            ],
        )
        for response in (today, earlier):
            for text in ('Poprzednie 2 tygodnie', 'Następne 2 tygodnie', 'Rodzaj listy',
                         'view=', 'Minione'):
                with self.subTest(text=text):
                    self.assertNotContains(response, text)

    def test_dzisiaj_is_current_only_on_the_window_starting_today(self):
        cases = (
            ({}, True),
            ({'start': self.today.isoformat()}, True),
            ({'start': self.days(14).isoformat()}, False),
            (self.earlier(), False),
            ({'start': self.days(-7).isoformat()}, False),
        )
        for params, current in cases:
            with self.subTest(params=params):
                nav = self.nav_html(self.client.get(INDEX_URL, params))
                self.assertEqual(nav.count('aria-current'), 1 if current else 0)
                self.assertEqual(
                    'aria-current="page">Dzisiaj</a>' in nav, current
                )


class CalendarWindowTests(ManageViewMixin, TestCase):
    def keys(self, response):
        return [day['key'] for day in response.context['days']]

    def test_default_window_is_today_through_today_plus_thirteen(self):
        response = self.client.get(INDEX_URL)

        self.assertEqual(
            self.keys(response),
            [self.days(offset).isoformat() for offset in range(14)],
        )
        self.assertTrue(response.context['is_today'])

    def test_earlier_then_next_returns_to_the_today_window(self):
        default = self.client.get(INDEX_URL)

        earlier = self.client.get(default.context['previous_url'])
        self.assertEqual(
            self.keys(earlier),
            [self.days(offset).isoformat() for offset in range(-14, 0)],
        )
        self.assertFalse(earlier.context['is_today'])

        back = self.client.get(earlier.context['next_url'])
        self.assertEqual(self.keys(back), self.keys(default))
        self.assertTrue(back.context['is_today'])

    def test_windows_move_forward_and_back_across_today(self):
        before = self.entry('Przedwczoraj', date=self.days(-2))
        after = self.entry('Pojutrze', date=self.days(2))

        straddling = self.client.get(INDEX_URL, {'start': self.days(-7).isoformat()})
        self.assertEqual(
            self.keys(straddling),
            [self.days(offset).isoformat() for offset in range(-7, 7)],
        )
        self.assertEqual(self.rendered_rows(straddling), [before.pk, after.pk])

        forward = self.client.get(straddling.context['next_url'])
        self.assertEqual(self.keys(forward)[0], self.days(7).isoformat())
        back = self.client.get(forward.context['previous_url'])
        self.assertEqual(self.keys(back)[0], self.days(-7).isoformat())
        further_back = self.client.get(back.context['previous_url'])
        self.assertEqual(self.keys(further_back)[0], self.days(-21).isoformat())
        self.assertEqual(
            self.client.get(further_back.context['today_url']).context['days'][0]['key'],
            self.today.isoformat(),
        )

    def test_valid_start_selects_the_requested_window(self):
        start = self.days(28)
        response = self.client.get(INDEX_URL, {'start': start.isoformat()})

        self.assertEqual(self.keys(response)[0], start.isoformat())
        self.assertEqual(self.keys(response)[-1], self.days(41).isoformat())

    def test_invalid_and_non_canonical_start_fall_back_to_today(self):
        cases = (
            'not-a-date',
            '',
            self.days(3).strftime('%Y%m%d'),
            f'{self.days(3).isoformat()}T00:00',
            f' {self.days(3).isoformat()}',
        )
        for value in cases:
            with self.subTest(start=value):
                response = self.client.get(INDEX_URL, {'start': value})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(self.keys(response)[0], self.today.isoformat())
                self.assertTrue(response.context['is_today'])

    def test_any_canonical_start_in_range_is_valid_on_either_side_of_today(self):
        for offset in (-1, -100, 1, 3, 100):
            with self.subTest(offset=offset):
                start = self.days(offset)
                response = self.client.get(INDEX_URL, {'start': start.isoformat()})
                self.assertEqual(self.keys(response)[0], start.isoformat())

    def test_rows_inside_a_day_run_earliest_first_in_an_earlier_window(self):
        evening = self.entry('Wieczór', date=self.days(-2), time=datetime.time(18, 0))
        morning = self.entry('Rano', date=self.days(-2), time=datetime.time(8, 0))
        untimed = self.entry('Bez godziny', date=self.days(-2))

        earlier = self.client.get(INDEX_URL, self.earlier())

        self.assertEqual(
            [pk for pk in self.rendered_rows(earlier) if pk in {evening.pk, morning.pk, untimed.pk}],
            [morning.pk, evening.pk, untimed.pk],
        )

    def test_out_of_range_start_falls_back_to_today_instead_of_failing(self):
        for value in ('9999-12-31', '9999-12-10', '0001-01-01', '0001-01-14'):
            with self.subTest(start=value):
                response = self.client.get(INDEX_URL, {'start': value})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(self.keys(response)[0], self.today.isoformat())
        entry = self.entry()
        self.assertContains(
            self.client.get(detail_url(entry.pk), {'start': '9999-12-31'}),
            f'href="{INDEX_URL}?start={self.today.isoformat()}"',
        )
        response = self.client.post(delete_url(entry.pk), {'start': '0001-01-01'})
        self.assertRedirects(response, f'{INDEX_URL}?start={self.today.isoformat()}')

    def test_navigation_moves_fourteen_days_both_ways(self):
        for offset in (0, 14, -14, -5):
            with self.subTest(offset=offset):
                start = self.days(offset)
                response = self.client.get(INDEX_URL, {'start': start.isoformat()})
                step = datetime.timedelta(days=14)
                self.assertEqual(
                    response.context['previous_url'],
                    f'{INDEX_URL}?start={(start - step).isoformat()}',
                )
                self.assertEqual(
                    response.context['next_url'],
                    f'{INDEX_URL}?start={(start + step).isoformat()}',
                )
                self.assertEqual(
                    response.context['today_url'],
                    f'{INDEX_URL}?start={self.today.isoformat()}',
                )

    def test_only_entries_inside_the_selected_window_are_queried(self):
        visible = self.entry('Widoczny', date=self.days(14))
        hidden = self.entry('Poza oknem', date=self.days(28))

        response = self.client.get(INDEX_URL, {'start': self.days(14).isoformat()})

        self.assertIn(visible.pk, self.rendered_rows(response))
        self.assertNotIn(hidden.pk, self.rendered_rows(response))


class DetailTests(ManageViewMixin, TestCase):
    def test_detail_shows_entry_data_and_provenance_without_internals(self):
        entry = self.entry(
            'Sprawdzian z fizyki',
            entry_type=EntryType.CALENDAR_EVENT.value,
            date=self.days(2),
            time=datetime.time(8, 55),
            assigned_member=self.child,
            school_item=SchoolItemKind.TEST.value,
            source=Entry.Source.EDUVULCAN,
            created_by=None,
            submission_key=uuid.uuid4(),
        )

        response = self.client.get(detail_url(entry.pk))

        for text in ('Sprawdzian z fizyki', 'Wydarzenie', '08:55', 'Michał', 'Sprawdzian',
                     'EduVulcan', 'Utworzono', 'Zmieniono'):
            with self.subTest(text=text):
                self.assertContains(response, text)
        self.assertNotContains(response, str(entry.submission_key))
        self.assertNotContains(response, 'Ewa')

    def test_detail_shows_subject_only_when_set(self):
        with_subject = self.entry(
            'Kartkówka',
            entry_type=EntryType.CALENDAR_EVENT.value,
            date=self.days(2),
            assigned_member=self.child,
            school_item=SchoolItemKind.QUIZ.value,
            school_subject='Geografia',
        )
        legacy = self.entry(
            'Sprawdzian',
            entry_type=EntryType.CALENDAR_EVENT.value,
            date=self.days(2),
            assigned_member=self.child,
            school_item=SchoolItemKind.TEST.value,
            source=Entry.Source.EDUVULCAN,
        )

        shown = self.client.get(detail_url(with_subject.pk))
        hidden = self.client.get(detail_url(legacy.pk))

        self.assertContains(shown, '<dt>Przedmiot</dt>', html=True)
        self.assertContains(shown, '<dd>Geografia</dd>', html=True)
        self.assertEqual(hidden.status_code, 200)
        self.assertContains(hidden, 'Element szkolny')
        self.assertNotContains(hidden, 'Przedmiot')

    def test_detail_hides_creator_and_submission_key_of_a_manual_entry(self):
        creator = self._member('parent2', FamilyMember.Role.PARENT, 'Tomasz')
        key = uuid.uuid4()
        entry = self.entry('Zebranie', created_by=creator, submission_key=key)

        response = self.client.get(detail_url(entry.pk))

        self.assertContains(response, 'Zebranie')
        self.assertNotContains(response, 'Tomasz')
        self.assertNotContains(response, str(key))

    def back_link(self, start):
        return f'<a href="{INDEX_URL}?start={start.isoformat()}">Wróć do listy</a>'

    def test_detail_links_back_to_the_window_the_entry_belongs_to(self):
        cases = {-3: -14, -14: -14, -15: -28, -1: -14, 0: 0, 10: 0, 13: 0, 14: 14}
        for entry_offset, window_offset in cases.items():
            with self.subTest(entry_offset=entry_offset):
                entry = self.entry(date=self.days(entry_offset))
                self.assertContains(
                    self.client.get(detail_url(entry.pk)),
                    self.back_link(self.days(window_offset)),
                    html=True,
                )

    def test_detail_preserves_the_requested_window(self):
        entry = self.entry(date=self.days(20))
        for offset in (14, -28, 3):
            with self.subTest(offset=offset):
                start = self.days(offset)
                response = self.client.get(detail_url(entry.pk), {'start': start.isoformat()})
                self.assertContains(response, self.back_link(start), html=True)
                self.assertContains(
                    response,
                    f'<input type="hidden" name="start" value="{start.isoformat()}">',
                    html=True,
                )

    def test_detail_without_start_returns_to_the_fortnight_holding_the_entry(self):
        later = self.entry(date=self.days(20))
        older = self.entry(date=self.days(-20))

        self.assertContains(
            self.client.get(detail_url(later.pk)), self.back_link(self.days(14)), html=True
        )
        self.assertContains(
            self.client.get(detail_url(older.pk)), self.back_link(self.days(-28)), html=True
        )
        # An invalid start behaves like a missing one.
        for start in ('not-a-date', '20261013', ''):
            with self.subTest(start=start):
                self.assertContains(
                    self.client.get(detail_url(older.pk), {'start': start}),
                    self.back_link(self.days(-28)),
                    html=True,
                )
        # A legacy view parameter is ignored.
        response = self.client.get(detail_url(older.pk), {'view': 'upcoming'})
        self.assertContains(response, self.back_link(self.days(-28)), html=True)
        self.assertNotContains(response, 'view=')
        self.assertNotContains(response, 'name="view"')

    def test_foreign_and_missing_ids_are_indistinguishable(self):
        """2.4"""
        foreign = self.entry(FOREIGN_SENTINEL, family=self.other_family)
        missing_pk = Entry.objects.order_by('-pk').first().pk + 1000

        for pk in (foreign.pk, missing_pk):
            for method, url in (
                ('get', detail_url(pk)),
                ('get', edit_url(pk)),
                ('post', edit_url(pk)),
                ('post', delete_url(pk)),
            ):
                with self.subTest(pk=pk, url=url, method=method):
                    response = getattr(self.client, method)(url, self.form_data())
                    self.assertEqual(response.status_code, 404)
                    self.assertNotContains(response, FOREIGN_SENTINEL, status_code=404)
        foreign.refresh_from_db()
        self.assertEqual(foreign.content, FOREIGN_SENTINEL)


class CreateTests(ManageViewMixin, TestCase):
    def test_create_saves_manual_entry_and_redirects_to_detail(self):
        """2.5"""
        data = self.form_data(submission_key=str(uuid.uuid4()))

        response = self.client.post(CREATE_URL, data)

        entry = Entry.objects.get()
        self.assertRedirects(response, detail_url(entry.pk), fetch_redirect_response=False)
        self.assertEqual(entry.source, Entry.Source.MANUAL)
        self.assertEqual(entry.created_by, self.parent)
        self.assertEqual(entry.assigned_member, self.child)
        self.assertContains(self.client.get(detail_url(entry.pk)), 'Dodano wpis.')

    def test_create_persists_the_subject_of_a_school_event(self):
        data = self.form_data(
            school_item=SchoolItemKind.HOMEWORK.value,
            school_subject='  Chemia ',
            submission_key=str(uuid.uuid4()),
        )

        response = self.client.post(CREATE_URL, data)

        entry = Entry.objects.get()
        self.assertRedirects(response, detail_url(entry.pk), fetch_redirect_response=False)
        self.assertEqual(entry.school_subject, 'Chemia')

    def test_create_school_event_without_subject_is_an_error(self):
        data = self.form_data(
            school_item=SchoolItemKind.QUIZ.value, submission_key=str(uuid.uuid4())
        )

        response = self.client.post(CREATE_URL, data)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Podaj przedmiot.')
        self.assertContains(response, 'id="id_school_subject_error"')
        self.assertFalse(Entry.objects.exists())

    def test_resubmitted_create_form_saves_one_entry(self):
        data = self.form_data(submission_key=str(uuid.uuid4()))

        first = self.client.post(CREATE_URL, data)
        second = self.client.post(CREATE_URL, data)

        self.assertEqual(Entry.objects.count(), 1)
        self.assertEqual(first['Location'], second['Location'])

    def test_invalid_create_shows_accessible_polish_errors_without_saving(self):
        data = self.form_data(
            content='',
            date='',
            school_item=SchoolItemKind.HOMEWORK.value,
            entry_type=EntryType.NOTE.value,
            submission_key=str(uuid.uuid4()),
        )

        response = self.client.post(CREATE_URL, data)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Entry.objects.exists())
        self.assertContains(response, 'Popraw zaznaczone pola.')
        self.assertContains(response, 'To pole jest wymagane.')
        self.assertContains(response, 'Ten element szkolny wymaga rodzaju')
        self.assertContains(response, 'aria-invalid="true"')
        self.assertContains(response, 'id="id_content_error"')

    def test_invalid_create_has_an_error_title_and_a_linked_summary(self):
        data = self.form_data(
            content='',
            school_item=SchoolItemKind.HOMEWORK.value,
            entry_type=EntryType.NOTE.value,
            submission_key=str(uuid.uuid4()),
        )

        response = self.client.post(CREATE_URL, data)

        self.assertContains(response, '<title>Błąd: Nowy wpis | FamilyNotes</title>')
        html = response.content.decode()
        summary = html[html.index('Popraw zaznaczone pola.'):html.index('</div>', html.index('Popraw zaznaczone pola.'))]
        self.assertIn('<a href="#id_content">Tytuł</a>', summary)
        self.assertIn('<a href="#id_school_item">Element szkolny</a>', summary)
        self.assertLess(summary.index('#id_content'), summary.index('#id_school_item'))
        self.assertNotIn('#id_date', summary)

    def test_valid_create_form_title_has_no_error_prefix(self):
        response = self.client.get(CREATE_URL)

        self.assertContains(response, '<title>Nowy wpis | FamilyNotes</title>')

    def test_create_form_offers_every_editable_field_and_a_submission_key(self):
        """2.6"""
        response = self.client.get(CREATE_URL)

        for name in ('entry_type', 'content', 'date', 'time', 'assigned_member',
                     'school_item', 'school_subject', 'submission_key'):
            with self.subTest(field=name):
                self.assertContains(response, f'name="{name}"')
        self.assertContains(response, f'href="{reverse("entries:capture")}"')
        self.assertContains(response, 'csrfmiddlewaretoken')


class EditTests(ManageViewMixin, TestCase):
    def test_edit_updates_fields_preserves_provenance_and_redirects_to_detail(self):
        key = uuid.uuid4()
        entry = self.entry(source=Entry.Source.EDUVULCAN, created_by=None, submission_key=key)
        created_at = entry.created_at

        response = self.client.post(
            edit_url(entry.pk),
            self.form_data(
                school_item=SchoolItemKind.TEST.value,
                school_subject=' Fizyka ',
                content='Poprawiony',
            ),
        )

        self.assertRedirects(response, detail_url(entry.pk))
        entry.refresh_from_db()
        self.assertEqual(entry.content, 'Poprawiony')
        self.assertEqual(entry.school_item, SchoolItemKind.TEST.value)
        self.assertEqual(entry.school_subject, 'Fizyka')
        self.assertEqual(entry.source, Entry.Source.EDUVULCAN)
        self.assertIsNone(entry.created_by)
        self.assertEqual(entry.submission_key, key)
        self.assertEqual(entry.created_at, created_at)
        self.assertEqual(entry.family, self.family)

    def test_edit_form_is_prefilled_without_submission_key(self):
        entry = self.entry('Kupić zeszyt', assigned_member=self.child)

        response = self.client.get(edit_url(entry.pk))

        self.assertContains(response, 'Kupić zeszyt')
        self.assertContains(response, f'<option value="{self.child.pk}" selected>')
        self.assertNotContains(response, 'name="submission_key"')
        self.assertContains(response, f'action="{edit_url(entry.pk)}"')
        self.assertContains(response, f'href="{detail_url(entry.pk)}"')

    def test_edit_form_shows_the_stored_subject(self):
        entry = self.entry(
            'Kartkówka',
            entry_type=EntryType.CALENDAR_EVENT.value,
            date=self.days(1),
            assigned_member=self.child,
            school_item=SchoolItemKind.QUIZ.value,
            school_subject='Historia',
        )

        response = self.client.get(edit_url(entry.pk))

        self.assertContains(response, '<label for="id_school_subject">Przedmiot</label>', html=True)
        self.assertContains(response, 'value="Historia"')

    def test_unrelated_edit_of_subjectless_eduvulcan_school_event_saves(self):
        entry = self.entry(
            'Sprawdzian: Biologia',
            entry_type=EntryType.CALENDAR_EVENT.value,
            date=self.days(4),
            assigned_member=self.child,
            school_item=SchoolItemKind.TEST.value,
            source=Entry.Source.EDUVULCAN,
            created_by=None,
        )

        response = self.client.post(
            edit_url(entry.pk),
            self.form_data(
                content='Sprawdzian: Biologia',
                date=self.days(5).isoformat(),
                assigned_member=str(self.other_child.pk),
                school_item=SchoolItemKind.TEST.value,
            ),
        )

        self.assertRedirects(response, detail_url(entry.pk))
        entry.refresh_from_db()
        self.assertEqual(entry.assigned_member, self.other_child)
        self.assertEqual(entry.school_subject, '')

    def test_setting_a_school_event_kind_without_subject_is_an_error(self):
        entry = self.entry(
            'Wywiadówka',
            entry_type=EntryType.CALENDAR_EVENT.value,
            date=self.days(4),
            assigned_member=self.child,
        )

        response = self.client.post(
            edit_url(entry.pk), self.form_data(school_item=SchoolItemKind.TEST.value)
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Podaj przedmiot.')
        entry.refresh_from_db()
        self.assertEqual(entry.school_item, '')

    def test_editing_title_keeps_deactivated_assignee(self):
        entry = self.entry('Oddać książkę', assigned_member=self.inactive_child)

        response = self.client.get(edit_url(entry.pk))
        self.assertContains(response, f'<option value="{self.inactive_child.pk}" selected>')

        response = self.client.post(
            edit_url(entry.pk),
            self.form_data(
                entry_type=EntryType.TODO.value,
                content='Oddać dwie książki',
                date=self.days(10).isoformat(),
                time='',
                assigned_member=str(self.inactive_child.pk),
            ),
        )

        self.assertRedirects(response, detail_url(entry.pk))
        entry.refresh_from_db()
        self.assertEqual(entry.content, 'Oddać dwie książki')
        self.assertEqual(entry.assigned_member, self.inactive_child)

    def test_invalid_edit_rerenders_without_mutation(self):
        entry = self.entry('Bez zmian')

        response = self.client.post(
            edit_url(entry.pk), self.form_data(assigned_member=str(self.other_family_child.pk))
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'aria-invalid="true"')
        self.assertContains(response, '<title>Błąd: Edytuj wpis | FamilyNotes</title>')
        self.assertContains(response, '<a href="#id_assigned_member">Dla kogo</a>')
        entry.refresh_from_db()
        self.assertEqual(entry.content, 'Bez zmian')


class DeleteTests(ManageViewMixin, TestCase):
    def test_delete_removes_entry_and_returns_to_the_posted_window(self):
        """2.5"""
        today = f'{INDEX_URL}?start={self.today.isoformat()}'
        cases = {
            self.days(-14).isoformat(): f'{INDEX_URL}?start={self.days(-14).isoformat()}',
            self.days(28).isoformat(): f'{INDEX_URL}?start={self.days(28).isoformat()}',
            self.days(-5).isoformat(): f'{INDEX_URL}?start={self.days(-5).isoformat()}',
            '': today,
            'https://evil.example/': today,
            '//evil.example': today,
        }
        for posted, expected in cases.items():
            with self.subTest(start=posted):
                entry = self.entry()
                response = self.client.post(
                    delete_url(entry.pk),
                    {'start': posted, 'view': 'past', 'next': 'https://evil.example/'},
                )
                self.assertRedirects(response, expected)
                self.assertFalse(Entry.objects.filter(pk=entry.pk).exists())

    def test_delete_without_start_returns_to_the_today_window(self):
        entry = self.entry()

        response = self.client.post(delete_url(entry.pk))

        self.assertRedirects(response, f'{INDEX_URL}?start={self.today.isoformat()}')

    def test_delete_removes_only_the_target(self):
        target = self.entry('Do usunięcia')
        keep = self.entry('Zostaje')
        foreign = self.entry(FOREIGN_SENTINEL, family=self.other_family)

        self.client.post(delete_url(target.pk))

        self.assertEqual(
            set(Entry.objects.values_list('pk', flat=True)), {keep.pk, foreign.pk}
        )
        self.assertContains(self.client.get(INDEX_URL), 'Usunięto wpis.')


class ManagementTemplateTests(ManageViewMixin, TestCase):
    """2.6: create, capture, edit and delete actions are reachable."""

    def test_list_rows_have_no_edit_link_and_no_empty_meta(self):
        untimed = self.entry('Oddać książkę do biblioteki', date=self.days(1))

        response = self.client.get(INDEX_URL)

        self.assertNotContains(response, 'Edytuj')
        self.assertContains(response, 'Oddać książkę do biblioteki')
        html = response.content.decode()
        start = html.index(f'data-entry-row="{untimed.pk}"')
        row = html[start:html.index('</li>', start)]
        self.assertNotIn('fn-entry-meta', row)

    def test_detail_page_keeps_the_edit_link(self):
        entry = self.entry('Oddać książkę do biblioteki', date=self.days(1))

        response = self.client.get(detail_url(entry.pk))

        self.assertContains(response, f'href="{edit_url(entry.pk)}"')

    def test_index_exposes_structured_create_and_capture(self):
        response = self.client.get(INDEX_URL)

        self.assertContains(response, f'href="{CREATE_URL}"')
        self.assertContains(response, f'href="{reverse("entries:capture")}"')

    def test_detail_has_edit_link_and_no_js_delete_disclosure(self):
        entry = self.entry()

        response = self.client.get(detail_url(entry.pk))
        html = response.content.decode()

        self.assertContains(response, f'href="{edit_url(entry.pk)}"')
        self.assertIn('<details class="fn-manage-delete"', html)
        self.assertNotIn('<details class="fn-manage-delete" data-state-part="delete" open', html)
        self.assertIn('<summary>Usuń wpis</summary>', html)
        self.assertIn('nie można cofnąć', html)
        delete_form = html[html.index(f'action="{delete_url(entry.pk)}"') - 40:]
        self.assertIn('method="post"', delete_form)
        self.assertIn('csrfmiddlewaretoken', delete_form)
        # The delete disclosure needs no JavaScript: the page loads only the
        # site-wide service-worker registration (S-06), nothing of its own.
        main = html[html.index('<main'):html.index('</main>')]
        self.assertNotIn('<script', main)
        self.assertEqual(html.count('<script'), 1)
        self.assertIn('js/pwa-register.js', html)

    def test_parent_navigation_links_to_the_index(self):
        for url in (reverse('account_status'), reverse('entries:capture')):
            with self.subTest(url=url):
                self.assertContains(self.client.get(url), f'href="{INDEX_URL}"')

    def test_child_account_page_has_no_index_link(self):
        self.client.force_login(self.child.user)

        self.assertNotContains(self.client.get(reverse('account_status')), f'href="{INDEX_URL}"')


class MessagesPartialTests(TestCase):
    def test_message_level_selects_panel_style(self):
        cases = {
            constants.SUCCESS: ('fn-panel--success', 'role="status"'),
            constants.WARNING: ('fn-panel--notice', 'role="status"'),
            constants.ERROR: ('fn-panel--danger', 'role="alert"'),
        }
        for level, (panel_class, role) in cases.items():
            with self.subTest(level=level):
                html = render_to_string(
                    'entries/_manage_messages.html', {'messages': [Message(level, 'Komunikat')]}
                )
                self.assertIn(panel_class, html)
                self.assertIn(role, html)
                self.assertIn('Komunikat', html)


class TwoParentManageViewTests(TwoParentFixtureMixin, ManageViewMixin, TestCase):
    """S-07: parent-assigned entries are created, listed and shown with their parent."""

    def test_index_and_detail_show_the_parent_assignee(self):
        mine = self.entry('Odebrać paczkę', date=self.days(1), assigned_member=self.parent)
        theirs = self.entry('Umówić mechanika', date=self.days(2), assigned_member=self.second_parent)

        index = self.client.get(INDEX_URL)

        self.assertEqual(self.rendered_rows(index), [mine.pk, theirs.pk])
        self.assertContains(index, 'Ewa')
        self.assertContains(index, 'Paweł')
        # S-08: each parent-assigned row sits under its parent's sub-heading
        # within the entry's day group.
        html = index.content.decode()
        for entry, member in ((mine, self.parent), (theirs, self.second_parent)):
            with self.subTest(heading=member.display_name):
                key = f'member-{member.pk}'
                day = day_html(html, entry.date.isoformat())
                self.assertEqual(group_heading(day, key), member.display_name)
                self.assertIn(f'data-entry-row="{entry.pk}"', group_html(day, key))
        for entry, name in ((mine, 'Ewa'), (theirs, 'Paweł')):
            with self.subTest(name=name):
                detail = self.client.get(detail_url(entry.pk))
                self.assertEqual(detail.status_code, 200)
                self.assertContains(detail, name)
                self.assertNotContains(detail, 'Ogólne')

    def test_create_and_edit_through_the_views_save_a_parent(self):
        for member in (self.parent, self.second_parent):
            with self.subTest(member=member.display_name):
                Entry.objects.all().delete()
                self.client.post(
                    CREATE_URL,
                    self.form_data(
                        entry_type=EntryType.NOTE.value,
                        date=self.days(10).isoformat(),
                        time='',
                        assigned_member=str(member.pk),
                        submission_key=str(uuid.uuid4()),
                    ),
                )
                entry = Entry.objects.get()
                self.assertEqual(entry.assigned_member, member)

                other = self.second_parent if member == self.parent else self.parent
                self.client.post(
                    edit_url(entry.pk),
                    self.form_data(
                        entry_type=EntryType.NOTE.value,
                        date=self.days(10).isoformat(),
                        time='',
                        assigned_member=str(other.pk),
                    ),
                )
                entry.refresh_from_db()
                self.assertEqual(entry.assigned_member, other)

    def test_anonymous_cannot_read_a_parent_assigned_entry(self):
        entry = self.entry('Odebrać paczkę', assigned_member=self.second_parent)
        self.client.logout()

        for url in (INDEX_URL, detail_url(entry.pk)):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse('account_login'), response['Location'])


class GroupedIndexTests(TwoParentFixtureMixin, ManageViewMixin, TestCase):
    """S-08: the parent index groups entries by day, then by assignee, in every window."""

    def setUp(self):
        super().setUp()
        e = self.entry
        # Created out of group order: the order comes from roles and member pks.
        self.family_today = e('Rodzina dziś', date=self.today)
        self.pawel_tomorrow = e('Paweł jutro', date=self.days(1), assigned_member=self.second_parent)
        self.ewa_later = e('Ewa później', assigned_member=self.parent)
        self.ania_tomorrow = e('Ania jutro', date=self.days(1), assigned_member=self.other_child)
        self.michal_next_week = e('Michał za tydzień', date=self.days(7), assigned_member=self.child)
        self.michal_today = e(
            'Michał dziś', date=self.today, time=datetime.time(8), assigned_member=self.child
        )
        self.michal_later = e('Michał później', assigned_member=self.child)
        self.zosia_today = e('Zosia dziś', date=self.today, assigned_member=self.inactive_child)
        self.family_later = e('Rodzina później')
        self.michal_yesterday = e('Michał wczoraj', date=self.days(-1), assigned_member=self.child)
        self.michal_last_week = e('Michał tydzień temu', date=self.days(-7), assigned_member=self.child)
        self.jolanta_yesterday = e(
            'Jolanta wczoraj', date=self.days(-1), assigned_member=self.inactive_parent
        )
        self.family_yesterday = e('Rodzina wczoraj', date=self.days(-1))
        self.foreign = e(
            FOREIGN_SENTINEL,
            family=self.other_family,
            date=self.today,
            assigned_member=self.other_family_child,
        )

    def key(self, member):
        return f'member-{member.pk}'

    def day_groups(self, html):
        """``{day key: [assignee keys]}`` in render order."""
        return {
            key: groups
            for key in DAY_PATTERN.findall(html)
            if (groups := GROUP_PATTERN.findall(day_html(html, key)))
        }

    def test_today_window_groups_by_day_then_children_parents_family(self):
        html = self.client.get(INDEX_URL).content.decode()

        self.assertEqual(
            DAY_PATTERN.findall(html),
            [self.days(offset).isoformat() for offset in range(14)],
        )
        headings = DAY_HEADING_PATTERN.findall(html)
        self.assertEqual(headings[0], parent_day_heading(self.today, self.today))
        self.assertEqual(headings[1], parent_day_heading(self.days(1), self.today))
        self.assertEqual(
            self.day_groups(html),
            {
                self.today.isoformat(): [self.key(self.child), self.key(self.inactive_child), 'family'],
                self.days(1).isoformat(): [self.key(self.other_child), self.key(self.second_parent)],
                self.days(7).isoformat(): [self.key(self.child)],
                self.days(10).isoformat(): [self.key(self.child), self.key(self.parent), 'family'],
            },
        )
        today = day_html(html, self.today.isoformat())
        self.assertEqual(
            GROUP_HEADING_PATTERN.findall(today), ['Michał', 'Zosia (nieaktywne konto)', 'Ogólne']
        )
        self.assertEqual(
            GROUP_HEADING_PATTERN.findall(day_html(html, self.days(10).isoformat())), ['Michał', 'Ewa', 'Ogólne']
        )

    def test_same_day_entries_share_one_day_heading_in_child_parent_family_order(self):
        day = self.days(3)
        # Created in reverse group order: the order comes from roles, not creation.
        family = self.entry('Rodzina za trzy dni', date=day, time=datetime.time(7))
        parent = self.entry('Ewa za trzy dni', date=day, time=datetime.time(8), assigned_member=self.parent)
        child = self.entry('Michał za trzy dni', date=day, time=datetime.time(9), assigned_member=self.child)

        html = self.client.get(INDEX_URL).content.decode()
        block = day_html(html, day.isoformat())

        self.assertEqual(DAY_PATTERN.findall(html).count(day.isoformat()), 1)
        self.assertEqual(len(DAY_HEADING_PATTERN.findall(block)), 1)
        self.assertEqual(GROUP_PATTERN.findall(block), [self.key(self.child), self.key(self.parent), 'family'])
        self.assertEqual(GROUP_HEADING_PATTERN.findall(block), ['Michał', 'Ewa', 'Ogólne'])
        self.assertEqual(
            [int(pk) for pk in ROW_PATTERN.findall(block)], [child.pk, parent.pk, family.pk]
        )

    def test_unassigned_entry_sits_in_the_family_group_of_its_day(self):
        html = self.client.get(INDEX_URL).content.decode()
        today = day_html(html, self.today.isoformat())

        self.assertEqual(group_heading(today, 'family'), 'Ogólne')
        self.assertEqual(
            [int(pk) for pk in ROW_PATTERN.findall(group_html(today, 'family'))],
            [self.family_today.pk],
        )
        self.assertEqual(
            [int(pk) for pk in ROW_PATTERN.findall(group_html(day_html(html, self.days(10).isoformat()), 'family'))],
            [self.family_later.pk],
        )

    def test_later_day_is_in_the_today_window_and_absent_from_the_earlier_one(self):
        upcoming = self.client.get(INDEX_URL).content.decode()
        past = self.client.get(INDEX_URL, self.earlier()).content.decode()

        self.assertEqual(DAY_PATTERN.findall(upcoming)[-1], self.days(13).isoformat())
        self.assertIn(parent_day_heading(self.days(10), self.today), upcoming)
        self.assertEqual(
            [int(pk) for pk in ROW_PATTERN.findall(group_html(day_html(upcoming, self.days(10).isoformat()), self.key(self.parent)))],
            [self.ewa_later.pk],
        )
        self.assertNotIn(self.days(10).isoformat(), DAY_PATTERN.findall(past))
        self.assertNotIn(parent_day_heading(self.days(10), self.today), past)

    def test_earlier_window_shows_chronological_days_then_children_parents_family(self):
        html = self.client.get(INDEX_URL, self.earlier()).content.decode()

        self.assertEqual(
            self.day_groups(html),
            {
                self.days(-1).isoformat(): [
                    self.key(self.child), self.key(self.inactive_parent), 'family'
                ],
                self.days(-7).isoformat(): [self.key(self.child)],
            },
        )
        self.assertEqual(
            DAY_PATTERN.findall(html),
            [self.days(offset).isoformat() for offset in range(-14, 0)],
        )
        self.assertEqual(
            DAY_HEADING_PATTERN.findall(html)[-1],
            parent_day_heading(self.days(-1), self.today),
        )
        self.assertEqual(
            group_heading(day_html(html, self.days(-1).isoformat()), self.key(self.inactive_parent)),
            'Jolanta (nieaktywne konto)',
        )

    def test_rows_keep_time_order_inside_an_assignee_sub_group(self):
        late = self.entry(
            'Michał dziś wieczorem', date=self.today, time=datetime.time(18), assigned_member=self.child
        )
        untimed = self.entry('Michał dziś kiedyś', date=self.today, assigned_member=self.child)
        early = self.entry(
            'Michał dziś rano', date=self.today, time=datetime.time(6), assigned_member=self.child
        )
        last_night = self.entry(
            'Michał wczoraj wieczorem', date=self.days(-1), time=datetime.time(21),
            assigned_member=self.child,
        )
        upcoming = self.client.get(INDEX_URL).content.decode()
        past = self.client.get(INDEX_URL, self.earlier()).content.decode()

        self.assertEqual(
            [int(pk) for pk in ROW_PATTERN.findall(
                group_html(day_html(upcoming, self.today.isoformat()), self.key(self.child))
            )],
            [early.pk, self.michal_today.pk, late.pk, untimed.pk],
        )
        self.assertEqual(
            [int(pk) for pk in ROW_PATTERN.findall(
                group_html(day_html(past, self.days(-1).isoformat()), self.key(self.child))
            )],
            [last_night.pk, self.michal_yesterday.pk],
        )
        self.assertNotIn('fn-manage-section-title', upcoming)
        self.assertNotIn('data-list-section', upcoming)

    def test_each_own_family_entry_renders_exactly_once(self):
        expected = {
            'today': {
                self.family_today, self.pawel_tomorrow, self.ewa_later, self.ania_tomorrow,
                self.michal_next_week, self.michal_today, self.michal_later,
                self.zosia_today, self.family_later,
            },
            'earlier': {
                self.michal_yesterday, self.michal_last_week, self.jolanta_yesterday,
                self.family_yesterday,
            },
        }
        windows = {'today': {}, 'earlier': self.earlier()}
        for window, entries in expected.items():
            with self.subTest(window=window):
                response = self.client.get(INDEX_URL, windows[window])
                rows = self.rendered_rows(response)
                self.assertEqual(sorted(rows), sorted(entry.pk for entry in entries))
                self.assertNotContains(response, FOREIGN_SENTINEL)
                self.assertNotIn(self.key(self.other_family_child), GROUP_PATTERN.findall(
                    response.content.decode()
                ))

    def test_reassigned_entry_moves_to_the_new_group(self):
        self.client.post(
            edit_url(self.family_later.pk),
            self.form_data(
                entry_type=EntryType.TODO.value,
                content='Rodzina później',
                date=self.days(10).isoformat(),
                time='',
                assigned_member=str(self.other_child.pk),
            ),
        )

        html = self.client.get(INDEX_URL).content.decode()

        later = day_html(html, self.days(10).isoformat())
        self.assertIn(
            f'data-entry-row="{self.family_later.pk}"',
            group_html(later, self.key(self.other_child)),
        )
        self.assertNotIn('family', GROUP_PATTERN.findall(later))

    def test_grouping_adds_no_queries_per_row(self):
        with self.assertNumQueries(self._index_queries()):
            self.client.get(INDEX_URL)
        for index in range(5):
            self.entry(f'Dodatkowy {index}', date=self.days(2), assigned_member=self.second_parent)
        with self.assertNumQueries(self._index_queries()):
            self.client.get(INDEX_URL)

    def _index_queries(self):
        with CaptureQueriesContext(connection) as queries:
            self.client.get(INDEX_URL)
        return len(queries.captured_queries)


FILTER_LINK_PATTERN = re.compile(
    r'<a href="([^"]*)" data-member-key="([\w-]+)"( aria-current="page")?>([^<]*)</a>'
)
VISIBLE_GROUP_PATTERN = re.compile(r'data-assignee-group="([\w-]+)">')
HIDDEN_GROUP_PATTERN = re.compile(r'data-assignee-group="([\w-]+)" hidden>')


class CalendarQueryCountTests(TwoParentFixtureMixin, ManageViewMixin, TestCase):
    """The parent calendar's query count does not grow with rows or assignees (no N+1)."""

    def count_queries(self, params):
        with CaptureQueriesContext(connection) as queries:
            self.assertEqual(self.client.get(INDEX_URL, params).status_code, 200)
        return len(queries)

    def test_parent_calendar_queries_do_not_grow_with_assignees(self):
        self.entry('Jeden', date=self.today, assigned_member=self.child)
        cases = [{}, {'member': str(self.child.pk)}]
        baseline = [self.count_queries(params) for params in cases]
        members = (self.other_child, self.parent, self.second_parent, self.inactive_child, None)
        for offset, member in enumerate(members, start=1):
            self.entry(f'Wpis {offset}', date=self.days(offset), assigned_member=member)
            self.entry(f'Drugi {offset}', date=self.days(offset), assigned_member=member)
        for params, expected in zip(cases, baseline):
            with self.subTest(params=params):
                self.assertEqual(self.count_queries(params), expected)


class MemberFilterTests(TwoParentFixtureMixin, ManageViewMixin, TestCase):
    """Phase 4: the parent calendar's child filter, rendered by the server for every window."""

    def setUp(self):
        super().setUp()
        e = self.entry
        self.michal_today = e('Michał dziś', date=self.today, assigned_member=self.child)
        self.ania_today = e('Ania dziś', date=self.today, assigned_member=self.other_child)
        self.ewa_today = e('Ewa dziś', date=self.today, assigned_member=self.parent)
        self.zosia_today = e('Zosia dziś', date=self.today, assigned_member=self.inactive_child)
        self.family_today = e('Rodzina dziś', date=self.today)
        self.ania_tomorrow = e('Ania jutro', date=self.days(1), assigned_member=self.other_child)
        self.pawel_later = e('Paweł później', date=self.days(3), assigned_member=self.second_parent)
        self.foreign = e(
            FOREIGN_SENTINEL, family=self.other_family, date=self.today,
            assigned_member=self.other_family_child,
        )

    def get(self, **params):
        return self.client.get(INDEX_URL, params).content.decode()

    def filter_links(self, html):
        """``[(href, key, current, label)]`` of the "Filtr wpisów" nav."""
        start = html.index('aria-label="Filtr wpisów"')
        nav = html[start:html.index('</nav>', start)]
        return [
            (href.replace('&amp;', '&'), key, bool(current), label)
            for href, key, current, label in FILTER_LINK_PATTERN.findall(nav)
        ]

    def assert_unfiltered(self, html):
        self.assertEqual(HIDDEN_GROUP_PATTERN.findall(html), [])
        self.assertEqual(
            [(key, current) for _href, key, current, _label in self.filter_links(html)],
            [('all', True), (f'member-{self.child.pk}', False), (f'member-{self.other_child.pk}', False)],
        )
        self.assertNotIn('member=', html.split('data-state-part="calendar-nav"', 1)[1])

    def test_filter_lists_all_then_each_active_child_in_pk_order(self):
        html = self.get()
        start = self.today.isoformat()

        self.assertEqual(
            self.filter_links(html),
            [
                (f'{INDEX_URL}?start={start}', 'all', True, 'Wszyscy'),
                (f'{INDEX_URL}?start={start}&member={self.child.pk}', f'member-{self.child.pk}',
                 False, 'Michał'),
                (f'{INDEX_URL}?start={start}&member={self.other_child.pk}',
                 f'member-{self.other_child.pk}', False, 'Ania'),
            ],
        )
        labels = [label for *_rest, label in self.filter_links(html)]
        for absent in ('Ewa', 'Paweł', 'Jolanta', 'Zosia', 'Kuba', 'Tomek'):
            with self.subTest(absent=absent):
                self.assertNotIn(absent, labels)
        self.assertIn('<p data-member-state="all" hidden>Pokazano: wszystkie wpisy</p>', html)
        self.assertIn(
            f'<p data-member-state="member-{self.child.pk}" hidden>Pokazano: Michał i Ogólne</p>', html
        )
        self.assertIn('role="status" aria-live="polite" data-live-region', html)

    def test_filter_links_keep_the_current_window(self):
        start = self.days(-14).isoformat()
        html = self.get(start=start, member=str(self.child.pk))

        for href, *_rest in self.filter_links(html):
            with self.subTest(href=href):
                self.assertTrue(href.startswith(f'{INDEX_URL}?start={start}'))

    def test_selected_child_renders_every_row_and_hides_other_groups(self):
        response = self.client.get(INDEX_URL, {'member': str(self.child.pk)})
        html = response.content.decode()

        self.assertEqual(
            sorted(self.rendered_rows(response)),
            sorted(entry.pk for entry in (
                self.michal_today, self.ania_today, self.ewa_today, self.zosia_today,
                self.family_today, self.ania_tomorrow, self.pawel_later,
            )),
        )
        today = day_html(html, self.today.isoformat())
        self.assertEqual(VISIBLE_GROUP_PATTERN.findall(today), [f'member-{self.child.pk}', 'family'])
        self.assertEqual(
            HIDDEN_GROUP_PATTERN.findall(today),
            [f'member-{self.other_child.pk}', f'member-{self.inactive_child.pk}',
             f'member-{self.parent.pk}'],
        )
        self.assertEqual(
            [(key, current) for _href, key, current, _label in self.filter_links(html)],
            [('all', False), (f'member-{self.child.pk}', True), (f'member-{self.other_child.pk}', False)],
        )
        self.assertNotContains(response, FOREIGN_SENTINEL)

    def test_empty_marker_follows_the_visible_groups(self):
        html = self.get(member=str(self.child.pk))

        cases = {
            # Michał and "Ogólne" are visible.
            self.today: False,
            # Only Ania's (hidden) group.
            self.days(1): True,
            # Only Paweł's (hidden) group.
            self.days(3): True,
            # No entries at all.
            self.days(2): True,
        }
        for day, empty in cases.items():
            with self.subTest(day=day):
                block = day_html(html, day.isoformat())
                self.assertEqual(EMPTY_DAY in block, empty)
                self.assertEqual('data-day-empty hidden>Brak wpisów' in block, not empty)
                self.assertEqual(
                    f'fn-calendar-day--empty" data-day-group="{day.isoformat()}"' in html, empty
                )
        unfiltered = self.get()
        self.assertNotIn(EMPTY_DAY, day_html(unfiltered, self.days(1).isoformat()))
        self.assertNotIn(EMPTY_DAY, day_html(unfiltered, self.days(3).isoformat()))

    def test_invalid_member_means_everyone_without_echoing_it(self):
        values = {
            'another family child': str(self.other_family_child.pk),
            'another family parent': str(self.other_family_parent.pk),
            'own parent': str(self.parent.pk),
            'second parent': str(self.second_parent.pk),
            'inactive parent': str(self.inactive_parent.pk),
            'inactive child': str(self.inactive_child.pk),
            'missing': '99999',
            'padded': f' {self.child.pk}',
            'leading zero': f'0{self.child.pk}',
            'negative': '-1',
            'junk': 'abc',
            'empty': '',
            'key form': f'member-{self.child.pk}',
        }
        for name, value in values.items():
            with self.subTest(name):
                response = self.client.get(INDEX_URL, {'member': value})
                html = response.content.decode()
                self.assert_unfiltered(html)
                self.assertNotContains(response, FOREIGN_SENTINEL)
                self.assertNotIn(f'member-{self.other_family_child.pk}"', html)
                self.assertNotIn(f'member={self.other_family_child.pk}', html)
                self.assertNotIn(f'member={self.other_family_parent.pk}', html)

    def test_member_is_carried_by_the_calendar_and_entry_links(self):
        html = self.get(member=str(self.child.pk))
        member = f'member={self.child.pk}'

        nav = html[html.index('data-state-part="calendar-nav"'):]
        nav = nav[:nav.index('</nav>')]
        self.assertEqual(
            re.findall(r'<a href="([^"]*)" data-member-link', nav),
            [
                f'{INDEX_URL}?start={self.days(-14).isoformat()}&amp;{member}',
                f'{INDEX_URL}?start={self.today.isoformat()}&amp;{member}',
                f'{INDEX_URL}?start={self.days(14).isoformat()}&amp;{member}',
            ],
        )
        self.assertIn(
            f'href="{detail_url(self.ania_today.pk)}?start={self.today.isoformat()}&amp;{member}"'
            ' data-member-link>',
            html,
        )
        unfiltered = self.get()
        self.assertIn(
            f'href="{detail_url(self.ania_today.pk)}?start={self.today.isoformat()}" data-member-link>',
            unfiltered,
        )

    def test_detail_back_link_and_delete_form_carry_a_validated_member(self):
        start = self.days(-14).isoformat()
        url = detail_url(self.michal_today.pk)

        html = self.client.get(url, {'start': start, 'member': str(self.child.pk)}).content.decode()
        self.assertIn(
            f'href="{INDEX_URL}?start={start}&amp;member={self.child.pk}">Wróć do listy</a>', html
        )
        self.assertIn(f'<input type="hidden" name="member" value="{self.child.pk}">', html)

        for value in (str(self.other_family_child.pk), str(self.parent.pk),
                      str(self.inactive_child.pk), 'abc'):
            with self.subTest(member=value):
                html = self.client.get(url, {'start': start, 'member': value}).content.decode()
                self.assertIn(f'href="{INDEX_URL}?start={start}">Wróć do listy</a>', html)
                self.assertNotIn('name="member"', html)
                self.assertNotIn(f'member={value}', html)

    def test_delete_returns_to_the_filtered_window_only_for_a_valid_member(self):
        start = self.days(14).isoformat()
        cases = {
            str(self.other_child.pk): f'{INDEX_URL}?start={start}&member={self.other_child.pk}',
            str(self.other_family_child.pk): f'{INDEX_URL}?start={start}',
            str(self.second_parent.pk): f'{INDEX_URL}?start={start}',
            str(self.inactive_child.pk): f'{INDEX_URL}?start={start}',
            'junk': f'{INDEX_URL}?start={start}',
        }
        for member, expected in cases.items():
            with self.subTest(member=member):
                entry = self.entry('Do usunięcia')
                response = self.client.post(
                    delete_url(entry.pk), {'start': start, 'member': member}
                )
                self.assertRedirects(response, expected)
                self.assertFalse(Entry.objects.filter(pk=entry.pk).exists())

    def test_family_without_active_children_has_no_filter(self):
        FamilyMember.objects.filter(pk__in=[self.child.pk, self.other_child.pk]).update(
            is_active=False
        )

        response = self.client.get(INDEX_URL, {'member': str(self.child.pk)})

        self.assertNotContains(response, 'data-member-filter')
        self.assertNotContains(response, 'Filtr wpisów')
        self.assertNotContains(response, 'data-live-region')
        self.assertNotContains(response, 'member=')
        self.assertEqual(HIDDEN_GROUP_PATTERN.findall(response.content.decode()), [])
