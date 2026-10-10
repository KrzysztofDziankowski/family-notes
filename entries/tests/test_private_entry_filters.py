"""Privacy controls and calendar privacy filters (private-family-entries, Phase 3).

Both calendars offer "Wszystkie" (default), "Prywatne" and "Nieprywatne" over
the entries the reader may already see; the filter is applied in the query and
carried by navigation, filter, entry, detail and redirect links. Only an
entry's creator sees and uses the privacy control, which changes nothing but
``is_private``.
"""

import datetime
import re
import uuid
from unittest import mock

from django.test import Client, TestCase
from django.urls import reverse

from entries.classification.service import ParentBatchClassification, ParentClassification
from entries.classification.types import ClassificationProposal, EntryType
from entries.models import Entry

from .test_follow_up_views import as_post_data
from .test_private_entries import (
    CHILD_PRIVATE,
    EWA_PRIVATE,
    FOREIGN_PRIVATE,
    PAWEL_PRIVATE,
    PrivateEntriesFixtureMixin,
)

INDEX_URL = reverse('entries:index')
CHILD_LIST_URL = reverse('entries:child_list')
ROW_PATTERN = re.compile(r'data-entry-row="(\d+)"')
PRIVACY_LINK_PATTERN = re.compile(
    r'<a href="([^"]*)" data-privacy-key="(\w+)"(?: data-member-link)?( aria-current="page")?>'
    r'([^<]*)</a>'
)


def privacy_nav(html):
    start = html.index('aria-label="Filtr prywatności"')
    return html[start:html.index('</nav>', start)]


def privacy_links(html):
    """``[(href, key, current, label)]`` of the "Filtr prywatności" nav."""
    return [
        (href.replace('&amp;', '&'), key, bool(current), label)
        for href, key, current, label in PRIVACY_LINK_PATTERN.findall(privacy_nav(html))
    ]


def calendar_nav_hrefs(html):
    start = html.index('data-state-part="calendar-nav"')
    nav = html[start:html.index('</nav>', start)]
    return [href.replace('&amp;', '&') for href in re.findall(r'href="([^"]*)"', nav)]


def rows(response):
    return sorted(int(pk) for pk in ROW_PATTERN.findall(response.content.decode()))


class ParentPrivacyFilterTests(PrivateEntriesFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.parent.user)
        self.start = self.today.isoformat()

    def test_default_all_lists_public_and_own_private_entries(self):
        response = self.client.get(INDEX_URL)

        self.assertEqual(
            rows(response), sorted([self.ewa_private.pk, self.public.pk, self.eduvulcan.pk])
        )
        for content in (PAWEL_PRIVATE, CHILD_PRIVATE, FOREIGN_PRIVATE):
            self.assertNotContains(response, content)
        self.assertEqual(
            privacy_links(response.content.decode()),
            [
                (f'{INDEX_URL}?start={self.start}', 'all', True, 'Wszystkie'),
                (f'{INDEX_URL}?start={self.start}&privacy=private', 'private', False, 'Prywatne'),
                (f'{INDEX_URL}?start={self.start}&privacy=public', 'public', False, 'Nieprywatne'),
            ],
        )

    def test_private_lists_only_own_private_entries(self):
        response = self.client.get(INDEX_URL, {'privacy': 'private'})

        self.assertEqual(rows(response), [self.ewa_private.pk])
        self.assertContains(response, 'data-entry-private>Prywatny</span>', count=1)
        for content in (PAWEL_PRIVATE, CHILD_PRIVATE, FOREIGN_PRIVATE):
            self.assertNotContains(response, content)
        self.assertEqual(
            [(key, current) for _href, key, current, _label in privacy_links(
                response.content.decode()
            )],
            [('all', False), ('private', True), ('public', False)],
        )

    def test_not_private_lists_only_public_entries(self):
        response = self.client.get(INDEX_URL, {'privacy': 'public'})

        self.assertEqual(rows(response), sorted([self.public.pk, self.eduvulcan.pk]))
        self.assertNotContains(response, 'data-entry-private')
        self.assertEqual(
            [(key, current) for _href, key, current, _label in privacy_links(
                response.content.decode()
            )],
            [('all', False), ('private', False), ('public', True)],
        )

    def test_invalid_privacy_means_all_without_echoing_it(self):
        default = rows(self.client.get(INDEX_URL))
        for value in ('', 'PRIVATE', 'Private', ' private', 'true', '1', 'all', 'prywatne',
                      'private&member=1', '<b>'):
            with self.subTest(value=value):
                response = self.client.get(INDEX_URL, {'privacy': value})
                html = response.content.decode()
                self.assertEqual(rows(response), default)
                self.assertEqual(
                    [(key, current) for _href, key, current, _label in privacy_links(html)],
                    [('all', True), ('private', False), ('public', False)],
                )
                self.assertNotIn(f'privacy={value}&', html.replace('&amp;', '&'))
                self.assertNotIn('<b>', html.split('<main', 1)[1])
                for href in calendar_nav_hrefs(html):
                    self.assertNotIn('privacy=', href)

    def test_privacy_is_carried_by_navigation_entry_and_member_links(self):
        html = self.client.get(
            INDEX_URL, {'privacy': 'private', 'member': str(self.child.pk)}
        ).content.decode().replace('&amp;', '&')
        state = f'member={self.child.pk}&privacy=private'

        self.assertEqual(
            calendar_nav_hrefs(html),
            [
                f'{INDEX_URL}?start={(self.today - datetime.timedelta(days=14)).isoformat()}&{state}',
                f'{INDEX_URL}?start={self.start}&{state}',
                f'{INDEX_URL}?start={(self.today + datetime.timedelta(days=14)).isoformat()}&{state}',
            ],
        )
        detail = reverse('entries:detail', args=[self.ewa_private.pk])
        self.assertIn(f'href="{detail}?start={self.start}&{state}" data-member-link>', html)
        # The child filter keeps the privacy filter, and the privacy filter keeps the child.
        self.assertIn(f'href="{INDEX_URL}?start={self.start}&privacy=private" data-member-key="all"', html)
        self.assertIn(
            f'href="{INDEX_URL}?start={self.start}&member={self.other_child.pk}&privacy=private"',
            html,
        )
        self.assertEqual(
            [href for href, *_rest in privacy_links(html)],
            [
                f'{INDEX_URL}?start={self.start}&member={self.child.pk}',
                f'{INDEX_URL}?start={self.start}&member={self.child.pk}&privacy=private',
                f'{INDEX_URL}?start={self.start}&member={self.child.pk}&privacy=public',
            ],
        )
        # The privacy links follow a JavaScript child switch (js/member-filter.js).
        self.assertEqual(privacy_nav(html).count('data-member-link'), 3)

    def test_privacy_filter_works_with_a_window_and_without_children(self):
        start = (self.today - datetime.timedelta(days=14)).isoformat()
        html = self.client.get(INDEX_URL, {'start': start, 'privacy': 'public'}).content.decode()

        for href, *_rest in privacy_links(html):
            with self.subTest(href=href):
                self.assertTrue(href.startswith(f'{INDEX_URL}?start={start}'))

    def test_detail_back_link_and_delete_form_carry_a_validated_privacy(self):
        url = reverse('entries:detail', args=[self.public.pk])
        start = self.start

        html = self.client.get(url, {'start': start, 'privacy': 'public'}).content.decode()
        self.assertIn(f'href="{INDEX_URL}?start={start}&amp;privacy=public">Wróć do listy</a>', html)
        self.assertIn('<input type="hidden" name="privacy" value="public">', html)

        for value in ('junk', 'PUBLIC', ''):
            with self.subTest(privacy=value):
                html = self.client.get(url, {'start': start, 'privacy': value}).content.decode()
                self.assertIn(f'href="{INDEX_URL}?start={start}">Wróć do listy</a>', html)
                self.assertNotIn('name="privacy"', html)

    def test_delete_returns_to_the_filtered_window_only_for_a_valid_privacy(self):
        cases = {
            'private': f'{INDEX_URL}?start={self.start}&privacy=private',
            'public': f'{INDEX_URL}?start={self.start}&privacy=public',
            'junk': f'{INDEX_URL}?start={self.start}',
        }
        for value, expected in cases.items():
            with self.subTest(privacy=value):
                entry = self.make_entry('Do usunięcia', self.parent)
                response = self.client.post(
                    reverse('entries:delete', args=[entry.pk]),
                    {'start': self.start, 'privacy': value},
                )
                self.assertRedirects(response, expected)


class ChildPrivacyFilterTests(PrivateEntriesFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.child.user)
        self.start = self.today.isoformat()

    def test_all_private_and_not_private_states(self):
        cases = {
            None: ([self.child_private, self.public, self.eduvulcan], 'all'),
            'private': ([self.child_private], 'private'),
            'public': ([self.public, self.eduvulcan], 'public'),
            'junk': ([self.child_private, self.public, self.eduvulcan], 'all'),
        }
        for value, (expected, current) in cases.items():
            with self.subTest(privacy=value):
                response = self.client.get(CHILD_LIST_URL, {'privacy': value} if value else {})
                self.assertEqual(rows(response), sorted(entry.pk for entry in expected))
                for content in (EWA_PRIVATE, PAWEL_PRIVATE, FOREIGN_PRIVATE):
                    self.assertNotContains(response, content)
                html = response.content.decode()
                self.assertEqual(
                    [key for _href, key, is_current, _label in privacy_links(html) if is_current],
                    [current],
                )
                self.assertNotIn('data-member-link', privacy_nav(html))

    def test_privacy_is_carried_by_navigation_entry_and_back_links(self):
        html = self.client.get(CHILD_LIST_URL, {'privacy': 'private'}).content.decode()
        html = html.replace('&amp;', '&')

        self.assertEqual(
            calendar_nav_hrefs(html),
            [
                f'{CHILD_LIST_URL}?start={(self.today - datetime.timedelta(days=14)).isoformat()}'
                '&privacy=private',
                f'{CHILD_LIST_URL}?start={self.start}&privacy=private',
                f'{CHILD_LIST_URL}?start={(self.today + datetime.timedelta(days=14)).isoformat()}'
                '&privacy=private',
            ],
        )
        detail = reverse('entries:child_detail', args=[self.child_private.pk])
        self.assertIn(f'href="{detail}?start={self.start}&privacy=private"', html)

        detail_html = self.client.get(
            detail, {'start': self.start, 'privacy': 'private'}
        ).content.decode()
        self.assertIn(
            f'href="{CHILD_LIST_URL}?start={self.start}&amp;privacy=private" data-back-link',
            detail_html,
        )
        junk_html = self.client.get(detail, {'start': self.start, 'privacy': 'x'}).content.decode()
        self.assertIn(f'href="{CHILD_LIST_URL}?start={self.start}" data-back-link', junk_html)


class PrivacyControlVisibilityTests(PrivateEntriesFixtureMixin, TestCase):
    def test_parent_sees_the_control_only_on_entries_they_created(self):
        own_public = self.make_entry('Publiczny wpis Ewy', self.parent)
        self.client.force_login(self.parent.user)
        cases = {
            self.ewa_private: True,
            own_public: True,
            self.public: False,
            self.eduvulcan: False,
        }
        for entry, shown in cases.items():
            with self.subTest(entry=entry.content):
                html = self.client.get(reverse('entries:detail', args=[entry.pk])).content.decode()
                self.assertEqual('data-state-part="privacy"' in html, shown)
                self.assertEqual(
                    f'action="{reverse("entries:privacy", args=[entry.pk])}"' in html, shown
                )

    def test_control_states_the_current_privacy_and_offers_the_opposite(self):
        self.client.force_login(self.parent.user)
        html = self.client.get(
            reverse('entries:detail', args=[self.ewa_private.pk])
        ).content.decode()
        self.assertIn('Wpis jest prywatny — widoczny tylko dla Ciebie.', html)
        self.assertIn('<input type="hidden" name="is_private" value="false">', html)
        self.assertIn('Oznacz jako nieprywatny', html)
        self.assertIn('name="family_context"', html)
        self.assertIn('name="csrfmiddlewaretoken"', html)

    def test_child_sees_the_control_only_on_own_entries(self):
        own_public = self.make_entry('Mój publiczny wpis', self.child)
        self.client.force_login(self.child.user)
        cases = {
            self.child_private: True,
            own_public: True,
            self.public: False,
            self.eduvulcan: False,
        }
        for entry, shown in cases.items():
            with self.subTest(entry=entry.content):
                html = self.client.get(
                    reverse('entries:child_detail', args=[entry.pk])
                ).content.decode()
                self.assertEqual('data-state-part="privacy"' in html, shown)
                # No general editing: the privacy form is the only form.
                main = html.split('<main', 1)[1]
                self.assertEqual(main.count('<form'), 1 if shown else 0)
                self.assertNotIn('Edytuj', main)
                self.assertNotIn('Usuń', main)


class ParentPrivacyChangeTests(PrivateEntriesFixtureMixin, TestCase):
    def url(self, entry_or_pk):
        return reverse('entries:privacy', args=[getattr(entry_or_pk, 'pk', entry_or_pk)])

    def test_creator_makes_an_entry_public_and_private_again(self):
        self.client.force_login(self.parent.user)
        before = Entry.objects.filter(pk=self.ewa_private.pk).values().get()

        response = self.client.post(self.url(self.ewa_private), {'is_private': 'false'})

        self.assertRedirects(
            response, reverse('entries:detail', args=[self.ewa_private.pk]),
            fetch_redirect_response=False,
        )
        after = Entry.objects.filter(pk=self.ewa_private.pk).values().get()
        self.assertFalse(after['is_private'])
        changed = {name for name in before if before[name] != after[name]}
        self.assertLessEqual(changed, {'is_private', 'updated_at'})
        self.assertContains(self.client.get(response['Location']), 'Wpis nie jest już prywatny.')

        self.client.post(self.url(self.ewa_private), {'is_private': 'true'})
        self.ewa_private.refresh_from_db()
        self.assertTrue(self.ewa_private.is_private)

    def test_redirect_keeps_the_validated_calendar_state(self):
        self.client.force_login(self.parent.user)
        start = (self.today - datetime.timedelta(days=14)).isoformat()
        detail = reverse('entries:detail', args=[self.ewa_private.pk])
        cases = [
            ({'start': start, 'member': str(self.child.pk), 'privacy': 'private'},
             f'{detail}?start={start}&member={self.child.pk}&privacy=private'),
            ({'start': '2026-1-1', 'member': str(self.other_family_child.pk), 'privacy': 'x'},
             detail),
            ({'privacy': 'public'}, f'{detail}?privacy=public'),
        ]
        for posted, expected in cases:
            with self.subTest(posted=posted):
                response = self.client.post(
                    self.url(self.ewa_private), {'is_private': 'true', **posted}
                )
                self.assertRedirects(response, expected)

    def test_non_creators_get_the_missing_id_404_and_nothing_changes(self):
        self.client.force_login(self.parent.user)
        missing = self.client.post(self.url(self.missing_pk()), {'is_private': 'true'})
        self.assertEqual(missing.status_code, 404)
        for entry in (self.pawel_private, self.child_private, self.public, self.eduvulcan,
                      self.foreign_private):
            with self.subTest(entry=entry.content):
                before = self.snapshot()
                response = self.client.post(
                    self.url(entry), {'is_private': 'false' if entry.is_private else 'true'}
                )
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.content, missing.content)
                self.assertEqual(self.snapshot(), before)

    def test_invalid_value_changes_nothing(self):
        self.client.force_login(self.parent.user)
        for data in ({}, {'is_private': ''}, {'is_private': 'on'}, {'is_private': 'False'}):
            with self.subTest(data=data):
                before = self.snapshot()
                response = self.client.post(self.url(self.ewa_private), data)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(self.snapshot(), before)

    def test_children_anonymous_and_get_are_refused(self):
        self.client.force_login(self.child.user)
        before = self.snapshot()
        # Even the child's own entry: the parent route needs a parent.
        for entry in (self.child_private, self.ewa_private):
            with self.subTest(entry=entry.content):
                response = self.client.post(self.url(entry), {'is_private': 'false'})
                self.assertEqual(response.status_code, 403)
        self.client.logout()
        response = self.client.post(self.url(self.ewa_private), {'is_private': 'false'})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response['Location'].startswith(reverse('account_login')))
        self.assertEqual(self.snapshot(), before)

        self.client.force_login(self.parent.user)
        self.assertEqual(self.client.get(self.url(self.ewa_private)).status_code, 405)

    def test_post_requires_csrf_and_the_current_family(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.parent.user)
        before = self.snapshot()

        response = csrf_client.post(self.url(self.ewa_private), {'is_private': 'false'})
        self.assertEqual(response.status_code, 403)

        self.client.force_login(self.parent.user)
        response = self.client.post(
            self.url(self.ewa_private),
            {'is_private': 'false', 'family_context': str(self.other_family.pk)},
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.snapshot(), before)


class ChildPrivacyChangeTests(PrivateEntriesFixtureMixin, TestCase):
    def url(self, entry_or_pk):
        return reverse('entries:child_privacy', args=[getattr(entry_or_pk, 'pk', entry_or_pk)])

    def test_child_creator_changes_only_privacy(self):
        self.client.force_login(self.child.user)
        before = Entry.objects.filter(pk=self.child_private.pk).values().get()

        response = self.client.post(
            self.url(self.child_private),
            {'is_private': 'false', 'start': self.today.isoformat(), 'privacy': 'private'},
        )

        detail = reverse('entries:child_detail', args=[self.child_private.pk])
        self.assertRedirects(response, f'{detail}?start={self.today.isoformat()}&privacy=private')
        after = Entry.objects.filter(pk=self.child_private.pk).values().get()
        self.assertFalse(after['is_private'])
        changed = {name for name in before if before[name] != after[name]}
        self.assertLessEqual(changed, {'is_private', 'updated_at'})
        # The now public entry is visible to the parents again.
        self.client.force_login(self.parent.user)
        self.assertContains(self.client.get(INDEX_URL), CHILD_PRIVATE)

    def test_child_cannot_change_entries_created_by_others(self):
        self.client.force_login(self.child.user)
        missing = self.client.post(self.url(self.missing_pk()), {'is_private': 'true'})
        self.assertEqual(missing.status_code, 404)
        for entry in (self.ewa_private, self.public, self.eduvulcan, self.foreign_private):
            with self.subTest(entry=entry.content):
                before = self.snapshot()
                response = self.client.post(self.url(entry), {'is_private': 'true'})
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.content, missing.content)
                self.assertEqual(self.snapshot(), before)

    def test_other_child_parent_and_anonymous_are_refused(self):
        before = self.snapshot()
        self.client.force_login(self.other_child.user)
        self.assertEqual(
            self.client.post(self.url(self.child_private), {'is_private': 'false'}).status_code,
            404,
        )
        self.client.force_login(self.parent.user)
        self.assertEqual(
            self.client.post(self.url(self.ewa_private), {'is_private': 'false'}).status_code,
            403,
        )
        self.client.logout()
        response = self.client.post(self.url(self.child_private), {'is_private': 'false'})
        self.assertTrue(response['Location'].startswith(reverse('account_login')))
        self.assertEqual(self.snapshot(), before)


def _proposal(**overrides):
    values = dict(
        entry_type=EntryType.TODO,
        content='Kupić prezent dla Michała',
        date=datetime.date.today() + datetime.timedelta(days=3),
    )
    values.update(overrides)
    return ClassificationProposal(**values)


class ParentConfirmationPrivacyTests(PrivateEntriesFixtureMixin, TestCase):
    """A parent chooses privacy per entry at single and batch confirmation."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.parent.user)

    def capture(self, *results):
        batch = ParentBatchClassification(
            items=tuple(ParentClassification(result=result) for result in results)
        )
        with mock.patch('entries.views.classify_entries_for_parent', return_value=batch):
            return self.client.post(reverse('entries:capture'), {'text': 'prezent'})

    def test_review_offers_an_unchecked_privacy_choice(self):
        response = self.capture(_proposal())

        self.assertContains(response, 'Prywatny — widoczny tylko dla mnie')
        self.assertContains(response, 'type="checkbox" name="is_private"')
        self.assertNotContains(response, 'type="checkbox" name="is_private" checked')

    def test_single_confirmation_saves_the_chosen_privacy(self):
        for is_private in (False, True):
            with self.subTest(is_private=is_private):
                data = as_post_data(self.capture(_proposal()).context['review_form'])
                data.pop('is_private', None)
                if is_private:
                    data['is_private'] = 'on'
                response = self.client.post(reverse('entries:confirm'), data)
                entry = Entry.objects.get(submission_key=data['submission_key'])
                self.assertRedirects(response, f"{reverse('entries:capture')}?saved={entry.pk}")
                self.assertIs(entry.is_private, is_private)
                self.assertEqual(entry.created_by, self.parent)

    def test_batch_confirmation_saves_a_privacy_per_entry(self):
        response = self.capture(_proposal(), _proposal(content='Odebrać paczkę'))
        data = {'count': '2', 'action': 'save'}
        for entry_form in response.context['batch_form'].forms:
            values = as_post_data(entry_form)
            values.pop('is_private', None)
            data.update({f'{entry_form.prefix}-{name}': value for name, value in values.items()})
        data['e0-include'] = 'on'
        data['e1-include'] = 'on'
        data['e1-is_private'] = 'on'

        self.client.post(reverse('entries:confirm_batch'), data)

        first = Entry.objects.get(submission_key=uuid.UUID(data['e0-submission_key']))
        second = Entry.objects.get(submission_key=uuid.UUID(data['e1-submission_key']))
        self.assertFalse(first.is_private)
        self.assertTrue(second.is_private)
        self.client.force_login(self.second_parent.user)
        html = self.client.get(INDEX_URL).content.decode()
        self.assertIn('Kupić prezent dla Michała', html)
        self.assertNotIn('Odebrać paczkę', html)
