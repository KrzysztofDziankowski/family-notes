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
from entries.forms import (
    CaptureForm,
    EntryCreateForm,
    EntryEditForm,
    EntryReviewForm,
    review_form_from_classification,
)
from entries.models import Entry

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


class ManagedEntryFormTests(FamilyFixtureMixin, TestCase):
    """Structured create and edit share one strict validation contract."""

    form_classes = (EntryCreateForm, EntryEditForm)

    def data(self, **overrides):
        values = {
            'entry_type': EntryType.CALENDAR_EVENT.value,
            'content': 'Sprawdzian z biologii o skórze',
            'date': MONDAY.isoformat(),
            'time': '08:30',
            'assigned_member': str(self.child.pk),
            'school_item': SchoolItemKind.TEST.value,
            'submission_key': str(uuid.uuid4()),
        }
        values.update(overrides)
        return values

    def each_form(self, **overrides):
        for form_class in self.form_classes:
            with self.subTest(form=form_class.__name__):
                yield form_class(self.parent, self.data(**overrides))

    def test_valid_data_is_accepted_by_both_forms(self):
        for form in self.each_form():
            self.assertTrue(form.is_valid(), form.errors)
            self.assertEqual(form.cleaned_data['school_item'], 'test')
            self.assertEqual(form.cleaned_data['assigned_member'], self.child)
            self.assertEqual(form.cleaned_data['time'], datetime.time(8, 30))

    def test_visible_fields_and_polish_labels(self):
        expected = {
            'entry_type': 'Rodzaj',
            'content': 'Tytuł',
            'date': 'Data',
            'time': 'Godzina',
            'assigned_member': 'Dla kogo',
            'school_subject': 'Przedmiot',
            'school_item': 'Element szkolny',
        }
        for form_class in self.form_classes:
            with self.subTest(form=form_class.__name__):
                form = form_class(self.parent)
                visible = {field.name: field.label for field in form.visible_fields()}
                self.assertEqual(visible, expected)
                html = form.as_div()
                self.assertIn('Brak', html)
                self.assertIn('sprawdzian', html)
                self.assertIn('Cała rodzina', html)

    def test_create_has_hidden_submission_key_and_edit_does_not(self):
        create = EntryCreateForm(self.parent)
        edit = EntryEditForm(self.parent)

        self.assertEqual([f.name for f in create.hidden_fields()], ['submission_key'])
        key = uuid.UUID(str(create['submission_key'].value()))
        self.assertNotEqual(key, uuid.UUID(str(EntryCreateForm(self.parent)['submission_key'].value())))
        self.assertIn(f'type="hidden" name="submission_key" value="{key}"', create.as_div())
        self.assertNotIn('submission_key', edit.fields)
        self.assertEqual(edit.hidden_fields(), [])

    def test_create_requires_valid_submission_key(self):
        for key in ('', 'not-a-uuid'):
            with self.subTest(key=key):
                form = EntryCreateForm(self.parent, self.data(submission_key=key))
                self.assertFalse(form.is_valid())
                self.assertIn('submission_key', form.errors)

    def test_school_item_type_mismatch_is_a_polish_error(self):
        for form in self.each_form(entry_type=EntryType.NOTE.value, assigned_member='', date=''):
            self.assertFalse(form.is_valid())
            self.assertEqual(
                form.errors['school_item'], ['Ten element szkolny wymaga rodzaju „Wydarzenie”.']
            )

    def test_note_school_item_on_calendar_event_is_rejected(self):
        for form in self.each_form(school_item=SchoolItemKind.GRADE.value):
            self.assertFalse(form.is_valid())
            self.assertEqual(
                form.errors['school_item'], ['Ten element szkolny wymaga rodzaju „Notatka”.']
            )

    def test_member_choices_are_active_members_of_own_family(self):
        for form_class in self.form_classes:
            with self.subTest(form=form_class.__name__):
                form = form_class(self.parent)
                self.assertQuerySetEqual(
                    form.fields['assigned_member'].queryset,
                    [self.parent, self.child, self.other_child],
                )

    def test_other_family_or_inactive_member_is_rejected(self):
        for member in (self.other_family_child, self.inactive_child):
            for form in self.each_form(assigned_member=str(member.pk)):
                self.assertFalse(form.is_valid())
                self.assertIn('assigned_member', form.errors)

    def test_edit_keeps_current_inactive_assignee_selectable(self):
        entry = Entry.objects.create(
            family=self.family,
            entry_type=EntryType.TODO.value,
            content='Oddać książkę',
            assigned_member=self.inactive_child,
        )

        form = EntryEditForm(self.parent, entry=entry)
        html = str(form['assigned_member'])
        self.assertIn(f'<option value="{self.inactive_child.pk}" selected>', html)
        self.assertIn('(nieaktywne konto)', html)

        bound = EntryEditForm(
            self.parent,
            self.data(entry_type=EntryType.TODO.value, school_item='', date='', time='',
                      assigned_member=str(self.inactive_child.pk)),
            entry=entry,
        )
        self.assertTrue(bound.is_valid(), bound.errors)
        self.assertEqual(bound.cleaned_data['assigned_member'], self.inactive_child)

    def test_content_is_required_stripped_and_bounded(self):
        for form in self.each_form(content='   '):
            self.assertFalse(form.is_valid())
            self.assertEqual(form.errors['content'], ['To pole jest wymagane.'])
        for form in self.each_form(content='x' * 2001):
            self.assertFalse(form.is_valid())
            self.assertIn('content', form.errors)
        for form in self.each_form(content='  Sprawdzian  '):
            self.assertTrue(form.is_valid(), form.errors)
            self.assertEqual(form.cleaned_data['content'], 'Sprawdzian')

    def test_calendar_event_requires_date(self):
        for form in self.each_form(date='', school_item=''):
            self.assertFalse(form.is_valid())
            self.assertEqual(form.errors['date'], ['Wydarzenie musi mieć datę.'])

    def test_school_item_requires_its_date_and_member(self):
        for form in self.each_form(assigned_member=''):
            self.assertFalse(form.is_valid())
            self.assertEqual(
                form.errors['assigned_member'], ['Wybierz osobę, której dotyczy wpis.']
            )
        for form in self.each_form(
            entry_type=EntryType.NOTE.value,
            school_item=SchoolItemKind.SUBSTITUTION.value,
            date='',
        ):
            self.assertFalse(form.is_valid())
            self.assertEqual(form.errors['date'], ['Podaj datę.'])

    def test_undated_note_without_school_item_is_valid(self):
        for form in self.each_form(
            entry_type=EntryType.NOTE.value, date='', time='', assigned_member='', school_item=''
        ):
            self.assertTrue(form.is_valid(), form.errors)
            self.assertIsNone(form.cleaned_data['assigned_member'])

    def test_unknown_choices_are_rejected_in_polish(self):
        for form in self.each_form(entry_type='meeting', school_item='exam'):
            self.assertFalse(form.is_valid())
            self.assertIn('Wybierz poprawną wartość', form.errors['entry_type'][0])
            self.assertIn('Wybierz poprawną wartość', form.errors['school_item'][0])

    def test_edit_form_is_prefilled_from_entry(self):
        entry = Entry.objects.create(
            family=self.family,
            entry_type=EntryType.CALENDAR_EVENT.value,
            content='Kartkówka z matematyki',
            date=MONDAY,
            time=datetime.time(9, 15),
            assigned_member=self.child,
            school_item=SchoolItemKind.QUIZ.value,
            source=Entry.Source.EDUVULCAN,
        )

        form = EntryEditForm(self.parent, entry=entry)

        html = form.as_div()
        self.assertIn('Kartkówka z matematyki', html)
        self.assertIn('value="2026-09-21"', html)
        self.assertIn('value="09:15"', html)
        self.assertIn(f'value="{self.child.pk}" selected', html)
        self.assertIn('value="quiz" selected', html)
        self.assertNotIn('eduvulcan', html.lower())


class ReviewFormKeepsSilentClearingTests(FamilyFixtureMixin, TestCase):
    def test_hidden_school_item_is_cleared_not_rejected(self):
        form = EntryReviewForm(
            self.parent,
            {
                'entry_type': EntryType.NOTE.value,
                'content': 'Notatka',
                'date': '',
                'time': '',
                'assigned_member': '',
                'school_item': SchoolItemKind.TEST.value,
                'submission_key': str(uuid.uuid4()),
            },
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['school_item'], '')
        self.assertNotIn('school_item', form.errors)
        self.assertEqual([f.name for f in form.visible_fields()],
                         ['entry_type', 'content', 'date', 'time', 'assigned_member',
                          'school_subject'])
