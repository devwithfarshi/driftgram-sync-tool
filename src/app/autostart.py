"""Driftgram: start with the computer, the way each desktop expects.

A sync tool that only runs when someone remembers to open it is not much of a
sync tool, so "start Driftgram when I log in" is a first-class setting. The
two platforms disagree about how that is expressed:

    Windows  a value under HKCU\\...\\CurrentVersion\\Run
    Linux    a .desktop file in ~/.config/autostart

Both are per-user and need no elevation, which matters - a non-technical user
should never see a UAC prompt or be asked for a sudo password to tick a box.

The app is launched with --tray so it starts quietly in the notification area
instead of throwing a window in the user's face at every login.
"""
from __future__ import annotations

import logging
import shlex
import sys
from pathlib import Path
from typing import List

from ..paths import APP_NAME, APP_SLUG, user_autostart_dir

logger = logging.getLogger("driftgram.autostart")

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = APP_NAME
_DESKTOP_FILE = f"{APP_SLUG}.desktop"


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle rather than a checkout."""
    return getattr(sys, "frozen", False)


def launch_command() -> List[str]:
    """Argv that starts this same Driftgram again, minimised to the tray."""
    if is_frozen():
        return [sys.executable, "--tray"]
    # Development: re-run the module with the same interpreter. pythonw avoids
    # a console window flashing up on Windows at every login.
    interpreter = Path(sys.executable)
    if sys.platform == "win32":
        windowed = interpreter.with_name("pythonw.exe")
        if windowed.exists():
            interpreter = windowed
    return [str(interpreter), "-m", "src.gui", "--tray"]


def _quoted_command() -> str:
    argv = launch_command()
    if sys.platform == "win32":
        return " ".join(f'"{part}"' if " " in part else part for part in argv)
    return " ".join(shlex.quote(part) for part in argv)


# --------------------------------------------------------------------------
# Windows
# --------------------------------------------------------------------------


def _win_is_enabled() -> bool:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, _VALUE_NAME)
            return bool(value)
    except FileNotFoundError:
        return False
    except OSError:
        return False


def _win_set(enabled: bool) -> None:
    import winreg

    if enabled:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            winreg.SetValueEx(key, _VALUE_NAME, 0, winreg.REG_SZ, _quoted_command())
    else:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, _VALUE_NAME)
        except FileNotFoundError:
            pass


# --------------------------------------------------------------------------
# Linux
# --------------------------------------------------------------------------


def _desktop_path() -> Path:
    return user_autostart_dir() / _DESKTOP_FILE


def _linux_is_enabled() -> bool:
    path = _desktop_path()
    if not path.exists():
        return False
    try:
        # A .desktop file can exist but be switched off by the desktop's own
        # startup-applications UI, which writes Hidden=true rather than
        # deleting the file. Honour that, or the checkbox would lie.
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return "Hidden=true" not in text.replace(" ", "")


def _linux_set(enabled: bool) -> None:
    path = _desktop_path()
    if not enabled:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "[Desktop Entry]",
                "Type=Application",
                f"Name={APP_NAME}",
                "Comment=Keep your folders backed up to Telegram",
                f"Exec={_quoted_command()}",
                f"Icon={APP_SLUG}",
                "Terminal=false",
                "X-GNOME-Autostart-enabled=true",
                "",
            ]
        ),
        encoding="utf-8",
    )


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------


def supported() -> bool:
    return sys.platform in ("win32", "linux")


def is_enabled() -> bool:
    try:
        if sys.platform == "win32":
            return _win_is_enabled()
        if sys.platform == "linux":
            return _linux_is_enabled()
    except Exception:
        logger.exception("Could not read the start-at-login setting")
    return False


def set_enabled(enabled: bool) -> bool:
    """Apply the setting. Returns what the system reports afterwards.

    Deliberately does not raise: failing to register an autostart entry is an
    annoyance, not a reason to refuse to save the rest of the user's settings.
    The returned value is what the UI should show, which may not be what was
    asked for if the desktop refused.
    """
    try:
        if sys.platform == "win32":
            _win_set(enabled)
        elif sys.platform == "linux":
            _linux_set(enabled)
        else:
            return False
    except Exception:
        logger.exception("Could not change the start-at-login setting")
    return is_enabled()
