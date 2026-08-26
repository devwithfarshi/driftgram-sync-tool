"""Tests for the sync engine, run against a FakeClient and a temp directory tree.

The first group locks down the invariant the whole tool rests on: nothing is
acted on unless its content differs from what the manifest recorded. The
second group covers conflict handling, which is new - a remote copy must
never silently overwrite local edits that were never uploaded.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from src.config import AppConfig, AppSettings, ConflictPolicy, RootConfig, SyncSettings
from src.events import EventBus, EventKind
from src.paths import AppPaths
from src.state import StateStore
from src.sync_engine import SyncEngine
from src.tg_client import make_caption
from tests.fake_telegram import FakeClient


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------


def build_config(tmp_path: Path, **sync_kwargs) -> AppConfig:
    root_dir = tmp_path / "synced"
    root_dir.mkdir(exist_ok=True)
    app_paths = AppPaths(config_file=tmp_path / "config.yaml", data_dir=tmp_path, portable=True)
    return AppConfig(
        api_id=1,
        api_hash="hash",
        session_name="test",
        target="me",
        roots=[RootConfig(path=root_dir, alias="docs", ignore=["secret/", "*.log"])],
        global_ignore=[],
        sync=SyncSettings(**sync_kwargs),
        state_db_path=tmp_path / "manifest.db",
        paths=app_paths,
        app=AppSettings(),
    )


@pytest.fixture
def env(tmp_path):
    config = build_config(tmp_path)
    state = StateStore(config.state_db_path)
    client = FakeClient()
    events = EventBus()
    seen = []
    events.subscribe(seen.append)
    engine = SyncEngine(client, config, state, events)
    yield engine, client, state, config, seen
    state.close()


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def bump_mtime(path: Path) -> None:
    """Force a distinct mtime; some filesystems have coarse timestamps."""
    stat = path.stat()
    import os

    os.utime(path, (stat.st_atime, stat.st_mtime + 10))


def kinds(events, kind) -> list:
    return [e for e in events if e.kind == kind]


# --------------------------------------------------------------------------
# the invariant
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_initial_scan_uploads_and_respects_ignores(env):
    engine, client, state, config, _ = env
    root = config.roots[0].path
    write(root / "a.txt", "alpha")
    write(root / "nested" / "b.txt", "beta")
    write(root / "notes.log", "ignored by *.log")
    write(root / "secret" / "keys.txt", "ignored by secret/")
    write(root / ".git" / "HEAD", "ignored by defaults")

    await engine.initial_scan()

    uploaded = {c.split("\n")[2] for c in client.uploads}
    assert uploaded == {"a.txt", "nested/b.txt"}
    assert state.get("docs", "notes.log") is None
    assert state.get("docs", "secret/keys.txt") is None


@pytest.mark.asyncio
async def test_second_scan_uploads_nothing(env):
    engine, client, state, config, _ = env
    write(config.roots[0].path / "a.txt", "alpha")

    await engine.initial_scan()
    assert len(client.uploads) == 1

    await engine.initial_scan()
    assert len(client.uploads) == 1, "unchanged file must not be re-uploaded"


@pytest.mark.asyncio
async def test_touched_but_unedited_file_is_not_re_uploaded(env):
    """mtime changed, bytes did not - the hash check must catch this."""
    engine, client, state, config, _ = env
    path = write(config.roots[0].path / "a.txt", "alpha")
    await engine.initial_scan()

    bump_mtime(path)
    await engine.initial_scan()

    assert len(client.uploads) == 1
    assert state.get("docs", "a.txt").local_mtime == path.stat().st_mtime


@pytest.mark.asyncio
async def test_edited_file_is_re_uploaded(env):
    engine, client, state, config, _ = env
    path = write(config.roots[0].path / "a.txt", "alpha")
    await engine.initial_scan()

    write(path, "alpha edited")
    await engine.handle_local_change(path, deleted=False)

    assert len(client.uploads) == 2
    assert state.get("docs", "a.txt").tg_message_id == 2


@pytest.mark.asyncio
async def test_downloaded_remote_file_is_not_re_uploaded(env):
    """The echo-loop guard: a file we just pulled down must not bounce back up."""
    engine, client, state, config, _ = env
    client.push(make_caption("docs", "from_phone.txt"), b"sent from my phone")

    await engine.poll_remote_once()
    dest = config.roots[0].path / "from_phone.txt"
    assert dest.read_bytes() == b"sent from my phone"

    # the watcher fires on the file we just wrote
    await engine.handle_local_change(dest, deleted=False)
    assert client.uploads == [], "downloaded file must not be re-uploaded"


@pytest.mark.asyncio
async def test_reprocessing_same_message_id_is_a_noop(env):
    engine, client, state, config, _ = env
    message = client.push(make_caption("docs", "x.txt"), b"payload")

    await engine.handle_remote_message(message)
    assert len(client.downloads) == 1

    await engine.handle_remote_message(message)
    assert len(client.downloads) == 1, "same message id must not download twice"


@pytest.mark.asyncio
async def test_our_own_upload_echoing_back_is_ignored(env):
    engine, client, state, config, _ = env
    write(config.roots[0].path / "a.txt", "alpha")
    await engine.initial_scan()

    # Telegram delivers our own upload back through the live listener
    await engine.handle_remote_message(client.messages[0])
    assert client.downloads == [], "our own upload must not be downloaded"


@pytest.mark.asyncio
async def test_empty_file_is_recorded_but_not_uploaded(env):
    """Telegram rejects 0-byte uploads; recording them stops an endless retry."""
    engine, client, state, config, _ = env
    write(config.roots[0].path / "empty.txt", "")

    await engine.initial_scan()

    assert client.uploads == []
    record = state.get("docs", "empty.txt")
    assert record is not None and record.tg_message_id is None and record.local_hash == "empty"


@pytest.mark.asyncio
async def test_internal_temp_file_is_never_uploaded(env):
    """A download in flight leaves a .driftgram-tmp inside a watched folder."""
    engine, client, state, config, _ = env
    stray = write(config.roots[0].path / "big.iso.driftgram-tmp", "half a download")

    await engine.initial_scan()
    await engine.handle_local_change(stray, deleted=False)

    assert client.uploads == []


@pytest.mark.asyncio
async def test_file_larger_than_limit_is_skipped_with_a_reason(env, tmp_path):
    config = build_config(tmp_path, max_file_size_mb=0)
    state = StateStore(config.state_db_path)
    events = EventBus()
    seen = []
    events.subscribe(seen.append)
    engine = SyncEngine(FakeClient(), config, state, events)
    write(config.roots[0].path / "huge.bin", "x" * 10)

    await engine.initial_scan()

    skipped = kinds(seen, EventKind.SKIPPED)
    assert skipped and "limit" in skipped[0].message
    state.close()


# --------------------------------------------------------------------------
# deletion
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_local_delete_removes_remote_when_enabled(tmp_path):
    config = build_config(tmp_path, delete_remote_on_local_delete=True)
    state = StateStore(config.state_db_path)
    client = FakeClient()
    engine = SyncEngine(client, config, state)
    path = write(config.roots[0].path / "a.txt", "alpha")
    await engine.initial_scan()

    path.unlink()
    await engine.handle_local_change(path, deleted=True)

    assert client.deleted == [1]
    assert state.get("docs", "a.txt") is None
    state.close()


@pytest.mark.asyncio
async def test_remote_delete_removes_local_and_manifest_together(tmp_path):
    """No await may separate unlink() from state.delete(), or the watcher races it."""
    config = build_config(tmp_path, delete_local_on_remote_delete=True)
    state = StateStore(config.state_db_path)
    client = FakeClient()
    engine = SyncEngine(client, config, state)
    path = write(config.roots[0].path / "a.txt", "alpha")
    await engine.initial_scan()

    await engine.handle_remote_delete([1], chat_id=None)

    assert not path.exists()
    assert state.get("docs", "a.txt") is None
    # the watcher now fires on the deletion we just performed
    await engine.handle_local_change(path, deleted=True)
    assert client.deleted == [], "must not try to delete an already-deleted message"
    state.close()


@pytest.mark.asyncio
async def test_remote_delete_ignored_when_disabled(env):
    engine, client, state, config, _ = env
    path = write(config.roots[0].path / "a.txt", "alpha")
    await engine.initial_scan()

    await engine.handle_remote_delete([1], chat_id=None)

    assert path.exists(), "delete_local_on_remote_delete defaults to off"


# --------------------------------------------------------------------------
# conflicts (new behaviour)
# --------------------------------------------------------------------------


async def setup_conflict(tmp_path, policy: ConflictPolicy):
    """A file uploaded, then edited locally, then a newer copy arrives remotely."""
    config = build_config(tmp_path, conflict_policy=policy)
    state = StateStore(config.state_db_path)
    client = FakeClient()
    events = EventBus()
    seen = []
    events.subscribe(seen.append)
    engine = SyncEngine(client, config, state, events)

    path = write(config.roots[0].path / "report.txt", "original")
    await engine.initial_scan()

    write(path, "MY LOCAL EDIT")       # local change that never reached Telegram
    bump_mtime(path)
    message = client.push(make_caption("docs", "report.txt"), b"THEIR REMOTE EDIT")
    return engine, client, state, config, seen, path, message


@pytest.mark.asyncio
async def test_conflict_keep_both_preserves_local_edit(tmp_path):
    engine, client, state, config, seen, path, message = await setup_conflict(
        tmp_path, ConflictPolicy.KEEP_BOTH
    )

    await engine.handle_remote_message(message)

    assert path.read_text() == "MY LOCAL EDIT", "local edit must survive"
    copy = config.roots[0].path / "report (from Telegram).txt"
    assert copy.read_bytes() == b"THEIR REMOTE EDIT"
    assert kinds(seen, EventKind.CONFLICT), "the user must be told a conflict happened"
    # the manifest still describes the user's own file, which is still unsynced
    assert state.get("docs", "report.txt").local_hash != None
    state.close()


@pytest.mark.asyncio
async def test_conflict_copy_gets_backed_up_as_its_own_file(tmp_path):
    """The conflict copy is a genuinely new local file and must be uploaded too."""
    engine, client, state, config, seen, path, message = await setup_conflict(
        tmp_path, ConflictPolicy.KEEP_BOTH
    )
    await engine.handle_remote_message(message)
    copy = config.roots[0].path / "report (from Telegram).txt"

    await engine.handle_local_change(copy, deleted=False)

    captions = [c.split("\n")[2] for c in client.uploads]
    assert "report (from Telegram).txt" in captions
    state.close()


@pytest.mark.asyncio
async def test_repeated_conflicts_do_not_overwrite_the_first_copy(tmp_path):
    engine, client, state, config, seen, path, message = await setup_conflict(
        tmp_path, ConflictPolicy.KEEP_BOTH
    )
    await engine.handle_remote_message(message)
    second = client.push(make_caption("docs", "report.txt"), b"A THIRD VERSION")

    await engine.handle_remote_message(second)

    root = config.roots[0].path
    assert (root / "report (from Telegram).txt").read_bytes() == b"THEIR REMOTE EDIT"
    assert (root / "report (from Telegram 2).txt").read_bytes() == b"A THIRD VERSION"
    state.close()


@pytest.mark.asyncio
async def test_conflict_remote_wins_overwrites(tmp_path):
    engine, client, state, config, seen, path, message = await setup_conflict(
        tmp_path, ConflictPolicy.REMOTE_WINS
    )

    await engine.handle_remote_message(message)

    assert path.read_bytes() == b"THEIR REMOTE EDIT"
    assert not (config.roots[0].path / "report (from Telegram).txt").exists()
    state.close()


@pytest.mark.asyncio
async def test_conflict_local_wins_skips_download(tmp_path):
    engine, client, state, config, seen, path, message = await setup_conflict(
        tmp_path, ConflictPolicy.LOCAL_WINS
    )

    await engine.handle_remote_message(message)

    assert path.read_text() == "MY LOCAL EDIT"
    assert client.downloads == []
    state.close()


@pytest.mark.asyncio
async def test_no_conflict_when_local_matches_manifest(env):
    """An unedited local file is replaced normally - this must not be a conflict."""
    engine, client, state, config, seen = env
    path = write(config.roots[0].path / "report.txt", "original")
    await engine.initial_scan()

    newer = client.push(make_caption("docs", "report.txt"), b"UPDATED ELSEWHERE")
    await engine.handle_remote_message(newer)

    assert path.read_bytes() == b"UPDATED ELSEWHERE"
    assert kinds(seen, EventKind.CONFLICT) == []


@pytest.mark.asyncio
async def test_untracked_local_file_is_treated_as_a_conflict(env):
    """A file we never uploaded is the user's - never clobber it."""
    engine, client, state, config, seen = env
    path = write(config.roots[0].path / "untracked.txt", "written offline")
    message = client.push(make_caption("docs", "untracked.txt"), b"remote version")

    await engine.handle_remote_message(message)

    assert path.read_text() == "written offline"
    assert (config.roots[0].path / "untracked (from Telegram).txt").exists()


# --------------------------------------------------------------------------
# pause
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pause_stops_uploads_and_resume_catches_up(env):
    engine, client, state, config, _ = env
    engine.set_paused(True)
    path = write(config.roots[0].path / "a.txt", "alpha")

    await engine.handle_local_change(path, deleted=False)
    assert client.uploads == []

    engine.set_paused(False)
    await engine.initial_scan()
    assert len(client.uploads) == 1, "resume must pick up what was missed"


@pytest.mark.asyncio
async def test_pause_does_not_consume_remote_messages(env):
    """A message dropped while paused must still be delivered after resume."""
    engine, client, state, config, _ = env
    engine.set_paused(True)
    message = client.push(make_caption("docs", "later.txt"), b"arrived while paused")

    await engine.handle_remote_message(message)
    assert client.downloads == []
    assert state.get_meta("last_offset_id") in (None, "0")

    engine.set_paused(False)
    await engine.poll_remote_once()
    assert (config.roots[0].path / "later.txt").read_bytes() == b"arrived while paused"


# --------------------------------------------------------------------------
# safety
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_path_escaping_the_root_is_refused(env):
    engine, client, state, config, _ = env
    message = client.push(make_caption("docs", "../../escaped.txt"), b"evil")

    await engine.handle_remote_message(message)

    assert client.downloads == []
    assert not (config.roots[0].path.parent.parent / "escaped.txt").exists()


@pytest.mark.asyncio
async def test_unknown_alias_is_ignored(env):
    engine, client, state, config, _ = env
    message = client.push(make_caption("some-other-machine", "a.txt"), b"not ours")

    await engine.handle_remote_message(message)

    assert client.downloads == []


@pytest.mark.asyncio
async def test_message_without_our_caption_is_ignored(env):
    """Ordinary chat messages in the target chat must be left alone."""
    engine, client, state, config, _ = env
    message = client.push("just a normal message with a photo", b"jpegdata")

    await engine.handle_remote_message(message)

    assert client.downloads == []
