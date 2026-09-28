"""Text and date normalization for EduVulcan notifications."""

from __future__ import annotations

import calendar
import datetime
import unicodedata
from typing import Optional

# Polish month names in the genitive case, as EduVulcan writes dates.
POLISH_MONTHS = {
    'stycznia': 1,
    'lutego': 2,
    'marca': 3,
    'kwietnia': 4,
    'maja': 5,
    'czerwca': 6,
    'lipca': 7,
    'sierpnia': 8,
    'września': 9,
    'października': 10,
    'listopada': 11,
    'grudnia': 12,
}

# Yearless dates resolve within this many months around the capture date.
YEAR_WINDOW_MONTHS = 6


def normalize_text(value: str) -> str:
    """NFC-normalize, drop invisible format characters, and collapse whitespace.

    Letters, diacritics, case, and punctuation are preserved.
    """
    composed = unicodedata.normalize('NFC', value)
    visible = ''.join(char for char in composed if unicodedata.category(char) != 'Cf')
    return ' '.join(visible.split())


def _shift_months(day: datetime.date, months: int) -> datetime.date:
    index = day.year * 12 + (day.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    last_day = calendar.monthrange(year, month)[1]
    return datetime.date(year, month, min(day.day, last_day))


def resolve_yearless_date(
    day: int, month_name: str, reference: datetime.date
) -> Optional[datetime.date]:
    """Return the matching date nearest to ``reference`` within six months.

    Candidates outside the window, impossible dates (for example 31 September
    or 29 February in a non-leap year), and unknown month names yield ``None``.
    An exact tie prefers the later date, since school notices mostly announce
    upcoming events.
    """
    month = POLISH_MONTHS.get(normalize_text(month_name).casefold())
    if month is None:
        return None
    earliest = _shift_months(reference, -YEAR_WINDOW_MONTHS)
    latest = _shift_months(reference, YEAR_WINDOW_MONTHS)
    candidates = []
    for year in (reference.year - 1, reference.year, reference.year + 1):
        try:
            candidate = datetime.date(year, month, day)
        except ValueError:
            continue
        if earliest <= candidate <= latest:
            candidates.append(candidate)
    if not candidates:
        return None
    return min(candidates, key=lambda candidate: (abs((candidate - reference).days), -candidate.toordinal()))
