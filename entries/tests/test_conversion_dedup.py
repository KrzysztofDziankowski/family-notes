"""Duplicate and exam-merge handling during EduVulcan conversion.

Database-backed: notifications are converted through ``convert_notification``
with a fixed ``now``. Text is anonymized and modeled on the sample corpus.
SQLite checks the functional contract; it does not validate the PostgreSQL
family row lock across processes.
"""

import datetime
from unittest import mock

from django.core.exceptions import ValidationError
from django.test import TestCase

from entries.classification.types import EntryType, SchoolItemKind
from entries.eduvulcan.conversion import ConversionOutcome, convert_notification
from entries.eduvulcan.types import OutputKind
from entries.models import Entry, InboundNotification, NotificationConversionOutput
from entries.services import delete_family_entry

from .test_classification_service import FamilyFixtureMixin
from .test_conversion_models import CAPTURED_AT, make_notification

T0 = datetime.datetime(2026, 9, 23, 9, 0, tzinfo=datetime.timezone.utc)
NEXT_DAY = datetime.timedelta(days=1)
LESSON_DATE = datetime.date(2026, 10, 2)
Status = InboundNotification.Status

EXAM_MESSAGE = '2 października, Biologia (biologia), Michał'
GRADE_MESSAGE = 'Nowa ocena: 4+, Matematyka, Michał'


class NoProviderBackend:
    """Fixed-rule fixtures must never reach the classifier."""

    def classify(self, request):
        raise AssertionError('dedup fixtures must convert through fixed rules')


class ConversionDedupTestCase(FamilyFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.next_index = 1

    def receive(self, title, message=EXAM_MESSAGE, *, family=None, captured_at=CAPTURED_AT):
        index = self.next_index
        self.next_index += 1
        return make_notification(
            family or self.family,
            index,
            title=title,
            message=message,
            captured_at=captured_at,
            captured_date=captured_at.date(),
            content_hash=f'{index:064d}',
        )

    def convert(self, row, now=T0):
        result = convert_notification(row.pk, backend=NoProviderBackend(), now=now)
        self.assertEqual(result.outcome, ConversionOutcome.PROCESSED)
        return result

    def output_kinds(self, row):
        return list(
            NotificationConversionOutput.objects.filter(notification=row).values_list(
                'kind', 'entry_id'
            )
        )

    def eduvulcan_entries(self, family=None):
        return Entry.objects.filter(
            family=family or self.family, source=Entry.Source.EDUVULCAN
        ).order_by('pk')


class ExamMergeTests(ConversionDedupTestCase):
    def test_quiz_then_test_leaves_one_upgraded_test_entry(self):
        quiz = self.receive('Kartkówka')
        self.convert(quiz)
        test = self.receive('Sprawdzian', captured_at=CAPTURED_AT + datetime.timedelta(seconds=9))

        self.convert(test)

        entry = self.eduvulcan_entries().get()
        self.assertEqual(entry.content, 'Sprawdzian: Biologia')
        self.assertEqual(entry.school_item, SchoolItemKind.TEST.value)
        self.assertEqual(entry.date, LESSON_DATE)
        self.assertEqual(entry.assigned_member, self.child)
        self.assertEqual(self.output_kinds(quiz), [(OutputKind.RULE.value, entry.pk)])
        self.assertEqual(self.output_kinds(test), [(OutputKind.MERGED.value, None)])

    def test_class_test_then_quiz_keeps_the_class_test(self):
        class_test = self.receive('Praca klasowa')
        self.convert(class_test)
        quiz = self.receive('Kartkówka', captured_at=CAPTURED_AT + datetime.timedelta(seconds=7))

        self.convert(quiz)

        entry = self.eduvulcan_entries().get()
        self.assertEqual(entry.content, 'Praca klasowa: Biologia')
        self.assertEqual(entry.school_item, SchoolItemKind.CLASS_TEST.value)
        self.assertEqual(self.output_kinds(quiz), [(OutputKind.MERGED.value, None)])

    def test_a_rejected_upgrade_is_still_merged_without_a_second_entry(self):
        quiz = self.receive('Kartkówka')
        self.convert(quiz)
        test = self.receive('Sprawdzian', captured_at=CAPTURED_AT + datetime.timedelta(seconds=9))

        with mock.patch(
            'entries.eduvulcan.conversion.upgrade_automated_exam_entry',
            side_effect=ValidationError('odrzucone'),
        ), self.assertLogs('entries.eduvulcan.conversion', 'WARNING') as logs:
            self.convert(test)

        entry = self.eduvulcan_entries().get()
        self.assertEqual(entry.content, 'Kartkówka: Biologia')
        self.assertEqual(self.output_kinds(test), [(OutputKind.MERGED.value, None)])
        self.assertIn(f'upgrade rejected: notification={test.pk} entry={entry.pk}', logs.output[0])
        self.assertNotIn('Biologia', ''.join(logs.output))

    def test_retrying_a_merged_notification_creates_nothing_new(self):
        self.convert(self.receive('Sprawdzian'))
        quiz = self.receive('Kartkówka')
        self.convert(quiz)
        InboundNotification.objects.filter(pk=quiz.pk).update(status=Status.PENDING)

        again = self.convert(quiz, now=T0 + datetime.timedelta(minutes=5))

        self.assertEqual(self.eduvulcan_entries().count(), 1)
        self.assertEqual(self.eduvulcan_entries().get().content, 'Sprawdzian: Biologia')
        self.assertEqual(
            [(output.kind, output.entry_id) for output in again.outputs],
            [(OutputKind.MERGED.value, None)],
        )

    def test_a_different_subject_is_not_merged(self):
        self.convert(self.receive('Kartkówka'))

        self.convert(self.receive('Sprawdzian', message='2 października, Chemia (chemia), Michał'))

        self.assertEqual(
            list(self.eduvulcan_entries().values_list('content', flat=True)),
            ['Kartkówka: Biologia', 'Sprawdzian: Chemia'],
        )


class DuplicateTests(ConversionDedupTestCase):
    def test_exact_resend_on_a_later_day_is_a_duplicate(self):
        first = self.receive('Sprawdzian')
        self.convert(first)
        resend = self.receive('Sprawdzian', captured_at=CAPTURED_AT + NEXT_DAY)

        self.convert(resend, now=T0 + NEXT_DAY)

        entry = self.eduvulcan_entries().get()
        self.assertEqual(entry.content, 'Sprawdzian: Biologia')
        self.assertNotEqual(first.notification_id, resend.notification_id)
        self.assertEqual(self.output_kinds(resend), [(OutputKind.DUPLICATE.value, None)])
        self.assertEqual(self.reload_status(resend), Status.PROCESSED)

    def test_undated_grade_is_a_duplicate_only_on_the_same_capture_day(self):
        self.convert(self.receive('Ocena', GRADE_MESSAGE))
        same_day = self.receive('Ocena', GRADE_MESSAGE)
        self.convert(same_day)
        next_day = self.receive('Ocena', GRADE_MESSAGE, captured_at=CAPTURED_AT + NEXT_DAY)

        self.convert(next_day, now=T0 + NEXT_DAY)

        self.assertEqual(self.output_kinds(same_day), [(OutputKind.DUPLICATE.value, None)])
        self.assertEqual(self.output_kinds(next_day)[0][0], OutputKind.RULE.value)
        self.assertEqual(self.eduvulcan_entries().count(), 2)

    def test_a_parent_deleted_entry_is_recreated_by_a_resend(self):
        first = self.convert(self.receive('Sprawdzian'))
        delete_family_entry(self.parent, first.outputs[0].entry_id)
        resend = self.receive('Sprawdzian', captured_at=CAPTURED_AT + NEXT_DAY)

        self.convert(resend, now=T0 + NEXT_DAY)

        entry = self.eduvulcan_entries().get()
        self.assertEqual(entry.content, 'Sprawdzian: Biologia')
        self.assertEqual(self.output_kinds(resend), [(OutputKind.RULE.value, entry.pk)])

    def test_a_manual_entry_with_identical_text_is_untouched_and_does_not_block(self):
        manual = Entry.objects.create(
            family=self.family,
            entry_type=EntryType.CALENDAR_EVENT.value,
            content='Kartkówka: Biologia',
            date=LESSON_DATE,
            assigned_member=self.child,
            school_item=SchoolItemKind.QUIZ.value,
            school_subject='Biologia',
            created_by=self.parent,
        )
        updated_at = manual.updated_at

        self.convert(self.receive('Sprawdzian'))
        self.convert(self.receive('Kartkówka'))

        manual.refresh_from_db()
        self.assertEqual(manual.content, 'Kartkówka: Biologia')
        self.assertEqual(manual.school_item, SchoolItemKind.QUIZ.value)
        self.assertEqual(manual.updated_at, updated_at)
        self.assertEqual(
            list(self.eduvulcan_entries().values_list('content', flat=True)),
            ['Sprawdzian: Biologia'],
        )

    def test_a_manual_entry_with_the_same_text_does_not_block_creation(self):
        Entry.objects.create(
            family=self.family,
            entry_type=EntryType.CALENDAR_EVENT.value,
            content='Sprawdzian: Biologia',
            date=LESSON_DATE,
            assigned_member=self.child,
            school_item=SchoolItemKind.TEST.value,
            school_subject='Biologia',
            created_by=self.parent,
        )

        row = self.receive('Sprawdzian')
        self.convert(row)

        self.assertEqual(self.eduvulcan_entries().count(), 1)
        self.assertEqual(self.output_kinds(row)[0][0], OutputKind.RULE.value)

    def test_another_familys_identical_entry_does_not_block_creation(self):
        # A child unknown to both families: both entries are unassigned and identical.
        message = '2 października, Biologia (biologia), Olek'
        self.convert(self.receive('Sprawdzian', message, family=self.other_family))
        foreign = self.eduvulcan_entries(self.other_family).get()

        row = self.receive('Sprawdzian', message)
        self.convert(row)

        entry = self.eduvulcan_entries().get()
        self.assertEqual(
            (entry.content, entry.assigned_member_id, entry.date),
            (foreign.content, foreign.assigned_member_id, foreign.date),
        )
        self.assertIsNone(entry.assigned_member_id)
        self.assertEqual(self.output_kinds(row), [(OutputKind.RULE.value, entry.pk)])
        self.assertEqual(self.eduvulcan_entries(self.other_family).count(), 1)

    def test_processed_log_reports_duplicate_and_merged_counts_without_text(self):
        self.convert(self.receive('Sprawdzian'))
        quiz = self.receive('Kartkówka')

        with self.assertLogs('entries.eduvulcan.conversion', level='INFO') as logs:
            self.convert(quiz)

        line = next(message for message in logs.output if 'processed' in message)
        self.assertIn(f'notification={quiz.pk}', line)
        self.assertIn('outputs=1 duplicates=0 merged=1', line)
        self.assertNotIn('Biologia', line)
        self.assertNotIn('Kartkówka', line)

    def reload_status(self, row):
        row.refresh_from_db()
        return row.status
