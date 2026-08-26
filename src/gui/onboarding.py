"""Driftgram: first-run setup, written for someone who has never seen a terminal.

The whole reason this app exists is that the command-line tool asks its user
to register a Telegram application, edit YAML, and type a login code into a
console. This wizard replaces all of that with a sequence of small screens,
each asking exactly one thing and explaining why it needs it.

The Telegram credentials step is the one real cliff: Telegram requires every
application to be registered, and there is no way around that other than
shipping a shared key, which we deliberately do not do - a shared key that
gets rate-limited would break the app for everyone at once. So the step is
made as short as possible: a button that opens the right page, two boxes to
paste into, and a check that catches typos before they turn into an
inscrutable error from the API.

Branching (2FA is only asked for when the account has it) is why this is a
QStackedWidget rather than QWizard: the flow is decided per step, in code,
right next to the step that decides it.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from ..config import (
    IGNORE_PRESETS,
    AppConfig,
    ConflictPolicy,
    RootConfig,
    root_conflict,
    suggest_alias,
)
from ..app.supervisor import LoginStep, Supervisor
from .bridge import watch
from .icons import app_pixmap
from .widgets import hint, label, muted, section, show_error, title, open_url

logger = logging.getLogger("driftgram.gui.setup")

WELCOME, CREDENTIALS, PHONE, CODE, PASSWORD, FOLDERS, OPTIONS, DONE = range(8)

_HASH_RE = re.compile(r"^[0-9a-fA-F]{32}$")
_PHONE_RE = re.compile(r"^\+?[0-9][0-9 \-()]{6,}$")


class StepDots(QWidget):
    """A row of dots showing roughly how far through setup the user is.

    Roughly, on purpose: the 2FA step only exists for some accounts, so an
    exact "step 4 of 7" would either lie or change under the user mid-flow.
    """

    def __init__(self, count: int, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._count = count
        self._current = 0
        self._accent = QColor("#1C82C4")
        self._idle = QColor(0, 0, 0, 45)
        self.setFixedHeight(14)

    def configure(self, accent: str, idle: str) -> None:
        self._accent = QColor(accent)
        self._idle = QColor(idle)
        self.update()

    def set_current(self, index: int) -> None:
        self._current = index
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(self._count * 16, 14)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        for index in range(self._count):
            painter.setBrush(self._accent if index <= self._current else self._idle)
            diameter = 8 if index == self._current else 6
            y = (self.height() - diameter) / 2
            painter.drawEllipse(int(index * 16), int(y), diameter, diameter)
        painter.end()


class SetupWizard(QDialog):
    """Collects credentials, signs in, picks folders, and returns a saved config."""

    completed = Signal(object)  # AppConfig

    def __init__(self, config: AppConfig, supervisor: Supervisor, parent: Optional[QWidget] = None,
                 already_signed_in: bool = False):
        super().__init__(parent)
        self.config = config
        self.supervisor = supervisor
        self.roots: List[RootConfig] = list(config.roots)
        self._busy = False
        self._signed_in = already_signed_in

        self.setWindowTitle("Set up Driftgram")
        self.setMinimumSize(660, 560)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._pages = QWidget()
        self._page_layout = QVBoxLayout(self._pages)
        self._page_layout.setContentsMargins(36, 32, 36, 16)
        self._page_layout.setSpacing(14)
        outer.addWidget(self._pages, 1)

        self._build_pages()

        footer = QWidget()
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(36, 12, 36, 24)
        self.dots = StepDots(6)
        footer_layout.addWidget(self.dots)
        footer_layout.addStretch(1)
        self.back_button = QPushButton("Back")
        self.back_button.clicked.connect(self._go_back)
        self.next_button = QPushButton("Continue")
        self.next_button.setObjectName("Primary")
        self.next_button.setDefault(True)
        self.next_button.clicked.connect(self._go_next)
        footer_layout.addWidget(self.back_button)
        footer_layout.addWidget(self.next_button)
        outer.addWidget(footer)

        self._index = FOLDERS if already_signed_in else WELCOME
        self._show_page(self._index)

    # ------------------------------------------------------------------
    # page construction
    # ------------------------------------------------------------------

    def _build_pages(self) -> None:
        from PySide6.QtWidgets import QStackedWidget

        self.stack = QStackedWidget()
        self._page_layout.addWidget(self.stack)
        self.stack.addWidget(self._page_welcome())
        self.stack.addWidget(self._page_credentials())
        self.stack.addWidget(self._page_phone())
        self.stack.addWidget(self._page_code())
        self.stack.addWidget(self._page_password())
        self.stack.addWidget(self._page_folders())
        self.stack.addWidget(self._page_options())
        self.stack.addWidget(self._page_done())

    def _page(self, *widgets: QWidget) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        for widget in widgets:
            layout.addWidget(widget)
        layout.addStretch(1)
        return page

    def _page_welcome(self) -> QWidget:
        logo = QLabel()
        logo.setPixmap(app_pixmap(72))
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)

        heading = title("Welcome to Driftgram")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)

        blurb = hint(
            "Driftgram keeps the folders you choose backed up to your own Telegram "
            "account, and brings changes back the other way too. Your files stay "
            "private - they go to Saved Messages, a chat only you can see."
        )
        blurb.setAlignment(Qt.AlignmentFlag.AlignCenter)

        points = muted(
            "•  Works in the background, with no size limit per file beyond Telegram's own 2 GB\n"
            "•  Send a file to Saved Messages from your phone and it lands in the right folder here\n"
            "•  Setup takes about three minutes, most of it copying two values from Telegram"
        )

        return self._page(logo, heading, blurb, muted(""), points)

    def _page_credentials(self) -> QWidget:
        steps = muted(
            "Telegram asks every app that connects to it to be registered - including this "
            "one, on your account. It is free, takes a minute, and you only do it once.\n\n"
            "1.  Click the button below. Log in with the phone number you use for Telegram.\n"
            "2.  Open “API development tools”.\n"
            "3.  Fill in any app name and short name (“Driftgram” works), then create it.\n"
            "4.  Copy the two values it shows you into the boxes below."
        )

        open_button = QPushButton("Open my.telegram.org")
        open_button.clicked.connect(lambda: open_url("https://my.telegram.org/apps"))
        open_button.setFixedWidth(220)

        self.api_id_entry = QLineEdit()
        self.api_id_entry.setPlaceholderText("api_id  —  digits only, e.g. 2040123")
        self.api_hash_entry = QLineEdit()
        self.api_hash_entry.setPlaceholderText("api_hash  —  32 letters and numbers")

        if self.config.api_id:
            self.api_id_entry.setText(str(self.config.api_id))
        if self.config.api_hash:
            self.api_hash_entry.setText(self.config.api_hash)

        self.credentials_error = label("", "Danger", wrap=True)
        self.credentials_error.hide()

        return self._page(
            title("Connect to Telegram"),
            steps,
            open_button,
            section("api_id"),
            self.api_id_entry,
            section("api_hash"),
            self.api_hash_entry,
            self.credentials_error,
        )

    def _page_phone(self) -> QWidget:
        self.phone_entry = QLineEdit()
        self.phone_entry.setPlaceholderText("+8801712345678")
        self.phone_error = label("", "Danger", wrap=True)
        self.phone_error.hide()
        return self._page(
            title("Sign in"),
            hint(
                "Enter the phone number for your Telegram account, including the country "
                "code. Telegram will send you a login code to confirm it's you."
            ),
            section("Phone number"),
            self.phone_entry,
            muted(
                "Driftgram runs entirely on this computer. Your number and your files are "
                "never sent anywhere except Telegram itself."
            ),
            self.phone_error,
        )

    def _page_code(self) -> QWidget:
        self.code_entry = QLineEdit()
        self.code_entry.setObjectName("CodeEntry")
        self.code_entry.setMaxLength(6)
        self.code_error = label("", "Danger", wrap=True)
        self.code_error.hide()
        resend = QPushButton("Didn't get a code? Go back and try again")
        resend.setObjectName("Link")
        resend.clicked.connect(self._go_back)
        return self._page(
            title("Enter your login code"),
            hint(
                "Telegram has sent you a code. If you're signed in to Telegram on your phone "
                "or another device, look for it there in the Telegram chat - otherwise check "
                "your text messages."
            ),
            self.code_entry,
            self.code_error,
            resend,
        )

    def _page_password(self) -> QWidget:
        self.password_entry = QLineEdit()
        self.password_entry.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_entry.setPlaceholderText("Your Telegram password")
        self.password_error = label("", "Danger", wrap=True)
        self.password_error.hide()
        return self._page(
            title("Two-step verification"),
            hint(
                "Your account has an extra password set up in Telegram. Enter it to finish "
                "signing in. This is not the code you just typed."
            ),
            self.password_entry,
            self.password_error,
        )

    def _page_folders(self) -> QWidget:
        self.folder_list = QListWidget()
        self.folder_list.setMinimumHeight(150)

        add_button = QPushButton("Add a folder…")
        add_button.setObjectName("Primary")
        add_button.clicked.connect(self._add_folder)
        remove_button = QPushButton("Remove")
        remove_button.clicked.connect(self._remove_folder)

        buttons = QWidget()
        buttons_layout = QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.addWidget(add_button)
        buttons_layout.addWidget(remove_button)
        buttons_layout.addStretch(1)

        self.preset_boxes: List[tuple] = []
        presets = QWidget()
        presets_layout = QVBoxLayout(presets)
        presets_layout.setContentsMargins(0, 0, 0, 0)
        presets_layout.setSpacing(2)
        for text, patterns in IGNORE_PRESETS.items():
            box = QCheckBox(text)
            # Developer clutter is checked by default because it is both the
            # largest and the least worth backing up; the rest are opt-in.
            box.setChecked(patterns[0] == "node_modules/")
            presets_layout.addWidget(box)
            self.preset_boxes.append((box, patterns))

        self._refresh_folder_list()

        return self._page(
            title("Choose what to back up"),
            hint(
                "Pick the folders you want kept safe. Everything inside them, including "
                "subfolders, is backed up. You can add or remove folders later."
            ),
            self.folder_list,
            buttons,
            section("Skip these, to save space and time"),
            presets,
        )

    def _page_options(self) -> QWidget:
        self.autostart_box = QCheckBox("Start Driftgram when I log in")
        self.autostart_box.setChecked(True)
        self.delete_local_box = QCheckBox(
            "If I delete a file from Telegram, delete it from this computer too"
        )
        self.delete_remote_box = QCheckBox(
            "If I delete a file on this computer, delete its Telegram copy too"
        )

        self.conflict_group = QButtonGroup(self)
        conflict_widget = QWidget()
        conflict_layout = QVBoxLayout(conflict_widget)
        conflict_layout.setContentsMargins(0, 0, 0, 0)
        conflict_layout.setSpacing(2)
        for policy in ConflictPolicy:
            radio = QRadioButton(policy.label)
            radio.setProperty("policy", policy.value)
            self.conflict_group.addButton(radio)
            conflict_layout.addWidget(radio)
            if policy is ConflictPolicy.KEEP_BOTH:
                radio.setChecked(True)

        return self._page(
            title("A few preferences"),
            section("Starting up"),
            self.autostart_box,
            section("Deleting"),
            muted(
                "Both of these are off to begin with, so nothing is ever removed without you "
                "doing it yourself in both places."
            ),
            self.delete_local_box,
            self.delete_remote_box,
            section("If the same file changes in both places"),
            conflict_widget,
        )

    def _page_done(self) -> QWidget:
        logo = QLabel()
        logo.setPixmap(app_pixmap(64))
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.done_summary = hint("")
        self.done_summary.setAlignment(Qt.AlignmentFlag.AlignCenter)
        heading = title("You're all set")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return self._page(
            logo,
            heading,
            self.done_summary,
            muted(
                "The first backup may take a while if your folders are large - Driftgram works "
                "through them in the background, and you can close the window. It keeps running "
                "in the notification area."
            ),
        )

    # ------------------------------------------------------------------
    # folders
    # ------------------------------------------------------------------

    def _refresh_folder_list(self) -> None:
        self.folder_list.clear()
        for root in self.roots:
            item = QListWidgetItem(str(root.path))
            item.setData(Qt.ItemDataRole.UserRole, root.alias)
            self.folder_list.addItem(item)
        if not self.roots:
            placeholder = QListWidgetItem("No folders chosen yet — click “Add a folder”")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.folder_list.addItem(placeholder)

    def _add_folder(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Choose a folder to back up", str(Path.home()))
        if not chosen:
            return
        path = Path(chosen)
        problem = root_conflict(path, self.roots)
        if problem:
            show_error(self, ValueError(problem), "That folder can't be added")
            return
        alias = suggest_alias(path, [r.alias for r in self.roots])
        self.roots.append(RootConfig(path=path, alias=alias, ignore=[]))
        self._refresh_folder_list()
        self._sync_next_state()

    def _remove_folder(self) -> None:
        row = self.folder_list.currentRow()
        if 0 <= row < len(self.roots):
            self.roots.pop(row)
            self._refresh_folder_list()
            self._sync_next_state()

    # ------------------------------------------------------------------
    # navigation
    # ------------------------------------------------------------------

    _DOT_FOR_PAGE = {
        WELCOME: 0, CREDENTIALS: 1, PHONE: 2, CODE: 2,
        PASSWORD: 2, FOLDERS: 3, OPTIONS: 4, DONE: 5,
    }

    def _show_page(self, index: int) -> None:
        self._index = index
        self.stack.setCurrentIndex(index)
        self.dots.set_current(self._DOT_FOR_PAGE[index])

        labels = {WELCOME: "Get started", DONE: "Start backing up"}
        self.next_button.setText(labels.get(index, "Continue"))
        # Hidden rather than disabled: on the first screen there is nothing
        # behind it, and once the account is signed in there is nothing back
        # there that could still be changed. A greyed-out button on step one
        # just reads as something being broken. Continue is right-aligned, so
        # hiding Back shifts nothing.
        self.back_button.setVisible(index not in (WELCOME, FOLDERS, DONE))
        self._sync_next_state()

        focus = {
            CREDENTIALS: getattr(self, "api_id_entry", None),
            PHONE: getattr(self, "phone_entry", None),
            CODE: getattr(self, "code_entry", None),
            PASSWORD: getattr(self, "password_entry", None),
        }.get(index)
        if focus is not None:
            focus.setFocus()

        if index == DONE:
            names = ", ".join(root.path.name or str(root.path) for root in self.roots)
            self.done_summary.setText(
                f"Driftgram will keep {len(self.roots)} folder"
                f"{'s' if len(self.roots) != 1 else ''} backed up: {names}."
            )

    def _sync_next_state(self) -> None:
        enabled = not self._busy
        if self._index == FOLDERS:
            enabled = enabled and bool(self.roots)
        self.next_button.setEnabled(enabled)

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self._busy = busy
        self.next_button.setText(message or ("Continue" if self._index != DONE else "Start backing up"))
        self.back_button.setEnabled(not busy)
        self._sync_next_state()

    def _go_back(self) -> None:
        previous = {
            CREDENTIALS: WELCOME,
            PHONE: CREDENTIALS,
            CODE: PHONE,
            PASSWORD: CODE,
            OPTIONS: FOLDERS,
        }.get(self._index)
        if previous is not None:
            self._clear_errors()
            self._show_page(previous)

    def _clear_errors(self) -> None:
        for name in ("credentials_error", "phone_error", "code_error", "password_error"):
            widget = getattr(self, name, None)
            if widget is not None:
                widget.hide()

    def _fail(self, widget: QLabel, message: str) -> None:
        widget.setText(message)
        widget.show()

    def _go_next(self) -> None:
        if self._busy:
            return
        self._clear_errors()
        handler = {
            WELCOME: lambda: self._show_page(CREDENTIALS),
            CREDENTIALS: self._submit_credentials,
            PHONE: self._submit_phone,
            CODE: self._submit_code,
            PASSWORD: self._submit_password,
            FOLDERS: lambda: self._show_page(OPTIONS),
            OPTIONS: lambda: self._show_page(DONE),
            DONE: self._finish,
        }[self._index]
        handler()

    # ------------------------------------------------------------------
    # steps that talk to Telegram
    # ------------------------------------------------------------------

    def _submit_credentials(self) -> None:
        api_id = self.api_id_entry.text().strip()
        api_hash = self.api_hash_entry.text().strip()

        if not api_id.isdigit():
            self._fail(
                self.credentials_error,
                "The api_id should be digits only - copy just the number, with no spaces.",
            )
            return
        if not _HASH_RE.match(api_hash):
            self._fail(
                self.credentials_error,
                "The api_hash should be exactly 32 letters and numbers. Copy the whole value.",
            )
            return

        self.config.api_id = int(api_id)
        self.config.api_hash = api_hash
        # The supervisor builds its client from config, so it has to see the
        # new credentials before we ask it to connect.
        self.supervisor.config = self.config

        self._set_busy(True, "Connecting…")
        watch(
            self.supervisor.connect(),
            on_success=self._after_connect,
            on_error=self._on_step_error(self.credentials_error),
        )

    def _after_connect(self, step) -> None:
        self._set_busy(False)
        if step == LoginStep.AUTHORIZED:
            self._signed_in = True
            self._show_page(FOLDERS)
        else:
            self._show_page(PHONE)

    def _submit_phone(self) -> None:
        phone = self.phone_entry.text().strip()
        if not _PHONE_RE.match(phone):
            self._fail(
                self.phone_error,
                "That doesn't look like a phone number. Include the country code, "
                "for example +8801712345678.",
            )
            return
        self._set_busy(True, "Sending code…")
        watch(
            self.supervisor.send_code(phone),
            on_success=lambda _: (self._set_busy(False), self._show_page(CODE)),
            on_error=self._on_step_error(self.phone_error),
        )

    def _submit_code(self) -> None:
        code = self.code_entry.text().strip()
        if len(code) < 4:
            self._fail(self.code_error, "Enter the code Telegram sent you.")
            return
        self._set_busy(True, "Checking…")
        watch(
            self.supervisor.sign_in_code(code),
            on_success=self._after_code,
            on_error=self._on_step_error(self.code_error),
        )

    def _after_code(self, step) -> None:
        self._set_busy(False)
        if step == LoginStep.NEED_PASSWORD:
            self._show_page(PASSWORD)
        else:
            self._signed_in = True
            self._show_page(FOLDERS)

    def _submit_password(self) -> None:
        password = self.password_entry.text()
        if not password:
            self._fail(self.password_error, "Enter your Telegram password.")
            return
        self._set_busy(True, "Signing in…")
        watch(
            self.supervisor.sign_in_password(password),
            on_success=lambda _: (self._set_busy(False), self._mark_signed_in()),
            on_error=self._on_step_error(self.password_error),
        )

    def _mark_signed_in(self) -> None:
        self._signed_in = True
        self._show_page(FOLDERS)

    def _on_step_error(self, widget: QLabel):
        def handler(error: BaseException) -> None:
            self._set_busy(False)
            message = getattr(error, "message", None) or str(error)
            detail = getattr(error, "hint", None)
            self._fail(widget, f"{message} {detail}" if detail else message)

        return handler

    # ------------------------------------------------------------------
    # finish
    # ------------------------------------------------------------------

    def _finish(self) -> None:
        extra_ignores: List[str] = []
        for box, patterns in self.preset_boxes:
            if box.isChecked():
                extra_ignores.extend(patterns)

        selected = self.conflict_group.checkedButton()
        policy = ConflictPolicy(selected.property("policy")) if selected else ConflictPolicy.KEEP_BOTH

        self.config.roots = self.roots
        self.config.global_ignore = sorted(set(self.config.global_ignore) | set(extra_ignores))
        self.config.sync.conflict_policy = policy
        self.config.sync.delete_local_on_remote_delete = self.delete_local_box.isChecked()
        self.config.sync.delete_remote_on_local_delete = self.delete_remote_box.isChecked()
        self.config.app.start_at_login = self.autostart_box.isChecked()
        self.config.app.setup_complete = True

        self.completed.emit(self.config)
        self.accept()
