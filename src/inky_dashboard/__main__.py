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

# JS probe: is Home Assistant's websocket currently connected? Returns True or
# False when it can be determined, or None if not (page still loading, or not a
# HA page at all). Used to avoid painting HA's "Connection lost. Reconnecting..."
# popover (and the default chrome it falls back to) onto the panel: while the
# socket is down we hold the last good frame instead of refreshing to a broken
# one. `hass.connection` is home-assistant-js-websocket's Connection, whose
# `connected` getter flips to false the moment the socket drops.
HA_CONNECTED_PROBE = """(() => {
  try {
    const ha = document.querySelector('home-assistant');
    const c = ha && ha.hass && ha.hass.connection;
    return c ? !!c.connected : null;
  } catch (e) { return null; }
})()"""


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
        "--supersample",
        type=float,
        default=1.0,
        help="Render at this multiple of the panel resolution and downscale "
        "(Lanczos) for anti-aliasing. E.g. 2 renders at 2x then shrinks, giving "
        "smooth text edges instead of the aliased edges you get at 1. Costs more "
        "CPU/RAM per frame. When >1, font anti-aliasing is left enabled.",
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
        "--min-refresh-interval",
        type=float,
        default=0.0,
        help="Minimum seconds between physical panel refreshes. A settled change "
        "that arrives sooner is held until this interval elapses, then the latest "
        "state is drawn. Coalesces frequently-changing content (e.g. live power "
        "readings) into fewer refreshes. Should be <= --refresh-delay. Default 0 "
        "(refresh as soon as a change settles).",
    )
    parser.add_argument(
        "--reload-after",
        type=int,
        default=3,
        help="After this many consecutive unusable polls (Home Assistant's socket "
        "reported down, or a screenshot timing out), reload the page to recover a "
        "wedged connection. Until then the last good frame is held on the panel so "
        "a transient outage never paints the reconnect popover. Default 3.",
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
    parser.add_argument(
        "--inject-css",
        default=None,
        help="Path to a CSS file whose contents are injected into the page after "
        "load. Handy for a self-contained @font-face (data: URI) plus the "
        "font-family CSS variables a framework reads (e.g. Home Assistant's "
        "--ha-font-family-*), which cascade into shadow DOM where a plain "
        "'* { font-family }' rule cannot reach.",
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
            # Render at scale * supersample device pixels per CSS pixel; the
            # layout still follows --scale (the viewport above is unchanged),
            # while --supersample only increases pixel density for downscaling.
            device_scale_factor=args.scale * args.supersample,
            locale=args.locale,
        )
        page = await context.new_page()
        await load_and_prepare(page, args)
        await render_loop(page, display, width, height, args)


async def load_and_prepare(page: Page, args):
    # Navigate to the target URL and (re-)apply all render-time setup: wait for
    # real content, run --eval, freeze animations, disable AA, inject CSS. This
    # runs once at startup and again whenever the render loop reloads to recover
    # a lost connection, so the sidebar-dock/eval and injected styles are always
    # re-applied after a reload (they live on the document, which a reload wipes).
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
    # Freeze animations/transitions so screenshots are stable.
    style = """
        *,
        *::before,
        *::after {
            -moz-animation: none !important;
            -moz-transition: none !important;
            animation: none !important;
            caret-color: transparent !important;
            transition: none !important;
        }
    """
    # Disable font anti-aliasing ONLY when not supersampling: at 1x, AA
    # produces gray edges the palette quantizer dithers into speckle, so
    # hard (aliased) edges look cleaner. When supersampling we render dense
    # with AA on and downscale, giving smooth edges — so keep AA there.
    if args.supersample <= 1.0:
        style += """
        *,
        *::before,
        *::after {
            font-smooth: never;
            -webkit-font-smoothing: none;
        }
        """
    await page.add_style_tag(content=style)
    # Inject user CSS last so it can override the page (e.g. swap the font).
    if args.inject_css:
        try:
            with open(args.inject_css) as f:
                await page.add_style_tag(content=f.read())
        except OSError as e:
            print(f"warning: --inject-css failed: {e}", file=sys.stderr)
    # Small arbitrary wait to ensure CSS styles are applied after the above
    # TODO: make configurable
    await asyncio.sleep(0.5)


async def render_loop(page: Page, display, width: int, height: int, args):
    # The Impression/Spectra panels only support a full, ~30s flashing refresh —
    # there is no partial/damage-region update — so every refresh is expensive and
    # wears the panel. Rather than redraw on a fixed timer, poll the page often and
    # only refresh when the rendered image has actually changed AND settled (stopped
    # changing for --settle-checks polls). This skips mid-transition frames and
    # never redraws a static page. --refresh-delay caps how stale the panel may get
    # if the page changes continuously and never settles, and --min-refresh-interval
    # sets a floor so frequently-changing content can't trigger back-to-back
    # refreshes.
    #
    # Every refresh is gated on the settled image differing from what is currently
    # on the panel (`sig != panel_sig`), so a burst of changes that ends up back on
    # the already-displayed image triggers no refresh at all — the churn just lands
    # in the `else` branch below and nothing is pushed.
    #
    # Resilience: a poll is "unusable" when Home Assistant reports its socket down
    # or a screenshot times out (e.g. a wifi blip stalls the transfer). Those polls
    # do NOT push and do NOT crash — the last good frame stays on the panel so the
    # "Connection lost" popover / default chrome never lands on e-ink. After
    # --reload-after such polls in a row, the page is reloaded to recover.
    panel_sig = None  # signature of the image currently on the panel
    prev_sig = None  # signature seen on the previous poll
    stable = 0  # consecutive polls with an unchanged image
    pending_since = None  # when the current (un-pushed) change first appeared
    last_refresh = None  # when the last physical refresh finished
    fails = 0  # consecutive unusable polls (disconnected / capture error)
    while True:
        # Hold the last good frame while HA explicitly reports its socket down,
        # so the reconnect popover is never captured. `None` (can't tell) falls
        # through to a normal capture — only an explicit False gates.
        try:
            connected = await page.evaluate(HA_CONNECTED_PROBE)
        except Exception:
            connected = None

        img = None
        if connected is False:
            print(
                f"HA connection down; holding last frame ({fails + 1})",
                file=sys.stderr,
            )
        else:
            try:
                img = await capture_frame(page, width, height)
            except PlaywrightTimeoutError:
                print(
                    f"screenshot timed out; holding last frame ({fails + 1})",
                    file=sys.stderr,
                )

        if img is None:
            # Unusable poll: recover by reloading once we've seen enough in a row.
            fails += 1
            if fails >= args.reload_after:
                print("reloading page to recover", file=sys.stderr)
                try:
                    await load_and_prepare(page, args)
                except Exception as e:
                    print(f"warning: reload failed: {e}", file=sys.stderr)
                fails = 0
            await asyncio.sleep(args.poll_delay)
            continue
        fails = 0

        sig = hashlib.sha256(img.tobytes()).digest()
        stable = stable + 1 if sig == prev_sig else 1
        prev_sig = sig
        now = time.monotonic()

        if sig != panel_sig:
            if pending_since is None:
                pending_since = now
            settled = stable >= args.settle_checks
            forced = (now - pending_since) >= args.refresh_delay
            rate_ok = (
                last_refresh is None
                or (now - last_refresh) >= args.min_refresh_interval
            )
            if (settled or forced) and rate_ok:
                print(
                    f"refreshing panel ({'settled' if settled else 'forced'})",
                    file=sys.stderr,
                )
                push_frame(display, img, args.saturation)
                panel_sig = sig
                pending_since = None
                last_refresh = time.monotonic()
        else:
            pending_since = None

        await asyncio.sleep(args.poll_delay)


async def capture_frame(page: Page, width: int, height: int):
    srcimg = Image.open(io.BytesIO(await page.screenshot()))
    # With --supersample the screenshot is larger than the panel; downscale it
    # with a high-quality filter for anti-aliasing before quantizing.
    if srcimg.size != (width, height):
        srcimg = srcimg.resize((width, height), Image.LANCZOS)
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
