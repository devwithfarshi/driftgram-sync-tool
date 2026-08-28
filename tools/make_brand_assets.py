"""Render the brand assets that live outside the app, from the app's own code.

    python tools/make_brand_assets.py            # writes into docs/images/
    python tools/make_brand_assets.py <dir>

Produces:

    social-preview.png     1280x640, for GitHub's Settings -> Social preview
    logo-lockup-light.png  mark + wordmark, for the README on a light theme
    logo-lockup-dark.png   the same, for a dark theme

The mark itself comes from src/gui/icons.app_pixmap, the same function that
draws the window icon, the tray icon and the .ico the installer uses. That is
the whole point: a logo redrawn by hand - or generated - for the README would
drift from the one people actually see once the app is running, and the drift
would be invisible until someone put the two side by side. Colours likewise
come from src/gui/theme, so the card cannot contradict the app either.

Run this after changing the mark or the palette, and commit the result.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QColor,
    QFont,
    QGuiApplication,
    QLinearGradient,
    QPainter,
    QPixmap,
)

from src.gui.icons import BRAND_BOTTOM, BRAND_TOP, app_pixmap  # noqa: E402
from src.gui.theme import DARK, LIGHT  # noqa: E402

# Whatever the host actually has. Qt walks this list and takes the first hit,
# so the card renders on a Windows box and a CI runner without shipping a font.
FONT_STACK = ["Segoe UI Variable Display", "Segoe UI", "Inter", "DejaVu Sans", "Arial"]

WORDMARK = "Driftgram"
TAGLINE = "Your folders, backed up to your own Telegram account."
META = "Two-way sync   ·   Windows & Linux   ·   Open source"


def _font(px: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    font = QFont()
    font.setFamilies(FONT_STACK)
    font.setPixelSize(px)
    font.setWeight(weight)
    return font


def social_preview(path: Path) -> Path:
    """1280x640 card for GitHub, X, Slack, Discord and anywhere else a link unfurls."""
    w, h = 1280, 640
    pixmap = QPixmap(w, h)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    # The app's dark background, not a flood of the brand gradient: a card that
    # is 100% gradient reads as generic SaaS, and dark cards hold their own in a
    # GitHub or X timeline. The gradient stays the accent, which is its job in
    # the app too.
    painter.fillRect(QRectF(0, 0, w, h), QColor(DARK.bg))

    # A soft brand wash bleeding in from the top left, clipped well outside the
    # frame so it reads as light rather than as a visible shape.
    wash = QLinearGradient(QPointF(0, 0), QPointF(w * 0.85, h))
    top = QColor(BRAND_TOP)
    top.setAlpha(46)
    mid = QColor(BRAND_BOTTOM)
    mid.setAlpha(12)
    wash.setColorAt(0.0, top)
    wash.setColorAt(0.55, mid)
    wash.setColorAt(1.0, QColor(0, 0, 0, 0))
    painter.fillRect(QRectF(0, 0, w, h), wash)

    # Centred, not left-aligned: GitHub, Slack and X each crop this card
    # differently, and a centred block survives all of them. It also avoids
    # leaving the right third of a 1280-wide canvas visibly empty.
    #
    # The wordmark carries the "Folders <-> Telegram" line in the app's sidebar,
    # but not here - set under a 96px wordmark it collides with the descender of
    # the g, and the sentence below says the same thing better.
    mark = 144
    gap = 30

    painter.setFont(_font(96, QFont.Weight.Bold))
    word_w = painter.fontMetrics().horizontalAdvance(WORDMARK)

    row_w = mark + gap + word_w
    row_x = (w - row_w) / 2
    row_y = 132

    painter.drawPixmap(int(row_x), row_y, app_pixmap(mark))

    painter.setPen(QColor(DARK.text))
    painter.drawText(QRectF(row_x + mark + gap, row_y, word_w + 8, mark),
                     int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                     WORDMARK)

    centre = int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)

    painter.setPen(QColor(DARK.text))
    painter.setFont(_font(38, QFont.Weight.Normal))
    painter.drawText(QRectF(0, 356, w, 52), centre, TAGLINE)

    # A short gradient rule, the one place the full brand ramp appears.
    rule_w = 220
    rule = QLinearGradient(QPointF((w - rule_w) / 2, 0), QPointF((w + rule_w) / 2, 0))
    rule.setColorAt(0.0, QColor(BRAND_TOP))
    rule.setColorAt(1.0, QColor(BRAND_BOTTOM))
    painter.fillRect(QRectF((w - rule_w) / 2, 438, rule_w, 5), rule)

    painter.setPen(QColor(DARK.muted))
    painter.setFont(_font(27, QFont.Weight.Medium))
    painter.drawText(QRectF(0, 472, w, 44), centre, META)


    painter.end()
    path.parent.mkdir(parents=True, exist_ok=True)
    pixmap.save(str(path), "PNG")
    return path


def logo_lockup(path: Path, *, dark: bool) -> Path:
    """Mark plus wordmark on transparency, for the top of the README.

    Two files rather than one: the tile carries its own gradient and works on
    any background, but the wordmark cannot - so the README picks between them
    with <picture> and prefers-color-scheme instead of settling for a grey that
    is slightly wrong in both themes.
    """
    palette = DARK if dark else LIGHT
    mark = 96
    w, h = 560, 144
    pixmap = QPixmap(w, h)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    painter.drawPixmap(0, (h - mark) // 2, app_pixmap(mark))

    text_x = mark + 26

    # Positioned off the wordmark's real baseline and descent rather than by
    # eyeballed rectangles: at this size the descender of the g in Driftgram
    # reaches into the line below, and stacking two guessed rects put the two
    # in contact.
    word = _font(58, QFont.Weight.Bold)
    painter.setFont(word)
    word_metrics = painter.fontMetrics()
    baseline = 20 + word_metrics.ascent()

    painter.setPen(QColor(palette.text))
    painter.drawText(QPointF(text_x, baseline), WORDMARK)

    tag = _font(23, QFont.Weight.Medium)
    painter.setFont(tag)
    tag_metrics = painter.fontMetrics()
    # Clear the descender, then add a little optical breathing room.
    tag_baseline = baseline + word_metrics.descent() + 8 + tag_metrics.ascent()

    painter.setPen(QColor(palette.muted))
    painter.drawText(QPointF(text_x + 3, tag_baseline), "Folders  ↔  Telegram")

    painter.end()
    path.parent.mkdir(parents=True, exist_ok=True)
    pixmap.save(str(path), "PNG")
    return path


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/images")
    # A QPixmap needs a GUI application to exist before it can be constructed.
    QGuiApplication(sys.argv[:1])

    written = [
        social_preview(out / "social-preview.png"),
        logo_lockup(out / "logo-lockup-light.png", dark=False),
        logo_lockup(out / "logo-lockup-dark.png", dark=True),
    ]
    for path in written:
        print(f"  {path}  ({path.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
