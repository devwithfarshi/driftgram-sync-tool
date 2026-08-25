"""Core two-way sync orchestration between local folders and a Telegram chat."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from pathlib import Path
from typing import Dict, Optional

from telethon import TelegramClient
from telethon.tl.custom.message import Message

from .config import AppConfig, RootConfig
from .ignore_rules import IgnoreMatcher
from .state import StateStore
from .tg_client import delete_messages, download_message, parse_caption, upload_file

logger = logging.getLogger("sync.engine")

HASH_CHUNK = 1024 * 1024


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(HASH_CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


class SyncEngine:
    def __init__(self, client: TelegramClient, config: AppConfig, state: StateStore):
        self.client = client
        self.config = config
        self.state = state
        self.target = config.target
        self.roots_by_alias: Dict[str, RootConfig] = {r.alias: r for r in config.roots}
        self.matchers: Dict[str, IgnoreMatcher] = {
            r.alias: IgnoreMatcher(r, config.global_ignore, config.sync) for r in config.roots
        }
        self._upload_lock = asyncio.Semaphore(3)

    # ---------- helpers ----------

    def _rel_path(self, root: RootConfig, abs_path: Path) -> Optional[str]:
        try:
            rel = abs_path.resolve().relative_to(root.path.resolve())
        except ValueError:
            return None
        rel_str = str(rel).replace("\\", "/")
        return "" if rel_str == "." else rel_str

    def _resolve_root_for_path(self, abs_path: Path) -> Optional[RootConfig]:
        for root in self.roots_by_alias.values():
            if self._rel_path(root, abs_path) is not None:
                return root
        return None

    def _too_big(self, size: int) -> bool:
        return size > self.config.sync.max_file_size_mb * 1024 * 1024

    # ---------- startup ----------

    async def initial_scan(self) -> None:
        for root in self.config.roots:
            if not root.path.exists():
                logger.warning("Root path does not exist, skipping: %s", root.path)
                continue
            matcher = self.matchers[root.alias]
            for dirpath, dirnames, filenames in os.walk(root.path):
                rel_dir = self._rel_path(root, Path(dirpath)) or ""
                dirnames[:] = [
                    d for d in dirnames
                    if not matcher.is_ignored((f"{rel_dir}/{d}" if rel_dir else d) + "/")
                ]
                for name in filenames:
                    abs_path = Path(dirpath) / name
                    rel_path = self._rel_path(root, abs_path)
                    if rel_path is None or matcher.is_ignored(rel_path):
                        continue
                    await self._maybe_upload(root, abs_path, rel_path)
        # catch up on anything sent to Telegram while we were offline
        await self.poll_remote_once()

    async def _maybe_upload(self, root: RootConfig, abs_path: Path, rel_path: str) -> None:
        try:
            stat = abs_path.stat()
        except (FileNotFoundError, PermissionError):
            return
        record = self.state.get(root.alias, rel_path)
        if record and record.local_size == stat.st_size and record.local_mtime == stat.st_mtime:
            return  # unchanged since last sync, skip re-hashing

        if self._too_big(stat.st_size):
            logger.warning("Skipping %s: exceeds max_file_size_mb", rel_path)
            return

        if stat.st_size == 0:
            # Telegram's upload API rejects 0-byte files (FilePartsInvalidError).
            # These are almost always placeholders (.gitkeep, empty locks, etc.) -
            # record them as handled so we don't retry every scan, but don't upload.
            logger.info("Skipping %s: empty file, Telegram can't store 0-byte uploads", rel_path)
            self.state.upsert(root.alias, rel_path, 0, stat.st_mtime, "empty", None)
            return

        file_hash = hash_file(abs_path)
        if record and record.local_hash == file_hash:
            # content identical (e.g. touched but not edited) - just refresh bookkeeping
            self.state.upsert(root.alias, rel_path, stat.st_size, stat.st_mtime, file_hash, record.tg_message_id)
            return

        async with self._upload_lock:
            message = await upload_file(self.client, self.target, abs_path, root.alias, rel_path)
        self.state.upsert(root.alias, rel_path, stat.st_size, stat.st_mtime, file_hash, message.id)

    # ---------- local -> remote ----------

    async def handle_local_change(self, abs_path: Path, deleted: bool) -> None:
        root = self._resolve_root_for_path(abs_path)
        if root is None:
            return
        rel_path = self._rel_path(root, abs_path)
        if rel_path is None or not rel_path or self.matchers[root.alias].is_ignored(rel_path):
            return

        if deleted or not abs_path.exists():
            await self._handle_local_delete(root, rel_path)
            return

        try:
            await self._maybe_upload(root, abs_path, rel_path)
        except Exception:
            logger.exception("Failed to sync local change for %s", rel_path)

    async def _handle_local_delete(self, root: RootConfig, rel_path: str) -> None:
        record = self.state.get(root.alias, rel_path)
        if not record:
            return
        if self.config.sync.delete_remote_on_local_delete and record.tg_message_id:
            try:
                await delete_messages(self.client, self.target, [record.tg_message_id])
            except Exception:
                logger.exception("Failed to delete remote message for %s", rel_path)
        self.state.delete(root.alias, rel_path)

    # ---------- remote -> local ----------

    async def handle_remote_message(self, message: Message) -> None:
        try:
            await self._handle_remote_message_inner(message)
        except Exception:
            logger.exception("Failed to process remote message %s", message.id)
        finally:
            self._bump_offset(message.id)

    def _bump_offset(self, message_id: int) -> None:
        last_id = int(self.state.get_meta("last_offset_id") or 0)
        if message_id > last_id:
            self.state.set_meta("last_offset_id", str(message_id))

    async def _handle_remote_message_inner(self, message: Message) -> None:
        if not message.file:
            return
        parsed = parse_caption(message.text)
        if not parsed:
            return
        alias, rel_path = parsed
        root = self.roots_by_alias.get(alias)
        if root is None:
            logger.warning("Message references unknown root alias '%s' - skipping (id=%s)", alias, message.id)
            return
        if not rel_path or self.matchers[root.alias].is_ignored(rel_path):
            return

        # Already known - this is an echo of a message we already recorded (most likely our own upload).
        existing_by_id = self.state.get_by_message_id(message.id)
        if existing_by_id is not None:
            return

        dest_path = (root.path / rel_path).resolve()
        if self._resolve_root_for_path(dest_path) is None:
            logger.warning("Refusing to write outside configured sync root: %s", rel_path)
            return

        if self._too_big(message.file.size or 0):
            logger.warning("Skipping remote file %s: exceeds max_file_size_mb", rel_path)
            return

        record = self.state.get(root.alias, rel_path)
        if record and record.tg_message_id and record.tg_message_id >= message.id:
            return  # already have this version or newer

        await download_message(self.client, message, dest_path)
        stat = dest_path.stat()
        file_hash = hash_file(dest_path)
        self.state.upsert(root.alias, rel_path, stat.st_size, stat.st_mtime, file_hash, message.id)

    async def poll_remote_once(self) -> None:
        last_id = int(self.state.get_meta("last_offset_id") or 0)
        async for message in self.client.iter_messages(self.target, min_id=last_id, reverse=True):
            await self.handle_remote_message(message)

    async def poll_remote_loop(self) -> None:
        while True:
            await asyncio.sleep(self.config.sync.poll_interval_seconds)
            try:
                await self.poll_remote_once()
            except Exception:
                logger.exception("Error while polling Telegram for changes")
