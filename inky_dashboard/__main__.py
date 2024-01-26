import argparse
import asyncio
import sys
import inky
from inky.auto import auto as Inky
from PIL import Image
import tempfile
from playwright.async_api import async_playwright


def main():
    parser = argparse.ArgumentParser(
        prog="inky-dashboard",
        description="Show a webpage on a Pimoroni inky-compatible E-Ink display",
    )
    parser.add_argument("url", help="URL of webpage to render")
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
    display = Inky()
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


async def render_frame(page, display, width, height):
    with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
        await page.screenshot(path=tmp.name)
        srcimg = Image.open(tmp.name)
    img = Image.new(srcimg.mode, (width, height), (255, 255, 255))
    img.paste(srcimg, (0, 0))
    display.set_image(img)
    display.show()
