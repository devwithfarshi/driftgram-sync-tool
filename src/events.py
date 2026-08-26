"""Driftgram: a small pub/sub bus so a UI can watch the sync engine work.

The engine used to communicate only through the logging module, which is
fine for a terminal and useless for a window: a GUI needs to know which file
is transferring, how far along it is, and whether anything needs attention.

The bus is deliberately one-directional and dependency-free. SyncEngine
emits; whoever is interested subscribes. The CLI subscribes to nothing and
behaves exactly as before, so this stays free when unused.

Threading: emit() runs on the engine's asyncio thread, subscribers may live
anywhere. A subscriber that raises is logged and dropped from that one
delivery - a broken UI must never take the sync engine down with it.
"""
from __future__ import annotations

import itertools
import logging
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, Optional

logger = logging.getLogger("driftgram.events")


class EventKind(str, Enum):
    # lifecycle
    STATUS = "status"
    # startup / full reconciliation pass
    SCAN_STARTED = "scan_started"
    SCAN_PROGRESS = "scan_progress"
    SCAN_FINISHED = "scan_finished"
    # local -> remote
    UPLOAD_STARTED = "upload_started"
    UPLOAD_PROGRESS = "upload_progress"
    UPLOAD_FINISHED = "upload_finished"
    # remote -> local
    DOWNLOAD_STARTED = "download_started"
    DOWNLOAD_PROGRESS = "download_progress"
    DOWNLOAD_FINISHED = "download_finished"
    # outcomes that are not transfers
    SKIPPED = "skipped"
    LOCAL_DELETED = "local_deleted"
    REMOTE_DELETED = "remote_deleted"
    CONFLICT = "conflict"
    ERROR = "error"


class RunState(str, Enum):
    STOPPED = "stopped"
    CONNECTING = "connecting"
    LOGIN_REQUIRED = "login_required"
    SCANNING = "scanning"
    SYNCING = "syncing"
    IDLE = "idle"
    PAUSED = "paused"
    OFFLINE = "offline"
    ERROR = "error"


@dataclass(frozen=True)
class SyncEvent:
    kind: EventKind
    alias: Optional[str] = None
    rel_path: Optional[str] = None
    #: human-readable one-liner; for SKIPPED/ERROR this is the reason
    message: Optional[str] = None
    bytes_done: Optional[int] = None
    bytes_total: Optional[int] = None
    #: only set on STATUS events
    state: Optional[RunState] = None
    #: free-form extras a UI may want (conflict copy path, counts, ...)
    extra: Dict[str, object] = field(default_factory=dict)

    @property
    def fraction(self) -> Optional[float]:
        if not self.bytes_total or self.bytes_done is None:
            return None
        return min(1.0, self.bytes_done / self.bytes_total)

    def summary(self) -> str:
        """One line suitable for an activity list. Wording lives here, not in the UI."""
        name = self.rel_path or ""
        verbs = {
            EventKind.UPLOAD_FINISHED: f"Backed up {name}",
            EventKind.DOWNLOAD_FINISHED: f"Downloaded {name}",
            EventKind.UPLOAD_STARTED: f"Uploading {name}",
            EventKind.DOWNLOAD_STARTED: f"Downloading {name}",
            EventKind.LOCAL_DELETED: f"Deleted locally: {name}",
            EventKind.REMOTE_DELETED: f"Removed from Telegram: {name}",
            EventKind.CONFLICT: f"Kept both copies of {name}",
            EventKind.SKIPPED: f"Skipped {name}" + (f" - {self.message}" if self.message else ""),
            EventKind.ERROR: self.message or "Something went wrong",
        }
        return verbs.get(self.kind, self.message or self.kind.value)


Subscriber = Callable[[SyncEvent], None]


class EventBus:
    """Thread-safe fan-out of SyncEvents to any number of subscribers."""

    def __init__(self) -> None:
        self._subscribers: Dict[int, Subscriber] = {}
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    def subscribe(self, callback: Subscriber) -> int:
        with self._lock:
            token = next(self._ids)
            self._subscribers[token] = callback
            return token

    def unsubscribe(self, token: int) -> None:
        with self._lock:
            self._subscribers.pop(token, None)

    def emit(self, event: SyncEvent) -> None:
        with self._lock:
            targets = list(self._subscribers.values())
        for callback in targets:
            try:
                callback(event)
            except Exception:  # a broken listener must not break syncing
                logger.exception("Event subscriber raised on %s", event.kind)

    # --- convenience emitters, so engine call sites stay short ---

    def status(self, state: RunState, message: Optional[str] = None, **extra) -> None:
        self.emit(SyncEvent(EventKind.STATUS, state=state, message=message, extra=extra))

    def error(self, message: str, alias: Optional[str] = None, rel_path: Optional[str] = None) -> None:
        self.emit(SyncEvent(EventKind.ERROR, alias=alias, rel_path=rel_path, message=message))

    def file(self, kind: EventKind, alias: str, rel_path: str, **kwargs) -> None:
        self.emit(SyncEvent(kind, alias=alias, rel_path=rel_path, **kwargs))


class NullBus(EventBus):
    """Used when nobody is listening (the CLI). Keeps engine code branch-free."""

    def emit(self, event: SyncEvent) -> None:  # pragma: no cover - trivial
        return
