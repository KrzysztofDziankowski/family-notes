"""Markup checks for field descriptions (S-17), shared by the view and form tests.

``entries.forms.describe_fields`` composes each field's ``aria-describedby``;
these helpers pin that every referenced ID is rendered exactly once.
"""

from collections import Counter
from html.parser import HTMLParser

_FIELD_TAGS = ('input', 'select', 'textarea')


class _Collector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = Counter()
        self.fields = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get('id'):
            self.ids[attrs['id']] += 1
        if tag in _FIELD_TAGS and attrs.get('id') and attrs.get('type') != 'hidden':
            self.fields[attrs['id']] = attrs


def _collect(html):
    collector = _Collector()
    collector.feed(html)
    collector.close()
    return collector


def described_by(html, field_id):
    """The ``aria-describedby`` IDs of the field ``field_id``, in order."""
    attrs = _collect(html).fields[field_id]
    return (attrs.get('aria-describedby') or '').split()


def assert_described_by(test, response_or_html, field_id, expected):
    """The field references exactly ``expected`` and each ID is rendered once."""
    html = getattr(response_or_html, 'content', response_or_html)
    if isinstance(html, bytes):
        html = html.decode()
    collector = _collect(html)
    test.assertIn(field_id, collector.fields, f'no field {field_id}')
    attrs = collector.fields[field_id]
    test.assertEqual((attrs.get('aria-describedby') or '').split(), list(expected))
    for target in expected:
        test.assertEqual(collector.ids[target], 1, f'{target} rendered {collector.ids[target]}x')
