"""Content-free exception summaries for log lines.

Exception messages may quote family text (notification titles, entry content,
database key values), so they are never logged. The class name, the database
SQLSTATE code and the stack frames (file, line, function) are logged instead:
enough to find the failing line without repeating any data.
"""

import os
import traceback

MAX_FRAMES = 8
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _sqlstate(exc):
    for candidate in (exc, exc.__cause__):
        code = getattr(candidate, 'sqlstate', None) or getattr(candidate, 'pgcode', None)
        if isinstance(code, str):
            return code
    return None


def _frame_path(filename):
    # Library frame (also a virtualenv inside the project): the
    # package-relative tail is enough to identify it.
    marker = os.sep + 'site-packages' + os.sep
    if marker in filename:
        return filename.split(marker, 1)[1]
    if filename.startswith(_PROJECT_ROOT + os.sep):
        return os.path.relpath(filename, _PROJECT_ROOT)
    return os.path.basename(filename)


def _frames(exc):
    frames = traceback.extract_tb(exc.__traceback__)[-MAX_FRAMES:]
    return ' > '.join(f'{_frame_path(f.filename)}:{f.lineno}:{f.name}' for f in frames)


def exception_summary(exc):
    """``Class [sqlstate=..] stack=a.py:1:f > b.py:2:g`` plus the chained causes.

    Starts with the class name, so ``error=%s`` lines keep their old prefix.
    Causes suppressed with ``raise ... from None`` are still followed: they are
    hidden from users, not from the operator.
    """
    parts = []
    seen = set()
    current = exc
    while current is not None and id(current) not in seen and len(seen) < 4:
        seen.add(id(current))
        part = type(current).__name__
        if (code := _sqlstate(current)) is not None:
            part += f' sqlstate={code}'
        if current.__traceback__ is not None:
            part += f' stack={_frames(current)}'
        parts.append(part)
        current = current.__cause__ or current.__context__
    return ' <- caused by '.join(parts)
