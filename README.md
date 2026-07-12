# `inky-dashboard`

A simple tool for rendering web pages to E-Ink® displays that are supported by the
[inky](https://github.com/pimoroni/inky) library.  More than likely you would run this
on a Raspberry Pi.

The tool spawns a long-lived browser using the `playwright` library, and takes screenshots
at a regular interval to render to the display.  Hence, you can easily test your webpage
in an ordinary browser before pointing this tool towards it.

The tool will by default not ever refresh the page; it is assumed that the page will
dynamically update, using for example Javascript or video.  I might implement refreshing
if I ever end up needing that, though...

## Usage

This project uses [uv](https://docs.astral.sh/uv/) for dependency management and builds.

Run with uv, like `uv run inky-dashboard`.  You will need to install the playwright
browsers with `uv run playwright install` the first time; this will download
self-contained headless browsers.

The program takes command-line flags, use `-h` for more info.  The only mandatory argument
is the URL to open, like so:

```
$ uv run inky-dashboard https://google.com
```

Useful flags:

- `-s, --scale` scales the page onto the panel; values below `1.0` "zoom out" so more
  content fits (the viewport is enlarged and rendered down onto the display).
- `-t, --type` selects the display driver explicitly (e.g. `impression-7.3`), for panels
  without an ID EEPROM that `auto` detection can't identify. `-c, --colour` sets the
  colour for pHAT/wHAT boards.
- `--wait-selector` waits for a CSS selector to appear before rendering, instead of relying
  on a fixed `--render-delay`. It pierces open shadow DOM, so `ha-card` works for Home
  Assistant dashboards.
- `--eval` runs a JavaScript expression in the page once after it loads, e.g. to tweak the
  layout or hide chrome.

### Example: a Home Assistant dashboard

Home Assistant loads its cards asynchronously and reserves a left margin for the docked
sidebar.  This waits for real content, hides the sidebar via HA's own sidebar-dock event,
and scales the whole dashboard onto the panel:

```
$ inky-dashboard \
    --wait-selector ha-card \
    --eval "document.querySelector('home-assistant').dispatchEvent(new CustomEvent('hass-dock-sidebar',{detail:{dock:'always_hidden'},bubbles:true,composed:true}))" \
    --scale 0.72 \
    http://homeassistant.local/dashboard-inky/0
```

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

This also lets you run the tool as a systemd-managed service:

```
$ cat /etc/systemd/system/inky-dashboard.service
[Unit]
Description=Inky Dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=exec
Environment=UV_TOOL_DIR=/var/lib/uv/tools
ExecStart=/usr/local/bin/inky-dashboard --wait-selector ha-card --scale 0.72 http://homeassistant.local/dashboard-inky/0
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target

$ sudo systemctl enable --now inky-dashboard.service
```

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
