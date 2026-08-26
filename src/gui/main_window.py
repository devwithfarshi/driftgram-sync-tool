"""Driftgram: the main window - a sidebar and five pages.

Closing the window does not quit. For a background sync tool that would be
the wrong instinct made permanent, so the window hides to the tray instead
and says so the first time, once. Where there is no tray to hide in - some
Linux desktops have none - closing really does quit, because hiding into
somewhere the user cannot reach would be worse.
"""
from __future__ import annotations

import logging
from typing import Callable, List, Optional

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..events import EventKind, RunState, SyncEvent
from .context import AppContext
from .icons import app_icon, app_pixmap
from .page_activity import ActivityPage
from .page_folders import FoldersPage
from .page_restore import RestorePage
from .page_settings import SettingsPage
from .page_status import StatusPage
from .widgets import label

logger = logging.getLogger("driftgram.gui.window")

NAV = [
    ("Status", "status"),
    ("Folders", "folders"),
    ("Activity", "activity"),
    ("Restore", "restore"),
    ("Settings", "settings"),
]


class MainWindow(QWidget):
    #: Emitted when the window hides itself instead of closing, so the tray can
    #: say so - a toast in a hidden window would be a message nobody sees.
    hidden_to_tray = Signal(str)

    def __init__(
        self,
        context: AppContext,
        on_quit: Callable[[], None],
        can_hide_to_tray: bool,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.context = context
        self._on_quit = on_quit
        self._can_hide_to_tray = can_hide_to_tray
        self._warned_about_hiding = False
        self._force_quit = False

        self.setWindowTitle("Driftgram")
        self.setWindowIcon(app_icon())
        self.resize(940, 680)
        self.setMinimumSize(780, 560)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_sidebar())

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        self.stack = QStackedWidget()
        self.status_page = StatusPage(context)
        self.folders_page = FoldersPage(context)
        self.activity_page = ActivityPage(context)
        self.restore_page = RestorePage(context)
        self.settings_page = SettingsPage(context)
        for page in (
            self.status_page,
            self.folders_page,
            self.activity_page,
            self.restore_page,
            self.settings_page,
        ):
            self.stack.addWidget(page)
        right_layout.addWidget(self.stack, 1)

        self.toast = label("", "Muted")
        self.toast.setContentsMargins(28, 0, 28, 10)
        self.toast.hide()
        right_layout.addWidget(self.toast)

        root.addWidget(right, 1)

        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self.toast.hide)

        context.signals.event.connect(self._on_event)
        self._select(0)

    # ------------------------------------------------------------------

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(198)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(14, 18, 14, 14)
        layout.setSpacing(4)

        brand = QWidget()
        brand_layout = QHBoxLayout(brand)
        brand_layout.setContentsMargins(4, 0, 0, 14)
        brand_layout.setSpacing(10)
        mark = QLabel()
        mark.setPixmap(app_pixmap(32))
        brand_layout.addWidget(mark)
        names = QWidget()
        names_layout = QVBoxLayout(names)
        names_layout.setContentsMargins(0, 0, 0, 0)
        names_layout.setSpacing(0)
        names_layout.addWidget(label("Driftgram", "BrandName"))
        names_layout.addWidget(label("Folders ↔ Telegram", "BrandTag"))
        brand_layout.addWidget(names)
        brand_layout.addStretch(1)
        layout.addWidget(brand)

        self._nav_buttons: List[QPushButton] = []
        for index, (text, _key) in enumerate(NAV):
            button = QPushButton(text)
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, i=index: self._select(i))
            layout.addWidget(button)
            self._nav_buttons.append(button)

        layout.addStretch(1)
        self.sidebar_status = label("", "BrandTag")
        self.sidebar_status.setWordWrap(True)
        self.sidebar_status.setContentsMargins(4, 0, 0, 0)
        layout.addWidget(self.sidebar_status)
        return sidebar

    def _select(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        for position, button in enumerate(self._nav_buttons):
            button.setChecked(position == index)
        if index == 0:
            self.status_page.refresh()
        elif index == 1:
            self.folders_page.refresh()

    def show_page(self, key: str) -> None:
        for index, (_text, name) in enumerate(NAV):
            if name == key:
                self._select(index)
                return

    # ------------------------------------------------------------------

    def notify(self, message: str) -> None:
        """A quiet one-line confirmation under the page, gone after a few seconds."""
        self.toast.setText(message)
        self.toast.show()
        self._toast_timer.start(4000)

    def _on_event(self, event: SyncEvent) -> None:
        if event.kind == EventKind.STATUS and event.state is not None:
            words = {
                RunState.IDLE: "Up to date",
                RunState.SYNCING: "Backing up…",
                RunState.SCANNING: "Checking…",
                RunState.PAUSED: "Paused",
                RunState.OFFLINE: "Offline",
                RunState.LOGIN_REQUIRED: "Sign in needed",
                RunState.ERROR: "Needs attention",
                RunState.CONNECTING: "Connecting…",
                RunState.STOPPED: "Stopped",
            }
            self.sidebar_status.setText(words.get(event.state, ""))

    # ------------------------------------------------------------------

    def request_quit(self) -> None:
        """Really exit, rather than hiding - used by the tray's Quit item."""
        self._force_quit = True
        self.close()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._force_quit or not self._can_hide_to_tray or not self.context.config.app.minimize_to_tray:
            event.accept()
            self._on_quit()
            return

        event.ignore()
        self.hide()
        if not self._warned_about_hiding:
            self._warned_about_hiding = True
            # Said once, and only once: a message every time would be nagging,
            # but saying nothing the first time looks like the app crashed.
            self.hidden_to_tray.emit(
                "Driftgram is still running here. Click the icon to open it again."
            )
