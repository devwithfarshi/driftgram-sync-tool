"""Configuration loading for the D-drive <-> Telegram sync tool."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import yaml
from dotenv import load_dotenv

DEFAULT_IGNORES = [
    "**/.git/**",
    "**/node_modules/**",
    "**/__pycache__/**",
    "**/.next/**",
    "**/.venv/**",
    "**/venv/**",
    "**/dist/**",
    "**/build/**",
    "**/Thumbs.db",
    "**/desktop.ini",
    "**/*.tmp",
    "**/~$*",
    "**/System Volume Information/**",
    "**/$RECYCLE.BIN/**",
]


@dataclass
class RootConfig:
    path: Path
    alias: str
    ignore: List[str] = field(default_factory=list)


@dataclass
class SyncSettings:
    poll_interval_seconds: int = 20
    delete_remote_on_local_delete: bool = False
    delete_local_on_remote_delete: bool = False
    max_file_size_mb: int = 1900
    use_default_ignores: bool = True
    debounce_seconds: float = 2.0


@dataclass
class AppConfig:
    api_id: int
    api_hash: str
    session_name: str
    target: str
    roots: List[RootConfig]
    global_ignore: List[str]
    sync: SyncSettings
    state_db_path: Path


def _slugify(path: Path) -> str:
    text = str(path).lower()
    keep = []
    for ch in text:
        if ch.isalnum():
            keep.append(ch)
        elif ch in "/\\: ":
            keep.append("-")
    slug = "".join(keep)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "root"


def load_config(config_path: str = "config.yaml", env_path: Optional[str] = None) -> AppConfig:
    if env_path:
        load_dotenv(env_path)
    else:
        load_dotenv()

    api_id_raw = os.environ.get("TG_API_ID")
    api_hash = os.environ.get("TG_API_HASH")
    session_name = os.environ.get("TG_SESSION_NAME", "d_drive_sync")

    if not api_id_raw or not api_hash:
        print(
            "Missing TG_API_ID / TG_API_HASH. Copy .env.example to .env and fill in "
            "credentials from https://my.telegram.org/apps",
            file=sys.stderr,
        )
        sys.exit(1)

    cfg_file = Path(config_path)
    if not cfg_file.exists():
        print(
            f"Config file not found: {cfg_file}. Copy config.example.yaml to {config_path} and edit it.",
            file=sys.stderr,
        )
        sys.exit(1)

    with cfg_file.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    telegram_raw = raw.get("telegram", {}) or {}
    sync_raw = raw.get("sync", {}) or {}
    roots_raw = raw.get("roots", []) or []
    global_ignore = raw.get("global_ignore", []) or []

    if not roots_raw:
        print("No sync roots configured. Add at least one entry under 'roots:' in your config.", file=sys.stderr)
        sys.exit(1)

    seen_aliases = set()
    roots: List[RootConfig] = []
    for entry in roots_raw:
        path = Path(entry["path"]).expanduser()
        alias = entry.get("alias") or _slugify(path)
        if alias in seen_aliases:
            print(
                f"Duplicate root alias '{alias}'. Give each root a unique 'alias' in your config.",
                file=sys.stderr,
            )
            sys.exit(1)
        seen_aliases.add(alias)
        roots.append(RootConfig(path=path, alias=alias, ignore=entry.get("ignore", []) or []))

    sync_settings = SyncSettings(
        poll_interval_seconds=int(sync_raw.get("poll_interval_seconds", 20)),
        delete_remote_on_local_delete=bool(sync_raw.get("delete_remote_on_local_delete", False)),
        delete_local_on_remote_delete=bool(sync_raw.get("delete_local_on_remote_delete", False)),
        max_file_size_mb=int(sync_raw.get("max_file_size_mb", 1900)),
        use_default_ignores=bool(sync_raw.get("use_default_ignores", True)),
        debounce_seconds=float(sync_raw.get("debounce_seconds", 2.0)),
    )

    return AppConfig(
        api_id=int(api_id_raw),
        api_hash=api_hash,
        session_name=session_name,
        target=telegram_raw.get("target", "me"),
        roots=roots,
        global_ignore=global_ignore,
        sync=sync_settings,
        state_db_path=Path(raw.get("state_db_path", "manifest.db")),
    )
