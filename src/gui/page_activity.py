"""Driftgram: a plain-language log of what the app has been doing.

Deliberately not the technical log. The rotating file in the data folder is
there for diagnosing problems; this is there so a user can confirm that the
thing they just saved really did get backed up, and see why something was
skipped without reading a stack trace.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..events import EventKind, SyncEvent
from .context import AppContext
from .theme import current_palette
from .widgets import Card, hint, reveal, title

#: Enough to cover a working session without letting the list grow unbounded.
MAX_ROWS = 500

#: Events worth showing a person. Progress ticks and status changes are not:
#: they are already on the status page, and here they would drown everything.
INTERESTING = {
    EventKind.UPLOAD_FINISHED,
    EventKind.DOWNLOAD_FINISHED,
    EventKind.SKIPPED,
    EventKind.LOCAL_DELETED,
    EventKind.REMOTE_DELETED,
    EventKind.CONFLICT,
    EventKind.ERROR,
    EventKind.SCAN_FINISHED,
}

NEEDS_ATTENTION = {EventKind.ERROR, EventKind.CONFLICT, EventKind.SKIPPED}


class ActivityPage(QWidget):
    def __init__(self, context: AppContext, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.context = context
        self._palette = current_palette()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)
        layout.addWidget(title("Activity"))
        layout.addWidget(hint("What Driftgram has done since it started."))

        card = Card()
        controls = QWidget()
        row = QHBoxLayout(controls)
        row.setContentsMargins(0, 0, 0, 0)
        self.only_attention = QCheckBox("Only show things that need attention")
        self.only_attention.toggled.connect(self._apply_filter)
        row.addWidget(self.only_attention)
        row.addStretch(1)
        log_button = QPushButton("Open log folder")
        log_button.clicked.connect(lambda: reveal(self.context.config.paths.data_dir))
        clear_button = QPushButton("Clear")
        clear_button.clicked.connect(self._clear)
        row.addWidget(log_button)
        row.addWidget(clear_button)
        card.add(controls)

        self.list = QListWidget()
        self.list.setObjectName("ActivityList")
        self.list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.list.setWordWrap(True)
        card.add(self.list)
        card.body.setStretchFactor(self.list, 1)

        layout.addWidget(card, 1)
        context.signals.event.connect(self.on_event)

    # ------------------------------------------------------------------

    def on_event(self, event: SyncEvent) -> None:
        if event.kind not in INTERESTING:
            return
        stamp = datetime.now().strftime("%H:%M:%S")
        item = QListWidgetItem(f"{stamp}   {event.summary()}")
        needs_attention = event.kind in NEEDS_ATTENTION
        item.setData(Qt.ItemDataRole.UserRole, needs_attention)
        if event.kind == EventKind.ERROR:
            item.setForeground(QColor(self._palette.danger))
        elif needs_attention:
            item.setForeground(QColor(self._palette.warning))
        if event.rel_path:
            item.setToolTip(event.rel_path)

        self.list.insertItem(0, item)
        item.setHidden(self.only_attention.isChecked() and not needs_attention)
        while self.list.count() > MAX_ROWS:
            self.list.takeItem(self.list.count() - 1)

    def _apply_filter(self, only_attention: bool) -> None:
        for index in range(self.list.count()):
            item = self.list.item(index)
            item.setHidden(only_attention and not bool(item.data(Qt.ItemDataRole.UserRole)))

    def _clear(self) -> None:
        self.list.clear()
