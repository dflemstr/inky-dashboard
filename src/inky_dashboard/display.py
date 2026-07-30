import inspect
import io
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


def _fetch(url: str, timeout: float):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.read()


def run(args):
    # Thin client: no browser. Poll the serve instance's cheap /hash endpoint;
    # when it changes (and --min-refresh-interval has elapsed), fetch the full
    # image and draw it on the panel. The color e-ink refresh itself is the slow
    # part, so the panel is only redrawn when the published image actually
    # changed. The panel keeps its last image with no power, so a server outage
    # simply leaves the last good dashboard in place.
    display = make_display(args.type, args.color)
    base = args.server_url.rstrip("/")
    last_etag = None
    last_refresh = None
    while True:
        try:
            etag = _fetch(f"{base}/hash", timeout=10).decode().strip()
        except (urllib.error.URLError, OSError) as e:
            print(f"hash poll failed ({e}); keeping last frame", file=sys.stderr)
            time.sleep(args.poll_delay)
            continue

        now = time.monotonic()
        if etag and etag != last_etag:
            rate_ok = (
                last_refresh is None
                or (now - last_refresh) >= args.min_refresh_interval
            )
            if rate_ok:
                try:
                    data = _fetch(f"{base}/image", timeout=30)
                    img = Image.open(io.BytesIO(data))
                    img.load()
                except (urllib.error.URLError, OSError) as e:
                    print(
                        f"image fetch failed ({e}); keeping last frame", file=sys.stderr
                    )
                    time.sleep(args.poll_delay)
                    continue
                print("refreshing panel", file=sys.stderr)
                push_frame(display, img, args.saturation)
                last_etag = etag
                last_refresh = time.monotonic()

        time.sleep(args.poll_delay)
