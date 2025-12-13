"""Transkript-Historie für WhisperGo.

Speichert transkribierte Texte in ~/.whisper_go/history.jsonl.
Jede Zeile ist ein JSON-Objekt mit Timestamp und Text.
"""

import json
import logging
from datetime import datetime

from config import USER_CONFIG_DIR

HISTORY_FILE = USER_CONFIG_DIR / "history.jsonl"
MAX_HISTORY_SIZE_MB = 10  # Max file size before rotation

logger = logging.getLogger(__name__)


def save_transcript(
    text: str,
    *,
    mode: str | None = None,
    language: str | None = None,
    refined: bool = False,
    app_context: str | None = None,
) -> bool:
    """Speichert ein Transkript in der Historie.

    Args:
        text: Der transkribierte Text
        mode: Transkriptions-Modus (deepgram, local, etc.)
        language: Erkannte/gesetzte Sprache
        refined: Ob LLM-Refine angewendet wurde
        app_context: Aktive App beim Transkribieren

    Returns:
        True bei Erfolg, False bei Fehler
    """
    if not text or not text.strip():
        return False

    try:
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)

        # Check file size and rotate if needed
        _rotate_if_needed()

        entry = {
            "timestamp": datetime.now().isoformat(),
            "text": text.strip(),
        }

        # Optional fields (nur wenn gesetzt)
        if mode:
            entry["mode"] = mode
        if language:
            entry["language"] = language
        if refined:
            entry["refined"] = True
        if app_context:
            entry["app"] = app_context

        with HISTORY_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        logger.debug(f"Transcript saved to history: {text[:50]}...")
        return True

    except Exception as e:
        logger.warning(f"Failed to save transcript to history: {e}")
        return False


def _rotate_if_needed() -> None:
    """Rotiert die Historie wenn sie zu groß wird."""
    if not HISTORY_FILE.exists():
        return

    try:
        size_mb = HISTORY_FILE.stat().st_size / (1024 * 1024)
        if size_mb < MAX_HISTORY_SIZE_MB:
            return

        # Rotate: Keep last 50% of entries
        lines = HISTORY_FILE.read_text(encoding="utf-8").splitlines()
        keep_count = len(lines) // 2
        if keep_count > 0:
            HISTORY_FILE.write_text(
                "\n".join(lines[-keep_count:]) + "\n",
                encoding="utf-8",
            )
            logger.info(f"History rotated: kept {keep_count} of {len(lines)} entries")

    except Exception as e:
        logger.warning(f"History rotation failed: {e}")


def get_recent_transcripts(count: int = 10) -> list[dict]:
    """Gibt die letzten N Transkripte zurück.

    Args:
        count: Anzahl der Einträge (default: 10)

    Returns:
        Liste von Transkript-Dictionaries (neueste zuerst)
    """
    if not HISTORY_FILE.exists():
        return []

    try:
        lines = HISTORY_FILE.read_text(encoding="utf-8").splitlines()
        entries = []

        # Parse from end (most recent first)
        for line in reversed(lines[-count:]):
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue

        return entries

    except Exception as e:
        logger.warning(f"Failed to read history: {e}")
        return []


def clear_history() -> bool:
    """Löscht die gesamte Historie.

    Returns:
        True bei Erfolg, False bei Fehler
    """
    try:
        if HISTORY_FILE.exists():
            HISTORY_FILE.unlink()
        logger.info("History cleared")
        return True
    except Exception as e:
        logger.warning(f"Failed to clear history: {e}")
        return False
