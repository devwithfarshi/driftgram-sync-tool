"""Render every Driftgram screen to PNG, without Telegram or a real sync.

A GUI that only imports cleanly has not been checked at all - layout bugs,
clipped text and unreadable contrast only show up when something is drawn. A
stub supervisor returning already-completed futures lets every page render
with realistic content, so the screens can be reviewed like screenshots.

    python tools/screenshot.py out_dir [--dark]
"""
from __future__ import annotations

import argparse
import concurrent.futures
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication  # noqa: E402

from src.app.supervisor import Account, LoginStep  # noqa: E402
from src.config import RootConfig, blank_config  # noqa: E402
from src.events import EventBus, EventKind, RunState, SyncEvent  # noqa: E402
from src.paths import AppPaths  # noqa: E402
from src.sync_engine import RemoteFile  # noqa: E402


def done(value=None):
    future: concurrent.futures.Future = concurrent.futures.Future()
    future.set_result(value)
    return future


class StubSupervisor:
    """Every call succeeds immediately with plausible data."""

    def __init__(self, config):
        self.config = config
        self.is_paused = False
        self.is_syncing = True

    def stats(self):
        return done((1284, 7_412_338_112))

    def account(self):
        return done(Account(user_id=1, username="example_user", first_name="Alex", phone="+10000000000"))

    def connect(self):
        return done(LoginStep.AUTHORIZED)

    def list_remote(self, on_progress=None):
        root = self.config.roots[0].path
        rows = [
            ("documents", "invoices/2026-08 invoice.pdf", 284_000, False),
            ("documents", "Thesis draft.docx", 1_942_000, True),
            ("documents", "photos/trip/DSC_0142.jpg", 4_820_000, False),
            ("projects", "driftgram/README.md", 7_400, True),
            ("projects", "site/build/bundle.js", 640_000, False),
        ]
        return done([
            RemoteFile(alias=a, rel_path=p, message_id=i + 10, size=s,
                       local_path=root / p, exists_locally=exists, ignored=False)
            for i, (a, p, s, exists) in enumerate(rows)
        ])

    def restore(self, files, overwrite=False):
        return done(len(files))

    def set_paused(self, paused):
        self.is_paused = paused
        return done(None)

    def sync_now(self):
        return done(None)

    def start_sync(self, config=None):
        return done(None)

    def sign_out(self):
        return done(None)

    def send_code(self, phone):
        return done(None)

    def sign_in_code(self, code):
        return done(LoginStep.AUTHORIZED)

    def sign_in_password(self, password):
        return done(LoginStep.AUTHORIZED)


def build_context(tmp: Path, bus: EventBus):
    from src.gui.bridge import EngineSignals
    from src.gui.context import AppContext

    paths = AppPaths(config_file=tmp / "config.yaml", data_dir=tmp, portable=True)
    config = blank_config(paths)
    config.api_id, config.api_hash = 2040123, "a" * 32
    config.app.setup_complete = True
    config.global_ignore = ["*.iso", "node_modules/", "*.log"]
    config.roots = [
        RootConfig(path=Path("D:/Documents"), alias="documents", ignore=["*.tmp", "~$*"]),
        RootConfig(path=Path("D:/Projects"), alias="projects", ignore=["node_modules/", "dist/"]),
        RootConfig(path=Path("E:/Photos"), alias="photos", ignore=[]),
    ]
    supervisor = StubSupervisor(config)
    return AppContext(
        config=config,
        supervisor=supervisor,
        signals=EngineSignals(bus),
        save=lambda: None,
        apply_and_restart=lambda: None,
        notify=lambda message: None,
    ), config, supervisor


def feed_activity(bus: EventBus) -> None:
    """Plausible history, so the activity and status pages aren't empty."""
    bus.emit(SyncEvent(EventKind.UPLOAD_FINISHED, alias="documents",
                       rel_path="invoices/2026-08 invoice.pdf", bytes_total=284_000))
    bus.emit(SyncEvent(EventKind.DOWNLOAD_FINISHED, alias="documents",
                       rel_path="Scanned receipt.jpg", bytes_total=910_000))
    bus.emit(SyncEvent(EventKind.SKIPPED, alias="projects", rel_path="ubuntu-24.04.iso",
                       message="larger than the 1900 MB limit"))
    bus.emit(SyncEvent(EventKind.CONFLICT, alias="documents", rel_path="Thesis draft.docx",
                       message="your version was kept; Telegram's copy saved as "
                               "Thesis draft (from Telegram).docx"))
    bus.emit(SyncEvent(EventKind.ERROR,
                       message="Folder not found: E:/Photos. It may be on a drive that isn't connected."))
    bus.emit(SyncEvent(EventKind.UPLOAD_FINISHED, alias="projects",
                       rel_path="driftgram/src/sync_engine.py", bytes_total=18_400))
    bus.status(RunState.IDLE)


def shoot(widget, path: Path, size=None) -> None:
    if size:
        widget.resize(*size)
    widget.show()
    QApplication.processEvents()
    widget.grab().save(str(path), "PNG")
    print(f"  {path.name}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("out")
    parser.add_argument("--dark", action="store_true")
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    qt = QApplication(sys.argv)
    # Set the scheme explicitly in both directions: leaving it unset would
    # follow the machine's own preference, so a dark desktop would silently
    # render two identical dark sets and the light theme would go unchecked.
    from PySide6.QtCore import Qt
    qt.styleHints().setColorScheme(Qt.ColorScheme.Dark if args.dark else Qt.ColorScheme.Light)
    from src.gui import theme
    theme.apply(qt)

    suffix = "-dark" if args.dark else ""
    bus = EventBus()
    tmp = out / "state"
    tmp.mkdir(exist_ok=True)
    context, config, supervisor = build_context(tmp, bus)

    print("wizard:")
    from src.gui.onboarding import SetupWizard, CREDENTIALS, PHONE, CODE, FOLDERS, OPTIONS, DONE
    wizard = SetupWizard(config, supervisor)
    wizard.roots = list(config.roots)
    wizard._refresh_folder_list()
    for name, page in [("welcome", 0), ("credentials", CREDENTIALS), ("phone", PHONE),
                       ("code", CODE), ("folders", FOLDERS), ("options", OPTIONS), ("done", DONE)]:
        wizard._show_page(page)
        shoot(wizard, out / f"wizard-{name}{suffix}.png", (660, 560))
    wizard.close()

    print("main window:")
    from src.gui.main_window import MainWindow
    window = MainWindow(context, on_quit=lambda: None, can_hide_to_tray=True)
    feed_activity(bus)
    QApplication.processEvents()

    for index, name in enumerate(["status", "folders", "activity", "restore", "settings"]):
        window._select(index)
        if name == "restore":
            window.restore_page._loaded(supervisor.list_remote().result())
            window.restore_page.only_missing.setChecked(False)
        QApplication.processEvents()
        shoot(window, out / f"window-{name}{suffix}.png", (940, 680))

    print("transfer in progress:")
    window._select(0)
    # The engine emits SYNCING before it starts a transfer; without it here the
    # headline would still read "Everything is backed up" mid-upload and the
    # screenshot would misrepresent the real behaviour.
    bus.status(RunState.SYNCING)
    bus.emit(SyncEvent(EventKind.UPLOAD_PROGRESS, alias="documents",
                       rel_path="photos/trip/DSC_0142.jpg",
                       bytes_done=3_100_000, bytes_total=4_820_000))
    QApplication.processEvents()
    shoot(window, out / f"window-status-transferring{suffix}.png", (940, 680))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
