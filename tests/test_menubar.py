"""Tests für menubar.py – Menübar-Status und Live-Preview."""

import pytest

from menubar import truncate_text, MAX_PREVIEW_LENGTH


class TestTruncateText:
    """Tests für truncate_text() – Text für Menübar kürzen."""

    @pytest.mark.parametrize(
        "text,max_length,expected",
        [
            ("Hallo", 25, "Hallo"),
            ("Kurz", MAX_PREVIEW_LENGTH, "Kurz"),
            ("a" * 25, 25, "a" * 25),
            ("a" * 30, 25, "a" * 25 + "…"),
            ("", 25, ""),
            ("  Hallo  ", 25, "Hallo"),
            ("Hallo Welt, ich spreche jetzt", 25, "Hallo Welt, ich spreche j…"),
            ("Test ", 4, "Test"),
            ("Test  ", 4, "Test"),
        ],
        ids=[
            "short_text",
            "default_max",
            "exact_length",
            "truncated",
            "empty",
            "strips_whitespace",
            "realistic_interim",
            "trailing_space_exact",
            "trailing_spaces_truncate",
        ],
    )
    def test_truncate_text(self, text, max_length, expected):
        """Verschiedene Texte werden korrekt gekürzt."""
        assert truncate_text(text, max_length) == expected

    def test_uses_ellipsis_unicode(self):
        """Verwendet Unicode-Ellipsis (…) statt drei Punkte (...)."""
        result = truncate_text("a" * 30, 10)
        assert result.endswith("…")
        assert not result.endswith("...")
