"""Driftgram: getting results from the engine thread onto the Qt thread safely.

Two things cross the thread boundary, and both are funnelled through here so
no widget ever has to think about it:

  EventBus -> Qt signals. EngineSignals lives on the GUI thread but has its
  emit() called from the engine thread. Qt's automatic connection type sees
  that mismatch and queues the delivery, so slots run on the GUI thread. This
  is the only correct way to touch a widget from another thread.

  Future -> callback. Supervisor returns concurrent.futures.Future objects
  whose done-callbacks fire on the engine thread, where calling into a widget
  would be a crash waiting to happen. watch() bounces them through a signal.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional, Set

from PySide6.QtCore import QObject, Signal

from ..events import EventBus, SyncEvent

logger = logging.getLogger("driftgram.gui.bridge")


class EngineSignals(QObject):
    """Qt-side mirror of the EventBus. Construct on the GUI thread."""

    event = Signal(object)  # SyncEvent

    def __init__(self, bus: EventBus, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._bus = bus
        self._token = bus.subscribe(self._on_event)

    def _on_event(self, event: SyncEvent) -> None:
        # Called on the engine thread. Emitting is safe; the receiving slots
        # live on the GUI thread, so Qt queues the call rather than running it
        # here. Nothing below this line may touch a widget directly.
        self.event.emit(event)

    def detach(self) -> None:
        self._bus.unsubscribe(self._token)


class _FutureRelay(QObject):
    """Carries one future's outcome from the engine thread to the GUI thread."""

    finished = Signal(object, object)  # (result, exception)


#: Relays must outlive the future they are watching; a local variable would be
#: collected the moment watch() returns, taking the pending signal with it.
_live_relays: Set[_FutureRelay] = set()


def watch(
    future,
    on_success: Optional[Callable[[object], None]] = None,
    on_error: Optional[Callable[[BaseException], None]] = None,
) -> None:
    """Run on_success/on_error on the GUI thread when `future` completes.

    Neither callback is required: fire-and-forget work can pass nothing and
    still have its exception logged rather than swallowed silently.
    """
    relay = _FutureRelay()
    _live_relays.add(relay)

    def deliver(result, error) -> None:
        _live_relays.discard(relay)
        try:
            if error is not None:
                if on_error is not None:
                    on_error(error)
                else:
                    logger.error("Background task failed: %s", error)
            elif on_success is not None:
                on_success(result)
        finally:
            relay.deleteLater()

    relay.finished.connect(deliver)

    def on_done(fut) -> None:  # runs on the engine thread
        try:
            relay.finished.emit(fut.result(), None)
        except BaseException as exc:  # noqa: BLE001 - forwarded verbatim to the GUI
            relay.finished.emit(None, exc)

    future.add_done_callback(on_done)
