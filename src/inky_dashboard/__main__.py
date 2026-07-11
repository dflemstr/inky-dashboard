import argparse
import asyncio
import io
import sys

import inky
from inky.auto import auto
from PIL import Image
from playwright.async_api import Page, async_playwright

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


def make_display(display_type, colour):
    if display_type == "auto":
        return auto()
    cls = getattr(inky, DISPLAY_TYPES[display_type])
    # colour is passed by keyword because the Impression/Spectra drivers take
    # `resolution` as their first positional argument, unlike pHAT/wHAT.
    if colour is not None:
        return cls(colour=colour)
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
        "--colour",
        "--color",
        dest="colour",
        default=None,
        help="Panel colour for pHAT/wHAT boards (e.g. black, red, yellow); "
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
    args = parser.parse_args()
    print(f"running with {vars(args)}", file=sys.stderr)
    asyncio.run(async_main(args))


async def async_main(args):
    display = make_display(args.type, args.colour)
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
