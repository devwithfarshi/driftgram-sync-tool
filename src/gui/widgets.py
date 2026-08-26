"""Driftgram: the handful of widgets every page reuses.

Small on purpose. The value is consistency - one definition of what a card
looks like, one way of showing an error, one way of opening a folder - so
that pages read as layout rather than as styling.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..errors import DriftgramError


class Card(QFrame):
    """A bordered panel with a vertical layout, used for every block of content."""

    def __init__(self, parent: Optional[QWidget] = None, tight: bool = False):
        super().__init__(parent)
        self.setObjectName("CardTight" if tight else "Card")
        self.body = QVBoxLayout(self)
        margin = 14 if tight else 18
        self.body.setContentsMargins(margin, margin, margin, margin)
        self.body.setSpacing(10)

    def add(self, widget: QWidget) -> QWidget:
        self.body.addWidget(widget)
        return widget


def label(text: str, name: str = "", wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    if name:
        widget.setObjectName(name)
    widget.setWordWrap(wrap)
    if wrap:
        widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
    return widget


def title(text: str) -> QLabel:
    return label(text, "PageTitle")


def hint(text: str) -> QLabel:
    return label(text, "PageHint", wrap=True)


def muted(text: str) -> QLabel:
    return label(text, "Muted", wrap=True)


def section(text: str) -> QLabel:
    return label(text, "SectionTitle")


def separator() -> QFrame:
    line = QFrame()
    line.setObjectName("Separator")
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFixedHeight(1)
    return line


class StatTile(QWidget):
    """One big number with a caption - the status page's headline figures."""

    def __init__(self, value: str, caption: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.value_label = label(value, "StatNumber")
        layout.addWidget(self.value_label)
        layout.addWidget(label(caption, "StatLabel"))

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)


def row(*widgets: QWidget, spacing: int = 8, stretch_last: bool = False) -> QWidget:
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(spacing)
    for index, widget in enumerate(widgets):
        layout.addWidget(widget, 1 if (stretch_last and index == len(widgets) - 1) else 0)
    if not stretch_last:
        layout.addStretch(1)
    return container


def show_error(parent: Optional[QWidget], error: BaseException, fallback_title: str = "Something went wrong") -> None:
    """Report a failure using the message the error was written to carry.

    DriftgramError splits what happened from what to do about it, which maps
    exactly onto a message box's text and informative text. Anything else is
    an unexpected bug, so it gets a generic heading and the raw detail.
    """
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    if isinstance(error, DriftgramError):
        box.setText(error.message)
        if error.hint:
            box.setInformativeText(error.hint)
    else:
        box.setText(fallback_title)
        box.setInformativeText(str(error) or error.__class__.__name__)
    box.setWindowTitle("Driftgram")
    box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    box.exec()


def confirm(parent: Optional[QWidget], question: str, detail: str = "", ok_text: str = "OK") -> bool:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle("Driftgram")
    box.setText(question)
    if detail:
        box.setInformativeText(detail)
    ok = box.addButton(ok_text, QMessageBox.ButtonRole.AcceptRole)
    box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
    box.exec()
    return box.clickedButton() is ok


def reveal(path: Path) -> None:
    """Open a folder in the system file manager (or the containing folder of a file)."""
    target = path if path.is_dir() else path.parent
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))


def open_url(url: str) -> None:
    QDesktopServices.openUrl(QUrl(url))
