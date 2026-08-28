# Driftgram brand

Everything here is already in the code. This file exists so anything made
*outside* the app — a screenshot annotation, a social post, a landing page —
matches what people see once it's running, instead of drifting from it.

The two sources of truth:

| What | Where |
|---|---|
| The mark, the gradient, the status colours | [`src/gui/icons.py`](../src/gui/icons.py) |
| The light and dark palettes | [`src/gui/theme.py`](../src/gui/theme.py) |

If this document and the code ever disagree, **the code is right** and this
file needs updating.

## Name

**Driftgram**, one word, capital D, no space, no hyphen. Not "DriftGram",
not "Drift Gram".

The repository is `driftgram-sync-tool`; the product is Driftgram.

In-app tagline, shown under the wordmark in the sidebar:

> Folders ↔ Telegram

Longer form, for anywhere with room for a sentence:

> Your folders, backed up to your own Telegram account.

## The mark

A sync loop: an almost-closed ring with an arrowhead, white, on a rounded tile
filled with the brand gradient.

It's drawn rather than shipped as a file — `_draw_mark` in `src/gui/icons.py`
paints it with QPainter, which is why it stays crisp at 16 px in a system tray
and at 512 px in an installer. Every proportion is relative to the size, so
there is exactly one definition:

| Element | Value |
|---|---|
| Tile corner radius | 23% of size |
| Gradient direction | Top-left → bottom-right |
| Ring inset from edge | 28% of size |
| Ring stroke width | 10.5% of size, round caps, min 1.5 px |
| Ring arc | Starts at 75°, sweeps −300° — open at the top right |
| Arrowhead | 20% of size, at the open end, pointing along travel |
| Ring and arrowhead colour | White at 94% opacity (`alpha 240`) |

The gap in the ring is deliberate and load-bearing: at 16 px a closed ring
turns into a solid blob, and the arrowhead is what says *sync* rather than
*loading*.

### Getting the mark at any size

Don't trace it. Render it:

```python
from src.gui.icons import app_pixmap
app_pixmap(512).save("mark-512.png")
```

`packaging/make_icons.py` uses the same function for the `.ico` and the
hicolor PNG set, and `tools/make_brand_assets.py` for the social card and
the README lockup.

## Colour

### Brand gradient

The only gradient in the identity. Use it for the tile, and sparingly as an
accent — never as a full-bleed background.

| Stop | Hex |
|---|---|
| Top / start | `#38B6F1` |
| Bottom / end | `#1C82C4` |

`#1C82C4` doubles as the light-theme accent, `#38B6F1` as the dark-theme
accent. That's why the tile reads correctly in both.

### Light palette

| Role | Hex |
|---|---|
| Background | `#FFFFFF` |
| Surface | `#F7F9FB` |
| Surface (alt) | `#EEF2F6` |
| Border | `#DFE5EC` |
| Text | `#111C29` |
| Muted text | `#5C6B7F` |
| Accent | `#1C82C4` |
| Accent text | `#FFFFFF` |
| Accent (soft) | `#E7F2FA` |
| Success | `#1E8E4E` |
| Warning | `#B4740B` |
| Danger | `#C42B30` |

### Dark palette

| Role | Hex |
|---|---|
| Background | `#15181C` |
| Surface | `#1C2026` |
| Surface (alt) | `#242A31` |
| Border | `#313943` |
| Text | `#E9EEF4` |
| Muted text | `#9AA7B6` |
| Accent | `#38B6F1` |
| Accent text | `#0A1218` |
| Accent (soft) | `#1B2C38` |
| Success | `#4ED084` |
| Warning | `#E3A93B` |
| Danger | `#F0666B` |

Driftgram follows the system setting; neither theme is the "real" one.

### Status colours

The dot on the tray icon. Nine run states, and **colour is never the only
carrier** — the tooltip says the same thing in words, for anyone who can't
rely on it.

| State | Hex |
|---|---|
| Idle (up to date) | `#3DBE6C` |
| Syncing / Scanning | `#38B6F1` |
| Connecting / Login required | `#F2B33D` |
| Paused / Offline / Stopped | `#8E97A3` |
| Error | `#E5484D` |

The dot is painted on a white disc first. That's not decoration: several of
these are blues that would otherwise vanish into the tile behind them.

## Typography

The app sets no font family — it takes the platform's UI font, so it looks
native on Windows and on Linux rather than slightly foreign on both. Brand
assets follow the same principle with a fallback stack:

```
Segoe UI Variable Display, Segoe UI, Inter, DejaVu Sans, Arial
```

Weights in use: 400 body, 500 labels, 600 section titles, 700 headings and
numbers. Nothing lighter than 400 — it fails at small sizes on Windows.

## Voice

The audience includes people who have never opened a terminal. The README, the
UI strings and the error messages are all written for them, and brand copy
should match:

- **Say what happened, in words a person would use.** "Folder not found:
  E:/Photos. It may be on a drive that isn't connected." Not "ENOENT".
- **No jargon where a plain word exists.** "Backed up", not "synchronised
  upstream".
- **Never claim more than is true.** Telegram's limits, the unsigned installer
  and the live-only deletion mirroring are all stated plainly rather than
  glossed over.
- **Sentence case** for headings and buttons. Not Title Case.
- Prefer "backed up" for the local → Telegram direction; the app says "Back up
  now", not "Sync now".

## Assets

Everything in `docs/images/`, all generated:

| File | What it's for |
|---|---|
| `social-preview.png` | 1280×640. GitHub Settings → Social preview; also what X, Slack and Discord unfurl. |
| `logo-lockup-light.png` | README header on a light theme. |
| `logo-lockup-dark.png` | README header on a dark theme. |
| `status.png`, `restore.png`, `activity.png`, `folders-dark.png`, `wizard-credentials.png` | README screenshots. |

Regenerate after changing the mark or the palette, and commit the result:

```bash
python tools/make_brand_assets.py     # card + lockups
python tools/screenshot.py docs/images-tmp        # screenshots, then copy the ones in use
```

Run both with a real display. Under `QT_QPA_PLATFORM=offscreen` some setups
find no fonts and render every label as empty boxes.

## Don't

- **Don't redraw or regenerate the mark.** Render it from `app_pixmap`. A
  hand-traced or AI-generated copy drifts from the icon in the tray, and
  nobody notices until the two are side by side.
- **Don't flood a surface with the gradient.** It's the tile and an accent.
- **Don't restyle the tile** — no drop shadows, no outline, no changing the
  23% radius, no rotating the ring.
- **Don't put the wordmark on the gradient.** Tile on background, wordmark
  beside it.
- **Don't use Telegram's logo or wordmark**, or blue-on-white styling that
  implies endorsement. Driftgram is not affiliated with Telegram, and the
  README says so. Naming Telegram in plain text is fine.
- **Don't give the mark less clear space than half its width** on any side.
