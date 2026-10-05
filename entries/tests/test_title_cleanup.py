"""Unit tests for the deterministic entry-title guard (S-20).

The guard removes only what classification extracted into another field: a
leading assignee reference and a trailing accepted date phrase. Every other
name, detail and the school subject stay in the title.
"""

from django.test import SimpleTestCase

from entries.classification.title import strip_extracted_phrases

KASIA = ('Kasia',)


class StripExtractedPhrasesTests(SimpleTestCase):
    def assertCleaned(self, content, expected, *, refs=KASIA, date_phrase=None):
        self.assertEqual(
            strip_extracted_phrases(content, assignee_refs=refs, date_phrase=date_phrase),
            expected,
        )

    def test_removed_cases(self):
        cases = [
            # (content, assignee refs, date phrase, expected)
            ('Kasia zrobić pranie w piątek', KASIA, 'w piątek', 'Zrobić pranie'),
            ('kasia zrobić pranie w piątek', KASIA, 'w piątek', 'Zrobić pranie'),
            ('kasia, zrobić pranie', KASIA, None, 'Zrobić pranie'),
            ('KASIA: zrobić pranie', KASIA, None, 'Zrobić pranie'),
            ('Zrobić pranie w piątek', KASIA, 'w piątek', 'Zrobić pranie'),
            ('Zrobić pranie, w piątek.', KASIA, 'w piątek', 'Zrobić pranie'),
            ('Zrobić pranie W PIĄTEK', KASIA, '„w piątek”', 'Zrobić pranie'),
            ('„Kasia” zrobić pranie „w piątek”', KASIA, 'w piątek', 'Zrobić pranie'),
            ('Zrobić pranie w  piątek', KASIA, 'w piątek', 'Zrobić pranie'),
            (
                'Hanna Kowalska, zrobić pranie',
                ('Hanna Kowalska', 'Hanna'),
                None,
                'Zrobić pranie',
            ),
            ('Hanna zrobić pranie', ('Hanna Kowalska', 'Hanna'), None, 'Zrobić pranie'),
            ('Hania odebrać paczkę', ('Hanna', 'Hania'), None, 'Odebrać paczkę'),
            (
                'Kartkówka z matematyki w piątek',
                ('Michał',),
                'w piątek',
                'Kartkówka z matematyki',
            ),
        ]
        for content, refs, date_phrase, expected in cases:
            with self.subTest(content=content, refs=refs, date_phrase=date_phrase):
                self.assertCleaned(content, expected, refs=refs, date_phrase=date_phrase)

    def test_kept_cases(self):
        cases = [
            # Other people and details are not extracted, so they stay.
            ('Kupić prezent dla babci', KASIA, None, 'Kupić prezent dla babci'),
            ('Spotkanie z Tomkiem', ('Tomasz',), None, 'Spotkanie z Tomkiem'),
            # The school subject stays in the title.
            ('Kartkówka z matematyki', ('Michał',), None, 'Kartkówka z matematyki'),
            # A leading name that is not an assignee reference stays.
            ('Bartek odebrać paczkę', KASIA, None, 'Bartek odebrać paczkę'),
            ('Bartek odebrać paczkę', (), None, 'Bartek odebrać paczkę'),
            # A name only prefixes a longer word.
            ('Kasiaczek zrobić pranie', KASIA, None, 'Kasiaczek zrobić pranie'),
            # The assignee mentioned later in the text is not leading.
            ('Zrobić pranie z Kasią', KASIA, None, 'Zrobić pranie z Kasią'),
            # Stripping would empty the title: keep the model's text.
            ('Kasia', KASIA, None, 'Kasia'),
            ('w piątek', KASIA, 'w piątek', 'W piątek'),
            ('Kasia w piątek', KASIA, 'w piątek', 'Kasia w piątek'),
            # A date phrase not at the end stays.
            ('W piątek zrobić pranie', KASIA, 'w piątek', 'W piątek zrobić pranie'),
            ('Zrobić pranie w piątek rano', KASIA, 'w piątek', 'Zrobić pranie w piątek rano'),
            # No accepted date phrase leaves dates in place.
            ('Zrobić pranie w piątek', KASIA, None, 'Zrobić pranie w piątek'),
            ('Zrobić pranie w piątek', KASIA, '   ', 'Zrobić pranie w piątek'),
            # A phrase glued to another word is not a trailing phrase.
            ('Zrobić pranie przedpiątek', KASIA, 'piątek', 'Zrobić pranie przedpiątek'),
            # Blank references never match.
            ('Zrobić pranie', ('', '  ', '„”'), None, 'Zrobić pranie'),
        ]
        for content, refs, date_phrase, expected in cases:
            with self.subTest(content=content, refs=refs, date_phrase=date_phrase):
                self.assertCleaned(content, expected, refs=refs, date_phrase=date_phrase)

    def test_title_starts_with_a_capital_letter(self):
        self.assertCleaned('zrobić pranie', 'Zrobić pranie')
        self.assertCleaned('„zrobić” pranie', '„Zrobić” pranie')
        self.assertCleaned('ćwiczyć grę', 'Ćwiczyć grę')

    def test_unchanged_title_keeps_its_whitespace(self):
        self.assertCleaned('Kupić  mleko', 'Kupić  mleko')

    def test_blank_content_is_returned_as_is(self):
        for content in ('', '   '):
            with self.subTest(content=content):
                self.assertCleaned(content, content, date_phrase='w piątek')
