import datetime
import uuid

from django.test import TestCase

from entries.classification.service import ParentClassification
from entries.classification.types import (
    ClassificationFollowUp,
    ClassificationProposal,
    ClassificationUnavailable,
    EntryType,
    MissingField,
    SchoolItemKind,
    UnavailableReason,
)
from entries.forms import CaptureForm, EntryReviewForm, review_form_from_classification

from .test_classification_service import FamilyFixtureMixin

MONDAY = datetime.date(2026, 9, 21)


class EntryReviewFormTests(FamilyFixtureMixin, TestCase):
    def bound(self, **overrides):
        data = {
            'entry_type': EntryType.CALENDAR_EVENT.value,
            'content': 'Sprawdzian z biologii o skórze',
            'date': MONDAY.isoformat(),
            'time': '',
            'assigned_member': str(self.child.pk),
            'school_item': SchoolItemKind.TEST.value,
            'submission_key': str(uuid.uuid4()),
        }
        data.update(overrides)
        return EntryReviewForm(self.parent, data)

    def test_member_choices_are_active_members_of_own_family(self):
        form = EntryReviewForm(self.parent)

        self.assertQuerySetEqual(
            form.fields['assigned_member'].queryset,
            [self.parent, self.child, self.other_child],
        )

    def test_other_family_or_inactive_member_is_rejected(self):
        for member in (self.other_family_child, self.inactive_child):
            with self.subTest(member=member.display_name):
                form = self.bound(assigned_member=str(member.pk))
                self.assertFalse(form.is_valid())
                self.assertIn('assigned_member', form.errors)

    def test_calendar_event_requires_date(self):
        form = self.bound(date='', school_item='')

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors['date'], ['Wydarzenie musi mieć datę.'])

    def test_school_item_requires_member_while_type_matches(self):
        form = self.bound(assigned_member='')

        self.assertFalse(form.is_valid())
        self.assertIn('assigned_member', form.errors)

    def test_changed_type_drops_school_item(self):
        form = self.bound(entry_type=EntryType.NOTE.value, assigned_member='', date='')

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['school_item'], '')

    def test_errors_are_polish(self):
        form = self.bound(content='')

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors['content'], ['To pole jest wymagane.'])

    def test_date_and_time_render_in_html_input_formats(self):
        form = EntryReviewForm(
            self.parent,
            initial={'date': MONDAY, 'time': datetime.time(8, 30)},
        )

        html = str(form['date']) + str(form['time'])
        self.assertIn('value="2026-09-21"', html)
        self.assertIn('value="08:30"', html)
        self.assertIn('type="date"', html)
        self.assertIn('type="time"', html)

    def test_iso_date_and_time_are_accepted_under_polish_locale(self):
        form = self.bound(time='08:30')

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['date'], MONDAY)
        self.assertEqual(form.cleaned_data['time'], datetime.time(8, 30))


class ReviewFormFromClassificationTests(FamilyFixtureMixin, TestCase):
    def test_proposal_prefills_values_and_member_from_resolved_membership(self):
        outcome = ParentClassification(
            result=ClassificationProposal(
                entry_type=EntryType.CALENDAR_EVENT,
                content='Sprawdzian',
                date=MONDAY,
                school_item=SchoolItemKind.TEST,
                member_name='michał',
            ),
            member=self.child,
        )

        form, missing = review_form_from_classification(self.parent, outcome, 'tekst')

        self.assertEqual(missing, [])
        self.assertEqual(form.initial['assigned_member'], self.child.pk)
        self.assertEqual(form.initial['date'], MONDAY)
        self.assertEqual(form.initial['school_item'], 'test')
        self.assertIsInstance(form.initial['submission_key'], uuid.UUID)

    def test_follow_up_marks_missing_fields(self):
        outcome = ParentClassification(
            result=ClassificationFollowUp(
                missing_fields=(MissingField.DATE, MissingField.AMBIGUOUS_MEMBER),
                entry_type=EntryType.CALENDAR_EVENT,
                content='Sprawdzian',
            )
        )

        form, missing = review_form_from_classification(self.parent, outcome, 'tekst')

        self.assertEqual(missing, ['date', 'assigned_member'])
        self.assertIn('aria-invalid="true"', str(form['date']))
        self.assertIn('Wybierz osobę.', [row['hint'] for row in form.rows()])

    def test_unavailable_falls_back_to_note_with_text(self):
        outcome = ParentClassification(
            result=ClassificationUnavailable(reason=UnavailableReason.TIMEOUT)
        )

        form, missing = review_form_from_classification(self.parent, outcome, 'Kupić zeszyt')

        self.assertEqual(missing, [])
        self.assertEqual(form.initial['entry_type'], 'note')
        self.assertEqual(form.initial['content'], 'Kupić zeszyt')


class CaptureFormTests(TestCase):
    def test_text_is_required_stripped_and_bounded(self):
        self.assertFalse(CaptureForm({'text': '   '}).is_valid())
        self.assertFalse(CaptureForm({'text': 'x' * 2001}).is_valid())
        form = CaptureForm({'text': '  Michał ma sprawdzian  '})
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data['text'], 'Michał ma sprawdzian')
