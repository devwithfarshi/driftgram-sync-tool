"""Driftgram: filesystem watcher reporting debounced create/modify/delete events.

Runs in watchdog's own background thread; hands each settled change back to
the asyncio event loop where the rest of the tool runs.
"""
from __future__ import annotations

import asyncio
import errno
import logging
import threading
from pathlib import Path
from typing import Awaitable, Callable, Dict

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .errors import WatcherError

logger = logging.getLogger("driftgram.watcher")

OnChange = Callable[[Path, bool], Awaitable[None]]


class DebouncedHandler(FileSystemEventHandler):
    """Collapses bursts of events on the same path into a single callback,
    fired `debounce_seconds` after the last event on that path."""

    def __init__(self, loop: asyncio.AbstractEventLoop, on_change: OnChange, debounce_seconds: float):
        self._loop = loop
        self._on_change = on_change
        self._debounce_seconds = debounce_seconds
        self._timers: Dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    def _schedule(self, path: str, deleted: bool) -> None:
        with self._lock:
            existing = self._timers.get(path)
            if existing:
                existing.cancel()

            def fire():
                with self._lock:
                    self._timers.pop(path, None)
                asyncio.run_coroutine_threadsafe(self._on_change(Path(path), deleted), self._loop)

            timer = threading.Timer(self._debounce_seconds, fire)
            timer.daemon = True
            self._timers[path] = timer
            timer.start()

    def on_created(self, event):
        if not event.is_directory:
            self._schedule(event.src_path, deleted=False)

    def on_modified(self, event):
        if not event.is_directory:
            self._schedule(event.src_path, deleted=False)

    def on_moved(self, event):
        if not event.is_directory:
            self._schedule(event.src_path, deleted=True)
            self._schedule(event.dest_path, deleted=False)

    def on_deleted(self, event):
        if not event.is_directory:
            self._schedule(event.src_path, deleted=True)


def start_watcher(root_path: Path, handler: DebouncedHandler) -> Observer:
    """Begin watching a folder, translating OS limits into readable errors.

    Linux backs recursive watching with inotify, which has a per-user cap on
    how many directories can be watched at once (fs.inotify.max_user_watches,
    often 8192). Point the app at a big tree and it hits that cap as a bare
    ENOSPC "No space left on device", which is one of the least helpful error
    messages an operating system produces - the disk is fine. Catch it here
    and say what actually went wrong, with the command that fixes it.
    """
    observer = Observer()
    try:
        observer.schedule(handler, str(root_path), recursive=True)
        observer.start()
    except OSError as exc:
        try:
            observer.stop()
        except Exception:
            pass
        if getattr(exc, "errno", None) == errno.ENOSPC:
            raise WatcherError(
                f"There are too many folders inside {root_path} to watch them all.",
                "Linux limits how many folders one program may watch. Raise the "
                "limit with:\n\n"
                "    sudo sysctl fs.inotify.max_user_watches=524288\n\n"
                "To make it permanent, add 'fs.inotify.max_user_watches=524288' to "
                "/etc/sysctl.conf. Alternatively, sync a smaller folder or add "
                "ignore rules for large subfolders.",
            ) from exc
        raise WatcherError(
            f"Couldn't watch {root_path} for changes.",
            str(exc),
        ) from exc
    logger.info("Watching %s", root_path)
    return observer
