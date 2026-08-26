"""Driftgram: core two-way sync between local folders and a Telegram chat.

THE INVARIANT: nothing is uploaded or downloaded unless its content differs
from what the manifest last recorded, and the manifest is updated immediately
after acting, before returning. That is what stops the two-way echo loop
(upload -> reappears as a Telegram message -> "downloads" -> touches the file
-> watcher fires -> re-uploads -> forever). Everything else in this file is
reporting and policy; that rule is correctness.

Added for the desktop app, all of it optional and inert for the CLI:
  * an EventBus so a window can show which file is moving and how far along
  * pause/resume, where resume re-runs a full scan rather than trying to
    queue up what was missed
  * conflict handling, so a remote copy can no longer silently overwrite
    local edits that were never uploaded
  * remote listing and restore in-process, so the app never needs the
    separate src.restore process that would fight it for the session file
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from telethon import TelegramClient, utils
from telethon.tl.custom.message import Message

from .config import AppConfig, ConflictPolicy, RootConfig
from .events import EventBus, EventKind, NullBus, RunState, SyncEvent
from .fsutil import conflict_path, unwritable_reason
from .ignore_rules import IgnoreMatcher
from .state import StateStore
from .tg_client import delete_messages, download_message, parse_caption, upload_file

logger = logging.getLogger("driftgram.engine")

HASH_CHUNK = 1024 * 1024
#: Don't emit progress for files small enough to finish before a bar renders.
PROGRESS_MIN_BYTES = 512 * 1024
#: Telethon calls progress callbacks per chunk; throttle to something a UI can use.
PROGRESS_INTERVAL = 0.25
#: How often the scan reports how far it has got.
SCAN_REPORT_EVERY = 25


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(HASH_CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


@dataclass
class RemoteFile:
    """One synced path as Telegram currently holds it - the restore browser's row."""

    alias: str
    rel_path: str
    message_id: int
    size: int
    local_path: Path
    exists_locally: bool
    ignored: bool
    date: Optional[object] = None
    message: Optional[Message] = field(default=None, repr=False, compare=False)


class SyncEngine:
    def __init__(
        self,
        client: TelegramClient,
        config: AppConfig,
        state: StateStore,
        events: Optional[EventBus] = None,
    ):
        self.client = client
        self.config = config
        self.state = state
        self.events = events or NullBus()
        self.target = config.target
        self.roots_by_alias: Dict[str, RootConfig] = {r.alias: r for r in config.roots}
        self.matchers: Dict[str, IgnoreMatcher] = {
            r.alias: IgnoreMatcher(r, config.global_ignore, config.sync) for r in config.roots
        }
        self._upload_lock = asyncio.Semaphore(3)
        # Resolved peer id of the sync target, filled in by resolve_target().
        # Only used to filter channel delete events - private-chat deletions
        # arrive without any chat id at all (see handle_remote_delete).
        self.target_chat_id: Optional[int] = None
        self._paused = False
        self._stopping = False

    # ---------- helpers ----------

    def _rel_path(self, root: RootConfig, abs_path: Path) -> Optional[str]:
        try:
            rel = abs_path.resolve().relative_to(root.path.resolve())
        except (ValueError, OSError):
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

    def _progress_cb(
        self, kind: EventKind, alias: str, rel_path: str, total: int
    ) -> Optional[Callable[[int, int], None]]:
        if total < PROGRESS_MIN_BYTES:
            return None
        last = [0.0]

        def report(done: int, size: int) -> None:
            now = time.monotonic()
            if done < size and now - last[0] < PROGRESS_INTERVAL:
                return
            last[0] = now
            self.events.file(kind, alias, rel_path, bytes_done=done, bytes_total=size)

        return report

    # ---------- run control ----------

    @property
    def paused(self) -> bool:
        return self._paused

    def set_paused(self, paused: bool) -> None:
        """Stop acting on changes without tearing anything down.

        Nothing is queued while paused: local edits are found again by the
        next scan, and remote messages are left unconsumed (handle_remote_message
        returns before bumping the offset), so the catch-up poll re-delivers
        them. Resume therefore just means 'scan again'.
        """
        self._paused = paused
        self.events.status(RunState.PAUSED if paused else RunState.IDLE)

    def request_stop(self) -> None:
        """Ask a long-running scan to give up at the next file."""
        self._stopping = True

    def clear_stop(self) -> None:
        self._stopping = False

    # ---------- startup ----------

    async def resolve_target(self) -> None:
        try:
            self.target_chat_id = utils.get_peer_id(await self.client.get_entity(self.target))
        except Exception:
            logger.warning("Could not resolve target '%s' to a chat id", self.target, exc_info=True)

    async def initial_scan(self) -> None:
        """Walk every root, upload whatever the manifest doesn't already know about."""
        self.events.status(RunState.SCANNING)
        self.events.emit(SyncEvent(EventKind.SCAN_STARTED, message="Checking your folders..."))
        checked = uploaded = 0
        last_report = time.monotonic()

        for root in self.config.roots:
            if self._stopping:
                break
            if not root.path.exists():
                logger.warning("Root path does not exist, skipping: %s", root.path)
                self.events.error(
                    f"Folder not found: {root.path}. It may be on a drive that isn't connected.",
                    alias=root.alias,
                )
                continue
            matcher = self.matchers[root.alias]
            for dirpath, dirnames, filenames in os.walk(root.path):
                if self._stopping:
                    break
                rel_dir = self._rel_path(root, Path(dirpath)) or ""
                dirnames[:] = [
                    d for d in dirnames
                    if not matcher.is_ignored((f"{rel_dir}/{d}" if rel_dir else d) + "/")
                ]
                for name in filenames:
                    if self._stopping or self._paused:
                        break
                    abs_path = Path(dirpath) / name
                    rel_path = self._rel_path(root, abs_path)
                    if rel_path is None or matcher.is_ignored(rel_path):
                        continue
                    checked += 1
                    if await self._maybe_upload(root, abs_path, rel_path):
                        uploaded += 1
                    now = time.monotonic()
                    if checked % SCAN_REPORT_EVERY == 0 or now - last_report > 1.0:
                        last_report = now
                        self.events.emit(_scan_progress(checked, uploaded))

        self.events.emit(_scan_finished(checked, uploaded))
        # catch up on anything sent to Telegram while we were offline
        await self.poll_remote_once()
        if not self._paused:
            self.events.status(RunState.IDLE)

    async def _maybe_upload(self, root: RootConfig, abs_path: Path, rel_path: str) -> bool:
        """Upload if and only if content differs from the manifest. Returns True if uploaded."""
        try:
            stat = abs_path.stat()
        except (FileNotFoundError, PermissionError, OSError):
            return False
        record = self.state.get(root.alias, rel_path)
        if record and record.local_size == stat.st_size and record.local_mtime == stat.st_mtime:
            return False  # unchanged since last sync, skip re-hashing

        if self._too_big(stat.st_size):
            logger.warning("Skipping %s: exceeds max_file_size_mb", rel_path)
            self.events.file(
                EventKind.SKIPPED, root.alias, rel_path,
                message=f"larger than the {self.config.sync.max_file_size_mb} MB limit",
            )
            return False

        if stat.st_size == 0:
            # Telegram's upload API rejects 0-byte files (FilePartsInvalidError).
            # These are almost always placeholders (.gitkeep, empty locks, etc.) -
            # record them as handled so we don't retry every scan, but don't upload.
            logger.info("Skipping %s: empty file, Telegram can't store 0-byte uploads", rel_path)
            self.state.upsert(root.alias, rel_path, 0, stat.st_mtime, "empty", None)
            return False

        try:
            file_hash = hash_file(abs_path)
        except (OSError, PermissionError) as exc:
            self.events.file(EventKind.SKIPPED, root.alias, rel_path, message=f"couldn't be read ({exc})")
            return False

        if record and record.local_hash == file_hash:
            # content identical (e.g. touched but not edited) - just refresh bookkeeping
            self.state.upsert(root.alias, rel_path, stat.st_size, stat.st_mtime, file_hash, record.tg_message_id)
            return False

        self.events.file(
            EventKind.UPLOAD_STARTED, root.alias, rel_path, bytes_total=stat.st_size, bytes_done=0
        )
        async with self._upload_lock:
            self.events.status(RunState.SYNCING)
            message = await upload_file(
                self.client, self.target, abs_path, root.alias, rel_path,
                progress_callback=self._progress_cb(
                    EventKind.UPLOAD_PROGRESS, root.alias, rel_path, stat.st_size
                ),
            )
        self.state.upsert(root.alias, rel_path, stat.st_size, stat.st_mtime, file_hash, message.id)
        self.events.file(
            EventKind.UPLOAD_FINISHED, root.alias, rel_path,
            bytes_total=stat.st_size, bytes_done=stat.st_size,
        )
        return True

    # ---------- local -> remote ----------

    async def handle_local_change(self, abs_path: Path, deleted: bool) -> None:
        if self._paused:
            return  # picked up by the rescan on resume
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
        except Exception as exc:
            logger.exception("Failed to sync local change for %s", rel_path)
            self.events.error(f"Couldn't back up {rel_path}: {exc}", alias=root.alias, rel_path=rel_path)
        finally:
            if not self._paused:
                self.events.status(RunState.IDLE)

    async def _handle_local_delete(self, root: RootConfig, rel_path: str) -> None:
        record = self.state.get(root.alias, rel_path)
        if not record:
            return
        if self.config.sync.delete_remote_on_local_delete and record.tg_message_id:
            try:
                await delete_messages(self.client, self.target, [record.tg_message_id])
                self.events.file(EventKind.REMOTE_DELETED, root.alias, rel_path)
            except Exception as exc:
                logger.exception("Failed to delete remote message for %s", rel_path)
                self.events.error(
                    f"Couldn't remove {rel_path} from Telegram: {exc}", alias=root.alias, rel_path=rel_path
                )
        self.state.delete(root.alias, rel_path)

    # ---------- remote -> local ----------

    async def handle_remote_message(self, message: Message) -> None:
        if self._paused:
            # Deliberately no _bump_offset: leaving the message unconsumed is
            # what lets the catch-up poll re-deliver it after resume.
            return
        try:
            await self._handle_remote_message_inner(message)
        except Exception as exc:
            logger.exception("Failed to process remote message %s", message.id)
            self.events.error(f"Couldn't download a file from Telegram: {exc}")
        finally:
            self._bump_offset(message.id)

    def _bump_offset(self, message_id: int) -> None:
        last_id = int(self.state.get_meta("last_offset_id") or 0)
        if message_id > last_id:
            self.state.set_meta("last_offset_id", str(message_id))

    def _local_has_diverged(self, dest_path: Path, record) -> bool:
        """Does the file on disk differ from what the manifest last recorded for it?

        True means the user changed it since the last sync and that change has
        not reached Telegram yet - so overwriting it would destroy work.
        """
        if not dest_path.exists():
            return False
        if record is None:
            return True  # a file we have never seen; treat as the user's own
        try:
            stat = dest_path.stat()
        except OSError:
            return False
        if record.local_size == stat.st_size and record.local_mtime == stat.st_mtime:
            return False
        try:
            return hash_file(dest_path) != record.local_hash
        except OSError:
            return True  # can't prove it is safe to overwrite, so assume it isn't

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

        blocked = unwritable_reason(rel_path)
        if blocked:
            logger.warning("Cannot write %s here: %s", rel_path, blocked)
            self.events.file(EventKind.SKIPPED, alias, rel_path, message=blocked)
            return

        dest_path = (root.path / rel_path).resolve()
        if self._resolve_root_for_path(dest_path) is None:
            logger.warning("Refusing to write outside configured sync root: %s", rel_path)
            return

        if self._too_big(message.file.size or 0):
            logger.warning("Skipping remote file %s: exceeds max_file_size_mb", rel_path)
            self.events.file(
                EventKind.SKIPPED, alias, rel_path,
                message=f"larger than the {self.config.sync.max_file_size_mb} MB limit",
            )
            return

        record = self.state.get(root.alias, rel_path)
        if record and record.tg_message_id and record.tg_message_id >= message.id:
            return  # already have this version or newer

        write_to = dest_path
        conflicted = False
        if self._local_has_diverged(dest_path, record):
            policy = self.config.sync.conflict_policy
            if policy is ConflictPolicy.LOCAL_WINS:
                self.events.file(
                    EventKind.SKIPPED, alias, rel_path,
                    message="you have newer local changes and 'always keep my copy' is on",
                )
                return
            if policy is ConflictPolicy.KEEP_BOTH:
                write_to = conflict_path(dest_path)
                conflicted = True
            # REMOTE_WINS falls through and overwrites, as it always did.

        size = message.file.size or 0
        self.events.file(EventKind.DOWNLOAD_STARTED, alias, rel_path, bytes_total=size, bytes_done=0)
        self.events.status(RunState.SYNCING)
        await download_message(
            self.client, message, write_to,
            progress_callback=self._progress_cb(EventKind.DOWNLOAD_PROGRESS, alias, rel_path, size),
        )

        if conflicted:
            # The manifest row still describes the user's own file at rel_path,
            # which is still there and still unsynced - so it must not be
            # overwritten with the downloaded copy's stats. The conflict copy is
            # left unrecorded on purpose: it is a genuinely new local file, and
            # the watcher will back it up as one.
            logger.info("Conflict on %s - kept both, Telegram's copy is %s", rel_path, write_to.name)
            self.events.emit(
                SyncEvent(
                    EventKind.CONFLICT,
                    alias=alias,
                    rel_path=rel_path,
                    message=f"your version was kept; Telegram's copy saved as {write_to.name}",
                    extra={"conflict_copy": str(write_to)},
                )
            )
            return

        stat = dest_path.stat()
        file_hash = hash_file(dest_path)
        self.state.upsert(root.alias, rel_path, stat.st_size, stat.st_mtime, file_hash, message.id)
        self.events.file(
            EventKind.DOWNLOAD_FINISHED, alias, rel_path, bytes_total=size, bytes_done=size
        )

    async def handle_remote_delete(self, deleted_ids, chat_id: Optional[int]) -> None:
        """Mirror a Telegram message deletion by removing the local file.

        Telegram only reports *where* a deletion happened for channels; for
        private chats and small groups (including Saved Messages) the update
        carries bare message ids and no peer. That is safe to work with,
        because non-channel message ids are unique per account - so the
        manifest lookup below identifies the file unambiguously. When a chat
        id *is* present we still check it, to avoid acting on deletions in
        some unrelated channel that happens to reuse an id.
        """
        if not self.config.sync.delete_local_on_remote_delete or self._paused:
            return
        if chat_id is not None and self.target_chat_id is not None and chat_id != self.target_chat_id:
            return

        for message_id in deleted_ids or []:
            record = self.state.get_by_message_id(message_id)
            if record is None:
                continue  # not a file we track
            root = self.roots_by_alias.get(record.root_alias)
            if root is None:
                continue
            abs_path = (root.path / record.rel_path).resolve()
            if self._resolve_root_for_path(abs_path) is None:
                logger.warning("Refusing to delete outside configured sync root: %s", record.rel_path)
                continue

            logger.info("Remote deletion of msg %s -> removing %s", message_id, record.rel_path)
            # No `await` between the unlink and the manifest delete: the local
            # watcher will fire on this deletion, and _handle_local_delete must
            # find no record (otherwise, with delete_remote_on_local_delete on,
            # it would try to delete the already-deleted message).
            try:
                abs_path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                logger.exception("Failed to delete local file %s", record.rel_path)
                continue
            self.state.delete(record.root_alias, record.rel_path)
            self.events.file(EventKind.LOCAL_DELETED, record.root_alias, record.rel_path)

    async def poll_remote_once(self) -> None:
        if self._paused:
            return
        last_id = int(self.state.get_meta("last_offset_id") or 0)
        async for message in self.client.iter_messages(self.target, min_id=last_id, reverse=True):
            if self._stopping or self._paused:
                return
            await self.handle_remote_message(message)

    async def poll_remote_loop(self) -> None:
        while not self._stopping:
            await asyncio.sleep(self.config.sync.poll_interval_seconds)
            if self._paused:
                continue
            try:
                await self.poll_remote_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Error while polling Telegram for changes")

    # ---------- restore (full-history browse and pull-back) ----------

    async def collect_remote_index(
        self, on_progress: Optional[Callable[[int, int], None]] = None
    ) -> List[RemoteFile]:
        """Newest Telegram message per (alias, rel_path) across the WHOLE history.

        The live sync only ever looks at messages newer than last_offset_id,
        so a file deleted locally after upload can never come back on its own.
        This walks everything, which is why it is a deliberate user action
        rather than something that runs on a timer.
        """
        newest: Dict[Tuple[str, str], Message] = {}
        scanned = 0
        async for message in self.client.iter_messages(self.target):  # newest first
            scanned += 1
            if on_progress and scanned % 50 == 0:
                on_progress(scanned, len(newest))
            if not message.file:
                continue
            parsed = parse_caption(message.text)
            if not parsed:
                continue
            newest.setdefault(parsed, message)  # first hit wins = highest message id
        logger.info("Scanned %d messages, found %d synced file path(s).", scanned, len(newest))

        results: List[RemoteFile] = []
        for (alias, rel_path), message in sorted(newest.items()):
            root = self.roots_by_alias.get(alias)
            if root is None:
                continue
            dest = (root.path / rel_path).resolve()
            try:
                dest.relative_to(root.path.resolve())
            except ValueError:
                logger.warning("Refusing to write outside sync root: %s", rel_path)
                continue
            results.append(
                RemoteFile(
                    alias=alias,
                    rel_path=rel_path,
                    message_id=message.id,
                    size=message.file.size or 0,
                    local_path=dest,
                    exists_locally=dest.exists(),
                    ignored=self.matchers[alias].is_ignored(rel_path),
                    date=getattr(message, "date", None),
                    message=message,
                )
            )
        return results

    async def restore_files(
        self,
        files: Sequence[RemoteFile],
        *,
        overwrite: bool = False,
        on_each: Optional[Callable[[RemoteFile, int, int], None]] = None,
    ) -> int:
        """Download the given files and record them as already-synced.

        Writing the manifest is the point: without it the watcher would see
        each restored file as brand new and immediately upload it again.
        """
        done = 0
        total = len(files)
        for index, item in enumerate(files, start=1):
            if self._stopping:
                break
            if item.exists_locally and not overwrite:
                continue
            if on_each:
                on_each(item, index, total)
            blocked = unwritable_reason(item.rel_path)
            if blocked:
                self.events.file(EventKind.SKIPPED, item.alias, item.rel_path, message=blocked)
                continue
            self.events.file(
                EventKind.DOWNLOAD_STARTED, item.alias, item.rel_path,
                bytes_total=item.size, bytes_done=0,
            )
            try:
                await download_message(
                    self.client, item.message, item.local_path,
                    progress_callback=self._progress_cb(
                        EventKind.DOWNLOAD_PROGRESS, item.alias, item.rel_path, item.size
                    ),
                )
            except Exception as exc:
                logger.exception("Failed to restore %s", item.rel_path)
                self.events.error(f"Couldn't restore {item.rel_path}: {exc}", alias=item.alias)
                continue
            stat = item.local_path.stat()
            self.state.upsert(
                item.alias, item.rel_path, stat.st_size, stat.st_mtime,
                hash_file(item.local_path), item.message_id,
            )
            self.events.file(
                EventKind.DOWNLOAD_FINISHED, item.alias, item.rel_path,
                bytes_total=item.size, bytes_done=item.size,
            )
            done += 1
        return done


# --- module-level event builders, kept out of the class for readability ---


def _scan_progress(checked: int, uploaded: int) -> SyncEvent:
    return SyncEvent(
        EventKind.SCAN_PROGRESS,
        message=f"Checked {checked:,} files, backed up {uploaded:,}",
        extra={"checked": checked, "uploaded": uploaded},
    )


def _scan_finished(checked: int, uploaded: int) -> SyncEvent:
    return SyncEvent(
        EventKind.SCAN_FINISHED,
        message=f"Checked {checked:,} files, backed up {uploaded:,}",
        extra={"checked": checked, "uploaded": uploaded},
    )
