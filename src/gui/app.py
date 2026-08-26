"""Driftgram: starting the desktop app.

Order of business, and why:

  1. One instance only. Two copies would fight over the manifest and the
     Telegram session, so a second launch hands its request to the first one
     (raising its window) and exits. A local socket does that *and* gives us
     the "raise the existing window" behaviour a user expects from clicking
     a desktop icon twice.
  2. A file lock on the data directory as well, because the CLI tools are
     separate processes that a socket cannot see.
  3. Load config, start the engine thread, connect.
  4. Setup wizard if anything is missing, main window if not.

Nothing here blocks the GUI thread on the engine: every call into the
supervisor returns a future, watched via bridge.watch.
"""
from __future__ import annotations

import argparse
import logging
import sys
from typing import Optional

from PySide6.QtCore import QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from ..app import autostart
from ..app.instance_lock import InstanceLock
from ..app.logging_setup import configure as configure_logging
from ..app.supervisor import LoginStep, Supervisor
from ..config import is_configured, load_or_blank, save_config
from ..errors import AlreadyRunningError, DriftgramError
from ..events import EventBus, RunState
from . import theme, tray as tray_module
from .bridge import EngineSignals, watch
from .context import AppContext
from .icons import app_icon
from .main_window import MainWindow
from .onboarding import SetupWizard
from .widgets import show_error

logger = logging.getLogger("driftgram.gui.app")

SOCKET_NAME = "driftgram-single-instance"


class DriftgramApp:
    def __init__(self, qt_app: QApplication, args: argparse.Namespace):
        self.qt = qt_app
        self.args = args
        self.bus = EventBus()
        self.window: Optional[MainWindow] = None
        self.tray: Optional[tray_module.Tray] = None
        self._quitting = False

        # A frozen build always uses the per-user locations: a desktop
        # shortcut inherits whatever working directory the shell felt like,
        # and picking up a stray config.yaml from it would be baffling.
        self.config = load_or_blank(args.config, force_managed=autostart.is_frozen())
        self.config.paths.ensure_dirs()
        configure_logging(self.config.paths.log_file, console=not autostart.is_frozen())

        self.lock = InstanceLock(self.config.paths.lock_file).acquire()

        self.supervisor = Supervisor(self.config, self.bus)
        self.signals = EngineSignals(self.bus)
        self.context = AppContext(
            config=self.config,
            supervisor=self.supervisor,
            signals=self.signals,
            save=self._save,
            apply_and_restart=self._apply_and_restart,
            notify=self._notify,
        )

    # ------------------------------------------------------------------
    # context callbacks
    # ------------------------------------------------------------------

    def _save(self) -> None:
        save_config(self.config)

    def _apply_and_restart(self) -> None:
        save_config(self.config)
        watch(
            self.supervisor.start_sync(self.config),
            on_error=lambda exc: show_error(self.window, exc, "Couldn't apply your changes"),
        )

    def _notify(self, message: str) -> None:
        if self.window is not None:
            self.window.notify(message)
        else:
            logger.info("%s", message)

    # ------------------------------------------------------------------
    # startup
    # ------------------------------------------------------------------

    def run(self) -> int:
        logger.info(
            "Driftgram starting - data in %s, %s build",
            self.config.paths.data_dir,
            "frozen" if autostart.is_frozen() else "source",
        )
        self.supervisor.start()
        # Deferred to the first turn of the event loop rather than run inline.
        # Startup can end in quit() - a cancelled setup wizard does exactly
        # that - and QApplication.quit() before exec() has begun is a no-op,
        # which would leave exec() running forever with no window to close.
        QTimer.singleShot(0, self._begin)
        return self.qt.exec()

    def _begin(self) -> None:
        if not (self.config.api_id and self.config.api_hash):
            # Nothing to connect with yet. Trying anyway would fail with
            # Telethon's own wording about empty API IDs, which is both alarming
            # and useless to someone who has simply never run setup.
            self._open_wizard(already_signed_in=False)
        else:
            watch(
                self.supervisor.connect(),
                on_success=self._after_connect,
                on_error=self._connect_failed,
            )

    def _connect_failed(self, error: BaseException) -> None:
        # Being unable to reach Telegram at launch is not fatal - the account
        # may still be signed in and the network may come back. Show the app
        # and let the engine's own reconnection handle it.
        logger.warning("Initial connection failed: %s", error)
        self.bus.status(RunState.OFFLINE, "Couldn't reach Telegram. Retrying in the background.")
        if is_configured(self.config):
            self._open_main_window(start_sync=True)
        else:
            self._open_wizard(already_signed_in=False)

    def _after_connect(self, step) -> None:
        signed_in = step == LoginStep.AUTHORIZED
        if signed_in and is_configured(self.config):
            self._open_main_window(start_sync=True)
        else:
            self._open_wizard(already_signed_in=signed_in)

    # ------------------------------------------------------------------
    # windows
    # ------------------------------------------------------------------

    def _open_wizard(self, already_signed_in: bool) -> None:
        wizard = SetupWizard(self.config, self.supervisor, already_signed_in=already_signed_in)
        wizard.setWindowIcon(app_icon())
        wizard.completed.connect(self._setup_finished)
        if wizard.exec() != SetupWizard.DialogCode.Accepted and self.window is None:
            # Closed without finishing: there is nothing to run, so exit
            # rather than leaving a half-configured app in the tray.
            self.quit()

    def _setup_finished(self, config) -> None:
        self.config = config
        self.context.config = config
        self.supervisor.config = config
        try:
            save_config(config)
        except DriftgramError as exc:
            show_error(None, exc, "Couldn't save your settings")
            return
        if autostart.supported():
            autostart.set_enabled(config.app.start_at_login)
        self._open_main_window(start_sync=True)

    def _open_main_window(self, start_sync: bool) -> None:
        if self.window is None:
            can_hide = tray_module.available()
            self.window = MainWindow(self.context, on_quit=self.quit, can_hide_to_tray=can_hide)
            if can_hide:
                self._build_tray()
                self.window.hidden_to_tray.connect(self._tray_notice)
            else:
                logger.info("No system tray on this desktop; the window will not hide.")

        if not (self.args.tray and tray_module.available()):
            self.window.show()
            self.window.raise_()
            self.window.activateWindow()

        if start_sync:
            watch(
                self.supervisor.start_sync(self.config),
                on_error=lambda exc: show_error(self.window, exc, "Couldn't start syncing"),
            )

    def _build_tray(self) -> None:
        self.tray = tray_module.Tray(
            on_open=self._show_window,
            on_toggle_pause=self._toggle_pause,
            on_sync_now=lambda: watch(self.supervisor.sync_now()),
            on_quit=self.quit,
        )
        self.tray.set_notifications_enabled(self.config.app.notifications)
        self.signals.event.connect(self.tray.on_event)
        self.tray.show()

    def _tray_notice(self, message: str) -> None:
        if self.tray is not None:
            self.tray.showMessage("Driftgram", message)

    def _show_window(self) -> None:
        if self.window is None:
            return
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def _toggle_pause(self) -> None:
        watch(self.supervisor.set_paused(not self.supervisor.is_paused))

    # ------------------------------------------------------------------
    # shutdown
    # ------------------------------------------------------------------

    def quit(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        if self.tray is not None:
            self.tray.hide()
        self.signals.detach()
        # Blocking briefly here is correct: the manifest and the Telegram
        # session must be closed cleanly before the process goes away.
        self.supervisor.shutdown()
        self.lock.release()
        self.qt.quit()


# --------------------------------------------------------------------------
# single instance
# --------------------------------------------------------------------------


def _hand_off_to_running_instance() -> bool:
    """True if another copy answered and was asked to show itself."""
    socket = QLocalSocket()
    socket.connectToServer(SOCKET_NAME)
    if not socket.waitForConnected(400):
        return False
    socket.write(b"show")
    socket.waitForBytesWritten(400)
    socket.disconnectFromServer()
    return True


def _listen_for_other_instances(app: DriftgramApp) -> QLocalServer:
    # A crashed previous run can leave the socket file behind on Linux; the
    # connect attempt above already proved nobody is listening on it.
    QLocalServer.removeServer(SOCKET_NAME)
    server = QLocalServer()
    server.listen(SOCKET_NAME)

    def on_connection() -> None:
        connection = server.nextPendingConnection()
        if connection is not None:
            connection.readyRead.connect(lambda: app._show_window())
            connection.disconnected.connect(connection.deleteLater)

    server.newConnection.connect(on_connection)
    return server


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="driftgram", description="Driftgram desktop app")
    parser.add_argument("--config", default=None, help="Use a specific settings file")
    parser.add_argument(
        "--tray", action="store_true", help="Start hidden in the notification area (used at login)"
    )
    parser.add_argument("--selftest", action="store_true", help=argparse.SUPPRESS)
    return parser


def selftest() -> int:
    """Prove a packaged build actually works, without opening a window.

    Freezing an app breaks in ways that source never does: a Qt platform
    plugin left out, a Telethon submodule that only gets imported by name, a
    missing TLS backend. All of those surface as a silent failure to launch -
    exactly the thing nobody notices until a user reports it. This touches
    each of them and reports what it found, so CI can gate on it.
    """
    import pathspec
    import telethon
    import watchdog.observers
    import yaml
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtNetwork import QLocalServer

    from ..state import StateStore  # noqa: F401 - importing is the test
    from ..sync_engine import SyncEngine  # noqa: F401
    from .icons import app_pixmap
    from .main_window import MainWindow  # noqa: F401
    from .onboarding import SetupWizard  # noqa: F401

    checks = [
        ("Qt platform plugin", QGuiApplication.platformName() or "none"),
        ("Qt local sockets", "ok" if QLocalServer else "missing"),
        ("icon rendering", "ok" if not app_pixmap(64).isNull() else "FAILED"),
        ("telethon", telethon.__version__),
        ("watchdog observer", watchdog.observers.Observer.__name__),
        ("pathspec", getattr(pathspec, "__version__", "ok")),
        ("yaml", yaml.__version__),
        ("system tray", "available" if tray_module.available() else "unavailable"),
    ]
    for name, value in checks:
        print(f"  {name:22} {value}")
    failed = [name for name, value in checks if value in ("FAILED", "none", "missing")]
    if failed:
        print("SELFTEST FAILED:", ", ".join(failed))
        return 1
    print("SELFTEST OK")
    return 0


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv if argv is not None else sys.argv[1:])

    qt_app = QApplication(sys.argv)
    qt_app.setApplicationName("Driftgram")
    qt_app.setApplicationDisplayName("Driftgram")
    qt_app.setOrganizationName("Driftgram")
    qt_app.setDesktopFileName("driftgram")
    qt_app.setWindowIcon(app_icon())
    # The tray keeps the app alive with no window open; without this, hiding
    # the last window would quietly quit the process.
    qt_app.setQuitOnLastWindowClosed(False)
    theme.apply(qt_app)

    if args.selftest:
        return selftest()

    if _hand_off_to_running_instance():
        return 0

    try:
        app = DriftgramApp(qt_app, args)
    except AlreadyRunningError as exc:
        show_error(None, exc)
        return 1
    except DriftgramError as exc:
        show_error(None, exc, "Driftgram couldn't start")
        return 1

    server = _listen_for_other_instances(app)
    qt_app.aboutToQuit.connect(server.close)
    return app.run()


if __name__ == "__main__":
    raise SystemExit(main())
