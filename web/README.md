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
src/input.css       Tailwind entry + @theme tokens + the component classes
dist/styles.css     compiled output - committed, do not edit by hand
js/main.js          platform-aware download, GitHub counts, mobile menu,
                    scroll spy, screenshot tabs, the loop diagram, the
                    sideways-scroll affordance, reveals
assets/             the mark, the screenshots, the social card
```

The page runs: hero (copy + a real screenshot) → four numbers → what it does
in three steps → the sync-loop diagram → features → screenshots → setup →
next to a cloud drive → limits → FAQ → download → closing CTA.

The three-step section exists because the diagram doesn't answer "what is
this". It explains loop prevention, which only matters to someone who already
knows what the tool is for. Anything explaining the product in plain language
has to come before it.

## Where things come from

Nothing visual here is invented. Colours are the dark palette from
[`../docs/BRAND.md`](../docs/BRAND.md), which documents `src/gui/theme.py`.
Green (`#4ED084`) and amber (`#E3A93B`) are the app's own status colours, used
with the same meanings: *settled* and *needs attention*.

`assets/` holds copies of files generated elsewhere in the repo. Regenerate at
the source, then copy them here:

| Asset | Made by |
|---|---|
| `mark-192.png`, `mark-512.png` | `src.gui.icons.write_png` — the same function behind the app and installer icons |
| `app-*.png` | `python tools/screenshot.py <dir> --dark` |
| `social-preview.png` | `python tools/make_brand_assets.py` |

**The screenshots are all rendered `--dark`**, because the page is dark and a
light screenshot dropped into it looks like a mistake rather than a theme.
`app-status.png` is `window-status-dark.png`, `app-wizard.png` is
`wizard-credentials-dark.png`, and the rest map by name. If you re-render
them, re-render the whole set — a mixed light/dark strip is what this
replaced.

Per `BRAND.md`, the mark is never traced or redrawn — it's rendered from the
app's drawing code, so it can't drift from the icon users actually see.

## Things worth keeping

- **The version and the file sizes are written out in several places.** There
  is no build step to thread one value through, so a release means editing all
  of them: the hero button's fallback `href`; the featured panel's `href`,
  `data-dl-file` and `data-dl-size`; the three rows under *Every build* (each
  `href`, file name and size); the two links to the release tag; the `chmod`
  line; the `<h2>`; and `VERSION` plus the `size` on each record in `BUILDS`
  in `js/main.js`. Grep for the old version number and read every hit.
- **The download section leads with one build and lists the rest.** The
  featured panel ships the Windows copy in the markup — the larger audience,
  and the same fallback the hero button uses without JS — and `fillPanel()`
  rewrites every field when the visitor is on Linux. Someone on macOS or a
  phone gets `NO_BUILD`: no "recommended" badge, no file name, no download
  arrow, no second button, and the primary action becomes the CLI, because
  offering a `.exe` to a Mac is worse than admitting there isn't one. The
  index below the panel always lists all three, so no build is ever reachable
  only through platform detection.
- **Content must not depend on JS to be visible.** The scroll reveals hide
  their content under `html.js` only, and that class is set by an inline script
  in `<head>`. A bare `.reveal { opacity: 0 }` would blank the whole page if
  the script failed to load. Same reasoning behind the swipe hints, which ship
  visible in the markup and are removed by JS when they aren't needed, and the
  FAQ, which is `<details>` rather than a scripted accordion.
- **The screenshot panel is aspect-locked** (`.win-shot`, `940 / 680`, with
  `object-fit: contain`). The wizard shot is 660×560 where the main window is
  940×680, so without the fixed ratio, switching tabs would resize the panel
  and shove the page around under the reader.
- **The loop diagram has a 600px floor** (`min-w-[600px]` inside an
  `overflow-x-auto` wrapper). Scaled below that its labels fall under 7px and
  stop being readable, so narrow screens swipe it instead — which is what the
  fade on the right edge and the "swipe the diagram" note are for.
- **The diagram's paused frame shows the outcome, not the origin.** `restFrame`
  in `main.js` puts a downloaded file beside the folder, an uploaded one beside
  Telegram, and a refused one dimmed against the manifest. It has to agree with
  the caption printed underneath it, or the still frame contradicts the words.
- **The diagram animates only while on screen**, via IntersectionObserver, and
  stops when the tab is hidden, when the pointer or keyboard focus is inside
  the figure, or when the reader presses pause. Those are four independent
  flags reconciled in one `sync()` — so a scroll can't undo an explicit pause.
- **`prefers-reduced-motion` is honoured**: reveals resolve immediately and the
  diagram steps through its states on a timer without travel.
- **The screenshot tabs use a roving tabindex** — one stop in the page's tab
  order, arrows/Home/End to move between them, which is the ARIA tabs pattern.
- The hero button is relabelled from the visitor's platform, and falls back to
  "See all downloads" on macOS and mobile rather than offering a build that
  doesn't exist.

## Known trade-off

Card and panel borders use `--color-line` (`#313943`), which is about 1.4:1
against the surfaces either side of it — below the 3:1 that WCAG 1.4.11 asks
of a boundary that identifies a control. That value is the app's own border
token, and the site is not allowed to drift from `BRAND.md`. It's tolerable
because no control depends on its border alone: tabs carry a text label at
7.3:1 and signal selection with a cyan border (7.7:1), a raised fill, and a
brighter label at once. Every piece of text on the page clears AA, the worst
being the dark button label on the gradient's far end at 4.6:1.

## Deploying

Any static host, with `web/` as the root. Two notes:

- The `og:image` and canonical URL in `index.html` are relative and point at
  `devwithfarshi.github.io/driftgram-sync-tool`. Change them to the real
  origin — link unfurls need absolute URLs.
- Fonts come from Google Fonts over the network. Self-host them in `assets/` if
  you'd rather the page make no third-party requests, which would match what
  the desktop app does.
