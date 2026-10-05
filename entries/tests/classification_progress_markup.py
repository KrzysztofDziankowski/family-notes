"""Markup checks for the classification progress indicator (S-06).

The browser behaviour lives in ``js/classification-progress.js``; these
helpers pin the server-rendered contract it relies on.
"""

from html.parser import HTMLParser

from django.templatetags.static import static

SCRIPT_URL = static('js/classification-progress.js')
STATE_COPY = {
    'running': 'Rozpoznaję wpis… Zwykle trwa to kilka sekund. Nie zamykaj tej strony.',
    'slow': 'Trwa to dłużej niż zwykle. Poczekaj jeszcze chwilę.',
    'stalled': 'Brak odpowiedzi serwera. Sprawdź połączenie i spróbuj ponownie.',
    'offline': (
        'Brak połączenia z internetem. Tekst nie został wysłany — spróbuj ponownie, '
        'gdy połączenie wróci.'
    ),
    'connection_lost': 'Utracono połączenie podczas rozpoznawania. Gdy wróci, spróbuj ponownie.',
}
RETRY_STATES = ('stalled', 'connection_lost')
VOID_TAGS = frozenset((
    'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta',
    'source', 'track', 'wbr',
))


class _ProgressCollector(HTMLParser):
    """Collects every progress form, live region, state block and submit button."""

    def __init__(self):
        super().__init__()
        self.stack = []
        self.forms = []
        self.regions = []
        self._form = None
        self._region = None
        self._block = None
        self._button = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        hidden_ancestor = any('hidden' in item['attrs'] for item in self.stack)
        if tag == 'form':
            self._form = {'attrs': attrs, 'buttons': [], 'regions': []}
            self.forms.append(self._form)
        if 'data-progress-live' in attrs:
            self._region = {
                'attrs': attrs,
                'hidden_ancestor': hidden_ancestor or 'hidden' in attrs,
                'blocks': [],
                'form': self._form,
            }
            self.regions.append(self._region)
            if self._form is not None:
                self._form['regions'].append(self._region)
        if 'data-progress-state' in attrs and self._region is not None:
            self._block = {'attrs': attrs, 'text': '', 'retry': 0, 'depth': len(self.stack)}
            self._region['blocks'].append(self._block)
        if 'data-progress-retry' in attrs and self._block is not None:
            self._block['retry'] += 1
            self._block['retry_type'] = attrs.get('type')
        if (
            tag == 'button'
            and attrs.get('type', 'submit') == 'submit'
            and self._form is not None
        ):
            self._button = {'attrs': attrs, 'text': ''}
            self._form['buttons'].append(self._button)
        if tag not in VOID_TAGS:
            self.stack.append({'tag': tag, 'attrs': attrs})

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.stack.pop()

    def handle_endtag(self, tag):
        if tag in VOID_TAGS:
            return
        closed = None
        while self.stack:
            closed = self.stack.pop()
            if closed['tag'] == tag:
                break
        if self._block is not None and len(self.stack) <= self._block['depth']:
            self._block = None
        if (
            self._region is not None
            and closed is not None
            and 'data-progress-live' in closed['attrs']
        ):
            self._region = None
        if tag == 'form':
            self._form = None
        elif tag == 'button':
            self._button = None

    def handle_data(self, data):
        if self._block is not None:
            self._block['text'] += data
        if self._button is not None:
            self._button['text'] += data


def collect(html):
    collector = _ProgressCollector()
    collector.feed(html)
    collector.close()
    return collector


def _normalized(text):
    return ' '.join(text.split())


def assert_progress_regions(test, html, visible=None):
    """Every progress live region is always rendered and holds the five states.

    ``visible`` maps nothing by default: every state block must be hidden.
    Returns the number of checked regions, so callers can prove the check
    was not vacuous.
    """
    collector = collect(html)
    for number, region in enumerate(collector.regions):
        with test.subTest(region=number):
            test.assertEqual(region['attrs'].get('role'), 'status')
            test.assertEqual(region['attrs'].get('aria-live'), 'polite')
            test.assertIn('data-live-region', region['attrs'])
            test.assertFalse(region['hidden_ancestor'], 'live region is under a hidden ancestor')
            test.assertIsNotNone(region['form'], 'live region is outside a form')
            names = [block['attrs'].get('data-progress-state') for block in region['blocks']]
            test.assertEqual(sorted(names), sorted(STATE_COPY))
            for block in region['blocks']:
                name = block['attrs']['data-progress-state']
                test.assertEqual(block['attrs'].get('class'), 'fn-panel fn-panel--notice')
                test.assertIn(STATE_COPY[name], _normalized(block['text']))
                if name == visible:
                    test.assertNotIn('hidden', block['attrs'], name)
                else:
                    test.assertIn('hidden', block['attrs'], name)
                if name in RETRY_STATES:
                    test.assertEqual(block['retry'], 1, name)
                    test.assertEqual(block['retry_type'], 'button', name)
                    test.assertIn('Spróbuj ponownie', block['text'])
                else:
                    test.assertEqual(block['retry'], 0, name)
    return len(collector.regions)


def progress_forms(html):
    """The forms that render the progress partial, with their submit buttons."""
    return [form for form in collect(html).forms if form['regions']]


def classification_submitters(form):
    """Visible labels of the submit buttons marked as provider calls."""
    return [
        button['text'].strip()
        for button in form['buttons']
        if 'data-classification-submit' in button['attrs']
    ]
