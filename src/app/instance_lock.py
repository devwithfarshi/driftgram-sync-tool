"""Driftgram: one process per data directory.

Two Driftgram processes sharing a manifest and a Telegram session file is
genuinely dangerous, not merely untidy: SQLite writes interleave, and
Telethon's session store is not written for concurrent use. The old README
handled this by asking the user to remember to stop the sync tool before
running the restore tool. An app cannot rely on that, so the rule is now
enforced - and because the GUI does its restoring in-process, the situation
mostly stops arising.

The lock is advisory and OS-level, so it dies with the process. A crashed
Driftgram leaves a stale lock *file* but not a stale *lock*, which is what
makes this safe to take at startup without any "delete this file to
continue" ritual.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

from ..errors import AlreadyRunningError

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl


class InstanceLock:
    """Exclusive advisory lock on a file, usable as a context manager.

    Byte 0 is the lock; the owner's PID is written from byte 1 onwards. That
    split matters on Windows, where msvcrt.locking makes the locked byte
    unreadable to every other handle - keeping the PID outside it means a
    second instance can still say *which* process is in the way.
    """

    #: Byte 0 is what actually gets locked; everything after it is diagnostics.
    _LOCK_BYTE = 0
    _PID_OFFSET = 1

    def __init__(self, lock_path: Path, label: str = "Driftgram"):
        self.lock_path = lock_path
        self.label = label
        self._handle = None

    def acquire(self) -> "InstanceLock":
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.lock_path.exists():
            self.lock_path.write_bytes(bytes(1))

        handle = open(self.lock_path, "r+b")
        try:
            handle.seek(self._LOCK_BYTE)
            if sys.platform == "win32":
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            other = self._read_pid()
            handle.close()
            who = f"Another copy (process {other})" if other else "Another copy"
            raise AlreadyRunningError(
                f"{self.label} is already running.",
                f"{who} is using {self.lock_path.parent}. Close it first - two "
                "copies sharing one manifest would corrupt it.",
            ) from exc

        handle.seek(self._PID_OFFSET)
        handle.write(str(os.getpid()).encode("ascii").ljust(16, b" "))
        handle.flush()
        self._handle = handle
        return self

    def _read_pid(self) -> Optional[str]:
        """Read the holder's PID without touching the locked byte."""
        try:
            with open(self.lock_path, "rb") as f:
                f.seek(self._PID_OFFSET)
                return f.read(16).decode("ascii", "replace").strip() or None
        except OSError:
            return None

    def release(self) -> None:
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            handle.seek(self._LOCK_BYTE)
            if sys.platform == "win32":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            handle.close()

    def __enter__(self) -> "InstanceLock":
        return self.acquire()

    def __exit__(self, *exc_info) -> None:
        self.release()
