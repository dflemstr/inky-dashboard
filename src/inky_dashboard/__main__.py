import argparse
import asyncio
import io
import sys

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
        "-w",
        "--refresh-delay",
        type=float,
        default=60.0,
        help="Wait this many seconds before starting to refresh the page again",
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
            await page.evaluate(args.eval_js)
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
        while True:
            await render_frame(page, display, width, height)
            await asyncio.sleep(args.refresh_delay)


async def render_frame(page: Page, display, width: int, height: int):
    srcimg = Image.open(io.BytesIO(await page.screenshot()))
    img = Image.new(srcimg.mode, (width, height), (255, 255, 255))
    img.paste(srcimg, (0, 0))
    display.set_image(img)
    display.show()
