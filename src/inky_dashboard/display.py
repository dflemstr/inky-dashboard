import inspect
import io
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request

import inky
from inky.auto import auto
from PIL import Image

# Maps a friendly --type value to the concrete inky driver class. Boards without
# an ID EEPROM can't be auto-detected, so the driver must be selected explicitly.
DISPLAY_TYPES = {
    "phat": "InkyPHAT",
    "phat-ssd1608": "InkyPHAT_SSD1608",
    "what": "InkyWHAT",
    "what-ssd1683": "InkyWHAT_SSD1683",
    "impression-5.7": "Inky7Colour",
    "impression-7.3": "Inky_Impressions_7",
    "spectra-7.3": "InkyE673",
    "spectra-13.3": "InkyEL133UF1",
}


def make_display(display_type, color):
    if display_type == "auto":
        return auto()
    cls = getattr(inky, DISPLAY_TYPES[display_type])
    # Passed by keyword because the Impression/Spectra drivers take `resolution`
    # as their first positional argument, unlike pHAT/wHAT. The inky library's
    # own parameter is spelled `colour`.
    if color is not None:
        return cls(colour=color)
    return cls()


def push_frame(display, img, saturation: float):
    # Only the Impression/Spectra drivers accept a saturation argument; pHAT/wHAT
    # boards have a fixed palette and their set_image() takes no such keyword.
    # set_image() quantizes/dithers the full-color image to the panel palette.
    if "saturation" in inspect.signature(display.set_image).parameters:
        display.set_image(img, saturation=saturation)
    else:
        display.set_image(img)
    display.show()


def _send_heartbeat(url, host, etag, drawn):
    # Best-effort liveness ping. Proves this Pi is alive AND still successfully
    # fetching from the render host (a WiFi wedge makes fetches fail, so the
    # heartbeats stop and a watcher on the other end can alert). Never raises:
    # a heartbeat failure must not disturb the panel loop.
    payload = json.dumps(
        {"host": host, "etag": etag or "", "drawn": bool(drawn)}
    ).encode()
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10):
            pass
    except (urllib.error.URLError, OSError) as e:
        print(f"heartbeat failed ({e})", file=sys.stderr)


def run(args):
    # Thin client: no browser. Poll the serve instance's image with a conditional
    # GET (If-None-Match): the server replies 304 when nothing changed (cheap) and
    # 200 + the new PNG when it did. The panel is redrawn when the latest fetched
    # image differs from what is on it and --min-refresh-interval has elapsed. The
    # slow color e-ink refresh is the reason for the debounce; the panel keeps its
    # last image with no power, so a server outage just leaves the last frame up.
    display = make_display(args.type, args.color)
    url = args.server_url.rstrip("/") + "/image"
    # Optional liveness heartbeat. Resolve from --heartbeat-url or the
    # INKY_HEARTBEAT_URL env var (the latter lets the systemd unit enable it
    # without changing the command line). A heartbeat is POSTed on each
    # successful poll, throttled to --heartbeat-interval seconds.
    heartbeat_url = getattr(args, "heartbeat_url", None) or os.environ.get(
        "INKY_HEARTBEAT_URL"
    )
    heartbeat_interval = getattr(args, "heartbeat_interval", None)
    if heartbeat_interval is None:
        heartbeat_interval = float(os.environ.get("INKY_HEARTBEAT_INTERVAL", "60"))
    hostname = socket.gethostname()
    last_heartbeat = None
    seen_etag = None  # ETag of the latest image we have fetched
    seen_img = None  # the latest fetched image, decoded (may be un-drawn)
    drawn_etag = None  # ETag of the image currently on the panel
    last_refresh = None
    while True:
        req = urllib.request.Request(url)
        if seen_etag is not None:
            req.add_header("If-None-Match", seen_etag)
        fetch_ok = False
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                etag = resp.headers.get("ETag")
                data = resp.read()
            img = Image.open(io.BytesIO(data))
            img.load()
            seen_etag, seen_img = etag, img
            fetch_ok = True
        except urllib.error.HTTPError as e:
            if e.code == 304:  # 304 = unchanged, expected and fine
                fetch_ok = True
            else:
                print(
                    f"image poll failed (HTTP {e.code}); keeping last frame",
                    file=sys.stderr,
                )
        except (urllib.error.URLError, OSError) as e:
            print(f"image poll failed ({e}); keeping last frame", file=sys.stderr)

        now = time.monotonic()
        # Heartbeat on any successful fetch (200 or 304): it proves the Pi is
        # alive and still reaching the render host, independent of whether the
        # panel redrew (a quiet dashboard legitimately holds the same frame).
        if heartbeat_url and fetch_ok:
            if last_heartbeat is None or (now - last_heartbeat) >= heartbeat_interval:
                _send_heartbeat(
                    heartbeat_url, hostname, seen_etag, seen_etag == drawn_etag
                )
                last_heartbeat = now

        if seen_img is not None and seen_etag != drawn_etag:
            rate_ok = (
                last_refresh is None
                or (now - last_refresh) >= args.min_refresh_interval
            )
            if rate_ok:
                print("refreshing panel", file=sys.stderr)
                push_frame(display, seen_img, args.saturation)
                drawn_etag = seen_etag
                last_refresh = time.monotonic()

        time.sleep(args.poll_delay)
