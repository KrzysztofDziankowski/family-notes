"""WCAG 2.2 contrast of the design tokens in css/tokens.css (S-17).

The ``:root`` custom properties are parsed from the stylesheet, so a token
edit that breaks a declared pair fails the suite.
"""

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

TOKENS_CSS = Path(settings.BASE_DIR) / 'family_notes' / 'static' / 'css' / 'tokens.css'

# (foreground, background) token names, without the ``--fn-color-`` prefix.
# SC 1.4.3 Contrast (Minimum): text needs at least 4.5:1.
TEXT_PAIRS = [
    *((text, background)
      for text in ('text', 'text-strong', 'muted', 'accent', 'danger')
      for background in ('bg', 'surface')),
    ('muted', 'success-bg'),  # .fn-muted inside a success panel
    ('muted', 'notice-bg'),  # .fn-muted inside a notice panel
    ('muted', 'danger-bg'),  # .fn-muted inside a danger panel
    ('danger', 'danger-bg'),  # .fn-field-error and delete summary on the open disclosure
    ('accent-inverse', 'accent'),  # primary buttons, active tab
    ('accent-inverse', 'danger'),  # "Usuń na stałe"
]
# SC 1.4.11 Non-text Contrast: control boundaries and focus indicators need 3:1.
NON_TEXT_PAIRS = [
    ('control-border', 'bg'),  # form-control boundary on the page
    ('control-border', 'surface'),  # form-control boundary on a panel
    *(('focus', background)  # focus outline on every background it can sit on
      for background in ('bg', 'surface', 'success-bg', 'notice-bg', 'danger-bg')),
]


def root_tokens(css):
    """``{name: value}`` of the ``--fn-color-*`` hex tokens in the first ``:root`` block."""
    block = re.search(r':root\s*\{(.*?)\}', css, re.DOTALL).group(1)
    return dict(re.findall(r'--fn-color-([a-z-]+):\s*(#[0-9a-fA-F]{6})\s*;', block))


def relative_luminance(hex_color):
    channels = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(first, second):
    lighter, darker = sorted((relative_luminance(first), relative_luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


class ContrastFormulaTests(SimpleTestCase):
    def test_known_ratios(self):
        self.assertAlmostEqual(contrast_ratio('#000000', '#ffffff'), 21.0, places=2)
        self.assertAlmostEqual(contrast_ratio('#ffffff', '#ffffff'), 1.0, places=2)
        self.assertAlmostEqual(contrast_ratio('#767676', '#ffffff'), 4.54, places=2)


class TokenContrastTests(SimpleTestCase):
    def setUp(self):
        self.tokens = root_tokens(TOKENS_CSS.read_text(encoding='utf-8'))

    def assert_pairs(self, pairs, minimum):
        for foreground, background in pairs:
            with self.subTest(foreground=foreground, background=background):
                self.assertIn(foreground, self.tokens)
                self.assertIn(background, self.tokens)
                ratio = contrast_ratio(self.tokens[foreground], self.tokens[background])
                self.assertGreaterEqual(
                    ratio, minimum, f'{foreground} on {background} is {ratio:.2f}:1'
                )

    def test_text_pairs_reach_4_5_to_1(self):
        self.assert_pairs(TEXT_PAIRS, 4.5)

    def test_non_text_pairs_reach_3_to_1(self):
        self.assert_pairs(NON_TEXT_PAIRS, 3.0)

    def test_pico_controls_use_the_project_tokens(self):
        css = TOKENS_CSS.read_text(encoding='utf-8')
        self.assertIn('--pico-form-element-border-color: var(--fn-color-control-border);', css)
        self.assertIn('--pico-secondary-focus: var(--fn-color-focus);', css)
