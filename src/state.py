"""Driftgram Sync Tool: SQLite-backed manifest of what has been synced.

This is what makes two-way sync safe: every file's last-known size/mtime/hash
and Telegram message id are recorded here. Both the local watcher and the
Telegram listener compare against this manifest before acting, which is what
stops an upload from bouncing back down as a "new" remote file (and vice
versa) - the classic two-way-sync echo loop.
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class FileRecord:
    root_alias: str
    rel_path: str
    local_size: Optional[int]
    local_mtime: Optional[float]
    local_hash: Optional[str]
    tg_message_id: Optional[int]
    updated_at: float


class StateStore:
    def __init__(self, db_path: Path):
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS files (
                root_alias TEXT NOT NULL,
                rel_path TEXT NOT NULL,
                local_size INTEGER,
                local_mtime REAL,
                local_hash TEXT,
                tg_message_id INTEGER,
                updated_at REAL,
                PRIMARY KEY (root_alias, rel_path)
            )
            """
        )
        self._conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        self._conn.commit()

    def get(self, root_alias: str, rel_path: str) -> Optional[FileRecord]:
        cur = self._conn.execute(
            "SELECT root_alias, rel_path, local_size, local_mtime, local_hash, tg_message_id, updated_at "
            "FROM files WHERE root_alias = ? AND rel_path = ?",
            (root_alias, rel_path),
        )
        row = cur.fetchone()
        return FileRecord(*row) if row else None

    def get_by_message_id(self, message_id: int) -> Optional[FileRecord]:
        cur = self._conn.execute(
            "SELECT root_alias, rel_path, local_size, local_mtime, local_hash, tg_message_id, updated_at "
            "FROM files WHERE tg_message_id = ?",
            (message_id,),
        )
        row = cur.fetchone()
        return FileRecord(*row) if row else None

    def upsert(
        self,
        root_alias: str,
        rel_path: str,
        local_size: Optional[int],
        local_mtime: Optional[float],
        local_hash: Optional[str],
        tg_message_id: Optional[int],
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO files (root_alias, rel_path, local_size, local_mtime, local_hash, tg_message_id, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(root_alias, rel_path) DO UPDATE SET
                local_size=excluded.local_size,
                local_mtime=excluded.local_mtime,
                local_hash=excluded.local_hash,
                tg_message_id=excluded.tg_message_id,
                updated_at=excluded.updated_at
            """,
            (root_alias, rel_path, local_size, local_mtime, local_hash, tg_message_id, time.time()),
        )
        self._conn.commit()

    def delete(self, root_alias: str, rel_path: str) -> None:
        self._conn.execute("DELETE FROM files WHERE root_alias = ? AND rel_path = ?", (root_alias, rel_path))
        self._conn.commit()

    def all_for_root(self, root_alias: str):
        cur = self._conn.execute(
            "SELECT root_alias, rel_path, local_size, local_mtime, local_hash, tg_message_id, updated_at "
            "FROM files WHERE root_alias = ?",
            (root_alias,),
        )
        return [FileRecord(*row) for row in cur.fetchall()]

    def get_meta(self, key: str) -> Optional[str]:
        cur = self._conn.execute("SELECT value FROM meta WHERE key = ?", (key,))
        row = cur.fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
