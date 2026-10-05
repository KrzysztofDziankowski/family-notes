"""S-15 role-change route, edit-page states, effective access and the changed-membership notice."""

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from entries.eduvulcan.children import match_child, snapshot_active_children
from family_access.membership import (
    INACTIVE_ROLE_TARGET_ERROR,
    LAST_PARENT_ERROR,
    SELF_DEMOTION_CONFIRM_ERROR,
)
from family_access.models import AutomationToken, FamilyMember
from family_access.notices import DEACTIVATED_NOTICE, DEMOTED_NOTICE, SESSION_KEY
from family_access.views import (
    MEMBER_DEMOTED_MESSAGE,
    MEMBER_PROMOTED_MESSAGE,
    ROLE_UNCHANGED_MESSAGE,
    SELF_DEMOTED_MESSAGE,
)

from .test_membership_services import MembershipFixtureMixin

PARENT = FamilyMember.Role.PARENT
CHILD = FamilyMember.Role.CHILD
LIST_URL = reverse('family_members')
STATES_URL = reverse('family_member_states')
PROMOTE_WARNING = 'Ta osoba będzie mogła zarządzać wpisami i członkami rodziny.'
DEMOTE_WARNING = 'Jej tokeny automatyzacji zostaną unieważnione'
LAST_PARENT_COPY = 'To ostatni aktywny rodzic, więc nie można zmienić jego roli.'


def role_url(pk):
    return reverse('family_member_role', args=[pk])


def edit_url(pk):
    return reverse('family_member_edit', args=[pk])


class RoleRouteAccessTests(MembershipFixtureMixin, TestCase):
    """The role route for each kind of visitor; denial never changes the database."""

    def setUp(self):
        super().setUp()
        self.inactive_parent = self.member('inactive-parent', PARENT, 'Ex', is_active=False)
        self.no_membership = get_user_model().objects.create_user(
            username='nobody', email='nobody@example.test'
        )

    def attempts(self):
        return [
            (self.child.pk, {'role': PARENT}),
            (self.other_parent.pk, {'role': CHILD}),
            (self.parent.pk, {'role': CHILD, 'confirm_self': 'on'}),
        ]

    def test_parent_promotes_and_demotes(self):
        self.client.force_login(self.parent.user)

        response = self.client.post(role_url(self.child.pk), {'role': PARENT}, follow=True)
        self.assertRedirects(response, LIST_URL)
        self.assertContains(response, MEMBER_PROMOTED_MESSAGE.format(name='Kasia'))
        self.child.refresh_from_db()
        self.assertEqual(self.child.role, PARENT)

        response = self.client.post(role_url(self.child.pk), {'role': CHILD}, follow=True)
        self.assertRedirects(response, LIST_URL)
        self.assertContains(response, MEMBER_DEMOTED_MESSAGE.format(name='Kasia'))
        self.child.refresh_from_db()
        self.assertEqual(self.child.role, CHILD)

    def test_unchanged_role_redirects_with_notice(self):
        self.client.force_login(self.parent.user)
        before = self.snapshot()

        response = self.client.post(role_url(self.child.pk), {'role': CHILD}, follow=True)

        self.assertRedirects(response, LIST_URL)
        self.assertContains(response, ROLE_UNCHANGED_MESSAGE.format(name='Kasia'))
        self.assertEqual(self.snapshot(), before)

    def test_anonymous_is_redirected_to_login(self):
        before = self.snapshot()
        for pk, data in self.attempts():
            with self.subTest(pk=pk):
                response = self.client.post(role_url(pk), data)
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
            for pk, data in self.attempts() + [(self.child.pk, {'role': PARENT,
                                                                'confirm_self': 'on'})]:
                with self.subTest(visitor=label, pk=pk):
                    self.assertEqual(self.client.post(role_url(pk), data).status_code, 403)
        self.assertEqual(self.snapshot(), before)

    def test_parent_of_another_family_gets_404(self):
        self.client.force_login(self.foreign_parent.user)
        before = self.snapshot()
        for pk, data in self.attempts():
            with self.subTest(pk=pk):
                self.assertEqual(self.client.post(role_url(pk), data).status_code, 404)
        self.assertEqual(self.snapshot(), before)

    def test_foreign_and_missing_ids_look_the_same(self):
        self.client.force_login(self.parent.user)
        before = self.snapshot()
        responses = []
        for pk in (self.foreign_child.pk, self.foreign_parent.pk, 999999):
            with self.subTest(pk=pk):
                response = self.client.post(role_url(pk), {'role': PARENT})
                self.assertEqual(response.status_code, 404)
                content = response.content.decode()
                for name in ('Obca', 'Obcy'):
                    self.assertNotIn(name, content)
                responses.append(content)
        self.assertEqual(len(set(responses)), 1)
        self.assertEqual(self.snapshot(), before)

    def test_role_route_requires_post_and_csrf(self):
        self.client.force_login(self.parent.user)
        self.assertEqual(self.client.get(role_url(self.child.pk)).status_code, 405)
        client = self.client_class(enforce_csrf_checks=True)
        client.force_login(self.parent.user)
        before = self.snapshot()
        self.assertEqual(client.post(role_url(self.child.pk), {'role': PARENT}).status_code, 403)
        self.assertEqual(self.snapshot(), before)


class RoleGuardViewTests(MembershipFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.parent.user)

    def test_self_demotion_without_confirmation_rerenders_with_error(self):
        before = self.snapshot()

        response = self.client.post(role_url(self.parent.pk), {'role': CHILD})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<title>Błąd: ')
        self.assertContains(response, SELF_DEMOTION_CONFIRM_ERROR)
        self.assertContains(response, 'Popraw zaznaczone pola.')
        self.assertEqual(self.snapshot(), before)

    def test_self_demotion_with_confirmation_goes_to_child_home(self):
        response = self.client.post(
            role_url(self.parent.pk), {'role': CHILD, 'confirm_self': 'on'}, follow=True
        )

        self.assertRedirects(
            response, reverse('entries:child_list'), fetch_redirect_response=True
        )
        self.assertEqual(response.redirect_chain[0][0], reverse('home'))
        self.assertContains(response, SELF_DEMOTED_MESSAGE)
        self.parent.refresh_from_db()
        self.assertEqual(self.parent.role, CHILD)

    def test_last_parent_demotion_rerenders_with_guard_error(self):
        FamilyMember.objects.filter(pk=self.other_parent.pk).update(role=CHILD)
        before = self.snapshot()

        response = self.client.post(
            role_url(self.parent.pk), {'role': CHILD, 'confirm_self': 'on'}
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<title>Błąd: ')
        self.assertContains(response, LAST_PARENT_ERROR)
        self.assertContains(response, LAST_PARENT_COPY)
        self.assertEqual(self.snapshot(), before)

    def test_inactive_target_rerenders_with_error(self):
        FamilyMember.objects.filter(pk=self.child.pk).update(is_active=False)
        before = self.snapshot()

        response = self.client.post(role_url(self.child.pk), {'role': PARENT})

        self.assertContains(response, INACTIVE_ROLE_TARGET_ERROR)
        self.assertNotContains(response, role_url(self.child.pk))
        self.assertEqual(self.snapshot(), before)

    def test_invalid_role_value_rerenders_and_changes_nothing(self):
        before = self.snapshot()
        for value in ('admin', ''):
            with self.subTest(value=value):
                response = self.client.post(role_url(self.child.pk), {'role': value})
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'Wybierz rolę: rodzic albo dziecko.')
        self.assertEqual(self.snapshot(), before)


class EditPageRoleTests(MembershipFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.parent.user)

    def page(self, member):
        return self.client.get(edit_url(member.pk)).content.decode()

    def test_child_page_offers_promotion(self):
        content = self.page(self.child)

        self.assertIn('Obecna rola: <strong>Dziecko</strong>', content)
        self.assertIn(role_url(self.child.pk), content)
        self.assertIn(PROMOTE_WARNING, content)
        self.assertNotIn(DEMOTE_WARNING, content)
        self.assertNotIn('confirm_self', content)
        self.assertIn('<legend>Nowa rola</legend>', content)

    def test_parent_page_offers_demotion_with_token_warning(self):
        content = self.page(self.other_parent)

        self.assertIn(role_url(self.other_parent.pk), content)
        self.assertIn(DEMOTE_WARNING, content)
        self.assertNotIn(PROMOTE_WARNING, content)
        self.assertNotIn('confirm_self', content)

    def test_own_page_has_self_demotion_checkbox(self):
        content = self.page(self.parent)

        self.assertIn(role_url(self.parent.pk), content)
        self.assertIn('name="confirm_self"', content)
        self.assertIn('Rozumiem, że stracę uprawnienia rodzica w tej rodzinie.', content)

    def test_last_parent_page_explains_instead_of_offering_the_form(self):
        FamilyMember.objects.filter(pk=self.other_parent.pk).update(role=CHILD)

        content = self.page(self.parent)

        self.assertIn(LAST_PARENT_COPY, content)
        self.assertNotIn(role_url(self.parent.pk), content)

    def test_role_form_preselects_the_other_role(self):
        content = self.page(self.child)

        self.assertRegex(content, r'<input[^>]*value="parent"[^>]*checked')
        self.assertNotRegex(content, r'<input[^>]*value="child"[^>]*checked')


class RoleStateGalleryTests(MembershipFixtureMixin, TestCase):
    ROLE_STATES = (
        'role_promote', 'role_demote', 'role_self_demote', 'role_self_demote_invalid',
        'role_last_parent', 'role_guard_error', 'role_inactive',
    )

    def test_gallery_is_404_without_debug(self):
        self.client.force_login(self.parent.user)
        self.assertEqual(self.client.get(STATES_URL).status_code, 404)

    @override_settings(DEBUG=True)
    def test_role_states_render_without_writes(self):
        self.client.force_login(self.parent.user)
        before = self.snapshot()
        tokens = AutomationToken.objects.count()

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(STATES_URL)

        self.assertEqual(response.status_code, 200)
        for state in self.ROLE_STATES:
            self.assertContains(response, f'data-member-state="{state}"')
        for copy in (PROMOTE_WARNING, DEMOTE_WARNING, LAST_PARENT_COPY, LAST_PARENT_ERROR,
                     SELF_DEMOTION_CONFIRM_ERROR, 'name="confirm_self"'):
            self.assertContains(response, copy)
        writes = [
            query['sql'] for query in queries.captured_queries
            if query['sql'].lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE'))
        ]
        self.assertEqual(writes, [])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(AutomationToken.objects.count(), tokens)


class EffectiveAccessTests(MembershipFixtureMixin, TestCase):
    """A role change governs every product path from the member's next request."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.parent.user)

    def client_for(self, member):
        client = self.client_class()
        client.force_login(member.user)
        return client

    def test_demoted_parent_loses_parent_paths_on_next_request(self):
        _token, secret = AutomationToken.issue(self.other_parent, 'Skrót')
        ping = reverse('automation:ping')
        auth = {'HTTP_AUTHORIZATION': f'Bearer {secret}'}
        sam = self.client_for(self.other_parent)
        self.assertEqual(sam.get(reverse('entries:index')).status_code, 200)
        self.assertEqual(self.client_class().get(ping, **auth).status_code, 200)

        self.client.post(role_url(self.other_parent.pk), {'role': CHILD})

        for name in ('entries:index', 'entries:capture', 'family_members'):
            with self.subTest(url=name):
                self.assertEqual(sam.get(reverse(name)).status_code, 403)
        self.assertEqual(self.client_class().get(ping, **auth).status_code, 401)
        self.assertRedirects(
            sam.get(reverse('home')), reverse('entries:child_list'),
            fetch_redirect_response=False,
        )
        self.assertEqual(sam.get(reverse('entries:child_list')).status_code, 200)

    def test_re_promoted_parent_keeps_old_token_revoked(self):
        _token, secret = AutomationToken.issue(self.other_parent, 'Skrót')
        ping = reverse('automation:ping')

        self.client.post(role_url(self.other_parent.pk), {'role': CHILD})
        self.client.post(role_url(self.other_parent.pk), {'role': PARENT})

        response = self.client_class().get(ping, HTTP_AUTHORIZATION=f'Bearer {secret}')
        self.assertEqual(response.status_code, 401)
        sam = self.client_for(self.other_parent)
        self.assertEqual(sam.get(reverse('entries:index')).status_code, 200)

    def test_promoted_child_gains_parent_paths_on_next_request(self):
        kasia = self.client_for(self.child)
        self.assertEqual(kasia.get(reverse('entries:index')).status_code, 403)

        self.client.post(role_url(self.child.pk), {'role': PARENT})

        for name in ('entries:index', 'family_members'):
            with self.subTest(url=name):
                self.assertEqual(kasia.get(reverse(name)).status_code, 200)
        self.assertRedirects(
            kasia.get(reverse('home')), reverse('entries:index'),
            fetch_redirect_response=False,
        )

    def test_promoted_child_leaves_the_eduvulcan_child_snapshot(self):
        self.assertIn(self.child.pk, [c.pk for c in snapshot_active_children(self.family)])

        self.client.post(role_url(self.child.pk), {'role': PARENT})

        children = snapshot_active_children(self.family)
        self.assertNotIn(self.child.pk, [c.pk for c in children])
        self.assertIsNone(match_child('Kasia', children))

    def test_demoted_parent_joins_the_eduvulcan_child_snapshot_and_matches_by_name(self):
        self.assertIsNone(match_child('Sam', snapshot_active_children(self.family)))

        self.client.post(role_url(self.other_parent.pk), {'role': CHILD})

        children = snapshot_active_children(self.family)
        self.assertIn(self.other_parent.pk, [c.pk for c in children])
        self.assertEqual(match_child('sam', children).pk, self.other_parent.pk)


class ChangedMembershipNoticeTests(MembershipFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.parent.user)
        self.sam = self.client_class()
        self.sam.force_login(self.other_parent.user)

    def assert_notice_once(self, client, notice):
        first = client.get(reverse('account_status'))
        self.assertContains(first, notice, count=1)
        self.assertContains(first, 'role="status"')
        second = client.get(reverse('account_status'))
        self.assertNotContains(second, notice)

    def test_parent_demoted_by_another_parent_sees_notice_once(self):
        self.client.post(role_url(self.other_parent.pk), {'role': CHILD})

        self.assert_notice_once(self.sam, DEMOTED_NOTICE)
        self.assertNotContains(self.sam.get(reverse('entries:child_list')), DEMOTED_NOTICE)

    def test_notice_shows_on_the_child_home_page(self):
        self.client.post(role_url(self.other_parent.pk), {'role': CHILD})

        response = self.sam.get(reverse('home'), follow=True)

        self.assertRedirects(response, reverse('entries:child_list'))
        self.assertContains(response, DEMOTED_NOTICE, count=1)

    def test_parent_deactivated_by_another_parent_sees_notice_once(self):
        self.client.post(reverse('family_member_deactivate', args=[self.other_parent.pk]))

        self.assert_notice_once(self.sam, DEACTIVATED_NOTICE)

    def test_self_demoted_parent_sees_only_the_success_message(self):
        response = self.client.post(
            role_url(self.parent.pk), {'role': CHILD, 'confirm_self': 'on'}, follow=True
        )

        self.assertContains(response, SELF_DEMOTED_MESSAGE)
        self.assertNotContains(response, DEMOTED_NOTICE)
        self.assertNotContains(self.client.get(reverse('account_status')), DEMOTED_NOTICE)

    def test_promotion_shows_no_notice(self):
        kasia = self.client_class()
        kasia.force_login(self.child.user)
        kasia.get(reverse('account_status'))

        self.client.post(role_url(self.child.pk), {'role': PARENT})

        for url in (reverse('account_status'), reverse('entries:index')):
            response = kasia.get(url)
            self.assertNotContains(response, DEMOTED_NOTICE)
            self.assertNotContains(response, DEACTIVATED_NOTICE)

    def test_child_deactivation_and_unchanged_parent_show_no_notice(self):
        kasia = self.client_class()
        kasia.force_login(self.child.user)
        self.client.post(reverse('family_member_deactivate', args=[self.child.pk]))

        self.assertNotContains(kasia.get(reverse('account_status')), DEACTIVATED_NOTICE)
        response = self.sam.get(reverse('account_status'))
        self.assertNotContains(response, DEMOTED_NOTICE)
        self.assertNotContains(response, DEACTIVATED_NOTICE)

    def test_change_while_signed_out_gives_no_notice_after_sign_in(self):
        self.client.post(role_url(self.other_parent.pk), {'role': CHILD})
        fresh = self.client_class()
        fresh.force_login(self.other_parent.user)

        self.assertNotContains(fresh.get(reverse('account_status')), DEMOTED_NOTICE)

    def test_session_stores_ids_and_roles_only(self):
        self.sam.get(reverse('account_status'))

        self.assertEqual(
            self.sam.session[SESSION_KEY], {'id': self.other_parent.pk, 'role': PARENT}
        )
