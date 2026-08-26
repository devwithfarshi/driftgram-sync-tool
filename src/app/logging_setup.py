"""Driftgram: one place that decides where log output goes.

A terminal user reads the console. An app user has no console at all - on
Windows the GUI is launched with pythonw/a windowed exe, so anything printed
to stdout goes nowhere. Both therefore always get a rotating file in the data
directory, which is also what the app's "Open log folder" button reveals and
what a bug report should attach.
"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
MAX_BYTES = 2 * 1024 * 1024
BACKUPS = 3


def configure(
    log_file: Optional[Path] = None,
    *,
    level: int = logging.INFO,
    console: bool = True,
) -> None:
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter(FORMAT)

    if console and sys.stderr is not None:
        stream = logging.StreamHandler()
        stream.setFormatter(formatter)
        root.addHandler(stream)

    if log_file is not None:
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            rotating = RotatingFileHandler(
                log_file, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8"
            )
            rotating.setFormatter(formatter)
            root.addHandler(rotating)
        except OSError:
            # A read-only or missing data directory is not a reason to refuse
            # to run; the user simply won't have a log file to send us.
            logging.getLogger("driftgram").warning("Could not open log file %s", log_file)

    # Telethon is chatty at INFO and most of it is protocol noise.
    logging.getLogger("telethon").setLevel(logging.WARNING)
