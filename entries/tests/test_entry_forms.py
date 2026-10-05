import datetime
import uuid

from django.template.loader import render_to_string
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
    BatchEntryCorrectionForm,
    BatchEntryForm,
    CaptureForm,
    EntryCreateForm,
    EntryEditForm,
    EntryReviewForm,
    FollowUpAnswerForm,
    ProposalCorrectionForm,
    describe_fields,
    review_form_from_classification,
)
from entries.models import Entry

from .field_association_markup import assert_described_by
from .test_classification_service import FamilyFixtureMixin, TwoParentFixtureMixin

MONDAY = datetime.date(2026, 9, 21)
SCHOOL_EVENT_KINDS = (
    SchoolItemKind.HOMEWORK,
    SchoolItemKind.CLASS_TEST,
    SchoolItemKind.TEST,
    SchoolItemKind.QUIZ,
)


class EntryReviewFormTests(FamilyFixtureMixin, TestCase):
    def bound(self, **overrides):
        data = {
            'entry_type': EntryType.CALENDAR_EVENT.value,
            'content': 'Sprawdzian z biologii o skórze',
            'date': MONDAY.isoformat(),
            'time': '',
            'assigned_member': str(self.child.pk),
            'school_item': SchoolItemKind.TEST.value,
            'school_subject': 'biologia',
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

    def test_changed_type_with_stale_school_item_is_an_error(self):
        form = self.bound(entry_type=EntryType.NOTE.value, assigned_member='', date='')

        self.assertFalse(form.is_valid())
        self.assertEqual(
            form.errors['school_item'], ['Ten element szkolny wymaga rodzaju „Wydarzenie”.']
        )

    def test_changed_type_with_cleared_school_item_is_valid(self):
        form = self.bound(
            entry_type=EntryType.NOTE.value,
            assigned_member='',
            date='',
            school_item='',
            school_subject='',
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['school_item'], '')

    def test_school_event_kinds_require_a_subject(self):
        for kind in SCHOOL_EVENT_KINDS:
            with self.subTest(kind=kind.value):
                form = self.bound(school_item=kind.value, school_subject='   ')

                self.assertFalse(form.is_valid())
                self.assertEqual(form.errors['school_subject'], ['Podaj przedmiot.'])

    def test_subject_is_optional_for_other_entries(self):
        form = self.bound(school_item='', school_subject='')

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['school_subject'], '')

    def test_subject_is_stripped_and_bounded(self):
        form = self.bound(school_subject='  Matematyka ')
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['school_subject'], 'Matematyka')

        too_long = self.bound(school_subject='x' * 101)
        self.assertFalse(too_long.is_valid())
        self.assertIn('school_subject', too_long.errors)

    def test_school_item_and_subject_are_visible_rows(self):
        form = EntryReviewForm(self.parent)

        self.assertEqual(
            [row['field'].name for row in form.rows()],
            [
                'entry_type', 'content', 'school_item', 'school_subject',
                'date', 'time', 'assigned_member',
            ],
        )
        self.assertEqual(form['school_item'].label, 'Element szkolny')
        self.assertEqual(form['school_subject'].label, 'Przedmiot')
        self.assertIn('Brak', str(form['school_item']))
        self.assertEqual([f.name for f in form.hidden_fields()], ['submission_key'])

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
            'school_subject': 'biologia',
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


class ReviewFormStrictSchoolItemTests(FamilyFixtureMixin, TestCase):
    def test_visible_school_item_mismatch_is_rejected_not_cleared(self):
        form = EntryReviewForm(
            self.parent,
            {
                'entry_type': EntryType.NOTE.value,
                'content': 'Notatka',
                'date': '',
                'time': '',
                'assigned_member': '',
                'school_item': SchoolItemKind.TEST.value,
                'school_subject': '',
                'submission_key': str(uuid.uuid4()),
            },
        )

        self.assertFalse(form.is_valid())
        self.assertEqual(
            form.errors['school_item'], ['Ten element szkolny wymaga rodzaju „Wydarzenie”.']
        )
        self.assertNotIn('school_subject', form.errors)
        self.assertEqual(
            {f.name for f in form.visible_fields()},
            {
                'entry_type', 'content', 'date', 'time', 'assigned_member',
                'school_item', 'school_subject', 'correction',
            },
        )


class SubjectOnEditTests(FamilyFixtureMixin, TestCase):
    def entry(self, **fields):
        values = dict(
            family=self.family,
            entry_type=EntryType.CALENDAR_EVENT.value,
            content='Sprawdzian: Biologia',
            date=MONDAY,
            assigned_member=self.child,
            school_item=SchoolItemKind.TEST.value,
            source=Entry.Source.EDUVULCAN,
        )
        values.update(fields)
        return Entry.objects.create(**values)

    def edit(self, entry, **overrides):
        data = {
            'entry_type': entry.entry_type,
            'content': entry.content,
            'date': entry.date.isoformat() if entry.date else '',
            'time': '',
            'assigned_member': str(entry.assigned_member_id or ''),
            'school_item': entry.school_item,
            'school_subject': entry.school_subject,
        }
        data.update(overrides)
        return EntryEditForm(self.parent, data, entry=entry)

    def test_prefills_the_stored_subject(self):
        entry = self.entry(school_subject='Biologia')

        form = EntryEditForm(self.parent, entry=entry)

        self.assertEqual(form['school_subject'].value(), 'Biologia')

    def test_unrelated_edit_of_subjectless_school_event_is_valid(self):
        entry = self.entry()
        cases = {
            'reassign': {'assigned_member': str(self.other_child.pk)},
            'move date': {'date': '2026-09-28'},
            'retitle': {'content': 'Sprawdzian z działu 3'},
        }
        for name, overrides in cases.items():
            with self.subTest(name):
                form = self.edit(entry, **overrides)
                self.assertTrue(form.is_valid(), form.errors)

    def test_clearing_a_stored_subject_is_an_error(self):
        entry = self.entry(school_subject='Biologia')

        form = self.edit(entry, school_subject='  ')

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors['school_subject'], ['Podaj przedmiot.'])

    def test_setting_or_changing_a_school_event_kind_requires_a_subject(self):
        plain = self.entry(school_item='', content='Wywiadówka')
        subjectless_test = self.entry()
        for entry, kind in (
            (plain, SchoolItemKind.TEST),
            (plain, SchoolItemKind.HOMEWORK),
            (subjectless_test, SchoolItemKind.QUIZ),
            (subjectless_test, SchoolItemKind.CLASS_TEST),
        ):
            with self.subTest(entry=entry.content, kind=kind.value):
                form = self.edit(entry, school_item=kind.value, school_subject='')
                self.assertFalse(form.is_valid())
                self.assertEqual(form.errors['school_subject'], ['Podaj przedmiot.'])


class EnterSubmitOptInTests(FamilyFixtureMixin, TestCase):
    """S-05: only the instruction boxes submit on Enter; „Tytuł” stays a newline."""

    def assert_opted_in(self, bound_field, submitter=None):
        html = str(bound_field)
        self.assertIn('data-enter-submit=""', html)
        self.assertIn('enterkeyhint="send"', html)
        if submitter is None:
            self.assertNotIn('data-enter-submitter', html)
        else:
            self.assertIn(f'data-enter-submitter="{submitter}"', html)

    def test_capture_and_follow_up_boxes_use_the_default_action(self):
        self.assert_opted_in(CaptureForm()['text'])
        self.assert_opted_in(FollowUpAnswerForm(self.parent)['answer'])

    def test_correction_boxes_name_their_popraw_button(self):
        cases = (
            (EntryReviewForm, None, 'correct-submit'),
            (ProposalCorrectionForm, None, 'correct-submit'),
            (BatchEntryForm, 'e3', 'e3-correct-submit'),
            (BatchEntryCorrectionForm, 'e3', 'e3-correct-submit'),
        )
        for form_class, prefix, submitter in cases:
            with self.subTest(form=form_class.__name__):
                form = form_class(self.parent, prefix=prefix)
                self.assert_opted_in(form['correction'], submitter)

    def test_title_boxes_are_not_opted_in(self):
        for form_class in (EntryReviewForm, EntryCreateForm, EntryEditForm):
            with self.subTest(form=form_class.__name__):
                html = str(form_class(self.parent)['content'])
                self.assertNotIn('data-enter-submit', html)
                self.assertNotIn('enterkeyhint', html)


class TwoParentAssigneeFormTests(TwoParentFixtureMixin, TestCase):
    """S-07: review, create and edit offer self and the other parent only."""

    def data(self, member, **overrides):
        values = {
            'entry_type': EntryType.NOTE.value,
            'content': 'Odebrać paczkę z poczty',
            'date': '',
            'time': '',
            'assigned_member': str(member.pk) if member is not None else '',
            'school_item': '',
            'school_subject': '',
            'submission_key': str(uuid.uuid4()),
        }
        values.update(overrides)
        return values

    def forms_for(self, member, **overrides):
        entry = Entry.objects.create(
            family=self.family, entry_type=EntryType.NOTE.value, content='Stary wpis'
        )
        yield EntryReviewForm(self.parent, self.data(member, **overrides))
        yield EntryCreateForm(self.parent, self.data(member, **overrides))
        yield EntryEditForm(self.parent, self.data(member, **overrides), entry=entry)

    def test_choices_include_both_parents_and_exclude_foreign_and_inactive(self):
        for form_class in (EntryReviewForm, EntryCreateForm, EntryEditForm):
            with self.subTest(form=form_class.__name__):
                queryset = form_class(self.parent).fields['assigned_member'].queryset
                self.assertQuerySetEqual(
                    queryset,
                    [self.parent, self.child, self.other_child, self.second_parent],
                )

    def test_self_and_other_parent_are_accepted_for_every_type(self):
        types = {
            EntryType.NOTE.value: {},
            EntryType.TODO.value: {},
            EntryType.CALENDAR_EVENT.value: {'date': MONDAY.isoformat()},
        }
        for member in (self.parent, self.second_parent):
            for entry_type, extra in types.items():
                for form in self.forms_for(member, entry_type=entry_type, **extra):
                    with self.subTest(
                        member=member.display_name, type=entry_type, form=type(form).__name__
                    ):
                        self.assertTrue(form.is_valid(), form.errors)
                        self.assertEqual(form.cleaned_data['assigned_member'], member)

    def test_foreign_and_inactive_parents_are_rejected_in_polish(self):
        for member in (self.other_family_parent, self.inactive_parent):
            for form in self.forms_for(member):
                with self.subTest(member=member.display_name, form=type(form).__name__):
                    self.assertFalse(form.is_valid())
                    self.assertIn(
                        'Wybierz poprawną wartość', form.errors['assigned_member'][0]
                    )

    def test_classified_parent_prefills_review_form(self):
        outcome = ParentClassification(
            result=ClassificationProposal(
                entry_type=EntryType.NOTE,
                content='Odebrać paczkę',
                member_name=self.second_parent.display_name,
            ),
            member=self.second_parent,
        )

        form, missing = review_form_from_classification(self.parent, outcome, 'tekst')

        self.assertEqual(missing, [])
        self.assertEqual(form.initial['assigned_member'], self.second_parent.pk)
        self.assertIn(
            f'<option value="{self.second_parent.pk}" selected>', str(form['assigned_member'])
        )


class DescribeFieldsTests(FamilyFixtureMixin, TestCase):
    """``describe_fields`` lists exactly the IDs ``_field.html`` renders (S-17)."""

    def review_data(self, **overrides):
        data = {
            'entry_type': EntryType.CALENDAR_EVENT.value,
            'content': 'Zebranie',
            'date': '',
            'time': '',
            'assigned_member': '',
            'school_item': '',
            'school_subject': '',
            'submission_key': str(uuid.uuid4()),
        }
        data.update(overrides)
        return data

    def render_field(self, form, name, hint=''):
        describe_fields(form)
        return render_to_string('entries/_field.html', {'field': form[name], 'hint': hint})

    def test_hint_only(self):
        form = EntryReviewForm(self.parent, missing={'date': 'Podaj datę.'})

        html = self.render_field(form, 'date', hint='Podaj datę.')

        self.assertIn('aria-invalid="true"', html)
        assert_described_by(self, html, 'id_date', ['id_date-hint'])

    def test_error_only(self):
        form = EntryCreateForm(self.parent, self.review_data(content=''))
        self.assertFalse(form.is_valid())

        html = self.render_field(form, 'content')

        self.assertIn('aria-invalid="true"', html)
        assert_described_by(self, html, 'id_content', ['id_content_error'])

    def test_missing_and_invalid_field_references_both_hint_and_error(self):
        form = EntryReviewForm(self.parent, self.review_data(), missing={'date': 'Podaj datę.'})
        self.assertFalse(form.is_valid())
        self.assertIn('date', form.errors)

        html = self.render_field(form, 'date', hint='Podaj datę.')

        self.assertIn('Podaj datę.', html)
        self.assertIn('Wydarzenie musi mieć datę.', html)
        assert_described_by(self, html, 'id_date', ['id_date-hint', 'id_date_error'])

    def test_two_errors_render_one_error_container(self):
        form = EntryCreateForm(self.parent, self.review_data(content=''))
        form.is_valid()
        form.add_error('content', 'Druga uwaga.')

        html = self.render_field(form, 'content')

        self.assertIn('To pole jest wymagane.', html)
        self.assertIn('Druga uwaga.', html)
        assert_described_by(self, html, 'id_content', ['id_content_error'])

    def test_readable_date_is_referenced_when_a_date_is_shown(self):
        form = EntryReviewForm(self.parent, initial={'date': MONDAY})

        describe_fields(form)

        self.assertIn('aria-describedby="id_date-human"', str(form['date']))

    def test_no_description_without_hint_error_or_date(self):
        form = EntryReviewForm(self.parent)

        describe_fields(form)

        self.assertNotIn('aria-describedby', str(form['date']))
        self.assertNotIn('aria-invalid', str(form['content']))

    def test_enter_fields_reference_their_enter_hint_on_valid_and_invalid_renders(self):
        valid = CaptureForm()
        describe_fields(valid)
        self.assertIn('aria-describedby="id_text-enter-hint"', str(valid['text']))

        invalid = CaptureForm({'text': ''})
        invalid.is_valid()
        describe_fields(invalid)
        self.assertIn('aria-describedby="id_text_error id_text-enter-hint"', str(invalid['text']))
