"""Menübar-Controller für whisper_go."""

# Status-Icons für Menübar
MENUBAR_ICONS = {
    "idle": "🎤",
    "recording": "🔴",
    "transcribing": "⏳",
    "done": "✅",
    "error": "❌",
}


class MenuBarController:
    """
    Menübar-Status-Anzeige via NSStatusBar.

    Zeigt aktuellen State als Icon + optional Interim-Text.
    Kein Polling - wird direkt via Callback aktualisiert.
    """

    def __init__(self):
        from AppKit import NSStatusBar, NSVariableStatusItemLength  # type: ignore[import-not-found]

        self._status_bar = NSStatusBar.systemStatusBar()
        self._status_item = self._status_bar.statusItemWithLength_(
            NSVariableStatusItemLength
        )
        self._status_item.setTitle_(MENUBAR_ICONS["idle"])
        self._current_state = "idle"

    def update_state(self, state: str, text: str | None = None) -> None:
        """Aktualisiert Menübar-Icon und optional Text."""
        self._current_state = state
        icon = MENUBAR_ICONS.get(state, MENUBAR_ICONS["idle"])

        if state == "recording" and text:
            # Kürzen für Menübar
            preview = (
                text[:20] + "…" if len(text) > 20 else text
            )
            self._status_item.setTitle_(f"{icon} {preview}")
        else:
            self._status_item.setTitle_(icon)
