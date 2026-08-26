"""Driftgram: shared exception types.

The CLI can afford to print a message and call sys.exit(); a GUI cannot -
a failed config load has to become a dialog, not a dead process. Every
recoverable failure therefore raises one of these instead of exiting, and
each carries a message written for a non-technical user to read verbatim.
"""
from __future__ import annotations

from typing import Optional


class DriftgramError(Exception):
    """Base class for errors that are safe to show a user directly."""

    def __init__(self, message: str, hint: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.hint = hint

    def __str__(self) -> str:
        return f"{self.message}\n\n{self.hint}" if self.hint else self.message


class ConfigError(DriftgramError):
    """Configuration is missing, malformed, or incomplete."""


class NotConfiguredError(ConfigError):
    """No config exists yet - the app should run first-time setup."""


class WatcherError(DriftgramError):
    """The filesystem watcher could not be started for a folder."""


class LoginRequiredError(DriftgramError):
    """Telegram session is missing or has been revoked."""


class AlreadyRunningError(DriftgramError):
    """Another Driftgram process holds the lock on this data directory."""
