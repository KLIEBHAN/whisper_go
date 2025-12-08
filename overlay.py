#!/usr/bin/env python3
"""
overlay.py – Untertitel-Overlay für whisper_go

Zeigt Interim-Results als elegantes Overlay am unteren Bildschirmrand
mit animierter Schallwellen-Visualisierung.

Nutzung:
    python overlay.py

Voraussetzung:
    PyObjC (bereits für NSWorkspace installiert)
"""

from pathlib import Path
import time

from AppKit import (
    NSApplication,
    NSBackingStoreBuffered,
    NSBezierPath,
    NSColor,
    NSFont,
    NSFontAttributeName,
    NSFontWeightMedium,
    NSFontWeightRegular,  # Standard-Gewichtung
    NSFontWeightSemibold,  # Fetter für bessere Lesbarkeit
    NSMakeRect,
    NSScreen,
    NSTextField,
    NSTextAlignmentCenter,
    NSView,
    NSVisualEffectView,
    NSWindow,
    NSWindowStyleMaskBorderless,
)
from Foundation import NSObject, NSString, NSTimer
from objc import super  # noqa: A004 - PyObjC braucht das
from Quartz import (
    CABasicAnimation,
    CAMediaTimingFunction,
    kCAMediaTimingFunctionEaseInEaseOut,
)

# NSVisualEffectMaterial Konstanten
NS_VISUAL_EFFECT_MATERIAL_HUD_WINDOW = 13
NS_VISUAL_EFFECT_BLENDING_MODE_BEHIND_WINDOW = 0
NS_VISUAL_EFFECT_STATE_ACTIVE = 1

# IPC-Dateien (synchron mit transcribe.py)
STATE_FILE = Path("/tmp/whisper_go.state")
INTERIM_FILE = Path("/tmp/whisper_go.interim")

# Konfiguration - MODERN VERTICAL LAYOUT
POLL_INTERVAL = 0.2
OVERLAY_MIN_WIDTH = 260  # Etwas breiter als Startbasis
OVERLAY_MAX_WIDTH_RATIO = 0.75
OVERLAY_HEIGHT = 100  # Mehr Luft (war 92)
OVERLAY_MARGIN_BOTTOM = 110  # Etwas höher positioniert
OVERLAY_CORNER_RADIUS = 22  # Etwas runder für die Höhe
OVERLAY_PADDING_H = 24  # Mehr seitlicher Abstand
OVERLAY_ALPHA = 0.95
FONT_SIZE = 15  # Größere Schrift
MAX_TEXT_LENGTH = 120
TEXT_FIELD_HEIGHT = 24  # Höheres Textfeld

# Schallwellen-Konfiguration
WAVE_BAR_COUNT = 5
WAVE_BAR_WIDTH = 4
WAVE_BAR_GAP = 5  # Etwas mehr Abstand zwischen Balken
WAVE_BAR_MIN_HEIGHT = 8  # Etwas größere "Ruhe"-Höhe
WAVE_BAR_MAX_HEIGHT = 32  # Höhere Amplitude
WAVE_AREA_WIDTH = WAVE_BAR_COUNT * WAVE_BAR_WIDTH + (WAVE_BAR_COUNT - 1) * WAVE_BAR_GAP

OVERLAY_WINDOW_LEVEL = 25


def truncate_text(text: str, max_length: int = MAX_TEXT_LENGTH) -> str:
    """Kürzt Text für Overlay-Anzeige."""
    text = text.strip()
    if len(text) <= max_length:
        return text
    return text[:max_length].rstrip() + "…"


class SoundWaveView(NSView):
    """Animierte Schallwellen-Visualisierung."""

    def initWithFrame_(self, frame):
        self = super().initWithFrame_(frame)
        if self:
            self.setWantsLayer_(True)
            self.bars = []
            self.animations_running = False
            self.current_animation = None
            self._setup_bars()
        return self

    def _setup_bars(self):
        """Erstellt die Balken für die Schallwellen."""
        frame = self.frame()
        center_y = frame.size.height / 2

        for i in range(WAVE_BAR_COUNT):
            x = i * (WAVE_BAR_WIDTH + WAVE_BAR_GAP)

            # Balken als CALayer
            bar = (
                self.layer().sublayers()[i]
                if self.layer().sublayers() and i < len(self.layer().sublayers())
                else None
            )

            if not bar:
                from Quartz import CALayer

                bar = CALayer.alloc().init()
                self.layer().addSublayer_(bar)

            bar.setBackgroundColor_(
                NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.9).CGColor()
            )
            bar.setCornerRadius_(WAVE_BAR_WIDTH / 2)

            # Initiale Position (zentriert)
            initial_height = WAVE_BAR_MIN_HEIGHT
            bar.setFrame_(
                ((x, center_y - initial_height / 2), (WAVE_BAR_WIDTH, initial_height))
            )

            self.bars.append(bar)

    def setBarColor_(self, ns_color):
        """Setzt die Farbe der Balken."""
        cg_color = ns_color.CGColor()
        for bar in self.bars:
            bar.setBackgroundColor_(cg_color)

    def startRecordingAnimation(self):
        """Startet die organische Schallwellen-Animation (Sprechen)."""
        if self.current_animation == "recording":
            return
            
        self.stopAnimating()
        self.current_animation = "recording"
        self.animations_running = True

        center_y = self.frame().size.height / 2
        
        # Organischere Animation mit leicht unterschiedlichen Timings
        durations = [0.42, 0.38, 0.45, 0.39, 0.41]
        delays = [0.0, 0.15, 0.3, 0.1, 0.25]

        for i, bar in enumerate(self.bars):
            duration = durations[i % len(durations)]
            delay = delays[i % len(delays)]

            # Höhen-Animation
            height_anim = CABasicAnimation.animationWithKeyPath_("bounds.size.height")
            height_anim.setFromValue_(WAVE_BAR_MIN_HEIGHT)
            height_anim.setToValue_(WAVE_BAR_MAX_HEIGHT)
            height_anim.setDuration_(duration)
            height_anim.setBeginTime_(
                bar.convertTime_fromLayer_(
                    CABasicAnimation.alloc().init().beginTime(), None
                ) + delay
            )
            height_anim.setRepeatCount_(float("inf"))
            height_anim.setAutoreverses_(True)
            height_anim.setTimingFunction_(
                CAMediaTimingFunction.functionWithName_(kCAMediaTimingFunctionEaseInEaseOut)
            )

            bar.addAnimation_forKey_(height_anim, f"heightAnim{i}")

    def startTranscribingAnimation(self):
        """Startet eine 'Loading'-Welle (Transkribieren)."""
        if self.current_animation == "transcribing":
            return

        self.stopAnimating()
        self.current_animation = "transcribing"
        self.animations_running = True

        # Eine Welle, die durchläuft
        total_duration = 1.0
        
        for i, bar in enumerate(self.bars):
            # Sequentielles Delay für Welleneffekt
            delay = (i / len(self.bars)) * (total_duration / 2)

            height_anim = CABasicAnimation.animationWithKeyPath_("bounds.size.height")
            height_anim.setFromValue_(WAVE_BAR_MIN_HEIGHT)
            height_anim.setToValue_(WAVE_BAR_MAX_HEIGHT * 0.7) # Etwas weniger Amplitude
            height_anim.setDuration_(total_duration)
            height_anim.setBeginTime_(
                bar.convertTime_fromLayer_(
                    CABasicAnimation.alloc().init().beginTime(), None
                ) + delay
            )
            height_anim.setRepeatCount_(float("inf"))
            height_anim.setAutoreverses_(True)
            height_anim.setTimingFunction_(
                CAMediaTimingFunction.functionWithName_(kCAMediaTimingFunctionEaseInEaseOut)
            )

            bar.addAnimation_forKey_(height_anim, f"transcribeAnim{i}")

    def startSuccessAnimation(self):
        """Einmaliges 'Hüpfen' in Grün für Erfolg."""
        self.stopAnimating()
        self.current_animation = "success"
        self.setBarColor_(NSColor.systemGreenColor())
        
        # Kurze La-Ola Welle
        for i, bar in enumerate(self.bars):
            duration = 0.3
            delay = i * 0.05
            
            anim = CABasicAnimation.animationWithKeyPath_("bounds.size.height")
            anim.setFromValue_(WAVE_BAR_MIN_HEIGHT)
            anim.setToValue_(WAVE_BAR_MAX_HEIGHT * 0.8)
            anim.setDuration_(duration)
            anim.setBeginTime_(bar.convertTime_fromLayer_(CABasicAnimation.alloc().init().beginTime(), None) + delay)
            anim.setAutoreverses_(True)
            anim.setRepeatCount_(1) 
            
            bar.addAnimation_forKey_(anim, f"successAnim{i}")

    def startErrorAnimation(self):
        """Kurzes rotes Aufblinken."""
        self.stopAnimating()
        self.current_animation = "error"
        self.setBarColor_(NSColor.systemRedColor())
        
        # Alle Balken kurz hoch
        for i, bar in enumerate(self.bars):
            anim = CABasicAnimation.animationWithKeyPath_("bounds.size.height")
            anim.setFromValue_(WAVE_BAR_MIN_HEIGHT)
            anim.setToValue_(WAVE_BAR_MAX_HEIGHT)
            anim.setDuration_(0.15)
            anim.setAutoreverses_(True)
            anim.setRepeatCount_(2) # 2x blinken
            bar.addAnimation_forKey_(anim, f"errorAnim{i}")

    def stopAnimating(self):
        """Stoppt alle Animationen."""
        if not self.animations_running:
            return

        self.animations_running = False
        self.current_animation = None
        for bar in self.bars:
            bar.removeAllAnimations()
            # Reset auf Ruheposition
            # Hinweis: Ohne explizites Setzen bleiben Layer manchmal im letzten State
            bar.setBounds_(NSMakeRect(0, 0, WAVE_BAR_WIDTH, WAVE_BAR_MIN_HEIGHT))

    def drawRect_(self, rect):
        """Zeichnet die Balken manuell (Fallback ohne Animation)."""
        if self.animations_running:
            return

        frame = self.frame()
        center_y = frame.size.height / 2

        NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.9).setFill()

        for i in range(WAVE_BAR_COUNT):
            x = i * (WAVE_BAR_WIDTH + WAVE_BAR_GAP)
            height = WAVE_BAR_MIN_HEIGHT
            y = center_y - height / 2

            path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                NSMakeRect(x, y, WAVE_BAR_WIDTH, height),
                WAVE_BAR_WIDTH / 2,
                WAVE_BAR_WIDTH / 2,
            )
            path.fill()


class WhisperOverlay(NSObject):
    """Hauptklasse für das Untertitel-Overlay."""

    def init(self):
        self = super().init()
        if self:
            self.window = None
            self.text_field = None
            self.visual_effect_view = None
            self.wave_view = None
            self.last_text = None
            self.last_interim = None
            self.target_alpha = 0.0
            
            # State Tracking für Feedback
            self.current_state_file_value = None
            self.state_timestamp = 0.0
            
            self._setup_window()
            self._setup_timer()
        return self

    def _setup_window(self):
        """Erstellt das Overlay-Fenster."""
        screen = NSScreen.mainScreen()
        if not screen:
            return

        screen_frame = screen.frame()

        width = OVERLAY_MIN_WIDTH
        height = OVERLAY_HEIGHT
        x = (screen_frame.size.width - width) / 2
        y = OVERLAY_MARGIN_BOTTOM

        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, width, height),
            NSWindowStyleMaskBorderless,
            NSBackingStoreBuffered,
            False,
        )

        self.window.setLevel_(OVERLAY_WINDOW_LEVEL)
        self.window.setIgnoresMouseEvents_(True)
        self.window.setOpaque_(False)
        self.window.setBackgroundColor_(NSColor.clearColor())
        self.window.setAlphaValue_(0.0) # Start unsichtbar für Fade-In
        self.window.setHasShadow_(True)

        self.visual_effect_view = NSVisualEffectView.alloc().initWithFrame_(
            NSMakeRect(0, 0, width, height)
        )
        self.visual_effect_view.setMaterial_(NS_VISUAL_EFFECT_MATERIAL_HUD_WINDOW)
        self.visual_effect_view.setBlendingMode_(
            NS_VISUAL_EFFECT_BLENDING_MODE_BEHIND_WINDOW
        )
        self.visual_effect_view.setState_(NS_VISUAL_EFFECT_STATE_ACTIVE)
        self.visual_effect_view.setWantsLayer_(True)
        self.visual_effect_view.layer().setCornerRadius_(OVERLAY_CORNER_RADIUS)
        self.visual_effect_view.layer().setMasksToBounds_(True)

        # Premium "Glass" Border
        self.visual_effect_view.layer().setBorderWidth_(1.0)
        self.visual_effect_view.layer().setBorderColor_(
            NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.15).CGColor()
        )

        self.window.setContentView_(self.visual_effect_view)
        # VERTIKALES LAYOUT (REFINED)

        # 1. Schallwelle (Oben)
        # Position: Vertikal etwas nach oben verschoben für gute Balance
        wave_y = height - (WAVE_BAR_MAX_HEIGHT + 20)
        wave_x = (width - WAVE_AREA_WIDTH) / 2

        self.wave_view = SoundWaveView.alloc().initWithFrame_(
            NSMakeRect(wave_x, wave_y, WAVE_AREA_WIDTH, WAVE_BAR_MAX_HEIGHT)
        )
        self.visual_effect_view.addSubview_(self.wave_view)

        # 2. Text (Unten)
        # Position: Unter der Wave, aber nicht am Boden klebend
        text_y = 16  # Abstand von unten

        self.text_field = NSTextField.alloc().initWithFrame_(
            NSMakeRect(
                OVERLAY_PADDING_H,
                text_y,
                width - 2 * OVERLAY_PADDING_H,
                TEXT_FIELD_HEIGHT,
            )
        )
        self.text_field.setStringValue_("")
        self.text_field.setBezeled_(False)
        self.text_field.setDrawsBackground_(False)
        self.text_field.setEditable_(False)
        self.text_field.setSelectable_(False)
        self.text_field.setAlignment_(NSTextAlignmentCenter)

        # Text Shadow (Subtil für Lesbarkeit)
        from AppKit import NSShadow
        text_shadow = NSShadow.alloc().init()
        text_shadow.setShadowOffset_((0, -1))
        text_shadow.setShadowBlurRadius_(2.0)
        text_shadow.setShadowColor_(NSColor.colorWithCalibratedWhite_alpha_(0.0, 0.3))
        self.text_field.setShadow_(text_shadow)

        # Helles Weiß für starken Kontrast
        self.text_field.setTextColor_(
            NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.95)
        )
        # Semibold Font
        self.text_field.setFont_(
            NSFont.systemFontOfSize_weight_(FONT_SIZE, NSFontWeightSemibold)
        )

        self.visual_effect_view.addSubview_(self.text_field)

    def _setup_timer(self):
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            POLL_INTERVAL,
            self,
            "pollState:",
            None,
            True,
        )

    def _update_text_style(self, is_status: bool):
        """Passt Schriftart und Farbe basierend auf Text-Typ an."""
        if is_status:
            # Status: Sehr dezent (Regular, transparent)
            self.text_field.setFont_(
                NSFont.systemFontOfSize_weight_(FONT_SIZE, NSFontWeightRegular)
            )
            self.text_field.setTextColor_(
                NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.6)
            )
        else:
            # Inhalt: Gut lesbar, aber nicht zu fett (Medium)
            self.text_field.setFont_(
                NSFont.systemFontOfSize_weight_(FONT_SIZE, NSFontWeightMedium)
            )
            self.text_field.setTextColor_(
                NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.9)
            )

    def _resize_window_for_text(self, text: str):
        """Passt Fenstergröße dynamisch an."""
        screen = NSScreen.mainScreen()
        if not screen:
            return

        screen_frame = screen.frame()

        # Aktuellen Font des Textfelds für Messung nutzen
        font = self.text_field.font()
        attributes = {NSFontAttributeName: font}
        ns_text = NSString.stringWithString_(text)

        text_size = ns_text.sizeWithAttributes_(attributes)
        text_width = text_size.width

        content_width = text_width + 2 * OVERLAY_PADDING_H
        min_for_wave = WAVE_AREA_WIDTH + 2 * OVERLAY_PADDING_H + 60

        width = max(
            OVERLAY_MIN_WIDTH,
            min_for_wave,
            min(content_width, screen_frame.size.width * OVERLAY_MAX_WIDTH_RATIO),
        )
        height = OVERLAY_HEIGHT

        x = (screen_frame.size.width - width) / 2
        y = OVERLAY_MARGIN_BOTTOM

        # Fenster Update (Animiert für flüssige Größenänderung)
        self.window.animator().setFrame_display_(NSMakeRect(x, y, width, height), True)
        self.visual_effect_view.setFrame_(NSMakeRect(0, 0, width, height))

        # Wave zentrieren
        wave_x = (width - WAVE_AREA_WIDTH) / 2
        wave_y = height - (WAVE_BAR_MAX_HEIGHT + 20)
        self.wave_view.setFrame_(
            NSMakeRect(wave_x, wave_y, WAVE_AREA_WIDTH, WAVE_BAR_MAX_HEIGHT)
        )

        # Text zentrieren/breiter machen
        self.text_field.setFrame_(
            NSMakeRect(
                OVERLAY_PADDING_H,
                16,  # Fester Abstand von unten
                width - 2 * OVERLAY_PADDING_H,
                TEXT_FIELD_HEIGHT,
            )
        )

    def _popIn(self):
        """Subtiler Scale-Effekt beim Erscheinen."""
        # Scale Animation für den Content View
        anim = CABasicAnimation.animationWithKeyPath_("transform.scale")
        anim.setFromValue_(0.95)
        anim.setToValue_(1.0)
        anim.setDuration_(0.25)
        anim.setTimingFunction_(CAMediaTimingFunction.functionWithName_(kCAMediaTimingFunctionEaseInEaseOut))
        
        self.visual_effect_view.layer().addAnimation_forKey_(anim, "popIn")

    def _fadeIn(self):
        """Sanftes Einblenden."""
        if self.target_alpha != OVERLAY_ALPHA:
            was_hidden = self.target_alpha == 0.0
            self.target_alpha = OVERLAY_ALPHA
            
            self.window.orderFront_(None)
            self.window.animator().setAlphaValue_(OVERLAY_ALPHA)
            
            if was_hidden:
                self._popIn()

    def _fadeOut(self):
        """Sanftes Ausblenden."""
        if self.target_alpha != 0.0:
            self.target_alpha = 0.0
            self.window.animator().setAlphaValue_(0.0)
            # Hinweis: Wir rufen orderOut_ nicht sofort auf, damit der Fade sichtbar ist.
            # Bei Alpha 0 ist es effektiv unsichtbar und Klicks gehen durch (ignoresMouseEvents=True)

    def pollState_(self, timer):
        state = self._read_state()
        interim_text = self._read_interim()
        current_time = time.time()

        # State Change Detection für Feedback-Timer
        if state != self.current_state_file_value:
            self.current_state_file_value = state
            self.state_timestamp = current_time
            
        # 1. Feedback-Zustände (Done/Error)
        if state in ["done", "error"]:
            # Nach 2 Sekunden ausblenden
            if current_time - self.state_timestamp > 2.0:
                self._fadeOut()
                return

            # Visualisierung anzeigen
            if state == "done":
                if self.wave_view.current_animation != "success":
                    self.wave_view.startSuccessAnimation()
                    self.text_field.setStringValue_("Done")
                    self.text_field.setTextColor_(NSColor.systemGreenColor())
                    self.text_field.setFont_(NSFont.systemFontOfSize_weight_(FONT_SIZE, NSFontWeightSemibold))
                    self._resize_window_for_text("Done")
                    self._fadeIn()
            elif state == "error":
                if self.wave_view.current_animation != "error":
                    self.wave_view.startErrorAnimation()
                    self.text_field.setStringValue_("Error")
                    self.text_field.setTextColor_(NSColor.systemRedColor())
                    self.text_field.setFont_(NSFont.systemFontOfSize_weight_(FONT_SIZE, NSFontWeightSemibold))
                    self._resize_window_for_text("Error")
                    self._fadeIn()
            
            return # Wichtig: Hier abbrechen, damit unten nichts überschrieben wird

        # 2. Aktive Zustände (Recording/Transcribing)
        is_status_msg = False
        new_text = None
        animation_mode = None

        if state == "recording":
            animation_mode = "recording"
            self.wave_view.setBarColor_(NSColor.systemRedColor())
            
            if interim_text:
                self.last_interim = interim_text
                new_text = f"{truncate_text(interim_text)} ..."
                is_status_msg = False
            elif self.last_interim:
                new_text = "Loading ..."
                is_status_msg = True
            else:
                new_text = "Listening ..."
                is_status_msg = True
                
        elif state == "transcribing":
            animation_mode = "transcribing"
            self.wave_view.setBarColor_(NSColor.systemOrangeColor())
            new_text = "Transcribing ..."
            self.last_interim = None
            is_status_msg = True
            
        else: # idle
            self.wave_view.setBarColor_(
                NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.9)
            )
            new_text = None
            self.last_interim = None
            is_status_msg = True
            animation_mode = None

        # Animation Update
        if animation_mode == "recording":
            self.wave_view.startRecordingAnimation()
        elif animation_mode == "transcribing":
            self.wave_view.startTranscribingAnimation()
        else:
            self.wave_view.stopAnimating()

        # Text & Visibility Update
        if new_text != self.last_text or self.target_alpha == 0.0: # Auch updaten wenn wir gerade eingeblendet werden
            self.last_text = new_text
            if new_text is not None:
                self._update_text_style(is_status_msg)
                self._resize_window_for_text(new_text)
                self.text_field.setStringValue_(new_text)
                self._fadeIn()
            else:
                self._fadeOut()

    def _read_state(self) -> str:
        try:
            state = STATE_FILE.read_text().strip()
            return state if state else "idle"
        except FileNotFoundError:
            return "idle"
        except OSError:
            return "idle"

    def _read_interim(self) -> str | None:
        try:
            text = INTERIM_FILE.read_text().strip()
            return text or None
        except FileNotFoundError:
            return None
        except OSError:
            return None


def main():
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(1)
    overlay = WhisperOverlay.alloc().init()  # noqa: F841
    app.run()


if __name__ == "__main__":
    main()
