"""Utility-Module für PulseScribe.

Gemeinsame Hilfsfunktionen für Logging und Zeitmessung.

Usage:
    from utils import setup_logging, log, error, timed_operation

    setup_logging(debug=True)
    with timed_operation("API-Call"):
        do_something()
"""

# NOTE:
# Keep this package-level re-export module intentionally small.
# `config.py` imports `utils.paths`, which imports the `utils` package and executes this
# file. Avoid importing modules here that in turn import `config`, otherwise we can
# end up with circular imports during app startup.

from .alerts import show_error_alert
from .hotkey import parse_hotkey, paste_transcript
from .logging import setup_logging, log, error, get_logger, get_session_id
from .timing import timed_operation, format_duration, log_preview

__all__ = [
    "setup_logging",
    "log",
    "error",
    "get_logger",
    "get_session_id",
    "timed_operation",
    "log_preview",
    "format_duration",
    "parse_hotkey",
    "paste_transcript",
    "show_error_alert",
]
