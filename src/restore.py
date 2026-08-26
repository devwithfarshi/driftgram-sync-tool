"""Driftgram: pull files back down from Telegram to disk.

The live sync only ever looks at Telegram messages *newer* than the recorded
offset, so a file deleted locally after it was uploaded never comes back on
its own - its message is behind the offset and the manifest row is gone.
This tool walks the full chat history instead, rebuilds the newest Telegram
version of every synced path, and downloads the ones you ask for.

Usage (stop `python -m src.main` first - both processes share one Telegram
session file and one manifest, and the instance lock now enforces that):

    python -m src.restore --list                 # what's in Telegram, and what's missing locally
    python -m src.restore                        # restore everything missing from disk
    python -m src.restore report.docx notes/     # restore matching paths only
    python -m src.restore report.docx --force    # overwrite the local copy too

Every restored file is written to the manifest with its real size/mtime/hash
and message id, so the watcher sees it as already-synced and does not bounce
it back up as a fresh upload.

The desktop app does all of this in its Restore tab, in the same process as
the running sync - so it never has to be stopped first. The history walk and
the download loop live in SyncEngine so both front ends share one
implementation.
"""
from __future__ import annotations

import argparse
import asyncio
import fnmatch
import logging
import sys
from typing import List

from telethon import TelegramClient

from .app.instance_lock import InstanceLock
from .app.logging_setup import configure as configure_logging
from .config import load_config
from .errors import DriftgramError
from .fsutil import human_bytes
from .state import StateStore
from .sync_engine import RemoteFile, SyncEngine

logger = logging.getLogger("driftgram.restore")


def _matches(rel_path: str, patterns: List[str]) -> bool:
    if not patterns:
        return True
    for pat in patterns:
        pat = pat.replace("\\", "/").rstrip("/")
        if fnmatch.fnmatch(rel_path, pat) or fnmatch.fnmatch(rel_path, f"*{pat}*"):
            return True
    return False


async def run(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    config.paths.ensure_dirs()
    configure_logging(config.paths.log_file)

    with InstanceLock(config.paths.lock_file):
        state = StateStore(config.state_db_path)
        client = TelegramClient(str(config.session_file), config.api_id, config.api_hash)
        await client.start()
        try:
            engine = SyncEngine(client, config, state)
            available = await engine.collect_remote_index()

            selected: List[RemoteFile] = []
            for item in available:
                if not _matches(item.rel_path, args.patterns):
                    continue
                if item.ignored and not args.include_ignored:
                    logger.info(
                        "Skipping %s: matches an ignore pattern (use --include-ignored)", item.rel_path
                    )
                    continue
                selected.append(item)

            if args.list:
                for item in selected:
                    mark = "on disk" if item.exists_locally else "MISSING"
                    print(
                        f"[{mark:>7}] {item.alias}/{item.rel_path}  "
                        f"({human_bytes(item.size)}, msg {item.message_id})"
                    )
                missing = sum(1 for s in selected if not s.exists_locally)
                print(f"\n{len(selected)} path(s); {missing} missing locally.")
                return 0

            todo = [s for s in selected if not s.exists_locally or args.force]
            if not todo:
                if selected:
                    print(
                        f"Nothing to restore. {len(selected)} matching path(s) already exist on "
                        "disk - pass --force to overwrite them with the Telegram copy."
                    )
                else:
                    print("Nothing in Telegram matched.")
                return 0

            def announce(item: RemoteFile, index: int, total: int) -> None:
                action = "Overwriting" if item.exists_locally else "Restoring"
                logger.info("[%d/%d] %s %s (msg %s)", index, total, action, item.rel_path, item.message_id)

            restored = await engine.restore_files(todo, overwrite=args.force, on_each=announce)
            print(f"\nRestored {restored} file(s). Manifest updated - the watcher will not re-upload them.")
            return 0
        finally:
            if client.is_connected():
                await client.disconnect()
            state.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m src.restore",
        description="Pull files back down from Telegram into the local sync roots.",
    )
    parser.add_argument(
        "patterns",
        nargs="*",
        help="Path fragments or globs to restore (relative to a sync root). Omit to restore everything missing locally.",
    )
    parser.add_argument("--config", default=None, help="Config file path (default: config.yaml, then the app's own)")
    parser.add_argument("--list", action="store_true", help="List what Telegram holds without downloading anything")
    parser.add_argument("--force", action="store_true", help="Overwrite local files that already exist")
    parser.add_argument(
        "--include-ignored", action="store_true", help="Also restore paths matched by your ignore patterns"
    )
    args = parser.parse_args()
    configure_logging(None)
    try:
        sys.exit(asyncio.run(run(args)))
    except KeyboardInterrupt:
        sys.exit(130)
    except DriftgramError as exc:
        print(f"\n{exc}\n", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
