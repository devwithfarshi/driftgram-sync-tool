"""Driftgram: run the sync engine in its own thread, driven from anywhere.

The engine is asyncio (Telethon) plus a couple of watchdog threads. A Qt GUI
owns the main thread and must never block on it. Rather than marry the two
loops with an adapter, the supervisor gives the engine a private thread and a
private event loop, and exposes every operation as a thread-safe call that
returns a concurrent.futures.Future.

That split is the whole point: sync_engine.py stays exactly the async code it
already was, the GUI stays responsive by construction, and neither imports the
other. Results and progress travel back through the EventBus.

Telethon in particular is not thread-safe - every call on the client must
happen on the loop that created it - so nothing here touches self._client
outside a coroutine submitted to that loop.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Coroutine, List, Optional, Sequence

from telethon import TelegramClient, events as tg_events
from telethon.errors import (
    ApiIdInvalidError,
    FloodWaitError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberBannedError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
)

from ..config import AppConfig
from ..errors import DriftgramError, LoginRequiredError, WatcherError
from ..events import EventBus, RunState
from ..local_watcher import DebouncedHandler, start_watcher
from ..state import StateStore
from ..sync_engine import RemoteFile, SyncEngine

logger = logging.getLogger("driftgram.supervisor")

#: How often to notice that the connection dropped or came back.
HEARTBEAT_SECONDS = 10


class LoginStep(str, Enum):
    """Where the user is in the Telegram sign-in flow."""

    AUTHORIZED = "authorized"
    NEED_PHONE = "need_phone"
    NEED_CODE = "need_code"
    NEED_PASSWORD = "need_password"


@dataclass
class Account:
    user_id: int
    username: Optional[str]
    first_name: Optional[str]
    phone: Optional[str]

    @property
    def label(self) -> str:
        if self.username:
            return f"@{self.username}"
        return self.first_name or str(self.user_id)


def _friendly(exc: BaseException) -> DriftgramError:
    """Turn a Telethon error into something worth showing a person.

    Telethon's exception names are precise and meaningless to most users;
    every one of these is a situation a non-technical user can actually hit
    during sign-in, so each gets an explanation and a way forward.
    """
    if isinstance(exc, DriftgramError):
        return exc
    if isinstance(exc, PhoneCodeInvalidError):
        return DriftgramError("That code wasn't right.", "Check the code Telegram sent you and try again.")
    if isinstance(exc, PhoneCodeExpiredError):
        return DriftgramError("That code has expired.", "Go back and request a new one.")
    if isinstance(exc, PhoneNumberInvalidError):
        return DriftgramError(
            "Telegram doesn't recognise that phone number.",
            "Include your country code, for example +8801712345678.",
        )
    if isinstance(exc, PhoneNumberBannedError):
        return DriftgramError(
            "That phone number has been banned by Telegram.",
            "You'll need to contact Telegram support - Driftgram can't help with this one.",
        )
    if isinstance(exc, ApiIdInvalidError):
        return DriftgramError(
            "Telegram rejected your API ID and API Hash.",
            "Go back a step and re-copy both values from my.telegram.org/apps. "
            "The API ID is digits only; the hash is a long string of letters and numbers.",
        )
    if isinstance(exc, FloodWaitError):
        minutes = max(1, int(getattr(exc, "seconds", 60)) // 60)
        return DriftgramError(
            f"Telegram is asking us to wait about {minutes} minute(s) before trying again.",
            "This happens after several rapid attempts. Leave it a little while and retry.",
        )
    if isinstance(exc, (ConnectionError, OSError, asyncio.TimeoutError)):
        return DriftgramError(
            "Couldn't reach Telegram.", "Check your internet connection and try again."
        )
    return DriftgramError("Something went wrong.", str(exc) or exc.__class__.__name__)


class Supervisor:
    """Owns the asyncio thread, the Telegram client, and the running engine."""

    def __init__(self, config: AppConfig, bus: EventBus):
        self.config = config
        self.bus = bus
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._client: Optional[TelegramClient] = None
        self._state: Optional[StateStore] = None
        self._engine: Optional[SyncEngine] = None
        self._observers: List[Any] = []
        self._tasks: List[asyncio.Task] = []
        self._phone: Optional[str] = None
        self._code_hash: Optional[str] = None
        self._syncing = False
        self._handler_target: Optional[str] = None
        self._handlers: List[Any] = []

    # ------------------------------------------------------------------
    # thread lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._thread_main, name="driftgram-engine", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=10):
            raise DriftgramError("The sync engine didn't start.", "Please restart Driftgram.")

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            try:
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            finally:
                loop.close()
                self._loop = None

    def submit(self, coro: Coroutine) -> "concurrent.futures.Future":
        """Run a coroutine on the engine loop from any thread."""
        if self._loop is None:
            future: concurrent.futures.Future = concurrent.futures.Future()
            future.set_exception(DriftgramError("The sync engine isn't running."))
            coro.close()
            return future
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def shutdown(self, timeout: float = 8.0) -> None:
        """Stop syncing, disconnect, close the database, and stop the loop."""
        if self._loop is None:
            return
        try:
            self.submit(self._async_shutdown()).result(timeout=timeout)
        except Exception:
            logger.exception("Error during shutdown")
        loop, self._loop = self._loop, None
        loop.call_soon_threadsafe(loop.stop)
        if self._thread:
            self._thread.join(timeout=timeout)
            self._thread = None
        self._ready.clear()

    async def _async_shutdown(self) -> None:
        await self._teardown_sync()
        if self._client is not None and self._client.is_connected():
            await self._client.disconnect()
        self._client = None
        if self._state is not None:
            self._state.close()
            self._state = None
        self.bus.status(RunState.STOPPED)

    # ------------------------------------------------------------------
    # connection + sign-in
    # ------------------------------------------------------------------

    async def _ensure_client(self) -> TelegramClient:
        if self._client is None:
            self.config.paths.ensure_dirs()
            self._client = TelegramClient(
                str(self.config.session_file),
                self.config.api_id,
                self.config.api_hash,
                # A background app should ride out a flaky connection rather
                # than give up after the library's default handful of tries.
                connection_retries=None,
                retry_delay=5,
                auto_reconnect=True,
                device_model="Driftgram",
                system_version="desktop",
            )
        if not self._client.is_connected():
            self.bus.status(RunState.CONNECTING)
            await self._client.connect()
        return self._client

    async def _connect(self) -> LoginStep:
        try:
            client = await self._ensure_client()
            if await client.is_user_authorized():
                return LoginStep.AUTHORIZED
            self.bus.status(RunState.LOGIN_REQUIRED)
            return LoginStep.NEED_PHONE
        except Exception as exc:
            raise _friendly(exc) from exc

    def connect(self) -> "concurrent.futures.Future":
        return self.submit(self._connect())

    async def _send_code(self, phone: str) -> None:
        try:
            client = await self._ensure_client()
            sent = await client.send_code_request(phone)
            self._phone = phone
            self._code_hash = sent.phone_code_hash
        except Exception as exc:
            raise _friendly(exc) from exc

    def send_code(self, phone: str) -> "concurrent.futures.Future":
        return self.submit(self._send_code(phone.strip()))

    async def _sign_in_code(self, code: str) -> LoginStep:
        if not self._phone or not self._code_hash:
            raise LoginRequiredError("We lost track of your sign-in.", "Go back and enter your number again.")
        try:
            client = await self._ensure_client()
            await client.sign_in(phone=self._phone, code=code.strip(), phone_code_hash=self._code_hash)
            return LoginStep.AUTHORIZED
        except SessionPasswordNeededError:
            return LoginStep.NEED_PASSWORD
        except Exception as exc:
            raise _friendly(exc) from exc

    def sign_in_code(self, code: str) -> "concurrent.futures.Future":
        return self.submit(self._sign_in_code(code))

    async def _sign_in_password(self, password: str) -> LoginStep:
        try:
            client = await self._ensure_client()
            await client.sign_in(password=password)
            return LoginStep.AUTHORIZED
        except Exception as exc:
            raise _friendly(exc) from exc

    def sign_in_password(self, password: str) -> "concurrent.futures.Future":
        return self.submit(self._sign_in_password(password))

    async def _account(self) -> Optional[Account]:
        client = await self._ensure_client()
        if not await client.is_user_authorized():
            return None
        me = await client.get_me()
        return Account(
            user_id=me.id,
            username=getattr(me, "username", None),
            first_name=getattr(me, "first_name", None),
            phone=getattr(me, "phone", None),
        )

    def account(self) -> "concurrent.futures.Future":
        return self.submit(self._account())

    async def _sign_out(self) -> None:
        await self._teardown_sync()
        if self._client is not None:
            try:
                await self._client.log_out()
            except Exception:
                logger.exception("Sign-out failed; removing the local session anyway")
            if self._client.is_connected():
                await self._client.disconnect()
            self._client = None
        # log_out() usually removes the file; make sure, so a stale session
        # can never silently keep the user signed in after they asked to leave.
        for suffix in ("", "-journal", "-wal", "-shm"):
            Path(str(self.config.session_file) + suffix).unlink(missing_ok=True)
        self.bus.status(RunState.LOGIN_REQUIRED)

    def sign_out(self) -> "concurrent.futures.Future":
        return self.submit(self._sign_out())

    # ------------------------------------------------------------------
    # syncing
    # ------------------------------------------------------------------

    async def _start_sync(self, config: Optional[AppConfig] = None) -> None:
        if config is not None:
            self.config = config
        await self._teardown_sync()

        client = await self._ensure_client()
        if not await client.is_user_authorized():
            self.bus.status(RunState.LOGIN_REQUIRED)
            raise LoginRequiredError("You're signed out of Telegram.", "Sign in again to resume syncing.")

        if self._state is None:
            self.config.paths.ensure_dirs()
            self._state = StateStore(self.config.state_db_path)

        engine = SyncEngine(client, self.config, self._state, self.bus)
        self._engine = engine
        await engine.resolve_target()

        # Registered once per client, not per sync restart: Telethon keeps
        # handlers on the client, so re-adding them on every settings change
        # would deliver each message N times. They read self._engine live.
        # The exception is a change of target chat, which is baked into the
        # NewMessage filter and so needs the handlers rebuilt.
        if self._handler_target != self.config.target:
            self._unregister_handlers(client)
            self._register_handlers(client)
            self._handler_target = self.config.target

        self._syncing = True
        self._tasks.append(asyncio.create_task(self._run_scan_then_watch()))
        self._tasks.append(asyncio.create_task(self._heartbeat()))

    def start_sync(self, config: Optional[AppConfig] = None) -> "concurrent.futures.Future":
        return self.submit(self._start_sync(config))

    def _register_handlers(self, client: TelegramClient) -> None:
        async def _on_new_message(event):
            if self._engine is not None:
                await self._engine.handle_remote_message(event.message)

        async def _on_deleted(event):
            if self._engine is not None:
                await self._engine.handle_remote_delete(event.deleted_ids, event.chat_id)

        new_message = tg_events.NewMessage(chats=self.config.target)
        # Deliberately NOT filtered with chats=: Telegram omits the peer for
        # deletions in private chats and small groups (Saved Messages
        # included), so a chats= filter would drop every such event.
        deleted = tg_events.MessageDeleted()

        client.add_event_handler(_on_new_message, new_message)
        client.add_event_handler(_on_deleted, deleted)
        self._handlers = [(_on_new_message, new_message), (_on_deleted, deleted)]

    def _unregister_handlers(self, client: TelegramClient) -> None:
        for callback, event_filter in self._handlers:
            try:
                client.remove_event_handler(callback, event_filter)
            except Exception:
                logger.debug("Handler was already gone", exc_info=True)
        self._handlers.clear()

    async def _run_scan_then_watch(self) -> None:
        engine = self._engine
        if engine is None:
            return
        try:
            await engine.initial_scan()
            self._start_observers(engine)
            self._tasks.append(asyncio.create_task(engine.poll_remote_loop()))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Initial sync failed")
            self.bus.error(str(_friendly(exc)))
            self.bus.status(RunState.ERROR)

    def _start_observers(self, engine: SyncEngine) -> None:
        loop = asyncio.get_running_loop()
        for root in self.config.roots:
            if not root.path.exists():
                continue
            handler = DebouncedHandler(loop, engine.handle_local_change, self.config.sync.debounce_seconds)
            try:
                self._observers.append(start_watcher(root.path, handler))
            except WatcherError as exc:
                # One unwatchable folder must not stop the others; the user is
                # told which, and everything else keeps syncing.
                logger.error("%s", exc)
                self.bus.error(str(exc), alias=root.alias)

    async def _heartbeat(self) -> None:
        """Notice the connection dropping or returning, so the UI can say so."""
        was_connected = True
        while self._syncing:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            client = self._client
            if client is None:
                continue
            connected = client.is_connected()
            if connected != was_connected:
                was_connected = connected
                if connected:
                    self.bus.status(RunState.IDLE, "Back online")
                else:
                    self.bus.status(RunState.OFFLINE, "No connection to Telegram")

    async def _teardown_sync(self) -> None:
        self._syncing = False
        if self._engine is not None:
            self._engine.request_stop()
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        for observer in self._observers:
            observer.stop()
        for observer in self._observers:
            observer.join(timeout=5)
        self._observers.clear()
        if self._engine is not None:
            self._engine.clear_stop()
        self._engine = None

    def stop_sync(self) -> "concurrent.futures.Future":
        return self.submit(self._teardown_sync())

    # ------------------------------------------------------------------
    # user actions
    # ------------------------------------------------------------------

    async def _set_paused(self, paused: bool) -> None:
        if self._engine is None:
            return
        self._engine.set_paused(paused)
        if not paused:
            # Resume means rescan: nothing was queued while paused, by design.
            await self._engine.initial_scan()

    def set_paused(self, paused: bool) -> "concurrent.futures.Future":
        return self.submit(self._set_paused(paused))

    async def _sync_now(self) -> None:
        if self._engine is None:
            raise DriftgramError("Syncing hasn't started yet.")
        await self._engine.initial_scan()

    def sync_now(self) -> "concurrent.futures.Future":
        return self.submit(self._sync_now())

    async def _list_remote(self, on_progress: Optional[Callable[[int, int], None]]) -> List[RemoteFile]:
        engine = self._engine
        if engine is None:
            client = await self._ensure_client()
            if self._state is None:
                self._state = StateStore(self.config.state_db_path)
            engine = SyncEngine(client, self.config, self._state, self.bus)
        try:
            return await engine.collect_remote_index(on_progress)
        except Exception as exc:
            raise _friendly(exc) from exc

    def list_remote(
        self, on_progress: Optional[Callable[[int, int], None]] = None
    ) -> "concurrent.futures.Future":
        return self.submit(self._list_remote(on_progress))

    async def _restore(self, files: Sequence[RemoteFile], overwrite: bool) -> int:
        engine = self._engine
        if engine is None:
            raise DriftgramError("Syncing hasn't started yet.")
        return await engine.restore_files(files, overwrite=overwrite)

    def restore(self, files: Sequence[RemoteFile], overwrite: bool = False) -> "concurrent.futures.Future":
        return self.submit(self._restore(files, overwrite))

    async def _stats(self) -> tuple:
        if self._state is None:
            return (0, 0)
        return self._state.stats()

    def stats(self) -> "concurrent.futures.Future":
        return self.submit(self._stats())

    @property
    def is_syncing(self) -> bool:
        return self._syncing

    @property
    def is_paused(self) -> bool:
        return self._engine is not None and self._engine.paused
