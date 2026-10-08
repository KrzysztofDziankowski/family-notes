"""Layout and focus rules in css/tokens.css that a rendered-HTML test cannot observe (S-17).

Browser behaviour was verified manually in headless Chromium; these tests pin the rules so a
stylesheet edit that drops them fails the suite.
"""

import re

from django.test import SimpleTestCase

from .test_tokens_contrast import TOKENS_CSS


def split_top_level(selector_list):
    """Split ``a, :is(b, c)`` on the commas outside parentheses."""
    parts, depth, current = [], 0, ''
    for char in selector_list:
        depth += char == '('
        depth -= char == ')'
        if char == ',' and depth == 0:
            parts.append(current)
            current = ''
        else:
            current += char
    return [*parts, current]


# A phone held in landscape (mobile-gui-enhancements): 667x375 and 844x390, not 568x320.
LANDSCAPE_PHONE = '(orientation: landscape) and (min-width: 36rem) and (max-height: 32rem)'


class TokensRuleTests(SimpleTestCase):
    def setUp(self):
        self.css = TOKENS_CSS.read_text(encoding='utf-8')

    def declarations_for(self, selector):
        """Merged declarations of every rule listing ``selector`` (whitespace-normalised)."""
        merged = {}
        stripped = re.sub(r'/\*.*?\*/', '', self.css, flags=re.DOTALL)
        for selectors, body in re.findall(r'([^{}]+)\{([^{}]*)\}', stripped):
            listed = {' '.join(s.split()) for s in split_top_level(selectors)}
            if selector in listed:
                merged.update(
                    (name.strip(), value.strip())
                    for name, value in re.findall(r'([-\w]+)\s*:\s*([^;]+);?', body)
                )
        return merged

    def test_site_nav_wraps_instead_of_scrolling(self):
        # SC 1.4.10: the two-family header ("Rodzina: …", "Zmień rodzinę", "Konto", "Wyloguj")
        # must wrap at 320 CSS px; Pico's nav and nav lists are single-line flex rows.
        for selector in ('.fn-site-nav', '.fn-site-nav ul'):
            with self.subTest(selector):
                self.assertEqual(self.declarations_for(selector).get('flex-wrap'), 'wrap')

    def test_date_and_time_fields_show_focus_while_the_picker_icon_has_it(self):
        # SC 2.4.7: Chromium's calendar/clock icon is its own Tab stop; the field then matches
        # only :focus-within, so that state must draw the shared focus outline.
        declarations = self.declarations_for(
            ':root input:is([type="date"], [type="time"]):focus-within'
        )
        self.assertEqual(declarations.get('outline'), '2px solid var(--fn-color-focus)')

    def media_blocks(self):
        """``{media query: css body}`` for each top-level ``@media`` block."""
        return dict(re.findall(r'@media\s*([^{]+?)\s*\{((?:[^{}]*\{[^{}]*\})*)\s*\}', self.css))

    def outside_media(self, selector):
        css = re.sub(r'@media[^{]+\{(?:[^{}]*\{[^{}]*\})*\s*\}', '', self.css)
        return TokensRuleTests.declarations_for(type('Rules', (), {'css': css})(), selector)

    def test_parent_calendar_is_one_column_then_seven_without_overflow(self):
        # parent-entries-calendar-layout: one column down to 320 CSS px, seven equal columns
        # (two chronological rows) when wide; minmax(0, 1fr) and min-width: 0 stop long
        # entry text from widening the grid (SC 1.4.10).
        self.assertEqual(
            self.outside_media('.fn-calendar').get('grid-template-columns'), 'minmax(0, 1fr)'
        )
        seven = self.calendar_media_queries()
        self.assertEqual(len(seven), 1)
        self.assertIn('grid-template-columns: repeat(7, minmax(0, 1fr));', seven[0][1])
        day = self.outside_media('.fn-calendar-day')
        self.assertEqual(day.get('min-width'), '0')
        self.assertEqual(day.get('overflow-wrap'), 'anywhere')

    def calendar_media_queries(self):
        """``[(media query list split on top-level commas, body)]`` of blocks giving
        ``.fn-calendar`` columns."""
        return [
            ([' '.join(q.split()) for q in split_top_level(query)], body)
            for query, body in self.media_blocks().items()
            if '.fn-calendar {' in body and 'grid-template-columns' in body
        ]

    def test_parent_calendar_is_seven_columns_on_wide_screens_and_landscape_phones(self):
        # mobile-gui-enhancements: the 80rem desktop rule stays; a landscape phone at least
        # 36rem wide and at most 32rem tall (667x375, 844x390, not 568x320) gets the same seven
        # columns and compact type. Portrait phones never match: they keep the base column.
        [(queries, body)] = self.calendar_media_queries()
        self.assertEqual(
            queries,
            ['(min-width: 80rem)',
             LANDSCAPE_PHONE],
        )
        for selector, declaration in (
            ('.fn-calendar {', 'grid-template-columns: repeat(7, minmax(0, 1fr));'),
            ('.fn-calendar-day {', 'font-size: 0.75rem;'),
            ('.fn-calendar-day .fn-entry-row {', 'padding: var(--fn-space-1) var(--fn-space-2);'),
        ):
            with self.subTest(selector):
                rule = body[body.index(selector):]
                self.assertIn(declaration, rule[:rule.index('}')])

    def test_landscape_phone_calendar_page_uses_the_full_width(self):
        # Pico caps .container at 510px from 576px up, which leaves seven columns too narrow
        # for "października": only the calendar page, only on a landscape phone, widens.
        body = self.media_blocks()[LANDSCAPE_PHONE]
        for selector, declarations in (
            ('body:has(.fn-calendar) > .container {',
             ('max-width: none;', 'padding-inline: var(--fn-space-2);')),
            ('.fn-calendar {', ('gap: var(--fn-space-1);',)),
            ('.fn-calendar-day .fn-entry-row {', ('padding: var(--fn-space-1);',)),
        ):
            rule = body[body.index(selector):]
            for declaration in declarations:
                with self.subTest(selector=selector, declaration=declaration):
                    self.assertIn(declaration, rule[:rule.index('}')])
        self.assertNotIn('grid-template-columns', body)
        self.assertNotIn('max-width: none', self.css.replace(body, ''))

    def test_parent_calendar_rules_use_tokens_not_literal_colours(self):
        literal = re.compile(r'#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(')
        for selector in ('.fn-calendar', '.fn-calendar-day', '.fn-calendar-day--empty',
                         '.fn-calendar-empty', '.fn-calendar-nav ul', '.fn-calendar-nav li'):
            declarations = self.outside_media(selector)
            with self.subTest(selector):
                self.assertTrue(declarations)
                for name, value in declarations.items():
                    self.assertIsNone(literal.search(value), f'{name}: {value}')
