"""
Native macOS-Alerts für Fehlermeldungen.

Bietet thread-sichere Funktionen für Pop-up-Dialoge,
die auch aus Worker-Threads aufgerufen werden können.
"""

import logging
import sys

logger = logging.getLogger("pulsescribe")


def show_error_alert(title: str, message: str) -> None:
    """Zeigt modalen Fehler-Dialog (thread-safe).

    Kann aus jedem Thread aufgerufen werden – dispatched automatisch
    zum Main-Thread, da NSAlert nur dort angezeigt werden kann.

    Args:
        title: Titel des Dialogs (fett)
        message: Detaillierte Fehlermeldung
    """
    if sys.platform != "darwin":
        # Auf anderen Plattformen nur loggen
        logger.error(f"{title}: {message}")
        return

    try:
        from AppKit import NSAlert, NSCriticalAlertStyle
        from Foundation import NSThread

        def _show_alert() -> None:
            alert = NSAlert.alloc().init()
            alert.setMessageText_(title)
            alert.setInformativeText_(message)
            alert.setAlertStyle_(NSCriticalAlertStyle)
            alert.addButtonWithTitle_("OK")
            alert.runModal()

        # Main-Thread-Check
        if NSThread.isMainThread():
            _show_alert()
        else:
            # Dispatch zum Main-Thread via objc helper
            from PyObjCTools import AppHelper

            AppHelper.callAfter(_show_alert)

    except ImportError:
        # PyObjC nicht verfügbar – nur loggen
        logger.error(f"{title}: {message}")
    except Exception as e:
        logger.error(f"Alert konnte nicht angezeigt werden: {e}")
        logger.error(f"{title}: {message}")
