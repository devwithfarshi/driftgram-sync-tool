"""Driftgram: settings, grouped by the question each one answers.

Ordered by how often a normal person needs them, not by how the config file
is laid out: account and behaviour first, tuning knobs last and clearly
marked as advanced. Every label is a sentence about what will happen, because
"poll_interval_seconds" means nothing to the audience this app is for.

Saving is split deliberately. Preferences apply immediately; anything that
changes what the engine watches (the target chat, the skip rules) needs the
engine rebuilt, and only those trigger a restart so a settings tweak doesn't
kick off a full rescan for nothing.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..app import autostart
from ..config import ConflictPolicy
from .bridge import watch
from .context import AppContext
from .widgets import Card, confirm, hint, label, muted, reveal, section, show_error, title


class SettingsPage(QWidget):
    def __init__(self, context: AppContext, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.context = context
        config = context.config

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 12)
        outer.setSpacing(12)
        outer.addWidget(title("Settings"))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 12, 0)
        layout.setSpacing(14)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        # --- account -------------------------------------------------
        account_card = Card()
        account_card.add(section("Telegram account"))
        self.account_label = muted("Checking…")
        account_card.add(self.account_label)

        account_row = QWidget()
        account_layout = QHBoxLayout(account_row)
        account_layout.setContentsMargins(0, 4, 0, 0)
        sign_out = QPushButton("Sign out")
        sign_out.setObjectName("DangerButton")
        sign_out.clicked.connect(self._sign_out)
        account_layout.addWidget(sign_out)
        account_layout.addStretch(1)
        account_card.add(account_row)
        layout.addWidget(account_card)

        # --- destination ---------------------------------------------
        target_card = Card()
        target_card.add(section("Where backups are kept"))
        target_card.add(
            muted(
                "By default your files go to Saved Messages - a private chat in your own "
                "Telegram account that nobody else can see. You can point Driftgram at a "
                "private channel instead if you'd rather keep it separate."
            )
        )
        self.target_entry = QLineEdit(config.target)
        self.target_entry.setPlaceholderText("me")
        target_card.add(self.target_entry)
        target_card.add(muted('Use "me" for Saved Messages, or a channel username or id.'))
        layout.addWidget(target_card)

        # --- conflicts ------------------------------------------------
        conflict_card = Card()
        conflict_card.add(section("If the same file changes in both places"))
        conflict_card.add(
            muted(
                "This decides what happens when Telegram has a newer copy of a file you have "
                "also edited here and not yet backed up."
            )
        )
        self.conflict_group = QButtonGroup(self)
        for policy in ConflictPolicy:
            radio = QRadioButton(policy.label)
            radio.setProperty("policy", policy.value)
            radio.setChecked(policy is config.sync.conflict_policy)
            self.conflict_group.addButton(radio)
            conflict_card.add(radio)
        conflict_card.add(
            muted(
                'Keeping both saves Telegram\'s version alongside yours as "name (from '
                'Telegram).ext", so nothing is ever lost.'
            )
        )
        layout.addWidget(conflict_card)

        # --- deletion -------------------------------------------------
        delete_card = Card()
        delete_card.add(section("Deleting"))
        self.delete_local = QCheckBox(
            "If I delete a file from Telegram, delete it from this computer too"
        )
        self.delete_local.setChecked(config.sync.delete_local_on_remote_delete)
        self.delete_remote = QCheckBox(
            "If I delete a file on this computer, delete its Telegram copy too"
        )
        self.delete_remote.setChecked(config.sync.delete_remote_on_local_delete)
        delete_card.add(self.delete_local)
        delete_card.add(self.delete_remote)
        delete_card.add(
            muted(
                "Deletions are only mirrored while Driftgram is running - Telegram keeps no "
                "record of a deleted message, so one that happened while the app was closed "
                "can never be detected afterwards."
            )
        )
        layout.addWidget(delete_card)

        # --- app behaviour --------------------------------------------
        app_card = Card()
        app_card.add(section("The app"))
        self.start_at_login = QCheckBox("Start Driftgram when I log in")
        self.start_at_login.setChecked(autostart.is_enabled())
        self.start_at_login.setEnabled(autostart.supported())
        if not autostart.supported():
            self.start_at_login.setToolTip("Not supported on this desktop.")
        self.minimize_to_tray = QCheckBox("Keep running in the background when I close the window")
        self.minimize_to_tray.setChecked(config.app.minimize_to_tray)
        self.notifications = QCheckBox("Show a notification when something needs attention")
        self.notifications.setChecked(config.app.notifications)
        for box in (self.start_at_login, self.minimize_to_tray, self.notifications):
            app_card.add(box)
        layout.addWidget(app_card)

        # --- skip rules ------------------------------------------------
        ignore_card = Card()
        ignore_card.add(section("Skip these in every folder"))
        ignore_card.add(muted("One rule per line. Applies on top of each folder's own rules."))
        self.global_ignore = QPlainTextEdit("\n".join(config.global_ignore))
        self.global_ignore.setFixedHeight(110)
        self.global_ignore.setPlaceholderText("*.iso\nnode_modules/")
        ignore_card.add(self.global_ignore)
        self.default_ignores = QCheckBox(
            "Also skip the usual clutter (.git, node_modules, caches, Thumbs.db…)"
        )
        self.default_ignores.setChecked(config.sync.use_default_ignores)
        ignore_card.add(self.default_ignores)
        layout.addWidget(ignore_card)

        # --- advanced ---------------------------------------------------
        advanced_card = Card()
        advanced_card.add(section("Advanced"))

        self.max_size = QSpinBox()
        self.max_size.setRange(1, 4000)
        self.max_size.setSuffix(" MB")
        self.max_size.setValue(config.sync.max_file_size_mb)
        advanced_card.add(self._field("Skip files larger than", self.max_size,
                                      "Telegram's own limit is about 2000 MB, or 4000 MB with Premium."))

        self.poll_interval = QSpinBox()
        self.poll_interval.setRange(5, 3600)
        self.poll_interval.setSuffix(" seconds")
        self.poll_interval.setValue(config.sync.poll_interval_seconds)
        advanced_card.add(self._field("Check Telegram for changes every", self.poll_interval,
                                      "A backstop only - new messages normally arrive instantly."))

        self.debounce = QDoubleSpinBox()
        self.debounce.setRange(0.2, 60.0)
        self.debounce.setSingleStep(0.5)
        self.debounce.setSuffix(" seconds")
        self.debounce.setValue(config.sync.debounce_seconds)
        advanced_card.add(self._field("Wait after a file stops changing", self.debounce,
                                      "Stops an app that saves repeatedly from causing several uploads."))
        layout.addWidget(advanced_card)

        # --- files -------------------------------------------------------
        files_card = Card()
        files_card.add(section("Driftgram's own files"))
        files_card.add(muted(f"Settings and logs: {config.paths.data_dir}"))
        files_row = QWidget()
        files_layout = QHBoxLayout(files_row)
        files_layout.setContentsMargins(0, 4, 0, 0)
        open_data = QPushButton("Open this folder")
        open_data.clicked.connect(lambda: reveal(self.context.config.paths.data_dir))
        files_layout.addWidget(open_data)
        files_layout.addStretch(1)
        files_card.add(files_row)
        layout.addWidget(files_card)

        layout.addStretch(1)

        # --- save bar -----------------------------------------------------
        save_row = QWidget()
        save_layout = QHBoxLayout(save_row)
        save_layout.setContentsMargins(0, 0, 0, 8)
        self.saved_note = muted("")
        save_layout.addWidget(self.saved_note)
        save_layout.addStretch(1)
        save_button = QPushButton("Save changes")
        save_button.setObjectName("Primary")
        save_button.clicked.connect(self._save)
        save_layout.addWidget(save_button)
        outer.addWidget(save_row)

        self.refresh_account()

    # ------------------------------------------------------------------

    def _field(self, text: str, widget: QWidget, note: str = "") -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(3)
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(QLabel(text))
        row_layout.addWidget(widget)
        row_layout.addStretch(1)
        layout.addWidget(row)
        if note:
            layout.addWidget(muted(note))
        return container

    def refresh_account(self) -> None:
        watch(
            self.context.supervisor.account(),
            on_success=self._show_account,
            on_error=lambda _: self.account_label.setText("Not signed in."),
        )

    def _show_account(self, account) -> None:
        if account is None:
            self.account_label.setText("Not signed in.")
        else:
            phone = f" · {account.phone}" if account.phone else ""
            self.account_label.setText(f"Signed in as {account.label}{phone}")

    # ------------------------------------------------------------------

    def _save(self) -> None:
        config = self.context.config

        # Remembered before mutating, so we can tell whether the engine has to
        # be rebuilt or whether this was only a preference change.
        old_target = config.target
        old_ignores = list(config.global_ignore)
        old_defaults = config.sync.use_default_ignores

        config.target = self.target_entry.text().strip() or "me"
        selected = self.conflict_group.checkedButton()
        if selected:
            config.sync.conflict_policy = ConflictPolicy(selected.property("policy"))
        config.sync.delete_local_on_remote_delete = self.delete_local.isChecked()
        config.sync.delete_remote_on_local_delete = self.delete_remote.isChecked()
        config.sync.max_file_size_mb = self.max_size.value()
        config.sync.poll_interval_seconds = self.poll_interval.value()
        config.sync.debounce_seconds = self.debounce.value()
        config.sync.use_default_ignores = self.default_ignores.isChecked()
        config.global_ignore = [
            line.strip() for line in self.global_ignore.toPlainText().splitlines() if line.strip()
        ]
        config.app.minimize_to_tray = self.minimize_to_tray.isChecked()
        config.app.notifications = self.notifications.isChecked()

        if autostart.supported():
            applied = autostart.set_enabled(self.start_at_login.isChecked())
            config.app.start_at_login = applied
            if applied != self.start_at_login.isChecked():
                # The desktop refused; show what is actually true rather than
                # leaving a ticked box that does nothing.
                self.start_at_login.setChecked(applied)
                self.context.notify("Your desktop didn't allow the start-at-login setting.")

        structural = (
            config.target != old_target
            or config.global_ignore != old_ignores
            or config.sync.use_default_ignores != old_defaults
        )

        try:
            if structural:
                self.context.apply_and_restart()
            else:
                self.context.save()
        except Exception as exc:
            show_error(self, exc, "Couldn't save your settings")
            return

        self.saved_note.setText("Saved.")
        self.context.notify("Settings saved.")

    def _sign_out(self) -> None:
        if not confirm(
            self,
            "Sign out of Telegram?",
            "Driftgram will stop backing up until you sign in again. Your files in Telegram "
            "are not touched.",
            ok_text="Sign out",
        ):
            return
        watch(
            self.context.supervisor.sign_out(),
            on_success=lambda _: (self.refresh_account(), self.context.notify("Signed out.")),
            on_error=lambda exc: show_error(self, exc),
        )
