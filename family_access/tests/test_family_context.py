"""S-16: several families per person, the chooser, the header switcher and the stale-tab guard."""

import re

from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import resolve, reverse

from entries import urls as entries_urls
from entries.classification.types import EntryType
from entries.models import Entry
from family_access import urls as family_access_urls
from family_access.context import FORM_FIELD, SESSION_KEY, is_guarded_view
from family_access.membership import reactivate_member
from family_access.models import AutomationToken, Family, FamilyMember

CHOOSER_URL = reverse('select_family')
STALE_COPY = 'Ta strona dotyczyła innej rodziny. Odśwież ją i spróbuj ponownie.'
POST_FORM = re.compile(r'<form\b[^>]*method="post"[^>]*>.*?</form>', re.DOTALL)
FORM_ACTION = re.compile(r'action="([^"]*)"')


def guarded_routes(entry_pk, member_pk):
    """Every route of the ``entries`` and ``family_access`` URL modules except the chooser."""
    routes = []
    for prefix, module in (('entries:', entries_urls), ('', family_access_urls)):
        for pattern in module.urlpatterns:
            if pattern.name == 'select_family':
                continue
            kwargs = {}
            if 'pk' in pattern.pattern.converters:
                kwargs['pk'] = entry_pk if prefix else member_pk
            routes.append((prefix + pattern.name, reverse(prefix + pattern.name, kwargs=kwargs)))
    return routes


class MultiFamilyFixtureMixin:
    """Ewa is a parent in "Rodzina testowa" (A) and in "Inna rodzina" (B)."""

    def setUp(self):
        super().setUp()
        self.family_a = Family.objects.create(name='Rodzina testowa')
        self.family_b = Family.objects.create(name='Inna rodzina')
        self.user = get_user_model().objects.create_user(username='ewa', email='ewa@example.test')
        self.parent_a = self.membership(self.user, self.family_a, FamilyMember.Role.PARENT, 'Ewa')
        self.parent_b = self.membership(self.user, self.family_b, FamilyMember.Role.PARENT, 'Ewa')
        self.child_a = self.member('kasia', self.family_a, FamilyMember.Role.CHILD, 'Kasia')
        self.child_b = self.member('tymek', self.family_b, FamilyMember.Role.CHILD, 'Tymek')
        self.entry_a = Entry.objects.create(
            family=self.family_a, entry_type=EntryType.TODO.value, content='Wpis A',
            assigned_member=self.child_a, created_by=self.parent_a,
        )
        self.entry_b = Entry.objects.create(
            family=self.family_b, entry_type=EntryType.TODO.value, content='Wpis B',
            assigned_member=self.child_b, created_by=self.parent_b,
        )

    def membership(self, user, family, role, display_name, is_active=True):
        return FamilyMember.objects.create(
            user=user, family=family, role=role, display_name=display_name, is_active=is_active,
        )

    def member(self, username, family, role, display_name, is_active=True):
        user = get_user_model().objects.create_user(
            username=username, email=f'{username}@example.test'
        )
        return self.membership(user, family, role, display_name, is_active)

    def sign_in(self, family=None):
        self.client.force_login(self.user)
        if family is not None:
            self.choose(family)

    def choose(self, family):
        session = self.client.session
        session[SESSION_KEY] = family.pk
        session.save()

    def snapshot(self):
        return (
            sorted(Entry.objects.values_list(
                'pk', 'family_id', 'entry_type', 'content', 'date', 'assigned_member_id',
                'updated_at',
            )),
            sorted(FamilyMember.objects.values_list(
                'pk', 'family_id', 'display_name', 'role', 'is_active',
            )),
            sorted(AutomationToken.objects.values_list('pk', 'revoked_at')),
        )

    def routes(self):
        return guarded_routes(self.entry_b.pk, self.child_b.pk)


class ChooserTests(MultiFamilyFixtureMixin, TestCase):
    def test_lists_only_the_users_own_active_memberships(self):
        inactive_family = Family.objects.create(name='Rodzina nieaktywna', is_active=False)
        self.membership(self.user, inactive_family, FamilyMember.Role.PARENT, 'Ewa')
        former = Family.objects.create(name='Rodzina dawna')
        self.membership(self.user, former, FamilyMember.Role.CHILD, 'Ewa', is_active=False)
        Family.objects.create(name='Rodzina obca')
        self.sign_in()

        response = self.client.get(CHOOSER_URL)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Rodzina testowa (Rodzic)')
        self.assertContains(response, 'Inna rodzina (Rodzic)')
        self.assertContains(response, 'name="family_id"', count=2)
        for name in ('Rodzina nieaktywna', 'Rodzina dawna', 'Rodzina obca'):
            self.assertNotContains(response, name)

    def test_role_is_shown_per_membership(self):
        self.parent_b.role = FamilyMember.Role.CHILD
        self.parent_b.save(update_fields=['role'])
        self.sign_in()

        response = self.client.get(CHOOSER_URL)

        self.assertContains(response, 'Rodzina testowa (Rodzic)')
        self.assertContains(response, 'Inna rodzina (Dziecko)')

    def test_choice_is_stored_and_lands_on_the_role_home(self):
        self.parent_b.role = FamilyMember.Role.CHILD
        self.parent_b.save(update_fields=['role'])
        self.sign_in()

        response = self.client.post(CHOOSER_URL, {'family_id': self.family_a.pk})

        self.assertRedirects(response, reverse('home'), fetch_redirect_response=False)
        self.assertEqual(self.client.session[SESSION_KEY], self.family_a.pk)
        self.assertRedirects(self.client.get(reverse('home')), reverse('entries:index'))

        self.client.post(CHOOSER_URL, {'family_id': self.family_b.pk})

        self.assertEqual(self.client.session[SESSION_KEY], self.family_b.pk)
        self.assertRedirects(self.client.get(reverse('home')), reverse('entries:child_list'))

    def test_foreign_or_inactive_family_is_404_and_session_unchanged(self):
        foreign = Family.objects.create(name='Rodzina obca')
        self.member('obcy', foreign, FamilyMember.Role.PARENT, 'Obcy')
        former = Family.objects.create(name='Rodzina dawna')
        self.membership(self.user, former, FamilyMember.Role.PARENT, 'Ewa', is_active=False)
        inactive_family = Family.objects.create(name='Rodzina nieaktywna', is_active=False)
        self.membership(self.user, inactive_family, FamilyMember.Role.PARENT, 'Ewa')
        self.sign_in(self.family_a)

        for family_id in (foreign.pk, former.pk, inactive_family.pk, 999999):
            with self.subTest(family_id=family_id):
                response = self.client.post(CHOOSER_URL, {'family_id': family_id})

                self.assertEqual(response.status_code, 404)
                self.assertEqual(self.client.session[SESSION_KEY], self.family_a.pk)

    def test_missing_or_malformed_choice_re_renders_with_an_error(self):
        self.sign_in(self.family_a)

        for data in ({}, {'family_id': ''}, {'family_id': 'abc'}, {'family_id': '-1'}):
            with self.subTest(data=data):
                response = self.client.post(CHOOSER_URL, data)

                self.assertContains(response, 'Wybierz rodzinę.', status_code=200)
                self.assertContains(response, 'aria-invalid="true"')
                self.assertEqual(self.client.session[SESSION_KEY], self.family_a.pk)

    def test_switch_requires_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)

        response = client.post(CHOOSER_URL, {'family_id': self.family_b.pk})

        self.assertEqual(response.status_code, 403)
        self.assertNotIn(SESSION_KEY, client.session)

    def test_chooser_requires_sign_in(self):
        response = self.client.get(CHOOSER_URL)

        self.assertRedirects(
            response, f"{reverse('account_login')}?next={CHOOSER_URL}",
            fetch_redirect_response=False,
        )


@override_settings(DEBUG=True)
class ChooserRedirectTests(MultiFamilyFixtureMixin, TestCase):
    def test_multi_family_user_without_selection_is_sent_to_the_chooser(self):
        self.sign_in()
        routes = [('home', reverse('home')), *self.routes()]

        for name, url in routes:
            with self.subTest(name):
                response = self.client.get(url)
                if response.status_code != 405:
                    self.assertRedirects(response, CHOOSER_URL, fetch_redirect_response=False)
                if name != 'home':
                    response = self.client.post(url, {FORM_FIELD: self.family_a.pk})
                    self.assertRedirects(response, CHOOSER_URL, fetch_redirect_response=False)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_single_family_user_is_never_sent_to_the_chooser(self):
        self.parent_b.delete()
        self.sign_in()
        routes = guarded_routes(self.entry_a.pk, self.child_a.pk)

        for name, url in [('home', reverse('home')), *routes]:
            with self.subTest(name):
                response = self.client.get(url)
                self.assertNotEqual(response.get('Location'), CHOOSER_URL)

    def test_deactivated_selection_falls_back_to_the_remaining_family(self):
        self.sign_in(self.family_b)
        self.parent_b.is_active = False
        self.parent_b.save(update_fields=['is_active'])

        response = self.client.get(reverse('entries:index'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Wpis A')
        self.assertEqual(self.client.session[SESSION_KEY], self.family_a.pk)


@override_settings(DEBUG=True)
class StaleTabGuardTests(MultiFamilyFixtureMixin, TestCase):
    def test_every_route_resolves_to_a_guarded_view(self):
        for name, url in self.routes():
            with self.subTest(name):
                self.assertTrue(is_guarded_view(resolve(url)))
        self.assertFalse(is_guarded_view(resolve(CHOOSER_URL)))
        self.assertFalse(is_guarded_view(resolve(reverse('automation:entries_list'))))

    def assert_refused(self, data):
        before = self.snapshot()
        for name, url in self.routes():
            with self.subTest(name):
                response = self.client.post(url, data)

                self.assertContains(response, STALE_COPY, status_code=409)
                self.assertTemplateUsed(response, '409.html')
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.client.session[SESSION_KEY], self.family_b.pk)

    def test_form_of_another_family_is_refused_without_writes(self):
        self.sign_in(self.family_b)

        self.assert_refused({FORM_FIELD: str(self.family_a.pk), 'display_name': 'Nowe',
                             'content': 'Nowy wpis', 'entry_type': EntryType.NOTE.value})

    def test_missing_field_is_refused_for_a_multi_family_user(self):
        self.sign_in(self.family_b)

        self.assert_refused({'display_name': 'Nowe', 'content': 'Nowy wpis',
                             'entry_type': EntryType.NOTE.value})

    def test_garbage_field_is_refused(self):
        self.sign_in(self.family_b)

        self.assert_refused({FORM_FIELD: 'B', 'content': 'Nowy wpis'})

    def test_stale_capture_creates_no_entry(self):
        self.sign_in(self.family_b)
        before = Entry.objects.count()

        response = self.client.post(reverse('entries:create'), {
            FORM_FIELD: str(self.family_a.pk),
            'entry_type': EntryType.NOTE.value,
            'content': 'Nowy wpis',
            'submission_key': '6b0f7c2e-79a4-4d55-a1b2-1f0d1f2f3a4b',
        })

        self.assertEqual(response.status_code, 409)
        self.assertEqual(Entry.objects.count(), before)

    def test_matching_field_reaches_the_view(self):
        self.sign_in(self.family_b)

        response = self.client.post(reverse('entries:create'), {
            FORM_FIELD: str(self.family_b.pk),
            'entry_type': EntryType.NOTE.value,
            'content': 'Nowy wpis',
            'submission_key': '6b0f7c2e-79a4-4d55-a1b2-1f0d1f2f3a4b',
        })

        created = Entry.objects.get(content='Nowy wpis')
        self.assertRedirects(response, reverse('entries:detail', args=[created.pk]))
        self.assertEqual(created.family, self.family_b)

    def test_missing_field_is_accepted_for_a_single_family_user(self):
        self.parent_b.delete()
        self.sign_in()

        for name, url in guarded_routes(self.entry_a.pk, self.child_a.pk):
            with self.subTest(name):
                response = self.client.post(url, {})
                self.assertNotEqual(response.status_code, 409)

    def test_single_family_user_with_a_foreign_field_is_refused(self):
        self.parent_b.delete()
        self.sign_in()

        response = self.client.post(reverse('entries:delete', args=[self.entry_a.pk]),
                                    {FORM_FIELD: str(self.family_b.pk)})

        self.assertEqual(response.status_code, 409)
        self.assertTrue(Entry.objects.filter(pk=self.entry_a.pk).exists())

    def test_chooser_and_logout_are_exempt(self):
        self.sign_in(self.family_b)

        response = self.client.post(CHOOSER_URL, {'family_id': self.family_a.pk})
        self.assertRedirects(response, reverse('home'), fetch_redirect_response=False)

        response = self.client.post(reverse('account_logout'))
        self.assertNotEqual(response.status_code, 409)
        self.assertNotIn('_auth_user_id', self.client.session)


@override_settings(DEBUG=True)
class FormFamilyFieldTests(MultiFamilyFixtureMixin, TestCase):
    def guarded_forms(self, response):
        forms = []
        for form in POST_FORM.findall(response.content.decode()):
            action = FORM_ACTION.search(form).group(1)
            if is_guarded_view(resolve(action)):
                forms.append((action, form))
        return forms

    def test_every_post_form_carries_the_current_family(self):
        self.sign_in(self.family_a)
        pages = [
            reverse('entries:capture'),
            reverse('entries:create'),
            reverse('entries:detail', args=[self.entry_a.pk]),
            reverse('entries:edit', args=[self.entry_a.pk]),
            reverse('entries:states'),
            reverse('family_members'),
            reverse('family_member_edit', args=[self.child_a.pk]),
            reverse('family_member_states'),
        ]
        field = f'<input type="hidden" name="{FORM_FIELD}" value="{self.family_a.pk}">'
        seen = set()

        for url in pages:
            with self.subTest(url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                for action, form in self.guarded_forms(response):
                    seen.add(resolve(action).view_name)
                    self.assertIn(field, form, f'{url}: form posting to {action}')

        expected = {
            'entries:capture', 'entries:answer', 'entries:confirm', 'entries:confirm_batch',
            'entries:create', 'entries:edit', 'entries:delete', 'family_member_edit',
            'family_member_deactivate', 'family_member_reactivate', 'family_member_role',
        }
        self.assertTrue(expected <= seen, expected - seen)


class HeaderSwitcherTests(MultiFamilyFixtureMixin, TestCase):
    def test_multi_family_header_shows_the_current_family_and_the_switch_link(self):
        self.sign_in(self.family_b)

        response = self.client.get(reverse('entries:index'))

        self.assertContains(response, 'Rodzina: <strong>Inna rodzina</strong>')
        self.assertContains(response, f'<a href="{CHOOSER_URL}">Zmień rodzinę</a>')
        self.assertContains(response, 'Wpis B')
        self.assertNotContains(response, 'Wpis A')

    def test_single_family_header_is_unchanged(self):
        self.parent_b.delete()
        self.sign_in()

        response = self.client.get(reverse('entries:index'))

        self.assertNotContains(response, 'Zmień rodzinę')
        self.assertNotContains(response, 'Rodzina:')

    def test_operator_added_membership_keeps_the_signed_in_family(self):
        self.parent_b.delete()
        self.sign_in()
        self.assertEqual(self.client.session[SESSION_KEY], self.family_a.pk)
        self.membership(self.user, self.family_b, FamilyMember.Role.CHILD, 'Ewa')

        response = self.client.get(reverse('entries:index'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Rodzina: <strong>Rodzina testowa</strong>')
        self.assertContains(response, 'Zmień rodzinę')

    def test_switching_family_shows_no_lost_role_notice(self):
        self.parent_b.role = FamilyMember.Role.CHILD
        self.parent_b.save(update_fields=['role'])
        self.sign_in(self.family_a)
        self.client.get(reverse('entries:index'))

        self.client.post(CHOOSER_URL, {'family_id': self.family_b.pk})
        response = self.client.get(reverse('entries:child_list'))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'zmienił Twoją rolę')
        self.assertNotContains(response, 'zostały wyłączone')


class NoSelectionRenderingTests(MultiFamilyFixtureMixin, TestCase):
    """The header never raises or redirects while no family is selected."""

    def test_chooser_logout_and_404_render_without_a_selection(self):
        self.sign_in()

        chooser = self.client.get(CHOOSER_URL)
        self.assertEqual(chooser.status_code, 200)
        self.assertContains(chooser, f'<a href="{CHOOSER_URL}">Wybierz rodzinę</a>')

        logout = self.client.get(reverse('account_logout'))
        self.assertEqual(logout.status_code, 200)

        missing = self.client.get('/nie-ma-takiej-strony/')
        self.assertEqual(missing.status_code, 404)
        self.assertTemplateUsed(missing, '404.html')
        self.assertNotIn('Location', missing)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_anonymous_pages_run_no_family_query(self):
        for url in (reverse('account_login'), '/nie-ma-takiej-strony/'):
            with self.subTest(url), CaptureQueriesContext(connection) as queries:
                self.client.get(url)

            self.assertFalse(
                [q for q in queries.captured_queries if 'family_access_' in q['sql']]
            )


class AdminSecondMembershipTests(MultiFamilyFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.parent_b.delete()
        self.operator = get_user_model().objects.create_superuser(
            username='operator', email='operator@example.test', password='unused-password'
        )
        self.client.force_login(self.operator)

    def add(self, family, display_name='Ewa'):
        return self.client.post(reverse('admin:family_access_familymember_add'), {
            'user': self.user.pk,
            'family': family.pk,
            'role': FamilyMember.Role.CHILD,
            'display_name': display_name,
            'is_active': 'on',
        })

    def test_operator_adds_an_active_membership_in_a_second_family(self):
        response = self.add(self.family_b)

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            FamilyMember.objects.filter(user=self.user, family=self.family_b, is_active=True)
            .exists()
        )
        self.assertEqual(FamilyMember.objects.filter(user=self.user, is_active=True).count(), 2)

    def test_duplicate_active_membership_in_one_family_is_a_form_error(self):
        before = self.snapshot()

        response = self.add(self.family_a, display_name='Ewa druga')

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, 'This user already has an active membership in this family.'
        )
        self.assertEqual(self.snapshot(), before)


class CrossFamilyReactivationTests(MultiFamilyFixtureMixin, TestCase):
    def test_reactivation_succeeds_when_the_user_is_active_in_another_family(self):
        self.child_a.is_active = False
        self.child_a.save(update_fields=['is_active'])
        self.membership(self.child_a.user, self.family_b, FamilyMember.Role.CHILD, 'Kasia')

        reactivate_member(self.parent_a, self.child_a.pk)

        self.child_a.refresh_from_db()
        self.assertTrue(self.child_a.is_active)
        self.assertEqual(
            FamilyMember.objects.filter(user=self.child_a.user, is_active=True).count(), 2
        )


class MembershipConstraintMigrationTests(TransactionTestCase):
    """``0004`` lifts one-membership-per-user without touching rows; its rollback is guarded."""

    before = [('family_access', '0003_authcacheentry')]
    after = [('family_access', '0004_membership_per_family')]

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def test_forward_keeps_rows_and_allows_one_active_membership_per_family(self):
        old_apps = self.migrate(self.before)
        User = old_apps.get_model('auth', 'User')
        OldFamily = old_apps.get_model('family_access', 'Family')
        OldMember = old_apps.get_model('family_access', 'FamilyMember')
        user = User.objects.create(username='ewa')
        family_a = OldFamily.objects.create(name='Rodzina testowa')
        family_b = OldFamily.objects.create(name='Inna rodzina')
        active = OldMember.objects.create(
            user=user, family=family_a, role='parent', display_name='Ewa', is_active=True,
        )
        OldMember.objects.create(
            user=user, family=family_b, role='child', display_name='Ewa', is_active=False,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            OldMember.objects.create(
                user=user, family=family_b, role='child', display_name='Ewa', is_active=True,
            )

        new_apps = self.migrate(self.after)
        Member = new_apps.get_model('family_access', 'FamilyMember')

        self.assertEqual(Member.objects.count(), 2)
        self.assertTrue(Member.objects.get(pk=active.pk).is_active)
        Member.objects.create(
            user_id=user.pk, family_id=family_b.pk, role='child', display_name='Ewa',
            is_active=True,
        )
        self.assertEqual(Member.objects.filter(user_id=user.pk, is_active=True).count(), 2)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Member.objects.create(
                user_id=user.pk, family_id=family_a.pk, role='child', display_name='Ewa',
                is_active=True,
            )

    def test_rollback_refuses_with_offending_user_ids_until_extras_are_deactivated(self):
        new_apps = self.migrate(self.after)
        User = new_apps.get_model('auth', 'User')
        Family_ = new_apps.get_model('family_access', 'Family')
        Member = new_apps.get_model('family_access', 'FamilyMember')
        user = User.objects.create(username='ewa', email='ewa@example.test')
        single = User.objects.create(username='kasia')
        family_a = Family_.objects.create(name='Rodzina testowa')
        family_b = Family_.objects.create(name='Inna rodzina')
        Member.objects.create(user=user, family=family_a, role='parent', display_name='Ewa')
        extra = Member.objects.create(
            user=user, family=family_b, role='child', display_name='Ewa',
        )
        Member.objects.create(user=single, family=family_a, role='child', display_name='Kasia')

        with self.assertRaises(RuntimeError) as caught:
            self.migrate(self.before)

        message = str(caught.exception)
        self.assertIn(f': {user.pk}.', message)
        self.assertNotIn('ewa@example.test', message)
        self.assertNotIn('Ewa', message)

        Member.objects.filter(pk=extra.pk).update(is_active=False)
        self.migrate(self.before)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Member.objects.filter(pk=extra.pk).update(is_active=True)
