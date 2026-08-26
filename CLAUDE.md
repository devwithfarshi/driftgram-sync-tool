# CLAUDE.md

Guidance for Claude (or anyone else) working in this repository.

## What this is

**Driftgram** - keeps chosen folders two-way synced with a Telegram chat,
using a personal Telegram account via Telethon (not the Bot API, to avoid the
50MB bot upload cap). A filesystem watcher on one side, a Telegram client on
the other, reconciled through a local SQLite manifest.

It ships two front ends over one engine:

- **`src/gui/`** - a PySide6 desktop app for Windows and Linux, aimed at
  people who have never opened a terminal. Setup wizard, folder picker, tray
  icon, in-app restore.
- **`src/main.py` / `src/restore.py`** - the original CLI. Still fully
  supported and needs no Qt installed.

Both read the same config and the same manifest, and only one may run at a
time (enforced by `src/app/instance_lock.py`).

## The one invariant that matters most

**Nothing acts on a file unless its content differs from what the manifest
(`manifest.db`, via `src/state.py`) last recorded.**

This is what prevents the classic two-way-sync infinite loop: upload → file
reappears as a Telegram message → gets "downloaded" → touches local file →
watcher sees it → re-uploads → forever. Every code path that uploads or
downloads a file **must** check the manifest first and **must** update it
immediately after acting, before returning. If you touch `sync_engine.py`,
preserve this pattern — it's not an optimization, it's the correctness
mechanism for the whole tool.

Two independent guards work together:
- **Local → remote**: `_maybe_upload` compares `(size, mtime)` first (cheap),
  falls back to a SHA-256 hash comparison only when those differ, and skips
  the upload if the hash matches what's on record.
- **Remote → local**: `_handle_remote_message_inner` checks
  `get_by_message_id` first (catches echoes of our own uploads) and compares
  the incoming message id against the manifest's recorded id for that path
  (catches redundant re-delivery) before downloading anything.

## Architecture

```
src/errors.py         DriftgramError and friends. Every recoverable failure
                      raises one of these carrying a message written for a
                      non-technical reader. Nothing in the library calls
                      sys.exit() - a GUI has to show a dialog and survive.

src/paths.py          AppPaths: portable mode (a config.yaml in the working
                      directory - the CLI's historical behaviour) vs managed
                      mode (%APPDATA%\Driftgram, ~/.config + ~/.local/share).

src/config.py         Loads AND saves settings. Credentials come from the
                      environment (.env, wins) or from config.yaml itself
                      (what the wizard writes). Owns DEFAULT_IGNORES,
                      INTERNAL_IGNORES, IGNORE_PRESETS, ConflictPolicy, and
                      the root_conflict / suggest_alias helpers the GUI uses.

src/events.py         EventBus: thread-safe pub/sub of SyncEvents so a UI can
                      show progress. NullBus when nobody is listening, which
                      is how the CLI pays nothing for it.

src/ignore_rules.py   IgnoreMatcher: gitignore-syntax matching per root,
                      combining INTERNAL_IGNORES (always) + defaults +
                      global_ignore + per-root ignore.

src/fsutil.py         unwritable_reason (names Windows can't create),
                      conflict_path (keep-both naming), human_bytes.

src/state.py          StateStore: SQLite manifest (files table + meta table).
                      The source of truth for "have we already synced this
                      exact content?", plus the counts the GUI displays.

src/tg_client.py      Telethon upload/download primitives + caption
                      encode/decode, with optional progress callbacks.
                      Caption format:
                          DRIFTGRAM
                          <root alias>
                          <relative path>
                      Every upload uses force_document=True so Telegram
                      never recompresses/transcodes the file.

src/local_watcher.py  watchdog wrapper with per-path debouncing
                      (threading.Timer), handing settled events back to the
                      asyncio loop via run_coroutine_threadsafe. Translates
                      inotify's ENOSPC into a readable WatcherError.

src/sync_engine.py    SyncEngine: the orchestrator. initial_scan(),
                      handle_local_change(), handle_remote_message(),
                      handle_remote_delete(), poll_remote_loop(), plus
                      collect_remote_index() / restore_files() for restore
                      and set_paused() for the GUI.

src/main.py           CLI entry point.
src/restore.py        CLI restore tool (delegates to SyncEngine).

src/app/              Application lifecycle. Knows nothing about Qt.
    supervisor.py       Owns an asyncio loop on its own thread plus the
                        Telegram client and engine. Every operation is a
                        thread-safe call returning a concurrent.futures.Future.
    instance_lock.py    OS-level advisory lock; one process per data dir.
    autostart.py        HKCU\...\Run on Windows, ~/.config/autostart on Linux.
    logging_setup.py    Rotating log file + optional console.

src/gui/              PySide6. Imports src.app, never the reverse.
    app.py              Bootstrap, single instance (QLocalServer), wiring.
    bridge.py           EngineSignals (EventBus -> Qt signals) and watch()
                        (Future -> GUI-thread callback).
    onboarding.py       First-run wizard, including the guided credentials step.
    main_window.py      Sidebar + pages + hide-to-tray.
    page_*.py           status / folders / activity / restore / settings.
    tray.py             QSystemTrayIcon with status badge and notifications.
    theme.py            Light/dark palettes and the stylesheet.
    icons.py            App and tray icons drawn with QPainter; also writes
                        the .ico / .png the installers need.
    widgets.py          Card, StatTile, show_error, confirm, reveal.
    context.py          AppContext: config + supervisor + save/restart hooks.

packaging/            driftgram.spec (PyInstaller), entry.py, make_icons.py,
                      windows/driftgram.iss (Inno Setup), linux/build_*.sh,
                      build.py (one command per platform).
tools/screenshot.py   Renders every screen to PNG against a stub supervisor.
```

Data flow for a local edit: watchdog → debounce → `handle_local_change` →
`_maybe_upload` (manifest check → hash → upload) → manifest updated with new
`tg_message_id`.

Data flow for a remote file (e.g. sent from phone): Telethon `NewMessage`
event (live) or `poll_remote_loop` (backstop) → `handle_remote_message` →
manifest/echo checks → conflict check → download → manifest updated.

## Threading model

The GUI owns the main thread; the engine gets its own thread with its own
asyncio loop, created by `Supervisor`. **Telethon is not thread-safe** — every
call on the client must happen on the loop that created it, so nothing outside
a coroutine submitted to that loop may touch `Supervisor._client`.

Crossing back the other way goes through `src/gui/bridge.py`:
- `EngineSignals` is constructed on the GUI thread but has `emit()` called
  from the engine thread; Qt's automatic connection type queues delivery so
  slots run on the GUI thread.
- `watch(future, ...)` bounces a future's done-callback (which fires on the
  engine thread) onto the GUI thread through a signal.

Never call a widget method from engine code, and never block the GUI thread
on `future.result()` — the one deliberate exception is `Supervisor.shutdown()`
at quit, where the manifest and session must close cleanly before exit.

## Running it

```
pip install -r requirements-gui.txt
python -m src.gui                    # desktop app
python -m src.gui --selftest         # verify Qt/Telethon/watchdog load, then exit

pip install -r requirements.txt      # CLI only, no Qt
python -m src.main
```

## Testing

```
pip install -r requirements-dev.txt
pytest
```

`tests/fake_telegram.py` provides a `FakeClient` with async `send_file` /
`iter_messages` / `download_media` / `delete_messages` stand-ins, run against
a `tempfile` tree, asserting against `StateStore` — never against real
Telegram. Things worth covering for any change to `sync_engine.py`:
- ignore patterns exclude directories *and* files during `os.walk`
  (directory pruning happens via `dirnames[:]` filtering)
- unchanged files are not re-uploaded on a second scan
- a downloaded remote file does not get re-uploaded when the watcher
  subsequently fires on it (the echo-loop guard)
- reprocessing the same Telegram message id is a no-op
- a conflicted download does not overwrite locally-modified content

For GUI changes, `python tools/screenshot.py <dir> [--dark]` renders every
screen against a stub supervisor. A GUI that only imports cleanly has not
been checked at all.

## Known gotchas

- **0-byte files are skipped, not uploaded.** Telegram's upload API rejects
  empty files with `FilePartsInvalidError`. `_maybe_upload` special-cases
  `stat.st_size == 0`: records it in the manifest with `tg_message_id=None`
  so it isn't retried every scan, but never calls `send_file`. Don't remove
  this check.
- **`.driftgram-tmp` is in `INTERNAL_IGNORES`, unconditionally.**
  `download_message` writes `<name>.driftgram-tmp` beside the destination and
  renames on completion, so during a large download that file sits inside a
  watched folder. Without the ignore, the watcher uploads a half-written file.
  It is applied regardless of `use_default_ignores`, which users can turn off.
- **Deleted Telegram messages leave no history.** `iter_messages` simply
  won't show them, so retroactive delete-sync (a delete that happened while
  the tool was offline) isn't possible — a Telegram API limitation, not a bug.
  Both delete directions are live-only.
- **`events.MessageDeleted` must be registered without `chats=`.** Telegram
  omits the peer entirely for deletions in private chats and small groups
  (Saved Messages included), so `event.chat_id` is `None` and Telethon's
  `chats=` filter would silently drop every such event. `handle_remote_delete`
  instead identifies the file through `get_by_message_id` — safe because
  non-channel message ids are unique per account — and only compares
  `chat_id` when one is actually present (i.e. channel targets).
- **Telethon handlers are registered once per client, not per sync restart.**
  Re-adding them on every settings change would deliver each message N times.
  `Supervisor` tracks `_handler_target` and only rebuilds them when the target
  chat changes, since that value is baked into the `NewMessage` filter.
- **The remote-delete path has no `await` between `unlink()` and
  `state.delete()`.** That's deliberate: the watcher fires on the deletion we
  just performed, and `_handle_local_delete` must find no manifest record,
  or (with `delete_remote_on_local_delete` on) it would try to delete the
  already-deleted message. Don't insert an await between those two lines.
- **Conflict copies are deliberately left out of the manifest.** With
  `keep_both`, the row for `rel_path` still describes the user's own
  (diverged, unsynced) file and must not be overwritten with the downloaded
  copy's stats. The conflict copy is a genuinely new local file; the watcher
  picks it up and backs it up as one. Recording it with matching size/mtime
  would make `_maybe_upload` skip it forever.
- **Pause does not queue anything.** `handle_remote_message` returns *before*
  `_bump_offset` while paused, so the catch-up poll re-delivers those messages
  later; local changes are found by the rescan that resume performs. Don't
  "fix" this by buffering events.
- **Nested/overlapping roots aren't supported.** `_resolve_root_for_path`
  returns the first root a path resolves under. `config.root_conflict()`
  rejects them at the point the user picks a folder.
- **Windows path separators**: `_rel_path` always normalizes to forward
  slashes before matching ignore patterns or building captions, since
  `pathspec` expects gitignore-style forward-slash paths. Keep that
  normalization if you touch path handling.
- **Some Linux filenames can't exist on Windows.** `fsutil.unwritable_reason`
  skips them on download with an explanation rather than renaming — a rename
  would be a new local file, so the watcher would upload it under the new name
  and Telegram would end up holding both.
- **Ctrl+C shutdown (CLI)** relies on `client.run_until_disconnected()` raising
  `KeyboardInterrupt` up through `asyncio.run`. Cleanup happens in `main.py`'s
  `finally` block — don't add an early `return`/`sys.exit` in `run()` that
  would skip it.
- **Rate limits**: Telethon auto-handles Telegram's flood-wait backoff; a
  large first-time sync may pause and resume rather than fail. The upload path
  is also gated through an `asyncio.Semaphore(3)` in `SyncEngine._upload_lock`.
- **`pathspec` is pinned `<2.0`.** The `gitwildmatch` factory `IgnoreMatcher`
  uses is deprecated in pathspec 1.x and will be removed in 2.x. Changing it
  means changing matching semantics, so the pin is deliberate.

## Packaging

`python packaging/build.py --installer` builds for the platform it runs on.
There is no cross-compiling — PyInstaller freezes the local interpreter — so
CI uses a two-runner matrix.

- **onedir, not onefile.** onefile unpacks to a temp directory on every
  launch, which for a Qt app means a visible delay each time and a full
  antivirus scan on Windows. AppImage and .deb both want a directory anyway.
- **`opengl32sw.dll` is excluded** in the spec (~20 MB). It's Qt's software
  OpenGL fallback, only loaded to give QtQuick or QOpenGLWidget a context; a
  pure-widgets app paints through the raster engine.
- **`collect_submodules` for telethon and watchdog is required, not
  defensive.** Telethon builds its API layer by importing generated modules
  dynamically and watchdog picks its observer backend by name; neither is
  visible to PyInstaller's static analysis, and both fail only once frozen.
- **Linux packages are built on Ubuntu 22.04** because an AppImage still links
  against the host glibc.
- **The Windows installer is per-user** (`PrivilegesRequired=lowest`), so
  there's no UAC prompt. The app's data is per-user anyway.
- **Uninstalling never removes the data directory.** It holds the manifest and
  the Telegram session; deleting it would sign the user out and discard the
  record of everything already backed up.

## Security

`config.yaml` (which may contain `api_hash`) and the `*.session` file are
equivalent to being logged into the Telegram account this tool runs as — never
commit or share either. `.gitignore` excludes both, along with `manifest.db`.
On POSIX, `save_config` writes the config `0600` and the data directory `0700`.
