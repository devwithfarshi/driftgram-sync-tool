"""A stand-in for Telethon, so the sync engine can be tested without Telegram.

Mirrors only what SyncEngine actually calls: send_file, iter_messages,
download_media, delete_messages, get_entity. Messages are kept in a list in
ascending id order, which is exactly how a real chat behaves for our purposes
- ids increase, deleted messages vanish from iteration.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional


class FakeFile:
    def __init__(self, size: int):
        self.size = size


class FakeMessage:
    def __init__(self, message_id: int, text: str, payload: bytes):
        self.id = message_id
        self.text = text
        self.payload = payload
        self.file = FakeFile(len(payload))
        self.date = None


class FakeClient:
    """Records everything it is asked to do, so tests can assert on API calls."""

    def __init__(self):
        self.messages: List[FakeMessage] = []
        self._next_id = 1
        self.uploads: List[str] = []          # captions, in send order
        self.downloads: List[str] = []        # destination paths, in download order
        self.deleted: List[int] = []

    # --- helpers used by tests, not by the engine ---

    def push(self, caption: str, payload: bytes) -> FakeMessage:
        """Simulate a file arriving from another device."""
        message = FakeMessage(self._next_id, caption, payload)
        self._next_id += 1
        self.messages.append(message)
        return message

    def drop(self, message_id: int) -> None:
        self.messages = [m for m in self.messages if m.id != message_id]

    # --- the Telethon surface the engine uses ---

    async def send_file(self, target, file=None, caption=None, force_document=None,
                        progress_callback=None):
        assert force_document is True, "uploads must be documents or Telegram recompresses them"
        payload = Path(file).read_bytes()
        message = self.push(caption, payload)
        self.uploads.append(caption)
        if progress_callback:
            progress_callback(len(payload), len(payload))
        return message

    async def download_media(self, message, file=None, progress_callback=None):
        Path(file).write_bytes(message.payload)
        self.downloads.append(str(file))
        if progress_callback:
            progress_callback(len(message.payload), len(message.payload))
        return file

    async def iter_messages(self, target, min_id: int = 0, reverse: bool = False):
        ordered = sorted(self.messages, key=lambda m: m.id, reverse=not reverse)
        for message in ordered:
            if min_id and message.id <= min_id:
                continue
            yield message

    async def delete_messages(self, target, message_ids):
        for message_id in message_ids:
            self.drop(message_id)
            self.deleted.append(message_id)

    async def get_entity(self, target):
        return _FakePeer()


class _FakePeer:
    user_id = 424242
