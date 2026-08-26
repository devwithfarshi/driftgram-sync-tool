"""Driftgram: cross-platform filename checks and human-readable sizes.

Once one machine can be Linux and another Windows, a name that is perfectly
legal on the machine that uploaded a file may be impossible to write on the
machine downloading it: Linux happily stores `notes:2024.txt` or `aux.log`,
Windows refuses both.

The tool *skips* those rather than renaming them. Renaming would look tidier
but would break the core invariant - a renamed download is a new local file,
so the watcher would upload it again under the new name and Telegram would
end up holding both. Skipping keeps the manifest honest and tells the user
exactly which file needs renaming at the source.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

_WINDOWS_ILLEGAL = set('<>:"|?*')
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def unwritable_reason(rel_path: str, *, platform: Optional[str] = None) -> Optional[str]:
    """Why this relative path cannot be created here, or None if it can.

    The returned string is shown to the user verbatim, so it names the
    offending component rather than talking about the path as a whole.
    """
    target = platform or sys.platform
    if not target.startswith("win"):
        return None

    for part in rel_path.replace("\\", "/").split("/"):
        if not part:
            continue
        bad = sorted(_WINDOWS_ILLEGAL & set(part))
        if bad:
            return f"Windows doesn't allow {' '.join(bad)} in the name \"{part}\""
        if any(ord(ch) < 32 for ch in part):
            return f'the name "{part}" contains a control character Windows rejects'
        if part[-1] in " .":
            return f'Windows doesn\'t allow the name "{part}" to end with a space or full stop'
        if part.split(".")[0].upper() in _WINDOWS_RESERVED:
            return f'"{part}" is a reserved device name on Windows'
    return None


def conflict_path(dest: Path, marker: str = "from Telegram") -> Path:
    """A free filename beside `dest` for keeping both copies of a conflicted file.

    report.docx -> "report (from Telegram).docx" -> "report (from Telegram 2).docx"
    """
    stem, suffix = dest.stem, dest.suffix
    candidate = dest.with_name(f"{stem} ({marker}){suffix}")
    counter = 2
    while candidate.exists():
        candidate = dest.with_name(f"{stem} ({marker} {counter}){suffix}")
        counter += 1
    return candidate


def human_bytes(size: Optional[int]) -> str:
    """1536 -> '1.5 KB'. Used everywhere the UI shows a size."""
    if size is None:
        return "-"
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}".replace(".0 ", " ")
        value /= 1024
    return f"{value:.1f} GB"
