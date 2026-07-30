import argparse
import sys


def _add_render_args(p):
    """Browser/render knobs shared by `serve` and `local`."""
    p.add_argument("url", help="URL of the web page to render")
    p.add_argument(
        "-s",
        "--scale",
        type=float,
        default=1.0,
        help="Scale the web page by this factor",
    )
    p.add_argument(
        "--supersample",
        type=float,
        default=1.0,
        help="Render at this multiple of the panel resolution and downscale "
        "(Lanczos) for anti-aliasing. Cheap on a real server; at 1 (default) font "
        "anti-aliasing is left disabled so text stays crisp on a limited palette.",
    )
    p.add_argument(
        "--poll-delay",
        type=float,
        default=2.0,
        help="How often (seconds) to screenshot the page and check for changes.",
    )
    p.add_argument(
        "--settle-checks",
        type=int,
        default=2,
        help="Require the rendered image to be identical across this many "
        "consecutive polls before publishing it. Debounces mid-transition frames.",
    )
    p.add_argument(
        "-w",
        "--refresh-delay",
        type=float,
        default=300.0,
        help="Upper bound (seconds) on staleness: publish the current image even "
        "if it never settles, after this long.",
    )
    p.add_argument(
        "--reload-after",
        type=int,
        default=3,
        help="Reload the page after this many consecutive unusable polls "
        "(content missing, socket down, or screenshot timeout).",
    )
    p.add_argument(
        "-r",
        "--render-delay",
        type=float,
        default=20.0,
        help="Wait this many seconds for the page to settle before first render.",
    )
    p.add_argument(
        "--wait-selector",
        default=None,
        help="Wait until an element matching this CSS selector appears (pierces "
        "open shadow DOM) before rendering. E.g. 'ha-card' for Home Assistant.",
    )
    p.add_argument(
        "--wait-timeout",
        type=float,
        default=120.0,
        help="Maximum seconds to wait for --wait-selector before rendering anyway.",
    )
    p.add_argument(
        "--locale",
        default=None,
        help="Browser locale (e.g. 'en-GB') for locale-aware formatting.",
    )
    p.add_argument(
        "--eval",
        dest="eval_js",
        default=None,
        help="Run this JavaScript expression in the page once after it loads.",
    )
    p.add_argument(
        "--inject-css",
        default=None,
        help="Path to a CSS file injected into the page after load.",
    )


def _add_panel_args(p):
    """Inky panel knobs shared by `local` and `display`."""
    p.add_argument(
        "-t",
        "--type",
        default="auto",
        help="Inky display model; 'auto' (default) reads the board EEPROM.",
    )
    p.add_argument(
        "-c",
        "--color",
        "--colour",
        dest="color",
        default=None,
        help="Panel color for pHAT/wHAT boards; ignored by Impression/Spectra.",
    )
    p.add_argument(
        "--saturation",
        type=float,
        default=0.5,
        help="Color saturation (0.0-1.0) for Impression/Spectra palette "
        "quantization, applied when the image is drawn on the panel.",
    )
    p.add_argument(
        "--min-refresh-interval",
        type=float,
        default=0.0,
        help="Minimum seconds between physical panel refreshes; a newer image is "
        "held until the interval elapses. Coalesces frequent changes.",
    )


def main():
    # Line-buffer stdout/stderr so each log line is flushed immediately even under
    # systemd or an ssh pipe (non-TTY), where Python would otherwise block-buffer.
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)

    parser = argparse.ArgumentParser(
        prog="inky-dashboard",
        description="Render web pages to Pimoroni Inky E-Ink displays. Rendering "
        "and display can run together ('local') or be split across hosts so a "
        "browser runs on a capable machine ('serve') while a small Raspberry Pi "
        "only pushes the finished image ('display').",
    )
    sub = parser.add_subparsers(dest="mode", required=True)

    serve = sub.add_parser(
        "serve",
        help="Render a web page in a browser and serve the panel-ready image "
        "over HTTP (run this on a capable host; no Inky needed).",
    )
    _add_render_args(serve)
    serve.add_argument(
        "--width",
        type=int,
        default=1600,
        help="Render/serve width in pixels (target panel resolution). Default 1600.",
    )
    serve.add_argument(
        "--height",
        type=int,
        default=1200,
        help="Render/serve height in pixels (target panel resolution). Default 1200.",
    )
    serve.add_argument(
        "--host", default="0.0.0.0", help="Address to bind the HTTP server to."
    )
    serve.add_argument(
        "--port", type=int, default=8080, help="Port to serve the panel image on."
    )

    local = sub.add_parser(
        "local",
        help="Render in a local browser AND push to the Inky panel on this same "
        "host (all-in-one; needs both browser and Inky).",
    )
    _add_render_args(local)
    _add_panel_args(local)

    display = sub.add_parser(
        "display",
        help="Fetch the image from a 'serve' instance and show it on the Inky "
        "panel (run this on the Raspberry Pi; no browser needed).",
    )
    display.add_argument(
        "server_url",
        help="Base URL of an 'inky-dashboard serve' instance, "
        "e.g. http://homeassistant.local:8080",
    )
    _add_panel_args(display)
    display.add_argument(
        "--poll-delay",
        type=float,
        default=5.0,
        help="How often (seconds) to check the server for a new image.",
    )

    args = parser.parse_args()
    print(f"running with {vars(args)}", file=sys.stderr)

    if args.mode == "serve":
        from . import serve as serve_mod

        serve_mod.run(args)
    elif args.mode == "local":
        from . import local as local_mod

        local_mod.run(args)
    elif args.mode == "display":
        from . import display as display_mod

        display_mod.run(args)


if __name__ == "__main__":
    main()
