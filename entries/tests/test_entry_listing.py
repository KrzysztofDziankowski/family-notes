"""Shared list contract: modes, partition boundaries, ordering and the row partial."""

import datetime

from django.http import HttpResponse
from django.template.loader import render_to_string
from django.test import TestCase, override_settings
from django.urls import path
from django.utils import timezone, translation

from entries.classification.types import EntryType, SchoolItemKind
from entries.listing import (
    DEFAULT_LIST_MODE,
    GROUP_FAMILY,
    LIST_MODES,
    PAST,
    SECTION_DATED,
    SECTION_PAST,
    SECTION_UNDATED,
    UPCOMING,
    EntrySection,
    day_heading,
    group_by_assignee,
    group_by_day,
    normalize_list_mode,
    partition_entries,
)
from entries.models import Entry

from .test_classification_service import FamilyFixtureMixin, TwoParentFixtureMixin

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


class DayHeadingTests(TestCase):
    # TODAY (2026-09-28) is a Monday.
    def _heading(self, days):
        return day_heading(TODAY + datetime.timedelta(days=days), TODAY)

    def test_relative_days(self):
        self.assertEqual(self._heading(0), 'Dziś')
        self.assertEqual(self._heading(1), 'Jutro')
        self.assertEqual(self._heading(-1), 'Wczoraj')

    def test_weekday_name_within_six_days(self):
        self.assertEqual(self._heading(2), 'Środa')
        self.assertEqual(self._heading(6), 'Niedziela')
        self.assertEqual(self._heading(-6), 'Wtorek')

    def test_full_date_from_seven_days(self):
        self.assertEqual(self._heading(7), 'Poniedziałek, 5 października')
        self.assertEqual(self._heading(-7), 'Poniedziałek, 21 września')

    def test_other_year_adds_the_year(self):
        self.assertEqual(
            day_heading(datetime.date(2027, 1, 4), TODAY), 'Poniedziałek, 4 stycznia 2027'
        )
        self.assertEqual(
            day_heading(datetime.date(2025, 12, 30), TODAY), 'Wtorek, 30 grudnia 2025'
        )

    def test_polish_regardless_of_active_language(self):
        with translation.override('en'):
            self.assertEqual(self._heading(2), 'Środa')
            self.assertEqual(self._heading(7), 'Poniedziałek, 5 października')


class GroupByDayTests(FamilyFixtureMixin, TestCase):
    _entry = PartitionTests._entry
    _set_timestamps = PartitionTests._set_timestamps

    def test_keeps_input_order_and_groups_undated_grade_by_effective_date(self):
        grade = self._entry('grade-today', school_item=SchoolItemKind.GRADE.value)
        self._set_timestamps(
            grade, created_at=datetime.datetime(2026, 9, 28, 10, 0, tzinfo=WARSAW)
        )
        self._entry('today-09', date=TODAY, time=datetime.time(9, 0))
        self._entry('tomorrow', date=TOMORROW)
        self._entry('in-a-week', date=TODAY + datetime.timedelta(days=7))
        self._entry('yesterday', date=YESTERDAY)
        self._entry('two-days-ago', date=YESTERDAY - datetime.timedelta(days=1))

        upcoming = partition_entries(Entry.objects.all(), UPCOMING, TODAY)[0].entries
        past = partition_entries(Entry.objects.all(), PAST, TODAY)[0].entries

        def contents(groups):
            return [(heading, [e.content for e in rows]) for heading, rows in groups]

        self.assertEqual(
            contents(group_by_day(upcoming, TODAY)),
            [
                ('Dziś', ['today-09', 'grade-today']),
                ('Jutro', ['tomorrow']),
                ('Poniedziałek, 5 października', ['in-a-week']),
            ],
        )
        self.assertEqual(
            contents(group_by_day(past, TODAY)),
            [('Wczoraj', ['yesterday']), ('Sobota', ['two-days-ago'])],
        )

    def test_empty_input_has_no_groups(self):
        self.assertEqual(group_by_day([], TODAY), [])


class GroupByAssigneeTests(TwoParentFixtureMixin, TestCase):
    """S-08: assignee groups over partitioned sections (children, parents, family)."""

    def _entry(self, content, member=None, date=None, time=None):
        return Entry.objects.create(
            family=self.family,
            entry_type=EntryType.NOTE.value,
            content=content,
            date=date,
            time=time,
            assigned_member=member,
        )

    def _sections(self, mode):
        return partition_entries(
            Entry.objects.select_related('assigned_member'), mode, TODAY
        )

    def _shape(self, groups):
        return [
            (group.key, [(s.key, [e.content for e in s.entries]) for s in group.sections])
            for group in groups
        ]

    def _key(self, member):
        return f'member-{member.pk}'

    def test_mixed_assignees_group_children_then_parents_then_family(self):
        # Created out of group order, so the order comes from roles and pks.
        self._entry('family-tomorrow', date=TOMORROW)
        self._entry('pawel-undated', self.second_parent)
        self._entry('ewa-today', self.parent, date=TODAY)
        self._entry('ania-today', self.other_child, date=TODAY, time=datetime.time(8, 0))
        self._entry('michal-tomorrow', self.child, date=TOMORROW)
        self._entry('michal-today', self.child, date=TODAY, time=datetime.time(9, 0))
        self._entry('michal-undated', self.child)
        self._entry('family-undated')
        self._entry('michal-yesterday', self.child, date=YESTERDAY)
        self._entry('pawel-yesterday', self.second_parent, date=YESTERDAY)
        self._entry('family-yesterday', date=YESTERDAY)

        self.assertEqual(
            self._shape(group_by_assignee(self._sections(UPCOMING))),
            [
                (self._key(self.child), [
                    (SECTION_DATED, ['michal-today', 'michal-tomorrow']),
                    (SECTION_UNDATED, ['michal-undated']),
                ]),
                (self._key(self.other_child), [(SECTION_DATED, ['ania-today'])]),
                (self._key(self.parent), [(SECTION_DATED, ['ewa-today'])]),
                (self._key(self.second_parent), [(SECTION_UNDATED, ['pawel-undated'])]),
                (GROUP_FAMILY, [
                    (SECTION_DATED, ['family-tomorrow']),
                    (SECTION_UNDATED, ['family-undated']),
                ]),
            ],
        )
        self.assertEqual(
            self._shape(group_by_assignee(self._sections(PAST))),
            [
                (self._key(self.child), [(SECTION_PAST, ['michal-yesterday'])]),
                (self._key(self.second_parent), [(SECTION_PAST, ['pawel-yesterday'])]),
                (GROUP_FAMILY, [(SECTION_PAST, ['family-yesterday'])]),
            ],
        )

    def test_groups_carry_their_member(self):
        self._entry('michal', self.child)
        self._entry('family')

        groups = group_by_assignee(self._sections(UPCOMING))

        self.assertEqual([group.member for group in groups], [self.child, None])

    def test_inactive_child_groups_with_children_before_parents(self):
        self._entry('ewa', self.parent)
        self._entry('zosia', self.inactive_child)
        self._entry('jolanta', self.inactive_parent)
        self._entry('michal', self.child)

        groups = group_by_assignee(self._sections(UPCOMING))

        self.assertEqual(
            [group.key for group in groups],
            [
                self._key(self.child),
                self._key(self.inactive_child),
                self._key(self.parent),
                self._key(self.inactive_parent),
            ],
        )

    def test_group_with_only_undated_rows_omits_the_empty_dated_section(self):
        self._entry('ania-undated', self.other_child)
        self._entry('michal-today', self.child, date=TODAY)

        self.assertEqual(
            self._shape(group_by_assignee(self._sections(UPCOMING))),
            [
                (self._key(self.child), [(SECTION_DATED, ['michal-today'])]),
                (self._key(self.other_child), [(SECTION_UNDATED, ['ania-undated'])]),
            ],
        )

    def test_empty_input_has_no_groups(self):
        self.assertEqual(group_by_assignee(self._sections(UPCOMING)), [])
        self.assertEqual(group_by_assignee([]), [])

    def test_order_within_groups_matches_partition_and_rows_appear_once(self):
        members = [self.child, None, self.second_parent, self.other_child, self.parent]
        for index in range(15):
            member = members[index % len(members)]
            day = TODAY + datetime.timedelta(days=(7 - index) % 4)
            self._entry(f'dated-{index}', member, date=day, time=datetime.time(8 + index % 3, 0))
            self._entry(f'undated-{index}', member)
            self._entry(f'past-{index}', member, date=YESTERDAY - datetime.timedelta(days=index % 3))

        for mode in (UPCOMING, PAST):
            with self.subTest(mode=mode):
                sections = self._sections(mode)
                expected = {s.key: [e.pk for e in s.entries] for s in sections}
                groups = group_by_assignee(self._sections(mode))

                grouped = [e.pk for g in groups for s in g.sections for e in s.entries]
                self.assertEqual(len(grouped), len(set(grouped)))
                self.assertEqual(
                    sorted(grouped), sorted(pk for pks in expected.values() for pk in pks)
                )
                for group in groups:
                    for section in group.sections:
                        pks = [e.pk for e in section.entries]
                        self.assertEqual(
                            pks, [pk for pk in expected[section.key] if pk in set(pks)]
                        )
                        assignees = {e.assigned_member_id for e in section.entries}
                        self.assertEqual(len(assignees), 1)

    def test_sections_are_evaluated_once_without_extra_queries(self):
        self._entry('michal', self.child, date=TODAY)
        self._entry('ewa', self.parent)
        self._entry('family')
        sections = self._sections(UPCOMING)

        with self.assertNumQueries(len(sections)):
            group_by_assignee(sections)

    def test_helper_does_not_scope_by_family(self):
        Entry.objects.create(
            family=self.other_family,
            entry_type=EntryType.NOTE.value,
            content='theirs',
            assigned_member=self.other_family_child,
        )
        rows = list(Entry.objects.select_related('assigned_member'))

        groups = group_by_assignee([EntrySection(SECTION_UNDATED, rows)])

        self.assertEqual(
            [group.key for group in groups], [self._key(self.other_family_child)]
        )


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

    def test_hide_date_shows_only_the_time(self):
        html = self._render(hide_date=True)

        self.assertIn('<span>08:15</span>', html)
        self.assertNotIn('września', html)

        self.entry.time = None
        html = self._render(hide_date=True)
        self.assertNotIn('września', html)
        self.assertNotIn('Bez daty', html)

    def test_undated_entry_shows_polish_placeholder(self):
        self.entry.entry_type = EntryType.NOTE.value
        self.entry.date = None
        self.entry.time = None

        self.assertIn('Bez daty', self._render())

    def test_timezone_default_is_warsaw(self):
        # Guards the effective-date contract: "today" and grade days are local.
        self.assertEqual(str(timezone.get_current_timezone()), 'Europe/Warsaw')
