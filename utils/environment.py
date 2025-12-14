"""Shared .env loading.

Both `transcribe.py` (CLI) and `pulsescribe_daemon.py` (macOS app/daemon) rely on
`.env` files. Historically they implemented slightly different loaders, which
made behavior drift over time.

Precedence (default `override_existing=False`):
1) Process environment (`os.environ`)
2) User config `.env` (`~/.pulsescribe/.env`)
3) Local project `.env` (current working directory)

On reload (`override_existing=True`), `.env` values override existing env vars,
while user config still overrides the local project `.env`.
"""

from __future__ import annotations

import os
from pathlib import Path


def load_environment(*, override_existing: bool = False) -> None:
    """Loads `.env` values into `os.environ` if python-dotenv is available.

    Also triggers config directory migration from ~/.whisper_go to ~/.pulsescribe.
    """
    # Trigger config migration first (before loading .env)
    try:
        from utils.migration import migrate_config_directory

        migrate_config_directory()
    except Exception:
        pass  # Migration is best-effort

    try:
        from dotenv import dotenv_values  # type: ignore[import-not-found]
    except Exception:
        return

    from config import USER_CONFIG_DIR
    from utils.migration import OLD_CONFIG_DIR

    local_env = Path(".env")
    user_env = USER_CONFIG_DIR / ".env"
    # Fallback to old config dir if new doesn't have .env yet
    old_user_env = OLD_CONFIG_DIR / ".env"

    merged: dict[str, str] = {}
    # Local first, then old user, then new user (new user wins).
    env_paths = [local_env, old_user_env, user_env]
    for env_path in env_paths:
        if not env_path.exists():
            continue
        for key, value in dotenv_values(env_path).items():
            if value is None:
                continue
            merged[str(key)] = str(value)

    for key, value in merged.items():
        if override_existing or key not in os.environ:
            os.environ[key] = value

    # Migrate old WHISPER_GO_* env vars to new PULSESCRIBE_* names
    _migrate_env_names()


def _migrate_env_names() -> None:
    """Map old WHISPER_GO_* env vars to new PULSESCRIBE_* names.

    If an old env var is set but the new one isn't, copy the value.
    This allows users to keep their old .env files working.
    """
    from utils.migration import ENV_MIGRATION_MAP

    for new_name, old_name in ENV_MIGRATION_MAP.items():
        if os.getenv(new_name) is None and os.getenv(old_name) is not None:
            os.environ[new_name] = os.environ[old_name]


__all__ = ["load_environment"]
