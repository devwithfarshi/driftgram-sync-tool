## What this changes

<!-- One or two sentences. Link the issue if there is one: Fixes #123 -->

## Why

<!-- What problem does it solve? If it's a bug fix, what was the cause? -->

## How I verified it

<!--
Say what you actually did. "Ran pytest" plus "created a 2 GB file in a watched
folder and confirmed it was skipped with a message" is exactly right.
-->

## Checklist

- [ ] `pytest` passes
- [ ] `python -m src.gui --selftest` exits cleanly
- [ ] No credentials in the diff — no `api_hash`, `.env`, `config.yaml`, or `*.session`
- [ ] One concern per PR

### If this touches `src/sync_engine.py`

- [ ] Every new upload/download path checks the manifest **before** acting and updates it **before** returning
- [ ] Added or extended a test in `tests/test_sync_engine.py` covering the change
- [ ] I read the relevant entries in [`CLAUDE.md`](../CLAUDE.md#known-gotchas) — several of the odd-looking lines in that file are load-bearing

### If this touches the GUI

- [ ] Ran `python tools/screenshot.py <dir>` and `--dark`, and the affected screens still look right
- [ ] No widget calls from engine code; nothing crosses threads except through `src/gui/bridge.py`
- [ ] Before/after screenshots attached below

## Screenshots

<!-- Delete this section if the change isn't visual. -->
