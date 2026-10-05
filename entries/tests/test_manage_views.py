"""Parent family entry management views (S-02): routes, index wiring, CRUD and redirects.

Partition/ordering rules themselves are covered by ``test_entry_listing``; these
tests prove the index renders them through the shared contract.
"""

import datetime
import re
import uuid

from django.contrib.messages import constants
from django.contrib.messages.storage.base import Message
from django.template.loader import render_to_string
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from entries.classification.types import EntryType, SchoolItemKind
from entries.models import Entry
from family_access.models import FamilyMember

from .test_classification_service import FamilyFixtureMixin

INDEX_URL = reverse('entries:index')
CREATE_URL = reverse('entries:create')
FOREIGN_SENTINEL = 'SENTINEL-OBCA-RODZINA-4b2d'
ROW_PATTERN = re.compile(r'data-entry-row="(\d+)"')
SECTION_PATTERN = re.compile(r'data-list-section="(\w+)"')


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
            entry_type=EntryType.TODO.value,
            content=content,
            created_by=self.parent,
        )
        values.update(fields)
        return Entry.objects.create(**values)

    def days(self, offset):
        return self.today + datetime.timedelta(days=offset)

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
        self.undated_old = e('Bez daty starszy')
        self.undated_new = e('Bez daty nowszy')
        Entry.objects.filter(pk=self.undated_old.pk).update(
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

    def test_upcoming_is_default_with_dated_then_undated_in_exact_order(self):
        response = self.client.get(INDEX_URL)

        self.assertEqual(
            self.rendered_rows(response),
            [
                self.today_early.pk,
                self.today_late.pk,
                self.today_untimed.pk,
                self.tomorrow.pk,
                self.next_week.pk,
                self.undated_new.pk,
                self.undated_old.pk,
            ],
        )
        self.assertEqual(SECTION_PATTERN.findall(response.content.decode()), ['dated', 'undated'])
        self.assertContains(response, 'aria-current="page">Nadchodzące<')

    def test_past_mode_lists_only_past_dates_in_exact_order(self):
        response = self.client.get(INDEX_URL, {'view': 'past'})

        self.assertEqual(
            self.rendered_rows(response),
            [self.yesterday_noon.pk, self.yesterday_untimed.pk, self.last_month.pk],
        )
        self.assertEqual(SECTION_PATTERN.findall(response.content.decode()), ['past'])
        self.assertContains(response, 'aria-current="page">Minione<')

    def test_unknown_mode_falls_back_to_upcoming(self):
        response = self.client.get(INDEX_URL, {'view': 'everything'})

        self.assertEqual(response.context['mode'], 'upcoming')
        self.assertIn(self.today_early.pk, self.rendered_rows(response))

    def test_index_shows_only_own_family_entries(self):
        """2.3"""
        for mode in ('upcoming', 'past'):
            with self.subTest(mode=mode):
                response = self.client.get(INDEX_URL, {'view': mode})
                self.assertNotContains(response, FOREIGN_SENTINEL)
                self.assertNotIn(self.foreign.pk, self.rendered_rows(response))
                self.assertNotIn(self.lucky.pk, self.rendered_rows(response))

    def test_rows_show_type_content_schedule_assignee_and_links(self):
        self.tomorrow.assigned_member = self.child
        self.tomorrow.save()

        response = self.client.get(INDEX_URL)

        self.assertContains(response, f'href="{detail_url(self.tomorrow.pk)}"')
        self.assertContains(response, f'href="{edit_url(self.tomorrow.pk)}"')
        self.assertContains(response, 'Michał')
        self.assertContains(response, 'Bez daty</span>')
        self.assertContains(response, ', 08:00')


class EmptyIndexTests(ManageViewMixin, TestCase):
    def test_each_mode_has_a_distinct_empty_state(self):
        self.entry(FOREIGN_SENTINEL, family=self.other_family, date=self.today)
        upcoming = self.client.get(INDEX_URL)
        past = self.client.get(INDEX_URL, {'view': 'past'})

        self.assertContains(upcoming, 'Nie ma nadchodzących wpisów.')
        self.assertContains(past, 'Nie ma minionych wpisów.')
        self.assertNotContains(upcoming, 'data-entry-row')
        self.assertNotContains(past, 'data-entry-row')
        self.assertContains(
            upcoming, '<p class="fn-empty fn-muted" data-state-part="empty-upcoming">'
        )
        self.assertContains(past, '<p class="fn-empty fn-muted" data-state-part="empty-past">')


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

    def test_detail_links_back_to_the_list_the_entry_belongs_to(self):
        past_entry = self.entry(date=self.days(-3))
        undated = self.entry()

        self.assertContains(
            self.client.get(detail_url(past_entry.pk)), f'href="{INDEX_URL}?view=past"'
        )
        self.assertContains(
            self.client.get(detail_url(undated.pk)), f'href="{INDEX_URL}?view=upcoming"'
        )

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
        self.assertContains(response, 'id="id_school_subject-error"')
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
        self.assertContains(response, 'id="id_content-error"')

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
                date='',
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
        entry.refresh_from_db()
        self.assertEqual(entry.content, 'Bez zmian')


class DeleteTests(ManageViewMixin, TestCase):
    def test_delete_removes_entry_and_returns_to_allowlisted_list_mode(self):
        """2.5"""
        cases = {
            'past': f'{INDEX_URL}?view=past',
            'upcoming': f'{INDEX_URL}?view=upcoming',
            '': f'{INDEX_URL}?view=upcoming',
            'https://evil.example/': f'{INDEX_URL}?view=upcoming',
            '//evil.example': f'{INDEX_URL}?view=upcoming',
        }
        for posted, expected in cases.items():
            with self.subTest(view=posted):
                entry = self.entry()
                response = self.client.post(
                    delete_url(entry.pk), {'view': posted, 'next': 'https://evil.example/'}
                )
                self.assertRedirects(response, expected)
                self.assertFalse(Entry.objects.filter(pk=entry.pk).exists())

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
