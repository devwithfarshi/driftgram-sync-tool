# CLAUDE.md

Guidance for Claude (or anyone else) working in this repository.

## What this is

**Driftgram Sync Tool** ("Driftgram") - a background tool that keeps chosen
folders on a Windows D: drive two-way synced with a Telegram chat, using a
personal Telegram account via Telethon (not the Bot API, to avoid the 50MB
bot upload cap). Runs as a long-lived Python process: a filesystem watcher
on one side, a Telegram client on the other, reconciled through a local
SQLite manifest.

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
src/config.py        Loads .env + config.yaml into typed dataclasses.
                      Owns DEFAULT_IGNORES (baked-in ignore patterns).

src/ignore_rules.py   IgnoreMatcher: gitignore-syntax matching per root,
                      combining global_ignore + per-root ignore + defaults.

src/state.py          StateStore: SQLite manifest (files table + meta
                      table). This is the source of truth for "have we
                      already synced this exact content?"

src/tg_client.py      Telethon upload/download primitives + caption
                      encode/decode. Caption format:
                          DRIFTGRAM
                          <root alias>
                          <relative path>
                      Every upload uses force_document=True so Telegram
                      never recompresses/transcodes the file.

src/local_watcher.py  watchdog wrapper with per-path debouncing
                      (threading.Timer), handing settled events back to
                      the asyncio loop via run_coroutine_threadsafe.

src/sync_engine.py    SyncEngine: the orchestrator. initial_scan() (startup
                      reconciliation), handle_local_change() (local →
                      remote), handle_remote_message() (remote → local),
                      poll_remote_loop() (catch-up polling as a backstop
                      to the live event listener).

src/main.py           Wires it together: Telethon login, initial scan,
                      starts one watchdog Observer per root, registers the
                      live NewMessage handler, runs the poll loop, handles
                      shutdown.
```

Data flow for a local edit: watchdog → debounce → `handle_local_change` →
`_maybe_upload` (manifest check → hash → upload) → manifest updated with new
`tg_message_id`.

Data flow for a remote file (e.g. sent from phone): Telethon `NewMessage`
event (live) or `poll_remote_loop` (backstop) → `handle_remote_message` →
manifest/echo checks → download → manifest updated with hash + message id.

## Running it

```
pip install -r requirements.txt
cp .env.example .env          # fill in TG_API_ID / TG_API_HASH
cp config.example.yaml config.yaml   # set your D: drive folders
python -m src.main
```

First run prompts for phone number / login code / 2FA in-terminal (Telethon
login), then saves a `.session` file and won't ask again.

## Testing

There's no test suite checked in yet. When adding one, mirror the approach
used during development: a `FakeClient` with async `send_file` /
`iter_messages` / `download_media` stand-ins, run against a `tempfile`
directory tree, and assert against `StateStore` contents — not against real
Telegram. Things worth covering for any change to `sync_engine.py`:
- ignore patterns correctly exclude directories *and* files during
  `os.walk` (directory pruning happens via `dirnames[:]` filtering)
- unchanged files are not re-uploaded on a second scan
- a downloaded remote file does not get re-uploaded when the watcher
  subsequently fires on it (the echo-loop guard)
- reprocessing the same Telegram message id is a no-op

## Known gotchas

- **0-byte files are skipped, not uploaded.** Telegram's upload API rejects
  empty files with `FilePartsInvalidError`. `_maybe_upload` special-cases
  `stat.st_size == 0`: records it in the manifest with `tg_message_id=None`
  so it isn't retried every scan, but never calls `send_file`. Don't remove
  this check.
- **Deleted Telegram messages leave no history.** `iter_messages` simply
  won't show them, so retroactive delete-sync (a delete that happened while
  the tool was offline) isn't reliable — this is a Telegram API limitation,
  not a bug. `delete_local_on_remote_delete` in config is a placeholder for
  a future live `events.MessageDeleted` handler; it isn't wired up yet.
  `delete_remote_on_local_delete` *does* work reliably since it's driven by
  the local filesystem watcher directly.
- **Nested/overlapping roots aren't supported.** `_resolve_root_for_path`
  returns the first root a path resolves under; don't configure one
  `roots:` entry as a subdirectory of another.
- **Windows path separators**: `_rel_path` always normalizes to forward
  slashes before matching ignore patterns or building captions, since
  `pathspec` expects gitignore-style forward-slash paths. Keep that
  normalization if you touch path handling.
- **Ctrl+C shutdown** relies on `client.run_until_disconnected()` raising
  `KeyboardInterrupt` up through `asyncio.run`. Cleanup (stopping observers,
  disconnecting, closing the DB) happens in `main.py`'s `finally` block —
  don't add an early `return`/`sys.exit` in `run()` that would skip it.
- **Rate limits**: Telethon auto-handles Telegram's flood-wait backoff; a
  large first-time sync of a big folder may pause and resume rather than
  fail. The upload path is also gated through an `asyncio.Semaphore(3)` in
  `SyncEngine._upload_lock` to avoid hammering the API with parallel sends.

## Security

`.env` and the `*.session` file are equivalent to being logged into the
Telegram account this tool runs as — never commit or share either
(`.gitignore` already excludes both, along with `manifest.db` and
`config.yaml` itself since it may contain personal folder paths).
