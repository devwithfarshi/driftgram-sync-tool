"""Driftgram: managing which folders are backed up.

Adding a folder is the one action here with a real constraint behind it - the
engine cannot represent a folder nested inside another folder, because a path
would then belong to two roots. Rather than explain that, the picker simply
refuses the choice and says which existing folder is in the way.

Removing a folder deliberately does not delete anything from Telegram. It
stops watching, forgets the local bookkeeping, and leaves the backup intact,
which is what "remove" almost always means to the person clicking it.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..config import RootConfig, root_conflict, suggest_alias
from .context import AppContext
from .widgets import Card, confirm, hint, muted, reveal, show_error, title


class IgnoreDialog(QDialog):
    """Edit one folder's skip-list, one pattern per line."""

    def __init__(self, root: RootConfig, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle(f"Skip rules for {root.path.name or root.path}")
        self.setMinimumSize(500, 380)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)
        layout.addWidget(
            hint(
                "Anything matching one of these is left out of the backup. Put one rule per "
                "line. A name on its own skips that file; a name ending in / skips a whole "
                "folder; * stands for any text."
            )
        )
        self.editor = QPlainTextEdit("\n".join(root.ignore))
        self.editor.setPlaceholderText("node_modules/\n*.log\ndrafts/")
        layout.addWidget(self.editor, 1)
        layout.addWidget(
            muted("Examples:   *.mp4   ·   node_modules/   ·   old backups/   ·   ~$*")
        )

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def patterns(self) -> list:
        return [line.strip() for line in self.editor.toPlainText().splitlines() if line.strip()]


class FoldersPage(QWidget):
    def __init__(self, context: AppContext, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.context = context

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)
        layout.addWidget(title("Folders"))
        layout.addWidget(
            hint(
                "These folders are kept backed up, including everything inside them. "
                "Removing one here stops watching it - your files in Telegram stay where "
                "they are."
            )
        )

        card = Card()
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Folder", "Tagged as", "Skip rules"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._sync_buttons)
        self.table.doubleClicked.connect(self._edit_ignores)
        card.add(self.table)

        buttons = QWidget()
        row = QHBoxLayout(buttons)
        row.setContentsMargins(0, 6, 0, 0)
        row.setSpacing(8)
        self.add_button = QPushButton("Add a folder…")
        self.add_button.setObjectName("Primary")
        self.add_button.clicked.connect(self._add)
        self.ignore_button = QPushButton("Edit skip rules…")
        self.ignore_button.clicked.connect(self._edit_ignores)
        self.open_button = QPushButton("Open folder")
        self.open_button.clicked.connect(self._open)
        self.remove_button = QPushButton("Remove")
        self.remove_button.setObjectName("DangerButton")
        self.remove_button.clicked.connect(self._remove)
        for button in (self.add_button, self.ignore_button, self.open_button, self.remove_button):
            row.addWidget(button)
        row.addStretch(1)
        card.add(buttons)

        layout.addWidget(card, 1)
        self.refresh()

    # ------------------------------------------------------------------

    def refresh(self) -> None:
        roots = self.context.config.roots
        self.table.setRowCount(len(roots))
        for index, root in enumerate(roots):
            path_item = QTableWidgetItem(str(root.path))
            if not root.path.exists():
                path_item.setText(f"{root.path}   (not found)")
                path_item.setToolTip(
                    "This folder isn't there right now. If it's on a removable or network "
                    "drive, reconnect it and Driftgram will pick up where it left off."
                )
            self.table.setItem(index, 0, path_item)
            self.table.setItem(index, 1, QTableWidgetItem(root.alias))
            count = len(root.ignore)
            summary = "none" if not count else f"{count} rule{'s' if count != 1 else ''}"
            self.table.setItem(index, 2, QTableWidgetItem(summary))
        self._sync_buttons()

    def _selected_index(self) -> int:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        return rows[0].row() if rows else -1

    def _sync_buttons(self) -> None:
        has_selection = self._selected_index() >= 0
        for button in (self.ignore_button, self.open_button, self.remove_button):
            button.setEnabled(has_selection)

    # ------------------------------------------------------------------

    def _add(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Choose a folder to back up", str(Path.home()))
        if not chosen:
            return
        path = Path(chosen)
        problem = root_conflict(path, self.context.config.roots)
        if problem:
            show_error(self, ValueError(problem), "That folder can't be added")
            return
        alias = suggest_alias(path, [r.alias for r in self.context.config.roots])
        self.context.config.roots.append(RootConfig(path=path, alias=alias, ignore=[]))
        self.refresh()
        self.context.apply_and_restart()
        self.context.notify(f"Now backing up {path.name or path}")

    def _remove(self) -> None:
        index = self._selected_index()
        if index < 0:
            return
        root = self.context.config.roots[index]
        if not confirm(
            self,
            f"Stop backing up {root.path.name or root.path}?",
            "The copies already in Telegram are left alone - this only stops watching "
            "the folder from now on.",
            ok_text="Stop backing up",
        ):
            return
        self.context.config.roots.pop(index)
        self.refresh()
        self.context.apply_and_restart()
        self.context.notify(f"Stopped backing up {root.path.name or root.path}")

    def _edit_ignores(self) -> None:
        index = self._selected_index()
        if index < 0:
            return
        root = self.context.config.roots[index]
        dialog = IgnoreDialog(root, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        root.ignore = dialog.patterns()
        self.refresh()
        self.context.apply_and_restart()
        self.context.notify("Skip rules updated")

    def _open(self) -> None:
        index = self._selected_index()
        if index >= 0:
            reveal(self.context.config.roots[index].path)
