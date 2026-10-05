"""End-to-end tests for the free-text correction step of the capture review.

A scripted fake backend replaces the configured provider, so the real views,
forms and correction service run: capture -> review -> correct -> confirm.
"""

import datetime
import logging
import uuid
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from entries.classification.backends import BackendOutput, ClassificationBackendError
from entries.classification.service import MAX_CORRECTION_LENGTH
from entries.classification.types import EntryType, SchoolItemKind, UnavailableReason
from entries.forms import EntryReviewForm, ProposalCorrectionForm
from entries.models import Entry

from .test_capture_views import RecordingHandler
from .test_classification_service import REFERENCE_DATE, WRITE_PREFIXES, FamilyFixtureMixin
from .classification_progress_markup import (
    assert_progress_regions,
    classification_submitters,
    progress_forms,
)
from .enter_submit_markup import assert_enter_assets, assert_enter_never_saves
from .test_follow_up_views import ScriptedBackend, as_post_data

CAPTURE_URL = reverse('entries:capture')
CORRECT_URL = reverse('entries:correct')
CONFIRM_URL = reverse('entries:confirm')

MONDAY = datetime.date(2026, 9, 21)
FRIDAY = datetime.date(2026, 9, 18)
INSTRUCTION = 'Michał ma sprawdzian z matematyki w poniedziałek o 8'
CONTENT = 'Sprawdzian z matematyki'
CORRECTION = 'zmień datę na piątek'
CORRECTION_SENTINEL = 'SENTINEL-POPRAWKA-3f9a w piątek'
UNAPPLIED_ERROR = 'Masz niezastosowaną poprawkę — naciśnij „Popraw” albo wyczyść pole.'
FAILED_NOTICE = 'Nie udało się zastosować poprawki. Napisz ją inaczej albo popraw pola ręcznie.'


def first_output(**overrides):
    values = dict(
        entry_type=EntryType.CALENDAR_EVENT,
        content=CONTENT,
        grounded=True,
        date=MONDAY,
        time=datetime.time(8, 0),
        school_item=SchoolItemKind.TEST,
        member_name='Michał',
        school_subject='matematyka',
    )
    values.update(overrides)
    return BackendOutput(**values)


def correction_output(changed, **overrides):
    return first_output(changed_fields=frozenset(changed), **overrides)


class CorrectionViewMixin(FamilyFixtureMixin):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.parent.user)
        self.backend = ScriptedBackend()

    def run_with_backend(self, url, data, *script):
        self.backend.script.extend(script)
        with mock.patch(
            'entries.views.timezone.localdate', return_value=REFERENCE_DATE
        ), mock.patch(
            'entries.classification.openai_backend.build_openai_backend',
            return_value=self.backend,
        ):
            return self.client.post(url, data)

    def review_data(self):
        """Capture the instruction and return the review form's posted values."""
        response = self.run_with_backend(CAPTURE_URL, {'text': INSTRUCTION}, first_output())
        self.assertEqual(response.context['state'], 'proposal')
        return as_post_data(response.context['review_form'])

    def posted_data(self, **overrides):
        data = {
            'entry_type': EntryType.CALENDAR_EVENT.value,
            'content': CONTENT,
            'date': MONDAY.isoformat(),
            'time': '08:00',
            'assigned_member': str(self.child.pk),
            'school_item': SchoolItemKind.TEST.value,
            'school_subject': 'matematyka',
            'submission_key': str(uuid.uuid4()),
            'correction': CORRECTION,
        }
        data.update(overrides)
        return data

    def correct(self, data, *script):
        return self.run_with_backend(CORRECT_URL, data, *script)


class CorrectionFlowTests(CorrectionViewMixin, TestCase):
    def test_capture_correct_confirm_saves_one_entry_with_the_corrected_date(self):
        data = self.review_data()

        corrected = self.correct(
            {**data, 'correction': CORRECTION}, correction_output({'date'}, date=FRIDAY)
        )

        self.assertEqual(corrected.context['state'], 'proposal')
        self.assertContains(corrected, 'Zaktualizowano: data.')
        form = corrected.context['review_form']
        self.assertEqual(form.initial['date'], FRIDAY)
        self.assertEqual(form.initial['content'], CONTENT)
        self.assertEqual(form.initial['time'], datetime.time(8, 0))
        self.assertEqual(form.initial['assigned_member'], self.child.pk)
        self.assertEqual(form.initial['school_subject'], 'matematyka')
        self.assertNotIn('correction', form.initial)
        self.assertNotEqual(str(form.initial['submission_key']), data['submission_key'])
        self.assertEqual(len(self.backend.requests), 2)
        self.assertFalse(Entry.objects.exists())

        confirmed = self.client.post(CONFIRM_URL, as_post_data(form))

        entry = Entry.objects.get()
        self.assertRedirects(confirmed, f'{CAPTURE_URL}?saved={entry.pk}')
        self.assertEqual(entry.date, FRIDAY)
        self.assertEqual(entry.content, CONTENT)
        self.assertEqual(entry.time, datetime.time(8, 0))
        self.assertEqual(entry.assigned_member, self.child)
        self.assertEqual(entry.school_item, SchoolItemKind.TEST.value)
        self.assertEqual(entry.school_subject, 'matematyka')

    def test_manual_edits_survive_a_correction_of_another_field(self):
        data = self.posted_data(time='09:15', content='Sprawdzian z algebry')

        response = self.correct(data, correction_output({'date'}, date=FRIDAY))

        (request,) = self.backend.requests
        self.assertEqual(request.current_proposal.time, datetime.time(9, 15))
        self.assertEqual(request.current_proposal.content, 'Sprawdzian z algebry')
        self.assertNotIn(INSTRUCTION, repr(vars(request)))
        form = response.context['review_form']
        self.assertEqual(form.initial['time'], datetime.time(9, 15))
        self.assertEqual(form.initial['content'], 'Sprawdzian z algebry')
        self.assertEqual(form.initial['date'], FRIDAY)

    def test_repeated_corrections_keep_earlier_changes(self):
        first = self.correct(self.posted_data(), correction_output({'date'}, date=FRIDAY))
        data = {**as_post_data(first.context['review_form']), 'correction': 'o 10'}

        second = self.correct(
            data, correction_output({'time'}, date=MONDAY, time=datetime.time(10, 0))
        )

        form = second.context['review_form']
        self.assertEqual(form.initial['date'], FRIDAY)
        self.assertEqual(form.initial['time'], datetime.time(10, 0))
        self.assertContains(second, 'Zaktualizowano: godzina.')
        self.assertEqual(len(self.backend.requests), 2)

    def test_general_note_is_corrected_into_a_dated_todo(self):
        data = self.posted_data(
            entry_type=EntryType.NOTE.value,
            content='Kupić prezent dla babci',
            date='',
            time='',
            assigned_member='',
            school_item='',
            school_subject='',
            correction='to jest zadanie na jutro',
        )
        output = BackendOutput(
            entry_type=EntryType.TODO,
            content='Zadanie na jutro',
            grounded=True,
            date=FRIDAY,
            changed_fields=frozenset({'entry_type', 'date'}),
        )

        response = self.correct(data, output)

        self.assertEqual(response.context['state'], 'proposal')
        form = response.context['review_form']
        self.assertEqual(form.initial['entry_type'], EntryType.TODO.value)
        self.assertEqual(form.initial['content'], 'Kupić prezent dla babci')
        self.assertEqual(form.initial['date'], FRIDAY)
        self.assertContains(response, 'Zaktualizowano: rodzaj, data.')

    def test_correction_leaving_the_date_missing_highlights_it(self):
        response = self.correct(
            self.posted_data(correction='usuń datę'), correction_output({'date'}, date=None)
        )

        self.assertEqual(response.context['state'], 'follow_up')
        form = response.context['review_form']
        self.assertIn('date', form.missing)
        self.assertContains(response, 'Podaj datę.')

    def test_subject_correction_fills_the_highlighted_subject(self):
        data = self.posted_data(school_subject='', correction='przedmiot to fizyka')

        response = self.correct(data, correction_output({'school_subject'}, school_subject='fizyka'))

        self.assertEqual(response.context['state'], 'proposal')
        self.assertEqual(response.context['review_form'].initial['school_subject'], 'fizyka')
        self.assertContains(response, 'Zaktualizowano: przedmiot.')


class NotAppliedTests(CorrectionViewMixin, TestCase):
    def assert_kept(self, response, data, notice):
        self.assertEqual(response.context['state'], 'correction_failed')
        form = response.context['review_form']
        for name in ('content', 'date', 'time', 'assigned_member', 'school_item', 'correction'):
            self.assertEqual(str(form[name].value()), data[name])
        self.assertNotEqual(form['submission_key'].value(), data['submission_key'])
        self.assertContains(response, data['correction'])
        if notice:
            self.assertContains(response, notice)
        self.assertFalse(Entry.objects.exists())

    def test_unclear_or_failed_correction_keeps_the_posted_values(self):
        cases = {
            'nothing changed': correction_output(set()),
            'ungrounded': correction_output({'date'}, date=FRIDAY, grounded=False),
            'provider failure': ClassificationBackendError(UnavailableReason.TIMEOUT),
        }
        for name, script in cases.items():
            with self.subTest(name):
                data = self.posted_data(time='09:15', correction='bla bla')

                response = self.correct(data, script)

                self.assert_kept(response, data, FAILED_NOTICE)

    def test_school_type_mismatch_names_the_required_type(self):
        data = self.posted_data(correction='to zadanie, nie wydarzenie')

        response = self.correct(
            data, correction_output({'entry_type'}, entry_type=EntryType.TODO)
        )

        self.assert_kept(
            response,
            data,
            'Ten element szkolny wymaga rodzaju „Wydarzenie”. Poprawka nie została zastosowana.',
        )

    def test_overlong_title_puts_the_error_on_the_correction(self):
        data = self.posted_data()
        with mock.patch('entries.views.correct_proposal_for_parent') as correct:
            from entries.classification.service import CorrectionRejection, ProposalCorrection

            correct.return_value = ProposalCorrection(
                outcome=None, rejection=CorrectionRejection.TOO_LONG
            )
            response = self.client.post(CORRECT_URL, data)

        self.assertEqual(response.context['state'], 'correction_failed')
        self.assertEqual(
            response.context['review_form'].errors['correction'], ['Poprawka jest za długa.']
        )


class FormValidationTests(CorrectionViewMixin, TestCase):
    def assert_form_error(self, data, field, message):
        response = self.correct(data)

        self.assertEqual(response.context['state'], 'invalid')
        self.assertEqual(response.context['review_form'].errors[field], [message])
        self.assertEqual(self.backend.requests, [])
        self.assertFalse(Entry.objects.exists())

    def test_empty_correction_is_a_field_error_without_backend_call(self):
        for blank in ('', '   '):
            with self.subTest(blank=blank):
                self.assert_form_error(
                    self.posted_data(correction=blank), 'correction', 'Wpisz, co zmienić.'
                )

    def test_too_long_correction_is_a_field_error_without_backend_call(self):
        self.assert_form_error(
            self.posted_data(correction='x' * (MAX_CORRECTION_LENGTH + 1)),
            'correction',
            'Poprawka jest za długa.',
        )

    def test_foreign_or_inactive_member_is_a_form_error_without_backend_call(self):
        for member in (self.other_family_child, self.inactive_child):
            with self.subTest(member.display_name):
                response = self.correct(self.posted_data(assigned_member=str(member.pk)))

                self.assertEqual(response.context['state'], 'invalid')
                self.assertIn('assigned_member', response.context['review_form'].errors)
                self.assertEqual(self.backend.requests, [])

    def test_school_type_mismatch_in_the_posted_form_is_an_error(self):
        response = self.correct(self.posted_data(entry_type=EntryType.NOTE.value))

        self.assertIn('school_item', response.context['review_form'].errors)
        self.assertEqual(self.backend.requests, [])

    def test_missing_schedule_values_do_not_block_a_correction(self):
        response = self.correct(
            self.posted_data(date='', school_subject='', correction='w piątek z fizyki'),
            correction_output({'date', 'school_subject'}, date=FRIDAY, school_subject='fizyka'),
        )

        self.assertEqual(response.context['state'], 'proposal')
        self.assertEqual(len(self.backend.requests), 1)


class ConfirmRefusesUnappliedCorrectionTests(CorrectionViewMixin, TestCase):
    def test_save_with_a_typed_correction_saves_nothing(self):
        data = self.posted_data()

        response = self.client.post(CONFIRM_URL, data)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['state'], 'invalid')
        form = response.context['review_form']
        self.assertEqual(form.errors['correction'], [UNAPPLIED_ERROR])
        self.assertNotEqual(form['submission_key'].value(), data['submission_key'])
        self.assertContains(response, UNAPPLIED_ERROR)
        self.assertFalse(Entry.objects.exists())

    def test_blank_correction_box_saves_normally(self):
        response = self.client.post(CONFIRM_URL, self.posted_data(correction='  '))

        entry = Entry.objects.get()
        self.assertRedirects(response, f'{CAPTURE_URL}?saved={entry.pk}')


class AccessAndPrivacyTests(CorrectionViewMixin, TestCase):
    def test_anonymous_is_redirected_to_login(self):
        self.client.logout()

        response = self.correct(self.posted_data())

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('account_login'), response['Location'])
        self.assertEqual(self.backend.requests, [])

    def test_non_parents_get_403(self):
        unconfigured = get_user_model().objects.create_user(username='unconfigured')
        for user in (self.child.user, self.inactive_child.user, unconfigured):
            with self.subTest(user.username):
                self.client.force_login(user)

                response = self.correct(self.posted_data())

                self.assertEqual(response.status_code, 403)
                self.assertEqual(self.backend.requests, [])

    def test_other_family_parent_cannot_use_our_member(self):
        self.client.force_login(self.other_family_parent.user)

        response = self.correct(self.posted_data())

        self.assertEqual(response.context['state'], 'invalid')
        self.assertIn('assigned_member', response.context['review_form'].errors)
        self.assertEqual(self.backend.requests, [])

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get(CORRECT_URL).status_code, 405)

    def test_nothing_is_written_before_confirm(self):
        cases = {
            'applied': correction_output({'date'}, date=FRIDAY),
            'not applied': correction_output(set()),
        }
        for name, script in cases.items():
            with self.subTest(name):
                with CaptureQueriesContext(connection) as queries:
                    self.correct(self.posted_data(), script)

                writes = [
                    query['sql']
                    for query in queries.captured_queries
                    if query['sql'].lstrip().upper().startswith(WRITE_PREFIXES)
                    and 'django_session' not in query['sql']
                ]
                self.assertEqual(writes, [])
                self.assertFalse(Entry.objects.exists())

    def test_correction_text_never_reaches_logs(self):
        handler = RecordingHandler()
        root = logging.getLogger()
        previous_level = root.level
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)
        try:
            for script in (
                correction_output({'date'}, date=FRIDAY),
                correction_output(set()),
                ClassificationBackendError(UnavailableReason.PROVIDER_ERROR),
            ):
                self.correct(self.posted_data(correction=CORRECTION_SENTINEL), script)
            self.client.post(CONFIRM_URL, self.posted_data(correction=CORRECTION_SENTINEL))
        finally:
            root.removeHandler(handler)
            root.setLevel(previous_level)

        for message in handler.messages:
            self.assertNotIn('SENTINEL-POPRAWKA', message)
        self.assertFalse(Entry.objects.exists())


class MarkupTests(CorrectionViewMixin, TestCase):
    def test_review_partial_offers_the_correction_with_stable_markup(self):
        data = self.review_data()
        response = self.correct({**data, 'correction': 'bla'}, correction_output(set()))

        for page in (self.run_with_backend(CAPTURE_URL, {'text': INSTRUCTION}, first_output()), response):
            with self.subTest(state=page.context['state']):
                self.assertContains(page, 'Popraw opis')
                self.assertContains(page, 'placeholder="np. zmień datę na 15 października"')
                self.assertContains(
                    page,
                    f'<button type="submit" name="action" value="correct" id="correct-submit" '
                    f'class="secondary" formaction="{CORRECT_URL}" formnovalidate '
                    f'data-classification-submit>Popraw</button>',
                    html=True,
                )
                self.assertContains(page, 'data-enter-submitter="correct-submit"')
                content = page.content.decode()
                # „Zapisz wpis” stays the default (first) submit.
                self.assertLess(content.index('Zapisz wpis'), content.index('id="correct-submit"'))
                self.assertNotIn('required id="id_correction"', content)

    def test_prefixed_forms_get_unique_submitter_ids(self):
        for form_class in (EntryReviewForm, ProposalCorrectionForm):
            with self.subTest(form_class.__name__):
                form = form_class(self.parent, prefix='p2')

                self.assertEqual(form.correct_submit_id, 'p2-correct-submit')
                self.assertEqual(
                    form.fields['correction'].widget.attrs['data-enter-submitter'],
                    'p2-correct-submit',
                )
                self.assertNotIn('required', str(form['correction']))


class EnterSubmitReviewTests(CorrectionViewMixin, TestCase):
    """S-05: Enter in „Popraw opis” runs „Popraw” and can never post to confirm."""

    def review_pages(self):
        proposal = self.run_with_backend(CAPTURE_URL, {'text': INSTRUCTION}, first_output())
        highlighted = self.correct(
            self.posted_data(correction='usuń datę'), correction_output({'date'}, date=None)
        )
        failed = self.correct(
            self.posted_data(correction='bla bla'),
            ClassificationBackendError(UnavailableReason.TIMEOUT),
        )
        invalid = self.client.post(CONFIRM_URL, self.posted_data())
        return {
            'proposal': proposal,
            'follow_up_highlight': highlighted,
            'correction_failed': failed,
            'invalid': invalid,
        }

    def test_enter_in_the_correction_box_never_posts_to_confirm(self):
        for name, page in self.review_pages().items():
            with self.subTest(page=name):
                self.assertEqual(page.context['state'], name.replace('_highlight', ''))
                checked = assert_enter_never_saves(self, page.content.decode())
                self.assertEqual(checked, 1)

    def test_correction_box_is_opted_in_and_the_title_box_is_not(self):
        page = self.run_with_backend(CAPTURE_URL, {'text': INSTRUCTION}, first_output())
        form = page.context['review_form']

        correction = str(form['correction'])
        self.assertIn('data-enter-submit=""', correction)
        self.assertIn('enterkeyhint="send"', correction)
        self.assertIn('data-enter-submitter="correct-submit"', correction)
        content = str(form['content'])
        self.assertNotIn('data-enter-submit', content)
        self.assertNotIn('enterkeyhint', content)
        assert_enter_assets(self, page, ['id_correction'])


class ProgressIndicatorReviewTests(CorrectionViewMixin, TestCase):
    """S-06: „Popraw” calls the provider and shows the indicator; saving does not."""

    def review_pages(self):
        return {
            'proposal': self.run_with_backend(CAPTURE_URL, {'text': INSTRUCTION}, first_output()),
            'correction_failed': self.correct(
                self.posted_data(correction='bla bla'),
                ClassificationBackendError(UnavailableReason.TIMEOUT),
            ),
            'invalid': self.client.post(CONFIRM_URL, self.posted_data()),
        }

    def test_review_form_marks_only_popraw_as_a_classification_submit(self):
        for name, page in self.review_pages().items():
            with self.subTest(state=name):
                self.assertEqual(page.context['state'], name)
                content = page.content.decode()
                self.assertEqual(assert_progress_regions(self, content), 1)
                [form] = progress_forms(content)
                self.assertEqual(form['attrs']['action'], CONFIRM_URL)
                # The default (no-submitter) action saves, so it never classifies.
                self.assertNotIn('data-classification-default', form['attrs'])
                self.assertEqual(form['attrs'].get('data-progress-slow-after'), '10')
                self.assertEqual(form['attrs'].get('data-progress-stalled-after'), '35')
                buttons = {button['text'].strip(): button['attrs'] for button in form['buttons']}
                self.assertEqual(set(buttons), {'Zapisz wpis', 'Popraw'})
                self.assertNotIn('data-classification-submit', buttons['Zapisz wpis'])
                self.assertIn('data-classification-submit', buttons['Popraw'])
                self.assertEqual(buttons['Popraw'].get('formaction'), CORRECT_URL)
                self.assertEqual(classification_submitters(form), ['Popraw'])
