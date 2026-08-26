"""Driftgram: the handful of things every page needs.

Pages need the current config, a way to reach the engine, and a way to say
"I changed something, save it and apply it". Passing one context object
around beats threading four constructor arguments through every widget, and
keeps the save/restart policy in one place instead of duplicated per page.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..config import AppConfig
from ..app.supervisor import Supervisor
from .bridge import EngineSignals


@dataclass
class AppContext:
    config: AppConfig
    supervisor: Supervisor
    signals: EngineSignals
    #: Persist the current config to disk. Raises ConfigError if it can't.
    save: Callable[[], None]
    #: Persist, then rebuild the engine so folder/ignore changes take effect.
    apply_and_restart: Callable[[], None]
    #: Show a transient message in the window's status area.
    notify: Callable[[str], None]
