import datetime

from django.http import QueryDict
from django.test import TestCase
from django.urls import resolve, reverse
from django.utils import timezone

from entries.api_views import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    EntriesQuery,
    entries_page,
    parse_entries_query,
    serialize_entry,
)
from entries.classification.types import EntryType, SchoolItemKind
from entries.models import Entry
from entries.services import automation_family_entries
from family_access.models import AutomationToken, Family, FamilyMember
from family_access.tests.test_automation import AutomationFixtureMixin

FOREIGN_SENTINEL = 'SENTINEL-obca-rodzina'
EXPECTED_FIELDS = {
    'id',
    'entry_type',
    'content',
    'date',
    'time',
    'assigned_member',
    'school_item',
    'school_subject',
    'source',
    'created_at',
    'updated_at',
}
# The response shape before S-01; every one of these keys must stay unchanged.
PRE_SUBJECT_FIELDS = EXPECTED_FIELDS - {'school_subject'}


def query(**params):
    """Build a QueryDict exactly as Django would parse the URL query string."""
    result = QueryDict(mutable=True)
    for name, value in params.items():
        result[name] = value
    return result


class EntriesQueryParserTests(TestCase):
    def test_defaults_without_parameters(self):
        self.assertEqual(
            parse_entries_query(query()),
            EntriesQuery(
                limit=DEFAULT_LIMIT,
                offset=0,
                date_from=None,
                date_to=None,
                include_undated=True,
            ),
        )
        self.assertEqual(DEFAULT_LIMIT, 100)
        self.assertEqual(MAX_LIMIT, 500)

    def test_limit_bounds(self):
        self.assertEqual(parse_entries_query(query(limit='1')).limit, 1)
        self.assertEqual(parse_entries_query(query(limit='500')).limit, 500)
        for value in ('0', '501', '-1', '', 'abc', '1.5', ' 5', '+5', '1_0', '١'):
            with self.subTest(limit=value):
                self.assertIsNone(parse_entries_query(query(limit=value)))

    def test_offset_is_non_negative_integer(self):
        self.assertEqual(parse_entries_query(query(offset='0')).offset, 0)
        self.assertEqual(parse_entries_query(query(offset='1000')).offset, 1000)
        self.assertEqual(parse_entries_query(query(offset='9' * 18)).offset, int('9' * 18))
        for value in ('-1', '', 'x', '2.0', '9223372036854775808', '0' * 5000):
            with self.subTest(offset=value):
                self.assertIsNone(parse_entries_query(query(offset=value)))

    def test_dates_accept_iso_format_only(self):
        parsed = parse_entries_query(query(date_from='2026-09-01', date_to='2026-09-30'))
        self.assertEqual(parsed.date_from, datetime.date(2026, 9, 1))
        self.assertEqual(parsed.date_to, datetime.date(2026, 9, 30))
        for value in ('20260901', '2026-9-1', '01.09.2026', '2026-09-01T00:00', '', 'dziś'):
            with self.subTest(date=value):
                self.assertIsNone(parse_entries_query(query(date_from=value)))
                self.assertIsNone(parse_entries_query(query(date_to=value)))

    def test_impossible_day_is_invalid_not_an_error(self):
        self.assertIsNone(parse_entries_query(query(date_from='2026-02-30')))
        self.assertIsNone(parse_entries_query(query(date_to='2026-13-01')))

    def test_inverted_range_is_invalid(self):
        self.assertIsNone(parse_entries_query(query(date_from='2026-09-02', date_to='2026-09-01')))
        same_day = parse_entries_query(query(date_from='2026-09-01', date_to='2026-09-01'))
        self.assertEqual(same_day.date_from, same_day.date_to)

    def test_include_undated_default_depends_on_bounds(self):
        self.assertTrue(parse_entries_query(query()).include_undated)
        self.assertFalse(parse_entries_query(query(date_from='2026-09-01')).include_undated)
        self.assertFalse(parse_entries_query(query(date_to='2026-09-01')).include_undated)

    def test_include_undated_is_case_insensitive_boolean(self):
        for value, expected in (('true', True), ('True', True), ('TRUE', True),
                                ('false', False), ('False', False), ('FALSE', False)):
            with self.subTest(include_undated=value):
                parsed = parse_entries_query(query(date_from='2026-09-01', include_undated=value))
                self.assertIs(parsed.include_undated, expected)
        self.assertFalse(parse_entries_query(query(include_undated='false')).include_undated)

    def test_include_undated_rejects_non_boolean_words(self):
        for value in ('1', '0', 'yes', 'no', '', 'tak'):
            with self.subTest(include_undated=value):
                self.assertIsNone(parse_entries_query(query(include_undated=value)))

    def test_unknown_parameters_are_ignored(self):
        self.assertEqual(
            parse_entries_query(query(family='999', member='1', page='2')),
            parse_entries_query(query()),
        )


class EntriesApiDataMixin(AutomationFixtureMixin):
    def setUp(self):
        super().setUp()
        self.other_family = Family.objects.create(name='The Other Family')
        self.other_parent = self.create_member(
            'other-parent', FamilyMember.Role.PARENT, family=self.other_family
        )

    def entry(self, content, day=None, *, family=None, **values):
        values.setdefault('entry_type', EntryType.NOTE.value)
        return Entry.objects.create(
            family=family or self.family, content=content, date=day, **values
        )

    def contents(self, queryset):
        return [entry.content for entry in queryset]


class AutomationFamilyEntriesFilterTests(EntriesApiDataMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.before = self.entry('before', datetime.date(2026, 8, 31))
        self.first_day = self.entry('first-day', datetime.date(2026, 9, 1))
        self.middle = self.entry('middle', datetime.date(2026, 9, 15))
        self.last_day = self.entry('last-day', datetime.date(2026, 9, 30))
        self.after = self.entry('after', datetime.date(2026, 10, 1))
        self.undated = self.entry('undated')
        self.entry(FOREIGN_SENTINEL, datetime.date(2026, 9, 15), family=self.other_family)
        self.entry(FOREIGN_SENTINEL, family=self.other_family)

    def read(self, **filters):
        return self.contents(automation_family_entries(self.parent, **filters))

    def assertNoForeignEntries(self, contents):
        self.assertNotIn(FOREIGN_SENTINEL, contents)

    def test_no_bounds_returns_dated_and_undated_family_entries(self):
        contents = self.read()

        self.assertEqual(
            contents, ['before', 'first-day', 'middle', 'last-day', 'after', 'undated']
        )
        self.assertNoForeignEntries(contents)

    def test_explicit_false_without_bounds_returns_only_dated_entries(self):
        contents = self.read(include_undated=False)

        self.assertEqual(contents, ['before', 'first-day', 'middle', 'last-day', 'after'])

    def test_both_bounds_are_inclusive(self):
        contents = self.read(
            date_from=datetime.date(2026, 9, 1),
            date_to=datetime.date(2026, 9, 30),
            include_undated=False,
        )

        self.assertEqual(contents, ['first-day', 'middle', 'last-day'])
        self.assertNoForeignEntries(contents)

    def test_date_from_alone_is_inclusive_lower_bound(self):
        contents = self.read(date_from=datetime.date(2026, 9, 30), include_undated=False)

        self.assertEqual(contents, ['last-day', 'after'])

    def test_date_to_alone_is_inclusive_upper_bound(self):
        contents = self.read(date_to=datetime.date(2026, 9, 1), include_undated=False)

        self.assertEqual(contents, ['before', 'first-day'])

    def test_range_with_undated_adds_undated_entries(self):
        contents = self.read(
            date_from=datetime.date(2026, 9, 15),
            date_to=datetime.date(2026, 9, 15),
            include_undated=True,
        )

        self.assertEqual(contents, ['middle', 'undated'])
        self.assertNoForeignEntries(contents)

    def test_single_bound_with_undated_adds_undated_entries(self):
        contents = self.read(date_to=datetime.date(2026, 8, 31), include_undated=True)

        self.assertEqual(contents, ['before', 'undated'])

    def test_parsed_defaults_drive_the_same_filter(self):
        parsed = parse_entries_query(query(date_from='2026-09-01', date_to='2026-09-30'))
        contents = self.read(
            date_from=parsed.date_from,
            date_to=parsed.date_to,
            include_undated=parsed.include_undated,
        )

        self.assertEqual(contents, ['first-day', 'middle', 'last-day'])

    def test_all_entry_types_and_sources_are_included(self):
        Entry.objects.filter(family=self.family).delete()
        self.entry('todo', entry_type=EntryType.TODO.value)
        self.entry(
            'event', datetime.date(2026, 9, 2), entry_type=EntryType.CALENDAR_EVENT.value
        )
        self.entry('automated', source=Entry.Source.EDUVULCAN)

        self.assertEqual(self.read(), ['todo', 'event', 'automated'])

    def test_inactive_membership_reads_nothing(self):
        self.parent.is_active = False

        self.assertEqual(self.read(), [])


class SerializeEntryTests(EntriesApiDataMixin, TestCase):
    def test_full_entry_exposes_domain_fields_as_iso_strings(self):
        entry = self.entry(
            'Sprawdzian z biologii',
            datetime.date(2026, 9, 28),
            entry_type=EntryType.CALENDAR_EVENT.value,
            time=datetime.time(8, 30),
            assigned_member=self.child,
            school_item=SchoolItemKind.TEST.value,
            school_subject='Biologia',
            source=Entry.Source.EDUVULCAN,
        )
        entry = automation_family_entries(self.parent).get(pk=entry.pk)

        data = serialize_entry(entry)

        self.assertEqual(set(data), EXPECTED_FIELDS)
        self.assertTrue(PRE_SUBJECT_FIELDS < set(data))
        self.assertEqual(data['school_subject'], 'Biologia')
        self.assertEqual(data['id'], entry.pk)
        self.assertEqual(data['entry_type'], 'calendar_event')
        self.assertEqual(data['content'], 'Sprawdzian z biologii')
        self.assertEqual(data['date'], '2026-09-28')
        self.assertEqual(data['time'], '08:30:00')
        self.assertEqual(data['assigned_member'], {'display_name': 'Child'})
        self.assertEqual(data['school_item'], SchoolItemKind.TEST.value)
        self.assertEqual(data['source'], 'eduvulcan')
        self.assertEqual(data['created_at'], entry.created_at.isoformat())
        self.assertEqual(data['updated_at'], entry.updated_at.isoformat())
        self.assertEqual(datetime.datetime.fromisoformat(data['created_at']), entry.created_at)

    def test_missing_values_are_null(self):
        entry = self.entry('Kupić zeszyt', entry_type=EntryType.TODO.value)

        data = serialize_entry(entry)

        self.assertIsNone(data['date'])
        self.assertIsNone(data['time'])
        self.assertIsNone(data['assigned_member'])
        self.assertEqual(entry.school_item, '')
        self.assertIsNone(data['school_item'])
        self.assertEqual(entry.school_subject, '')
        self.assertIsNone(data['school_subject'])
        self.assertEqual(data['source'], 'manual')

    def test_inactive_historical_member_keeps_display_name(self):
        entry = self.entry('Stary wpis', assigned_member=self.child)
        FamilyMember.objects.filter(pk=self.child.pk).update(is_active=False)
        entry = automation_family_entries(self.parent).get(pk=entry.pk)

        data = serialize_entry(entry)

        self.assertEqual(data['assigned_member'], {'display_name': 'Child'})

    def test_internal_fields_are_never_exposed(self):
        entry = self.entry(
            'Wpis rodzica', created_by=self.parent, assigned_member=self.child,
        )
        Entry.objects.filter(pk=entry.pk).update(
            submission_key='00000000-0000-4000-8000-0000000000aa'
        )
        entry = automation_family_entries(self.parent).get(pk=entry.pk)

        data = serialize_entry(entry)

        for name in ('family', 'family_id', 'created_by', 'created_by_id', 'submission_key',
                     'assigned_member_id', 'token'):
            self.assertNotIn(name, data)
        self.assertEqual(set(data['assigned_member']), {'display_name'})
        flattened = repr(data)
        self.assertNotIn('00000000-0000-4000-8000-0000000000aa', flattened)
        self.assertNotIn(self.family.name, flattened)
        self.assertNotIn('parent@example.test', flattened)


class EntriesOrderingAndPaginationTests(EntriesApiDataMixin, TestCase):
    def page(self, limit, offset, **filters):
        return entries_page(
            automation_family_entries(self.parent, **filters),
            EntriesQuery(limit=limit, offset=offset),
        )

    def ids(self, page):
        return [record['id'] for record in page['results']]

    def test_order_is_created_at_then_id(self):
        base = timezone.now()
        late = self.entry('late')
        early = self.entry('early')
        tie_high = self.entry('tie-high')
        tie_low = self.entry('tie-low')
        Entry.objects.filter(pk=late.pk).update(created_at=base + datetime.timedelta(hours=2))
        Entry.objects.filter(pk=early.pk).update(created_at=base - datetime.timedelta(hours=1))
        # Equal timestamps fall back to id, independent of insertion order.
        Entry.objects.filter(pk__in=[tie_high.pk, tie_low.pk]).update(created_at=base)

        ordered = list(automation_family_entries(self.parent).values_list('pk', flat=True))

        self.assertEqual(
            ordered, [early.pk, min(tie_high.pk, tie_low.pk), max(tie_high.pk, tie_low.pk), late.pk]
        )

    def test_envelope_counts_filtered_total_before_paging(self):
        entries = [self.entry(f'entry-{index}') for index in range(5)]
        self.entry(FOREIGN_SENTINEL, family=self.other_family)

        page = self.page(limit=2, offset=1)

        self.assertEqual(set(page), {'count', 'limit', 'offset', 'results'})
        self.assertEqual(page['count'], 5)
        self.assertEqual(page['limit'], 2)
        self.assertEqual(page['offset'], 1)
        self.assertEqual(self.ids(page), [entries[1].pk, entries[2].pk])

    def test_offset_past_end_returns_empty_results_with_count(self):
        self.entry('only')

        page = self.page(limit=10, offset=5)

        self.assertEqual(page['count'], 1)
        self.assertEqual(page['results'], [])

    def test_entry_added_between_pages_is_not_repeated(self):
        entries = [self.entry(f'entry-{index}') for index in range(4)]

        first = self.page(limit=2, offset=0)
        added = self.entry('added-between-pages')
        second = self.page(limit=2, offset=2)
        third = self.page(limit=2, offset=4)

        self.assertEqual(self.ids(first), [entries[0].pk, entries[1].pk])
        self.assertEqual(self.ids(second), [entries[2].pk, entries[3].pk])
        self.assertEqual(self.ids(third), [added.pk])
        seen = self.ids(first) + self.ids(second) + self.ids(third)
        self.assertEqual(len(seen), len(set(seen)))

    def test_page_serialization_avoids_per_entry_member_queries(self):
        for index in range(3):
            self.entry(f'assigned-{index}', assigned_member=self.child)

        with self.assertNumQueries(2):
            # One count, one page select joined with the assigned member.
            page = self.page(limit=10, offset=0)

        self.assertEqual(len(page['results']), 3)


class FamilyEntriesEndpointTests(EntriesApiDataMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse('automation:entries_list')
        self.token, self.secret = AutomationToken.issue(self.parent, 'Telefon')
        self.foreign_token, self.foreign_secret = AutomationToken.issue(
            self.other_parent, 'Obcy telefon'
        )
        self.dated = self.entry(
            'Sprawdzian z biologii',
            datetime.date(2026, 9, 28),
            entry_type=EntryType.CALENDAR_EVENT.value,
            time=datetime.time(8, 30),
            assigned_member=self.child,
            school_item=SchoolItemKind.TEST.value,
            source=Entry.Source.EDUVULCAN,
        )
        self.todo = self.entry('Kupić zeszyt', entry_type=EntryType.TODO.value)
        self.note = self.entry('Notatka rodzica', datetime.date(2026, 10, 5))
        self.foreign_dated = self.entry(
            FOREIGN_SENTINEL, datetime.date(2026, 9, 28), family=self.other_family
        )
        self.foreign_undated = self.entry(FOREIGN_SENTINEL, family=self.other_family)

    def get(self, secret=None, authorization=None, **params):
        if authorization is None:
            authorization = f'Bearer {secret or self.secret}'
        headers = {} if authorization is False else {'HTTP_AUTHORIZATION': authorization}
        return self.client.get(self.url, params, **headers)

    def assert_rejected(self, response):
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {'error': 'invalid_token'})
        self.assertEqual(response['WWW-Authenticate'], 'Bearer')
        self.assertNotIn(FOREIGN_SENTINEL, response.content.decode())
        self.assertNotIn(self.dated.content, response.content.decode())

    def ids(self, response):
        return [record['id'] for record in response.json()['results']]

    # --- 200 contract ---------------------------------------------------------

    def test_route_is_under_automation_prefix(self):
        self.assertEqual(self.url, '/api/automation/entries/')
        self.assertTrue(resolve(self.url).func.csrf_exempt)

    def test_active_parent_token_reads_own_family_entries_only(self):
        response = self.get()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')
        body = response.json()
        self.assertEqual(set(body), {'count', 'limit', 'offset', 'results'})
        self.assertEqual(body['count'], 3)
        self.assertEqual(body['limit'], 100)
        self.assertEqual(body['offset'], 0)
        self.assertEqual(self.ids(response), [self.dated.pk, self.todo.pk, self.note.pk])
        for record in body['results']:
            self.assertEqual(set(record), EXPECTED_FIELDS)
        self.assertNotIn(FOREIGN_SENTINEL, response.content.decode())

    def test_records_carry_all_types_sources_and_undated_entries(self):
        records = {record['id']: record for record in self.get().json()['results']}

        self.assertEqual(
            {record['entry_type'] for record in records.values()},
            {'calendar_event', 'todo', 'note'},
        )
        self.assertEqual({record['source'] for record in records.values()}, {'eduvulcan', 'manual'})
        self.assertEqual(
            records[self.dated.pk],
            {
                'id': self.dated.pk,
                'entry_type': 'calendar_event',
                'content': 'Sprawdzian z biologii',
                'date': '2026-09-28',
                'time': '08:30:00',
                'assigned_member': {'display_name': 'Child'},
                'school_item': SchoolItemKind.TEST.value,
                'school_subject': None,
                'source': 'eduvulcan',
                'created_at': records[self.dated.pk]['created_at'],
                'updated_at': records[self.dated.pk]['updated_at'],
            },
        )
        undated = records[self.todo.pk]
        self.assertIsNone(undated['date'])
        self.assertIsNone(undated['time'])
        self.assertIsNone(undated['assigned_member'])
        self.assertIsNone(undated['school_item'])

    def test_foreign_family_sees_only_its_own_entries(self):
        response = self.get(secret=self.foreign_secret)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['count'], 2)
        self.assertEqual(
            self.ids(response), [self.foreign_dated.pk, self.foreign_undated.pk]
        )
        self.assertNotIn(self.dated.content, response.content.decode())

    def test_foreign_entry_never_counts_even_on_matching_filters(self):
        response = self.get(date_from='2026-09-28', date_to='2026-09-28', include_undated='true')

        self.assertEqual(response.json()['count'], 2)
        self.assertEqual(self.ids(response), [self.dated.pk, self.todo.pk])
        self.assertNotIn(FOREIGN_SENTINEL, response.content.decode())

    def test_client_cannot_select_another_family(self):
        response = self.get(family=str(self.other_family.pk), family_id=str(self.other_family.pk))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['count'], 3)
        self.assertNotIn(FOREIGN_SENTINEL, response.content.decode())

    def test_date_range_excludes_undated_by_default(self):
        response = self.get(date_from='2026-09-01', date_to='2026-09-30')

        self.assertEqual(response.json()['count'], 1)
        self.assertEqual(self.ids(response), [self.dated.pk])

    def test_explicit_false_without_bounds_returns_dated_only(self):
        response = self.get(include_undated='FALSE')

        self.assertEqual(self.ids(response), [self.dated.pk, self.note.pk])

    def test_pagination_counts_before_paging(self):
        response = self.get(limit='1', offset='1')

        body = response.json()
        self.assertEqual(body['count'], 3)
        self.assertEqual(body['limit'], 1)
        self.assertEqual(body['offset'], 1)
        self.assertEqual(self.ids(response), [self.todo.pk])

    def test_offset_past_end_returns_empty_page(self):
        response = self.get(offset='50')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'count': 3, 'limit': 100, 'offset': 50, 'results': []})

    def test_family_without_entries_returns_empty_page(self):
        Entry.objects.filter(family=self.family).delete()

        response = self.get()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'count': 0, 'limit': 100, 'offset': 0, 'results': []})

    def test_order_is_created_at_then_id(self):
        Entry.objects.filter(pk=self.dated.pk).update(
            created_at=timezone.now() + datetime.timedelta(hours=1)
        )

        self.assertEqual(self.ids(self.get()), [self.todo.pk, self.note.pk, self.dated.pk])

    def test_response_never_echoes_token_secret(self):
        response = self.get()

        content = response.content.decode()
        self.assertNotIn(self.secret, content)
        self.assertNotIn(self.token.prefix, content)
        self.assertNotIn('Telefon', content)

    # --- 400 contract ---------------------------------------------------------

    def test_invalid_query_returns_400_without_entries(self):
        for params in (
            {'limit': '0'},
            {'limit': '501'},
            {'limit': 'abc'},
            {'offset': '-1'},
            {'offset': '9223372036854775808'},
            {'offset': '0' * 5000},
            {'limit': '0' * 5000},
            {'date_from': '2026-02-30'},
            {'date_to': '28.09.2026'},
            {'date_from': '2026-09-02', 'date_to': '2026-09-01'},
            {'include_undated': '1'},
            {'include_undated': ''},
        ):
            with self.subTest(params=params):
                response = self.get(**params)

                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json(), {'error': 'invalid_query'})
                self.assertNotIn(self.dated.content, response.content.decode())

    def test_invalid_token_wins_over_invalid_query(self):
        self.assert_rejected(self.get(authorization=False, limit='0'))

    # --- 401 contract ---------------------------------------------------------

    def test_header_problems_are_rejected(self):
        for authorization in (
            False,
            f'Basic {self.secret}',
            'Bearer',
            f'Bearer {self.secret} extra',
            'Bearer fnat_unknown-secret',
        ):
            with self.subTest(authorization=authorization):
                self.assert_rejected(self.get(authorization=authorization))

    def test_revoked_token_is_rejected(self):
        AutomationToken.objects.filter(pk=self.token.pk).update(revoked_at=timezone.now())

        self.assert_rejected(self.get())

    def test_revocation_takes_effect_immediately(self):
        self.assertEqual(self.get().status_code, 200)

        AutomationToken.objects.filter(pk=self.token.pk).update(revoked_at=timezone.now())

        self.assert_rejected(self.get())

    def test_expired_token_is_rejected(self):
        AutomationToken.objects.filter(pk=self.token.pk).update(
            expires_at=timezone.now() - datetime.timedelta(seconds=1)
        )

        self.assert_rejected(self.get())

    def test_owner_that_became_child_is_rejected(self):
        self.parent.role = FamilyMember.Role.CHILD
        self.parent.save(update_fields=('role',))

        self.assert_rejected(self.get())

    def test_inactive_parent_membership_is_rejected(self):
        self.parent.is_active = False
        self.parent.save(update_fields=('is_active',))

        self.assert_rejected(self.get())

    def test_inactive_user_account_is_rejected(self):
        user = self.parent.user
        user.is_active = False
        user.save(update_fields=('is_active',))

        self.assert_rejected(self.get())

    def test_inactive_family_is_rejected(self):
        self.family.is_active = False
        self.family.save(update_fields=('is_active',))

        self.assert_rejected(self.get())

    def test_signed_in_session_without_token_is_rejected(self):
        self.client.force_login(self.parent.user)

        self.assert_rejected(self.get(authorization=False))

    # --- 405 contract ---------------------------------------------------------

    def snapshot(self):
        return list(Entry.objects.order_by('pk').values())

    def test_mutating_methods_are_not_allowed_and_change_nothing(self):
        before = self.snapshot()
        payload = '{"content": "Nowy wpis", "entry_type": "note"}'
        client = self.client_class(enforce_csrf_checks=True)

        for method in ('post', 'put', 'patch', 'delete'):
            for headers in ({'HTTP_AUTHORIZATION': f'Bearer {self.secret}'}, {}):
                with self.subTest(method=method, authenticated=bool(headers)):
                    response = getattr(client, method)(
                        self.url, data=payload, content_type='application/json', **headers
                    )

                    self.assertEqual(response.status_code, 405)
                    self.assertEqual(response['Allow'], 'GET')

        self.assertEqual(self.snapshot(), before)
        self.token.refresh_from_db()
        # 405 is answered before authentication, so the token is never touched.
        self.assertIsNone(self.token.last_used_at)


class TwoParentApiTests(EntriesApiDataMixin, TestCase):
    """S-07: the automation API names a parent assignee like any other member."""

    def setUp(self):
        super().setUp()
        self.second_parent = self.create_member('second-parent', FamilyMember.Role.PARENT)
        _, self.secret = AutomationToken.issue(self.parent, 'Telefon')
        self.mine = self.entry('Odebrać paczkę', assigned_member=self.parent)
        self.theirs = self.entry('Umówić mechanika', assigned_member=self.second_parent)
        self.entry(FOREIGN_SENTINEL, family=self.other_family, assigned_member=self.other_parent)

    def test_parent_assignees_are_serialized_by_display_name(self):
        response = self.client.get(
            reverse('automation:entries_list'), HTTP_AUTHORIZATION=f'Bearer {self.secret}'
        )

        self.assertEqual(response.status_code, 200)
        records = {record['id']: record for record in response.json()['results']}
        self.assertEqual(set(records), {self.mine.pk, self.theirs.pk})
        self.assertEqual(records[self.mine.pk]['assigned_member'], {'display_name': 'Parent'})
        self.assertEqual(
            records[self.theirs.pk]['assigned_member'], {'display_name': 'Second Parent'}
        )
        self.assertNotIn(FOREIGN_SENTINEL, response.content.decode())


class MultiFamilyTokenTests(TestCase):
    """S-16: a token stays bound to its membership's family, whatever the session says."""

    def setUp(self):
        from django.contrib.auth import get_user_model

        from family_access.context import SESSION_KEY

        self.session_key = SESSION_KEY
        self.family_a = Family.objects.create(name='Rodzina testowa')
        self.family_b = Family.objects.create(name='Inna rodzina')
        self.user = get_user_model().objects.create_user(username='ewa', email='ewa@example.test')
        self.parent_a = FamilyMember.objects.create(
            user=self.user, family=self.family_a, role=FamilyMember.Role.PARENT, display_name='Ewa',
        )
        self.parent_b = FamilyMember.objects.create(
            user=self.user, family=self.family_b, role=FamilyMember.Role.PARENT, display_name='Ewa',
        )
        self.entry_a = Entry.objects.create(
            family=self.family_a, entry_type=EntryType.TODO.value, content='Wpis A',
        )
        self.entry_b = Entry.objects.create(
            family=self.family_b, entry_type=EntryType.TODO.value, content=FOREIGN_SENTINEL,
        )
        _, self.secret_a = AutomationToken.issue(self.parent_a, 'Telefon A')
        _, self.secret_b = AutomationToken.issue(self.parent_b, 'Telefon B')
        self.url = reverse('automation:entries_list')

    def get(self, secret):
        return self.client.get(self.url, HTTP_AUTHORIZATION=f'Bearer {secret}')

    def ids(self, response):
        return [record['id'] for record in response.json()['results']]

    def test_token_reads_only_its_family_even_when_the_session_is_on_another(self):
        self.client.force_login(self.user)
        session = self.client.session
        session[self.session_key] = self.family_b.pk
        session.save()

        response = self.get(self.secret_a)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.ids(response), [self.entry_a.pk])
        self.assertNotIn(FOREIGN_SENTINEL, response.content.decode())

    def test_api_ignores_a_client_supplied_family(self):
        response = self.client.get(
            self.url, {'family': self.family_b.pk, 'family_id': self.family_b.pk},
            HTTP_AUTHORIZATION=f'Bearer {self.secret_a}',
        )

        self.assertNotIn(self.entry_b.pk, self.ids(response) if response.status_code == 200 else [])
        self.assertNotIn(FOREIGN_SENTINEL, response.content.decode())

    def test_deactivating_one_membership_disables_only_its_token(self):
        self.parent_a.is_active = False
        self.parent_a.save(update_fields=['is_active'])

        self.assertEqual(self.get(self.secret_a).status_code, 401)
        response = self.get(self.secret_b)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.ids(response), [self.entry_b.pk])
