"""Driftgram: the page that answers 'is my stuff safe right now?'.

That question deserves a sentence, not a dashboard. The headline says the
state in plain words, the line under it says what is happening at this exact
moment, and everything else is secondary. A progress bar appears only while
something is actually moving, so a calm system looks calm.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..events import EventKind, RunState, SyncEvent
from ..fsutil import human_bytes
from .bridge import watch
from .context import AppContext
from .widgets import Card, StatTile, hint, label, reveal, section, show_error, title

#: What each engine state is called in the window, and whether it is a problem.
STATE_WORDS = {
    RunState.STOPPED: ("Not running", "Driftgram isn't syncing at the moment."),
    RunState.CONNECTING: ("Connecting…", "Reaching Telegram."),
    RunState.LOGIN_REQUIRED: ("Sign in needed", "Driftgram has been signed out of Telegram."),
    RunState.SCANNING: ("Checking your folders…", "Looking for anything that changed."),
    RunState.SYNCING: ("Backing up…", "Transferring files."),
    RunState.IDLE: ("Everything is backed up", "Watching your folders for changes."),
    RunState.PAUSED: ("Paused", "Nothing will be backed up until you resume."),
    RunState.OFFLINE: ("Offline", "Waiting for a connection to Telegram."),
    RunState.ERROR: ("Something needs attention", "See Activity for details."),
}

RECENT_LIMIT = 6


class StatusPage(QWidget):
    def __init__(self, context: AppContext, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.context = context
        self._state = RunState.STOPPED

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        layout.addWidget(title("Status"))

        # --- the headline card ---
        status_card = Card()
        self.headline = label("Starting…", "StatusHeadline")
        self.detail = label("", "StatusDetail", wrap=True)
        status_card.add(self.headline)
        status_card.add(self.detail)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        self.progress.hide()
        status_card.add(self.progress)

        buttons = QWidget()
        button_row = QHBoxLayout(buttons)
        button_row.setContentsMargins(0, 6, 0, 0)
        button_row.setSpacing(8)
        self.pause_button = QPushButton("Pause")
        self.pause_button.clicked.connect(self._toggle_pause)
        self.sync_button = QPushButton("Back up now")
        self.sync_button.setObjectName("Primary")
        self.sync_button.clicked.connect(self._sync_now)
        button_row.addWidget(self.sync_button)
        button_row.addWidget(self.pause_button)
        button_row.addStretch(1)
        status_card.add(buttons)
        layout.addWidget(status_card)

        # --- numbers ---
        stats_card = Card()
        stats_row = QWidget()
        stats_layout = QHBoxLayout(stats_row)
        stats_layout.setContentsMargins(0, 0, 0, 0)
        self.files_tile = StatTile("0", "FILES BACKED UP")
        self.size_tile = StatTile("0 B", "TOTAL SIZE")
        self.folders_tile = StatTile("0", "FOLDERS WATCHED")
        for tile in (self.files_tile, self.size_tile, self.folders_tile):
            stats_layout.addWidget(tile, 1)
        stats_card.add(stats_row)
        layout.addWidget(stats_card)

        # --- recent activity ---
        recent_card = Card()
        recent_card.add(section("Recent activity"))
        self.recent = QListWidget()
        self.recent.setObjectName("ActivityList")
        self.recent.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.recent.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.recent.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        recent_card.add(self.recent)
        layout.addWidget(recent_card)

        layout.addStretch(1)

        self._fit_recent()
        context.signals.event.connect(self.on_event)
        self.refresh()

    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Re-read what doesn't arrive as an event: config and manifest totals."""
        self.folders_tile.set_value(str(len(self.context.config.roots)))
        watch(self.context.supervisor.stats(), on_success=self._apply_stats)

    def _apply_stats(self, stats) -> None:
        count, total = stats
        self.files_tile.set_value(f"{count:,}")
        self.size_tile.set_value(human_bytes(total))

    def _set_state(self, state: RunState, message: str = "") -> None:
        self._state = state
        headline, default_detail = STATE_WORDS.get(state, ("Working…", ""))
        self.headline.setText(headline)
        self.detail.setText(message or default_detail)
        self.pause_button.setText("Resume" if state == RunState.PAUSED else "Pause")
        self.sync_button.setEnabled(state not in (RunState.STOPPED, RunState.LOGIN_REQUIRED))
        if state not in (RunState.SYNCING, RunState.SCANNING):
            self.progress.hide()

    def on_event(self, event: SyncEvent) -> None:
        if event.kind == EventKind.STATUS and event.state is not None:
            self._set_state(event.state, event.message or "")
            if event.state == RunState.IDLE:
                self.refresh()
            return

        if event.kind in (EventKind.UPLOAD_PROGRESS, EventKind.DOWNLOAD_PROGRESS):
            fraction = event.fraction
            if fraction is not None:
                verb = "Backing up" if event.kind == EventKind.UPLOAD_PROGRESS else "Downloading"
                self.progress.setValue(int(fraction * 100))
                self.progress.show()
                self.detail.setText(
                    f"{verb} {event.rel_path} — {human_bytes(event.bytes_done)} "
                    f"of {human_bytes(event.bytes_total)}"
                )
            return

        if event.kind in (EventKind.SCAN_PROGRESS, EventKind.SCAN_FINISHED):
            self.detail.setText(event.message or "")
            return

        if event.kind in (
            EventKind.UPLOAD_FINISHED,
            EventKind.DOWNLOAD_FINISHED,
            EventKind.CONFLICT,
            EventKind.LOCAL_DELETED,
            EventKind.REMOTE_DELETED,
            EventKind.ERROR,
        ):
            self.progress.hide()
            self._push_recent(event)
            if event.kind in (EventKind.UPLOAD_FINISHED, EventKind.DOWNLOAD_FINISHED):
                self.refresh()

    def _push_recent(self, event: SyncEvent) -> None:
        stamp = datetime.now().strftime("%H:%M")
        self.recent.insertItem(0, f"{stamp}   {event.summary()}")
        while self.recent.count() > RECENT_LIMIT:
            self.recent.takeItem(self.recent.count() - 1)
        self._fit_recent()

    def _fit_recent(self) -> None:
        """Grow the list to fit its rows instead of scrolling them out of sight.

        A fixed pixel height guesses at the row height and gets it wrong on
        any machine with a different font or scaling factor, which silently
        hides the most recent entries - the ones that matter most here.
        """
        count = self.recent.count()
        if not count:
            self.recent.setFixedHeight(0)
            return
        row_height = self.recent.sizeHintForRow(0)
        self.recent.setFixedHeight(count * row_height + 6)

    # ------------------------------------------------------------------

    def _toggle_pause(self) -> None:
        pausing = self._state != RunState.PAUSED
        self.pause_button.setEnabled(False)
        watch(
            self.context.supervisor.set_paused(pausing),
            on_success=lambda _: self.pause_button.setEnabled(True),
            on_error=self._report,
        )

    def _sync_now(self) -> None:
        self.sync_button.setEnabled(False)
        watch(
            self.context.supervisor.sync_now(),
            on_success=lambda _: self.sync_button.setEnabled(True),
            on_error=self._report,
        )

    def _report(self, error: BaseException) -> None:
        self.pause_button.setEnabled(True)
        self.sync_button.setEnabled(True)
        show_error(self, error)
