"""UI-Komponenten für PulseScribe (Menübar, Overlay, Welcome).

macOS: MenuBarController, OverlayController, OnboardingWizardController, WelcomeController
Windows: WindowsOverlayController
"""

import sys

__all__ = []

if sys.platform == "darwin":
    from .menubar import MenuBarController
    from .overlay import OverlayController
    from .onboarding_wizard import OnboardingWizardController
    from .welcome import WelcomeController

    __all__ = [
        "MenuBarController",
        "OverlayController",
        "OnboardingWizardController",
        "WelcomeController",
    ]
elif sys.platform == "win32":
    # Prefer PySide6 overlay (GPU-accelerated), fallback to Tkinter
    try:
        from .overlay_pyside6 import PySide6OverlayController as WindowsOverlayController
    except ImportError:
        from .overlay_windows import WindowsOverlayController

    __all__ = ["WindowsOverlayController"]
