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

[Service]
Type=exec
Environment=UV_TOOL_DIR=/var/lib/uv/tools
ExecStart=/usr/local/bin/inky-dashboard <add args here>
Restart=on-failure

[Install]
WantedBy=default.target

$ sudo systemctl enable --now inky-dashboard.service
```

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
