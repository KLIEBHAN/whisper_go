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


__all__ = ["load_vocabulary"]

