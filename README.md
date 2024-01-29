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

Run with poetry, like `poetry run inky-dashboard`.  You might need to install playwright
browsers with `poetry run playwright install` the first time; this will download
self-contained headless browsers.

The program takes command-line flags, use `-h` for more info.  The only mandatory argument
is the URL to open, like so:

```
$ inky-dashboard https://google.com
```

## Installing

I'd recommend using `pipx` for installation.  You will need to install playwright browsers
in the relevant virtualenv that was created.

To install for your own user only:

```
$ pipx install <path to inky-dashboard>
-- OR --
$ pipx install git+https://github.com/dflemstr/inky-dashboard
$ source /home/dflemstr/.local/pipx/venvs/inky-dashboard/bin/activate
$ playwright install
```

You can also install the tool globally (for all users) using this hack:

```
$ sudo PIPX_HOME=/var/lib/pipx PIPX_BIN_DIR=/usr/local/bin pipx install <path to inky-dashboard>
-- OR --
$ sudo PIPX_HOME=/var/lib/pipx PIPX_BIN_DIR=/usr/local/bin pipx install git+https://github.com/dflemstr/inky-dashboard
$ sudo -s
# source /var/lib/pipx/venvs/inky-dashboard/bin/activate
# playwright install
```

This also lets you run the tool as a systemd-managed service:

```
$ cat /etc/systemd/system/inky-dashboard.service 
[Unit]
Description=Inky Dashboard

[Service]
Type=exec
ExecStart=/usr/local/bin/inky-dashboard <add args here>
Restart=on-failure

[Install]
WantedBy=default.target

$ sudo systemctl enable --now inky-dashboard.service
```
