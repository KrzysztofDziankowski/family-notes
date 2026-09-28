"""Shared list contract: modes, partition boundaries, ordering and the row partial."""

import datetime

from django.http import HttpResponse
from django.template.loader import render_to_string
from django.test import TestCase, override_settings
from django.urls import path
from django.utils import timezone

from entries.classification.types import EntryType, SchoolItemKind
from entries.listing import (
    DEFAULT_LIST_MODE,
    LIST_MODES,
    PAST,
    SECTION_DATED,
    SECTION_PAST,
    SECTION_UNDATED,
    UPCOMING,
    normalize_list_mode,
    partition_entries,
)
from entries.models import Entry

from .test_classification_service import FamilyFixtureMixin

TODAY = datetime.date(2026, 9, 28)
YESTERDAY = TODAY - datetime.timedelta(days=1)
TOMORROW = TODAY + datetime.timedelta(days=1)
WARSAW = datetime.timezone(datetime.timedelta(hours=2))  # CEST on these dates


def _dummy(request, pk):
    return HttpResponse()


urlpatterns = [
    path('detail/<int:pk>/', _dummy, name='test_detail'),
    path('edit/<int:pk>/', _dummy, name='test_edit'),
]


class ListModeTests(TestCase):
    def test_modes_and_default(self):
        self.assertEqual(LIST_MODES, ('upcoming', 'past'))
        self.assertEqual(DEFAULT_LIST_MODE, UPCOMING)

    def test_known_modes_pass_through(self):
        self.assertEqual(normalize_list_mode('upcoming'), 'upcoming')
        self.assertEqual(normalize_list_mode('past'), 'past')

    def test_unknown_empty_and_missing_map_to_upcoming(self):
        for value in (None, '', 'PAST', 'future', 'past ', ['past']):
            with self.subTest(value=value):
                self.assertEqual(normalize_list_mode(value), UPCOMING)


class PartitionTests(FamilyFixtureMixin, TestCase):
    def _entry(self, content, date=None, time=None, school_item='', entry_type=None):
        return Entry.objects.create(
            family=self.family,
            entry_type=(entry_type or EntryType.NOTE).value,
            content=content,
            date=date,
            time=time,
            school_item=school_item,
        )

    def _set_timestamps(self, entry, *, created_at=None, updated_at=None):
        values = {}
        if created_at is not None:
            values['created_at'] = created_at
        if updated_at is not None:
            values['updated_at'] = updated_at
        Entry.objects.filter(pk=entry.pk).update(**values)

    def _sections(self, mode, today=TODAY):
        return {
            section.key: [entry.content for entry in section.entries]
            for section in partition_entries(Entry.objects.all(), mode, today)
        }

    def test_boundaries_between_upcoming_undated_and_past(self):
        self._entry('yesterday', date=YESTERDAY)
        self._entry('today', date=TODAY)
        self._entry('tomorrow', date=TOMORROW)
        self._entry('undated')

        self.assertEqual(
            self._sections(UPCOMING),
            {SECTION_DATED: ['today', 'tomorrow'], SECTION_UNDATED: ['undated']},
        )
        self.assertEqual(self._sections(PAST), {SECTION_PAST: ['yesterday']})

    def test_section_shape_and_order(self):
        upcoming = partition_entries(Entry.objects.all(), UPCOMING, TODAY)
        past = partition_entries(Entry.objects.all(), PAST, TODAY)

        self.assertEqual([s.key for s in upcoming], [SECTION_DATED, SECTION_UNDATED])
        self.assertEqual([s.key for s in past], [SECTION_PAST])

    def test_unknown_mode_is_treated_as_upcoming(self):
        self._entry('tomorrow', date=TOMORROW)
        self._entry('yesterday', date=YESTERDAY)

        self.assertEqual(
            self._sections('bogus'),
            {SECTION_DATED: ['tomorrow'], SECTION_UNDATED: []},
        )

    def test_upcoming_orders_by_date_then_time_missing_last_then_pk(self):
        self._entry('tomorrow-08', date=TOMORROW, time=datetime.time(8, 0))
        self._entry('today-no-time-a', date=TODAY)
        self._entry('today-18', date=TODAY, time=datetime.time(18, 0))
        self._entry('today-no-time-b', date=TODAY)
        self._entry('today-09-a', date=TODAY, time=datetime.time(9, 0))
        self._entry('today-09-b', date=TODAY, time=datetime.time(9, 0))

        self.assertEqual(
            self._sections(UPCOMING)[SECTION_DATED],
            [
                'today-09-a',
                'today-09-b',
                'today-18',
                'today-no-time-a',
                'today-no-time-b',
                'tomorrow-08',
            ],
        )

    def test_undated_orders_by_updated_at_desc_then_pk_desc(self):
        older = self._entry('older')
        newer = self._entry('newer')
        tie_a = self._entry('tie-a')
        tie_b = self._entry('tie-b')
        base = datetime.datetime(2026, 9, 20, 12, 0, tzinfo=datetime.timezone.utc)
        self._set_timestamps(older, updated_at=base)
        self._set_timestamps(newer, updated_at=base + datetime.timedelta(hours=2))
        self._set_timestamps(tie_a, updated_at=base + datetime.timedelta(hours=1))
        self._set_timestamps(tie_b, updated_at=base + datetime.timedelta(hours=1))

        self.assertEqual(
            self._sections(UPCOMING)[SECTION_UNDATED],
            ['newer', 'tie-b', 'tie-a', 'older'],
        )

    def test_past_orders_by_date_desc_then_time_desc_missing_last_then_pk_desc(self):
        earlier_day = YESTERDAY - datetime.timedelta(days=1)
        self._entry('earlier-20', date=earlier_day, time=datetime.time(20, 0))
        self._entry('yesterday-no-time-a', date=YESTERDAY)
        self._entry('yesterday-08', date=YESTERDAY, time=datetime.time(8, 0))
        self._entry('yesterday-no-time-b', date=YESTERDAY)
        self._entry('yesterday-17-a', date=YESTERDAY, time=datetime.time(17, 0))
        self._entry('yesterday-17-b', date=YESTERDAY, time=datetime.time(17, 0))
        self._entry('undated')

        self.assertEqual(
            self._sections(PAST)[SECTION_PAST],
            [
                'yesterday-17-b',
                'yesterday-17-a',
                'yesterday-08',
                'yesterday-no-time-b',
                'yesterday-no-time-a',
                'earlier-20',
            ],
        )

    def test_lucky_numbers_are_excluded_from_both_modes(self):
        lucky = SchoolItemKind.LUCKY_NUMBER.value
        self._entry('lucky-undated', school_item=lucky)
        self._entry('lucky-today', date=TODAY, school_item=lucky)
        self._entry('lucky-yesterday', date=YESTERDAY, school_item=lucky)
        self._entry('plain', date=TODAY)

        upcoming = self._sections(UPCOMING)
        past = self._sections(PAST)

        self.assertEqual(upcoming, {SECTION_DATED: ['plain'], SECTION_UNDATED: []})
        self.assertEqual(past, {SECTION_PAST: []})

    def test_undated_grade_uses_local_creation_day(self):
        grade = SchoolItemKind.GRADE.value
        today_grade = self._entry('grade-today', school_item=grade)
        yesterday_grade = self._entry('grade-yesterday', school_item=grade)
        self._set_timestamps(
            today_grade, created_at=datetime.datetime(2026, 9, 28, 10, 0, tzinfo=WARSAW)
        )
        self._set_timestamps(
            yesterday_grade,
            created_at=datetime.datetime(2026, 9, 27, 10, 0, tzinfo=WARSAW),
        )
        self._entry('today-09', date=TODAY, time=datetime.time(9, 0))
        self._entry('tomorrow', date=TOMORROW)
        self._entry('yesterday-12', date=YESTERDAY, time=datetime.time(12, 0))
        self._entry('two-days-ago', date=YESTERDAY - datetime.timedelta(days=1))

        upcoming = self._sections(UPCOMING)
        past = self._sections(PAST)

        # A grade has no time, so it sorts after timed entries on its day.
        self.assertEqual(upcoming[SECTION_DATED], ['today-09', 'grade-today', 'tomorrow'])
        self.assertEqual(upcoming[SECTION_UNDATED], [])
        self.assertEqual(past[SECTION_PAST], ['yesterday-12', 'grade-yesterday', 'two-days-ago'])
        self.assertIsNone(Entry.objects.get(pk=today_grade.pk).date)
        self.assertIsNone(Entry.objects.get(pk=yesterday_grade.pk).date)

    def test_grade_effective_date_follows_local_midnight_not_utc(self):
        grade = self._entry('grade-after-midnight', school_item=SchoolItemKind.GRADE.value)
        # 22:30 UTC on the 27th is 00:30 on the 28th in Europe/Warsaw.
        self._set_timestamps(
            grade,
            created_at=datetime.datetime(2026, 9, 27, 22, 30, tzinfo=datetime.timezone.utc),
        )

        self.assertEqual(self._sections(UPCOMING)[SECTION_DATED], ['grade-after-midnight'])
        self.assertEqual(self._sections(PAST)[SECTION_PAST], [])

    def test_undated_non_grade_note_never_gets_an_effective_date(self):
        note = self._entry('undated-note', school_item=SchoolItemKind.LATE_ARRIVAL.value)
        self._set_timestamps(
            note, created_at=datetime.datetime(2026, 9, 1, 10, 0, tzinfo=WARSAW)
        )

        self.assertEqual(self._sections(UPCOMING)[SECTION_UNDATED], ['undated-note'])
        self.assertEqual(self._sections(PAST)[SECTION_PAST], [])

    def test_helper_does_not_widen_the_callers_scope(self):
        self._entry('ours', date=TODAY)
        Entry.objects.create(
            family=self.other_family,
            entry_type=EntryType.NOTE.value,
            content='theirs',
            date=TODAY,
        )

        sections = partition_entries(
            Entry.objects.filter(family=self.family), UPCOMING, TODAY
        )

        self.assertEqual([e.content for e in sections[0].entries], ['ours'])


@override_settings(ROOT_URLCONF='entries.tests.test_entry_listing')
class EntryRowPartialTests(FamilyFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.entry = Entry.objects.create(
            family=self.family,
            entry_type=EntryType.CALENDAR_EVENT.value,
            content='Sprawdzian ' + 'x' * 200,
            date=datetime.date(2026, 9, 21),
            time=datetime.time(8, 15),
            assigned_member=self.child,
        )

    def _render(self, **context):
        context.setdefault('entry', self.entry)
        context.setdefault('detail_url_name', 'test_detail')
        return render_to_string('entries/_entry_row.html', context)

    def test_row_links_to_detail_and_shows_type_date_time_and_assignee(self):
        html = self._render()

        self.assertIn(f'href="/detail/{self.entry.pk}/"', html)
        self.assertIn('Wydarzenie', html)
        self.assertIn('poniedziałek, 21 września 2026, 08:15', html)
        self.assertIn('Michał', html)
        self.assertNotIn('x' * 200, html)
        self.assertNotIn('Edytuj', html)

    def test_hide_assignee_and_family_wide_label(self):
        self.assertNotIn('Michał', self._render(hide_assignee=True))

        self.entry.assigned_member = None
        self.assertIn('Cała rodzina', self._render())

    def test_optional_edit_link(self):
        html = self._render(edit_url_name='test_edit')

        self.assertIn(f'href="/edit/{self.entry.pk}/"', html)
        self.assertIn('Edytuj', html)

    def test_undated_entry_shows_polish_placeholder(self):
        self.entry.entry_type = EntryType.NOTE.value
        self.entry.date = None
        self.entry.time = None

        self.assertIn('Bez daty', self._render())

    def test_timezone_default_is_warsaw(self):
        # Guards the effective-date contract: "today" and grade days are local.
        self.assertEqual(str(timezone.get_current_timezone()), 'Europe/Warsaw')
