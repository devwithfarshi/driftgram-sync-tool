"""Driftgram: pull files back down from Telegram to disk.

The live sync only ever looks at Telegram messages *newer* than the recorded
offset, so a file deleted locally after it was uploaded never comes back on
its own - its message is behind the offset and the manifest row is gone.
This tool walks the full chat history instead, rebuilds the newest Telegram
version of every synced path, and downloads the ones you ask for.

Usage (stop `python -m src.main` first - both processes share one Telegram
session file and one manifest):

    python -m src.restore --list                 # what's in Telegram, and what's missing locally
    python -m src.restore                        # restore everything missing from disk
    python -m src.restore report.docx notes/     # restore matching paths only
    python -m src.restore report.docx --force    # overwrite the local copy too

Every restored file is written to the manifest with its real size/mtime/hash
and message id, so the watcher sees it as already-synced and does not bounce
it back up as a fresh upload.
"""
from __future__ import annotations

import argparse
import asyncio
import fnmatch
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from telethon import TelegramClient

from .config import load_config
from .ignore_rules import IgnoreMatcher
from .state import StateStore
from .sync_engine import hash_file
from .tg_client import download_message, parse_caption

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("driftgram.restore")


def _matches(rel_path: str, patterns: List[str]) -> bool:
    if not patterns:
        return True
    for pat in patterns:
        pat = pat.replace("\\", "/").rstrip("/")
        if fnmatch.fnmatch(rel_path, pat) or fnmatch.fnmatch(rel_path, f"*{pat}*"):
            return True
    return False


async def collect_remote(client: TelegramClient, target) -> Dict[Tuple[str, str], object]:
    """Newest message per (alias, rel_path) across the whole chat history."""
    newest: Dict[Tuple[str, str], object] = {}
    scanned = 0
    async for message in client.iter_messages(target):  # newest first
        scanned += 1
        if not message.file:
            continue
        parsed = parse_caption(message.text)
        if not parsed:
            continue
        newest.setdefault(parsed, message)  # first hit wins = highest message id
    logger.info("Scanned %d messages, found %d synced file path(s) in Telegram.", scanned, len(newest))
    return newest


async def run(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    state = StateStore(config.state_db_path)
    roots_by_alias = {r.alias: r for r in config.roots}
    matchers = {r.alias: IgnoreMatcher(r, config.global_ignore, config.sync) for r in config.roots}

    client = TelegramClient(config.session_name, config.api_id, config.api_hash)
    await client.start()
    try:
        newest = await collect_remote(client, config.target)

        selected: List[Tuple[str, str, object, Path, bool]] = []
        for (alias, rel_path), message in sorted(newest.items()):
            root = roots_by_alias.get(alias)
            if root is None:
                logger.warning("Skipping '%s/%s': no root configured with alias '%s'", alias, rel_path, alias)
                continue
            if not _matches(rel_path, args.patterns):
                continue
            if matchers[alias].is_ignored(rel_path) and not args.include_ignored:
                logger.info("Skipping %s: matches an ignore pattern (use --include-ignored)", rel_path)
                continue
            dest = (root.path / rel_path).resolve()
            try:
                dest.relative_to(root.path.resolve())
            except ValueError:
                logger.warning("Refusing to write outside sync root: %s", rel_path)
                continue
            selected.append((alias, rel_path, message, dest, dest.exists()))

        if args.list:
            for alias, rel_path, message, dest, exists in selected:
                mark = "on disk" if exists else "MISSING"
                size = message.file.size or 0
                print(f"[{mark:>7}] {alias}/{rel_path}  ({size} bytes, msg {message.id})")
            print(f"\n{len(selected)} path(s); {sum(1 for s in selected if not s[4])} missing locally.")
            return 0

        todo = [s for s in selected if not s[4] or args.force]
        if not todo:
            skipped = len(selected)
            print(
                f"Nothing to restore. {skipped} matching path(s) already exist on disk "
                "- pass --force to overwrite them with the Telegram copy."
                if skipped
                else "Nothing in Telegram matched."
            )
            return 0

        for alias, rel_path, message, dest, exists in todo:
            action = "Overwriting" if exists else "Restoring"
            logger.info("%s %s (msg %s)", action, rel_path, message.id)
            await download_message(client, message, dest)
            stat = dest.stat()
            state.upsert(alias, rel_path, stat.st_size, stat.st_mtime, hash_file(dest), message.id)

        print(f"\nRestored {len(todo)} file(s). Manifest updated - the watcher will not re-upload them.")
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
    parser.add_argument("--config", default="config.yaml", help="Config file path (default: config.yaml)")
    parser.add_argument("--list", action="store_true", help="List what Telegram holds without downloading anything")
    parser.add_argument("--force", action="store_true", help="Overwrite local files that already exist")
    parser.add_argument(
        "--include-ignored", action="store_true", help="Also restore paths matched by your ignore patterns"
    )
    args = parser.parse_args()
    try:
        sys.exit(asyncio.run(run(args)))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
