"""Batch review and all-or-nothing save on the capture page.

The batch service is mocked with ``ParentBatchClassification`` results, so
these tests pin the view, form, template and save behaviour.
"""

import datetime
import logging
import uuid
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from entries.classification.backends import BackendOutput, ClassificationBackendError
from entries.classification.service import (
    MAX_PROPOSALS_PER_INSTRUCTION,
    ParentBatchClassification,
    ParentClassification,
)
from entries.classification.types import (
    ClassificationFollowUp,
    ClassificationProposal,
    ClassificationUnavailable,
    EntryType,
    MissingField,
    SchoolItemKind,
    UnavailableReason,
)
from entries.forms import BATCH_EMPTY_SELECTION_ERROR, BATCH_STALE_ERROR
from entries.models import Entry
from entries.views import SAVE_FAILED_ERROR, TOO_MANY_ENTRIES_NOTICE

from .classification_progress_markup import (
    assert_progress_regions,
    classification_submitters,
    progress_forms,
)
from .enter_submit_markup import assert_enter_assets, assert_enter_never_saves
from .test_capture_views import RecordingHandler
from .test_classification_service import FamilyFixtureMixin, TwoParentFixtureMixin
from .test_follow_up_views import ScriptedBackend

CAPTURE_URL = reverse('entries:capture')
BATCH_URL = reverse('entries:confirm_batch')
WEDNESDAY = datetime.date(2026, 10, 7)
THURSDAY = datetime.date(2026, 10, 8)
NEXT_MONDAY = datetime.date(2026, 10, 12)
SIX_PM = datetime.time(18, 0)
MEETINGS_TEXT = 'Spotkanie z wychowawczynią dziś, jutro i w przyszłym tygodniu w poniedziałek o 18:00'
SENTINEL = 'SENTINEL-BATCH-4d1a'


def meeting(date, **overrides):
    values = dict(
        entry_type=EntryType.CALENDAR_EVENT,
        content='Spotkanie z wychowawczynią',
        date=date,
        time=SIX_PM,
    )
    values.update(overrides)
    return ClassificationProposal(**values)


def batch_of(*results, member=None):
    return ParentBatchClassification(
        items=tuple(ParentClassification(result=result, member=member) for result in results)
    )


def posted_from(batch_form, *, exclude=()):
    """The POST data a browser would send for the rendered batch form."""
    data = {'count': str(batch_form.count), 'action': 'save'}
    for index, form in enumerate(batch_form.forms):
        for name, value in form.initial.items():
            if name == 'include':
                continue
            data[f'{form.prefix}-{name}'] = '' if value is None else str(value)
        if index not in exclude:
            data[f'{form.prefix}-include'] = 'on'
    return data


class BatchViewMixin(FamilyFixtureMixin):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.parent.user)

    def capture(self, batch, text=MEETINGS_TEXT):
        with mock.patch(
            'entries.views.classify_entries_for_parent', return_value=batch
        ) as classify, mock.patch('entries.views.timezone.localdate', return_value=WEDNESDAY):
            response = self.client.post(CAPTURE_URL, {'text': text})
        self.classify_mock = classify
        return response

    def meetings_form(self):
        response = self.capture(batch_of(*(meeting(d) for d in (WEDNESDAY, THURSDAY, NEXT_MONDAY))))
        return response, response.context['batch_form']

    def entry_data(self, index, **overrides):
        values = {
            'entry_type': EntryType.CALENDAR_EVENT.value,
            'content': 'Spotkanie z wychowawczynią',
            'date': WEDNESDAY.isoformat(),
            'time': '18:00',
            'assigned_member': '',
            'school_item': '',
            'school_subject': '',
            'submission_key': str(uuid.uuid4()),
            'include': 'on',
        }
        values.update(overrides)
        return {f'e{index}-{name}': value for name, value in values.items() if value is not None}

    def batch_data(self, *entries):
        data = {'count': str(len(entries)), 'action': 'save'}
        for index, overrides in enumerate(entries):
            data.update(self.entry_data(index, **overrides))
        return data


class BatchReviewRenderTests(BatchViewMixin, TestCase):
    def test_three_proposals_render_three_ticked_fieldsets_with_dates_and_time(self):
        response, form = self.meetings_form()

        self.assertEqual(response.context['state'], 'batch')
        self.assertContains(response, 'Sprawdź wpisy (3)')
        self.assertContains(response, 'data-batch-entry=', count=3)
        self.assertContains(response, '<legend>Wpis 2</legend>', html=True)
        self.assertContains(response, 'Uwzględnij', count=3)
        self.assertContains(response, 'checked', count=3)
        self.assertContains(response, 'value="18:00"', count=3)
        for text in ('środa, 7 października 2026', 'czwartek, 8 października 2026',
                     'poniedziałek, 12 października 2026'):
            self.assertContains(response, text)
        self.assertContains(response, f'action="{BATCH_URL}"')
        self.assertContains(response, 'Zapisz wpisy')
        self.assertContains(response, 'name="count" value="3"')
        keys = {sub.initial['submission_key'] for sub in form.forms}
        self.assertEqual(len(keys), 3)
        self.assertEqual(self.classify_mock.call_args.kwargs['reference_date'], WEDNESDAY)

    def test_missing_date_is_highlighted_in_its_proposal(self):
        response = self.capture(
            batch_of(
                meeting(WEDNESDAY),
                ClassificationFollowUp(
                    missing_fields=(MissingField.DATE,),
                    entry_type=EntryType.CALENDAR_EVENT,
                    content='Spotkanie z wychowawczynią',
                    time=SIX_PM,
                ),
            )
        )

        form = response.context['batch_form']
        self.assertEqual(form.forms[0].missing, {})
        self.assertEqual(form.forms[1].missing, {'date': 'Podaj datę.'})
        self.assertContains(response, 'id="id_e1-date-hint"')

    def test_duplicate_hint_appears_for_identical_proposals(self):
        response = self.capture(batch_of(meeting(THURSDAY), meeting(WEDNESDAY), meeting(THURSDAY)))

        self.assertContains(response, 'Taki sam jak wpis 1.', count=1)
        self.assertEqual(response.context['batch_form'].duplicate_hints(), {2: 'Taki sam jak wpis 1.'})

    def test_one_item_batch_keeps_the_single_review(self):
        response = self.capture(batch_of(meeting(WEDNESDAY)))

        self.assertEqual(response.context['state'], 'proposal')
        self.assertNotIn('batch_form', response.context)

    def test_too_many_entries_renders_the_note_fallback_with_the_notice(self):
        response = self.capture(
            batch_of(ClassificationUnavailable(reason=UnavailableReason.TOO_MANY_ENTRIES))
        )

        self.assertEqual(response.context['state'], 'unavailable')
        self.assertContains(response, TOO_MANY_ENTRIES_NOTICE)
        self.assertEqual(TOO_MANY_ENTRIES_NOTICE, 'Za dużo wpisów w jednym poleceniu (maks. 10). Podziel polecenie.')
        review = response.context['review_form']
        self.assertEqual(review.initial['entry_type'], EntryType.NOTE.value)
        self.assertEqual(review.initial['content'], MEETINGS_TEXT)


class BatchSaveTests(BatchViewMixin, TestCase):
    def test_confirming_saves_every_proposal_and_lists_them(self):
        _, form = self.meetings_form()

        response = self.client.post(BATCH_URL, posted_from(form))

        entries = list(Entry.objects.order_by('pk'))
        self.assertEqual([entry.date for entry in entries], [WEDNESDAY, THURSDAY, NEXT_MONDAY])
        self.assertEqual({entry.time for entry in entries}, {SIX_PM})
        self.assertEqual({entry.source for entry in entries}, {Entry.Source.MANUAL})
        ids = ','.join(str(entry.pk) for entry in entries)
        self.assertRedirects(response, f'{CAPTURE_URL}?saved={ids}')

        saved = self.client.get(response['Location'])
        self.assertEqual(saved.context['state'], 'saved')
        self.assertContains(saved, 'Dodano wpisy (3)')
        self.assertContains(saved, 'data-saved-entry', count=3)
        self.assertContains(saved, 'poniedziałek, 12 października 2026')

    def test_unticking_one_proposal_saves_two(self):
        _, form = self.meetings_form()

        self.client.post(BATCH_URL, posted_from(form, exclude={1}))

        self.assertEqual(
            sorted(Entry.objects.values_list('date', flat=True)), [WEDNESDAY, NEXT_MONDAY]
        )

    def test_unticked_invalid_proposal_does_not_block_the_save(self):
        data = self.batch_data({}, {'date': '', 'content': '', 'include': None})

        response = self.client.post(BATCH_URL, data)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Entry.objects.count(), 1)

    def test_school_event_is_saved_with_its_subject(self):
        data = self.batch_data(
            {},
            {
                'content': 'Sprawdzian z biologii',
                'school_item': SchoolItemKind.TEST.value,
                'school_subject': 'biologia',
                'assigned_member': str(self.child.pk),
                'time': '',
            },
        )

        self.client.post(BATCH_URL, data)

        school = Entry.objects.get(school_item=SchoolItemKind.TEST.value)
        self.assertEqual(school.school_subject, 'biologia')
        self.assertEqual(school.assigned_member, self.child)
        self.assertEqual(Entry.objects.count(), 2)

    def test_replayed_post_creates_no_new_rows(self):
        _, form = self.meetings_form()
        data = posted_from(form)

        first = self.client.post(BATCH_URL, data)
        second = self.client.post(BATCH_URL, data)

        self.assertEqual(Entry.objects.count(), 3)
        self.assertEqual(first['Location'], second['Location'])


class BatchRejectionTests(BatchViewMixin, TestCase):
    def assert_rerendered(self, response, message=None):
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['state'], 'batch')
        if message is not None:
            self.assertContains(response, message)
        self.assertFalse(Entry.objects.exists())

    def test_duplicate_submission_keys_are_a_stale_form(self):
        key = str(uuid.uuid4())
        data = self.batch_data({'submission_key': key}, {'submission_key': key, 'date': THURSDAY.isoformat()})

        response = self.client.post(BATCH_URL, data)

        self.assert_rerendered(response, BATCH_STALE_ERROR)
        self.assertTrue(response.context['batch_form'].stale)

    def test_unticking_every_proposal_is_an_error(self):
        data = self.batch_data({'include': None}, {'include': None})

        response = self.client.post(BATCH_URL, data)

        self.assert_rerendered(response, BATCH_EMPTY_SELECTION_ERROR)

    def test_included_proposal_with_missing_date_saves_nothing(self):
        data = self.batch_data({}, {'date': ''})

        response = self.client.post(BATCH_URL, data)

        self.assert_rerendered(response, 'Podaj datę.')
        form = response.context['batch_form']
        self.assertEqual(form.forms[1].fields['date'].widget.attrs['aria-invalid'], 'true')
        # The parent's keys are kept for the retry.
        self.assertEqual(
            str(form.forms[0]['submission_key'].value()), data['e0-submission_key']
        )

    def test_service_rejection_of_the_second_proposal_rolls_back_the_first(self):
        foreign_key = uuid.uuid4()
        Entry.objects.create(date=datetime.date(2026, 9, 21),
            family=self.other_family,
            entry_type=EntryType.NOTE.value,
            content='SENTINEL-OBCY-WPIS',
            submission_key=foreign_key,
        )
        data = self.batch_data({}, {'submission_key': str(foreign_key)})

        response = self.client.post(BATCH_URL, data)

        self.assertEqual(response.context['state'], 'batch')
        self.assertContains(response, SAVE_FAILED_ERROR)
        self.assertNotContains(response, 'SENTINEL-OBCY-WPIS')
        self.assertEqual(Entry.objects.filter(family=self.family).count(), 0)
        form = response.context['batch_form']
        new_keys = {str(sub['submission_key'].value()) for sub in form.forms}
        self.assertNotIn(str(foreign_key), new_keys)
        self.assertNotIn(data['e0-submission_key'], new_keys)

    def test_tampered_count_is_a_stale_form(self):
        for count in ('0', str(MAX_PROPOSALS_PER_INSTRUCTION + 1), 'abc', '', None):
            with self.subTest(count=count):
                data = self.batch_data({})
                if count is None:
                    del data['count']
                else:
                    data['count'] = count

                response = self.client.post(BATCH_URL, data)

                self.assert_rerendered(response, BATCH_STALE_ERROR)
                self.assertContains(response, 'Zacznij od nowa')
                self.assertNotContains(response, 'Zapisz wpisy')

    def test_foreign_member_is_a_field_error(self):
        data = self.batch_data({}, {'assigned_member': str(self.other_family_child.pk)})

        response = self.client.post(BATCH_URL, data)

        self.assert_rerendered(response)
        self.assertIn('assigned_member', response.context['batch_form'].forms[1].errors)


class BatchAccessTests(BatchViewMixin, TestCase):
    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get(BATCH_URL).status_code, 405)

    def test_anonymous_is_redirected_to_login(self):
        self.client.logout()

        response = self.client.post(BATCH_URL, self.batch_data({}))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('account_login'), response['Location'])
        self.assertFalse(Entry.objects.exists())

    def test_non_parents_get_403(self):
        unconfigured = get_user_model().objects.create_user(username='unconfigured')
        for user in (self.child.user, self.other_family_child.user, unconfigured):
            with self.subTest(user=user.username):
                self.client.force_login(user)

                response = self.client.post(BATCH_URL, self.batch_data({}))

                self.assertEqual(response.status_code, 403)
        self.assertFalse(Entry.objects.exists())

    def test_other_family_parent_cannot_use_our_members_or_keys(self):
        _, form = self.meetings_form()
        self.client.post(BATCH_URL, posted_from(form))
        ours = Entry.objects.first()
        self.client.force_login(self.other_family_parent.user)

        member = self.client.post(BATCH_URL, self.batch_data({'assigned_member': str(self.child.pk)}))
        replay = self.client.post(BATCH_URL, self.batch_data({'submission_key': str(ours.submission_key)}))

        self.assertIn('assigned_member', member.context['batch_form'].forms[0].errors)
        self.assertContains(replay, SAVE_FAILED_ERROR)
        self.assertFalse(Entry.objects.filter(family=self.other_family).exists())

    def test_saved_panel_ignores_foreign_and_invalid_ids(self):
        foreign = Entry.objects.create(date=datetime.date(2026, 9, 21),
            family=self.other_family, entry_type=EntryType.NOTE.value, content='SENTINEL-OBCY-WPIS'
        )
        ours = Entry.objects.create(date=datetime.date(2026, 9, 21),
            family=self.family, entry_type=EntryType.NOTE.value, content='Nasz wpis'
        )
        too_many = ','.join([str(ours.pk)] * (MAX_PROPOSALS_PER_INSTRUCTION + 1))

        for value in (str(foreign.pk), 'abc', '1²', too_many, f'{foreign.pk},x'):
            with self.subTest(saved=value):
                response = self.client.get(CAPTURE_URL, {'saved': value})
                self.assertEqual(response.context['state'], 'empty')
                self.assertNotContains(response, 'SENTINEL-OBCY-WPIS')

        mixed = self.client.get(CAPTURE_URL, {'saved': f'{foreign.pk},{ours.pk},abc'})
        self.assertEqual(mixed.context['saved_entries'], [ours])
        self.assertContains(mixed, 'Dodano wpis')
        self.assertNotContains(mixed, 'SENTINEL-OBCY-WPIS')


class BatchPrivacyTests(BatchViewMixin, TestCase):
    def test_posted_text_never_reaches_logs(self):
        foreign_key = uuid.uuid4()
        Entry.objects.create(date=datetime.date(2026, 9, 21),
            family=self.other_family, entry_type=EntryType.NOTE.value, content='x',
            submission_key=foreign_key,
        )
        handler = RecordingHandler()
        root = logging.getLogger()
        previous_level = root.level
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)
        try:
            self.client.post(
                BATCH_URL,
                self.batch_data(
                    {'content': SENTINEL},
                    {'content': SENTINEL, 'submission_key': str(foreign_key)},
                ),
            )
            self.client.post(BATCH_URL, self.batch_data({'content': SENTINEL, 'date': ''}))
            self.client.post(BATCH_URL, self.batch_data({'content': SENTINEL}))
        finally:
            root.removeHandler(handler)
            root.setLevel(previous_level)

        self.assertTrue(handler.messages)
        for message in handler.messages:
            self.assertNotIn(SENTINEL, message)
        self.assertEqual(Entry.objects.filter(family=self.family).count(), 1)


# --- Phase 3: per-proposal free-text correction ------------------------------

UNAPPLIED_ERROR = 'Masz niezastosowaną poprawkę — naciśnij „Popraw” albo wyczyść pole.'
CORRECTION_SENTINEL = 'SENTINEL-POPRAWKA-BATCH-77e1'
_BATCH_FIELDS = (
    'entry_type', 'content', 'date', 'time', 'assigned_member', 'school_item',
    'school_subject', 'submission_key', 'correction',
)


def browser_post(batch_form, action='save', **overrides):
    """What a browser posts back from the rendered batch form (bound or not)."""
    data = {'count': str(batch_form.count), 'action': action}
    for form in batch_form.forms:
        for name in _BATCH_FIELDS:
            value = form[name].value()
            if isinstance(value, datetime.time):
                value = value.strftime('%H:%M')
            data[f'{form.prefix}-{name}'] = '' if value is None else str(value)
        if form['include'].value():
            data[f'{form.prefix}-include'] = 'on'
    data.update(overrides)
    return data


def meeting_output(date, changed=None, **overrides):
    values = dict(
        entry_type=EntryType.CALENDAR_EVENT,
        content='Spotkanie z wychowawczynią',
        grounded=True,
        date=date,
        time=SIX_PM,
    )
    values.update(overrides)
    return BackendOutput(
        changed_fields=frozenset(changed) if changed is not None else None, **values
    )


class BatchCorrectionMixin(BatchViewMixin):
    def setUp(self):
        super().setUp()
        self.backend = ScriptedBackend()

    def post_with_backend(self, data, *script):
        self.backend.script.extend(script)
        with mock.patch('entries.views.timezone.localdate', return_value=WEDNESDAY), mock.patch(
            'entries.classification.openai_backend.build_openai_backend',
            return_value=self.backend,
        ):
            return self.client.post(BATCH_URL, data)

    def three_meetings(self):
        return self.batch_data(
            {'date': WEDNESDAY.isoformat(), 'content': 'Spotkanie z dyrekcją'},
            {'date': THURSDAY.isoformat()},
            {'date': NEXT_MONDAY.isoformat(), 'include': None},
        )


class BatchCorrectionTests(BatchCorrectionMixin, TestCase):
    def test_correcting_proposal_two_changes_only_proposal_two(self):
        data = self.three_meetings()
        data['action'] = 'correct-1'
        data['e1-correction'] = 'zmień godzinę na 19:00'

        response = self.post_with_backend(
            data, meeting_output(THURSDAY, changed={'time'}, time=datetime.time(19, 0))
        )

        self.assertEqual(response.context['state'], 'batch')
        (request,) = self.backend.requests
        self.assertEqual(request.current_proposal.date, THURSDAY)
        self.assertEqual(request.correction_text, 'zmień godzinę na 19:00')
        form = response.context['batch_form']
        first, second, third = form.forms
        self.assertEqual(second['time'].value(), datetime.time(19, 0))
        self.assertEqual(second['date'].value(), THURSDAY)
        self.assertTrue(second['include'].value())
        self.assertEqual(first['content'].value(), 'Spotkanie z dyrekcją')
        self.assertEqual(first['time'].value(), '18:00')
        self.assertTrue(first['include'].value())
        self.assertFalse(third['include'].value())
        self.assertEqual(third['date'].value(), NEXT_MONDAY.isoformat())
        self.assertContains(response, 'Wpis 2: zaktualizowano: godzina.')
        old_keys = {data[f'e{index}-submission_key'] for index in range(3)}
        new_keys = {str(sub['submission_key'].value()) for sub in form.forms}
        self.assertEqual(len(new_keys), 3)
        self.assertFalse(old_keys & new_keys)
        self.assertFalse(Entry.objects.exists())

    def test_broken_unticked_proposal_does_not_block_correcting_another(self):
        data = self.three_meetings()
        data.update({'e2-date': 'nie-data', 'action': 'correct-0', 'e0-correction': 'na czwartek'})

        response = self.post_with_backend(
            data, meeting_output(THURSDAY, changed={'date'}, content='Spotkanie z dyrekcją')
        )

        form = response.context['batch_form']
        self.assertEqual(form.forms[0]['date'].value(), THURSDAY)
        self.assertEqual(form.forms[2].errors, {})
        self.assertEqual(form.forms[2]['date'].value(), 'nie-data')
        self.assertContains(response, 'Wpis 1: zaktualizowano: data wydarzenia.')

    def test_after_a_correction_saving_saves_the_corrected_values(self):
        data = self.three_meetings()
        data['action'] = 'correct-1'
        data['e1-correction'] = 'zmień godzinę na 19:00'
        corrected = self.post_with_backend(
            data, meeting_output(THURSDAY, changed={'time'}, time=datetime.time(19, 0))
        )

        saved = self.client.post(BATCH_URL, browser_post(corrected.context['batch_form']))

        self.assertEqual(saved.status_code, 302)
        entries = list(Entry.objects.order_by('date'))
        self.assertEqual([entry.date for entry in entries], [WEDNESDAY, THURSDAY])
        self.assertEqual([entry.time for entry in entries], [SIX_PM, datetime.time(19, 0)])
        self.assertEqual(entries[0].content, 'Spotkanie z dyrekcją')

    def test_failed_correction_keeps_every_proposal_and_the_text(self):
        data = self.three_meetings()
        data['action'] = 'correct-1'
        data['e1-correction'] = 'bla bla'

        response = self.post_with_backend(
            data, ClassificationBackendError(UnavailableReason.TIMEOUT)
        )

        form = response.context['batch_form']
        self.assertEqual(len(form.forms), 3)
        self.assertEqual(form.forms[1]['correction'].value(), 'bla bla')
        self.assertEqual(form.forms[1]['date'].value(), THURSDAY.isoformat())
        self.assertEqual(form.forms[0]['content'].value(), 'Spotkanie z dyrekcją')
        self.assertContains(
            response,
            'Wpis 2: Nie udało się zastosować poprawki. Napisz ją inaczej albo popraw pola ręcznie.',
        )
        self.assertNotIn(data['e1-submission_key'], {str(f['submission_key'].value()) for f in form.forms})

    def test_invalid_target_is_a_stale_form_without_backend_call(self):
        for action in ('correct-3', 'correct-x', 'correct-', 'correct--1', 'correct', 'correct-²'):
            with self.subTest(action=action):
                data = self.three_meetings()
                data['action'] = action
                data['e0-correction'] = 'na czwartek'

                response = self.post_with_backend(data)

                self.assertContains(response, BATCH_STALE_ERROR)
                self.assertEqual(self.backend.requests, [])

    def test_empty_correction_is_a_field_error_without_backend_call(self):
        data = self.three_meetings()
        data['action'] = 'correct-1'

        response = self.post_with_backend(data)

        self.assertContains(response, 'Wpisz, co zmienić.')
        self.assertEqual(self.backend.requests, [])
        self.assertIn('correction', response.context['batch_form'].forms[1].errors)

    def test_save_with_a_pending_correction_saves_nothing(self):
        for index in (0, 2):
            with self.subTest(proposal=index + 1):
                data = self.three_meetings()
                data[f'e{index}-correction'] = 'zmień godzinę'

                response = self.client.post(BATCH_URL, data)

                self.assertEqual(response.context['state'], 'batch')
                self.assertIn(
                    UNAPPLIED_ERROR,
                    response.context['batch_form'].forms[index].errors['correction'],
                )
                self.assertFalse(Entry.objects.exists())

    def test_each_popraw_button_has_a_stable_id_named_by_its_textarea(self):
        response, _ = self.meetings_form()

        for index in range(3):
            self.assertContains(
                response,
                f'<button type="submit" name="action" value="correct-{index}" '
                f'id="e{index}-correct-submit" class="secondary" formnovalidate '
                f'data-classification-submit>Popraw</button>',
                html=True,
            )
            self.assertContains(response, f'data-enter-submitter="e{index}-correct-submit"')
        self.assertContains(response, 'Popraw tekstem', count=3)
        body = response.content.decode()
        self.assertLess(body.index('value="save"'), body.index('value="correct-0"'))

    def test_correction_text_never_reaches_logs(self):
        handler = RecordingHandler()
        root = logging.getLogger()
        previous_level = root.level
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)
        try:
            data = self.three_meetings()
            data.update({'action': 'correct-1', 'e1-correction': CORRECTION_SENTINEL})
            self.post_with_backend(data, ClassificationBackendError(UnavailableReason.TIMEOUT))
            self.post_with_backend(
                data, meeting_output(THURSDAY, changed={'time'}, time=datetime.time(19, 0))
            )
        finally:
            root.removeHandler(handler)
            root.setLevel(previous_level)

        for message in handler.messages:
            self.assertNotIn(CORRECTION_SENTINEL, message)

    def test_correction_is_refused_for_non_parents(self):
        data = self.three_meetings()
        data.update({'action': 'correct-1', 'e1-correction': 'na piątek'})
        self.client.force_login(self.child.user)

        refused = self.post_with_backend(data)
        self.client.logout()
        anonymous = self.post_with_backend(data)

        self.assertEqual(refused.status_code, 403)
        self.assertEqual(anonymous.status_code, 302)
        self.assertEqual(self.backend.requests, [])


class BatchProgressIndicatorTests(BatchCorrectionMixin, TestCase):
    """S-06: each proposal's „Popraw” shows the indicator; „Zapisz wpisy” does not."""

    def test_only_the_popraw_buttons_are_classification_submits(self):
        response, _ = self.meetings_form()

        content = response.content.decode()
        self.assertEqual(assert_progress_regions(self, content), 1)
        [form] = progress_forms(content)
        self.assertEqual(form['attrs']['action'], reverse('entries:confirm_batch'))
        self.assertNotIn('data-classification-default', form['attrs'])
        marked = [
            button['attrs'].get('value')
            for button in form['buttons']
            if 'data-classification-submit' in button['attrs']
        ]
        self.assertEqual(marked, ['correct-0', 'correct-1', 'correct-2'])
        saves = [b for b in form['buttons'] if b['attrs'].get('value') == 'save']
        self.assertEqual(len(saves), 2)
        for save in saves:
            self.assertNotIn('data-classification-submit', save['attrs'])
        self.assertEqual(classification_submitters(form), ['Popraw'] * 3)


class BatchEnterSubmitTests(BatchCorrectionMixin, TestCase):
    """S-05: Enter in a „Popraw tekstem” box runs that proposal's „Popraw” only."""

    def test_each_correction_box_names_its_own_popraw_button(self):
        response, _ = self.meetings_form()

        self.assertEqual(response.context['state'], 'batch')
        self.assertEqual(assert_enter_never_saves(self, response.content.decode()), 3)
        assert_enter_assets(self, response, ['id_e0-correction', 'id_e1-correction', 'id_e2-correction'])

    def test_corrected_batch_keeps_the_safe_submitters(self):
        data = self.three_meetings()
        data['action'] = 'correct-1'
        data['e1-correction'] = 'zmień godzinę na 19:00'

        response = self.post_with_backend(
            data, meeting_output(THURSDAY, changed={'time'}, time=datetime.time(19, 0))
        )

        self.assertEqual(response.context['state'], 'batch')
        self.assertEqual(assert_enter_never_saves(self, response.content.decode()), 3)


class TwoParentBatchSaveTests(TwoParentFixtureMixin, BatchViewMixin, TestCase):
    """S-07: the batch review offers both parents and saves a parent per proposal."""

    def test_every_proposal_offers_both_parents(self):
        _, form = self.meetings_form()

        for entry_form in form.forms:
            with self.subTest(prefix=entry_form.prefix):
                self.assertQuerySetEqual(
                    entry_form.fields['assigned_member'].queryset,
                    [self.parent, self.child, self.other_child, self.second_parent],
                )

    def test_resolved_parents_are_preselected_and_saved_per_proposal(self):
        batch = ParentBatchClassification(
            items=(
                ParentClassification(
                    result=meeting(WEDNESDAY, member_name='Ewa'), member=self.parent
                ),
                ParentClassification(
                    result=meeting(THURSDAY, member_name='Paweł'), member=self.second_parent
                ),
            )
        )
        response = self.capture(batch)
        form = response.context['batch_form']
        self.assertEqual(
            [entry_form.initial['assigned_member'] for entry_form in form.forms],
            [self.parent.pk, self.second_parent.pk],
        )

        self.client.post(BATCH_URL, posted_from(form))

        self.assertEqual(
            list(Entry.objects.order_by('date').values_list('assigned_member_id', flat=True)),
            [self.parent.pk, self.second_parent.pk],
        )

    def test_manually_chosen_parents_are_saved(self):
        data = self.batch_data(
            {'assigned_member': str(self.second_parent.pk)},
            {'assigned_member': str(self.parent.pk), 'date': THURSDAY.isoformat()},
        )

        self.client.post(BATCH_URL, data)

        self.assertEqual(
            list(Entry.objects.order_by('date').values_list('assigned_member_id', flat=True)),
            [self.second_parent.pk, self.parent.pk],
        )

    def test_foreign_or_inactive_parent_saves_nothing(self):
        for member in (self.other_family_parent, self.inactive_parent):
            with self.subTest(member=member.display_name):
                data = self.batch_data({}, {'assigned_member': str(member.pk)})

                response = self.client.post(BATCH_URL, data)

                self.assertIn('assigned_member', response.context['batch_form'].forms[1].errors)
        self.assertFalse(Entry.objects.exists())
