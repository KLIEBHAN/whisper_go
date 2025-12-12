"""Shared Custom Vocabulary loader.

Providers and CLI use the same vocabulary file (`~/.whisper_go/vocabulary.json`).
To avoid redundant disk I/O on every transcription, this module caches the
parsed vocabulary and only reloads when the file changes.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from config import VOCABULARY_FILE as _DEFAULT_VOCAB_FILE

logger = logging.getLogger("whisper_go")

# Cache per path: {Path: (mtime, data)}
_cache: dict[Path, tuple[float, dict]] = {}


def load_vocabulary(path: Path | None = None) -> dict:
    """Loads custom vocabulary from JSON.

    Args:
        path: Optional override for tests or custom setups.

    Returns:
        Dict with a guaranteed "keywords" list.
    """
    vocab_file = path or _DEFAULT_VOCAB_FILE

    try:
        mtime = vocab_file.stat().st_mtime
    except FileNotFoundError:
        _cache.pop(vocab_file, None)
        return {"keywords": []}
    except OSError as e:
        logger.warning(f"Vocabulary-Datei nicht lesbar: {e}")
        _cache.pop(vocab_file, None)
        return {"keywords": []}

    cached = _cache.get(vocab_file)
    if cached and cached[0] == mtime:
        return cached[1]

    try:
        data = json.loads(vocab_file.read_text())
        if not isinstance(data.get("keywords"), list):
            data["keywords"] = []
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Vocabulary-Datei fehlerhaft: {e}")
        data = {"keywords": []}

    _cache[vocab_file] = (mtime, data)
    return data


def save_vocabulary(keywords: list[str], path: Path | None = None) -> None:
    """Speichert Custom Vocabulary als JSON.

    Args:
        keywords: Liste der Keywords.
        path: Optionaler Pfad-Override (Tests).
    """
    vocab_file = path or _DEFAULT_VOCAB_FILE
    vocab_file.parent.mkdir(parents=True, exist_ok=True)

    data: dict = {}
    if vocab_file.exists():
        try:
            existing = json.loads(vocab_file.read_text())
            if isinstance(existing, dict):
                data = existing
        except (json.JSONDecodeError, OSError):
            data = {}

    data["keywords"] = list(keywords)

    try:
        vocab_file.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    except OSError as e:
        logger.warning(f"Vocabulary-Datei nicht schreibbar: {e}")
        raise

    # Cache direkt aktualisieren, damit Änderungen sofort wirken.
    try:
        mtime = vocab_file.stat().st_mtime
        _cache[vocab_file] = (mtime, data)
    except OSError:
        _cache.pop(vocab_file, None)


__all__ = ["load_vocabulary", "save_vocabulary"]
