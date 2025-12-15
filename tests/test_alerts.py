"""Tests für utils/alerts.py - Native macOS-Alerts."""

import sys
from unittest.mock import MagicMock, patch


class TestShowErrorAlert:
    """Tests für show_error_alert()."""

    def test_non_darwin_only_logs(self, caplog):
        """Auf nicht-macOS wird nur geloggt, kein NSAlert."""
        with patch.object(sys, "platform", "linux"):
            # Re-importieren um Platform-Check zu triggern
            from utils.alerts import show_error_alert

            with caplog.at_level("ERROR"):
                show_error_alert("Test Title", "Test Message")

            assert "Test Title" in caplog.text
            assert "Test Message" in caplog.text

    def test_darwin_creates_alert(self):
        """Auf macOS wird NSAlert erstellt und konfiguriert."""
        if sys.platform != "darwin":
            return  # Skip auf anderen Plattformen

        # AppKit-Klassen mocken
        mock_alert_instance = MagicMock()
        mock_alert = MagicMock()
        mock_alert.alloc.return_value.init.return_value = mock_alert_instance

        mock_thread = MagicMock()
        mock_thread.isMainThread.return_value = True

        with patch.dict(
            "sys.modules",
            {
                "AppKit": MagicMock(NSAlert=mock_alert, NSCriticalAlertStyle=2),
                "Foundation": MagicMock(NSThread=mock_thread, NSObject=MagicMock()),
            },
        ):
            # Force re-import mit gemockten Modulen
            import importlib
            import utils.alerts

            importlib.reload(utils.alerts)

            utils.alerts.show_error_alert(
                "API-Key fehlt", "DEEPGRAM_API_KEY nicht gesetzt"
            )

        # Verify NSAlert wurde konfiguriert
        mock_alert_instance.setMessageText_.assert_called_once_with("API-Key fehlt")
        mock_alert_instance.setInformativeText_.assert_called_once_with(
            "DEEPGRAM_API_KEY nicht gesetzt"
        )
        mock_alert_instance.runModal.assert_called_once()

    def test_import_error_falls_back_to_logging(self, caplog):
        """Bei fehlendem PyObjC wird nur geloggt."""
        if sys.platform != "darwin":
            return

        # Mocke AppKit so, dass ein Import-Fehler simuliert wird
        mock_appkit = MagicMock()
        mock_appkit.NSAlert.alloc.return_value.init.side_effect = Exception(
            "Simulated error"
        )

        mock_thread = MagicMock()
        mock_thread.isMainThread.return_value = True

        with patch.dict(
            "sys.modules",
            {
                "AppKit": mock_appkit,
                "Foundation": MagicMock(NSThread=mock_thread),
            },
        ):
            import importlib
            import utils.alerts

            importlib.reload(utils.alerts)

            with caplog.at_level("ERROR"):
                utils.alerts.show_error_alert("Test", "Message")

            # Sollte ohne Crash durchlaufen und loggen
            assert (
                "Alert konnte nicht angezeigt werden" in caplog.text
                or "Test" in caplog.text
            )
