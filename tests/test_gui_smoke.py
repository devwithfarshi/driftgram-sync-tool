"""Exercise the GUI's wiring, not just its imports.

Rendering a page proves the layout builds. It does not prove that clicking
Save reads the right widgets, that adding a folder validates, or that the
restore table's selection logic works - those are ordinary Python methods
full of attribute lookups, and they fail at the moment a user clicks, which
is the worst possible time to find out.

Runs against the offscreen platform plugin, so no display is needed. Skipped
entirely when PySide6 isn't installed, because the CLI is supported without it.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6", reason="GUI extras not installed")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src.config import ConflictPolicy, RootConfig, blank_config  # noqa: E402
from src.events import EventBus, EventKind, RunState, SyncEvent  # noqa: E402
from src.paths import AppPaths  # noqa: E402
from src.sync_engine import RemoteFile  # noqa: E402
from tools.screenshot import StubSupervisor  # noqa: E402


@pytest.fixture(scope="session")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def context(tmp_path, qt_app):
    from src.gui.bridge import EngineSignals
    from src.gui.context import AppContext

    resolved = AppPaths(config_file=tmp_path / "config.yaml", data_dir=tmp_path, portable=True)
    config = blank_config(resolved)
    config.api_id, config.api_hash = 2040123, "c" * 32
    config.app.setup_complete = True
    docs = tmp_path / "docs"
    docs.mkdir()
    config.roots = [RootConfig(path=docs, alias="docs", ignore=["*.log"])]

    bus = EventBus()
    saved: list = []
    restarted: list = []
    notices: list = []
    ctx = AppContext(
        config=config,
        supervisor=StubSupervisor(config),
        signals=EngineSignals(bus),
        save=lambda: saved.append(True),
        apply_and_restart=lambda: restarted.append(True),
        notify=notices.append,
    )
    ctx._bus, ctx._saved, ctx._restarted, ctx._notices = bus, saved, restarted, notices
    return ctx


# --------------------------------------------------------------------------


def test_status_page_reacts_to_the_whole_event_stream(context):
    from src.gui.page_status import StatusPage

    page = StatusPage(context)
    for event in [
        SyncEvent(EventKind.STATUS, state=RunState.SCANNING),
        SyncEvent(EventKind.SCAN_PROGRESS, message="Checked 10 files, backed up 2"),
        SyncEvent(EventKind.UPLOAD_STARTED, alias="docs", rel_path="a.txt", bytes_total=1000),
        SyncEvent(EventKind.UPLOAD_PROGRESS, alias="docs", rel_path="a.txt",
                  bytes_done=500, bytes_total=1000),
        SyncEvent(EventKind.UPLOAD_FINISHED, alias="docs", rel_path="a.txt", bytes_total=1000),
        SyncEvent(EventKind.CONFLICT, alias="docs", rel_path="b.txt", message="kept both"),
        SyncEvent(EventKind.ERROR, message="something broke"),
        SyncEvent(EventKind.STATUS, state=RunState.IDLE),
    ]:
        page.on_event(event)

    assert page.headline.text() == "Everything is backed up"
    assert page.recent.count() == 3  # upload, conflict, error - not the progress ticks
    assert page.files_tile.value_label.text() == "1,284"


def test_status_progress_bar_appears_and_clears(context):
    from src.gui.page_status import StatusPage

    page = StatusPage(context)
    page.on_event(SyncEvent(EventKind.UPLOAD_PROGRESS, alias="docs", rel_path="big.iso",
                            bytes_done=25, bytes_total=100))
    assert page.progress.isVisible() or page.progress.value() == 25

    page.on_event(SyncEvent(EventKind.STATUS, state=RunState.IDLE))
    assert page.progress.isHidden()


def test_pause_button_round_trips(context):
    from src.gui.page_status import StatusPage

    page = StatusPage(context)
    page._toggle_pause()
    assert context.supervisor.is_paused

    page.on_event(SyncEvent(EventKind.STATUS, state=RunState.PAUSED))
    assert page.pause_button.text() == "Resume"


def test_folders_page_lists_roots_and_flags_missing_ones(context, tmp_path):
    from src.gui.page_folders import FoldersPage

    context.config.roots.append(RootConfig(path=tmp_path / "gone", alias="gone"))
    page = FoldersPage(context)

    assert page.table.rowCount() == 2
    assert "not found" in page.table.item(1, 0).text()
    assert page.table.item(0, 2).text() == "1 rule"


def test_ignore_dialog_parses_lines_and_drops_blanks(context):
    from src.gui.page_folders import IgnoreDialog

    dialog = IgnoreDialog(context.config.roots[0])
    dialog.editor.setPlainText("node_modules/\n\n  *.log  \n\ndrafts/\n")

    assert dialog.patterns() == ["node_modules/", "*.log", "drafts/"]


def test_removing_a_folder_saves_and_restarts(context, monkeypatch):
    from src.gui import page_folders
    from src.gui.page_folders import FoldersPage

    page = FoldersPage(context)
    page.table.selectRow(0)
    monkeypatch.setattr(page_folders, "confirm", lambda *a, **k: True)

    page._remove()

    assert context.config.roots == []
    assert context._restarted, "removing a folder must rebuild the engine"


def test_settings_save_writes_every_field_back(context):
    from src.gui.page_settings import SettingsPage

    page = SettingsPage(context)
    page.target_entry.setText("@my_backup_channel")
    page.delete_local.setChecked(True)
    page.max_size.setValue(500)
    page.poll_interval.setValue(90)
    page.notifications.setChecked(False)
    page.global_ignore.setPlainText("*.iso\n\n*.mkv\n")
    for button in page.conflict_group.buttons():
        if button.property("policy") == ConflictPolicy.LOCAL_WINS.value:
            button.setChecked(True)

    page._save()

    config = context.config
    assert config.target == "@my_backup_channel"
    assert config.sync.delete_local_on_remote_delete is True
    assert config.sync.max_file_size_mb == 500
    assert config.sync.poll_interval_seconds == 90
    assert config.app.notifications is False
    assert config.global_ignore == ["*.iso", "*.mkv"]
    assert config.sync.conflict_policy is ConflictPolicy.LOCAL_WINS
    # Target and ignore rules are baked into the engine, so this must restart it
    # rather than only writing the file.
    assert context._restarted


def test_settings_preference_only_change_saves_without_restarting(context):
    from src.gui.page_settings import SettingsPage

    page = SettingsPage(context)
    page.minimize_to_tray.setChecked(False)

    page._save()

    assert context.config.app.minimize_to_tray is False
    assert context._saved and not context._restarted


def test_restore_page_filters_and_counts_selection(context, tmp_path):
    from src.gui.page_restore import RestorePage

    page = RestorePage(context)
    files = [
        RemoteFile("docs", "keep.txt", 1, 100, tmp_path / "keep.txt", False, False),
        RemoteFile("docs", "here.txt", 2, 200, tmp_path / "here.txt", True, False),
        RemoteFile("docs", "notes/deep.md", 3, 300, tmp_path / "notes/deep.md", False, False),
    ]
    page._loaded(files)

    # Missing files are pre-ticked, so "look then restore" is two clicks.
    assert len(page._checked_files()) == 2
    assert "Restore 2 files" in page.restore_button.text()

    page.only_missing.setChecked(False)
    page.filter_entry.setText("deep")
    visible = [i for i in range(page.table.rowCount()) if not page.table.isRowHidden(i)]
    assert visible == [2]

    # A hidden row must never be restored, even if it is still ticked: the
    # filter is the user's statement of what they are looking at.
    assert [f.rel_path for f in page._checked_files()] == ["notes/deep.md"]

    page._set_all(False)
    assert page._checked_files() == []

    page.filter_entry.setText("")
    assert [f.rel_path for f in page._checked_files()] == ["keep.txt"], (
        "clearing the filter should reveal the row that was never unticked"
    )


def test_activity_page_colours_and_filters(context):
    from src.gui.page_activity import ActivityPage

    page = ActivityPage(context)
    page.on_event(SyncEvent(EventKind.UPLOAD_FINISHED, alias="docs", rel_path="a.txt"))
    page.on_event(SyncEvent(EventKind.ERROR, message="disk unplugged"))
    page.on_event(SyncEvent(EventKind.UPLOAD_PROGRESS, alias="docs", rel_path="a.txt"))

    assert page.list.count() == 2, "progress ticks must not reach the activity log"

    page.only_attention.setChecked(True)
    hidden = [page.list.item(i).isHidden() for i in range(page.list.count())]
    assert hidden.count(True) == 1


def test_main_window_builds_and_switches_pages(context):
    from src.gui.main_window import MainWindow

    window = MainWindow(context, on_quit=lambda: None, can_hide_to_tray=True)
    for key in ("status", "folders", "activity", "restore", "settings"):
        window.show_page(key)
    assert window.stack.currentIndex() == 4

    window.notify("hello")
    assert window.toast.text() == "hello"


def test_closing_hides_to_tray_when_one_is_available(context):
    from PySide6.QtGui import QCloseEvent

    from src.gui.main_window import MainWindow

    quits: list = []
    window = MainWindow(context, on_quit=lambda: quits.append(True), can_hide_to_tray=True)
    window.show()

    event = QCloseEvent()
    window.closeEvent(event)
    assert not quits and not event.isAccepted()

    # ...but the tray's Quit really does quit.
    window.request_quit()
    assert quits


def test_closing_quits_when_there_is_no_tray(context):
    """Hiding into a tray that doesn't exist would strand the app out of reach."""
    from PySide6.QtGui import QCloseEvent

    from src.gui.main_window import MainWindow

    quits: list = []
    window = MainWindow(context, on_quit=lambda: quits.append(True), can_hide_to_tray=False)
    window.closeEvent(QCloseEvent())
    assert quits


def test_wizard_validates_credentials_before_calling_telegram(context):
    from src.gui.onboarding import CREDENTIALS, SetupWizard

    wizard = SetupWizard(context.config, context.supervisor)
    wizard._show_page(CREDENTIALS)

    wizard.api_id_entry.setText("not-a-number")
    wizard.api_hash_entry.setText("c" * 32)
    wizard._submit_credentials()
    assert wizard.credentials_error.isVisible() or wizard.credentials_error.text()

    wizard.api_id_entry.setText("2040123")
    wizard.api_hash_entry.setText("too-short")
    wizard._clear_errors()
    wizard._submit_credentials()
    assert "32" in wizard.credentials_error.text()


def test_wizard_rejects_a_malformed_phone_number(context):
    from src.gui.onboarding import PHONE, SetupWizard

    wizard = SetupWizard(context.config, context.supervisor)
    wizard._show_page(PHONE)
    wizard.phone_entry.setText("hello")

    wizard._submit_phone()

    assert "phone number" in wizard.phone_error.text()


def test_wizard_blocks_continue_until_a_folder_is_chosen(context):
    from src.gui.onboarding import FOLDERS, SetupWizard

    wizard = SetupWizard(context.config, context.supervisor)
    wizard.roots = []
    wizard._show_page(FOLDERS)
    assert not wizard.next_button.isEnabled()

    wizard.roots = list(context.config.roots)
    wizard._refresh_folder_list()
    wizard._sync_next_state()
    assert wizard.next_button.isEnabled()


def test_wizard_finish_produces_a_complete_config(context, qtbot=None):
    from src.gui.onboarding import DONE, OPTIONS, SetupWizard

    wizard = SetupWizard(context.config, context.supervisor)
    wizard.roots = list(context.config.roots)
    wizard._show_page(OPTIONS)
    wizard.autostart_box.setChecked(False)
    wizard.delete_local_box.setChecked(True)
    wizard._show_page(DONE)

    produced: list = []
    wizard.completed.connect(produced.append)
    wizard._finish()

    assert produced, "finishing setup must emit the config"
    config = produced[0]
    assert config.app.setup_complete
    assert config.sync.delete_local_on_remote_delete is True
    assert config.sync.conflict_policy is ConflictPolicy.KEEP_BOTH
    assert config.roots
