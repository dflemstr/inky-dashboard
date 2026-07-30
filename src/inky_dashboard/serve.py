import asyncio
import io
import re
import sys

from aiohttp import web

from .render import run_render

# One entity-tag: an optional weak indicator W/ then a quoted opaque-tag. Used to
# pull each tag out of an If-None-Match list (commas between tags don't need
# special handling since the opaque-tag is delimited by quotes).
_ETAG_RE = re.compile(r'(W/)?("[^"]*")')


def _if_none_match(headers, current_etag: str) -> bool:
    """RFC 9110 If-None-Match evaluation for a GET: True (-> 304) if the client
    already holds the current representation. Accepts a list of entity-tags
    (comma-separated and/or across repeated headers) or "*", and uses weak
    comparison (the W/ prefix is ignored when matching)."""
    values = headers.getall("If-None-Match", [])
    if not values:
        return False
    combined = ",".join(values).strip()
    if combined == "*":
        return True
    # Weak comparison: compare opaque-tags, ignoring any W/ on either side. Our
    # own tags are always strong, so just compare the quoted opaque-tag.
    current_opaque = current_etag[2:] if current_etag.startswith("W/") else current_etag
    for _weak, opaque in _ETAG_RE.findall(combined):
        if opaque == current_opaque:
            return True
    return False


class ImageState:
    """The most recently published panel image, shared between the render loop
    and the HTTP handlers. Full-color at panel resolution; the display client
    quantizes to the panel palette."""

    def __init__(self):
        self.png = None
        self.etag = None

    def set(self, png: bytes, etag: str):
        self.png = png
        self.etag = etag


async def _image_handler(request):
    state = request.app["state"]
    if state.png is None:
        return web.Response(status=503, text="no image rendered yet")
    # Conditional GET: if the client already has the current image, save the
    # transfer and reply 304 Not Modified (RFC 9110 If-None-Match).
    if _if_none_match(request.headers, state.etag):
        return web.Response(status=304, headers={"ETag": state.etag})
    return web.Response(
        body=state.png, content_type="image/png", headers={"ETag": state.etag}
    )


async def _index_handler(request):
    state = request.app["state"]
    ready = "yes" if state.png else "no"
    return web.Response(
        text=f"inky-dashboard serve\nimage ready: {ready}\nGET /image\n"
    )


async def serve_async(args):
    state = ImageState()
    app = web.Application()
    app["state"] = state
    app.add_routes(
        [
            web.get("/", _index_handler),
            web.get("/image", _image_handler),
        ]
    )
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, args.host, args.port)
    await site.start()
    print(f"serving panel image on http://{args.host}:{args.port}", file=sys.stderr)

    def publish(img, sig):
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        # Quoted per the HTTP ETag grammar; the client treats it as opaque.
        state.set(buf.getvalue(), f'"{sig.hex()}"')
        print("published image", file=sys.stderr)

    try:
        await run_render(args, publish, args.width, args.height)
    finally:
        await runner.cleanup()


def run(args):
    asyncio.run(serve_async(args))
