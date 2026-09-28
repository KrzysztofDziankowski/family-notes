"""Gunicorn hooks for FamilyNotes.

Loaded explicitly with ``--config gunicorn.conf.py`` from the release
directory (Gunicorn also discovers this file in its working directory).
Command-line options such as ``--workers 2`` and ``--timeout 45`` stay in the
systemd unit and take precedence over this file; it only adds hooks.

The EduVulcan conversion worker starts in ``post_worker_init``: inside each
worker process, after the fork and after Django is loaded, so it never runs
in a ``--preload`` master, in management commands, or at import time. See
``entries/eduvulcan/worker.py`` for the full rationale.
"""


def post_worker_init(worker):
    # Conversion must never keep a worker from serving requests (intake
    # stays up); a failure here only shows up in /healthz/conversion/.
    try:
        from entries.eduvulcan.worker import start_worker

        start_worker()
    except Exception as exc:
        worker.log.warning('EduVulcan conversion worker not started: error=%s', type(exc).__name__)


def worker_exit(server, worker):
    try:
        from entries.eduvulcan.worker import stop_worker

        stop_worker()
    except Exception as exc:
        server.log.warning('EduVulcan conversion worker stop failed: error=%s', type(exc).__name__)
