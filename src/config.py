"""Configuration loading and saving for Driftgram.

Two things changed here when the desktop app arrived.

First, nothing calls sys.exit() any more. A CLI can die on a bad config; a
window has to show a dialog and stay alive, so every failure raises a
ConfigError carrying a message written for a non-technical reader. The CLI
entry points catch it and print exactly what they used to.

Second, config is now writable. Credentials may come from the environment
(the original .env flow, still supported and still winning ties) or from
config.yaml itself, which is what the setup wizard writes. Relative paths
resolve against the data directory chosen by src.paths, so an installed app
keeps its manifest in AppData while a git checkout keeps it in the checkout.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from dotenv import load_dotenv

from .errors import ConfigError, NotConfiguredError
from .paths import AppPaths, discover

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

#: Always applied, regardless of use_default_ignores. These are Driftgram's own
#: scratch files: download_message writes "<name>.driftgram-tmp" beside the
#: destination and renames it on completion, so for the duration of a large
#: download that temp file sits inside a watched folder. Without this it would
#: look like an ordinary new file and get uploaded.
INTERNAL_IGNORES: List[str] = ["**/*.driftgram-tmp"]

#: Offered as tick-boxes in the setup wizard, so a user never has to learn
#: gitignore syntax to exclude the things people usually want excluded.
IGNORE_PRESETS: Dict[str, List[str]] = {
    "Developer junk (node_modules, build output, caches)": [
        "node_modules/",
        "dist/",
        "build/",
        ".next/",
        "target/",
        "*.pyc",
    ],
    "Large disc images (*.iso, *.vmdk)": ["*.iso", "*.vmdk", "*.vdi", "*.img"],
    "Videos (*.mp4, *.mkv, *.mov)": ["*.mp4", "*.mkv", "*.mov", "*.avi"],
    "Log and temporary files": ["*.log", "*.tmp", "*.bak", "*.swp"],
}


class ConflictPolicy(str, Enum):
    """What to do when Telegram has a newer copy of a file the user also edited locally."""

    KEEP_BOTH = "keep_both"      # download alongside as "name (from Telegram).ext" - lossless
    REMOTE_WINS = "remote_wins"  # overwrite the local file
    LOCAL_WINS = "local_wins"    # leave the local file alone, do not download

    @property
    def label(self) -> str:
        return {
            ConflictPolicy.KEEP_BOTH: "Keep both copies (recommended)",
            ConflictPolicy.REMOTE_WINS: "Let Telegram's copy replace mine",
            ConflictPolicy.LOCAL_WINS: "Always keep my copy",
        }[self]


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
    conflict_policy: ConflictPolicy = ConflictPolicy.KEEP_BOTH


@dataclass
class AppSettings:
    """Desktop-app-only preferences. Ignored entirely by the CLI."""

    start_at_login: bool = False
    minimize_to_tray: bool = True
    notifications: bool = True
    setup_complete: bool = False


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
    paths: AppPaths
    app: AppSettings = field(default_factory=AppSettings)

    @property
    def session_file(self) -> Path:
        return self.paths.resolve_data(f"{self.session_name}.session")


# --------------------------------------------------------------------------
# alias + validation helpers (shared by the loader and the setup wizard)
# --------------------------------------------------------------------------


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


def suggest_alias(path: Path, taken: Optional[List[str]] = None) -> str:
    """A short, stable, unique tag for a folder - what the GUI proposes on 'Add folder'.

    Prefers the folder's own name ("Documents" -> "documents") because that is
    what a user recognises in the Telegram caption, falling back to the full
    slugified path only when the name alone would collide.
    """
    taken = list(taken or [])
    base = _slugify(Path(path.name or str(path)))
    candidate = base
    if candidate in taken:
        candidate = _slugify(path)
    suffix = 2
    while candidate in taken:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def root_conflict(new_path: Path, existing: List[RootConfig]) -> Optional[str]:
    """Reject nested or duplicate folders, which the sync engine cannot represent.

    _resolve_root_for_path returns the *first* root a path falls under, so a
    folder inside another folder would be attributed unpredictably. Better to
    refuse it where the user picks it, in words they can act on.
    """
    try:
        new_resolved = new_path.resolve()
    except OSError:
        return f"{new_path} could not be read."

    for root in existing:
        try:
            other = root.path.resolve()
        except OSError:
            continue
        if new_resolved == other:
            return f"{new_path} is already being synced."
        if _is_within(new_resolved, other):
            return (
                f"{new_path} is inside {root.path}, which is already synced. "
                "Remove the outer folder first, or pick a different one."
            )
        if _is_within(other, new_resolved):
            return (
                f"{new_path} contains {root.path}, which is already synced. "
                "Remove the inner folder first, or pick a different one."
            )
    return None


# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------


def _coerce_api_id(raw: Any) -> int:
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        raise ConfigError(
            "Your Telegram API ID doesn't look right.",
            "It should be a number only, like 1234567 - copy it exactly from "
            "my.telegram.org/apps.",
        ) from None


def load_config(
    config_path: Optional[str] = None,
    env_path: Optional[str] = None,
    *,
    force_managed: bool = False,
) -> AppConfig:
    """Read config from disk. Raises ConfigError / NotConfiguredError - never exits."""
    load_dotenv(env_path) if env_path else load_dotenv()

    app_paths = discover(config_path, force_managed=force_managed)
    if not app_paths.config_file.exists():
        raise NotConfiguredError(
            "Driftgram hasn't been set up yet.",
            f"Expected a settings file at {app_paths.config_file}. Run the app to "
            "set it up, or copy config.example.yaml to config.yaml and edit it.",
        )

    try:
        with app_paths.config_file.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(
            f"Your settings file couldn't be read: {app_paths.config_file}",
            f"It isn't valid YAML. {exc}",
        ) from exc
    except OSError as exc:
        raise ConfigError(f"Couldn't open {app_paths.config_file}", str(exc)) from exc

    if not isinstance(raw, dict):
        raise ConfigError(
            f"Your settings file couldn't be read: {app_paths.config_file}",
            "The file should be a set of settings, but it contains something else.",
        )

    return _from_mapping(raw, app_paths)


def _from_mapping(raw: Dict[str, Any], app_paths: AppPaths) -> AppConfig:
    telegram_raw = raw.get("telegram") or {}
    sync_raw = raw.get("sync") or {}
    app_raw = raw.get("app") or {}
    roots_raw = raw.get("roots") or []
    global_ignore = raw.get("global_ignore") or []

    # Environment wins over the config file, so an existing .env keeps working
    # and a developer can override an installed config without editing it.
    api_id_raw = os.environ.get("TG_API_ID") or telegram_raw.get("api_id")
    api_hash = os.environ.get("TG_API_HASH") or telegram_raw.get("api_hash")
    session_name = (
        os.environ.get("TG_SESSION_NAME") or telegram_raw.get("session_name") or "driftgram"
    )

    if not api_id_raw or not api_hash:
        raise NotConfiguredError(
            "Driftgram needs your Telegram API ID and API Hash before it can connect.",
            "Get them free at https://my.telegram.org/apps - the app walks you "
            "through it on first run.",
        )

    seen_aliases: List[str] = []
    roots: List[RootConfig] = []
    for entry in roots_raw:
        if not isinstance(entry, dict) or not entry.get("path"):
            raise ConfigError(
                "One of your synced folders is missing its location.",
                "Every entry under 'roots:' needs a 'path:'.",
            )
        path = Path(str(entry["path"])).expanduser()
        alias = str(entry.get("alias") or suggest_alias(path, seen_aliases))
        if alias in seen_aliases:
            raise ConfigError(
                f"Two synced folders share the name '{alias}'.",
                "Each folder needs its own unique short name, because that name "
                "is what tags its files in Telegram.",
            )
        seen_aliases.append(alias)
        roots.append(RootConfig(path=path, alias=alias, ignore=list(entry.get("ignore") or [])))

    policy_raw = str(sync_raw.get("conflict_policy", ConflictPolicy.KEEP_BOTH.value)).lower()
    try:
        conflict_policy = ConflictPolicy(policy_raw)
    except ValueError:
        raise ConfigError(
            f"'{policy_raw}' isn't a valid conflict setting.",
            "Choose one of: " + ", ".join(p.value for p in ConflictPolicy),
        ) from None

    try:
        sync_settings = SyncSettings(
            poll_interval_seconds=max(5, int(sync_raw.get("poll_interval_seconds", 20))),
            delete_remote_on_local_delete=bool(sync_raw.get("delete_remote_on_local_delete", False)),
            delete_local_on_remote_delete=bool(sync_raw.get("delete_local_on_remote_delete", False)),
            max_file_size_mb=int(sync_raw.get("max_file_size_mb", 1900)),
            use_default_ignores=bool(sync_raw.get("use_default_ignores", True)),
            debounce_seconds=max(0.2, float(sync_raw.get("debounce_seconds", 2.0))),
            conflict_policy=conflict_policy,
        )
    except (TypeError, ValueError) as exc:
        raise ConfigError("One of your sync settings has an invalid value.", str(exc)) from exc

    app_settings = AppSettings(
        start_at_login=bool(app_raw.get("start_at_login", False)),
        minimize_to_tray=bool(app_raw.get("minimize_to_tray", True)),
        notifications=bool(app_raw.get("notifications", True)),
        setup_complete=bool(app_raw.get("setup_complete", False)),
    )

    return AppConfig(
        api_id=_coerce_api_id(api_id_raw),
        api_hash=str(api_hash).strip(),
        session_name=str(session_name),
        target=str(telegram_raw.get("target") or "me"),
        roots=roots,
        global_ignore=[str(p) for p in global_ignore],
        sync=sync_settings,
        state_db_path=app_paths.resolve_data(raw.get("state_db_path") or "manifest.db"),
        paths=app_paths,
        app=app_settings,
    )


def blank_config(app_paths: AppPaths) -> AppConfig:
    """An unconfigured AppConfig for the setup wizard to fill in."""
    return AppConfig(
        api_id=0,
        api_hash="",
        session_name="driftgram",
        target="me",
        roots=[],
        global_ignore=[],
        sync=SyncSettings(),
        state_db_path=app_paths.resolve_data("manifest.db"),
        paths=app_paths,
        app=AppSettings(),
    )


def load_or_blank(config_path: Optional[str] = None, *, force_managed: bool = False) -> AppConfig:
    """Load config, falling back to a blank one when setup hasn't happened yet.

    The GUI always has *some* config object to bind widgets to, even on a first
    run where no file exists and no credentials are known.
    """
    try:
        return load_config(config_path, force_managed=force_managed)
    except NotConfiguredError:
        return blank_config(discover(config_path, force_managed=force_managed))


def is_configured(config: AppConfig) -> bool:
    return bool(config.api_id and config.api_hash and config.roots and config.app.setup_complete)


# --------------------------------------------------------------------------
# saving
# --------------------------------------------------------------------------

_HEADER = """# Driftgram settings.
#
# This file is managed by the Driftgram app - it is rewritten whenever you
# change something in Settings, so hand-written comments here will be lost.
# Editing it by hand is fine while the app is closed.
#
# NOTE: api_hash below is a credential. Treat this file like a password.
"""


def to_mapping(config: AppConfig) -> Dict[str, Any]:
    """The YAML-shaped view of a config, without any Path or Enum objects."""
    return {
        "telegram": {
            "target": config.target,
            "api_id": config.api_id,
            "api_hash": config.api_hash,
            "session_name": config.session_name,
        },
        "sync": {
            "poll_interval_seconds": config.sync.poll_interval_seconds,
            "delete_remote_on_local_delete": config.sync.delete_remote_on_local_delete,
            "delete_local_on_remote_delete": config.sync.delete_local_on_remote_delete,
            "max_file_size_mb": config.sync.max_file_size_mb,
            "use_default_ignores": config.sync.use_default_ignores,
            "debounce_seconds": config.sync.debounce_seconds,
            "conflict_policy": config.sync.conflict_policy.value,
        },
        "app": {
            "start_at_login": config.app.start_at_login,
            "minimize_to_tray": config.app.minimize_to_tray,
            "notifications": config.app.notifications,
            "setup_complete": config.app.setup_complete,
        },
        "roots": [
            {
                "path": str(root.path).replace("\\", "/"),
                "alias": root.alias,
                "ignore": list(root.ignore),
            }
            for root in config.roots
        ],
        "global_ignore": list(config.global_ignore),
        "state_db_path": str(config.state_db_path).replace("\\", "/"),
    }


def save_config(config: AppConfig) -> None:
    """Write config atomically, then restrict it to the owner where possible.

    Atomic because a half-written settings file would leave the app unable to
    start; owner-only because api_hash is in there.
    """
    config.paths.ensure_dirs()
    target = config.paths.config_file
    tmp = target.with_name(target.name + ".tmp")
    body = yaml.safe_dump(
        to_mapping(config), sort_keys=False, allow_unicode=True, default_flow_style=False
    )
    try:
        tmp.write_text(_HEADER + "\n" + body, encoding="utf-8")
        os.replace(tmp, target)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise ConfigError(f"Couldn't save your settings to {target}", str(exc)) from exc
    if os.name != "nt":
        try:
            target.chmod(0o600)
        except OSError:
            pass


def with_roots(config: AppConfig, roots: List[RootConfig]) -> AppConfig:
    return replace(config, roots=list(roots))
