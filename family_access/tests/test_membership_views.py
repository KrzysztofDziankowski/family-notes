from unittest import mock

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from entries.eduvulcan.children import snapshot_active_children
from entries.forms import EntryCreateForm
from entries.models import Entry
from family_access import membership
from family_access.membership import (
    DUPLICATE_MEMBERSHIP_ERROR,
    DUPLICATE_NAME_ERROR,
    LAST_PARENT_ERROR,
    SELF_DEACTIVATION_ERROR,
)
from family_access.models import AutomationToken, FamilyMember

from .test_membership_services import MembershipFixtureMixin

LIST_URL = reverse('family_members')
STATES_URL = reverse('family_member_states')
PARENT_REACTIVATION_COPY = 'Ta osoba odzyska uprawnienia rodzica.'


def edit_url(pk):
    return reverse('family_member_edit', args=[pk])


def deactivate_url(pk):
    return reverse('family_member_deactivate', args=[pk])


def reactivate_url(pk):
    return reverse('family_member_reactivate', args=[pk])


class AccessMatrixTests(MembershipFixtureMixin, TestCase):
    """Every route for each kind of visitor; denial never changes the database."""

    def setUp(self):
        super().setUp()
        self.inactive_parent = self.member(
            'inactive-parent', FamilyMember.Role.PARENT, 'Ex', is_active=False
        )
        self.no_membership = get_user_model().objects.create_user(
            username='nobody', email='nobody@example.test'
        )

    def requests(self, pk):
        return [
            ('get', LIST_URL, {}),
            ('get', edit_url(pk), {}),
            ('post', edit_url(pk), {'display_name': 'Nowe imię'}),
            ('post', deactivate_url(pk), {}),
            ('post', reactivate_url(pk), {}),
        ]

    def call(self, method, url, data):
        return getattr(self.client, method)(url, data)

    def test_anonymous_is_redirected_to_login(self):
        before = self.snapshot()
        for method, url, data in self.requests(self.child.pk):
            with self.subTest(method=method, url=url):
                response = self.call(method, url, data)
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse('account_login'), response['Location'])
        self.assertEqual(self.snapshot(), before)

    def test_non_parents_get_403(self):
        visitors = {
            'child': self.child.user,
            'inactive parent': self.inactive_parent.user,
            'no membership': self.no_membership,
        }
        before = self.snapshot()
        for label, user in visitors.items():
            self.client.force_login(user)
            for method, url, data in self.requests(self.child.pk):
                with self.subTest(visitor=label, method=method, url=url):
                    self.assertEqual(self.call(method, url, data).status_code, 403)
        self.assertEqual(self.snapshot(), before)

    def test_parent_of_another_family_gets_404_for_our_members(self):
        self.client.force_login(self.foreign_parent.user)
        before = self.snapshot()
        for method, url, data in self.requests(self.child.pk)[1:]:
            with self.subTest(method=method, url=url):
                self.assertEqual(self.call(method, url, data).status_code, 404)
        self.assertEqual(self.snapshot(), before)

    def test_foreign_and_missing_ids_look_the_same(self):
        self.client.force_login(self.parent.user)
        before = self.snapshot()
        for pk in (self.foreign_child.pk, 999999):
            for method, url, data in self.requests(pk)[1:]:
                with self.subTest(pk=pk, method=method, url=url):
                    response = self.call(method, url, data)
                    self.assertEqual(response.status_code, 404)
                    self.assertNotIn('Obca', response.content.decode())
        self.assertEqual(self.snapshot(), before)

    def test_list_shows_own_family_only(self):
        self.client.force_login(self.parent.user)

        response = self.client.get(LIST_URL)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        for name in ('Alex', 'Sam', 'Kasia', 'Ex'):
            self.assertIn(name, content)
        for name in ('Obcy', 'Obca'):
            self.assertNotIn(name, content)
        self.assertIn('Nowe osoby dodaje do rodziny administrator rodziny.', content)


class ListRenderingTests(MembershipFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.parent.user)

    def row(self, content, member):
        start = content.index(f'data-member-row="{member.pk}"')
        end = content.find('</li>', start)
        return content[start:end]

    def test_self_row_has_no_deactivate_action(self):
        content = self.client.get(LIST_URL).content.decode()

        own = self.row(content, self.parent)
        self.assertNotIn(deactivate_url(self.parent.pk), own)
        self.assertIn('Nie możesz wyłączyć własnego dostępu.', own)
        self.assertIn(deactivate_url(self.other_parent.pk), self.row(content, self.other_parent))
        self.assertIn('Tokeny automatyzacji', self.row(content, self.other_parent))
        self.assertIn(deactivate_url(self.child.pk), self.row(content, self.child))

    def test_last_parent_row_has_no_deactivate_action(self):
        # A signed-in parent always counts as remaining, so the "last parent"
        # state is simulated at the guard's query (e.g. S-15 demotions).
        with mock.patch.object(membership, '_remaining_parent_exists', return_value=False):
            content = self.client.get(LIST_URL).content.decode()

        sam = self.row(content, self.other_parent)
        self.assertNotIn(deactivate_url(self.other_parent.pk), sam)
        self.assertIn('To ostatni aktywny rodzic.', sam)
        self.assertIn(deactivate_url(self.child.pk), self.row(content, self.child))

    def test_inactive_parent_row_asks_for_confirmation_and_child_row_does_not(self):
        FamilyMember.objects.filter(pk__in=[self.other_parent.pk, self.child.pk]).update(
            is_active=False
        )

        content = self.client.get(LIST_URL).content.decode()

        parent_row = self.row(content, self.other_parent)
        child_row = self.row(content, self.child)
        self.assertIn('<details', parent_row)
        self.assertIn(PARENT_REACTIVATION_COPY, parent_row)
        self.assertIn(reactivate_url(self.other_parent.pk), parent_row)
        self.assertNotIn('<details', child_row)
        self.assertNotIn(PARENT_REACTIVATION_COPY, child_row)
        self.assertIn(reactivate_url(self.child.pk), child_row)

    def test_account_page_links_parents_only(self):
        self.assertContains(self.client.get(reverse('account_status')), LIST_URL)
        self.client.force_login(self.child.user)
        self.assertNotContains(self.client.get(reverse('account_status')), LIST_URL)


class MutationViewTests(MembershipFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.parent.user)

    def test_rename_redirects_with_notice(self):
        response = self.client.post(
            edit_url(self.child.pk), {'display_name': ' Katarzyna '}, follow=True
        )

        self.assertRedirects(response, LIST_URL)
        self.assertContains(response, 'Zapisano nowe imię: Katarzyna.')
        self.child.refresh_from_db()
        self.assertEqual(self.child.display_name, 'Katarzyna')

    def test_edit_page_prefills_name_and_explains_child_matching(self):
        response = self.client.get(edit_url(self.child.pk))

        self.assertContains(response, 'value="Kasia"')
        self.assertContains(response, 'powiadomienia ze szkoły')
        self.assertNotContains(self.client.get(edit_url(self.other_parent.pk)), 'powiadomienia ze szkoły')

    def test_invalid_rename_rerenders_with_error_and_changes_nothing(self):
        before = self.snapshot()
        for value, message in (('', 'Podaj imię.'), ('sam', DUPLICATE_NAME_ERROR)):
            with self.subTest(value=value):
                response = self.client.post(edit_url(self.child.pk), {'display_name': value})
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, message)
                self.assertContains(response, '<title>Błąd: ')
                self.assertContains(response, 'Popraw zaznaczone pola.')
        self.assertEqual(self.snapshot(), before)

    def test_deactivate_and_reactivate_child(self):
        response = self.client.post(deactivate_url(self.child.pk), follow=True)
        self.assertRedirects(response, LIST_URL)
        self.assertContains(response, 'Wyłączono dostęp: Kasia.')
        self.child.refresh_from_db()
        self.assertFalse(self.child.is_active)

        response = self.client.post(reactivate_url(self.child.pk), follow=True)
        self.assertContains(response, 'Przywrócono dostęp: Kasia.')
        self.child.refresh_from_db()
        self.assertTrue(self.child.is_active)

    def test_guard_errors_rerender_the_list_and_change_nothing(self):
        before = self.snapshot()

        response = self.client.post(deactivate_url(self.parent.pk))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, SELF_DEACTIVATION_ERROR)
        self.assertContains(response, '<title>Błąd: Członkowie rodziny')
        self.assertEqual(self.snapshot(), before)

    def test_last_parent_guard_error(self):
        before = self.snapshot()

        with mock.patch.object(membership, '_remaining_parent_exists', return_value=False):
            response = self.client.post(deactivate_url(self.other_parent.pk))

        self.assertContains(response, LAST_PARENT_ERROR)
        self.assertEqual(self.snapshot(), before)

    def test_reactivation_succeeds_when_active_in_another_family(self):
        FamilyMember.objects.filter(pk=self.child.pk).update(is_active=False)
        FamilyMember.objects.create(
            user=self.child.user, family=self.foreign_family,
            role=FamilyMember.Role.CHILD, display_name='Kasia',
        )

        response = self.client.post(reactivate_url(self.child.pk))

        self.assertRedirects(response, reverse('family_members'))
        self.child.refresh_from_db()
        self.assertTrue(self.child.is_active)

    def test_reactivation_error_when_already_active_in_this_family(self):
        FamilyMember.objects.filter(pk=self.child.pk).update(is_active=False)
        FamilyMember.objects.create(
            user=self.child.user, family=self.family,
            role=FamilyMember.Role.CHILD, display_name='Katarzyna',
        )
        before = self.snapshot()

        response = self.client.post(reactivate_url(self.child.pk))

        self.assertContains(response, DUPLICATE_MEMBERSHIP_ERROR)
        self.assertEqual(self.snapshot(), before)

    def test_mutations_require_post(self):
        for url in (deactivate_url(self.child.pk), reactivate_url(self.child.pk)):
            self.assertEqual(self.client.get(url).status_code, 405)

    def test_mutations_enforce_csrf(self):
        client = self.client_class(enforce_csrf_checks=True)
        client.force_login(self.parent.user)
        before = self.snapshot()
        for url in (deactivate_url(self.child.pk), edit_url(self.child.pk)):
            self.assertEqual(client.post(url, {'display_name': 'X'}).status_code, 403)
        self.assertEqual(self.snapshot(), before)

    def test_parent_reactivation_logs_ids_only(self):
        FamilyMember.objects.filter(pk=self.other_parent.pk).update(is_active=False)

        with self.assertLogs(membership.logger, level='INFO') as logs:
            self.client.post(reactivate_url(self.other_parent.pk))

        self.assertEqual(
            [record.getMessage() for record in logs.records],
            [
                f'membership_event=member_reactivated family={self.family.pk} '
                f'member={self.other_parent.pk} actor={self.parent.pk}'
            ],
        )
        for secret in ('Sam', 'Alex', '@example.test'):
            self.assertNotIn(secret, '\n'.join(logs.output))


class StateGalleryTests(MembershipFixtureMixin, TestCase):
    def test_gallery_is_404_without_debug(self):
        self.client.force_login(self.parent.user)
        self.assertEqual(self.client.get(STATES_URL).status_code, 404)

    @override_settings(DEBUG=True)
    def test_gallery_is_parent_only(self):
        response = self.client.get(STATES_URL)
        self.assertEqual(response.status_code, 302)
        self.client.force_login(self.child.user)
        self.assertEqual(self.client.get(STATES_URL).status_code, 403)

    @override_settings(DEBUG=True)
    def test_gallery_renders_every_state_without_writes(self):
        self.client.force_login(self.parent.user)
        before = self.snapshot()
        tokens = AutomationToken.objects.count()

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(STATES_URL)

        self.assertEqual(response.status_code, 200)
        for state in (
            'list', 'deactivate_open', 'reactivate_parent_open', 'last_parent',
            'guard_error', 'reactivate_error', 'edit', 'edit_invalid', 'edit_duplicate',
        ):
            self.assertContains(response, f'data-member-state="{state}"')
        for copy in (PARENT_REACTIVATION_COPY, LAST_PARENT_ERROR, DUPLICATE_MEMBERSHIP_ERROR,
                     DUPLICATE_NAME_ERROR, 'Podaj imię.'):
            self.assertContains(response, copy)
        # Two S-14 list confirmations plus five S-15 role confirmations
        # (promote, demote, self-demote, its invalid re-render, guard error).
        self.assertContains(response, 'open>', count=7)
        writes = [
            query['sql'] for query in queries.captured_queries
            if query['sql'].lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE'))
        ]
        self.assertEqual(writes, [])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(AutomationToken.objects.count(), tokens)


class DeactivationRegressionTests(MembershipFixtureMixin, TestCase):
    """Deactivation through the UI interacts correctly with entries, matching and tokens."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.parent.user)
        self.entry = Entry.objects.create(
            family=self.family,
            entry_type='todo',
            content='Oddać książkę',
            assigned_member=self.child,
            created_by=self.parent,
        )

    def test_deactivated_child_leaves_choices_and_snapshots_but_entries_stay(self):
        self.client.post(deactivate_url(self.child.pk))

        form = EntryCreateForm(self.parent)
        self.assertNotIn(self.child, form.fields['assigned_member'].queryset)
        self.assertNotIn(self.child.pk, [child.pk for child in snapshot_active_children(self.family)])
        response = self.client.get(reverse('entries:detail', args=[self.entry.pk]))
        self.assertContains(response, 'Oddać książkę')

    def test_deactivated_child_loses_access_and_regains_it(self):
        self.client.post(deactivate_url(self.child.pk))

        child_client = self.client_class()
        child_client.force_login(self.child.user)
        self.assertEqual(child_client.get(reverse('entries:child_list')).status_code, 403)
        self.assertContains(
            child_client.get(reverse('account_status')),
            'nie jest jeszcze skonfigurowane',
        )

        self.client.post(reactivate_url(self.child.pk))

        self.assertContains(child_client.get(reverse('entries:child_list')), 'Oddać książkę')
        self.assertIn(self.child.pk, [child.pk for child in snapshot_active_children(self.family)])

    def test_deactivated_parent_token_gets_401_and_stays_revoked(self):
        _token, secret = AutomationToken.issue(self.other_parent, 'Skrót')
        ping = reverse('automation:ping')
        auth = {'HTTP_AUTHORIZATION': f'Bearer {secret}'}
        self.assertEqual(self.client_class().get(ping, **auth).status_code, 200)

        self.client.post(deactivate_url(self.other_parent.pk))
        self.assertEqual(self.client_class().get(ping, **auth).status_code, 401)
        parent_client = self.client_class()
        parent_client.force_login(self.other_parent.user)
        self.assertEqual(parent_client.get(reverse('entries:index')).status_code, 403)

        self.client.post(reactivate_url(self.other_parent.pk))
        self.assertEqual(self.client_class().get(ping, **auth).status_code, 401)
        self.assertEqual(parent_client.get(reverse('entries:index')).status_code, 200)
