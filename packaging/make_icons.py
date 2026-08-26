"""Generate the icon files the installers need, from src/gui/icons.py.

Keeping the icon as drawing code rather than as committed binaries means
there is one definition to change, and no chance of the app icon and the
installer icon drifting apart. Run as part of the build:

    python packaging/make_icons.py

Produces, under packaging/generated/:
    driftgram.ico            Windows: app exe + installer
    driftgram.png            Linux: 512px master for .desktop / AppImage
    hicolor/<size>/...png    Linux: the sizes an icon theme expects
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUT = Path(__file__).resolve().parent / "generated"
HICOLOR_SIZES = (16, 24, 32, 48, 64, 128, 256, 512)


def main() -> int:
    # A QGuiApplication has to exist before any QPixmap is constructed.
    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication(sys.argv)  # noqa: F841 - must stay alive for the duration

    from src.gui.icons import write_ico, write_png

    OUT.mkdir(parents=True, exist_ok=True)
    write_ico(OUT / "driftgram.ico")
    write_png(OUT / "driftgram.png", 512)
    for size in HICOLOR_SIZES:
        write_png(OUT / "hicolor" / f"{size}x{size}" / "apps" / "driftgram.png", size)

    print(f"Icons written to {OUT}")
    for path in sorted(OUT.rglob("*")):
        if path.is_file():
            print(f"  {path.relative_to(OUT)}  ({path.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
