"""Representative acceptance corpus for the classification boundary.

Every case runs the real ``classify_for_parent`` service with the real
``OpenAIClassificationBackend``. The OpenAI client is a real SDK client whose
HTTP transport is scripted, so request serialization, adapter translation,
domain validation, and local member resolution are all exercised without
network access, nondeterminism, or real sleeps. The model does the date
arithmetic; these tests assert that the reference date and weekday are sent
and that the returned date flows unchanged into the proposal.

All instructions and names are synthetic. Live evaluation against the real
provider is opt-in (``CLASSIFICATION_LIVE_EVAL=1``) and skipped by default.
"""

import datetime
import io
import json
import os
import re
import shutil
import subprocess
import time
import unittest
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings

from entries.classification.backends import BackendOutput, ClassificationBackendError
from entries.classification.openai_backend import OpenAIClassificationBackend, build_openai_backend
from entries.classification.service import classify_for_parent, correct_proposal_for_parent
from entries.classification.types import (
    ClassificationFollowUp,
    ClassificationProposal,
    ClassificationUnavailable,
    EntryType,
    MissingField,
    ProposalValues,
    SchoolItemKind,
    UnavailableReason,
)
from entries.management.commands import classification_smoke
from entries.tests.test_classification_service import FamilyFixtureMixin
from entries.tests.test_openai_backend import (
    CONNECTION,
    FULL_SETTINGS,
    MODEL,
    TIMEOUT,
    FakeClock,
    ScriptedTransport,
    make_client,
    ok,
    response_body,
    status_error,
)
from family_access.models import FamilyMember

# PRD US-01: an instruction entered on Saturday 2026-09-19 about "Monday"
# must be dated Monday 2026-09-21.
PRD_REFERENCE_DATE = datetime.date(2026, 9, 19)
PRD_MONDAY = datetime.date(2026, 9, 21)
PRD_INSTRUCTION = 'Michał ma w poniedziałek sprawdzian z biologii o skórze'
PRD_CONTENT = 'Sprawdzian z biologii o skórze'
DEADLINE_SECONDS = 25.0
PRD_BUDGET_SECONDS = 30.0

# PK-10 / US-10: a meeting proposed for Friday 2026-09-25, corrected on
# Saturday 2026-09-19 with „zmień datę na 15 października”.
CORRECTION_TEXT = 'zmień datę na 15 października'
CORRECTED_DATE = datetime.date(2026, 10, 15)
MEETING = ProposalValues(
    entry_type=EntryType.CALENDAR_EVENT,
    content='Spotkanie z wychowawczynią',
    date=datetime.date(2026, 9, 25),
    time=datetime.time(17, 0),
)


def model_output(**fields):
    """A scripted structured-output answer, as the model would return it."""
    return ok(response_body(json.dumps(model_values(**fields), ensure_ascii=False)))


def model_list_output(*entries):
    """A scripted list answer (``classify_many``); each entry is a ``model_values`` dict."""
    body = {'entries': [model_values(**entry) for entry in entries]}
    return ok(response_body(json.dumps(body, ensure_ascii=False)))


def model_entry_output(**fields):
    """``model_output`` wrapped as a one-entry list, as capture now asks for it."""
    return model_list_output(fields)


def model_values(**fields):
    values = dict(
        entry_type=None,
        content='',
        grounded=True,
        date=None,
        date_source=None,
        time=None,
        school_item=None,
        member_name=None,
        school_subject=None,
        member_mention=None,
    )
    values.update(fields)
    return values


class AdapterPathMixin(FamilyFixtureMixin):
    """Runs the service through the real adapter over a scripted transport."""

    def run_service(self, steps, text=PRD_INSTRUCTION, reference_date=PRD_REFERENCE_DATE):
        self.clock = FakeClock()
        self.transport = ScriptedTransport(self.clock, steps)
        backend = OpenAIClassificationBackend(
            client=make_client(self.transport),
            model=MODEL,
            clock=self.clock,
            sleep=self.clock.sleep,
        )
        return classify_for_parent(
            self.parent.user,
            text,
            reference_date=reference_date,
            locale='pl-PL',
            backend=backend,
        )

    def sent_input(self, index=0):
        return json.loads(self.transport.bodies()[index]['input'])


class PrdSchoolEventTests(AdapterPathMixin, TestCase):
    """US-01: "Michał has a biology test on Monday about the skin"."""

    def test_prd_example_is_dated_monday_and_assigned_to_michal(self):
        outcome = self.run_service(
            [
                model_output(
                    entry_type='calendar_event',
                    content=PRD_CONTENT,
                    date=PRD_MONDAY.isoformat(),
                    date_source='w poniedziałek',
                    school_item='test',
                    member_name='Michał',
                    school_subject='biologia',
                )
            ]
        )

        self.assertEqual(
            outcome.result,
            ClassificationProposal(
                entry_type=EntryType.CALENDAR_EVENT,
                content=PRD_CONTENT,
                date=PRD_MONDAY,
                school_item=SchoolItemKind.TEST,
                member_name='Michał',
                school_subject='biologia',
            ),
        )
        self.assertEqual(outcome.result.school_subject, 'biologia')
        self.assertEqual(outcome.result.date.weekday(), 0)
        self.assertEqual(outcome.member, self.child)

    def test_prd_request_carries_reference_date_weekday_and_only_allowed_names(self):
        self.run_service([model_output(entry_type='note', content='x')])

        (body,) = self.transport.bodies()
        self.assertIs(body['store'], False)
        self.assertEqual(body['model'], MODEL)
        self.assertEqual(
            self.sent_input(),
            {
                'data_odniesienia': '2026-09-19',
                'dzien_tygodnia': 'sobota',
                'ustawienia_regionalne': 'pl-PL',
                'dozwolone_osoby': ['Ewa', 'Michał', 'Ania'],
                'polecenie': PRD_INSTRUCTION,
            },
        )


class PolishRelativeDateTests(AdapterPathMixin, TestCase):
    CASES = (
        # (instruction, reference date, weekday sent, model answer, expected type)
        (
            'Jutro Ania ma kartkówkę z angielskiego',
            datetime.date(2026, 9, 21),
            'poniedziałek',
            dict(
                entry_type='calendar_event',
                content='Kartkówka z angielskiego',
                date='2026-09-22',
                date_source='Jutro',
                school_item='quiz',
                member_name='Ania',
                school_subject='angielski',
            ),
            EntryType.CALENDAR_EVENT,
        ),
        (
            'Pojutrze o 18:00 zebranie rodziców',
            datetime.date(2026, 9, 23),
            'środa',
            dict(
                entry_type='calendar_event',
                content='Zebranie rodziców',
                date='2026-09-25',
                date_source='Pojutrze',
                time='18:00',
            ),
            EntryType.CALENDAR_EVENT,
        ),
        (
            'W przyszły piątek Michał oddaje zadanie domowe z polskiego',
            datetime.date(2026, 9, 24),
            'czwartek',
            dict(
                entry_type='calendar_event',
                content='Zadanie domowe z polskiego',
                date='2026-10-02',
                date_source='W przyszły piątek',
                school_item='homework',
                member_name='Michał',
                school_subject='polski',
            ),
            EntryType.CALENDAR_EVENT,
        ),
        (
            'W niedzielę kupić prezent dla babci',
            datetime.date(2026, 9, 26),
            'sobota',
            dict(
                entry_type='todo',
                content='Kupić prezent dla babci',
                date='2026-09-27',
                date_source='W niedzielę',
            ),
            EntryType.TODO,
        ),
    )

    def test_reference_date_is_sent_and_returned_date_flows_into_proposal(self):
        for text, reference_date, weekday, answer, entry_type in self.CASES:
            with self.subTest(text):
                outcome = self.run_service(
                    [model_output(**answer)], text=text, reference_date=reference_date
                )

                sent = self.sent_input()
                self.assertEqual(sent['data_odniesienia'], reference_date.isoformat())
                self.assertEqual(sent['dzien_tygodnia'], weekday)
                self.assertEqual(sent['polecenie'], text)
                self.assertIsInstance(outcome.result, ClassificationProposal)
                self.assertEqual(outcome.result.entry_type, entry_type)
                self.assertEqual(
                    outcome.result.date, datetime.date.fromisoformat(answer['date'])
                )


class EntryCategoryTests(AdapterPathMixin, TestCase):
    """Calendar entries, tests/homework, school notes, and general notes."""

    def test_complete_entries_become_proposals(self):
        cases = {
            'calendar event with time': (
                dict(
                    entry_type='calendar_event',
                    content='Wizyta u dentysty',
                    date='2026-09-22',
                    date_source='w poniedziałek',
                    time='16:30',
                ),
                EntryType.CALENDAR_EVENT,
                None,
            ),
            'class test': (
                dict(
                    entry_type='calendar_event',
                    content='Praca klasowa z matematyki',
                    date='2026-09-24',
                    date_source='w poniedziałek',
                    school_item='class_test',
                    member_name='Michał',
                    school_subject='matematyka',
                ),
                EntryType.CALENDAR_EVENT,
                'child',
            ),
            'homework': (
                dict(
                    entry_type='calendar_event',
                    content='Zadanie domowe z przyrody',
                    date='2026-09-23',
                    date_source='w poniedziałek',
                    school_item='homework',
                    member_name='Ania',
                    school_subject='przyroda',
                ),
                EntryType.CALENDAR_EVENT,
                'other_child',
            ),
            'room change': (
                dict(
                    entry_type='note',
                    content='Zmiana sali na 12',
                    date='2026-09-22',
                    date_source='w poniedziałek',
                    school_item='room_change',
                ),
                EntryType.NOTE,
                None,
            ),
            'lucky number': (
                dict(entry_type='note', content='Szczęśliwy numerek 7', school_item='lucky_number'),
                EntryType.NOTE,
                None,
            ),
            'grade': (
                dict(
                    entry_type='note',
                    content='Piątka z historii',
                    school_item='grade',
                    member_name='Michał',
                ),
                EntryType.NOTE,
                'child',
            ),
            'late arrival': (
                dict(entry_type='note', content='Spóźnienie na pierwszą lekcję', school_item='late_arrival'),
                EntryType.NOTE,
                None,
            ),
            'todo without date': (
                dict(entry_type='todo', content='Podpisać zgodę na wycieczkę'),
                EntryType.TODO,
                None,
            ),
        }
        for label, (answer, entry_type, member_attr) in cases.items():
            with self.subTest(label):
                outcome = self.run_service([model_output(**answer)])

                self.assertIsInstance(outcome.result, ClassificationProposal)
                self.assertEqual(outcome.result.entry_type, entry_type)
                self.assertEqual(outcome.result.content, answer['content'])
                expected_member = getattr(self, member_attr) if member_attr else None
                self.assertEqual(outcome.member, expected_member)

    def test_unrecognized_content_becomes_general_note(self):
        text = '  Babcia dzwoniła, że przyjedzie w odwiedziny  '

        outcome = self.run_service([model_output(content='cokolwiek')], text=text)

        self.assertEqual(
            outcome.result,
            ClassificationProposal(entry_type=EntryType.NOTE, content=text.strip()),
        )
        self.assertIsNone(outcome.member)


class MissingFieldFollowUpTests(AdapterPathMixin, TestCase):
    def test_missing_required_fields_become_follow_ups(self):
        cases = {
            'calendar event without date': (
                dict(entry_type='calendar_event', content='Zebranie rodziców'),
                (MissingField.DATE,),
            ),
            'test without date': (
                dict(
                    entry_type='calendar_event',
                    content='Sprawdzian z biologii',
                    school_item='test',
                    member_name='Michał',
                    school_subject='biologia',
                ),
                (MissingField.DATE,),
            ),
            'quiz without member': (
                dict(
                    entry_type='calendar_event',
                    content='Kartkówka z fizyki',
                    date='2026-09-22',
                    date_source='w poniedziałek',
                    school_item='quiz',
                    school_subject='fizyka',
                ),
                (MissingField.AFFECTED_MEMBER,),
            ),
            'test without subject': (
                dict(
                    entry_type='calendar_event',
                    content='Sprawdzian',
                    date='2026-09-22',
                    date_source='w poniedziałek',
                    school_item='test',
                    member_name='Michał',
                ),
                (MissingField.SCHOOL_SUBJECT,),
            ),
            'homework without date, member or subject': (
                dict(entry_type='calendar_event', content='Zadanie domowe', school_item='homework'),
                (MissingField.DATE, MissingField.AFFECTED_MEMBER, MissingField.SCHOOL_SUBJECT),
            ),
            'school test typed as note still needs date, member and subject': (
                dict(entry_type='note', content='Sprawdzian', school_item='test'),
                (MissingField.DATE, MissingField.AFFECTED_MEMBER, MissingField.SCHOOL_SUBJECT),
            ),
            'substitution without date': (
                dict(entry_type='note', content='Zastępstwo z WF', school_item='substitution'),
                (MissingField.DATE,),
            ),
        }
        for label, (answer, missing) in cases.items():
            with self.subTest(label):
                outcome = self.run_service([model_output(**answer)])

                self.assertIsInstance(outcome.result, ClassificationFollowUp)
                self.assertEqual(outcome.result.missing_fields, missing)


    def test_invented_reference_date_becomes_date_follow_up(self):
        # Live gpt-5-nano answered an undated instruction with the reference
        # date; without a verbatim date_source the adapter drops it.
        text = 'Ania ma kartkówkę z matematyki'
        answer = dict(
            entry_type='calendar_event',
            content='Kartkówka z matematyki',
            date=PRD_REFERENCE_DATE.isoformat(),
            school_item='quiz',
            member_name='Ania',
            school_subject='matematyka',
        )
        for date_source in (None, 'w sobotę'):
            with self.subTest(date_source=date_source):
                outcome = self.run_service(
                    [model_output(**answer, date_source=date_source)], text=text
                )

                self.assertIsInstance(outcome.result, ClassificationFollowUp)
                self.assertEqual(outcome.result.missing_fields, (MissingField.DATE,))
                self.assertIsNone(outcome.result.date)
                self.assertEqual(outcome.member, self.other_child)


class AmbiguityAndInventionTests(AdapterPathMixin, TestCase):
    def test_duplicate_names_become_ambiguous_follow_up(self):
        self._member('second-michal', FamilyMember.Role.CHILD, 'Michał')

        outcome = self.run_service(
            [
                model_output(
                    entry_type='calendar_event',
                    content=PRD_CONTENT,
                    date=PRD_MONDAY.isoformat(),
                    date_source='w poniedziałek',
                    school_item='test',
                    member_name='Michał',
                )
            ]
        )

        self.assertEqual(self.sent_input()['dozwolone_osoby'], ['Ewa', 'Michał', 'Ania', 'Michał'])
        self.assertIsInstance(outcome.result, ClassificationFollowUp)
        self.assertIn(MissingField.AMBIGUOUS_MEMBER, outcome.result.missing_fields)
        self.assertIsNone(outcome.result.member_name)
        self.assertIsNone(outcome.member)

    def test_invented_details_are_rejected(self):
        test_event = dict(
            entry_type='calendar_event',
            content=PRD_CONTENT,
            date=PRD_MONDAY.isoformat(),
            date_source='w poniedziałek',
            school_item='test',
        )
        cases = {
            'invented member': (dict(test_event, member_name='Bartek'), UnavailableReason.UNKNOWN_MEMBER),
            'inactive member': (dict(test_event, member_name='Zosia'), UnavailableReason.UNKNOWN_MEMBER),
            'other-family member': (dict(test_event, member_name='Kuba'), UnavailableReason.UNKNOWN_MEMBER),
            'altered spelling': (dict(test_event, member_name='Michal'), UnavailableReason.UNKNOWN_MEMBER),
            'ungrounded details': (
                dict(test_event, member_name='Michał', grounded=False),
                UnavailableReason.UNSUPPORTED_CONTENT,
            ),
            'empty content': (
                dict(test_event, member_name='Michał', content='   '),
                UnavailableReason.EMPTY_CONTENT,
            ),
        }
        for label, (answer, reason) in cases.items():
            with self.subTest(label):
                outcome = self.run_service([model_output(**answer)])

                self.assertEqual(outcome.result, ClassificationUnavailable(reason=reason))
                self.assertIsNone(outcome.member)


class ShortNameTests(AdapterPathMixin, TestCase):
    """PK-01 / US-01: "Hania ma jutro dentystę" in a family with Hanna."""

    INSTRUCTION = 'Hania ma jutro dentystę'
    TOMORROW = datetime.date(2026, 9, 20)

    def setUp(self):
        super().setUp()
        # "Ania" shares the Anna group with "Hania"; keep the corpus family
        # free of that collision so each case picks its own.
        self.other_child.display_name = 'Ola'
        self.other_child.save(update_fields=('display_name',))
        self.hanna = self._member('hanna', FamilyMember.Role.CHILD, 'Hanna')

    def dentist(self, **fields):
        values = dict(
            entry_type='calendar_event',
            content='Dentysta',
            date=self.TOMORROW.isoformat(),
            date_source='jutro',
            member_mention='Hania',
        )
        values.update(fields)
        return model_output(**values)

    def test_short_name_resolves_to_the_family_member(self):
        outcome = self.run_service([self.dentist(member_name=None)], text=self.INSTRUCTION)

        self.assertEqual(self.sent_input()['dozwolone_osoby'], ['Ewa', 'Michał', 'Ola', 'Hanna'])
        self.assertEqual(
            outcome.result,
            ClassificationProposal(
                entry_type=EntryType.CALENDAR_EVENT,
                content='Dentysta',
                date=self.TOMORROW,
                member_name='Hanna',
            ),
        )
        self.assertEqual(outcome.member, self.hanna)

    def test_short_name_fitting_two_members_asks_who_is_meant(self):
        self._member('anna', FamilyMember.Role.CHILD, 'Anna')

        outcome = self.run_service([self.dentist(member_name='Hanna')], text=self.INSTRUCTION)

        self.assertIsInstance(outcome.result, ClassificationFollowUp)
        self.assertEqual(outcome.result.missing_fields, (MissingField.AMBIGUOUS_MEMBER,))
        self.assertIsNone(outcome.result.member_name)
        self.assertEqual(outcome.result.date, self.TOMORROW)
        self.assertIsNone(outcome.member)

    def test_mentions_of_inactive_or_foreign_members_never_resolve(self):
        for returned, mention in (('Zosia', 'Zofia'), ('Kuba', 'Jakub')):
            with self.subTest(mention):
                outcome = self.run_service(
                    [self.dentist(member_name=returned, member_mention=mention)],
                    text=self.INSTRUCTION,
                )

                self.assertEqual(
                    outcome.result,
                    ClassificationUnavailable(reason=UnavailableReason.UNKNOWN_MEMBER),
                )
                self.assertIsNone(outcome.member)


class TitleKeepsActionOnlyTests(AdapterPathMixin, TestCase):
    """PK-20 / US-11: "kasia zrobić pranie w piątek" on Sunday 2026-10-04."""

    INSTRUCTION = 'kasia zrobić pranie w piątek'
    SUNDAY = datetime.date(2026, 10, 4)
    FRIDAY = datetime.date(2026, 10, 9)

    def setUp(self):
        super().setUp()
        self.kasia = self._member('kasia', FamilyMember.Role.CHILD, 'Kasia')

    def laundry(self, **fields):
        values = dict(
            entry_type='todo',
            content='Zrobić pranie',
            date=self.FRIDAY.isoformat(),
            date_source='w piątek',
            member_name='Kasia',
            member_mention='Kasia',
        )
        values.update(fields)
        return model_output(**values)

    def classify(self, answer, text=INSTRUCTION):
        return self.run_service([answer], text=text, reference_date=self.SUNDAY)

    def test_owner_example_keeps_only_the_action_for_clean_and_echoing_output(self):
        for content in (
            'Zrobić pranie',
            'zrobić pranie',
            'Kasia zrobić pranie w piątek',
            'kasia, zrobić pranie w piątek',
        ):
            with self.subTest(content=content):
                outcome = self.classify(self.laundry(content=content))

                self.assertEqual(self.sent_input()['dzien_tygodnia'], 'niedziela')
                self.assertEqual(
                    outcome.result,
                    ClassificationProposal(
                        entry_type=EntryType.TODO,
                        content='Zrobić pranie',
                        date=self.FRIDAY,
                        member_name='Kasia',
                    ),
                )
                self.assertEqual(outcome.member, self.kasia)

    def test_ungrounded_date_phrase_stays_in_the_title_and_todo_asks_no_date(self):
        cases = (
            # Evidence that is not in the parent's text.
            (self.INSTRUCTION, 'w sobotę'),
            # Evidence echoed in the title but absent from the parent's text.
            ('kasia zrobić pranie', 'w piątek'),
        )
        for text, date_source in cases:
            with self.subTest(text=text, date_source=date_source):
                outcome = self.classify(
                    self.laundry(
                        content='Kasia zrobić pranie w piątek', date_source=date_source
                    ),
                    text=text,
                )

                self.assertEqual(
                    outcome.result,
                    ClassificationProposal(
                        entry_type=EntryType.TODO,
                        content='Zrobić pranie w piątek',
                        member_name='Kasia',
                    ),
                )
                self.assertEqual(outcome.member, self.kasia)

    def test_unmatched_leading_name_is_not_stripped(self):
        text = 'Bartek odebrać paczkę'

        outcome = self.classify(
            self.laundry(
                content=text,
                date=None,
                date_source=None,
                member_name=None,
                member_mention='Bartek',
            ),
            text=text,
        )

        self.assertEqual(
            outcome.result,
            ClassificationProposal(entry_type=EntryType.TODO, content=text),
        )
        self.assertIsNone(outcome.member)

    def test_school_title_keeps_its_subject(self):
        outcome = self.classify(
            self.laundry(
                entry_type='calendar_event',
                content='Kartkówka z matematyki w piątek',
                school_item='quiz',
                school_subject='matematyka',
            ),
            text='Kartkówka z matematyki dla Kasi w piątek',
        )

        self.assertEqual(
            outcome.result,
            ClassificationProposal(
                entry_type=EntryType.CALENDAR_EVENT,
                content='Kartkówka z matematyki',
                date=self.FRIDAY,
                school_item=SchoolItemKind.QUIZ,
                member_name='Kasia',
                school_subject='matematyka',
            ),
        )
        self.assertEqual(outcome.member, self.kasia)


class FreeTextCorrectionTests(AdapterPathMixin, TestCase):
    """PK-10 / US-10: a correction changes only the field it names."""

    def correct(self, answer, current=MEETING, correction=CORRECTION_TEXT):
        self.clock = FakeClock()
        self.transport = ScriptedTransport(self.clock, [answer])
        backend = OpenAIClassificationBackend(
            client=make_client(self.transport),
            model=MODEL,
            clock=self.clock,
            sleep=self.clock.sleep,
        )
        return correct_proposal_for_parent(
            self.parent.user,
            current,
            correction,
            reference_date=PRD_REFERENCE_DATE,
            locale='pl-PL',
            backend=backend,
        )

    def meeting_answer(self, **fields):
        values = dict(
            entry_type='calendar_event',
            content='Spotkanie z wychowawczynią',
            date=CORRECTED_DATE.isoformat(),
            date_source='15 października',
            time='17:00',
            changed_fields=['date'],
        )
        values.update(fields)
        return model_output(**values)

    def test_date_correction_flows_into_the_merged_proposal(self):
        correction = self.correct(self.meeting_answer())

        self.assertEqual(
            self.sent_input(),
            {
                'data_odniesienia': '2026-09-19',
                'dzien_tygodnia': 'sobota',
                'ustawienia_regionalne': 'pl-PL',
                'dozwolone_osoby': ['Ewa', 'Michał', 'Ania'],
                'obecna_propozycja': {
                    'typ': 'calendar_event',
                    'tytul': 'Spotkanie z wychowawczynią',
                    'element_szkolny': None,
                    'przedmiot': None,
                    'data': '2026-09-25',
                    'godzina': '17:00',
                    'osoba': None,
                },
                'poprawka': CORRECTION_TEXT,
            },
        )
        self.assertTrue(correction.applied)
        self.assertEqual(correction.changed, frozenset({'date'}))
        self.assertEqual(
            correction.outcome.result,
            ClassificationProposal(
                entry_type=EntryType.CALENDAR_EVENT,
                content='Spotkanie z wychowawczynią',
                date=CORRECTED_DATE,
                time=datetime.time(17, 0),
            ),
        )

    def test_echoed_or_rewritten_fields_outside_changed_fields_are_ignored(self):
        correction = self.correct(
            self.meeting_answer(content='Spotkanie 15 października', time='18:00')
        )

        self.assertEqual(correction.outcome.result.content, 'Spotkanie z wychowawczynią')
        self.assertEqual(correction.outcome.result.time, datetime.time(17, 0))
        self.assertEqual(correction.outcome.result.date, CORRECTED_DATE)

    def test_date_not_grounded_in_the_correction_is_not_applied(self):
        correction = self.correct(self.meeting_answer(date_source='w piątek'))

        self.assertFalse(correction.applied)
        self.assertIsNone(correction.outcome)


class ProviderFailureTests(AdapterPathMixin, TestCase):
    def test_provider_failures_become_safe_unavailable_results(self):
        cases = {
            'refusal': ([ok(response_body(refusal='Nie mogę pomóc.'))], UnavailableReason.REFUSED),
            'malformed': ([ok(response_body('{"content": "x"'))], UnavailableReason.MALFORMED_OUTPUT),
            'incomplete': (
                [ok(response_body(status='incomplete', incomplete_reason='max_output_tokens'))],
                UnavailableReason.INCOMPLETE_OUTPUT,
            ),
            'timeout twice': ([(10.0, TIMEOUT), (10.0, TIMEOUT)], UnavailableReason.TIMEOUT),
            'rate limit twice': ([status_error(429), status_error(429)], UnavailableReason.RATE_LIMITED),
            'authentication': ([status_error(401)], UnavailableReason.PROVIDER_ERROR),
        }
        for label, (steps, reason) in cases.items():
            with self.subTest(label):
                outcome = self.run_service(steps)

                self.assertEqual(outcome.result, ClassificationUnavailable(reason=reason))
                self.assertIsNone(outcome.member)


class VirtualLatencyClock:
    """Real ``time.monotonic`` plus simulated provider latency.

    ``ScriptedTransport`` advances ``now`` to simulate a slow provider, and
    ``sleep`` advances it instead of sleeping, so the adapter's deadline math
    runs against the real monotonic clock without real waiting.
    """

    def __init__(self):
        self.offset = 0.0
        self.sleeps = []

    def __call__(self):
        return time.monotonic() + self.offset

    @property
    def now(self):
        return self()

    @now.setter
    def now(self, value):
        self.offset += value - self()

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.offset += seconds


class TimeoutHonoringTransport(ScriptedTransport):
    """A provider that is cut off at the per-attempt read timeout, like httpx."""

    def __call__(self, request):
        step = self.steps[0]
        if not isinstance(step[0], str):
            duration, outcome = step
            read_timeout = request.extensions['timeout']['read']
            if duration > read_timeout:
                self.steps[0] = (read_timeout, TIMEOUT)
        return super().__call__(request)


@override_settings(**FULL_SETTINGS)
class WallClockDeadlineTests(FamilyFixtureMixin, TestCase):
    """Every outcome returns inside the 25-second deadline, with no real sleeps."""

    SCENARIOS = {
        'success': [(2.0, ok())],
        'timeout then success': [(10.0, TIMEOUT), (9.0, ok())],
        'provider hangs twice': [(60.0, ok()), (60.0, ok())],
        'timeout exhaustion': [(10.0, TIMEOUT), (10.0, TIMEOUT)],
        'rate limit': [(1.0, status_error(429)), (1.0, status_error(429))],
        'connection error': [(9.0, CONNECTION), (9.0, CONNECTION)],
        '5xx': [(3.0, status_error(500)), (3.0, status_error(503))],
        'slow 5xx then provider hangs': [(9.5, status_error(500)), (30.0, ok())],
        'refusal': [(4.0, ok(response_body(refusal='Nie mogę pomóc.')))],
        'malformed': [(4.0, ok(response_body('nie json')))],
        'non-retryable 4xx': [(1.0, status_error(400))],
    }

    def test_every_outcome_returns_within_deadline_without_real_sleeps(self):
        real_started = time.monotonic()
        for label, steps in self.SCENARIOS.items():
            with self.subTest(label):
                clock = VirtualLatencyClock()
                transport = TimeoutHonoringTransport(clock, steps)
                # Built from the production settings, so the configured
                # deadline, attempt timeout, and retry policy are what is timed.
                backend = build_openai_backend(
                    client=make_client(transport), clock=clock, sleep=clock.sleep
                )
                started = clock()
                wall_started = time.monotonic()

                outcome = classify_for_parent(
                    self.parent.user,
                    PRD_INSTRUCTION,
                    reference_date=PRD_REFERENCE_DATE,
                    backend=backend,
                )

                simulated = clock() - started
                self.assertIn(outcome.result.kind, {'proposal', 'follow_up', 'unavailable'})
                self.assertLessEqual(simulated, DEADLINE_SECONDS)
                self.assertLess(time.monotonic() - wall_started, DEADLINE_SECONDS)
                # Backoff is simulated: at most one 0.5 s retry delay, never slept.
                self.assertLessEqual(sum(clock.sleeps), 0.5)
        # The whole corpus runs in real time far below one deadline.
        self.assertLess(time.monotonic() - real_started, 5.0)


@unittest.skipUnless(
    os.getenv('CLASSIFICATION_LIVE_EVAL') == '1',
    'Live provider evaluation is opt-in: set CLASSIFICATION_LIVE_EVAL=1 with '
    'classification enabled, a key, and a model.',
)
class LiveProviderEvaluationTests(FamilyFixtureMixin, TestCase):
    """Opt-in, nondeterministic evaluation with synthetic data only."""

    def classify_live(self, text):
        started = time.monotonic()
        outcome = classify_for_parent(
            self.parent.user, text, reference_date=PRD_REFERENCE_DATE, locale='pl-PL'
        )
        elapsed = time.monotonic() - started
        self.assertNotEqual(
            getattr(outcome.result, 'reason', None),
            UnavailableReason.DISABLED,
            'Classification is not fully configured for live evaluation.',
        )
        self.assertLess(elapsed, PRD_BUDGET_SECONDS)
        return outcome

    def test_prd_example(self):
        outcome = self.classify_live(PRD_INSTRUCTION)

        self.assertIsInstance(outcome.result, ClassificationProposal)
        self.assertEqual(outcome.result.date, PRD_MONDAY)
        self.assertEqual(outcome.member, self.child)

    def test_missing_date_asks_follow_up(self):
        outcome = self.classify_live('Michał ma sprawdzian z matematyki')

        self.assertIsInstance(outcome.result, ClassificationFollowUp)
        self.assertIn(MissingField.DATE, outcome.result.missing_fields)

    def test_invented_member_is_not_resolved(self):
        outcome = self.classify_live('Bartek ma kartkówkę z chemii we wtorek')

        self.assertIsNone(outcome.member)

    def correct_live(self, correction, current=MEETING, current_member=None):
        started = time.monotonic()
        result = correct_proposal_for_parent(
            self.parent.user,
            current,
            correction,
            reference_date=PRD_REFERENCE_DATE,
            current_member=current_member,
            locale='pl-PL',
        )
        self.assertLess(time.monotonic() - started, PRD_BUDGET_SECONDS)
        self.assertTrue(result.applied, result.rejection)
        return result

    def test_date_correction_changes_only_the_date(self):
        correction = self.correct_live(CORRECTION_TEXT)

        self.assertEqual(correction.changed, frozenset({'date'}))
        self.assertEqual(
            correction.outcome.result,
            ClassificationProposal(
                entry_type=EntryType.CALENDAR_EVENT,
                content='Spotkanie z wychowawczynią',
                date=CORRECTED_DATE,
                time=datetime.time(17, 0),
            ),
        )

    def test_member_correction_changes_only_the_person(self):
        tymek = self._member('tymek', FamilyMember.Role.CHILD, 'Tymoteusz')

        correction = self.correct_live('to dla Tymka')

        self.assertEqual(correction.changed, frozenset({'member_name'}))
        self.assertEqual(correction.outcome.member, tymek)
        self.assertEqual(correction.outcome.result.date, MEETING.date)
        self.assertEqual(correction.outcome.result.time, MEETING.time)
        self.assertEqual(correction.outcome.result.content, MEETING.content)


class SmokeCommandTests(SimpleTestCase):
    """The operator smoke check reports only safe fields and its timing."""

    SENTINEL = 'SMOKE-SENTINEL-3fa91c'

    def run_command(self, backend_or_error, *, elapsed=1.2):
        ticks = iter((100.0, 100.0 + elapsed))
        build = mock.Mock()
        if isinstance(backend_or_error, Exception):
            build.side_effect = backend_or_error
        else:
            build.return_value = backend_or_error
        stdout = io.StringIO()
        with mock.patch.object(classification_smoke, 'build_openai_backend', build), \
                mock.patch.object(classification_smoke, 'clock', lambda: next(ticks)):
            try:
                call_command('classification_smoke', sentinel=self.SENTINEL, stdout=stdout)
            finally:
                self.output = stdout.getvalue()

    def test_proposal_reports_safe_fields_only(self):
        backend = mock.Mock()
        backend.classify.return_value = BackendOutput(
            entry_type=EntryType.CALENDAR_EVENT,
            content=f'Sprawdzian {self.SENTINEL}',
            grounded=True,
            date=PRD_MONDAY,
            school_item=SchoolItemKind.TEST,
            member_name='Michał',
        )

        self.run_command(backend)

        (request,) = backend.classify.call_args.args
        self.assertIn(self.SENTINEL, request.submitted_text)
        self.assertEqual(request.locale, 'pl-PL')
        self.assertIn('outcome=proposal', self.output)
        self.assertIn('date=2026-09-21', self.output)
        self.assertIn('member_resolved=yes', self.output)
        self.assertIn('elapsed_ms=1200', self.output)
        for sensitive in (self.SENTINEL, 'Michał', 'Sprawdzian', 'skórze'):
            self.assertNotIn(sensitive, self.output)

    def test_safe_failure_within_budget_succeeds(self):
        backend = mock.Mock()
        backend.classify.side_effect = ClassificationBackendError(UnavailableReason.TIMEOUT)

        self.run_command(backend, elapsed=20.5)

        self.assertIn('outcome=unavailable reason=timeout', self.output)

    def test_disabled_configuration_fails(self):
        with self.assertRaises(CommandError):
            self.run_command(ClassificationBackendError(UnavailableReason.DISABLED))

        self.assertIn('reason=disabled', self.output)

    def test_over_budget_fails(self):
        backend = mock.Mock()
        backend.classify.return_value = BackendOutput(
            entry_type=EntryType.NOTE, content='x', grounded=True
        )

        with self.assertRaises(CommandError):
            self.run_command(backend, elapsed=31.0)

    def test_invalid_sentinel_is_rejected(self):
        with self.assertRaises(CommandError):
            call_command('classification_smoke', sentinel='short', stdout=io.StringIO())


class RepositoryHygieneTests(SimpleTestCase):
    """No real provider key, family-text fixture, or provider payload is committed.

    Scans tracked files plus untracked files that are not ignored (i.e. files
    that could be committed next). Ignored local files such as ``.env`` are
    deliberately excluded.
    """

    # Real OpenAI keys are long; test sentinels are marked with SENTINEL.
    KEY_PATTERN = re.compile(r'(?<![A-Za-z0-9_-])sk-[A-Za-z0-9_-]{20,}')
    # Env-style assignments in docs/config; Python sources read it from settings.
    ASSIGNED_KEY_PATTERN = re.compile(r'^[ \t]*OPENAI_API_KEY[ \t]*=[ \t]*(\S+)', re.MULTILINE)
    # Written with a character class so this source file does not match itself.
    PAYLOAD_PATTERN = re.compile(r'"object"\s*:\s*"respons[e]"')
    FIXTURE_SUFFIXES = {'.json', '.jsonl', '.ndjson', '.har', '.yaml', '.yml'}
    FIXTURE_DIRECTORIES = {'fixtures', 'cassettes', 'recordings'}
    FORBIDDEN_TRACKED = {'.env', 'db.sqlite3'}

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        root = Path(settings.BASE_DIR)
        if shutil.which('git') is None:
            raise unittest.SkipTest('git is not available')
        listing = subprocess.run(
            ['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'],
            cwd=root,
            capture_output=True,
            check=False,
        )
        if listing.returncode != 0:
            raise unittest.SkipTest('not a git work tree')
        tracked = subprocess.run(
            ['git', 'ls-files', '-z', '--cached'], cwd=root, capture_output=True, check=True
        )
        cls.root = root
        cls.paths = sorted({p for p in listing.stdout.decode().split('\0') if p})
        cls.tracked = {p for p in tracked.stdout.decode().split('\0') if p}

    def contents(self):
        for relative in self.paths:
            path = self.root / relative
            if path.is_file():
                yield relative, path.read_bytes().decode('utf-8', errors='ignore')

    def test_no_provider_key_is_committed(self):
        findings = []
        for relative, text in self.contents():
            for match in self.KEY_PATTERN.finditer(text):
                if 'SENTINEL' not in match.group(0):
                    findings.append(relative)
            if relative.endswith('.py'):
                continue
            for match in self.ASSIGNED_KEY_PATTERN.finditer(text):
                value = match.group(1)
                if not (value.startswith('<') and value.endswith('>')):
                    findings.append(relative)
        # Only paths are reported, never the matched value.
        self.assertEqual(sorted(set(findings)), [])

    def test_no_payload_or_family_text_fixtures_are_committed(self):
        # Harness configuration is not a captured family/provider fixture.
        # contents() still scans these files for payloads and provider keys.
        hook_configs = {'.codex/hooks.json', '.claude/settings.json'}
        fixture_files = [
            relative
            for relative in self.paths
            if (Path(relative).suffix.lower() in self.FIXTURE_SUFFIXES
                and relative not in hook_configs)
            or self.FIXTURE_DIRECTORIES & set(Path(relative).parts)
        ]
        payloads = [
            relative for relative, text in self.contents() if self.PAYLOAD_PATTERN.search(text)
        ]

        self.assertEqual(fixture_files, [])
        self.assertEqual(payloads, [])

    def test_local_secrets_and_database_are_not_tracked(self):
        self.assertIn('entries/classification/openai_backend.py', self.paths)
        self.assertEqual(self.FORBIDDEN_TRACKED & self.tracked, set())

    def test_key_scanner_detects_a_key_shaped_value(self):
        fake_key = 'sk-' + 'proj-' + 'A1b2' * 10

        self.assertIsNotNone(self.KEY_PATTERN.search(f'key = "{fake_key}"'))
        self.assertIsNone(self.KEY_PATTERN.search('flask-sqlalchemy-extension-package'))
