# Security policy

## Reporting a vulnerability

**Please don't open a public issue for a security problem.**

Use GitHub's private reporting instead:
[**Report a vulnerability**](https://github.com/devwithfarshi/driftgram-sync-tool/security/advisories/new).
That opens a private thread visible only to the maintainers.

Please include what an attacker can do, the steps to reproduce it, and the
version or commit you tested. A proof of concept helps, but a clear
description is enough — don't sit on a report because you haven't written an
exploit.

You should get an acknowledgement within a few days. Driftgram is maintained
by one person in their spare time, so there's no formal SLA; a fix for
something serious will be prioritised over everything else.

## Supported versions

Only the latest release. This is a small desktop tool with no server side and
no long-term support branches — fixes land in `main` and go out in the next
release.

## What's in scope

Driftgram runs entirely on the user's own machine and talks to Telegram and
nothing else. There's no backend, no telemetry, no update check and no
third-party service, so the interesting attack surface is local and
Telegram-side:

- **Credential exposure.** Anything that writes `api_hash`, the session file
  or its contents somewhere it shouldn't be — a log line, an error dialog, a
  crash report, a world-readable file. On POSIX, `save_config` writes the
  config `0600` and the data directory `0700`; a path that bypasses that is a
  bug.
- **Path traversal from a remote caption.** A Telegram caption chooses where a
  downloaded file lands. `_handle_remote_message_inner` resolves the
  destination and refuses to write outside a configured root, and
  `fsutil.unwritable_reason` rejects names the platform can't store. Any way
  around either check is a vulnerability, not a quirk.
- **Data loss.** A path that overwrites or deletes local content the manifest
  hasn't accounted for. The conflict policies exist so a user's own edits are
  never silently destroyed; a case where `keep_both` still loses data counts
  here.
- **Privilege or persistence surprises.** The Windows installer is per-user
  (`PrivilegesRequired=lowest`) and autostart writes to `HKCU\...\Run` or
  `~/.config/autostart`. Anything that escalates beyond the invoking user, or
  installs persistence the user didn't ask for, is in scope.

## What's not in scope

- **Someone with your session file can read your files.** That's what the
  session *is* — a Telegram login. Protecting it is the user's job, and the
  README and `.gitignore` say so in several places. "I gave someone my
  `.session` and they got in" is not a vulnerability.
- **Telegram's own limits and behaviour.** The ~2 GB / 4 GB file cap, flood
  waits, and the fact that deleted messages leave no history (so an offline
  deletion can never be detected afterwards) are platform constraints, not
  bugs.
- **Unsigned installers.** The Windows installer isn't code-signed, so
  SmartScreen warns on first run. A certificate costs a few hundred dollars a
  year; this is a documented trade-off, not an oversight.
- **Findings from a scanner with no demonstrated impact.** A dependency
  advisory for a code path Driftgram never calls is worth an ordinary issue,
  not a security report.

## A note for users

Your `config.yaml` may contain your `api_hash`, and your `*.session` file is
equivalent to being logged into your Telegram account. Never share, commit or
upload either. If you think one has leaked: sign the session out from Telegram
→ Settings → Devices, then reset your credentials at
[my.telegram.org/apps](https://my.telegram.org/apps).
