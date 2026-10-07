"""Duplicate and exam-merge decisions for EduVulcan rule proposals.

Proposals come from the fixed rules, so content has the exact shape conversion
saves. Existing entries are plain stand-ins built from earlier proposals; no
database is needed. Every child name here is invented.
"""

import datetime
from types import SimpleNamespace

from django.test import SimpleTestCase

from entries.classification.types import EntryType, SchoolItemKind
from entries.eduvulcan.dedup import Action, Candidate, ExamRank, decide, exam_rank
from entries.eduvulcan.rules import general_note_proposal, propose_entries
from entries.eduvulcan.types import ChildSnapshot, EntryProposal, OutputKind

CAPTURED = datetime.date(2026, 9, 23)
NEXT_DAY = datetime.date(2026, 9, 24)
EVENT_DATE = datetime.date(2026, 10, 7)
ZUZANNA = ChildSnapshot(pk=13, display_name='Zuzanna')
BARTOSZ = ChildSnapshot(pk=12, display_name='Bartosz')
CHILDREN = (BARTOSZ, ZUZANNA)


def propose(title, message, *, captured=CAPTURED, children=CHILDREN):
    proposals = propose_entries(title, message, captured_at=captured, children=children)
    assert proposals is not None, (title, message)
    return proposals


def exam(label, subject='Biologia (biologia)', child='Zuzanna', day='7 października', **kwargs):
    (proposal,) = propose(label, f'{day}, {subject}, {child}', **kwargs)
    return proposal


def stored(proposal, *, pk=1, source='eduvulcan', **overrides):
    """An entry as conversion would have saved ``proposal``."""
    values = dict(
        pk=pk,
        entry_type=proposal.entry_type.value,
        assigned_member_id=proposal.assigned_member_id,
        date=proposal.date,
        school_item=proposal.school_item.value if proposal.school_item else '',
        content=proposal.content,
        source=source,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def candidate(entry, captured_date=CAPTURED):
    return Candidate(entry=entry, captured_date=captured_date)


class ExamRankTests(SimpleTestCase):
    def test_exam_labels_are_ranked(self):
        self.assertEqual(exam_rank('Kartkówka: Biologia'), ExamRank(1, 'Kartkówka', 'biologia'))
        self.assertEqual(exam_rank('Sprawdzian: Biologia'), ExamRank(2, 'Sprawdzian', 'biologia'))
        self.assertEqual(
            exam_rank('Praca klasowa: Biologia'), ExamRank(3, 'Praca klasowa', 'biologia')
        )

    def test_remainder_keeps_child_suffix_and_is_normalized(self):
        self.assertEqual(
            exam_rank('  sprawdzian:   Biologia  —  Nieznany '),
            ExamRank(2, 'Sprawdzian', 'biologia — nieznany'),
        )

    def test_non_exams_have_no_rank(self):
        for content in ('Zadanie domowe: Biologia', 'Ocena: 5, Biologia', 'Kartkówka Biologia', ''):
            with self.subTest(content=content):
                self.assertIsNone(exam_rank(content))


class ExamMergeTests(SimpleTestCase):
    def assert_merged_result(self, first_label, second_label, expected_label):
        first = exam(first_label)
        second = exam(second_label)
        decision = decide(second, CAPTURED, [candidate(stored(first))])
        expected_kind = {
            'Kartkówka': SchoolItemKind.QUIZ,
            'Sprawdzian': SchoolItemKind.TEST,
            'Praca klasowa': SchoolItemKind.CLASS_TEST,
        }[expected_label]
        if expected_label == first_label:
            self.assertEqual(decision.action, Action.MERGED)
        else:
            self.assertEqual(decision.action, Action.UPGRADE)
            self.assertEqual(decision.content, f'{expected_label}: Biologia')
            self.assertEqual(decision.school_item, expected_kind)

    def test_quiz_then_test_upgrades_to_test(self):
        self.assert_merged_result('Kartkówka', 'Sprawdzian', 'Sprawdzian')

    def test_test_then_quiz_keeps_test(self):
        self.assert_merged_result('Sprawdzian', 'Kartkówka', 'Sprawdzian')

    def test_class_test_then_quiz_keeps_class_test(self):
        self.assert_merged_result('Praca klasowa', 'Kartkówka', 'Praca klasowa')

    def test_quiz_then_class_test_upgrades_to_class_test(self):
        self.assert_merged_result('Kartkówka', 'Praca klasowa', 'Praca klasowa')

    def test_upgrade_targets_the_matched_entry(self):
        existing = stored(exam('Kartkówka'), pk=7)

        decision = decide(exam('Sprawdzian'), CAPTURED, [candidate(existing)])

        self.assertIs(decision.entry, existing)

    def test_equal_rank_resend_is_a_duplicate(self):
        for label in ('Kartkówka', 'Sprawdzian', 'Praca klasowa'):
            with self.subTest(label=label):
                existing = stored(exam(label))

                decision = decide(exam(label), NEXT_DAY, [candidate(existing)])

                self.assertEqual(decision.action, Action.DUPLICATE)
                self.assertIs(decision.entry, existing)

    def test_upgraded_entry_absorbs_a_lower_rank_resend(self):
        upgraded = stored(exam('Kartkówka'), content='Sprawdzian: Biologia',
                          school_item=SchoolItemKind.TEST.value)

        decision = decide(exam('Kartkówka'), CAPTURED, [candidate(upgraded)])

        self.assertEqual(decision.action, Action.MERGED)

    def test_homework_is_not_merged_with_exams(self):
        homework = propose('Zadanie domowe', 'Zadanie domowe 7 października, Biologia (biologia), Zuzanna')[0]
        test = exam('Sprawdzian')

        self.assertEqual(decide(test, CAPTURED, [candidate(stored(homework))]).action, Action.CREATE)
        self.assertEqual(decide(homework, CAPTURED, [candidate(stored(test))]).action, Action.CREATE)

    def test_unassigned_exam_merges_and_keeps_child_suffix(self):
        quiz = exam('Kartkówka', child='Nieznany')
        test = exam('Sprawdzian', child='Nieznany')
        self.assertIsNone(quiz.member)
        self.assertEqual(quiz.content, 'Kartkówka: Biologia — Nieznany')

        decision = decide(test, CAPTURED, [candidate(stored(quiz))])

        self.assertEqual(decision.action, Action.UPGRADE)
        self.assertEqual(decision.content, 'Sprawdzian: Biologia — Nieznany')
        self.assertIsNone(decision.school_item)

    def test_different_unmatched_children_are_not_merged(self):
        quiz = exam('Kartkówka', child='Nieznany')
        test = exam('Sprawdzian', child='Ktoś Inny')

        self.assertEqual(decide(test, CAPTURED, [candidate(stored(quiz))]).action, Action.CREATE)

    def test_different_subject_date_or_child_is_not_matched(self):
        existing = stored(exam('Kartkówka'))
        for incoming in (
            exam('Sprawdzian', subject='Chemia (chemia)'),
            exam('Sprawdzian', day='8 października'),
            exam('Sprawdzian', child='Bartosz'),
        ):
            with self.subTest(content=incoming.content, date=incoming.date):
                self.assertEqual(
                    decide(incoming, CAPTURED, [candidate(existing)]).action, Action.CREATE
                )

    def test_highest_ranked_match_wins_ties_by_lowest_id(self):
        quiz = stored(exam('Kartkówka'), pk=1)
        test_late = stored(exam('Sprawdzian'), pk=5,
                           content='Sprawdzian: biologia')
        test_early = stored(exam('Sprawdzian'), pk=3,
                            content='SPRAWDZIAN:  Biologia')

        decision = decide(
            exam('Praca klasowa'),
            CAPTURED,
            [candidate(test_late), candidate(quiz), candidate(test_early)],
        )

        self.assertEqual(decision.action, Action.UPGRADE)
        self.assertIs(decision.entry, test_early)
        self.assertEqual(decision.content, 'Praca klasowa: Biologia')

    def test_normalization_ignores_case_and_whitespace(self):
        existing = stored(exam('Kartkówka'), content=' kartkówka:   BIOLOGIA ')

        self.assertEqual(
            decide(exam('Kartkówka'), CAPTURED, [candidate(existing)]).action, Action.DUPLICATE
        )
        upgrade = decide(exam('Sprawdzian'), CAPTURED, [candidate(existing)])
        self.assertEqual(upgrade.action, Action.UPGRADE)
        self.assertEqual(upgrade.content, 'Sprawdzian: BIOLOGIA')


class ExactDuplicateTests(SimpleTestCase):
    def grade(self, captured=CAPTURED):
        (proposal,) = propose('Ocena', 'Nowa ocena: 5, Biologia, Zuzanna', captured=captured)
        return proposal

    def test_grade_resent_same_capture_day_is_a_duplicate(self):
        existing = stored(self.grade())

        decision = decide(self.grade(), CAPTURED, [candidate(existing, CAPTURED)])

        self.assertEqual(decision.action, Action.DUPLICATE)

    def test_grade_resent_on_another_day_is_created(self):
        existing = stored(self.grade())

        decision = decide(self.grade(NEXT_DAY), NEXT_DAY, [candidate(existing, CAPTURED)])

        self.assertEqual(decision.action, Action.CREATE)

    def test_undated_candidate_without_source_day_is_not_matched(self):
        existing = stored(self.grade())

        self.assertEqual(
            decide(self.grade(), CAPTURED, [candidate(existing, None)]).action, Action.CREATE
        )

    def test_timetable_change_resend_is_a_duplicate(self):
        message = 'Zastępstwo w dniu 24 września na lekcji Matematyka, Nowak Anna'
        (first,) = propose('Zmiana planu dla Zuzanna', message)
        (second,) = propose('Zmiana planu dla Zuzanna', message, captured=NEXT_DAY)

        decision = decide(second, NEXT_DAY, [candidate(stored(first), CAPTURED)])

        self.assertEqual(decision.action, Action.DUPLICATE)

    def test_rule_remainder_duplicate_needs_same_capture_day(self):
        message = 'Zastępstwo w dniu 24 września na lekcji Matematyka, Nowak Anna coś nowego'
        proposals = propose('Zmiana planu dla Zuzanna', f'Uwaga: {message}')
        remainder = proposals[-1]
        self.assertEqual(remainder.kind, OutputKind.RULE_REMAINDER)
        existing = stored(remainder)

        self.assertEqual(
            decide(remainder, CAPTURED, [candidate(existing, CAPTURED)]).action, Action.DUPLICATE
        )
        self.assertEqual(
            decide(remainder, NEXT_DAY, [candidate(existing, CAPTURED)]).action, Action.CREATE
        )

    def test_differing_field_is_not_a_duplicate(self):
        grade = self.grade()
        for overrides in (
            {'assigned_member_id': BARTOSZ.pk},
            {'assigned_member_id': None},
            {'school_item': ''},
            {'entry_type': EntryType.TODO.value},
            {'content': 'Ocena: 4, Biologia'},
            {'date': CAPTURED},
        ):
            with self.subTest(**overrides):
                existing = stored(grade, **overrides)
                self.assertEqual(
                    decide(grade, CAPTURED, [candidate(existing)]).action, Action.CREATE
                )

    def test_manual_entry_is_ignored(self):
        for proposal in (self.grade(), exam('Sprawdzian')):
            with self.subTest(content=proposal.content):
                manual = stored(proposal, source='manual')
                self.assertEqual(
                    decide(proposal, CAPTURED, [candidate(manual)]).action, Action.CREATE
                )

    def test_manual_exam_does_not_absorb_or_get_upgraded(self):
        manual = stored(exam('Kartkówka'), source='manual')

        self.assertEqual(
            decide(exam('Sprawdzian'), CAPTURED, [candidate(manual)]).action, Action.CREATE
        )

    def test_non_rule_proposals_are_always_created(self):
        test = exam('Sprawdzian')
        existing = stored(test)
        classified = EntryProposal(
            output_index=0,
            kind=OutputKind.CLASSIFICATION,
            entry_type=test.entry_type,
            content=test.content,
            date=test.date,
            school_item=test.school_item,
            member=test.member,
        )
        note = general_note_proposal('Sprawdzian', '7 października, Biologia, Zuzanna')
        for proposal in (classified, note):
            with self.subTest(kind=proposal.kind):
                self.assertEqual(
                    decide(proposal, CAPTURED, [candidate(existing), candidate(stored(note))]).action,
                    Action.CREATE,
                )

    def test_no_candidates_creates(self):
        self.assertEqual(decide(exam('Sprawdzian'), CAPTURED, []).action, Action.CREATE)
