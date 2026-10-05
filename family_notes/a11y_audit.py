"""Structural WCAG 2.2 AA page audit (S-17). Test support only: never imported by product code.

``audit_page(html)`` parses a rendered page with the standard library and
returns human-readable violations; an empty list means the page passes. It
checks structure only (landmarks, headings, names, references, live regions).
Colour in context, focus order on screen and announcements need the manual
pass described in ``context/foundation/accessibility.md``.
"""

from collections import Counter
from html.parser import HTMLParser

VOID_TAGS = frozenset({
    'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta',
    'source', 'track', 'wbr',
})
TEXTLESS_TAGS = frozenset({'script', 'style', 'template'})
HEADING_TAGS = ('h1', 'h2', 'h3', 'h4', 'h5', 'h6')
FIELD_TAGS = frozenset({'input', 'select', 'textarea'})
# Inputs that are buttons or carry no user value need no <label>.
UNLABELLED_INPUT_TYPES = frozenset({'hidden', 'submit', 'button', 'reset', 'image'})
REFERENCE_ATTRS = ('aria-describedby', 'aria-labelledby')
LIVE_ROLES = ('alert', 'status')


class Node:
    def __init__(self, tag, attrs, parent=None):
        self.tag = tag
        self.attrs = attrs
        self.parent = parent
        self.children = []

    def iter(self):
        """This node and every descendant element, in document order."""
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.iter()

    def is_hidden(self):
        """Whether this element or an ancestor carries ``hidden``."""
        node = self
        while node is not None:
            if 'hidden' in node.attrs:
                return True
            node = node.parent
        return False

    def text(self, *, visible_only=False):
        if visible_only and 'hidden' in self.attrs:
            return ''
        parts = []
        for child in self.children:
            if isinstance(child, Node):
                if child.tag not in TEXTLESS_TAGS:
                    parts.append(child.text(visible_only=visible_only))
            else:
                parts.append(child)
        return ' '.join(' '.join(parts).split())

    def describe(self):
        details = ''.join(
            f' {name}="{self.attrs[name]}"'
            for name in ('id', 'name', 'href', 'class', 'role')
            if self.attrs.get(name)
        )
        return f'<{self.tag}{details}>'


class _TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node('#document', {})
        self._stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, {name: value or '' for name, value in attrs}, self._stack[-1])
        self._stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self._stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self._stack.pop()

    def handle_endtag(self, tag):
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                return

    def handle_data(self, data):
        self._stack[-1].children.append(data)


def parse(html):
    builder = _TreeBuilder()
    builder.feed(html)
    builder.close()
    return builder.root


def _is_focusable(node):
    if node.is_hidden() or 'disabled' in node.attrs:
        return False
    tabindex = node.attrs.get('tabindex')
    if tabindex is not None:
        try:
            return int(tabindex) >= 0
        except ValueError:
            pass
    if node.tag == 'a':
        return 'href' in node.attrs
    if node.tag == 'input':
        return node.attrs.get('type', 'text') != 'hidden'
    return node.tag in ('button', 'select', 'textarea', 'summary')


def _accessible_name(node, ids):
    label = node.attrs.get('aria-label', '').strip()
    if label:
        return label
    labelled = [ids[ref] for ref in node.attrs.get('aria-labelledby', '').split() if ref in ids]
    if labelled:
        return ' '.join(target.text() for target in labelled).strip()
    if node.tag == 'input':
        return node.attrs.get('value', '').strip()
    return node.text()


def _check_document(root, elements, violations):
    html = next((node for node in elements if node.tag == 'html'), None)
    if html is None or html.attrs.get('lang') != 'pl':
        violations.append('<html> must declare lang="pl"')
    title = next((node for node in elements if node.tag == 'title'), None)
    if title is None or not title.text():
        violations.append('the page needs a non-empty <title>')
    mains = [node for node in elements if node.tag == 'main']
    if len(mains) != 1:
        violations.append(f'expected exactly one <main>, found {len(mains)}')
    h1s = [node for node in elements if node.tag == 'h1']
    if len(h1s) != 1:
        violations.append(f'expected exactly one <h1>, found {len(h1s)}')


def _check_headings(elements, violations):
    previous = 0
    for node in elements:
        if node.tag not in HEADING_TAGS:
            continue
        level = int(node.tag[1])
        if level > previous + 1:
            violations.append(
                f'heading level skipped: <{node.tag}> "{node.text()}" follows h{previous or "-"}'
            )
        if not node.text():
            violations.append(f'empty heading {node.describe()}')
        previous = level


def _check_skip_link(elements, ids, violations):
    first = next((node for node in elements if _is_focusable(node)), None)
    href = first.attrs.get('href', '') if first is not None and first.tag == 'a' else ''
    if not href.startswith('#') or len(href) < 2:
        found = first.describe() if first is not None else 'nothing'
        violations.append(f'the first focusable element must be a skip link, found {found}')
    elif href[1:] not in ids:
        violations.append(f'the skip link points at a missing id: {href}')


def _check_ids_and_references(elements, ids, id_counts, violations):
    for value, count in id_counts.items():
        if count > 1:
            violations.append(f'duplicate id "{value}" ({count}x)')
    for node in elements:
        for attr in REFERENCE_ATTRS:
            for ref in node.attrs.get(attr, '').split():
                if ref not in ids:
                    violations.append(f'{node.describe()} {attr} points at a missing id: {ref}')
        href = node.attrs.get('href', '') if node.tag == 'a' else ''
        if href.startswith('#') and len(href) > 1 and href[1:] not in ids:
            violations.append(f'{node.describe()} links to a missing id')


def _check_fields(elements, ids, violations):
    label_targets = {node.attrs.get('for') for node in elements if node.tag == 'label'}
    for node in elements:
        if node.tag not in FIELD_TAGS or node.is_hidden():
            continue
        if node.tag == 'input' and node.attrs.get('type', 'text') in UNLABELLED_INPUT_TYPES:
            continue
        has_label = (
            (node.attrs.get('id') and node.attrs['id'] in label_targets)
            or node.attrs.get('aria-label', '').strip()
            or node.attrs.get('aria-labelledby', '').strip()
            or any(parent.tag == 'label' for parent in _ancestors(node))
        )
        if not has_label:
            violations.append(f'field without a label: {node.describe()}')
        if node.attrs.get('aria-invalid') == 'true':
            refs = [ids[ref] for ref in node.attrs.get('aria-describedby', '').split() if ref in ids]
            if not any(target.text() for target in refs):
                violations.append(f'invalid field without a resolvable description: {node.describe()}')


def _ancestors(node):
    node = node.parent
    while node is not None:
        yield node
        node = node.parent


def _check_names(elements, ids, violations):
    for node in elements:
        if node.tag == 'a' and 'href' in node.attrs or node.tag == 'button':
            if not _accessible_name(node, ids):
                violations.append(f'{node.describe()} has no text or aria-label')


def _check_focus_attributes(elements, violations):
    for node in elements:
        tabindex = node.attrs.get('tabindex', '').strip()
        if tabindex.isdigit() and int(tabindex) > 0:
            violations.append(f'positive tabindex on {node.describe()}')
    autofocus = [node for node in elements if 'autofocus' in node.attrs]
    if len(autofocus) > 1:
        violations.append(f'{len(autofocus)} autofocus elements; at most one is allowed')


def _check_live_regions(elements, violations):
    for node in elements:
        if node.attrs.get('role') not in LIVE_ROLES or node.is_hidden():
            continue
        if 'aria-live' in node.attrs and 'data-live-region' in node.attrs:
            states = [
                child for child in node.iter()
                if child is not node and 'hidden' in child.attrs and child.text()
            ]
            if not states:
                violations.append(
                    f'script-updated live region {node.describe()} has no hidden state block with text'
                )
        elif not node.text(visible_only=True):
            violations.append(f'{node.describe()} with role="{node.attrs["role"]}" has no visible text')


def audit_page(html):
    """Structural accessibility violations of a rendered page (empty when it passes)."""
    root = parse(html)
    elements = [node for node in root.iter() if node is not root]
    id_counts = Counter(node.attrs['id'] for node in elements if node.attrs.get('id'))
    ids = {}
    for node in elements:
        ids.setdefault(node.attrs.get('id'), node)
    ids.pop(None, None)
    ids.pop('', None)
    violations = []
    _check_document(root, elements, violations)
    _check_headings(elements, violations)
    _check_skip_link(elements, ids, violations)
    _check_ids_and_references(elements, ids, id_counts, violations)
    _check_fields(elements, ids, violations)
    _check_names(elements, ids, violations)
    _check_focus_attributes(elements, violations)
    _check_live_regions(elements, violations)
    return violations


def assert_accessible(testcase, response_or_html):
    """Fail ``testcase`` with every violation of the rendered page."""
    html = getattr(response_or_html, 'content', response_or_html)
    if isinstance(html, bytes):
        html = html.decode()
    violations = audit_page(html)
    if violations:
        testcase.fail('Accessibility audit failed:\n- ' + '\n- '.join(violations))
