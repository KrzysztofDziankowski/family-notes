"""Membership audit lines reach the configured log output (Operator Recovery Runbook, step 2).

``assertLogs`` lowers the logger level for the duration of the block, so it would pass even if
``LOGGING`` filtered the line out. These tests keep the configured levels and listen on the root
logger, where the console handler sits.
"""

import logging

from django.test import TestCase

from family_access.membership import change_member_role, deactivate_member
from family_access.models import FamilyMember

from .test_membership_services import MembershipFixtureMixin


class _ListHandler(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


class MembershipLoggingTests(MembershipFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.handler = _ListHandler()
        root = logging.getLogger()
        root.addHandler(self.handler)
        self.addCleanup(root.removeHandler, self.handler)

    def events(self):
        return [m for m in self.handler.messages if m.startswith('membership_event=')]

    def test_configured_level_lets_membership_info_through(self):
        self.assertTrue(logging.getLogger('family_access.membership').isEnabledFor(logging.INFO))

    def test_role_change_line_reaches_root_handler_with_ids_only(self):
        change_member_role(self.parent, self.child.pk, FamilyMember.Role.PARENT)

        self.assertEqual(
            self.events(),
            [
                f'membership_event=role_changed family={self.family.pk} '
                f'member={self.child.pk} actor={self.parent.pk} old_role=child new_role=parent'
            ],
        )

    def test_deactivation_line_reaches_root_handler_without_names(self):
        deactivate_member(self.parent, self.child.pk)

        events = self.events()
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0].startswith('membership_event=member_deactivated '))
        for private in ('Kasia', 'Alex', 'child@example.test', 'parent@example.test'):
            self.assertNotIn(private, events[0])
