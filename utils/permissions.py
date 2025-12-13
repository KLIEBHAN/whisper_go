"""
Berechtigungs-Checks für macOS (Mikrofon, Accessibility).
"""

import logging
import ctypes
import ctypes.util

from AppKit import NSAlert, NSInformationalAlertStyle
from AVFoundation import (
    AVCaptureDevice,
    AVMediaTypeAudio,
    AVAuthorizationStatusAuthorized,
    AVAuthorizationStatusDenied,
    AVAuthorizationStatusRestricted,
    AVAuthorizationStatusNotDetermined,
)

logger = logging.getLogger("whisper_go")

# Accessibility API laden
_app_services = ctypes.cdll.LoadLibrary(
    ctypes.util.find_library("ApplicationServices")
)
_app_services.AXIsProcessTrusted.restype = ctypes.c_bool


def get_microphone_permission_state() -> str:
    """Gibt den aktuellen Mikrofon-Permission-State zurück.

    Returns:
        One of: "authorized", "not_determined", "denied", "restricted", "unknown"
    """
    try:
        status = AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeAudio)
    except Exception:
        return "unknown"

    if status == AVAuthorizationStatusAuthorized:
        return "authorized"
    if status == AVAuthorizationStatusNotDetermined:
        return "not_determined"
    if status == AVAuthorizationStatusDenied:
        return "denied"
    if status == AVAuthorizationStatusRestricted:
        return "restricted"
    return "unknown"


def check_microphone_permission(show_alert: bool = True, request: bool = False) -> bool:
    """
    Prüft Mikrofon-Berechtigung.
    Zeigt einen Alert, falls Zugriff verweigert wurde.
    
    Returns:
        True wenn Zugriff erlaubt oder (noch) nicht entschieden.
        False wenn explizit verweigert/eingeschränkt.
    """
    state = get_microphone_permission_state()
    
    if state == "authorized":
        return True
        
    if state == "not_determined":
        # OS wird beim ersten Zugriff fragen
        if request:
            try:
                AVCaptureDevice.requestAccessForMediaType_completionHandler_(
                    AVMediaTypeAudio, lambda _granted: None
                )
            except Exception:
                pass
        return True
        
    if state in ("denied", "restricted"):
        logger.error("Mikrofon-Zugriff verweigert!")
        if show_alert:
            _show_permission_alert(
                "Mikrofon-Zugriff erforderlich",
                "Whisper Go benötigt Zugriff auf das Mikrofon, um Sprache aufzunehmen.\n\n"
                "Bitte aktiviere es unter:\n"
                "Systemeinstellungen → Datenschutz & Sicherheit → Mikrofon"
            )
        return False
        
    return True


def check_accessibility_permission(show_alert: bool = True, request: bool = False) -> bool:
    """
    Prüft Accessibility-Berechtigung (für Auto-Paste via CMD+V).
    Zeigt einen Alert, falls Zugriff nicht gewährt.
    
    Returns:
        True wenn Zugriff erlaubt, False wenn nicht.
    """
    if _app_services.AXIsProcessTrusted():
        return True

    if request:
        try:
            from Quartz import (  # type: ignore[import-not-found]
                AXIsProcessTrustedWithOptions,
                kAXTrustedCheckOptionPrompt,
            )

            AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})
        except Exception:
            pass
    
    logger.warning("Accessibility-Berechtigung fehlt - Auto-Paste wird nicht funktionieren")
    if show_alert:
        _show_permission_alert(
            "Bedienungshilfen-Zugriff empfohlen",
            "Whisper Go benötigt Bedienungshilfen-Zugriff für Auto-Paste (CMD+V).\n\n"
            "Ohne diese Berechtigung wird der Text nur in die Zwischenablage kopiert.\n\n"
            "Aktiviere es unter:\n"
            "Systemeinstellungen → Datenschutz & Sicherheit → Bedienungshilfen"
        )
    return False


def check_input_monitoring_permission(show_alert: bool = True, request: bool = False) -> bool:
    """
    Prüft Input‑Monitoring/Eingabemonitoring‑Berechtigung (für globale Key‑Listener).

    macOS verlangt diese Berechtigung für Quartz Event Taps und pynput Listener.

    Args:
        show_alert: Wenn True, zeigt einen Hinweis‑Alert bei fehlender Berechtigung.
        request: Wenn True, fordert der Prozess die Berechtigung aktiv an.

    Returns:
        True wenn Zugriff erlaubt, False wenn nicht.
    """
    try:
        from Quartz import CGPreflightListenEventAccess, CGRequestListenEventAccess  # type: ignore[import-not-found]
    except Exception:
        return True

    try:
        ok = bool(CGPreflightListenEventAccess())
    except Exception:
        ok = False

    if ok:
        return True

    logger.warning("Input‑Monitoring‑Berechtigung fehlt – globale Hotkeys funktionieren nicht")
    if show_alert:
        _show_permission_alert(
            "Eingabemonitoring‑Zugriff empfohlen",
            "Whisper Go benötigt Eingabemonitoring‑Zugriff für systemweite Hotkeys "
            "(Fn/CapsLock/Hold‑Mode).\n\n"
            "Aktiviere es unter:\n"
            "Systemeinstellungen → Datenschutz & Sicherheit → Eingabemonitoring",
        )

    if request:
        try:
            CGRequestListenEventAccess()
        except Exception:
            pass

    return False


def _show_permission_alert(title: str, message: str) -> None:
    """Zeigt modalen Fehler-Dialog."""
    alert = NSAlert.alloc().init()
    alert.setMessageText_(title)
    alert.setInformativeText_(message)
    alert.setAlertStyle_(NSInformationalAlertStyle)
    alert.addButtonWithTitle_("OK")
    alert.runModal()
