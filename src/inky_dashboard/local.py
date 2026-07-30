import asyncio
import sys

from .display import make_display, push_frame
from .render import run_render


def run(args):
    # All-in-one: render the page in a local browser and push settled images
    # straight to the Inky panel on this same host (needs both the browser and
    # the display halves). Panel resolution comes from the driver.
    display = make_display(args.type, args.color)
    width, height = display.resolution

    def publish(img, sig):
        print("refreshing panel", file=sys.stderr)
        push_frame(display, img, args.saturation)

    asyncio.run(run_render(args, publish, width, height))
