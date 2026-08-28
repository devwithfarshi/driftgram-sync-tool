# Driftgram

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Build](https://github.com/devwithfarshi/driftgram-sync-tool/actions/workflows/build.yml/badge.svg)](https://github.com/devwithfarshi/driftgram-sync-tool/actions/workflows/build.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![Platform: Windows | Linux](https://img.shields.io/badge/platform-Windows%20%7C%20Linux-lightgrey.svg)](#install)

Keep the folders you choose backed up to your own Telegram account — and get
changes back the other way too. Save a file on your PC and it appears in
Telegram. Send a file to Telegram from your phone and it lands in the right
folder on your PC.

Everything runs on your own machine, using your own Telegram account. Your
files go to **Saved Messages** by default: a private chat only you can see.
Nothing passes through anybody else's server, and there is no account to
create, no subscription, and no storage limit beyond Telegram's own.

There are two ways to use it:

| | |
|---|---|
| **Driftgram app** | A normal desktop app for Windows and Linux. Setup wizard, folder picker, tray icon, restore browser. **Start here.** |
| **Command line** | The original `python -m src.main`. Same engine, same config, no Qt required — handy on a headless machine. |

---

# Using the app

## Install

### Windows

1. Download `Driftgram-x.y.z-Setup.exe` from the
   [Releases page](../../releases).
2. Run it. It installs for your user only, so there is no administrator
   prompt.
3. Driftgram opens and walks you through setup.

> Windows SmartScreen may warn you the first time, because the installer
> isn't code-signed (a certificate costs a few hundred dollars a year).
> Click **More info → Run anyway** if you're happy to.

### Linux

**AppImage — works on any distribution, no installation:**

```bash
chmod +x Driftgram-x.y.z-x86_64.AppImage
./Driftgram-x.y.z-x86_64.AppImage
```

**Debian / Ubuntu / Mint:**

```bash
sudo apt install ./driftgram_x.y.z_amd64.deb
```

Then find Driftgram in your applications menu.

## Setting it up

The first run asks for four things. The only fiddly one is the second.

**1. Connect to Telegram.** Telegram requires every app that talks to it to be
registered — including this one, on your account. It's free and takes about a
minute. Driftgram gives you a button that opens the right page; you log in,
open *API development tools*, fill in any app name, and copy two values
(`api_id` and `api_hash`) back into Driftgram.

> Why not skip this? Because the alternative is shipping one shared key inside
> the app for everybody. If Telegram ever rate-limited or banned that key,
> every Driftgram user would break at once. Your own key can't be taken away
> by someone else's misuse.

**2. Sign in.** Phone number, then the login code Telegram sends you (it
arrives in the Telegram app if you're signed in elsewhere, otherwise by SMS),
then your two-step password if you have one.

**3. Choose folders.** Pick the folders you want backed up. Tick any of the
presets to skip things that aren't worth uploading — build output, video
files, logs.

**4. Preferences.** Whether to start at login, whether deletions should be
mirrored, and what to do if the same file changes in two places at once.

That's it. Driftgram starts backing up immediately and keeps running in the
notification area. The first pass through a large folder can take a while;
you can close the window and leave it to work.

## The app, page by page

**Status** — whether everything is backed up, what's transferring right now,
how many files and how much data. Pause and resume here.

**Folders** — add and remove folders, and edit each one's skip rules.
Removing a folder only stops watching it; the copies already in Telegram are
left alone.

**Activity** — a plain-language log of what has happened, with errors and
anything needing attention picked out in colour.

**Restore** — see everything Telegram is holding, including files you've since
deleted from your computer, and bring back whatever you need. Tick and click.

**Settings** — account, where backups go, conflict handling, deletion
mirroring, start-at-login, and a few advanced knobs.

## If the same file changes in both places

Say you edit a document on your PC while it's offline, and meanwhile a newer
copy of the same document arrives from your phone. Driftgram's default is
**keep both**: your version stays exactly where it is, and Telegram's copy is
saved next to it as `name (from Telegram).ext`. You get a notification, and
you decide which to keep.

You can change this in Settings to *let Telegram's copy replace mine* or
*always keep my copy*.

---

# How it works

- Every synced file is uploaded to Telegram as a **document** (never
  compressed) with a caption recording which folder and relative path it
  belongs to. That's how a file sent from your phone gets put back in the
  right place.
- A local SQLite file (`manifest.db`) remembers the size, timestamp and hash
  of every synced file. **Nothing is uploaded or downloaded unless its content
  differs from what the manifest recorded.** This is what stops the classic
  two-way-sync loop, where an upload reappears as a "new" remote file, gets
  downloaded, touches the local file, and gets uploaded again forever.
- A filesystem watcher catches local changes instantly, with a short debounce
  so an editor saving five times doesn't cause five uploads.
- A live Telegram listener catches new messages the moment they arrive; a
  periodic pass catches anything that happened while Driftgram was closed.

## Where Driftgram keeps its own files

| | Windows | Linux |
|---|---|---|
| Settings | `%APPDATA%\Driftgram\config.yaml` | `~/.config/driftgram/config.yaml` |
| Manifest, session, log | `%APPDATA%\Driftgram\` | `~/.local/share/driftgram/` |

Settings → *Driftgram's own files* → **Open this folder** takes you there.

Uninstalling does **not** delete these. If you reinstall, Driftgram picks up
where it left off instead of re-uploading everything.

If a `config.yaml` exists in the current working directory, Driftgram uses
that instead and keeps everything beside it — which is what makes a git
checkout self-contained. The installed app ignores this and always uses the
locations above.

## Worth knowing

- **File size cap.** Telegram allows about 2 GB per file, or 4 GB with
  Premium. Anything over your configured limit is skipped and logged, not
  silently dropped.
- **Deletion mirroring only works while Driftgram is running.** Telegram keeps
  no record of a deleted message, so a deletion that happened while the app
  was closed can never be detected afterwards.
- **Folders can't be nested inside one another.** Driftgram refuses to add a
  folder that sits inside — or contains — one you already sync, because a file
  would then belong to two of them.
- **Windows can't store some Linux filenames.** A file called `notes:2024.txt`
  or `aux.log` is legal on Linux and impossible on Windows. Driftgram skips
  those on the Windows side and tells you which, rather than renaming them
  behind your back.
- **Linux watch limits.** Linux caps how many folders one program may watch.
  On a very large tree you may need:
  ```bash
  sudo sysctl fs.inotify.max_user_watches=524288
  ```
  Driftgram detects this and tells you, rather than failing with a bare "no
  space left on device".
- **Rate limits.** Telegram may throttle a very large first sync. Driftgram
  pauses and resumes automatically.

## Security

- Your `config.yaml` contains your `api_hash`, and the `.session` file is
  equivalent to being logged into your Telegram account. **Never share
  either.** On Linux both are written owner-only.
- Driftgram talks to Telegram and nothing else. There is no telemetry, no
  update check, and no server belonging to anyone else.
- If you'd rather keep sync traffic out of Saved Messages, create a private
  channel and set it as the target in Settings.

---

# For developers

## Running from source

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1          # Windows PowerShell
source .venv/bin/activate            # Linux / macOS / Git Bash

pip install -r requirements-gui.txt  # or requirements.txt for the CLI only
python -m src.gui                    # desktop app
```

`python -m src.gui --selftest` checks that Qt, Telethon and watchdog all load
and exits — useful for verifying a build without opening a window.

## The command-line tool

Unchanged, and still fully supported. It needs no Qt.

```bash
pip install -r requirements.txt
cp .env.example .env                  # fill in TG_API_ID / TG_API_HASH
cp config.example.yaml config.yaml    # set your folders
python -m src.main
```

Credentials can live in `.env` or in `config.yaml` under `telegram:`. The
environment wins if both are set.

Restoring from the command line walks the full chat history:

```bash
python -m src.restore --list              # what's in Telegram, and what's missing
python -m src.restore                     # restore everything missing locally
python -m src.restore report.docx         # restore matching paths only
python -m src.restore report.docx --force # overwrite the local copy too
```

The app and the CLI share a manifest and a Telegram session, so only one may
run at a time — a lock file enforces this and says which process holds it.
The app does its restoring in-process, so it never needs stopping first.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

The suite runs against a `FakeClient` and a temp directory tree — no Telegram
account needed. It covers the manifest invariant (unchanged files aren't
re-uploaded, downloads don't bounce back up, reprocessing a message id is a
no-op), conflict handling, deletion in both directions, pause/resume, path
escaping, config round-tripping, filename portability, and the cross-process
lock.

`python tools/screenshot.py <dir> [--dark]` renders every screen to PNG
against a stub supervisor, so layout can be reviewed without a Telegram
account.

## Building installers

```bash
pip install -r requirements-dev.txt
python packaging/build.py --installer
```

Builds for whatever platform you run it on — PyInstaller freezes the local
interpreter, so there is no cross-compiling. Windows additionally needs
[Inno Setup 6](https://jrsoftware.org/isdl.php); Linux needs `dpkg-deb` for
the `.deb` and network access to fetch `appimagetool`.

`.github/workflows/build.yml` does both on a two-runner matrix and attaches
the results to a GitHub release when a `v*` tag is pushed. Linux packaging
runs on Ubuntu 22.04 deliberately: an AppImage still links against the host
glibc, so one built on a newer release won't start on an older one.

## Layout

```
src/config.py         Loads and saves settings; raises, never exits.
src/paths.py          Where config/manifest/session/log live per platform.
src/errors.py         Exceptions carrying messages meant to be read by a user.
src/events.py         EventBus: how the engine reports progress to a UI.
src/state.py          StateStore: the SQLite manifest. The source of truth.
src/ignore_rules.py   gitignore-style matching per folder.
src/fsutil.py         Cross-platform filename checks, conflict naming, sizes.
src/tg_client.py      Telethon upload/download and caption encode/decode.
src/local_watcher.py  watchdog wrapper with per-path debouncing.
src/sync_engine.py    The orchestrator. Owns the invariant.
src/main.py           CLI entry point.
src/restore.py        CLI restore tool.

src/app/              Running it as an application, with no Qt involved:
    supervisor.py       the engine on its own thread, driven from anywhere
    instance_lock.py    one process per data directory
    autostart.py        start at login (registry / XDG autostart)
    logging_setup.py    rotating log file

src/gui/              PySide6 desktop app:
    app.py              bootstrap, single instance, wiring
    onboarding.py       first-run setup wizard
    main_window.py      sidebar + pages
    page_*.py           status, folders, activity, restore, settings
    tray.py             notification-area icon
    bridge.py           engine thread -> Qt thread, safely
    theme.py, icons.py, widgets.py

packaging/            PyInstaller spec, icon generation, installers, build.py
tools/screenshot.py   Render every screen to PNG for review
```

## Contributing

Bug reports, documentation fixes and code are all welcome — see
[CONTRIBUTING.md](CONTRIBUTING.md) for how to get set up, how the test suite
works without a Telegram account, and the one invariant any change to the sync
engine has to preserve.

Please report security problems privately rather than as a public issue:
[SECURITY.md](SECURITY.md). Everyone taking part is expected to follow the
[Code of Conduct](CODE_OF_CONDUCT.md).

## Licence

[MIT](LICENSE) — do what you like with it, including commercially, as long as
the copyright notice comes along. No warranty.

Driftgram is not affiliated with Telegram. It uses
[Telethon](https://github.com/LonamiWebs/Telethon) to talk to Telegram's
public MTProto API with your own credentials.
