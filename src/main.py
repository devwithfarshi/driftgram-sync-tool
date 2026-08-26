"""Driftgram CLI entry point: two-way background sync of folders and Telegram.

Usage:
    python -m src.main [path-to-config.yaml]

First run will ask for your phone number, login code, and 2FA password (if
set) directly in this terminal - that's Telethon logging into your Telegram
account. After that it reuses the saved session file.

For a windowed version with a setup wizard, folder picker and tray icon, run
`python -m src.gui` instead (or launch the installed Driftgram app). Both
share this same engine, config and manifest.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import List

from telethon import TelegramClient, events
from watchdog.observers import Observer

from .app.instance_lock import InstanceLock
from .app.logging_setup import configure as configure_logging
from .config import load_config
from .errors import DriftgramError, WatcherError
from .local_watcher import DebouncedHandler, start_watcher
from .state import StateStore
from .sync_engine import SyncEngine

logger = logging.getLogger("driftgram.main")


async def run(config_path: str) -> None:
    config = load_config(config_path)
    config.paths.ensure_dirs()
    configure_logging(config.paths.log_file)

    # One process per data directory: a second Driftgram sharing this manifest
    # and session file would corrupt both. Held for the lifetime of the run.
    with InstanceLock(config.paths.lock_file):
        state = StateStore(config.state_db_path)

        client = TelegramClient(str(config.session_file), config.api_id, config.api_hash)
        await client.start()  # prompts for phone/code on first run only
        me = await client.get_me()
        logger.info("Logged in to Telegram as %s", getattr(me, "username", None) or me.id)

        engine = SyncEngine(client, config, state)
        await engine.resolve_target()

        logger.info("Running initial scan of configured folders...")
        await engine.initial_scan()
        logger.info("Initial scan complete.")

        loop = asyncio.get_running_loop()
        observers: List[Observer] = []
        for root in config.roots:
            if not root.path.exists():
                continue
            handler = DebouncedHandler(loop, engine.handle_local_change, config.sync.debounce_seconds)
            try:
                observers.append(start_watcher(root.path, handler))
            except WatcherError as exc:
                # One unwatchable folder shouldn't stop the others from syncing.
                logger.error("%s", exc)

        @client.on(events.NewMessage(chats=config.target))
        async def _on_new_message(event):
            await engine.handle_remote_message(event.message)

        # Deliberately NOT filtered with chats=: Telegram omits the peer entirely
        # for deletions in private chats and small groups (Saved Messages
        # included), so a chats= filter would silently drop every such event.
        # handle_remote_delete identifies the file by message id via the manifest.
        @client.on(events.MessageDeleted())
        async def _on_deleted_message(event):
            await engine.handle_remote_delete(event.deleted_ids, event.chat_id)

        poll_task = asyncio.create_task(engine.poll_remote_loop())

        logger.info("Driftgram running. Watching %d folder(s). Press Ctrl+C to stop.", len(observers))

        try:
            await client.run_until_disconnected()
        except KeyboardInterrupt:
            pass
        finally:
            poll_task.cancel()
            for observer in observers:
                observer.stop()
            for observer in observers:
                observer.join(timeout=5)
            if client.is_connected():
                await client.disconnect()
            state.close()
            logger.info("Stopped cleanly.")


def main() -> None:
    config_path = sys.argv[1] if len(sys.argv) > 1 else None
    configure_logging(None)  # console only until we know where the data dir is
    try:
        asyncio.run(run(config_path))
    except KeyboardInterrupt:
        pass
    except DriftgramError as exc:
        # Config problems, a second instance, and similar are expected failures
        # with a message written for a person - print that, not a traceback.
        print(f"\n{exc}\n", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
