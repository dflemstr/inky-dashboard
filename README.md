# `inky-dashboard`

A simple tool for rendering web pages to E-Ink® displays that are supported by the
[inky](https://github.com/pimoroni/inky) library.  More than likely you would run this
on a Raspberry Pi.

It spawns a long-lived browser using the `playwright` library and takes screenshots at a
regular interval.  The page is loaded once and left running, so it updates itself
dynamically (via JavaScript, websockets, video, etc.).  The image is only redrawn on the
panel when it has actually **changed** and has **settled** — see [Refreshing](#refreshing).
This matters because color E-Ink panels (Impression/Spectra) only support a single
full-screen refresh that takes tens of seconds and flashes; there is no partial update, so
redrawing only when something really changed avoids needless flashing and panel wear.

## Modes

Rendering a modern web page needs a real browser, which is heavy for a small Pi (a Pi Zero
can barely fit one Chromium).  So the tool can **split rendering from display** across two
hosts, or do both on one:

- **`local`** — render *and* draw on the same host (the classic single-box setup).
  Needs the browser and the Inky. `pip install inky-dashboard[local]`.
- **`serve`** — run the browser on a capable host (a NAS, your Home Assistant server, …),
  render + settle, and serve the finished panel image over HTTP.  No Inky needed.
  `pip install inky-dashboard[serve]`.
- **`display`** — run on the Raspberry Pi: fetch the image from a `serve` instance and push
  it to the panel.  **No browser** — a tiny footprint, so even a Pi Zero is comfortable.
  `pip install inky-dashboard[display]`.

The `serve`/`display` split is the recommended setup for constrained panels: the browser's
memory pressure moves off the Pi entirely, and (when the render host also hosts the page,
e.g. Home Assistant) rendering happens over localhost, so it's fast and never hits flaky
Wi-Fi.

## Usage

This project uses [uv](https://docs.astral.sh/uv/) for dependency management and builds.
Install the playwright browsers once on any host that renders (`local`/`serve`) with
`uv run playwright install`.

```
# all-in-one on one host:
$ inky-dashboard local https://google.com

# split across two hosts:
$ inky-dashboard serve   https://google.com --width 1600 --height 1200   # on the render host
$ inky-dashboard display http://render-host:8080                         # on the Pi
```

`serve` exposes `GET /image` (the current PNG, with an `ETag`) and `GET /hash`; the
`display` client polls `/hash` and only fetches `/image` when it changes.

Useful flags (`local`/`serve` share the render flags; `local`/`display` share the panel
flags):

- `-s, --scale` scales the page onto the panel; values below `1.0` "zoom out" so more
  content fits (the viewport is enlarged and rendered down onto the display).
- `--supersample` renders at a multiple of the panel resolution and downscales (Lanczos)
  for anti-aliasing. At `1` (default) text has hard, aliased edges (font smoothing is
  disabled, since on a limited palette the quantizer would dither AA grays into speckle);
  at e.g. `2` it renders 2x with smoothing on and shrinks, giving smoother edges at the
  cost of more CPU/RAM per frame.
- `-t, --type` selects the display driver explicitly (e.g. `impression-7.3`), for panels
  without an ID EEPROM that `auto` detection can't identify. `-c, --color` sets the
  color for pHAT/wHAT boards.
- `--wait-selector` waits for a CSS selector to appear before rendering, instead of relying
  on a fixed `--render-delay`. It pierces open shadow DOM, so `ha-card` works for Home
  Assistant dashboards.
- `--saturation` (Impression/Spectra panels) sets the color saturation used when quantizing
  to the panel's palette; higher is more vivid. Theme colors that match the resulting palette
  render without dithering.
- `--locale` sets the browser locale (e.g. `en-GB`), which drives locale-aware formatting
  such as 12h/24h clocks and date formats on pages that follow the browser locale.
- `--eval` runs a JavaScript expression in the page once after it loads, e.g. to tweak the
  layout or hide chrome.
- `--poll-delay`, `--settle-checks`, `--refresh-delay` control the refresh model
  (see [Refreshing](#refreshing)).

### Refreshing

Color E-Ink panels have no partial-update mode: every refresh redraws the whole screen,
takes tens of seconds, and flashes.  So instead of redrawing on a timer, the tool:

1. screenshots the page every `--poll-delay` seconds (default `2`) and hashes the result;
2. waits until the image stops changing — identical across `--settle-checks` consecutive
   polls (default `2`) — so it never captures a mid-transition frame (animations, values
   ticking over, a chart re-drawing);
3. refreshes the panel only when a *settled* image differs from what is already displayed.

A static page is therefore never redrawn.  `--refresh-delay` (default `300`) is an upper
bound on staleness: if the page changes continuously and never settles, the panel is
refreshed anyway after that many seconds so it can't get arbitrarily out of date.

`--min-refresh-interval` (default `0`) sets a lower bound — a floor between physical
refreshes.  A settled change that arrives sooner is held until the interval elapses, then
the latest state is drawn.  This coalesces frequently-changing content (a live power
reading, say) into fewer refreshes instead of redrawing every few seconds.  (The panel's
own multi-second refresh already rate-limits somewhat; this extends that deliberately.)

### Riding out connection blips

A transient outage (the backend restarting, a wifi stall) should not paint a broken page.
When the source page can't be captured — a screenshot times out, or (for Home Assistant)
the frontend reports its websocket down — the tool **holds the last good frame** on the
panel rather than refreshing to a "Connection lost" popover or default chrome, and it does
not crash.  After `--reload-after` such polls in a row (default `3`) it reloads the page to
recover a wedged connection, re-applying `--eval` and injected styles.  Because the panel
keeps its last image with no power, the dashboard simply stays put until real content is
back.

### Example: a Home Assistant dashboard

Home Assistant loads its cards asynchronously and reserves a left margin for the docked
sidebar.  This waits for real content, hides the sidebar via HA's own sidebar-dock event,
and scales the whole dashboard onto the panel.  Rendering on the HA host itself is ideal —
the page loads over localhost, so it's fast and immune to Wi-Fi stalls:

```
# on the render host (e.g. the Home Assistant server):
$ inky-dashboard serve \
    --width 1600 --height 1200 --scale 1.44 \
    --wait-selector ha-card \
    --eval "document.querySelector('home-assistant').dispatchEvent(new CustomEvent('hass-dock-sidebar',{detail:{dock:'always_hidden'},bubbles:true,composed:true}))" \
    http://localhost:8123/dashboard-inky/0

# on the Raspberry Pi driving the panel:
$ inky-dashboard display http://homeassistant.local:8080 --saturation 0.0
```

To do everything on one box instead, swap `serve …` for `local …` (and drop the
`display` command).

## Installing

Use `uv tool` to install the command onto your `PATH`.  You will need to install the
playwright browsers afterwards.

To install for your own user only:

```
$ uv tool install <path to inky-dashboard>
-- OR --
$ uv tool install git+https://github.com/dflemstr/inky-dashboard
$ uv tool run --from inky-dashboard playwright install
```

You can also install the tool globally (for all users) by pointing uv at a shared
location:

```
$ sudo UV_TOOL_DIR=/var/lib/uv/tools UV_TOOL_BIN_DIR=/usr/local/bin \
    uv tool install git+https://github.com/dflemstr/inky-dashboard
$ sudo UV_TOOL_DIR=/var/lib/uv/tools \
    uv tool run --from inky-dashboard playwright install
```

Pass the extra you need, e.g. `git+https://github.com/dflemstr/inky-dashboard#egg=inky-dashboard[display]`
on the Pi (no browser) or `[serve]` on the render host.

This also lets you run the tool as a systemd-managed service.  On the Raspberry Pi, the
`display` client is tiny (no browser):

```
$ cat /etc/systemd/system/inky-dashboard.service
[Unit]
Description=Inky Dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=exec
Environment=UV_TOOL_DIR=/var/lib/uv/tools
ExecStart=/usr/local/bin/inky-dashboard display http://homeassistant.local:8080 --saturation 0.0
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target

$ sudo systemctl enable --now inky-dashboard.service
```

The render side (`serve`) is best packaged as an add-on/container on the render host; the
`--eval` value contains spaces, so wrap it in double quotes in a unit file, otherwise
systemd splits it into multiple arguments.

The `--eval` value contains spaces, so wrap it in double quotes in the unit file if you use
it, otherwise systemd splits it into multiple arguments.

## Development

Install the project with its dev dependencies and set up the browsers:

```
$ uv sync
$ uv run playwright install
```

Lint and format with [ruff](https://docs.astral.sh/ruff/):

```
$ uv run ruff check
$ uv run ruff format
```
