# Driftgram landing page

A single static page. No framework, no bundler, no server — `index.html`, one
compiled stylesheet, one script.

## Running it

`web/dist/styles.css` is committed, so the page works as-is:

```bash
cd web
python -m http.server 4173     # then open http://localhost:4173
```

Only touch npm if you're changing the styling:

```bash
npm install
npm run dev      # rebuild dist/styles.css on change
npm run build    # minified, before committing
```

Tailwind v4 keeps its configuration in CSS rather than a JS file — the tokens
live in the `@theme` block at the top of `src/input.css`.

## Layout

```
index.html          the page
src/input.css       Tailwind entry + @theme tokens + a few component classes
dist/styles.css     compiled output - committed, do not edit by hand
js/main.js          platform-aware download, screenshot tabs, the loop diagram, reveals
assets/             the mark, the screenshots, the social card
```

## Where things come from

Nothing visual here is invented. Colours are the dark palette from
[`../docs/BRAND.md`](../docs/BRAND.md), which documents `src/gui/theme.py`.
Green (`#3DBE6C`) and amber (`#F2B33D`) are the app's own tray status colours,
used with the same meanings: *settled* and *needs attention*.

`assets/` holds copies of files generated elsewhere in the repo. Regenerate at
the source, then copy them here:

| Asset | Made by |
|---|---|
| `mark-192.png`, `mark-512.png` | `src.gui.icons.write_png` — the same function behind the app and installer icons |
| `status.png`, `folders-dark.png`, `activity.png`, `restore.png`, `wizard-credentials.png` | `python tools/screenshot.py` |
| `social-preview.png` | `python tools/make_brand_assets.py` |

Per `BRAND.md`, the mark is never traced or redrawn — it's rendered from the
app's drawing code, so it can't drift from the icon users actually see.

## Things worth keeping

- **The version and download URLs appear in three places**: the hero button
  fallback `href`, the three cards in the download section, and `VERSION` in
  `js/main.js`. There's no build step to thread one value through, so update
  all three when a release ships.
- **Content must not depend on JS to be visible.** The scroll reveals hide
  their content under `html.js` only, and that class is set by an inline script
  in `<head>`. A bare `.reveal { opacity: 0 }` would blank the whole page if
  the script failed to load.
- **The loop diagram has a 600px floor** (`min-w-[600px]` inside an
  `overflow-x-auto` wrapper). Scaled below that its labels fall under 7px and
  stop being readable, so narrow screens swipe it instead.
- **The diagram animates only while on screen**, via IntersectionObserver, and
  stops when the tab is hidden.
- **`prefers-reduced-motion` is honoured**: reveals resolve immediately and the
  diagram steps through its states on a timer without travel.
- The hero button is relabelled from the visitor's platform, and falls back to
  "See all downloads" on macOS and mobile rather than offering a build that
  doesn't exist.

## Deploying

Any static host, with `web/` as the root. Two notes:

- The `og:image` and canonical URL in `index.html` are relative and point at
  `devwithfarshi.github.io/driftgram-sync-tool`. Change them to the real
  origin — link unfurls need absolute URLs.
- Fonts come from Google Fonts over the network. Self-host them in `assets/` if
  you'd rather the page make no third-party requests, which would match what
  the desktop app does.
