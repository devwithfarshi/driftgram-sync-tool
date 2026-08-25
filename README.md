# Driftgram Sync Tool

Driftgram is a background tool that keeps chosen folders on your D: drive
two-way synced with a Telegram chat (by default, your own "Saved Messages").
Runs on your own machine using your personal Telegram account, so there's no
50MB bot upload limit.

## How it works

- Every synced file is uploaded to Telegram as a **document** (never
  compressed) with a hidden caption that records which folder ("alias") and
  relative path it belongs to. That's how a file sent from your phone gets
  put back in the right place on your PC.
- A local SQLite file (`manifest.db`) remembers the last-known hash of every
  synced file. This is what stops the classic two-way-sync loop
  (upload → shows back up as "new" → re-download → re-upload → ...):
  nothing gets acted on unless its content actually differs from what the
  manifest last recorded.
- A filesystem watcher (`watchdog`) catches local changes instantly (with a
  short debounce so editors don't trigger 5 uploads while saving).
- A live Telegram event listener catches new messages the moment they
  arrive; a periodic reconciliation pass (`poll_interval_seconds`) catches
  anything that happened while the tool was offline.

## Setup

1. **Install Python 3.10+** if you don't have it.

2. **Get Telegram API credentials** (one-time, free): go to
   <https://my.telegram.org/apps>, log in with the Telegram account you want
   Driftgram to use, and create an app (any name/platform works). You'll get
   an `api_id` and `api_hash`.

3. **Create and activate a virtual environment** (recommended, so
   Driftgram's dependencies stay out of your global Python install). From
   the project folder:

   PowerShell:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

   Command Prompt (cmd.exe):
   ```bat
   python -m venv .venv
   .venv\Scripts\activate.bat
   ```

   Git Bash / WSL / Linux / macOS:
   ```bash
   python -m venv .venv
   source .venv/bin/activate      # Git Bash on Windows: source .venv/Scripts/activate
   ```

   Your prompt should now be prefixed with `(.venv)`. If PowerShell refuses
   to run the activate script ("running scripts is disabled on this
   system"), allow it for your user once:
   ```powershell
   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
   ```

   `.venv/` is already in `.gitignore`. To leave the environment later, run
   `deactivate`. You need to activate it again in every new terminal before
   running Driftgram (or call the interpreter directly - see below).

4. **Install dependencies** (with the venv active):
   ```
   pip install -r requirements.txt
   ```

5. **Configure credentials:** copy `.env.example` to `.env` and fill in
   `TG_API_ID` / `TG_API_HASH`.

6. **Configure your folders:** copy `config.example.yaml` to `config.yaml`
   and edit the `roots:` list to point at the D: drive folders you want
   synced, plus any per-folder ignore patterns.

7. **First run:**
   ```
   python -m src.main
   ```
   The first time, Telethon will ask for your phone number, the login code
   Telegram sends you, and your 2FA password if you have one set. After
   that it saves a session file (`<TG_SESSION_NAME>.session`) and won't ask
   again.

Leave it running in a terminal (or set it up as a scheduled/background task
- see below) and it will keep syncing in both directions.

## Configuration reference (`config.yaml`)

```yaml
telegram:
  target: "me"   # "me" = Saved Messages, or a channel/group username/id

sync:
  poll_interval_seconds: 20
  delete_remote_on_local_delete: false
  delete_local_on_remote_delete: false
  max_file_size_mb: 1900
  use_default_ignores: true
  debounce_seconds: 2.0

roots:
  - path: "D:/Projects"
    alias: "projects"        # stable id tagged onto every message - don't change once set
    ignore:
      - "node_modules/"
      - "*.log"

global_ignore:
  - "*.iso"
```

Ignore patterns use `.gitignore` syntax. With `use_default_ignores: true`
(the default), common junk is already excluded: `.git`, `node_modules`,
`__pycache__`, `.next`, `dist`, `build`, `venv`/`.venv`, `Thumbs.db`,
`desktop.ini`, `*.tmp`, Office lock files (`~$*`), and Windows system
folders.

## Restoring a file you deleted locally

With the default `delete_remote_on_local_delete: false`, deleting a local
file leaves its Telegram copy untouched - but the running tool won't bring
it back, because it only inspects messages newer than the offset it has
already processed. To pull files back down, stop Driftgram (both share one
Telegram session and one manifest) and run the restore tool, which scans the
whole chat history:

```
python -m src.restore --list        # see every synced path in Telegram, and which are missing on disk
python -m src.restore              # download everything missing locally
python -m src.restore report.docx  # restore just the paths matching a fragment or glob
python -m src.restore report.docx --force   # overwrite the local copy with Telegram's
```

Restored files are written into the manifest with their real size, mtime and
hash, so when you restart Driftgram the watcher sees them as already synced
and doesn't re-upload them. Add `--include-ignored` to restore a path that
now matches one of your ignore patterns.

## Limitations, worth knowing

- **Telegram's file size cap** is ~2GB for regular accounts (~4GB with
  Telegram Premium). Files over `max_file_size_mb` are skipped and logged,
  not silently dropped.
- **Deletion sync only works while Driftgram is running.** Both directions
  (`delete_remote_on_local_delete` and `delete_local_on_remote_delete`) are
  driven by live events - the filesystem watcher one way, Telegram's
  `MessageDeleted` update the other. Telegram leaves no trace of a deleted
  message in chat history, so a deletion that happened while the tool was
  stopped can never be detected afterwards; it will simply be ignored on the
  next start. Delete things with the tool running if you want the other side
  to follow.
- **Nested/overlapping sync roots aren't supported** - keep your configured
  folders separate from each other.
- **Rate limits:** Telegram may briefly throttle very rapid bulk uploads
  (e.g. syncing a huge folder for the first time). Telethon handles the
  standard flood-wait backoff automatically; it'll just pause and resume.

## Security notes

- `.env` and the `*.session` file are equivalent to being logged into your
  Telegram account. Never commit them or share them. The included
  `.gitignore` already excludes both.
- Consider using a **dedicated private Telegram channel** instead of Saved
  Messages as the `target` if you want to keep the sync traffic visually
  separate from your normal chat history.

## Running Driftgram in the background on Windows

Simplest option: use Task Scheduler to run
`pythonw -m src.main` (note `pythonw`, not `python`, to avoid a console
window) at login, working directory set to this project folder. For a first
run, use `python -m src.main` in a normal terminal so you can complete the
phone/code login prompt interactively.

If you set up a virtual environment, point Task Scheduler at the venv's
interpreter by absolute path instead of relying on activation - e.g.
program `D:\driftgram-sync-tool\.venv\Scripts\pythonw.exe` with arguments
`-m src.main` and "Start in" set to `D:\driftgram-sync-tool`. The same
trick works from any terminal without activating: `.venv\Scripts\python -m
src.main`.
