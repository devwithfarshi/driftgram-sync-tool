"""Driftgram: the app icon and the tray status icons, drawn rather than shipped.

Drawing them with QPainter instead of bundling PNGs means one definition
renders crisply at 16px in a tray, at 256px in an installer, and at whatever
odd size a Linux desktop asks for - no blurry upscales and no set of files to
keep in sync. packaging/make_icons.py calls straight into here to produce the
.ico and .png that the Windows installer and the .desktop entry need.

The mark is a sync loop: an almost-closed ring with an arrowhead, which stays
legible when it is sixteen pixels across and half of that is padding.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Dict, Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)

from ..events import RunState

BRAND_TOP = "#38B6F1"
BRAND_BOTTOM = "#1C82C4"

#: The dot painted over the tray icon. Colour carries the meaning at a glance;
#: the tooltip carries it in words for anyone who can't rely on colour.
STATUS_COLORS: Dict[RunState, Optional[str]] = {
    RunState.IDLE: "#3DBE6C",
    RunState.SYNCING: "#38B6F1",
    RunState.SCANNING: "#38B6F1",
    RunState.CONNECTING: "#F2B33D",
    RunState.PAUSED: "#8E97A3",
    RunState.OFFLINE: "#8E97A3",
    RunState.LOGIN_REQUIRED: "#F2B33D",
    RunState.ERROR: "#E5484D",
    RunState.STOPPED: "#8E97A3",
}


def _draw_mark(painter: QPainter, size: int) -> None:
    """The rounded tile and the sync ring, sized relative to `size`."""
    rect = QRectF(0, 0, size, size)

    gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
    gradient.setColorAt(0.0, QColor(BRAND_TOP))
    gradient.setColorAt(1.0, QColor(BRAND_BOTTOM))

    tile = QPainterPath()
    tile.addRoundedRect(rect, size * 0.23, size * 0.23)
    painter.fillPath(tile, QBrush(gradient))

    # The ring: an arc left open at the top right, where the arrowhead sits.
    stroke = max(1.5, size * 0.105)
    inset = size * 0.28
    ring = QRectF(inset, inset, size - inset * 2, size - inset * 2)

    pen = QPen(QColor(255, 255, 255, 240))
    pen.setWidthF(stroke)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawArc(ring, int(75 * 16), int(-300 * 16))

    # Arrowhead at the open end, pointing along the direction of travel.
    angle = math.radians(75)
    radius = ring.width() / 2
    tip = QPointF(
        ring.center().x() + radius * math.cos(angle),
        ring.center().y() - radius * math.sin(angle),
    )
    head = size * 0.20
    path = QPainterPath()
    path.moveTo(tip.x() + head * 0.55, tip.y() - head * 0.15)
    path.lineTo(tip.x() - head * 0.45, tip.y() - head * 0.45)
    path.lineTo(tip.x() - head * 0.10, tip.y() + head * 0.55)
    path.closeSubpath()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(255, 255, 255, 240))
    painter.drawPath(path)


def app_pixmap(size: int = 256) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    _draw_mark(painter, size)
    painter.end()
    return pixmap


def app_icon() -> QIcon:
    """Multi-resolution icon, so Qt picks a crisp size instead of scaling one."""
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(app_pixmap(size))
    return icon


def status_pixmap(state: RunState, size: int = 64) -> QPixmap:
    """App mark with a status dot in the corner."""
    pixmap = app_pixmap(size)
    color = STATUS_COLORS.get(state)
    if not color:
        return pixmap

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    # The badge is a white disc with the status colour inside it. Painting the
    # white disc first is what guarantees contrast: several status colours are
    # blues that would otherwise disappear into the tile behind them.
    badge = size * 0.40
    margin = size * 0.03
    outer = QRectF(size - badge - margin, size - badge - margin, badge, badge)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(255, 255, 255, 245))
    painter.drawEllipse(outer)

    inset = badge * 0.20
    painter.setBrush(QColor(color))
    painter.drawEllipse(outer.adjusted(inset, inset, -inset, -inset))
    painter.end()
    return pixmap


def status_icon(state: RunState) -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128):
        icon.addPixmap(status_pixmap(state, size))
    return icon


# --------------------------------------------------------------------------
# export helpers, used by packaging/make_icons.py
# --------------------------------------------------------------------------


def write_png(path: Path, size: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    app_pixmap(size).save(str(path), "PNG")
    return path


def write_ico(path: Path, sizes=(16, 24, 32, 48, 64, 128, 256)) -> Path:
    """Write a Windows .ico by hand, as PNG-compressed entries.

    Qt can only write .ico where the platform's image plugin supports it, and
    the build machine is not guaranteed to have that. The container format is
    simple enough to emit directly, and every Windows version since Vista
    reads PNG-compressed entries, so this avoids the dependency entirely.
    """
    import struct
    from PySide6.QtCore import QBuffer

    blobs = []
    for size in sizes:
        # QBuffer's own internal byte array, not one passed in: a QByteArray
        # constructed inline is a Python temporary, and Qt would be left
        # holding a pointer to it after the garbage collector runs.
        buffer = QBuffer()
        buffer.open(QBuffer.OpenModeFlag.WriteOnly)
        app_pixmap(size).save(buffer, "PNG")
        blobs.append((size, bytes(buffer.data())))
        buffer.close()

    path.parent.mkdir(parents=True, exist_ok=True)
    header = struct.pack("<HHH", 0, 1, len(blobs))  # reserved, type=icon, count
    directory = b""
    offset = len(header) + 16 * len(blobs)
    for size, blob in blobs:
        # 0 in the width/height byte means 256 - the format's own convention.
        dimension = 0 if size >= 256 else size
        directory += struct.pack(
            "<BBBBHHII", dimension, dimension, 0, 0, 1, 32, len(blob), offset
        )
        offset += len(blob)

    path.write_bytes(header + directory + b"".join(blob for _, blob in blobs))
    return path
