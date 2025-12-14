"""Migration helpers for whisper_go → PulseScribe rename.

Provides backwards compatibility for:
- ENV variables (WHISPER_GO_* → PULSESCRIBE_*)
- User config path (~/.whisper_go → ~/.pulsescribe)

Migration strategy:
1. Check for old ENV vars, use as fallback if new not set
2. Auto-migrate user config directory on first run
3. Log deprecation warnings (once per session)
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger("pulsescribe")

# Mapping: NEW_NAME → OLD_NAME (for fallback lookup)
ENV_MIGRATION_MAP: dict[str, str] = {
    # Core settings
    "PULSESCRIBE_MODE": "WHISPER_GO_MODE",
    "PULSESCRIBE_MODEL": "WHISPER_GO_MODEL",
    "PULSESCRIBE_LANGUAGE": "WHISPER_GO_LANGUAGE",
    "PULSESCRIBE_STREAMING": "WHISPER_GO_STREAMING",
    # Hotkey settings
    "PULSESCRIBE_HOTKEY": "WHISPER_GO_HOTKEY",
    "PULSESCRIBE_HOTKEY_MODE": "WHISPER_GO_HOTKEY_MODE",
    "PULSESCRIBE_TOGGLE_HOTKEY": "WHISPER_GO_TOGGLE_HOTKEY",
    "PULSESCRIBE_HOLD_HOTKEY": "WHISPER_GO_HOLD_HOTKEY",
    # Refine settings
    "PULSESCRIBE_REFINE": "WHISPER_GO_REFINE",
    "PULSESCRIBE_REFINE_MODEL": "WHISPER_GO_REFINE_MODEL",
    "PULSESCRIBE_REFINE_PROVIDER": "WHISPER_GO_REFINE_PROVIDER",
    # Context settings
    "PULSESCRIBE_CONTEXT": "WHISPER_GO_CONTEXT",
    "PULSESCRIBE_APP_CONTEXTS": "WHISPER_GO_APP_CONTEXTS",
    # UI settings
    "PULSESCRIBE_OVERLAY": "WHISPER_GO_OVERLAY",
    "PULSESCRIBE_DOCK_ICON": "WHISPER_GO_DOCK_ICON",
    "PULSESCRIBE_CLIPBOARD_RESTORE": "WHISPER_GO_CLIPBOARD_RESTORE",
    # Local backend settings
    "PULSESCRIBE_LOCAL_BACKEND": "WHISPER_GO_LOCAL_BACKEND",
    "PULSESCRIBE_LOCAL_MODEL": "WHISPER_GO_LOCAL_MODEL",
    "PULSESCRIBE_LOCAL_FAST": "WHISPER_GO_LOCAL_FAST",
    "PULSESCRIBE_LOCAL_COMPUTE_TYPE": "WHISPER_GO_LOCAL_COMPUTE_TYPE",
    "PULSESCRIBE_LOCAL_CPU_THREADS": "WHISPER_GO_LOCAL_CPU_THREADS",
    "PULSESCRIBE_LOCAL_NUM_WORKERS": "WHISPER_GO_LOCAL_NUM_WORKERS",
    "PULSESCRIBE_LOCAL_BEAM_SIZE": "WHISPER_GO_LOCAL_BEAM_SIZE",
    "PULSESCRIBE_LOCAL_BEST_OF": "WHISPER_GO_LOCAL_BEST_OF",
    "PULSESCRIBE_LOCAL_TEMPERATURE": "WHISPER_GO_LOCAL_TEMPERATURE",
    "PULSESCRIBE_LOCAL_WITHOUT_TIMESTAMPS": "WHISPER_GO_LOCAL_WITHOUT_TIMESTAMPS",
    "PULSESCRIBE_LOCAL_VAD_FILTER": "WHISPER_GO_LOCAL_VAD_FILTER",
    "PULSESCRIBE_LOCAL_WARMUP": "WHISPER_GO_LOCAL_WARMUP",
    "PULSESCRIBE_DEVICE": "WHISPER_GO_DEVICE",
    "PULSESCRIBE_FP16": "WHISPER_GO_FP16",
}

# Track which deprecation warnings we've shown (once per session)
_warned_env_vars: set[str] = set()
_path_migration_done: bool = False

# Old and new config paths
OLD_CONFIG_DIR = Path.home() / ".whisper_go"
NEW_CONFIG_DIR = Path.home() / ".pulsescribe"


def get_env_migrated(new_name: str, default: str | None = None) -> str | None:
    """Get ENV variable with fallback to old WHISPER_GO_* name.

    Checks new name first, falls back to old name if not set.
    Logs deprecation warning on first use of old name.
    """
    # Try new name first
    value = os.getenv(new_name)
    if value is not None:
        return value

    # Check if there's an old name mapping
    old_name = ENV_MIGRATION_MAP.get(new_name)
    if old_name is None:
        return default

    # Try old name as fallback
    value = os.getenv(old_name)
    if value is not None:
        _warn_deprecated_env(old_name, new_name)
        return value

    return default


def _warn_deprecated_env(old_name: str, new_name: str) -> None:
    """Log deprecation warning once per ENV variable."""
    if old_name in _warned_env_vars:
        return
    _warned_env_vars.add(old_name)
    logger.warning(
        f"Deprecated: {old_name} → bitte zu {new_name} umbenennen "
        f"(wird in zukünftiger Version entfernt)"
    )


def migrate_config_directory() -> bool:
    """Migrate user config from ~/.whisper_go to ~/.pulsescribe.

    Returns True if migration was performed, False otherwise.
    Only migrates if:
    - Old directory exists
    - New directory doesn't exist (or is empty)
    """
    global _path_migration_done

    if _path_migration_done:
        return False
    _path_migration_done = True

    # New dir already exists with content → no migration needed
    if NEW_CONFIG_DIR.exists() and any(NEW_CONFIG_DIR.iterdir()):
        # But warn if old dir also exists (user should clean up)
        if OLD_CONFIG_DIR.exists():
            logger.info(
                f"Hinweis: Alte Konfiguration in {OLD_CONFIG_DIR} kann gelöscht werden"
            )
        return False

    # Old dir doesn't exist → fresh install, no migration
    if not OLD_CONFIG_DIR.exists():
        return False

    # Migrate: copy old → new
    logger.info(f"Migriere Konfiguration: {OLD_CONFIG_DIR} → {NEW_CONFIG_DIR}")
    try:
        shutil.copytree(OLD_CONFIG_DIR, NEW_CONFIG_DIR, dirs_exist_ok=True)
        logger.info("Migration erfolgreich! Alte Dateien bleiben als Backup erhalten.")
        return True
    except OSError as e:
        logger.error(f"Migration fehlgeschlagen: {e}")
        return False


def check_deprecated_env_usage() -> list[tuple[str, str]]:
    """Check for any deprecated ENV variables in use.

    Returns list of (old_name, new_name) tuples for all deprecated vars found.
    Useful for showing a summary at startup.
    """
    deprecated: list[tuple[str, str]] = []
    for new_name, old_name in ENV_MIGRATION_MAP.items():
        if os.getenv(old_name) is not None and os.getenv(new_name) is None:
            deprecated.append((old_name, new_name))
    return deprecated


__all__ = [
    "get_env_migrated",
    "migrate_config_directory",
    "check_deprecated_env_usage",
    "ENV_MIGRATION_MAP",
    "OLD_CONFIG_DIR",
    "NEW_CONFIG_DIR",
]
