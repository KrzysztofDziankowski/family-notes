"""Structural accessibility audit of every covered family flow (S-17).

Each state is rendered through the real views (classification mocked at the
view boundary, as in ``test_capture_views``) and must pass ``audit_page``.
See ``context/foundation/accessibility.md``; a new product page adds a case here.
"""

import datetime
import re
import uuid
from unittest import mock

from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from entries.classification.service import (
    CorrectionRejection,
    ParentBatchClassification,
    ParentClassification,
    ProposalCorrection,
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
from entries.forms import CaptureForm
from entries.models import Entry
from entries.views import PROGRESS_STATE_LABELS, _describe_capture_forms, _progress_thresholds
from family_notes.a11y_audit import assert_accessible

from .test_classification_service import FamilyFixtureMixin
from .test_follow_up_views import as_post_data

CAPTURE_URL = reverse('entries:capture')
ANSWER_URL = reverse('entries:answer')
CORRECT_URL = reverse('entries:correct')
CONFIRM_URL = reverse('entries:confirm')
BATCH_URL = reverse('entries:confirm_batch')
TODAY = datetime.date(2026, 10, 5)
NEXT_MONDAY = datetime.date(2026, 10, 12)
PROGRESS_STATES = [state for state, _label in PROGRESS_STATE_LABELS]


def proposal(**overrides):
    values = dict(
        entry_type=EntryType.CALENDAR_EVENT,
        content='Sprawdzian z biologii',
        date=NEXT_MONDAY,
        time=datetime.time(8, 0),
        school_item=SchoolItemKind.TEST,
        school_subject='biologia',
        member_name='Michał',
    )
    values.update(overrides)
    return ClassificationProposal(**values)


def missing_date():
    return ClassificationFollowUp(
        missing_fields=(MissingField.DATE,),
        entry_type=EntryType.CALENDAR_EVENT,
        content='Wywiadówka w szkole',
    )


class CaptureAuditMixin(FamilyFixtureMixin):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.parent.user)
        patcher = mock.patch('entries.views.timezone.localdate', return_value=TODAY)
        patcher.start()
        self.addCleanup(patcher.stop)

    def outcome(self, result):
        member = self.child if getattr(result, 'member_name', None) else None
        return ParentClassification(result=result, member=member)

    def capture(self, *results, text='Michał ma sprawdzian z biologii'):
        batch = ParentBatchClassification(items=tuple(self.outcome(r) for r in results))
        with mock.patch('entries.views.classify_entries_for_parent', return_value=batch):
            return self.client.post(CAPTURE_URL, {'text': text})

    def assert_state(self, response, state):
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['state'], state)
        assert_accessible(self, response)

    def review_data(self, **overrides):
        data = as_post_data(self.capture(proposal()).context['review_form'])
        data.update(overrides)
        return data

    def question_data(self):
        response = self.capture(missing_date())
        return as_post_data(response.context['follow_up_form'])


class CaptureFlowAuditTests(CaptureAuditMixin, TestCase):
    def test_empty(self):
        self.assert_state(self.client.get(CAPTURE_URL), 'empty')

    def test_invalid(self):
        self.assert_state(self.client.post(CAPTURE_URL, {'text': ''}), 'empty')

    def test_proposal(self):
        self.assert_state(self.capture(proposal()), 'proposal')

    def test_past_date(self):
        self.assert_state(self.capture(proposal(date=TODAY - datetime.timedelta(days=3))), 'proposal')

    def test_unavailable(self):
        response = self.capture(ClassificationUnavailable(reason=UnavailableReason.TIMEOUT))
        self.assert_state(response, 'unavailable')

    def test_follow_up_question(self):
        self.assert_state(self.capture(missing_date()), 'question')

    def test_follow_up_invalid(self):
        response = self.client.post(ANSWER_URL, {**self.question_data(), 'answer': ''})
        self.assert_state(response, 'question')

    def test_skipped(self):
        response = self.client.post(ANSWER_URL, {**self.question_data(), 'action': 'skip'})
        self.assert_state(response, 'skipped')

    def test_follow_up_answer_highlights_review(self):
        with mock.patch(
            'entries.views.classify_follow_up_answer',
            return_value=ParentClassification(result=missing_date()),
        ):
            response = self.client.post(ANSWER_URL, {**self.question_data(), 'answer': 'nie wiem'})
        self.assert_state(response, 'follow_up')

    def test_confirm_invalid(self):
        response = self.client.post(CONFIRM_URL, self.review_data(content='', date=''))
        self.assert_state(response, 'invalid')

    def test_unapplied_correction_on_save(self):
        response = self.client.post(CONFIRM_URL, self.review_data(correction='zmień datę'))
        self.assert_state(response, 'invalid')

    def test_saved(self):
        entry = Entry.objects.create(date=datetime.date(2026, 9, 21),
            family=self.family,
            entry_type=EntryType.TODO.value,
            content='Oddać zgodę',
            created_by=self.parent,
        )
        self.assert_state(self.client.get(CAPTURE_URL, {'saved': entry.pk}), 'saved')


class CorrectionAuditTests(CaptureAuditMixin, TestCase):
    def correct(self, correction, **data):
        with mock.patch('entries.views.correct_proposal_for_parent', return_value=correction):
            return self.client.post(CORRECT_URL, self.review_data(correction='na piątek', **data))

    def test_corrected(self):
        corrected = ProposalCorrection(
            outcome=self.outcome(proposal(date=NEXT_MONDAY + datetime.timedelta(days=4))),
            changed=frozenset({'date'}),
            applied=True,
        )
        self.assert_state(self.correct(corrected), 'proposal')

    def test_correction_failed(self):
        failed = ProposalCorrection(outcome=None, rejection=CorrectionRejection.NOT_APPLIED)
        self.assert_state(self.correct(failed), 'correction_failed')

    def test_correction_too_long(self):
        too_long = ProposalCorrection(outcome=None, rejection=CorrectionRejection.TOO_LONG)
        self.assert_state(self.correct(too_long), 'correction_failed')

    def test_correction_invalid(self):
        response = self.client.post(CORRECT_URL, self.review_data(correction=''))
        self.assert_state(response, 'invalid')


class BatchAuditTests(CaptureAuditMixin, TestCase):
    def batch(self):
        return self.capture(
            proposal(),
            proposal(date=NEXT_MONDAY + datetime.timedelta(days=1)),
            missing_date(),
        )

    def test_batch_review(self):
        self.assert_state(self.batch(), 'batch')

    def test_batch_invalid(self):
        response = self.batch()
        data = {'count': '3', 'action': 'save'}
        for entry_form in response.context['batch_form'].forms:
            values = as_post_data(entry_form)
            values.pop('include', None)
            data.update({f'{entry_form.prefix}-{name}': value for name, value in values.items()})

        invalid = self.client.post(BATCH_URL, data)

        self.assert_state(invalid, 'batch')
        self.assertContains(invalid, 'role="alert"')


class ProgressStateAuditTests(CaptureAuditMixin, TestCase):
    """Capture and follow-up forms in each S-06 progress state, one form per page."""

    def render_capture(self, **context):
        request = RequestFactory().get(CAPTURE_URL)
        request.user = self.parent.user
        context = {'state': 'empty', **_progress_thresholds(), **context}
        _describe_capture_forms(context)
        return render_to_string('entries/capture.html', context, request=request)

    def test_capture_in_each_progress_state(self):
        for state in PROGRESS_STATES:
            with self.subTest(state=state):
                html = self.render_capture(
                    capture_form=CaptureForm(initial={'text': 'Kasia ma jutro sprawdzian'}),
                    progress_state=state,
                )
                self.assertIn(f'data-progress-state="{state}">', html)
                assert_accessible(self, html)

    def test_follow_up_in_each_progress_state(self):
        follow_up_form = self.capture(missing_date()).context['follow_up_form']
        for state in PROGRESS_STATES:
            with self.subTest(state=state):
                html = self.render_capture(
                    state='question', follow_up_form=follow_up_form, progress_state=state
                )
                self.assertIn(f'data-progress-state="{state}">', html)
                assert_accessible(self, html)


class ManagementAuditTests(FamilyFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.parent.user)
        self.today = timezone.localdate()

    def entry(self, content, days=None, **fields):
        date = self.today + datetime.timedelta(days=10 if days is None else days)
        return Entry.objects.create(
            family=self.family,
            entry_type=EntryType.TODO.value,
            content=content,
            date=date,
            created_by=self.parent,
            **fields,
        )

    def form_data(self, **overrides):
        data = {
            'entry_type': EntryType.TODO.value,
            'content': 'Oddać książkę',
            'date': '',
            'time': '',
            'assigned_member': str(self.child.pk),
            'school_item': '',
            'school_subject': '',
            'submission_key': str(uuid.uuid4()),
        }
        data.update(overrides)
        return data

    def window(self, offset):
        return {'start': (self.today + datetime.timedelta(days=offset)).isoformat()}

    def test_list_today_earlier_and_empty_windows(self):
        cases = {'empty today': {}, 'empty earlier': self.window(-14)}
        for name, params in cases.items():
            with self.subTest(name):
                assert_accessible(self, self.client.get(reverse('entries:index'), params))
        self.entry('Zebranie', days=2, assigned_member=self.child)
        self.entry('Odebrać paczkę', days=2, assigned_member=self.parent)
        self.entry('Wynieść śmieci', days=2)
        self.entry('Kupić blok')
        self.entry('Zapłacić za obiady', days=-3, assigned_member=self.parent)
        self.entry('Oddać bilety', days=-3)
        # S-08: h1 page title, h2 per calendar day (all 14, empty ones too),
        # h3 per assignee within the day.
        assignee_groups = {
            'today': ({}, range(14), {2: 3, 10: 1}),
            'earlier': (self.window(-14), range(-14, 0), {-3: 2}),
        }
        for window, (params, offsets, groups) in assignee_groups.items():
            headings = ['h1']
            for offset in offsets:
                headings += ['h2'] + ['h3'] * groups.get(offset, 0)
            with self.subTest(window=window):
                response = self.client.get(reverse('entries:index'), params)
                assert_accessible(self, response)
                html = response.content.decode()
                main = html[html.index('<main'):html.index('</main>')]
                self.assertEqual(re.findall(r'<(h[1-6])\b', main), headings)
                # The calendar nav is a labelled landmark whose current window is
                # announced only on the window starting today.
                self.assertEqual(main.count('aria-label="Nawigacja kalendarza"'), 1)
                self.assertEqual(
                    main.count('aria-current="page">Dzisiaj</a>'), 1 if window == 'today' else 0
                )

    def test_filtered_and_unfiltered_windows(self):
        """Phase 4: the "Filtr wpisów" nav and its live region pass, with and without a child."""
        self.entry('Zebranie', days=2, assigned_member=self.child)
        self.entry('Basen', days=2, assigned_member=self.other_child)
        self.entry('Odebrać paczkę', days=3, assigned_member=self.parent)
        self.entry('Wynieść śmieci', days=2)
        cases = {
            'unfiltered': {},
            'filtered': {'member': str(self.child.pk)},
            'filtered earlier': {**self.window(-14), 'member': str(self.other_child.pk)},
            'invalid member': {'member': str(self.other_family_child.pk)},
        }
        for name, params in cases.items():
            with self.subTest(name):
                response = self.client.get(reverse('entries:index'), params)
                assert_accessible(self, response)
                html = response.content.decode()
                main = html[html.index('<main'):html.index('</main>')]
                self.assertEqual(main.count('aria-label="Filtr wpisów"'), 1)
                self.assertEqual(main.count('data-live-region'), 1)
                self.assertEqual(main.count('data-member-key='), 3)
                self.assertEqual(
                    re.findall(r'data-member-key="([\w-]+)" aria-current="page"', main),
                    [f'member-{self.child.pk}' if name == 'filtered'
                     else f'member-{self.other_child.pk}' if name == 'filtered earlier' else 'all'],
                )
        entry = self.entry('Zebranie', days=2, assigned_member=self.child)
        assert_accessible(self, self.client.get(
            reverse('entries:detail', args=[entry.pk]), {'member': str(self.child.pk)}
        ))

    def test_detail_and_open_delete_disclosure(self):
        entry = self.entry('Zebranie', days=2, assigned_member=self.child)
        assert_accessible(self, self.client.get(reverse('entries:detail', args=[entry.pk])))

        request = RequestFactory().get(reverse('entries:detail', args=[entry.pk]))
        request.user = self.parent.user
        request._messages = mock.MagicMock(__iter__=lambda _self: iter(()))
        html = render_to_string(
            'entries/manage_detail.html',
            {
                'entry': entry,
                'list_start': self.today,
                'list_query': f'start={self.today.isoformat()}',
                'delete_open': True,
            },
            request=request,
        )
        self.assertIn('data-state-part="delete" open', html)
        assert_accessible(self, html)

    def test_create_and_create_invalid(self):
        assert_accessible(self, self.client.get(reverse('entries:create')))
        invalid = self.client.post(
            reverse('entries:create'),
            self.form_data(content='', school_item=SchoolItemKind.HOMEWORK.value),
        )
        self.assertEqual(invalid.status_code, 200)
        assert_accessible(self, invalid)

    def test_edit_and_edit_invalid(self):
        entry = self.entry('Zebranie', days=2, assigned_member=self.child)
        url = reverse('entries:edit', args=[entry.pk])
        assert_accessible(self, self.client.get(url))
        invalid = self.client.post(url, self.form_data(content=''))
        self.assertEqual(invalid.status_code, 200)
        assert_accessible(self, invalid)


class ChildAuditTests(FamilyFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.child.user)
        self.today = timezone.localdate()

    def window(self, offset):
        return {'start': (self.today + datetime.timedelta(days=offset)).isoformat()}

    def test_calendar_today_earlier_and_empty_windows_and_detail(self):
        url = reverse('entries:child_list')
        for name, params in {'empty today': {}, 'empty earlier': self.window(-14)}.items():
            with self.subTest(name):
                assert_accessible(self, self.client.get(url, params))
        entries = [
            Entry.objects.create(
                family=self.family,
                entry_type=EntryType.TODO.value,
                content=content,
                date=self.today + datetime.timedelta(days=days),
                assigned_member=self.child,
                created_by=self.parent,
                **fields,
            )
            for content, days, fields in (
                ('Zebranie', 1, {}),
                ('Kupić blok', 1, {}),
                ('Szczęśliwy numerek: 7', 2,
                 {'school_item': SchoolItemKind.LUCKY_NUMBER.value}),
                ('Obiady', -2, {}),
            )
        ]
        for window, (params, offset) in {'today': ({}, 0), 'earlier': (self.window(-14), -14)}.items():
            with self.subTest(window=window):
                response = self.client.get(url, params)
                assert_accessible(self, response)
                html = response.content.decode()
                main = html[html.index('<main'):html.index('</main>')]
                # h1 page title and one h2 per calendar day; no assignee h3.
                self.assertEqual(re.findall(r'<(h[1-6])\b', main), ['h1'] + ['h2'] * 14)
                self.assertEqual(main.count('aria-label="Nawigacja kalendarza"'), 1)
                self.assertEqual(
                    main.count('aria-current="page">Dzisiaj</a>'), 1 if window == 'today' else 0
                )
                day_ids = re.findall(r'<h2 class="fn-day-heading" id="([^"]+)"', main)
                self.assertEqual(len(day_ids), 14)
                for list_id in re.findall(r'aria-labelledby="([^"]+)"', main):
                    self.assertIn(list_id, day_ids)
        assert_accessible(self, self.client.get(reverse('entries:child_detail', args=[entries[0].pk])))
        assert_accessible(
            self,
            self.client.get(reverse('entries:child_detail', args=[entries[3].pk]), self.window(-14)),
        )


CHILD_CAPTURE_URL = reverse('entries:child_capture')
CHILD_ANSWER_URL = reverse('entries:child_answer')
CHILD_CORRECT_URL = reverse('entries:child_correct')
CHILD_CONFIRM_URL = reverse('entries:child_confirm')
CHILD_BATCH_URL = reverse('entries:child_confirm_batch')


class ChildCaptureAuditTests(FamilyFixtureMixin, TestCase):
    """Child capture, review, follow-up, correction, invalid and saved states."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.child.user)
        patcher = mock.patch('entries.views.timezone.localdate', return_value=TODAY)
        patcher.start()
        self.addCleanup(patcher.stop)

    def capture(self, *results):
        batch = ParentBatchClassification(
            items=tuple(ParentClassification(result=r, member=self.child) for r in results)
        )
        with mock.patch('entries.views.classify_entries_for_child', return_value=batch):
            return self.client.post(CHILD_CAPTURE_URL, {'text': 'Mam sprawdzian z biologii'})

    def assert_state(self, response, state):
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['state'], state)
        self.assertTemplateUsed(response, 'entries/child_capture.html')
        assert_accessible(self, response)

    def review_data(self, **overrides):
        data = as_post_data(self.capture(proposal()).context['review_form'])
        data.update(overrides)
        return data

    def question_data(self):
        return as_post_data(self.capture(missing_date()).context['follow_up_form'])

    def test_empty_and_invalid_capture(self):
        self.assert_state(self.client.get(CHILD_CAPTURE_URL), 'empty')
        self.assert_state(self.client.post(CHILD_CAPTURE_URL, {'text': ''}), 'empty')

    def test_proposal_with_privacy_choice(self):
        response = self.capture(proposal())
        self.assert_state(response, 'proposal')
        self.assertContains(response, 'for="id_is_private"')

    def test_unavailable(self):
        response = self.capture(ClassificationUnavailable(reason=UnavailableReason.TIMEOUT))
        self.assert_state(response, 'unavailable')

    def test_follow_up_question_invalid_answer_and_skip(self):
        self.assert_state(self.capture(missing_date()), 'question')
        data = self.question_data()
        self.assert_state(self.client.post(CHILD_ANSWER_URL, {**data, 'answer': ''}), 'question')
        self.assert_state(
            self.client.post(CHILD_ANSWER_URL, {**data, 'action': 'skip'}), 'skipped'
        )

    def test_follow_up_answer_highlights_review(self):
        with mock.patch(
            'entries.views.classify_follow_up_answer_for_child',
            return_value=ParentClassification(result=missing_date(), member=self.child),
        ):
            response = self.client.post(
                CHILD_ANSWER_URL, {**self.question_data(), 'answer': 'nie wiem'}
            )
        self.assert_state(response, 'follow_up')

    def test_correction_states(self):
        failed = ProposalCorrection(outcome=None, rejection=CorrectionRejection.NOT_APPLIED)
        with mock.patch('entries.views.correct_proposal_for_child', return_value=failed):
            response = self.client.post(CHILD_CORRECT_URL, self.review_data(correction='dla Ani'))
        self.assert_state(response, 'correction_failed')
        self.assert_state(
            self.client.post(CHILD_CORRECT_URL, self.review_data(correction='')), 'invalid'
        )

    def test_confirm_invalid(self):
        response = self.client.post(CHILD_CONFIRM_URL, self.review_data(content='', date=''))
        self.assert_state(response, 'invalid')

    def test_batch_review_and_invalid(self):
        response = self.capture(proposal(), proposal(date=NEXT_MONDAY + datetime.timedelta(days=1)))
        self.assert_state(response, 'batch')
        data = {'count': '2', 'action': 'save'}
        for entry_form in response.context['batch_form'].forms:
            values = as_post_data(entry_form)
            values.pop('include', None)
            values.pop('is_private', None)
            data.update({f'{entry_form.prefix}-{name}': value for name, value in values.items()})
        invalid = self.client.post(CHILD_BATCH_URL, data)
        self.assert_state(invalid, 'batch')
        self.assertContains(invalid, 'role="alert"')

    def test_saved_public_and_private(self):
        for is_private in (False, True):
            with self.subTest(is_private=is_private):
                entry = Entry.objects.create(
                    date=TODAY, family=self.family, entry_type=EntryType.TODO.value,
                    content='Oddać książkę', assigned_member=self.child,
                    created_by=self.child, is_private=is_private,
                )
                response = self.client.get(CHILD_CAPTURE_URL, {'saved': entry.pk})
                self.assert_state(response, 'saved')
                self.assertEqual(
                    'data-saved-private' in response.content.decode(), is_private
                )

    def test_child_list_with_capture_link(self):
        response = self.client.get(reverse('entries:child_list'))
        self.assertContains(response, f'href="{CHILD_CAPTURE_URL}"')
        assert_accessible(self, response)
