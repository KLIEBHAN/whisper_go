"""Welcome/Setup Window für WhisperGo.

Zeigt Onboarding-Informationen, API-Key-Setup und Feature-Übersicht.
Erscheint beim ersten Start und kann über Menubar aufgerufen werden.
"""

import os

from utils.preferences import (
    get_api_key,
    get_show_welcome_on_startup,
    save_api_key,
    set_onboarding_seen,
    set_show_welcome_on_startup,
)

# Window-Konfiguration
WELCOME_WIDTH = 500
WELCOME_HEIGHT = 650  # Erhöht für besseres Layout
WELCOME_CORNER_RADIUS = 16
WELCOME_PADDING = 24
SECTION_SPACING = 16  # Reduziert für kompakteres Layout
LABEL_SPACING = 6
FOOTER_HEIGHT = 50  # Reservierter Bereich für Footer


def _get_color(r: int, g: int, b: int, a: float = 1.0):
    """Erstellt NSColor aus RGB-Werten."""
    from AppKit import NSColor  # type: ignore[import-not-found]

    return NSColor.colorWithSRGBRed_green_blue_alpha_(r / 255, g / 255, b / 255, a)


class WelcomeController:
    """Welcome/Setup Window für WhisperGo.

    Zeigt:
    - Hotkey-Anleitung
    - API-Key-Konfiguration (mit Save-Buttons)
    - Aktuelle Einstellungen
    - Feature-Liste
    """

    def __init__(self, hotkey: str, config: dict):
        """Initialisiert Welcome Window.

        Args:
            hotkey: Konfigurierter Hotkey (z.B. "F19")
            config: Dict mit aktuellen Einstellungen:
                - deepgram_key: bool (Key vorhanden?)
                - groq_key: bool (Key vorhanden?)
                - refine: bool (LLM-Nachbearbeitung aktiv?)
                - refine_model: str (Modell-Name)
                - language: str (Sprache)
                - mode: str (Provider-Modus)
        """
        self.hotkey = hotkey
        self.config = config
        self._window = None
        self._deepgram_field = None
        self._groq_field = None
        self._deepgram_status = None
        self._groq_status = None
        self._startup_checkbox = None
        self._on_start_callback = None
        self._build_window()

    def _build_window(self) -> None:
        """Erstellt das Welcome Window mit allen Sections."""
        from AppKit import (  # type: ignore[import-not-found]
            NSBackingStoreBuffered,
            NSClosableWindowMask,
            NSMakeRect,
            NSScreen,
            NSTitledWindowMask,
            NSVisualEffectView,
            NSWindow,
        )

        screen = NSScreen.mainScreen()
        if not screen:
            return

        # Fenster zentriert erstellen
        screen_frame = screen.frame()
        x = (screen_frame.size.width - WELCOME_WIDTH) / 2
        y = (screen_frame.size.height - WELCOME_HEIGHT) / 2

        self._window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, WELCOME_WIDTH, WELCOME_HEIGHT),
            NSTitledWindowMask | NSClosableWindowMask,
            NSBackingStoreBuffered,
            False,
        )
        self._window.setTitle_("WhisperGo Setup")
        self._window.setReleasedWhenClosed_(False)

        # Visual Effect View (HUD-Material wie Overlay)
        content_frame = NSMakeRect(0, 0, WELCOME_WIDTH, WELCOME_HEIGHT)
        visual_effect = NSVisualEffectView.alloc().initWithFrame_(content_frame)
        visual_effect.setMaterial_(13)  # HUD Window
        visual_effect.setBlendingMode_(0)  # Behind Window
        visual_effect.setState_(1)  # Active
        self._window.setContentView_(visual_effect)
        self._content_view = visual_effect

        # Sections von oben nach unten aufbauen
        y_pos = WELCOME_HEIGHT - WELCOME_PADDING - 30

        y_pos = self._build_header(y_pos)
        y_pos = self._build_hotkey_section(y_pos)
        y_pos = self._build_api_section(y_pos)
        y_pos = self._build_settings_section(y_pos)
        y_pos = self._build_features_section(y_pos)
        self._build_footer()

    def _build_header(self, y: int) -> int:
        """Erstellt Header mit Titel."""
        from AppKit import (  # type: ignore[import-not-found]
            NSColor,
            NSFont,
            NSFontWeightBold,
            NSMakeRect,
            NSTextField,
        )

        # Titel
        title = NSTextField.alloc().initWithFrame_(
            NSMakeRect(WELCOME_PADDING, y, WELCOME_WIDTH - 2 * WELCOME_PADDING, 30)
        )
        title.setStringValue_("🎤 Welcome to WhisperGo")
        title.setBezeled_(False)
        title.setDrawsBackground_(False)
        title.setEditable_(False)
        title.setSelectable_(False)
        title.setFont_(NSFont.systemFontOfSize_weight_(20, NSFontWeightBold))
        title.setTextColor_(NSColor.whiteColor())
        self._content_view.addSubview_(title)

        return y - 40 - SECTION_SPACING

    def _build_hotkey_section(self, y: int) -> int:
        """Erstellt Hotkey-Anzeige."""
        from AppKit import (  # type: ignore[import-not-found]
            NSBox,
            NSColor,
            NSFont,
            NSFontWeightMedium,
            NSMakeRect,
            NSTextField,
            NSTextAlignmentCenter,
        )

        # Section-Label
        label = self._create_section_label("⌨️  Hotkey", y)
        self._content_view.addSubview_(label)
        y -= 24 + LABEL_SPACING

        # Hotkey-Badge Box
        box_height = 44
        box = NSBox.alloc().initWithFrame_(
            NSMakeRect(
                WELCOME_PADDING,
                y - box_height,
                WELCOME_WIDTH - 2 * WELCOME_PADDING,
                box_height,
            )
        )
        box.setBoxType_(4)  # Custom
        box.setBorderType_(1)  # Line
        box.setFillColor_(NSColor.colorWithCalibratedWhite_alpha_(0.2, 0.5))
        box.setBorderColor_(NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.2))
        box.setCornerRadius_(8)
        self._content_view.addSubview_(box)

        # Hotkey-Text
        hotkey_text = NSTextField.alloc().initWithFrame_(
            NSMakeRect(
                WELCOME_PADDING + 16,
                y - box_height + 10,
                WELCOME_WIDTH - 2 * WELCOME_PADDING - 32,
                24,
            )
        )
        hotkey_text.setStringValue_(f"{self.hotkey}  (Press to start/stop recording)")
        hotkey_text.setBezeled_(False)
        hotkey_text.setDrawsBackground_(False)
        hotkey_text.setEditable_(False)
        hotkey_text.setSelectable_(False)
        hotkey_text.setAlignment_(NSTextAlignmentCenter)
        hotkey_text.setFont_(NSFont.systemFontOfSize_weight_(14, NSFontWeightMedium))
        hotkey_text.setTextColor_(NSColor.whiteColor())
        self._content_view.addSubview_(hotkey_text)

        return y - box_height - SECTION_SPACING

    def _build_api_section(self, y: int) -> int:
        """Erstellt API-Key-Eingabefelder mit Save-Buttons."""
        # Section-Label
        label = self._create_section_label("🔑 API Configuration", y)
        self._content_view.addSubview_(label)
        y -= 24 + LABEL_SPACING

        # Deepgram API Key
        y = self._build_api_row(
            y,
            "Deepgram API Key (required):",
            "DEEPGRAM_API_KEY",
            is_deepgram=True,
        )

        y -= 12  # Spacing zwischen den Feldern

        # Groq API Key
        y = self._build_api_row(
            y,
            "Groq API Key (optional, for LLM refine):",
            "GROQ_API_KEY",
            is_deepgram=False,
        )

        return y - SECTION_SPACING

    def _build_api_row(
        self, y: int, label_text: str, key_name: str, is_deepgram: bool
    ) -> int:
        """Erstellt eine API-Key-Zeile mit Label, Textfeld, Status und Save-Button."""
        from AppKit import (  # type: ignore[import-not-found]
            NSBezelStyleRounded,
            NSButton,
            NSColor,
            NSFont,
            NSFontWeightRegular,
            NSMakeRect,
            NSSecureTextField,
            NSTextField,
        )
        import objc  # type: ignore[import-not-found]

        # Label
        label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(WELCOME_PADDING, y - 16, WELCOME_WIDTH - 2 * WELCOME_PADDING, 16)
        )
        label.setStringValue_(label_text)
        label.setBezeled_(False)
        label.setDrawsBackground_(False)
        label.setEditable_(False)
        label.setSelectable_(False)
        label.setFont_(NSFont.systemFontOfSize_weight_(12, NSFontWeightRegular))
        label.setTextColor_(NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.7))
        self._content_view.addSubview_(label)
        y -= 20

        # Textfeld (Secure für API-Keys)
        field_width = (
            WELCOME_WIDTH - 2 * WELCOME_PADDING - 80
        )  # Platz für Status + Button
        field = NSSecureTextField.alloc().initWithFrame_(
            NSMakeRect(WELCOME_PADDING, y - 24, field_width, 24)
        )
        field.setPlaceholderString_("Enter API key...")
        field.setFont_(NSFont.systemFontOfSize_(12))

        # Existierenden Key anzeigen (maskiert)
        existing_key = get_api_key(key_name) or os.getenv(key_name)
        if existing_key:
            field.setStringValue_(existing_key)

        self._content_view.addSubview_(field)

        # Status-Indicator
        status = NSTextField.alloc().initWithFrame_(
            NSMakeRect(WELCOME_PADDING + field_width + 8, y - 22, 20, 20)
        )
        status.setBezeled_(False)
        status.setDrawsBackground_(False)
        status.setEditable_(False)
        status.setSelectable_(False)
        status.setFont_(NSFont.systemFontOfSize_(14))

        # Status basierend auf vorhandenem Key
        has_key = bool(existing_key) or self.config.get(
            "deepgram_key" if is_deepgram else "groq_key", False
        )
        status.setStringValue_("✓" if has_key else "✗")
        status.setTextColor_(
            _get_color(51, 217, 178) if has_key else _get_color(255, 71, 87)
        )
        self._content_view.addSubview_(status)

        # Save-Button
        save_btn = NSButton.alloc().initWithFrame_(
            NSMakeRect(WELCOME_WIDTH - WELCOME_PADDING - 50, y - 24, 50, 24)
        )
        save_btn.setTitle_("Save")
        save_btn.setBezelStyle_(NSBezelStyleRounded)
        save_btn.setFont_(NSFont.systemFontOfSize_(11))

        # Action Handler für Save-Button
        handler = _SaveButtonHandler.alloc().initWithKeyName_field_status_(
            key_name, field, status
        )
        save_btn.setTarget_(handler)
        save_btn.setAction_(objc.selector(handler.saveKey_, signature=b"v@:@"))
        # Handler referenzieren damit er nicht garbage collected wird
        if is_deepgram:
            self._deepgram_handler = handler
        else:
            self._groq_handler = handler

        self._content_view.addSubview_(save_btn)

        # Referenzen speichern
        if is_deepgram:
            self._deepgram_field = field
            self._deepgram_status = status
        else:
            self._groq_field = field
            self._groq_status = status

        return y - 28

    def _build_settings_section(self, y: int) -> int:
        """Zeigt aktuelle Einstellungen an."""
        from AppKit import (  # type: ignore[import-not-found]
            NSColor,
            NSFont,
            NSFontWeightRegular,
            NSMakeRect,
            NSTextField,
        )

        # Section-Label
        label = self._create_section_label("⚙️  Current Settings", y)
        self._content_view.addSubview_(label)
        y -= 24 + LABEL_SPACING

        # Settings-Liste
        settings = [
            f"• Refine: {'✓ Enabled' if self.config.get('refine') else '✗ Disabled'}"
            + (
                f" ({self.config.get('refine_model', '')})"
                if self.config.get("refine")
                else ""
            ),
            f"• Language: {self.config.get('language', 'auto-detect') or 'auto-detect'}",
            f"• Provider: {self.config.get('mode', 'deepgram').title()}",
        ]

        for setting in settings:
            setting_label = NSTextField.alloc().initWithFrame_(
                NSMakeRect(
                    WELCOME_PADDING + 8,
                    y - 18,
                    WELCOME_WIDTH - 2 * WELCOME_PADDING - 16,
                    18,
                )
            )
            setting_label.setStringValue_(setting)
            setting_label.setBezeled_(False)
            setting_label.setDrawsBackground_(False)
            setting_label.setEditable_(False)
            setting_label.setSelectable_(False)
            setting_label.setFont_(
                NSFont.systemFontOfSize_weight_(12, NSFontWeightRegular)
            )
            setting_label.setTextColor_(
                NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.8)
            )
            self._content_view.addSubview_(setting_label)
            y -= 20

        return y - SECTION_SPACING

    def _build_features_section(self, y: int) -> int:
        """Zeigt Feature-Liste an."""
        from AppKit import (  # type: ignore[import-not-found]
            NSColor,
            NSFont,
            NSFontWeightRegular,
            NSMakeRect,
            NSTextField,
        )

        # Section-Label
        label = self._create_section_label("✨ Features", y)
        self._content_view.addSubview_(label)
        y -= 24 + LABEL_SPACING

        # Feature-Liste
        features = [
            "• Real-time streaming (~300ms latency)",
            "• LLM post-processing for grammar & punctuation",
            "• Context-aware: adapts to email/chat/code",
            '• Voice commands: "new paragraph", "comma", etc.',
        ]

        for feature in features:
            feature_label = NSTextField.alloc().initWithFrame_(
                NSMakeRect(
                    WELCOME_PADDING + 8,
                    y - 18,
                    WELCOME_WIDTH - 2 * WELCOME_PADDING - 16,
                    18,
                )
            )
            feature_label.setStringValue_(feature)
            feature_label.setBezeled_(False)
            feature_label.setDrawsBackground_(False)
            feature_label.setEditable_(False)
            feature_label.setSelectable_(False)
            feature_label.setFont_(
                NSFont.systemFontOfSize_weight_(12, NSFontWeightRegular)
            )
            feature_label.setTextColor_(
                NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.8)
            )
            self._content_view.addSubview_(feature_label)
            y -= 20

        return y - SECTION_SPACING

    def _build_footer(self) -> None:
        """Erstellt Footer mit Separator, Checkbox und Start-Button."""
        from AppKit import (  # type: ignore[import-not-found]
            NSBezelStyleRounded,
            NSBox,
            NSButton,
            NSButtonTypeSwitch,
            NSColor,
            NSFont,
            NSFontWeightSemibold,
            NSMakeRect,
        )
        import objc  # type: ignore[import-not-found]

        footer_y = WELCOME_PADDING + 8

        # Separator-Linie über dem Footer
        separator_y = footer_y + 40
        separator = NSBox.alloc().initWithFrame_(
            NSMakeRect(
                WELCOME_PADDING, separator_y, WELCOME_WIDTH - 2 * WELCOME_PADDING, 1
            )
        )
        separator.setBoxType_(2)  # Separator
        separator.setBorderColor_(NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.2))
        self._content_view.addSubview_(separator)

        # "Show at startup" Checkbox
        checkbox = NSButton.alloc().initWithFrame_(
            NSMakeRect(WELCOME_PADDING, footer_y, 150, 20)
        )
        checkbox.setButtonType_(NSButtonTypeSwitch)
        checkbox.setTitle_("Show at startup")
        checkbox.setFont_(NSFont.systemFontOfSize_(12))
        checkbox.setState_(1 if get_show_welcome_on_startup() else 0)

        # Checkbox Handler
        checkbox_handler = _CheckboxHandler.alloc().init()
        checkbox.setTarget_(checkbox_handler)
        checkbox.setAction_(
            objc.selector(checkbox_handler.toggleStartup_, signature=b"v@:@")
        )
        self._checkbox_handler = checkbox_handler

        self._content_view.addSubview_(checkbox)
        self._startup_checkbox = checkbox

        # "Start WhisperGo" Button
        start_btn = NSButton.alloc().initWithFrame_(
            NSMakeRect(WELCOME_WIDTH - WELCOME_PADDING - 160, footer_y - 4, 160, 32)
        )
        start_btn.setTitle_("Start WhisperGo")
        start_btn.setBezelStyle_(NSBezelStyleRounded)
        start_btn.setFont_(NSFont.systemFontOfSize_weight_(13, NSFontWeightSemibold))

        # Start-Button Handler
        start_handler = _StartButtonHandler.alloc().initWithController_(self)
        start_btn.setTarget_(start_handler)
        start_btn.setAction_(objc.selector(start_handler.startApp_, signature=b"v@:@"))
        self._start_handler = start_handler

        self._content_view.addSubview_(start_btn)

    def _create_section_label(self, text: str, y: int):
        """Erstellt ein Section-Label."""
        from AppKit import (  # type: ignore[import-not-found]
            NSColor,
            NSFont,
            NSFontWeightSemibold,
            NSMakeRect,
            NSTextField,
        )

        label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(WELCOME_PADDING, y - 20, WELCOME_WIDTH - 2 * WELCOME_PADDING, 20)
        )
        label.setStringValue_(text)
        label.setBezeled_(False)
        label.setDrawsBackground_(False)
        label.setEditable_(False)
        label.setSelectable_(False)
        label.setFont_(NSFont.systemFontOfSize_weight_(14, NSFontWeightSemibold))
        label.setTextColor_(NSColor.whiteColor())
        return label

    def set_on_start_callback(self, callback) -> None:
        """Setzt Callback für Start-Button."""
        self._on_start_callback = callback

    def show(self) -> None:
        """Zeigt Window (nicht-modal)."""
        if self._window:
            self._window.makeKeyAndOrderFront_(None)
            self._window.center()
            # App aktivieren damit Fenster im Vordergrund ist
            from AppKit import NSApp  # type: ignore[import-not-found]

            NSApp.activateIgnoringOtherApps_(True)

    def close(self) -> None:
        """Schließt Window und markiert Onboarding als gesehen."""
        set_onboarding_seen(True)
        if self._window:
            self._window.close()

    def _handle_start(self) -> None:
        """Handler für Start-Button."""
        set_onboarding_seen(True)
        if self._on_start_callback:
            self._on_start_callback()
        self.close()


# =============================================================================
# Objective-C Handler Klassen
# =============================================================================


def _create_save_handler_class():
    """Erstellt NSObject-Subklasse für Save-Button."""
    from Foundation import NSObject  # type: ignore[import-not-found]
    import objc  # type: ignore[import-not-found]

    class SaveButtonHandler(NSObject):
        """Handler für API-Key Save-Buttons."""

        def initWithKeyName_field_status_(self, key_name, field, status):
            self = objc.super(SaveButtonHandler, self).init()
            if self is None:
                return None
            self._key_name = key_name
            self._field = field
            self._status = status
            return self

        @objc.signature(b"v@:@")
        def saveKey_(self, _sender) -> None:
            """Speichert API-Key aus Textfeld."""
            value = self._field.stringValue()
            if value:
                save_api_key(self._key_name, value)
                self._status.setStringValue_("✓")
                self._status.setTextColor_(_get_color(51, 217, 178))
            else:
                self._status.setStringValue_("✗")
                self._status.setTextColor_(_get_color(255, 71, 87))

    return SaveButtonHandler


def _create_checkbox_handler_class():
    """Erstellt NSObject-Subklasse für Checkbox."""
    from Foundation import NSObject  # type: ignore[import-not-found]
    import objc  # type: ignore[import-not-found]

    class CheckboxHandler(NSObject):
        """Handler für Show-at-startup Checkbox."""

        @objc.signature(b"v@:@")
        def toggleStartup_(self, sender) -> None:
            """Toggle für Show-at-startup."""
            set_show_welcome_on_startup(sender.state() == 1)

    return CheckboxHandler


def _create_start_handler_class():
    """Erstellt NSObject-Subklasse für Start-Button."""
    from Foundation import NSObject  # type: ignore[import-not-found]
    import objc  # type: ignore[import-not-found]

    class StartButtonHandler(NSObject):
        """Handler für Start-Button."""

        def initWithController_(self, controller):
            self = objc.super(StartButtonHandler, self).init()
            if self is None:
                return None
            self._controller = controller
            return self

        @objc.signature(b"v@:@")
        def startApp_(self, _sender) -> None:
            """Startet App und schließt Window."""
            self._controller._handle_start()

    return StartButtonHandler


# Handler-Klassen erstellen
_SaveButtonHandler = _create_save_handler_class()
_CheckboxHandler = _create_checkbox_handler_class()
_StartButtonHandler = _create_start_handler_class()
