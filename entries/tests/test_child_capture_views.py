"""Child natural-language capture: classify, follow up, correct and confirm for oneself.

A scripted fake backend replaces the configured provider, so the real child views,
forms, classification service and save service run end to end.
"""

import datetime
import re
import uuid
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse

from entries.classification.backends import BackendOutput
from entries.classification.service import ParentBatchClassification, ParentClassification
from entries.classification.types import ClassificationProposal, EntryType, SchoolItemKind
from entries.models import Entry
from entries.services import (
    child_entries,
    parent_family_entries,
    save_child_entries,
    save_child_entry,
)
from entries.views import CORRECTION_FAILED_NOTICE, SAVE_FAILED_ERROR
from family_access.context import FORM_FIELD

from .test_classification_service import FamilyFixtureMixin
from .test_follow_up_views import ScriptedBackend, as_post_data

CAPTURE_URL = reverse('entries:child_capture')
ANSWER_URL = reverse('entries:child_answer')
CORRECT_URL = reverse('entries:child_correct')
CONFIRM_URL = reverse('entries:child_confirm')
BATCH_URL = reverse('entries:child_confirm_batch')
CHILD_ROUTES = (CAPTURE_URL, ANSWER_URL, CORRECT_URL, CONFIRM_URL, BATCH_URL)
PARENT_ROUTES = tuple(
    reverse(f'entries:{name}') for name in ('capture', 'answer', 'correct', 'confirm', 'confirm_batch')
)
SATURDAY = datetime.date(2026, 9, 19)
NEXT_FRIDAY = datetime.date(2026, 9, 25)
POST_FORM = re.compile(r'<form\b[^>]*method="post"[^>]*>.*?</form>', re.DOTALL)


def output(**overrides):
    values = dict(
        entry_type=EntryType.CALENDAR_EVENT,
        content='Trening piłki nożnej',
        grounded=True,
        date=NEXT_FRIDAY,
        time=datetime.time(17, 0),
    )
    values.update(overrides)
    return BackendOutput(**values)


class ChildCaptureMixin(FamilyFixtureMixin):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.child.user)
        self.backend = ScriptedBackend()

    def post_with_backend(self, url, data, *script):
        self.backend.script.extend(script)
        with mock.patch('entries.views.timezone.localdate', return_value=SATURDAY), mock.patch(
            'entries.classification.openai_backend.build_openai_backend', return_value=self.backend
        ):
            return self.client.post(url, data)

    def capture(self, *script, text='Mam trening w piątek o 17'):
        return self.post_with_backend(CAPTURE_URL, {'text': text}, *script)

    def review_data(self, response, **overrides):
        data = as_post_data(response.context['review_form'])
        data.update(overrides)
        return data

    def assertOwnEntry(self, entry, *, is_private=False):
        self.assertEqual(entry.assigned_member, self.child)
        self.assertEqual(entry.created_by, self.child)
        self.assertEqual(entry.family, self.family)
        self.assertEqual(entry.source, Entry.Source.MANUAL)
        self.assertIs(entry.is_private, is_private)


class ChildCaptureAccessTests(ChildCaptureMixin, TestCase):
    def test_anonymous_is_redirected_to_login(self):
        self.client.logout()
        for url in CHILD_ROUTES:
            with self.subTest(url=url):
                response = self.client.post(url, {'text': 'x'})
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse('account_login'), response['Location'])
        self.assertEqual(Entry.objects.count(), 0)

    def test_parents_inactive_children_and_unconfigured_users_are_forbidden(self):
        unconfigured = get_user_model().objects.create_user(username='unconfigured')
        for name, user in (
            ('parent', self.parent.user),
            ('inactive child', self.inactive_child.user),
            ('unconfigured', unconfigured),
        ):
            self.client.force_login(user)
            for url in CHILD_ROUTES:
                with self.subTest(name, url=url):
                    response = self.post_with_backend(url, {'text': 'Trening'}, output())
                    self.assertEqual(response.status_code, 403)
        self.assertEqual(self.backend.requests, [])
        self.assertEqual(Entry.objects.count(), 0)

    def test_child_in_inactive_family_is_forbidden(self):
        self.family.is_active = False
        self.family.save(update_fields=['is_active'])
        self.assertEqual(self.client.get(CAPTURE_URL).status_code, 403)

    def test_parent_capture_routes_stay_parent_only(self):
        for url in PARENT_ROUTES:
            with self.subTest(url=url):
                self.assertEqual(self.post_with_backend(url, {'text': 'Trening'}, output()).status_code, 403)
        self.assertEqual(self.backend.requests, [])

    def test_get_confirm_is_not_allowed(self):
        for url in CHILD_ROUTES[1:]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 405)

    def test_child_list_links_to_the_child_capture_only(self):
        html = self.client.get(reverse('entries:child_list')).content.decode()
        self.assertIn(f'href="{CAPTURE_URL}"', html)
        self.assertNotIn(f'href="{reverse("entries:capture")}"', html)
        self.assertNotIn(f'href="{reverse("entries:create")}"', html)


class ChildCaptureFormTests(ChildCaptureMixin, TestCase):
    def test_capture_page_posts_to_the_child_routes_with_the_family_field(self):
        response = self.client.get(CAPTURE_URL)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'entries/child_capture.html')
        self.assertContains(response, '<h1>Dodaj mój wpis</h1>', html=True)
        self.assertContains(response, f'href="{reverse("entries:child_list")}"')
        self.assertNotContains(response, f'href="{reverse("entries:index")}"')
        self.assert_family_forms(response, {CAPTURE_URL})

    def assert_family_forms(self, response, expected_actions):
        field = f'<input type="hidden" name="{FORM_FIELD}" value="{self.family.pk}">'
        actions = set()
        for form in POST_FORM.findall(response.content.decode().split('<main', 1)[1]):
            self.assertIn(field, form)
            actions.update(re.findall(r'(?:action|formaction)="([^"]*)"', form))
        self.assertEqual(actions, expected_actions)

    def test_review_offers_privacy_and_no_assignee_choice(self):
        response = self.capture(output(member_name='Ania'))

        self.assertEqual(response.context['state'], 'proposal')
        form = response.context['review_form']
        self.assertNotIn('assigned_member', form.fields)
        self.assertFalse(form['is_private'].value())
        self.assertNotContains(response, 'name="assigned_member"')
        self.assertNotContains(response, 'Ania')
        self.assertContains(response, 'Dla kogo: <strong>Michał</strong>', html=True)
        self.assertContains(response, 'Prywatny — widoczny tylko dla mnie')
        self.assertContains(response, 'type="checkbox" name="is_private"')
        self.assertNotContains(response, 'type="checkbox" name="is_private" checked')
        self.assertNotContains(response, 'Usuń')
        self.assertNotContains(response, 'Edytuj')
        self.assert_family_forms(response, {CONFIRM_URL, CORRECT_URL})
        # Only the child's own name reaches the provider.
        self.assertEqual(self.backend.requests[0].allowed_member_names, ('Michał',))

    def test_question_form_has_no_assignee_and_posts_to_child_answer(self):
        response = self.capture(output(date=None))

        self.assertEqual(response.context['state'], 'question')
        self.assertNotIn('assigned_member', response.context['follow_up_form'].fields)
        self.assertNotContains(response, 'name="assigned_member"')
        self.assert_family_forms(response, {ANSWER_URL})


class ChildConfirmTests(ChildCaptureMixin, TestCase):
    def test_task_event_and_note_are_saved_public_for_the_child(self):
        cases = {
            EntryType.TODO: output(entry_type=EntryType.TODO, content='Oddać książkę'),
            EntryType.CALENDAR_EVENT: output(member_name='Ania'),
            EntryType.NOTE: output(entry_type=EntryType.NOTE, content='Pożyczyłem linijkę',
                                   date=None, time=None),
        }
        for entry_type, result in cases.items():
            with self.subTest(entry_type=entry_type):
                response = self.capture(result)
                confirmed = self.client.post(CONFIRM_URL, self.review_data(response))
                entry = Entry.objects.get(entry_type=entry_type.value)
                self.assertRedirects(confirmed, f'{CAPTURE_URL}?saved={entry.pk}')
                self.assertOwnEntry(entry)
                saved = self.client.get(confirmed['Location'])
                self.assertEqual(saved.context['state'], 'saved')
                self.assertEqual(saved.context['saved_entries'], [entry])
                self.assertNotContains(saved, 'data-saved-private')
        # Public: visible under the normal family rules.
        self.assertEqual(parent_family_entries(self.parent).count(), 3)

    def test_private_choice_makes_the_entry_creator_only(self):
        response = self.capture(output())
        self.client.post(CONFIRM_URL, self.review_data(response, is_private='on'))

        entry = Entry.objects.get()
        self.assertOwnEntry(entry, is_private=True)
        self.assertFalse(parent_family_entries(self.parent).exists())
        self.assertEqual(list(child_entries(self.child)), [entry])
        saved = self.client.get(CAPTURE_URL, {'saved': entry.pk})
        self.assertContains(saved, 'data-saved-private')

    def test_tampered_assignee_is_ignored_and_the_child_is_assigned(self):
        response = self.capture(output())
        for member in (self.other_child, self.parent, self.other_family_child):
            with self.subTest(member=member.display_name):
                self.client.post(CONFIRM_URL, self.review_data(
                    response, assigned_member=str(member.pk), submission_key=str(uuid.uuid4())
                ))
        self.assertEqual(Entry.objects.count(), 3)
        for entry in Entry.objects.all():
            self.assertOwnEntry(entry)

    def test_school_event_needing_a_member_is_satisfied_by_the_child(self):
        response = self.capture(output(
            content='Sprawdzian z historii', school_item=SchoolItemKind.TEST,
            school_subject='historia', member_name='Ania',
        ))
        self.assertEqual(response.context['state'], 'proposal')
        self.client.post(CONFIRM_URL, self.review_data(response))
        self.assertOwnEntry(Entry.objects.get())

    def test_invalid_review_rerenders_with_errors_and_saves_nothing(self):
        response = self.capture(output())
        invalid = self.client.post(CONFIRM_URL, self.review_data(response, content='', date=''))

        self.assertEqual(invalid.status_code, 200)
        self.assertEqual(invalid.context['state'], 'invalid')
        self.assertTemplateUsed(invalid, 'entries/child_capture.html')
        self.assertContains(invalid, '<title>Błąd: ')
        self.assertFalse(Entry.objects.exists())

    def test_replay_returns_only_the_childs_own_entry(self):
        response = self.capture(output())
        data = self.review_data(response)
        first = self.client.post(CONFIRM_URL, data)
        again = self.client.post(CONFIRM_URL, data)
        self.assertEqual(first['Location'], again['Location'])
        self.assertEqual(Entry.objects.count(), 1)

    def test_replayed_key_of_another_creator_is_refused_without_leaking(self):
        others = [
            Entry.objects.create(
                family=self.family, entry_type=EntryType.NOTE.value, content=f'SENTINEL-{name}',
                date=SATURDAY, assigned_member=self.child, created_by=creator,
                submission_key=uuid.uuid4(), is_private=private,
            )
            for name, creator, private in (
                ('PARENT-PUBLIC', self.parent, False),
                ('SIBLING-PUBLIC', self.other_child, False),
                ('SIBLING-PRIVATE', self.other_child, True),
            )
        ]
        response = self.capture(output())
        for entry in others:
            with self.subTest(entry=entry.content):
                refused = self.client.post(CONFIRM_URL, self.review_data(
                    response, submission_key=str(entry.submission_key)
                ))
                self.assertEqual(refused.status_code, 200)
                self.assertEqual(refused.context['state'], 'invalid')
                self.assertContains(refused, SAVE_FAILED_ERROR)
                self.assertNotContains(refused, 'SENTINEL')
                new_key = refused.context['review_form']['submission_key'].value()
                self.assertNotEqual(str(new_key), str(entry.submission_key))
        self.assertEqual(Entry.objects.count(), len(others))

    def test_saved_panel_ignores_entries_that_are_not_the_childs_own(self):
        sibling = Entry.objects.create(
            family=self.family, entry_type=EntryType.NOTE.value, content='SENTINEL-SIBLING',
            date=SATURDAY, assigned_member=self.other_child,
        )
        general = Entry.objects.create(
            family=self.family, entry_type=EntryType.NOTE.value, content='SENTINEL-GENERAL',
            date=SATURDAY,
        )
        response = self.client.get(CAPTURE_URL, {'saved': f'{sibling.pk},{general.pk}'})
        self.assertEqual(response.context['state'], 'empty')
        self.assertNotContains(response, 'SENTINEL')


class ChildFollowUpAndCorrectionTests(ChildCaptureMixin, TestCase):
    def test_answer_completes_the_draft_and_a_named_sibling_is_ignored(self):
        question = self.capture(output(date=None, member_name='Ania'))
        data = as_post_data(question.context['follow_up_form'])

        answered = self.post_with_backend(
            ANSWER_URL, {**data, 'answer': 'w piątek, z Anią'},
            output(date=NEXT_FRIDAY, member_name='Ania', member_mention='Ania'),
        )

        self.assertEqual(answered.context['state'], 'proposal')
        self.assertEqual(answered.context['review_form']['date'].value(), NEXT_FRIDAY)
        self.assertEqual(self.backend.requests[-1].allowed_member_names, ('Michał',))
        self.client.post(CONFIRM_URL, self.review_data(answered))
        self.assertOwnEntry(Entry.objects.get())

    def test_tampered_hidden_assignee_cannot_redirect_the_draft(self):
        question = self.capture(output(date=None))
        data = {**as_post_data(question.context['follow_up_form']),
                'assigned_member': str(self.other_child.pk), 'action': 'skip'}

        skipped = self.post_with_backend(ANSWER_URL, data)

        self.assertEqual(skipped.context['state'], 'skipped')
        self.client.post(CONFIRM_URL, self.review_data(skipped))
        self.assertOwnEntry(Entry.objects.get())

    def test_invalid_answer_rerenders_the_question(self):
        question = self.capture(output(date=None))
        response = self.post_with_backend(ANSWER_URL, {**as_post_data(question.context['follow_up_form']),
                                         'answer': ''})
        self.assertEqual(response.context['state'], 'question')
        self.assertContains(response, '<title>Błąd: ')

    def test_correction_changes_fields_but_never_the_person(self):
        review = self.capture(output())
        data = self.review_data(review, correction='w sobotę z Anią', is_private='on')

        corrected = self.post_with_backend(CORRECT_URL, data, output(
            date=datetime.date(2026, 9, 26), member_name='Ania', member_mention='Ania',
            changed_fields=frozenset({'date', 'member_name'}),
        ))

        self.assertEqual(corrected.context['state'], 'proposal')
        form = corrected.context['review_form']
        self.assertEqual(form['date'].value(), datetime.date(2026, 9, 26))
        self.assertTrue(form['is_private'].value())  # the choice survives the correction
        self.assertEqual(self.backend.requests[-1].current_proposal.member_name, 'Michał')
        self.client.post(CONFIRM_URL, as_post_data(form) | {'is_private': 'on'})
        self.assertOwnEntry(Entry.objects.get(), is_private=True)

    def test_correction_that_only_reassigns_is_not_applied(self):
        review = self.capture(output())
        data = self.review_data(review, correction='to dla Ani')

        failed = self.post_with_backend(CORRECT_URL, data, output(
            member_name='Ania', member_mention='Ania', changed_fields=frozenset({'member_name'}),
        ))

        self.assertEqual(failed.context['state'], 'correction_failed')
        self.assertContains(failed, CORRECTION_FAILED_NOTICE)
        self.assertFalse(Entry.objects.exists())


class ChildBatchTests(ChildCaptureMixin, TestCase):
    def batch(self):
        proposals = tuple(
            ParentClassification(
                result=ClassificationProposal(
                    entry_type=EntryType.TODO, content='Spakować strój na basen',
                    date=SATURDAY + datetime.timedelta(days=offset),
                ),
                member=self.child,
            )
            for offset in (1, 2)
        )
        with mock.patch(
            'entries.views.classify_entries_for_child',
            return_value=ParentBatchClassification(items=proposals),
        ) as classify, mock.patch('entries.views.timezone.localdate', return_value=SATURDAY):
            response = self.client.post(CAPTURE_URL, {'text': 'Basen jutro i pojutrze'})
        classify.assert_called_once()
        self.assertEqual(classify.call_args.args[0], self.child)
        return response

    def posted(self, response, **extra):
        form = response.context['batch_form']
        data = {'count': str(form.count), 'action': 'save'}
        for entry_form in form.forms:
            for name, value in entry_form.initial.items():
                if name in ('include', 'is_private'):
                    continue
                data[f'{entry_form.prefix}-{name}'] = '' if value is None else str(value)
            data[f'{entry_form.prefix}-include'] = 'on'
        data.update(extra)
        return data

    def test_each_proposal_has_its_own_privacy_choice_and_is_saved_for_the_child(self):
        response = self.batch()
        self.assertEqual(response.context['state'], 'batch')
        self.assertContains(response, 'name="e0-is_private"')
        self.assertContains(response, 'name="e1-is_private"')
        self.assertNotContains(response, 'assigned_member')
        self.assertContains(response, f'action="{BATCH_URL}"')

        saved = self.client.post(BATCH_URL, self.posted(
            response, **{'e1-is_private': 'on', 'e0-assigned_member': str(self.other_child.pk)}
        ))

        entries = list(Entry.objects.order_by('date'))
        self.assertRedirects(saved, f'{CAPTURE_URL}?saved={entries[0].pk},{entries[1].pk}')
        self.assertOwnEntry(entries[0])
        self.assertOwnEntry(entries[1], is_private=True)

    def test_batch_replay_of_another_creators_key_rolls_back(self):
        foreign = Entry.objects.create(
            family=self.family, entry_type=EntryType.NOTE.value, content='SENTINEL-PARENT',
            date=SATURDAY, assigned_member=self.child, created_by=self.parent,
            submission_key=uuid.uuid4(),
        )
        response = self.batch()
        refused = self.client.post(BATCH_URL, self.posted(
            response, **{'e1-submission_key': str(foreign.submission_key)}
        ))
        self.assertEqual(refused.status_code, 200)
        self.assertContains(refused, SAVE_FAILED_ERROR)
        self.assertNotContains(refused, 'SENTINEL')
        self.assertEqual(list(Entry.objects.all()), [foreign])

    def test_batch_correction_keeps_the_child_and_the_privacy_choice(self):
        response = self.batch()
        data = self.posted(response, action='correct-0', **{
            'e0-correction': 'w niedzielę dla Ani', 'e0-is_private': 'on',
        })
        corrected_output = BackendOutput(
            entry_type=EntryType.TODO, content='Spakować strój na basen', grounded=True,
            date=datetime.date(2026, 9, 20), member_name='Ania',
            changed_fields=frozenset({'date', 'member_name'}),
        )
        retry = self.post_with_backend(BATCH_URL, data, corrected_output)

        form = retry.context['batch_form']
        self.assertEqual(form.forms[0]['date'].value(), datetime.date(2026, 9, 20))
        self.assertTrue(form.forms[0]['is_private'].value())
        self.assertNotIn('assigned_member', form.forms[0].fields)
        self.assertFalse(Entry.objects.exists())


class ChildSaveServiceTests(FamilyFixtureMixin, TestCase):
    def values(self, **overrides):
        values = dict(
            entry_type=EntryType.TODO.value, content='Oddać książkę', date=SATURDAY, time=None,
            assigned_member=None, school_item='', school_subject='', submission_key=uuid.uuid4(),
        )
        values.update(overrides)
        return values

    def test_no_assignee_becomes_the_child_and_the_child_is_creator(self):
        entry, created = save_child_entry(self.child, **self.values())
        self.assertTrue(created)
        self.assertEqual((entry.assigned_member, entry.created_by), (self.child, self.child))
        self.assertFalse(entry.is_private)

    def test_another_assignee_is_rejected(self):
        for member in (self.other_child, self.parent, self.other_family_child):
            with self.subTest(member=member.display_name):
                with self.assertRaises(ValidationError):
                    save_child_entry(self.child, **self.values(assigned_member=member))
        with self.assertRaises(ValidationError):
            save_child_entries(self.child, [
                self.values(), self.values(assigned_member=self.other_child),
            ])
        self.assertFalse(Entry.objects.exists())

    def test_non_children_are_refused(self):
        for membership in (self.parent, self.inactive_child, None):
            with self.subTest(membership=membership):
                with self.assertRaises(PermissionDenied):
                    save_child_entry(membership, **self.values())
        self.assertFalse(Entry.objects.exists())

    def test_replay_of_a_siblings_public_entry_is_rejected(self):
        sibling, _ = save_child_entry(self.other_child, **self.values())
        with self.assertRaises(ValidationError):
            save_child_entry(self.child, **self.values(submission_key=sibling.submission_key))
        self.assertEqual(list(Entry.objects.all()), [sibling])
