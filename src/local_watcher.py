"""Driftgram: filesystem watcher reporting debounced create/modify/delete events.

Runs in watchdog's own background thread; hands each settled change back to
the asyncio event loop where the rest of the tool runs.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path
from typing import Awaitable, Callable, Dict

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

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
    observer = Observer()
    observer.schedule(handler, str(root_path), recursive=True)
    observer.start()
    logger.info("Watching %s", root_path)
    return observer
