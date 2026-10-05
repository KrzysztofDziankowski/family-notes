import unicodedata

from django.test import SimpleTestCase

from entries.classification.names import (
    DIMINUTIVES,
    match_mention,
    name_group,
    normalize_name,
)


def match(mention, names):
    return match_mention(mention, list(names), display_name=lambda name: name)


class DictionaryTests(SimpleTestCase):
    def test_keys_are_sorted_and_all_entries_are_lowercase_nfc(self):
        self.assertEqual(list(DIMINUTIVES), sorted(DIMINUTIVES))
        for full_name, short_forms in DIMINUTIVES.items():
            for name in (full_name, *short_forms):
                self.assertEqual(name, unicodedata.normalize('NFC', name).casefold())
                self.assertEqual(name, name.strip())

    def test_recorded_example_and_anna_forms_are_covered(self):
        self.assertTrue({'hania', 'hanka', 'hanusia'} <= DIMINUTIVES['hanna'])
        self.assertTrue({'hania', 'ania', 'anka'} <= DIMINUTIVES['anna'])

    def test_name_group_includes_every_full_name_of_a_short_form(self):
        self.assertEqual(name_group('Hania'), {'hania', 'hanna', 'anna'})
        self.assertEqual(name_group('Hanna'), {'hanna'})
        self.assertEqual(name_group('  '), frozenset())

    def test_normalize_name_keeps_diacritics(self):
        decomposed = unicodedata.normalize('NFD', 'Michał')
        self.assertEqual(normalize_name(f'  {decomposed} '), 'michał')
        self.assertNotEqual(normalize_name('Michal'), normalize_name('Michał'))


class MatchMentionTests(SimpleTestCase):
    def test_short_name_resolves_to_a_unique_full_name(self):
        self.assertEqual(match('Hania', ['Hanna', 'Michał']), ('Hanna',))

    def test_short_name_fitting_two_members_is_ambiguous(self):
        self.assertEqual(match('Hania', ['Hanna', 'Michał', 'Anna']), ('Hanna', 'Anna'))

    def test_exact_and_case_insensitive_full_name(self):
        self.assertEqual(match('Hanna', ['Hanna', 'Anna']), ('Hanna',))
        self.assertEqual(match('hANNA', ['Hanna', 'Anna']), ('Hanna',))

    def test_display_name_with_surname(self):
        self.assertEqual(match('Hania', ['Hanna Kowalska', 'Michał']), ('Hanna Kowalska',))
        self.assertEqual(match('Hanna', ['Hanna Kowalska']), ('Hanna Kowalska',))
        self.assertEqual(match('hanna kowalska', ['Hanna Kowalska']), ('Hanna Kowalska',))

    def test_stored_diminutive_matched_by_its_full_form(self):
        self.assertEqual(match('Katarzyna', ['Kasia', 'Tymek']), ('Kasia',))
        self.assertEqual(match('Tymoteusz', ['Kasia', 'Tymek']), ('Tymek',))

    def test_diacritics_remain_significant(self):
        self.assertEqual(match('Michal', ['Michał']), ())
        self.assertEqual(match('Michał', ['Michal']), ())

    def test_blank_or_unknown_mention_matches_nothing(self):
        self.assertEqual(match('', ['Hanna']), ())
        self.assertEqual(match('   ', ['Hanna']), ())
        self.assertEqual(match(None, ['Hanna']), ())
        self.assertEqual(match('Bożydar', ['Hanna', 'Anna']), ())

    def test_exact_match_beats_group_match(self):
        # "Ania" is a short form of Anna, and "Hania" shares the Anna group,
        # but a member literally named "Ania" wins without a question.
        self.assertEqual(match('Ania', ['Hania', 'Ania']), ('Ania',))

    def test_group_fallback_when_no_exact_match(self):
        # Pinned on purpose: with only "Hania" in the family, "Ania" reaches
        # her through the shared Anna group.
        self.assertEqual(match('Ania', ['Hania']), ('Hania',))

    def test_candidate_order_is_preserved_and_objects_are_returned(self):
        class Member:
            def __init__(self, display_name):
                self.display_name = display_name

        anna, hanna = Member('Anna'), Member('Hanna')
        result = match_mention('Hania', [anna, hanna], display_name=lambda m: m.display_name)
        self.assertEqual(result, (anna, hanna))
