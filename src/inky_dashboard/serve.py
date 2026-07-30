import asyncio
import io
import sys

from aiohttp import web

from .render import run_render


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
    return web.Response(
        body=state.png, content_type="image/png", headers={"ETag": state.etag}
    )


async def _hash_handler(request):
    state = request.app["state"]
    return web.Response(text=state.etag or "")


async def _index_handler(request):
    state = request.app["state"]
    ready = "yes" if state.png else "no"
    return web.Response(
        text=f"inky-dashboard serve\nimage ready: {ready}\nGET /image  GET /hash\n"
    )


async def serve_async(args):
    state = ImageState()
    app = web.Application()
    app["state"] = state
    app.add_routes(
        [
            web.get("/", _index_handler),
            web.get("/image", _image_handler),
            web.get("/hash", _hash_handler),
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
        state.set(buf.getvalue(), sig.hex())
        print("published image", file=sys.stderr)

    try:
        await run_render(args, publish, args.width, args.height)
    finally:
        await runner.cleanup()


def run(args):
    asyncio.run(serve_async(args))
