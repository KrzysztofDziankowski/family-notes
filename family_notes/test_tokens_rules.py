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
