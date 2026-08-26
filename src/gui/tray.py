"""Driftgram: the notification-area icon.

A background sync tool lives here most of its life, so the icon has to carry
the whole status on its own - hence the coloured badge and a tooltip that
says the same thing in words, for anyone who can't rely on colour alone.

Not every desktop has a tray. GNOME dropped the legacy protocol and only
shows StatusNotifierItem icons when an extension provides them, so
`available()` may be False on a perfectly healthy Linux system. Callers must
handle that rather than assume the icon is there - otherwise closing the
window would hide the app somewhere the user cannot get it back from.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

from ..events import EventKind, RunState, SyncEvent
from .icons import status_icon

logger = logging.getLogger("driftgram.gui.tray")

TOOLTIPS = {
    RunState.STOPPED: "Driftgram - not running",
    RunState.CONNECTING: "Driftgram - connecting",
    RunState.LOGIN_REQUIRED: "Driftgram - sign in needed",
    RunState.SCANNING: "Driftgram - checking your folders",
    RunState.SYNCING: "Driftgram - backing up",
    RunState.IDLE: "Driftgram - everything is backed up",
    RunState.PAUSED: "Driftgram - paused",
    RunState.OFFLINE: "Driftgram - offline",
    RunState.ERROR: "Driftgram - needs attention",
}


def available() -> bool:
    return QSystemTrayIcon.isSystemTrayAvailable()


class Tray(QSystemTrayIcon):
    def __init__(
        self,
        on_open: Callable[[], None],
        on_toggle_pause: Callable[[], None],
        on_sync_now: Callable[[], None],
        on_quit: Callable[[], None],
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._on_toggle_pause = on_toggle_pause
        self._paused = False
        self._notifications_enabled = True

        self.setIcon(status_icon(RunState.STOPPED))
        self.setToolTip(TOOLTIPS[RunState.STOPPED])

        menu = QMenu()
        self._open_action = QAction("Open Driftgram", self)
        self._open_action.triggered.connect(on_open)
        menu.addAction(self._open_action)

        self._pause_action = QAction("Pause", self)
        self._pause_action.triggered.connect(on_toggle_pause)
        menu.addAction(self._pause_action)

        sync_action = QAction("Back up now", self)
        sync_action.triggered.connect(on_sync_now)
        menu.addAction(sync_action)

        menu.addSeparator()
        quit_action = QAction("Quit Driftgram", self)
        quit_action.triggered.connect(on_quit)
        menu.addAction(quit_action)

        self.setContextMenu(menu)
        self._menu = menu  # keep a reference: Qt does not own it
        self.activated.connect(lambda reason: on_open() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)

    def set_notifications_enabled(self, enabled: bool) -> None:
        self._notifications_enabled = enabled

    def on_event(self, event: SyncEvent) -> None:
        if event.kind == EventKind.STATUS and event.state is not None:
            self.setIcon(status_icon(event.state))
            self.setToolTip(event.message or TOOLTIPS.get(event.state, "Driftgram"))
            self._paused = event.state == RunState.PAUSED
            self._pause_action.setText("Resume" if self._paused else "Pause")
            return

        if not self._notifications_enabled:
            return

        # Only two things are worth interrupting someone for: a conflict, where
        # a decision was made on their behalf, and an error they may need to
        # act on. Routine transfers stay silent.
        if event.kind == EventKind.CONFLICT:
            self.showMessage(
                "Kept both copies",
                f"{event.rel_path} changed in both places. {event.message or ''}".strip(),
                QSystemTrayIcon.MessageIcon.Information,
                8000,
            )
        elif event.kind == EventKind.ERROR:
            self.showMessage(
                "Driftgram needs attention",
                event.message or "Something went wrong.",
                QSystemTrayIcon.MessageIcon.Warning,
                8000,
            )
