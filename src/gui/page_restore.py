"""Driftgram: getting files back out of Telegram.

The running sync only ever looks at messages newer than the offset it has
already processed, so a file deleted locally after it was uploaded never
returns on its own. Recovering it means walking the entire chat history,
which is slow and pointless to do on a timer - so it is a button.

The command-line version of this had to be run as a separate process, with a
warning to stop the sync tool first because they would fight over the session
file. Here it runs inside the same process, on the same client, so that whole
class of problem simply does not exist.
"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..fsutil import human_bytes
from ..sync_engine import RemoteFile
from .bridge import watch
from .context import AppContext
from .widgets import Card, confirm, hint, muted, show_error, title


class RestorePage(QWidget):
    def __init__(self, context: AppContext, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.context = context
        self._files: List[RemoteFile] = []
        self._busy = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)
        layout.addWidget(title("Restore"))
        layout.addWidget(
            hint(
                "Everything Driftgram has ever backed up is still in Telegram, even if you "
                "deleted it here. Look it up and bring back whatever you need."
            )
        )

        card = Card()

        controls = QWidget()
        row = QHBoxLayout(controls)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.look_button = QPushButton("Look in Telegram")
        self.look_button.setObjectName("Primary")
        self.look_button.clicked.connect(self._load)
        row.addWidget(self.look_button)

        self.filter_entry = QLineEdit()
        self.filter_entry.setPlaceholderText("Filter by name…")
        self.filter_entry.textChanged.connect(self._apply_filter)
        self.filter_entry.setEnabled(False)
        row.addWidget(self.filter_entry, 1)

        self.only_missing = QCheckBox("Only files missing from this computer")
        self.only_missing.setChecked(True)
        self.only_missing.toggled.connect(self._apply_filter)
        self.only_missing.setEnabled(False)
        row.addWidget(self.only_missing)
        card.add(controls)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # indeterminate: the history length is unknown
        self.progress.hide()
        card.add(self.progress)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["", "File", "Size", "Status"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        header = self.table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 34)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemChanged.connect(lambda _: self._sync_buttons())
        card.add(self.table)
        card.body.setStretchFactor(self.table, 1)

        actions = QWidget()
        action_row = QHBoxLayout(actions)
        action_row.setContentsMargins(0, 6, 0, 0)
        action_row.setSpacing(8)
        self.select_all = QPushButton("Select all")
        self.select_all.clicked.connect(lambda: self._set_all(True))
        self.select_none = QPushButton("Select none")
        self.select_none.clicked.connect(lambda: self._set_all(False))
        self.restore_button = QPushButton("Restore selected")
        self.restore_button.setObjectName("Primary")
        self.restore_button.clicked.connect(self._restore)
        action_row.addWidget(self.restore_button)
        action_row.addWidget(self.select_all)
        action_row.addWidget(self.select_none)
        action_row.addStretch(1)
        self.summary = muted("")
        action_row.addWidget(self.summary)
        card.add(actions)

        layout.addWidget(card, 1)
        self._sync_buttons()

    # ------------------------------------------------------------------
    # loading
    # ------------------------------------------------------------------

    def _load(self) -> None:
        self._set_busy(True, "Reading your Telegram history…")
        watch(self.context.supervisor.list_remote(), on_success=self._loaded, on_error=self._failed)

    def _loaded(self, files) -> None:
        self._files = list(files or [])
        self._set_busy(False)
        self.filter_entry.setEnabled(True)
        self.only_missing.setEnabled(True)
        self._populate()
        if not self._files:
            self.context.notify("Nothing backed up in Telegram yet.")

    def _failed(self, error: BaseException) -> None:
        self._set_busy(False)
        show_error(self, error)

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self._busy = busy
        self.progress.setVisible(busy)
        self.look_button.setEnabled(not busy)
        self.look_button.setText(message if busy else "Look in Telegram")
        self._sync_buttons()

    # ------------------------------------------------------------------
    # table
    # ------------------------------------------------------------------

    def _populate(self) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(len(self._files))
        for index, item in enumerate(self._files):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            # Pre-tick what is actually missing: that is the common case, and
            # it makes "look, then restore" a two-click job.
            check.setCheckState(
                Qt.CheckState.Checked if not item.exists_locally else Qt.CheckState.Unchecked
            )
            self.table.setItem(index, 0, check)

            name = QTableWidgetItem(f"{item.alias}/{item.rel_path}")
            name.setToolTip(str(item.local_path))
            self.table.setItem(index, 1, name)
            self.table.setItem(index, 2, QTableWidgetItem(human_bytes(item.size)))

            if item.exists_locally:
                status = "Already here"
            elif item.ignored:
                status = "Missing (matches a skip rule)"
            else:
                status = "Missing"
            self.table.setItem(index, 3, QTableWidgetItem(status))
        self.table.blockSignals(False)
        self._apply_filter()

    def _apply_filter(self) -> None:
        needle = self.filter_entry.text().strip().lower()
        only_missing = self.only_missing.isChecked()
        visible = 0
        for index, item in enumerate(self._files):
            hidden = (only_missing and item.exists_locally) or (
                needle and needle not in f"{item.alias}/{item.rel_path}".lower()
            )
            self.table.setRowHidden(index, bool(hidden))
            visible += 0 if hidden else 1
        self.summary.setText(f"{visible} of {len(self._files)} shown")
        self._sync_buttons()

    def _set_all(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self.table.blockSignals(True)
        for index in range(self.table.rowCount()):
            if not self.table.isRowHidden(index):
                self.table.item(index, 0).setCheckState(state)
        self.table.blockSignals(False)
        self._sync_buttons()

    def _checked_files(self) -> List[RemoteFile]:
        """Ticked *and* visible rows only.

        Hidden rows are excluded deliberately. A row can keep its tick while a
        filter hides it - "Select none" only reaches what is on screen, as
        users expect - and restoring something the user cannot see, possibly
        over the top of a local file, is exactly the kind of surprise this
        page must never spring. What is shown and ticked is what gets
        restored, and the button's count says so.
        """
        chosen = []
        for index, item in enumerate(self._files):
            if self.table.isRowHidden(index):
                continue
            cell = self.table.item(index, 0)
            if cell is not None and cell.checkState() == Qt.CheckState.Checked:
                chosen.append(item)
        return chosen

    def _sync_buttons(self) -> None:
        has_rows = self.table.rowCount() > 0
        self.select_all.setEnabled(has_rows and not self._busy)
        self.select_none.setEnabled(has_rows and not self._busy)
        count = len(self._checked_files()) if has_rows else 0
        self.restore_button.setEnabled(bool(count) and not self._busy)
        self.restore_button.setText(
            f"Restore {count} file{'s' if count != 1 else ''}" if count else "Restore selected"
        )

    # ------------------------------------------------------------------
    # restoring
    # ------------------------------------------------------------------

    def _restore(self) -> None:
        chosen = self._checked_files()
        if not chosen:
            return
        existing = [item for item in chosen if item.exists_locally]
        overwrite = False
        if existing:
            overwrite = confirm(
                self,
                f"{len(existing)} of these are already on this computer.",
                "Replacing them with the Telegram copy will discard whatever is here now. "
                "Choose Skip to restore only the missing ones.",
                ok_text="Replace them",
            )
            if not overwrite:
                chosen = [item for item in chosen if not item.exists_locally]
                if not chosen:
                    return

        self._set_busy(True, "Restoring…")
        watch(
            self.context.supervisor.restore(chosen, overwrite=overwrite),
            on_success=self._restored,
            on_error=self._failed,
        )

    def _restored(self, count) -> None:
        self._set_busy(False)
        self.context.notify(f"Restored {count} file{'s' if count != 1 else ''}.")
        # Statuses are now stale - everything just restored exists locally.
        self._load()
