# Contributing to Driftgram

Thanks for taking a look. Bug reports, documentation fixes and code are all
welcome, and you don't need to ask permission before opening an issue.

If you're planning something large — a new sync target, a rewrite of the
engine, a second UI — please open an issue first so we can agree on the shape
before you spend a weekend on it.

## Before you touch anything: never commit credentials

Three files in a working checkout are equivalent to being logged into your
Telegram account:

| File | Why it matters |
|---|---|
| `.env` | holds `TG_API_ID` / `TG_API_HASH` |
| `config.yaml` | the setup wizard writes `api_hash` here, plus your real folder paths |
| `*.session` | Telethon's session **is** the login — no password needed to reuse it |

All three are in `.gitignore`, along with `manifest.db`, the log and the lock
file. Please don't relax those rules, and run `git status` before committing if
you've been testing against a real account.

If you ever do commit one by accident: revoke it first (sign the session out
from Telegram → Settings → Devices, and reset the hash at
[my.telegram.org/apps](https://my.telegram.org/apps)), then worry about
rewriting history. A rotated credential in a public commit is harmless; a live
one is not.

## Getting set up

```bash
git clone https://github.com/devwithfarshi/driftgram-sync-tool.git
cd driftgram-sync-tool

python -m venv .venv
.venv\Scripts\Activate.ps1           # Windows PowerShell
source .venv/bin/activate             # Linux / macOS / Git Bash

pip install -r requirements-dev.txt   # everything, including Qt and pytest
```

You do **not** need a Telegram account to work on this. The test suite runs
against a fake client, and `tools/screenshot.py` renders every GUI screen
against a stub. An account is only needed if you want to run the real thing.

To run it for real, follow the setup in the [README](README.md#setting-it-up).
A `config.yaml` in the repo root makes the checkout self-contained — the
manifest, session and log all land beside it instead of in your user profile.

## The one rule that matters

**Nothing acts on a file unless its content differs from what the manifest
last recorded.**

The manifest (`manifest.db`, via `src/state.py`) is what stops the classic
two-way-sync loop: upload → the file reappears as a Telegram message → gets
"downloaded" → touches the local file → the watcher sees it → re-uploads →
forever.

Every code path that uploads or downloads **must** check the manifest before
acting and update it immediately after, before returning. In `sync_engine.py`
that's two guards working together:

- **Local → remote**: `_maybe_upload` compares `(size, mtime)` first, falls
  back to SHA-256 only when those differ, and skips the upload when the hash
  matches what's on record.
- **Remote → local**: `_handle_remote_message_inner` checks
  `get_by_message_id` (catches echoes of our own uploads) and compares the
  incoming message id against the manifest's recorded id for that path
  (catches redundant re-delivery) before downloading.

If a change to `sync_engine.py` makes those checks awkward, the change is
probably wrong. It isn't an optimization — it's the correctness mechanism for
the whole tool.

[`CLAUDE.md`](CLAUDE.md) documents the architecture, the threading model, and
about a dozen non-obvious gotchas (why 0-byte files are skipped, why
`MessageDeleted` is registered without `chats=`, why there's deliberately no
`await` between `unlink()` and `state.delete()`). Read the relevant section
before changing engine or GUI internals — most of those entries exist because
the obvious approach was tried and broke something.

## Tests

```bash
pytest
```

`tests/fake_telegram.py` provides a `FakeClient` with async `send_file` /
`iter_messages` / `download_media` / `delete_messages` stand-ins, run against a
`tempfile` tree and asserted against a real `StateStore`. Never write a test
that talks to Telegram.

Any change to `sync_engine.py` should keep these covered, and add to them:

- ignore patterns exclude directories *and* files during `os.walk`
- unchanged files aren't re-uploaded on a second scan
- a downloaded remote file isn't re-uploaded when the watcher then fires on it
- reprocessing the same message id is a no-op
- a conflicted download doesn't overwrite locally-modified content
- a caption whose path escapes the root is refused

## GUI changes

A GUI that only imports cleanly has not been checked at all.

```bash
python tools/screenshot.py out/          # light theme
python tools/screenshot.py out/ --dark   # dark theme
```

That renders every screen to PNG against a stub supervisor, so you can review
layout without an account. Attach before/after images to any PR that changes
appearance.

Two constraints from the threading model:

- Never call a widget method from engine code. Cross back through
  `src/gui/bridge.py` — `EngineSignals` for events, `watch()` for futures.
- Never block the GUI thread on `future.result()`. The single deliberate
  exception is `Supervisor.shutdown()` at quit.

Telethon is not thread-safe, so nothing outside a coroutine submitted to the
supervisor's loop may touch `Supervisor._client`.

## Style

Match the file you're editing. Broadly:

- Comments explain *why*, not *what*. The existing ones are load-bearing
  documentation of decisions — if you remove a comment, you're claiming its
  reasoning no longer applies.
- Recoverable failures raise a `DriftgramError` (`src/errors.py`) carrying a
  message a non-technical person can read. Nothing in the library may call
  `sys.exit()` — a GUI has to show a dialog and survive.
- Paths normalize to forward slashes (`_rel_path`) before matching ignore
  patterns or building captions, because `pathspec` expects gitignore-style
  paths. Keep that if you touch path handling.
- `pathspec` is pinned `<2.0` deliberately: the `gitwildmatch` factory is
  deprecated in 1.x and removed in 2.x, and changing it changes matching
  semantics.

## Pull requests

1. Branch off `main`.
2. Keep it to one concern. Two unrelated fixes are two PRs.
3. `pytest` passes, and `python -m src.gui --selftest` exits cleanly.
4. Describe what you changed and how you verified it. "Tested manually" is
   fine as long as you say what you did.

CI runs the suite and the self-test on Windows and Ubuntu, then builds the
installers, so a PR that breaks packaging is caught before merge.

## Building installers

```bash
python packaging/build.py --installer
```

Builds for whatever platform you run it on — PyInstaller freezes the local
interpreter, so there's no cross-compiling. Windows also needs
[Inno Setup 6](https://jrsoftware.org/isdl.php); Linux needs `dpkg-deb` and
network access to fetch `appimagetool`.

Linux packaging runs on Ubuntu 22.04 in CI on purpose: an AppImage still links
against the host glibc, so one built on a newer release won't start on an
older one.

## Licence

By contributing you agree your work is released under the
[MIT Licence](LICENSE) that covers this project.
