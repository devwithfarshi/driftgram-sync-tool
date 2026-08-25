"""Driftgram: Telethon helpers - caption encode/decode, upload, download, delete.

Every file is sent with force_document=True so Telegram never recompresses
or transcodes it - what comes back down is byte-for-byte what went up.
The caption is how the tool maps a Telegram message back to a local path:

    DRIFTGRAM
    <root alias>
    <relative path>
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Tuple

from telethon import TelegramClient

logger = logging.getLogger("driftgram.telegram")

CAPTION_PREFIX = "DRIFTGRAM"


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


async def upload_file(client: TelegramClient, target, local_path: Path, alias: str, rel_path: str):
    caption = make_caption(alias, rel_path)
    logger.info("Uploading %s", rel_path)
    message = await client.send_file(
        target,
        file=str(local_path),
        caption=caption,
        force_document=True,
    )
    return message


async def download_message(client: TelegramClient, message, dest_path: Path) -> None:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_name(dest_path.name + ".driftgram-tmp")
    logger.info("Downloading -> %s", dest_path)
    await client.download_media(message, file=str(tmp_path))
    tmp_path.replace(dest_path)


async def delete_messages(client: TelegramClient, target, message_ids) -> None:
    if not message_ids:
        return
    await client.delete_messages(target, message_ids)
