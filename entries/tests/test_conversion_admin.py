"""Operator admin for the conversion lifecycle (S-05 Phase 2).

The inbox stays read-only; superusers get only a requeue action for failed
rows, diagnostics stay sanitized, and pruned rows show an explicit state.
"""

import datetime

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from entries.eduvulcan.conversion import convert_notification, prune_raw_notifications
from entries.models import InboundNotification, NotificationConversionOutput
from family_access.tests.test_automation import AutomationFixtureMixin

from .test_conversion_models import make_notification

Status = InboundNotification.Status
CHANGELIST = reverse('admin:entries_inboundnotification_changelist')
LEGACY_ERROR_SENTINEL = 'SENTINEL-LEGACY-ERROR-91b2'


class ConversionAdminTests(AutomationFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.failed = make_notification(
            self.family,
            1,
            status=Status.FAILED,
            attempt_count=3,
            last_error_code='database_busy',
            error=LEGACY_ERROR_SENTINEL,
        )
        self.pending = make_notification(self.family, 2, message='Nowa ocena: 5, Plastyka, Child')
        self.superuser = get_user_model().objects.create_superuser(
            username='operator', email='operator@example.test', password='unused'
        )

    def change_url(self, row):
        return reverse('admin:entries_inboundnotification_change', args=(row.pk,))

    def requeue(self, *rows):
        return self.client.post(
            CHANGELIST,
            {
                'action': 'requeue_failed',
                'index': 0,
                '_selected_action': [row.pk for row in rows],
            },
            follow=True,
        )

    def test_superuser_can_requeue_failed_rows_only(self):
        self.client.force_login(self.superuser)
        payload = dict(self.failed.payload)

        response = self.requeue(self.failed, self.pending)

        self.assertContains(response, 'Requeued failed notifications: 1.')
        self.failed.refresh_from_db()
        self.assertEqual((self.failed.status, self.failed.attempt_count), (Status.PENDING, 0))
        self.assertEqual(self.failed.payload, payload)
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, Status.PENDING)

    def test_requeue_is_the_only_granted_write(self):
        self.client.force_login(self.superuser)
        changelist = self.client.get(CHANGELIST)
        self.assertContains(changelist, 'Requeue selected failed notifications')

        self.assertEqual(self.client.get(reverse('admin:entries_inboundnotification_add')).status_code, 403)
        page = self.client.get(self.change_url(self.failed))
        self.assertNotContains(page, 'name="title"')
        self.assertNotContains(page, 'name="status"')
        self.client.post(self.change_url(self.failed), {'title': 'Zmieniony', 'status': 'pending'})

        self.failed.refresh_from_db()
        self.assertEqual((self.failed.status, self.failed.title), (Status.FAILED, 'Sprawdzian'))

    def test_superuser_cannot_delete_notifications(self):
        self.client.force_login(self.superuser)
        model_admin = admin.site._registry[InboundNotification]
        request = RequestFactory().get('/')
        request.user = self.superuser

        self.assertIs(model_admin.has_delete_permission(request), False)
        self.assertIs(model_admin.has_delete_permission(request, self.failed), False)
        self.assertNotIn('delete_selected', model_admin.get_actions(request))
        delete_url = reverse('admin:entries_inboundnotification_delete', args=(self.failed.pk,))
        self.assertEqual(self.client.get(delete_url).status_code, 403)
        self.client.post(
            CHANGELIST,
            {'action': 'delete_selected', 'index': 0, '_selected_action': [self.failed.pk]},
        )
        self.client.post(delete_url, {'post': 'yes'})

        self.assertTrue(InboundNotification.objects.filter(pk=self.failed.pk).exists())

    def test_staff_without_superuser_cannot_requeue(self):
        staff = get_user_model().objects.create_user(
            username='staff', email='staff@example.test', is_staff=True
        )
        staff.user_permissions.add(
            Permission.objects.get(codename='view_inboundnotification'),
            Permission.objects.get(codename='change_inboundnotification'),
        )
        self.client.force_login(staff)

        # The project admin site admits superusers only; the action is also
        # gated on superuser status in case that ever changes.
        self.assertRedirects(
            self.client.get(CHANGELIST), f"{reverse('admin:login')}?next={CHANGELIST}"
        )
        self.requeue(self.failed)

        self.failed.refresh_from_db()
        self.assertEqual(self.failed.status, Status.FAILED)

    def test_family_members_are_denied_the_requeue_action(self):
        self.client.force_login(self.parent.user)

        response = self.client.post(
            CHANGELIST,
            {'action': 'requeue_failed', 'index': 0, '_selected_action': [self.failed.pk]},
        )

        self.assertRedirects(response, f"{reverse('admin:login')}?next={CHANGELIST}")
        self.failed.refresh_from_db()
        self.assertEqual(self.failed.status, Status.FAILED)

    def test_failed_row_shows_only_sanitized_diagnostics(self):
        self.client.force_login(self.superuser)

        page = self.client.get(self.change_url(self.failed))

        self.assertContains(page, 'database_busy')
        self.assertContains(page, 'Attempt count')
        self.assertNotContains(page, LEGACY_ERROR_SENTINEL)
        self.assertNotContains(self.client.get(CHANGELIST), LEGACY_ERROR_SENTINEL)

    def test_pruned_row_renders_an_explicit_state_and_keeps_provenance(self):
        row = make_notification(self.family, 3, title='Ocena', message='Nowa ocena: 4, Muzyka, Child')
        convert_notification(row.pk)
        InboundNotification.objects.filter(pk=row.pk).update(
            received_at=timezone.now() - datetime.timedelta(days=91)
        )
        prune_raw_notifications()
        output = NotificationConversionOutput.objects.get(notification=row)
        self.client.force_login(self.superuser)

        changelist = self.client.get(CHANGELIST)
        page = self.client.get(self.change_url(row))

        self.assertContains(changelist, 'Raw data pruned')
        self.assertContains(page, 'Raw data pruned')
        self.assertContains(page, 'Fixed rule')
        self.assertContains(page, str(output.entry))
        self.assertNotContains(page, 'Muzyka')


class RequeuePermissionTests(TestCase):
    def test_requeue_permission_requires_an_active_staff_superuser(self):
        model_admin = admin.site._registry[InboundNotification]
        request = RequestFactory().get('/')
        User = get_user_model()
        cases = (
            (User(is_active=True, is_staff=True, is_superuser=True), True),
            (User(is_active=True, is_staff=True, is_superuser=False), False),
            (User(is_active=False, is_staff=True, is_superuser=True), False),
        )
        for user, allowed in cases:
            with self.subTest(allowed=allowed, active=user.is_active):
                request.user = user
                self.assertIs(model_admin.has_requeue_permission(request), allowed)
                self.assertIs(model_admin.has_change_permission(request), False)
                self.assertIs(model_admin.has_add_permission(request), False)
