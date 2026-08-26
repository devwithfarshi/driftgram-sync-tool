"""Driftgram: where config, manifest, session and logs live on each platform.

The CLI has always kept everything in the working directory. An installed
desktop app cannot - Program Files is not writable, and a user should not
have to know where the app was unpacked. So there are two modes:

  portable  - a config.yaml sits in the working directory (or was passed
              explicitly). Everything resolves next to it, exactly as the
              CLI has always behaved. This keeps `python -m src.main` in a
              git checkout working with no changes.

  managed   - no local config.yaml, so the per-user OS locations are used:
                Windows  %APPDATA%/Driftgram/
                Linux    ~/.config/driftgram/   (config)
                         ~/.local/share/driftgram/  (manifest, session, logs)
              honouring XDG_CONFIG_HOME / XDG_DATA_HOME when set.

Portable mode is detected, never configured, so a developer checkout and an
installed copy can coexist on one machine without fighting over state.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

APP_NAME = "Driftgram"
APP_SLUG = "driftgram"
CONFIG_FILENAME = "config.yaml"


def _windows_appdata() -> Path:
    base = os.environ.get("APPDATA")
    if base:
        return Path(base)
    return Path.home() / "AppData" / "Roaming"


def user_config_dir() -> Path:
    if sys.platform == "win32":
        return _windows_appdata() / APP_NAME
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP_SLUG


def user_data_dir() -> Path:
    if sys.platform == "win32":
        return _windows_appdata() / APP_NAME
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / APP_SLUG


def user_autostart_dir() -> Path:
    """Linux XDG autostart directory (unused on Windows, which uses the registry)."""
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "autostart"


@dataclass(frozen=True)
class AppPaths:
    """Resolved locations for one Driftgram instance."""

    config_file: Path
    data_dir: Path
    portable: bool

    @property
    def log_file(self) -> Path:
        return self.data_dir / "driftgram.log"

    @property
    def lock_file(self) -> Path:
        return self.data_dir / "driftgram.lock"

    def resolve_data(self, value: os.PathLike | str) -> Path:
        """Resolve a possibly-relative path from config against the data dir."""
        path = Path(value).expanduser()
        return path if path.is_absolute() else (self.data_dir / path)

    def ensure_dirs(self) -> None:
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        _harden(self.config_file.parent)
        if self.data_dir != self.config_file.parent:
            _harden(self.data_dir)


def _harden(directory: Path) -> None:
    """Restrict a directory to the owner where the OS supports it.

    The session file inside is equivalent to being logged into the user's
    Telegram account, so on POSIX it should not be world-readable. Windows
    ACLs already restrict a per-user AppData folder; chmod is a no-op there.
    """
    if sys.platform == "win32":
        return
    try:
        directory.chmod(0o700)
    except OSError:
        pass  # best effort - an unusual filesystem is not a reason to fail


def discover(explicit_config: Optional[str] = None, *, force_managed: bool = False) -> AppPaths:
    """Work out which mode we are in and where everything lives.

    force_managed skips the working-directory probe; the installed GUI uses
    it so that launching from a random working directory (a desktop shortcut
    inherits one) can never accidentally pick up a stray config.yaml.
    """
    if explicit_config:
        config_file = Path(explicit_config).expanduser().resolve()
        return AppPaths(config_file=config_file, data_dir=config_file.parent, portable=True)

    if not force_managed:
        local = Path(CONFIG_FILENAME)
        if local.exists():
            resolved = local.resolve()
            return AppPaths(config_file=resolved, data_dir=resolved.parent, portable=True)

    return AppPaths(
        config_file=user_config_dir() / CONFIG_FILENAME,
        data_dir=user_data_dir(),
        portable=False,
    )
