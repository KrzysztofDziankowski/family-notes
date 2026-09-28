"""Fixed EduVulcan rules: proposals, dates, child matching, and malformed input.

``CORPUS`` mirrors the category, punctuation, date, and multi-change shapes of
real forwarded notifications. Every child, teacher, school, and identifier in
it is invented; no real notification value is stored here.
"""

import datetime
import unicodedata

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from entries.classification.types import EntryType, SchoolItemKind
from entries.eduvulcan.children import (
    match_child,
    normalize_child_name,
    snapshot_active_children,
)
from entries.eduvulcan.rules import (
    general_note_proposal,
    general_note_text,
    propose_entries,
    reference_date_for,
)
from entries.eduvulcan.text import normalize_text, resolve_yearless_date
from entries.eduvulcan.types import ChildSnapshot, EntryProposal, OutputKind
from family_access.models import Family, FamilyMember

CAPTURED = datetime.date(2026, 9, 23)
LUCJA = ChildSnapshot(pk=11, display_name='Łucja')
BARTOSZ = ChildSnapshot(pk=12, display_name='Bartosz')
ZUZANNA = ChildSnapshot(pk=13, display_name='Zuzanna')
CHILDREN = (LUCJA, BARTOSZ, ZUZANNA)

# (title, message, captured day) in the shapes the phone automation forwards.
CORPUS = {
    'test': ('Sprawdzian', '7 października, Biologia (biologia), Zuzanna', CAPTURED),
    'quiz': ('Kartkówka', '30 września, Matematyka (matematyka), Zuzanna', CAPTURED),
    'class_test': ('Praca klasowa', '6 października, Fizyka (fizyka), Bartosz', CAPTURED),
    'homework': (
        'Zadanie domowe',
        'Zadanie domowe 25 września, Matematyka (matematyka), Łucja',
        CAPTURED,
    ),
    'grade': ('Ocena', 'Nowa ocena: 4+, Matematyka, Łucja', CAPTURED),
    'lucky_number': (
        'Szczęśliwy numerek',
        'W dniu 24 września szczęśliwy numer to: 7, Bartosz',
        datetime.date(2026, 9, 24),
    ),
    'late_arrival': (
        'Frekwencja',
        'Spóźnienie na 2. lekcji, Łucja, w dniu 25 września',
        datetime.date(2026, 9, 25),
    ),
    'teacher_message': (
        'Nowa wiadomość',
        '23 września od Lipińska Grażyna [LG] - P - (SP 99): konkurs',
        CAPTURED,
    ),
    'teacher_message_quoted': (
        'Nowa wiadomość',
        '23 września od Zawadzki Olaf [ZO] - P - (SP 99): „Rowerem do szkoły”',
        CAPTURED,
    ),
    'teacher_message_punctuated': (
        'Nowa wiadomość',
        '24 września od Kowalczyk Irena [Ki] - P - (SP 99): WAŻNE! Składka na '
        'wycieczkę z pieniędzy klasowych.',
        datetime.date(2026, 9, 24),
    ),
    'substitution': (
        'Zmiana planu dla Łucja',
        'Zastępstwo w dniu 25 września na lekcji Język angielski, Zawadzki Olaf (5B)',
        CAPTURED,
    ),
    'teacher_absence': (
        'Zmiana planu dla Bartosz',
        'Nieobecność nauczyciela w dniu 24 września, Kowalczyk Irena (7B)',
        CAPTURED,
    ),
    'support_teacher_absence': (
        'Zmiana planu dla Bartosz',
        'Nieobecność nauczyciela wspomagającego w dniu 30 września, Wróbel-Nowicka Ewelina (7B)',
        datetime.date(2026, 9, 25),
    ),
    'multi_change': (
        'Zmiana planu dla Łucja',
        'Zmieniono salę w dniu 30 września na lekcji Technika, Zawadzki Olaf (5B) '
        'Zastępstwo w dniu 30 września na lekcji Technika, Zawadzki Olaf (5B)',
        datetime.date(2026, 9, 25),
    ),
}


def propose(key=None, *, title=None, message=None, captured=CAPTURED, children=CHILDREN):
    if key is not None:
        title, message, captured = CORPUS[key]
    return propose_entries(title, message, captured_at=captured, children=children)


def only(proposals):
    (proposal,) = proposals
    return proposal


class CategoryRuleTests(SimpleTestCase):
    def test_prd_shaped_test_becomes_dated_calendar_event_for_child(self):
        # Same shape as the PRD US-02 example, with an invented child name.
        proposal = only(
            propose(
                title='Sprawdzian',
                message='2 października, Język angielski (j. angielski), Łucja',
            )
        )

        self.assertEqual(proposal.output_index, 0)
        self.assertEqual(proposal.kind, OutputKind.RULE)
        self.assertEqual(proposal.entry_type, EntryType.CALENDAR_EVENT)
        self.assertEqual(proposal.content, 'Sprawdzian: Język angielski')
        self.assertEqual(proposal.date, datetime.date(2026, 10, 2))
        self.assertIsNone(proposal.time)
        self.assertEqual(proposal.school_item, SchoolItemKind.TEST)
        self.assertEqual(proposal.member, LUCJA)
        self.assertEqual(proposal.assigned_member_id, LUCJA.pk)

    def test_calendar_categories(self):
        expected = {
            'test': ('Sprawdzian: Biologia', datetime.date(2026, 10, 7), SchoolItemKind.TEST, ZUZANNA),
            'quiz': ('Kartkówka: Matematyka', datetime.date(2026, 9, 30), SchoolItemKind.QUIZ, ZUZANNA),
            'class_test': (
                'Praca klasowa: Fizyka', datetime.date(2026, 10, 6), SchoolItemKind.CLASS_TEST, BARTOSZ,
            ),
            'homework': (
                'Zadanie domowe: Matematyka', datetime.date(2026, 9, 25), SchoolItemKind.HOMEWORK, LUCJA,
            ),
        }
        for key, (content, date, school_item, member) in expected.items():
            with self.subTest(key):
                proposal = only(propose(key))

                self.assertEqual(proposal.entry_type, EntryType.CALENDAR_EVENT)
                self.assertEqual(proposal.content, content)
                self.assertEqual(proposal.date, date)
                self.assertEqual(proposal.school_item, school_item)
                self.assertEqual(proposal.member, member)

    def test_child_note_categories(self):
        expected = {
            'grade': ('Ocena: 4+, Matematyka', None, SchoolItemKind.GRADE, LUCJA),
            'lucky_number': (
                'Szczęśliwy numerek: 7', datetime.date(2026, 9, 24), SchoolItemKind.LUCKY_NUMBER, BARTOSZ,
            ),
            'late_arrival': (
                'Spóźnienie na 2. lekcji', datetime.date(2026, 9, 25), SchoolItemKind.LATE_ARRIVAL, LUCJA,
            ),
        }
        for key, (content, date, school_item, member) in expected.items():
            with self.subTest(key):
                proposal = only(propose(key))

                self.assertEqual(proposal.entry_type, EntryType.NOTE)
                self.assertEqual(proposal.content, content)
                self.assertEqual(proposal.date, date)
                self.assertEqual(proposal.school_item, school_item)
                self.assertEqual(proposal.member, member)

    def test_other_attendance_event_is_a_child_note_without_school_kind(self):
        proposal = only(
            propose(
                title='Frekwencja',
                message='Nieobecność na 3. lekcji, Bartosz, w dniu 25 września',
            )
        )

        self.assertEqual(proposal.entry_type, EntryType.NOTE)
        self.assertEqual(proposal.content, 'Nieobecność na 3. lekcji')
        self.assertIsNone(proposal.school_item)
        self.assertEqual(proposal.member, BARTOSZ)

    def test_teacher_messages_are_unassigned_family_notes_dated_by_message(self):
        expected = {
            'teacher_message': (
                'Wiadomość od Lipińska Grażyna [LG] - P - (SP 99): konkurs',
                datetime.date(2026, 9, 23),
            ),
            'teacher_message_quoted': (
                'Wiadomość od Zawadzki Olaf [ZO] - P - (SP 99): „Rowerem do szkoły”',
                datetime.date(2026, 9, 23),
            ),
            'teacher_message_punctuated': (
                'Wiadomość od Kowalczyk Irena [Ki] - P - (SP 99): WAŻNE! Składka na '
                'wycieczkę z pieniędzy klasowych.',
                datetime.date(2026, 9, 24),
            ),
        }
        for key, (content, date) in expected.items():
            with self.subTest(key):
                proposal = only(propose(key))

                self.assertEqual(proposal.entry_type, EntryType.NOTE)
                self.assertEqual(proposal.content, content)
                self.assertEqual(proposal.date, date)
                self.assertIsNone(proposal.school_item)
                self.assertIsNone(proposal.member)

    def test_single_timetable_changes_are_dated_child_notes(self):
        expected = {
            'substitution': (
                'Zastępstwo: Język angielski, Zawadzki Olaf (5B)',
                datetime.date(2026, 9, 25),
                SchoolItemKind.SUBSTITUTION,
                LUCJA,
            ),
            'teacher_absence': (
                'Nieobecność nauczyciela: Kowalczyk Irena (7B)',
                datetime.date(2026, 9, 24),
                None,
                BARTOSZ,
            ),
            'support_teacher_absence': (
                'Nieobecność nauczyciela wspomagającego: Wróbel-Nowicka Ewelina (7B)',
                datetime.date(2026, 9, 30),
                None,
                BARTOSZ,
            ),
        }
        for key, (content, date, school_item, member) in expected.items():
            with self.subTest(key):
                proposal = only(propose(key))

                self.assertEqual(proposal.kind, OutputKind.RULE)
                self.assertEqual(proposal.entry_type, EntryType.NOTE)
                self.assertEqual(proposal.content, content)
                self.assertEqual(proposal.date, date)
                self.assertEqual(proposal.school_item, school_item)
                self.assertEqual(proposal.member, member)

    def test_every_corpus_shape_is_interpreted_by_a_rule(self):
        for key in CORPUS:
            with self.subTest(key):
                proposals = propose(key)

                self.assertIsNotNone(proposals)
                self.assertTrue(all(isinstance(p, EntryProposal) for p in proposals))
                self.assertEqual(
                    [p.output_index for p in proposals], list(range(len(proposals)))
                )

    def test_rules_are_deterministic(self):
        for key in CORPUS:
            with self.subTest(key):
                self.assertEqual(propose(key), propose(key))


class MultiChangeTests(SimpleTestCase):
    def test_each_valid_change_becomes_an_ordered_child_note(self):
        proposals = propose('multi_change')

        self.assertEqual([p.output_index for p in proposals], [0, 1])
        self.assertEqual(
            [p.content for p in proposals],
            [
                'Zmiana sali: Technika, Zawadzki Olaf (5B)',
                'Zastępstwo: Technika, Zawadzki Olaf (5B)',
            ],
        )
        self.assertEqual(
            [p.school_item for p in proposals],
            [SchoolItemKind.ROOM_CHANGE, SchoolItemKind.SUBSTITUTION],
        )
        for proposal in proposals:
            self.assertEqual(proposal.date, datetime.date(2026, 9, 30))
            self.assertEqual(proposal.member, LUCJA)
            self.assertEqual(proposal.entry_type, EntryType.NOTE)

    def test_malformed_content_becomes_one_trailing_unassigned_note(self):
        message = (
            'Uwaga: zmiana organizacji dnia '
            'Zastępstwo w dniu 30 września na lekcji Technika, Zawadzki Olaf (5B) '
            'Zastępstwo w dniu 31 września na lekcji Muzyka, Kowalczyk Irena (5B) '
            'Zmieniono salę w dniu 1 października, Kowalczyk Irena (5B) '
            'Nieobecność nauczyciela w dniu 2 października, Lipińska Grażyna (5B)'
        )

        proposals = propose(title='Zmiana planu dla Łucja', message=message)

        self.assertEqual([p.output_index for p in proposals], [0, 1, 2])
        valid, absence, remainder = proposals
        self.assertEqual(valid.content, 'Zastępstwo: Technika, Zawadzki Olaf (5B)')
        self.assertEqual(valid.date, datetime.date(2026, 9, 30))
        self.assertEqual(absence.content, 'Nieobecność nauczyciela: Lipińska Grażyna (5B)')
        self.assertEqual(absence.date, datetime.date(2026, 10, 2))
        for proposal in (valid, absence):
            self.assertEqual(proposal.kind, OutputKind.RULE)
            self.assertEqual(proposal.member, LUCJA)

        self.assertEqual(remainder.kind, OutputKind.RULE_REMAINDER)
        self.assertEqual(remainder.entry_type, EntryType.NOTE)
        self.assertIsNone(remainder.member)
        self.assertIsNone(remainder.date)
        self.assertIsNone(remainder.school_item)
        self.assertEqual(
            remainder.content,
            'Zmiana planu dla Łucja: Uwaga: zmiana organizacji dnia '
            'Zastępstwo w dniu 31 września na lekcji Muzyka, Kowalczyk Irena (5B) '
            'Zmieniono salę w dniu 1 października, Kowalczyk Irena (5B)',
        )

    def test_wholly_malformed_timetable_is_left_to_fallback(self):
        for message in (
            'Plan lekcji został zmieniony',
            'Zastępstwo w dniu 31 września na lekcji Muzyka, Kowalczyk Irena (5B)',
            'Zastępstwo w dniu 30 września',
        ):
            with self.subTest(message=message):
                self.assertIsNone(propose(title='Zmiana planu dla Łucja', message=message))

    def test_changes_for_unknown_child_stay_ordered_and_unassigned(self):
        title, message, captured = CORPUS['multi_change']

        proposals = propose(
            title='Zmiana planu dla Kacper', message=message, captured=captured
        )

        self.assertEqual([p.output_index for p in proposals], [0, 1])
        for proposal in proposals:
            self.assertIsNone(proposal.member)
            self.assertTrue(proposal.content.endswith(' — Kacper'))
            self.assertIsNotNone(proposal.school_item)


class NormalizationTests(SimpleTestCase):
    def test_decomposed_unicode_and_irregular_whitespace_match_rules(self):
        title = unicodedata.normalize('NFD', ' Kartkówka ')
        message = unicodedata.normalize(
            'NFD', '30 września,  Matematyka (matematyka), Łucja​\n'
        )

        proposal = only(propose(title=title, message=message))

        self.assertEqual(proposal.content, 'Kartkówka: Matematyka')
        self.assertEqual(unicodedata.normalize('NFC', proposal.content), proposal.content)
        self.assertEqual(proposal.school_item, SchoolItemKind.QUIZ)
        self.assertEqual(proposal.member, LUCJA)

    def test_category_titles_ignore_case(self):
        proposal = only(
            propose(title='PRACA KLASOWA', message='6 października, Fizyka (fizyka), Bartosz')
        )

        self.assertEqual(proposal.content, 'Praca klasowa: Fizyka')

    def test_normalize_text_preserves_polish_letters_case_and_punctuation(self):
        self.assertEqual(
            normalize_text('  Zażółć\tgęślą  JAŹŃ: „cytat”!​ '),
            'Zażółć gęślą JAŹŃ: „cytat”!',
        )

    def test_general_note_text_joins_normalized_title_and_message(self):
        self.assertEqual(
            general_note_text(' Nieznana  kategoria ', 'Treść powiadomienia '),
            'Nieznana kategoria: Treść powiadomienia',
        )
        proposal = general_note_proposal('Nieznana kategoria', 'Treść', output_index=0)
        self.assertEqual(proposal.kind, OutputKind.GENERAL_NOTE)
        self.assertEqual(proposal.entry_type, EntryType.NOTE)
        self.assertIsNone(proposal.member)
        self.assertIsNone(proposal.date)


class YearInferenceTests(SimpleTestCase):
    def test_nearest_year_is_chosen_around_the_new_year(self):
        cases = [
            (datetime.date(2026, 12, 20), 5, 'stycznia', datetime.date(2027, 1, 5)),
            (datetime.date(2027, 1, 10), 20, 'grudnia', datetime.date(2026, 12, 20)),
            (datetime.date(2026, 9, 23), 2, 'października', datetime.date(2026, 10, 2)),
            (datetime.date(2026, 9, 25), 21, 'września', datetime.date(2026, 9, 21)),
        ]
        for reference, day, month, expected in cases:
            with self.subTest(reference=reference, day=day, month=month):
                self.assertEqual(resolve_yearless_date(day, month, reference), expected)

    def test_six_month_window_boundaries(self):
        reference = datetime.date(2026, 1, 1)

        self.assertEqual(
            resolve_yearless_date(1, 'lipca', reference), datetime.date(2026, 7, 1)
        )
        # 2 July 2026 is one day past the window, so the earlier one wins.
        self.assertEqual(
            resolve_yearless_date(2, 'lipca', reference), datetime.date(2025, 7, 2)
        )
        self.assertEqual(
            resolve_yearless_date(1, 'lipca', datetime.date(2026, 12, 31)),
            datetime.date(2026, 7, 1),
        )

    def test_exact_tie_prefers_the_later_date(self):
        # 1 April 2027 and 1 April 2028 are both 183 days from 1 October 2027
        # (the later span crosses 29 February) and both lie inside the window.
        self.assertEqual(
            resolve_yearless_date(1, 'kwietnia', datetime.date(2027, 10, 1)),
            datetime.date(2028, 4, 1),
        )

    def test_leap_day_resolves_only_to_an_existing_date(self):
        self.assertEqual(
            resolve_yearless_date(29, 'lutego', datetime.date(2027, 9, 1)),
            datetime.date(2028, 2, 29),
        )
        self.assertIsNone(resolve_yearless_date(29, 'lutego', datetime.date(2026, 9, 1)))

    def test_impossible_dates_and_unknown_months_are_rejected(self):
        for day, month in ((31, 'września'), (0, 'maja'), (32, 'stycznia'), (5, 'brumaire')):
            with self.subTest(day=day, month=month):
                self.assertIsNone(resolve_yearless_date(day, month, CAPTURED))

    def test_month_names_ignore_case(self):
        self.assertEqual(
            resolve_yearless_date(2, 'Października', CAPTURED), datetime.date(2026, 10, 2)
        )

    def test_rules_resolve_dates_across_the_year_end(self):
        proposal = only(
            propose(
                title='Sprawdzian',
                message='8 stycznia, Historia (historia), Bartosz',
                captured=datetime.date(2026, 12, 18),
            )
        )

        self.assertEqual(proposal.date, datetime.date(2027, 1, 8))

    def test_reference_date_uses_local_day_of_aware_capture_time(self):
        # 23:30 UTC on 30 Sept is already 1 Oct in Europe/Warsaw.
        captured_at = datetime.datetime(2026, 9, 30, 23, 30, tzinfo=datetime.timezone.utc)

        self.assertEqual(reference_date_for(captured_at), datetime.date(2026, 10, 1))
        self.assertEqual(reference_date_for(CAPTURED), CAPTURED)


class ChildMatchingTests(SimpleTestCase):
    def test_name_matching_ignores_case_and_spacing_but_not_diacritics(self):
        self.assertEqual(match_child(' łucja ', CHILDREN), LUCJA)
        self.assertEqual(match_child(unicodedata.normalize('NFD', 'Łucja'), CHILDREN), LUCJA)
        self.assertIsNone(match_child('Lucja', CHILDREN))
        self.assertIsNone(match_child('', CHILDREN))
        self.assertEqual(normalize_child_name(' ZUZANNA '), 'zuzanna')

    def test_duplicate_names_resolve_to_the_newest_membership(self):
        newer = ChildSnapshot(pk=40, display_name='Łucja')
        older = ChildSnapshot(pk=5, display_name='łucja ')

        for children in ((LUCJA, newer, older), (newer, older, LUCJA)):
            with self.subTest(order=[child.pk for child in children]):
                proposal = only(propose('homework', children=children))
                self.assertEqual(proposal.member, newer)

    def test_missing_child_yields_unassigned_proposal_naming_the_child(self):
        proposal = only(propose('test', children=(LUCJA, BARTOSZ)))

        self.assertIsNone(proposal.member)
        self.assertEqual(proposal.content, 'Sprawdzian: Biologia — Zuzanna')
        self.assertEqual(proposal.entry_type, EntryType.CALENDAR_EVENT)
        self.assertEqual(proposal.date, datetime.date(2026, 10, 7))
        # A test kind requires a member, so the unassigned event carries none.
        self.assertIsNone(proposal.school_item)

    def test_missing_child_keeps_note_kinds_that_do_not_need_a_member(self):
        proposal = only(propose('lucky_number', children=()))

        self.assertIsNone(proposal.member)
        self.assertEqual(proposal.content, 'Szczęśliwy numerek: 7 — Bartosz')
        self.assertEqual(proposal.school_item, SchoolItemKind.LUCKY_NUMBER)


class MalformedInputTests(SimpleTestCase):
    def test_unknown_or_empty_notifications_are_left_to_fallback(self):
        for title, message in (
            ('Nowe ogłoszenie', 'Zebranie z rodzicami 2 października'),
            ('', '2 października, Biologia (biologia), Łucja'),
            ('Sprawdzian', '   '),
            ('Zmiana planu', 'Zastępstwo w dniu 25 września na lekcji Biologia, Kowalczyk Irena (7B)'),
        ):
            with self.subTest(title=title):
                self.assertIsNone(propose(title=title, message=message))

    def test_known_category_with_unexpected_message_is_left_to_fallback(self):
        cases = {
            'Sprawdzian': 'Biologia, Łucja',
            'Kartkówka': '31 września, Matematyka (matematyka), Łucja',
            'Zadanie domowe': 'Zadanie domowe na jutro',
            'Ocena': 'Nowa ocena: 5',
            'Szczęśliwy numerek': 'Szczęśliwy numer to: 7, Łucja',
            'Frekwencja': 'Spóźnienie na 2. lekcji, Łucja',
            'Nowa wiadomość': 'Nowa wiadomość od wychowawcy',
        }
        for title, message in cases.items():
            with self.subTest(title=title):
                self.assertIsNone(propose(title=title, message=message))


class PrivacyTests(SimpleTestCase):
    def test_proposal_and_snapshot_reprs_hide_family_text(self):
        proposals = propose('multi_change') + propose('teacher_message') + (LUCJA,)

        text = repr(proposals) + str(proposals)
        for sensitive in ('Łucja', 'Technika', 'Zawadzki', 'Lipińska', 'konkurs'):
            self.assertNotIn(sensitive, text)


class ChildSnapshotTests(TestCase):
    def setUp(self):
        self.family = Family.objects.create(name='Rodzina Testowa')
        self.other_family = Family.objects.create(name='Inna Rodzina')

    def member(self, name, role=FamilyMember.Role.CHILD, family=None, is_active=True):
        user = get_user_model().objects.create_user(
            username=f'user-{FamilyMember.objects.count()}'
        )
        return FamilyMember.objects.create(
            user=user,
            family=family or self.family,
            role=role,
            display_name=name,
            is_active=is_active,
        )

    def test_snapshot_holds_only_active_children_of_the_family(self):
        first = self.member('Łucja')
        self.member('Ewelina', role=FamilyMember.Role.PARENT)
        self.member('Kacper', is_active=False)
        self.member('Bartosz', family=self.other_family)
        second = self.member('Zuzanna')

        snapshot = snapshot_active_children(self.family)

        self.assertEqual(
            snapshot,
            (
                ChildSnapshot(pk=first.pk, display_name='Łucja'),
                ChildSnapshot(pk=second.pk, display_name='Zuzanna'),
            ),
        )

    def test_inactive_family_has_an_empty_snapshot(self):
        self.member('Łucja')
        self.family.is_active = False
        self.family.save(update_fields=('is_active',))

        self.assertEqual(snapshot_active_children(self.family), ())

    def test_newest_active_duplicate_wins_and_inactive_duplicate_is_ignored(self):
        older = self.member('Łucja')
        newer = self.member('Łucja')
        self.member('Łucja', is_active=False)

        proposal = only(
            propose('homework', children=snapshot_active_children(self.family))
        )

        self.assertEqual(proposal.assigned_member_id, newer.pk)
        self.assertNotEqual(proposal.assigned_member_id, older.pk)

    def test_inactive_named_child_yields_unassigned_proposal(self):
        self.member('Łucja', is_active=False)

        proposal = only(
            propose('grade', children=snapshot_active_children(self.family))
        )

        self.assertIsNone(proposal.member)
        self.assertEqual(proposal.content, 'Ocena: 4+, Matematyka — Łucja')
