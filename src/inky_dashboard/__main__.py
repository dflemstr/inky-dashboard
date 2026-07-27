import argparse
import asyncio
import hashlib
import inspect
import io
import sys
import time

import inky
from inky.auto import auto
from PIL import Image
from playwright.async_api import Page, async_playwright
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

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


def main():
    parser = argparse.ArgumentParser(
        prog="inky-dashboard",
        description="Show a webpage on a Pimoroni inky-compatible E-Ink display",
    )
    parser.add_argument("url", help="URL of webpage to render")
    parser.add_argument(
        "-t",
        "--type",
        choices=["auto", *DISPLAY_TYPES],
        default="auto",
        help="Inky display model; 'auto' (default) reads the board EEPROM. Set "
        "explicitly for boards without an EEPROM (e.g. some Impression panels).",
    )
    parser.add_argument(
        "-c",
        "--color",
        "--colour",
        dest="color",
        default=None,
        help="Panel color for pHAT/wHAT boards (e.g. black, red, yellow); "
        "ignored by Impression/Spectra panels",
    )
    parser.add_argument(
        "-s",
        "--scale",
        type=float,
        default=1.0,
        help="Scale the webpage by this factor",
    )
    parser.add_argument(
        "--poll-delay",
        type=float,
        default=2.0,
        help="How often (seconds) to screenshot the page and check for changes. "
        "The panel is only physically refreshed when the image actually changes "
        "and has settled (see --settle-checks), so this can be short.",
    )
    parser.add_argument(
        "--settle-checks",
        type=int,
        default=2,
        help="Require the rendered image to be identical across this many "
        "consecutive polls before refreshing the panel. Debounces mid-transition "
        "frames (animations, values ticking) so the slow e-ink refresh only fires "
        "once the page has stopped changing.",
    )
    parser.add_argument(
        "-w",
        "--refresh-delay",
        type=float,
        default=300.0,
        help="Upper bound (seconds) on panel staleness: if the image differs from "
        "what is on the panel but never settles, force a refresh after this long. "
        "Bounds latency for pages that change continuously.",
    )
    parser.add_argument(
        "-r",
        "--render-delay",
        type=float,
        default=20.0,
        help='Wait this many seconds for the webpage to "settle" (run JS etc) before first render',
    )
    parser.add_argument(
        "--wait-selector",
        default=None,
        help="Before rendering, wait until an element matching this CSS selector "
        "appears (pierces open shadow DOM). E.g. 'ha-card' for Home Assistant. "
        "This waits for real content instead of relying on --render-delay alone.",
    )
    parser.add_argument(
        "--wait-timeout",
        type=float,
        default=60.0,
        help="Maximum seconds to wait for --wait-selector before rendering anyway",
    )
    parser.add_argument(
        "--saturation",
        type=float,
        default=0.5,
        help="Color saturation (0.0-1.0) for the e-ink palette quantization; "
        "higher is more saturated. Only used by Impression/Spectra panels.",
    )
    parser.add_argument(
        "--locale",
        default=None,
        help="Browser locale (e.g. 'en-GB') for the page. Affects locale-aware "
        "formatting such as 12h/24h clocks and date/number formats; e.g. a page "
        "that follows the browser locale will render 24-hour times under 'en-GB'.",
    )
    parser.add_argument(
        "--eval",
        dest="eval_js",
        default=None,
        help="Run this JavaScript expression in the page once after it loads "
        "(after --wait-selector), before the first render. Useful for tweaking "
        "layout, e.g. hiding chrome. Wrap multi-statement code in an IIFE.",
    )
    args = parser.parse_args()
    print(f"running with {vars(args)}", file=sys.stderr)
    asyncio.run(async_main(args))


async def async_main(args):
    display = make_display(args.type, args.color)
    width, height = display.resolution

    display.set_border(inky.WHITE)

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(
            viewport={
                "width": int(width * (1 / args.scale)),
                "height": int(height * (1 / args.scale)),
            },
            color_scheme="light",
            is_mobile=False,
            device_scale_factor=args.scale,
            locale=args.locale,
        )
        page = await context.new_page()
        await page.goto(args.url)
        if args.wait_selector:
            try:
                await page.wait_for_selector(
                    args.wait_selector, timeout=args.wait_timeout * 1000
                )
            except PlaywrightTimeoutError:
                print(
                    f"warning: {args.wait_selector!r} did not appear within "
                    f"{args.wait_timeout}s; rendering anyway",
                    file=sys.stderr,
                )
        if args.eval_js:
            # Retry: right after load the target elements may not exist yet
            # (e.g. an auth redirect still settling). A failing --eval must not
            # crash the render loop, so treat a persistent failure as a warning.
            for attempt in range(3):
                try:
                    await page.evaluate(args.eval_js)
                    break
                except Exception as e:
                    if attempt == 2:
                        print(f"warning: --eval failed: {e}", file=sys.stderr)
                    else:
                        await asyncio.sleep(2)
        await asyncio.sleep(args.render_delay)
        # Do this after the page has fully rendered, since it might
        # do redirects or whatever during the render_delay
        await page.add_style_tag(
            content="""
            *,
            *::before,
            *::after {
                -moz-animation: none !important;
                -moz-transition: none !important;
                animation: none !important;
                caret-color: transparent !important;
                transition: none !important;
                font-smooth: never;
                -webkit-font-smoothing : none;
            }
        """
        )
        # Small arbitrary wait to ensure CSS styles are applied after the above
        # TODO: make configurable
        await asyncio.sleep(0.5)
        await render_loop(page, display, width, height, args)


async def render_loop(page: Page, display, width: int, height: int, args):
    # The Impression/Spectra panels only support a full, ~30s flashing refresh —
    # there is no partial/damage-region update — so every refresh is expensive and
    # wears the panel. Rather than redraw on a fixed timer, poll the page often and
    # only refresh when the rendered image has actually changed AND settled (stopped
    # changing for --settle-checks polls). This skips mid-transition frames and
    # never redraws a static page. --refresh-delay caps how stale the panel may get
    # if the page changes continuously and never settles.
    #
    # Every refresh is gated on the settled image differing from what is currently
    # on the panel (`sig != panel_sig`), so a burst of changes that ends up back on
    # the already-displayed image triggers no refresh at all — the churn just lands
    # in the `else` branch below and nothing is pushed.
    panel_sig = None  # signature of the image currently on the panel
    prev_sig = None  # signature seen on the previous poll
    stable = 0  # consecutive polls with an unchanged image
    pending_since = None  # when the current (un-pushed) change first appeared
    while True:
        img = await capture_frame(page, width, height)
        sig = hashlib.sha256(img.tobytes()).digest()
        stable = stable + 1 if sig == prev_sig else 1
        prev_sig = sig

        if sig != panel_sig:
            if pending_since is None:
                pending_since = time.monotonic()
            settled = stable >= args.settle_checks
            forced = (time.monotonic() - pending_since) >= args.refresh_delay
            if settled or forced:
                print(
                    f"refreshing panel ({'settled' if settled else 'forced'})",
                    file=sys.stderr,
                )
                push_frame(display, img, args.saturation)
                panel_sig = sig
                pending_since = None
        else:
            pending_since = None

        await asyncio.sleep(args.poll_delay)


async def capture_frame(page: Page, width: int, height: int):
    srcimg = Image.open(io.BytesIO(await page.screenshot()))
    img = Image.new(srcimg.mode, (width, height), (255, 255, 255))
    img.paste(srcimg, (0, 0))
    return img


def push_frame(display, img, saturation: float):
    # Only the Impression/Spectra drivers accept a saturation argument; pHAT/wHAT
    # boards have a fixed palette and their set_image() takes no such keyword.
    if "saturation" in inspect.signature(display.set_image).parameters:
        display.set_image(img, saturation=saturation)
    else:
        display.set_image(img)
    display.show()
