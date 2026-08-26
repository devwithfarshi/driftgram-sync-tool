"""Frozen-app entry point.

PyInstaller needs a script to start from, not a module, so this is the thin
equivalent of `python -m src.gui`. It also does the two things that only
matter once the app is a bundle rather than a checkout:

  * multiprocessing.freeze_support(), which stops a frozen process that
    happens to spawn a child from re-running the whole app instead;
  * turning an exception during startup into a message box, because a
    windowed build has no console for a traceback to land in - the user
    would just see nothing happen at all.
"""
from __future__ import annotations

import multiprocessing
import sys
import traceback


def _report_fatal(exc: BaseException) -> None:
    detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        app = QApplication.instance() or QApplication(sys.argv)
        box = QMessageBox()
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle("Driftgram")
        box.setText("Driftgram couldn't start.")
        box.setInformativeText(str(exc) or exc.__class__.__name__)
        box.setDetailedText(detail)
        box.exec()
    except Exception:
        # No Qt means no dialog; stderr may go nowhere in a windowed build,
        # but printing costs nothing and helps when run from a terminal.
        print(detail, file=sys.stderr)


def main() -> int:
    multiprocessing.freeze_support()
    try:
        from src.gui.app import main as gui_main

        return gui_main()
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001 - last line of defence
        _report_fatal(exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
