"""Tests for the pieces the desktop app added around the sync engine.

None of this needs Qt or Telegram: paths, config round-tripping, filename
portability and the cross-process lock are all plain Python, and they are
exactly the things that break quietly on the platform you didn't develop on.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from src import paths
from src.app.instance_lock import InstanceLock
from src.config import (
    AppConfig,
    ConflictPolicy,
    RootConfig,
    blank_config,
    is_configured,
    load_config,
    root_conflict,
    save_config,
    suggest_alias,
)
from src.errors import AlreadyRunningError, ConfigError, NotConfiguredError
from src.fsutil import conflict_path, human_bytes, unwritable_reason
from src.paths import AppPaths

ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------
# paths
# --------------------------------------------------------------------------


def test_portable_mode_when_a_local_config_exists(tmp_path, monkeypatch):
    """A git checkout with a config.yaml keeps everything beside it, as the CLI always did."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text("roots: []", encoding="utf-8")

    resolved = paths.discover()

    assert resolved.portable
    assert resolved.config_file == (tmp_path / "config.yaml").resolve()
    assert resolved.data_dir == tmp_path.resolve()


def test_managed_mode_when_no_local_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    resolved = paths.discover()

    assert not resolved.portable
    assert resolved.config_file.name == "config.yaml"
    assert resolved.data_dir == paths.user_data_dir()


def test_force_managed_ignores_a_stray_local_config(tmp_path, monkeypatch):
    """An installed app must not adopt a config.yaml from whatever directory it launched in."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text("roots: []", encoding="utf-8")

    assert not paths.discover(force_managed=True).portable


def test_relative_state_path_resolves_against_the_data_dir(tmp_path):
    resolved = AppPaths(config_file=tmp_path / "config.yaml", data_dir=tmp_path, portable=True)

    assert resolved.resolve_data("manifest.db") == tmp_path / "manifest.db"
    absolute = Path(tmp_path / "elsewhere" / "m.db")
    assert resolved.resolve_data(absolute) == absolute


# --------------------------------------------------------------------------
# config
# --------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolate_dotenv(monkeypatch):
    """Stop load_config() reading the developer's own .env during these tests.

    python-dotenv resolves a bare load_dotenv() by walking up from the calling
    module - src/config.py - so it finds the checkout's .env no matter what the
    working directory is, and those real credentials then win over the ones a
    test just wrote. Correct in production, ruinous for a round-trip test.
    """
    monkeypatch.setattr("src.config.load_dotenv", lambda *args, **kwargs: False)


def make_config(tmp_path) -> AppConfig:
    resolved = AppPaths(config_file=tmp_path / "config.yaml", data_dir=tmp_path, portable=True)
    config = blank_config(resolved)
    config.api_id = 2040123
    config.api_hash = "b" * 32
    config.roots = [RootConfig(path=tmp_path / "docs", alias="docs", ignore=["*.log"])]
    config.global_ignore = ["*.iso"]
    config.sync.conflict_policy = ConflictPolicy.REMOTE_WINS
    config.app.setup_complete = True
    return config


def test_config_survives_a_save_load_round_trip(tmp_path, monkeypatch):
    monkeypatch.delenv("TG_API_ID", raising=False)
    monkeypatch.delenv("TG_API_HASH", raising=False)
    original = make_config(tmp_path)

    save_config(original)
    reloaded = load_config(str(tmp_path / "config.yaml"))

    assert reloaded.api_id == original.api_id
    assert reloaded.api_hash == original.api_hash
    assert reloaded.sync.conflict_policy is ConflictPolicy.REMOTE_WINS
    assert [r.alias for r in reloaded.roots] == ["docs"]
    assert reloaded.roots[0].ignore == ["*.log"]
    assert reloaded.global_ignore == ["*.iso"]
    assert reloaded.app.setup_complete
    assert is_configured(reloaded)


def test_environment_credentials_win_over_the_config_file(tmp_path, monkeypatch):
    """The original .env flow has to keep working for anyone already using it."""
    save_config(make_config(tmp_path))
    monkeypatch.setenv("TG_API_ID", "999")
    monkeypatch.setenv("TG_API_HASH", "from-env")

    reloaded = load_config(str(tmp_path / "config.yaml"))

    assert reloaded.api_id == 999
    assert reloaded.api_hash == "from-env"


def test_missing_config_raises_rather_than_exiting(tmp_path):
    """A GUI cannot survive sys.exit(); every failure has to be catchable."""
    with pytest.raises(NotConfiguredError) as caught:
        load_config(str(tmp_path / "nope.yaml"))
    assert "hasn't been set up" in caught.value.message


def test_broken_yaml_raises_a_readable_error(tmp_path):
    (tmp_path / "config.yaml").write_text("roots: [\n  bad", encoding="utf-8")
    with pytest.raises(ConfigError) as caught:
        load_config(str(tmp_path / "config.yaml"))
    assert "couldn't be read" in caught.value.message


def test_duplicate_aliases_are_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("TG_API_ID", "1")
    monkeypatch.setenv("TG_API_HASH", "x")
    (tmp_path / "config.yaml").write_text(
        textwrap.dedent(
            """
            roots:
              - path: "/a"
                alias: "same"
              - path: "/b"
                alias: "same"
            """
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError) as caught:
        load_config(str(tmp_path / "config.yaml"))
    assert "same" in caught.value.message


def test_saved_config_is_owner_only_on_posix(tmp_path):
    """The file holds api_hash, so it must not be world-readable."""
    if os.name == "nt":
        pytest.skip("POSIX permissions only")
    save_config(make_config(tmp_path))
    assert (tmp_path / "config.yaml").stat().st_mode & 0o077 == 0


def test_alias_suggestions_are_readable_and_unique():
    assert suggest_alias(Path("/home/me/Documents")) == "documents"
    first = suggest_alias(Path("/home/me/Documents"))
    second = suggest_alias(Path("/mnt/backup/Documents"), [first])
    assert second != first and second


@pytest.mark.parametrize(
    "candidate, expect_problem",
    [
        ("/data/projects", True),      # identical
        ("/data/projects/web", True),  # inside an existing root
        ("/data", True),               # contains an existing root
        ("/data/photos", False),
    ],
)
def test_nested_roots_are_refused(candidate, expect_problem):
    existing = [RootConfig(path=Path("/data/projects"), alias="projects")]
    assert bool(root_conflict(Path(candidate), existing)) is expect_problem


# --------------------------------------------------------------------------
# filename portability
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rel_path",
    ["notes:2024.txt", "a/aux.log", "why?.txt", 'quote".txt', "trailing /x.txt", "dir/name."],
)
def test_windows_rejects_names_it_cannot_create(rel_path):
    reason = unwritable_reason(rel_path, platform="win32")
    assert reason, f"{rel_path} should have been rejected"


@pytest.mark.parametrize("rel_path", ["notes.txt", "a/b/c.tar.gz", "Ünïcodé ok.txt", "auxiliary.log"])
def test_ordinary_names_are_allowed_everywhere(rel_path):
    assert unwritable_reason(rel_path, platform="win32") is None
    assert unwritable_reason(rel_path, platform="linux") is None


def test_linux_allows_what_windows_forbids():
    """The check is about the machine writing the file, not the one that sent it."""
    assert unwritable_reason("notes:2024.txt", platform="linux") is None


def test_conflict_copies_do_not_overwrite_each_other(tmp_path):
    original = tmp_path / "report.docx"
    original.write_text("mine", encoding="utf-8")

    first = conflict_path(original)
    assert first.name == "report (from Telegram).docx"
    first.write_text("theirs", encoding="utf-8")

    second = conflict_path(original)
    assert second.name == "report (from Telegram 2).docx"


@pytest.mark.parametrize(
    "size, expected",
    [(0, "0 B"), (999, "999 B"), (1024, "1 KB"), (1536, "1.5 KB"), (5 * 1024**2, "5 MB"), (None, "-")],
)
def test_human_bytes(size, expected):
    assert human_bytes(size) == expected


# --------------------------------------------------------------------------
# instance lock
# --------------------------------------------------------------------------


def test_lock_blocks_a_second_process(tmp_path):
    """Two Driftgrams on one manifest would corrupt it; the lock has to be real,
    not just a flag inside one process."""
    lock_file = tmp_path / "driftgram.lock"
    held = InstanceLock(lock_file).acquire()
    try:
        probe = textwrap.dedent(
            f"""
            import sys, pathlib
            sys.path.insert(0, {str(ROOT)!r})
            from src.app.instance_lock import InstanceLock
            from src.errors import AlreadyRunningError
            try:
                InstanceLock(pathlib.Path({str(lock_file)!r})).acquire()
                print("ACQUIRED")
            except AlreadyRunningError:
                print("BLOCKED")
            """
        )
        result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
        assert result.stdout.strip() == "BLOCKED", result.stderr
    finally:
        held.release()


def test_lock_is_released_for_the_next_process(tmp_path):
    lock_file = tmp_path / "driftgram.lock"
    InstanceLock(lock_file).acquire().release()

    second = InstanceLock(lock_file).acquire()
    second.release()  # no exception means it was genuinely free


def test_lock_reports_which_process_holds_it(tmp_path):
    held = InstanceLock(tmp_path / "driftgram.lock").acquire()
    try:
        assert held._read_pid() == str(os.getpid())
    finally:
        held.release()


def test_lock_works_as_a_context_manager(tmp_path):
    lock_file = tmp_path / "driftgram.lock"
    with InstanceLock(lock_file):
        with pytest.raises(AlreadyRunningError):
            # Same process, but a distinct OS-level lock request.
            other = InstanceLock(lock_file)
            other.acquire()
    InstanceLock(lock_file).acquire().release()
