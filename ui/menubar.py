"""Menübar-Controller für whisper_go."""

from pathlib import Path

import objc
from Foundation import NSObject  # type: ignore[import-not-found]

from config import LOG_FILE
from utils.state import AppState

# Status-Icons für Menübar
MENUBAR_ICONS = {
    AppState.IDLE: "🎤",
    AppState.RECORDING: "🔴",
    AppState.TRANSCRIBING: "⏳",
    AppState.REFINING: "⏳",  # Refining uses same icon as transcribing for now
    AppState.DONE: "✅",
    AppState.ERROR: "❌",
}


class _MenuActionHandler(NSObject):
    """Objective-C Target für Menü-Actions."""

    def initWithLogPath_(self, log_path: str):
        self = objc.super(_MenuActionHandler, self).init()
        if self is None:
            return None
        self.log_path = log_path
        return self

    @objc.signature(b"v@:@")
    def openLogs_(self, _sender) -> None:
        """Öffnet die Log-Datei im Standard-Viewer."""
        from AppKit import NSWorkspace  # type: ignore[import-not-found]

        log_path = Path(self.log_path)
        if not log_path.exists():
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.touch()
        NSWorkspace.sharedWorkspace().openFile_(str(log_path))


class MenuBarController:
    """
    Menübar-Status-Anzeige via NSStatusBar.

    Zeigt aktuellen State als Icon + optional Interim-Text.
    Kein Polling - wird direkt via Callback aktualisiert.
    """

    def __init__(self):
        from AppKit import (  # type: ignore[import-not-found]
            NSStatusBar,
            NSVariableStatusItemLength,
            NSMenu,
            NSMenuItem,
        )

        # Target für Menü-Callbacks
        self._action_handler = _MenuActionHandler.alloc().initWithLogPath_(str(LOG_FILE))

        self._status_bar = NSStatusBar.systemStatusBar()
        self._status_item = self._status_bar.statusItemWithLength_(
            NSVariableStatusItemLength
        )
        self._status_item.setTitle_(MENUBAR_ICONS[AppState.IDLE])

        # Dropdown Menü erstellen
        menu = NSMenu.alloc().init()

        # Titel-Item (Info)
        title_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Whisper Go", None, ""
        )
        title_item.setEnabled_(False)
        menu.addItem_(title_item)

        menu.addItem_(NSMenuItem.separatorItem())

        # Logs öffnen
        logs_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Open Logs", "openLogs:", ""
        )
        logs_item.setTarget_(self._action_handler)
        menu.addItem_(logs_item)

        menu.addItem_(NSMenuItem.separatorItem())

        # Quit-Item (kein Shortcut - CMD+Q läuft über Application Menu)
        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit", "terminate:", ""
        )
        menu.addItem_(quit_item)

        self._status_item.setMenu_(menu)

        self._current_state = AppState.IDLE

    def update_state(self, state: AppState, text: str | None = None) -> None:
        """Aktualisiert Menübar-Icon und optional Text."""
        self._current_state = state
        icon = MENUBAR_ICONS.get(state, MENUBAR_ICONS[AppState.IDLE])

        if state == AppState.RECORDING and text:
            # Kürzen für Menübar
            preview = text[:20] + "…" if len(text) > 20 else text
            self._status_item.setTitle_(f"{icon} {preview}")
        else:
            self._status_item.setTitle_(icon)
