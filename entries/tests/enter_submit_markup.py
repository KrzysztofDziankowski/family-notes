"""Markup checks for Enter-to-submit (S-05), shared by the view tests.

The browser behaviour lives in ``js/enter-submit.js``; these helpers pin the
server-rendered contract it relies on.
"""

from html.parser import HTMLParser

from django.templatetags.static import static
from django.urls import reverse

ENTER_HINT = 'Enter wysyła, Shift+Enter dodaje nową linię.'
SCRIPT_URL = static('js/enter-submit.js')


class _FormCollector(HTMLParser):
    """Collects every form with its textareas and submit buttons."""

    def __init__(self):
        super().__init__()
        self.forms = []
        self._form = None
        self._button = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'form':
            self._form = {'attrs': attrs, 'textareas': [], 'buttons': []}
            self.forms.append(self._form)
        elif self._form is None:
            return
        elif tag == 'textarea':
            self._form['textareas'].append(attrs)
        elif tag == 'button' and attrs.get('type', 'submit') == 'submit':
            self._button = {'attrs': attrs, 'text': ''}
            self._form['buttons'].append(self._button)

    def handle_endtag(self, tag):
        if tag == 'form':
            self._form = None
        elif tag == 'button':
            self._button = None

    def handle_data(self, data):
        if self._button is not None:
            self._button['text'] += data


def forms_in(html):
    collector = _FormCollector()
    collector.feed(html)
    collector.close()
    return collector.forms


def assert_enter_never_saves(test, html):
    """Every Enter field of a save form submits only through its „Popraw” button.

    Returns the number of checked Enter fields, so callers can prove the
    check was not vacuous.
    """
    confirm_url = reverse('entries:confirm')
    batch_url = reverse('entries:confirm_batch')
    correct_url = reverse('entries:correct')
    checked = 0
    for form in forms_in(html):
        action = form['attrs'].get('action')
        if action not in (confirm_url, batch_url):
            continue
        buttons = {b['attrs'].get('id'): b for b in form['buttons'] if b['attrs'].get('id')}
        for field in form['textareas']:
            if 'data-enter-submit' not in field:
                continue
            checked += 1
            name = field.get('name', '')
            with test.subTest(form=action, field=name):
                test.assertTrue(name.endswith('correction'), name)
                submitter_id = field.get('data-enter-submitter')
                test.assertTrue(submitter_id, f'{name} has no named submitter')
                test.assertIn(submitter_id, buttons, f'{submitter_id} is not in the same form')
                button = buttons[submitter_id]
                test.assertEqual(button['text'].strip(), 'Popraw')
                test.assertNotEqual(button, form['buttons'][0], 'points at the default save')
                if action == confirm_url:
                    test.assertEqual(button['attrs'].get('formaction'), correct_url)
                    test.assertEqual(button['attrs'].get('name'), 'action')
                    test.assertEqual(button['attrs'].get('value'), 'correct')
                else:
                    prefix = name.removesuffix('-correction')
                    index = prefix.removeprefix('e')
                    test.assertTrue(index.isdigit(), name)
                    test.assertEqual(submitter_id, f'e{index}-correct-submit')
                    test.assertEqual(button['attrs'].get('name'), 'action')
                    test.assertEqual(button['attrs'].get('value'), f'correct-{index}')
                    test.assertNotIn('formaction', button['attrs'])
    return checked


def assert_enter_assets(test, response, field_ids):
    """The page loads the script and renders a hidden hint for each Enter field."""
    test.assertContains(response, f'<script src="{SCRIPT_URL}" defer></script>', html=True)
    for field_id in field_ids:
        with test.subTest(field=field_id):
            test.assertContains(
                response,
                f'<p class="fn-muted" id="{field_id}-enter-hint" data-enter-hint hidden>'
                f'<small>{ENTER_HINT}</small></p>',
                html=True,
            )
