"""Driftgram: Telethon helpers - caption encode/decode, upload, download, delete.

Every file is sent with force_document=True so Telegram never recompresses
or transcodes it - what comes back down is byte-for-byte what went up.
The caption is how the tool maps a Telegram message back to a local path:

    DRIFTGRAM
    <root alias>
    <relative path>

Both transfer helpers accept an optional progress_callback(done, total).
Telethon calls it per chunk, which is far too often to drive a UI directly -
callers are expected to throttle before turning those into events.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional, Tuple

from telethon import TelegramClient

logger = logging.getLogger("driftgram.telegram")

CAPTION_PREFIX = "DRIFTGRAM"

ProgressCallback = Callable[[int, int], None]


def make_caption(alias: str, rel_path: str) -> str:
    return f"{CAPTION_PREFIX}\n{alias}\n{rel_path}"


def parse_caption(caption: Optional[str]) -> Optional[Tuple[str, str]]:
    if not caption:
        return None
    lines = caption.split("\n")
    if len(lines) < 3 or lines[0] != CAPTION_PREFIX:
        return None
    alias = lines[1]
    rel_path = "\n".join(lines[2:])
    return alias, rel_path


async def upload_file(
    client: TelegramClient,
    target,
    local_path: Path,
    alias: str,
    rel_path: str,
    progress_callback: Optional[ProgressCallback] = None,
):
    caption = make_caption(alias, rel_path)
    logger.info("Uploading %s", rel_path)
    message = await client.send_file(
        target,
        file=str(local_path),
        caption=caption,
        force_document=True,
        progress_callback=progress_callback,
    )
    return message


async def download_message(
    client: TelegramClient,
    message,
    dest_path: Path,
    progress_callback: Optional[ProgressCallback] = None,
) -> None:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_name(dest_path.name + ".driftgram-tmp")
    logger.info("Downloading -> %s", dest_path)
    try:
        await client.download_media(message, file=str(tmp_path), progress_callback=progress_callback)
        tmp_path.replace(dest_path)
    finally:
        # A cancelled or failed download must not leave a stray .driftgram-tmp
        # sitting in a synced folder, where the watcher would try to upload it.
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                logger.warning("Could not clean up temp file %s", tmp_path)


async def delete_messages(client: TelegramClient, target, message_ids) -> None:
    if not message_ids:
        return
    await client.delete_messages(target, message_ids)
