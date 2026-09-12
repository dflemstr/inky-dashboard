import asyncio
import hashlib
import io
import os
import sys
import time

from PIL import Image
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page, async_playwright
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

# How many times to retry the initial navigation before giving up. A transient
# network error (e.g. net::ERR_NETWORK_CHANGED) should be ridden out, not fatal.
GOTO_RETRIES = 3

# Reload the page from scratch this often (seconds), as a freshness backstop.
# Home Assistant is a PWA: after a core update the backend version changes but a
# long-lived tab keeps rendering the frontend it loaded at startup, and the
# version-pinned custom cards (apexcharts, auto-entities, ...) then break while
# built-ins keep working. Blocking the service worker (see run_render) makes a
# reload actually fetch the new frontend; this periodic reload guarantees the tab
# picks up a new frontend within the interval even if nothing else triggers a
# reload. Override with INKY_RENDER_RELOAD_INTERVAL (0 disables).
RELOAD_INTERVAL = float(os.environ.get("INKY_RENDER_RELOAD_INTERVAL", str(6 * 3600)))

# JS probe: is Home Assistant's websocket currently connected? True/False when
# determinable, else None (page still loading, or not a HA page). Used to avoid
# capturing HA's "Connection lost. Reconnecting..." popover.
HA_CONNECTED_PROBE = """(() => {
  try {
    const ha = document.querySelector('home-assistant');
    const c = ha && ha.hass && ha.hass.connection;
    return c ? !!c.connected : null;
  } catch (e) { return null; }
})()"""


async def load_and_prepare(page: Page, args):
    # Navigate to the target URL and (re-)apply all render-time setup: wait for
    # real content, run --eval, freeze animations, disable AA, inject CSS. Runs
    # at startup and again on every reload, so injected styles/eval are always
    # re-applied after a reload (a reload wipes them from the document).
    for attempt in range(1, GOTO_RETRIES + 1):
        try:
            await page.goto(args.url)
            break
        except PlaywrightError as e:
            if attempt == GOTO_RETRIES:
                raise
            print(
                f"warning: navigation failed ({e}); retrying ({attempt})",
                file=sys.stderr,
            )
            await asyncio.sleep(min(2 * attempt, 10))
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
    # Disable font anti-aliasing unless supersampling: at 1x, AA gray edges get
    # dithered into speckle on a limited palette, so hard edges look cleaner.
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
    if args.inject_css:
        try:
            with open(args.inject_css) as f:
                await page.add_style_tag(content=f.read())
        except OSError as e:
            print(f"warning: --inject-css failed: {e}", file=sys.stderr)
    await asyncio.sleep(0.5)


async def capture_frame(page: Page, width: int, height: int):
    srcimg = Image.open(io.BytesIO(await page.screenshot()))
    # With --supersample the screenshot is larger than the panel; downscale it
    # with a high-quality filter for anti-aliasing before use.
    if srcimg.size != (width, height):
        srcimg = srcimg.resize((width, height), Image.LANCZOS)
    img = Image.new(srcimg.mode, (width, height), (255, 255, 255))
    img.paste(srcimg, (0, 0))
    return img


async def render_loop(page: Page, publish, width: int, height: int, args):
    # Poll the page often and hand a full-color panel-resolution image to
    # `publish(img, sig)` only when the rendered result has actually changed AND
    # settled (unchanged across --settle-checks polls). A full color e-ink refresh
    # is slow, so this debounce avoids mid-transition frames. A poll is "unusable"
    # when required content is missing (--wait-selector absent), HA's socket is
    # down, or a screenshot times out; those keep the last published image rather
    # than publishing a half-loaded page or the reconnect popover. After
    # --reload-after unusable polls, the page is reloaded to recover.
    #
    # --min-refresh-interval (read via getattr; only some callers set it) is a
    # floor between publishes: a settled change arriving sooner is held until the
    # interval elapses, then the latest state is published. `publish` is called
    # only when a changed image both settles/forces AND clears that floor.
    min_refresh = getattr(args, "min_refresh_interval", 0.0)
    published_sig = None
    prev_sig = None
    stable = 0
    pending_since = None
    last_publish = None
    fails = 0
    last_reload = time.monotonic()
    # Track the HA websocket so we can reload the page the moment it reconnects.
    # A HA core update takes the backend down and back up; reloading on reconnect
    # re-fetches the (now newer) frontend right away instead of waiting for the
    # periodic backstop, so version-pinned custom cards recover in seconds.
    ever_connected = False
    was_down = False
    while True:
        # Freshness backstop: periodically reload from scratch so the tab picks up
        # a new HA frontend after a core update (see RELOAD_INTERVAL). A failure
        # reload below also resets this timer, so a healthy tab reloads at most
        # once per interval.
        if RELOAD_INTERVAL > 0 and (time.monotonic() - last_reload) >= RELOAD_INTERVAL:
            print("periodic reload (frontend freshness)", file=sys.stderr)
            try:
                await load_and_prepare(page, args)
            except Exception as e:
                print(f"warning: periodic reload failed: {e}", file=sys.stderr)
            last_reload = time.monotonic()
        content_ok = True
        if args.wait_selector:
            try:
                handle = await page.query_selector(args.wait_selector)
            except Exception:
                handle = None
            content_ok = handle is not None
            if handle is not None:
                await handle.dispose()
        try:
            connected = await page.evaluate(HA_CONNECTED_PROBE)
        except Exception:
            connected = None

        # Reload as soon as HA comes back after having been down (a core update):
        # the reconnected frontend may be a new version, so fetch it fresh.
        if connected is True and was_down:
            print("HA reconnected; reloading for a fresh frontend", file=sys.stderr)
            try:
                await load_and_prepare(page, args)
            except Exception as e:
                print(f"warning: reconnect reload failed: {e}", file=sys.stderr)
            was_down = False
            fails = 0
            last_reload = time.monotonic()
            await asyncio.sleep(args.poll_delay)
            continue
        if connected is True:
            ever_connected = True
        elif connected is False and ever_connected:
            # Genuinely disconnected (the socket exists but reports not-connected,
            # i.e. the backend went away) after having been up: arm a reload for
            # when it returns. None (page loading / probe error) is not treated as
            # a disconnect, so a reload's own loading window can't re-arm this.
            was_down = True

        img = None
        if not content_ok:
            print(
                f"{args.wait_selector!r} not present; holding ({fails + 1})",
                file=sys.stderr,
            )
        elif connected is False:
            print(f"HA connection down; holding ({fails + 1})", file=sys.stderr)
        else:
            try:
                img = await capture_frame(page, width, height)
            except PlaywrightTimeoutError:
                print(f"screenshot timed out; holding ({fails + 1})", file=sys.stderr)

        if img is None:
            fails += 1
            if fails >= args.reload_after:
                print("reloading page to recover", file=sys.stderr)
                try:
                    await load_and_prepare(page, args)
                except Exception as e:
                    print(f"warning: reload failed: {e}", file=sys.stderr)
                fails = 0
                last_reload = time.monotonic()
            await asyncio.sleep(args.poll_delay)
            continue
        fails = 0

        sig = hashlib.sha256(img.tobytes()).digest()
        stable = stable + 1 if sig == prev_sig else 1
        prev_sig = sig
        now = time.monotonic()

        if sig != published_sig:
            if pending_since is None:
                pending_since = now
            settled = stable >= args.settle_checks
            forced = (now - pending_since) >= args.refresh_delay
            rate_ok = last_publish is None or (now - last_publish) >= min_refresh
            if (settled or forced) and rate_ok:
                await _maybe_await(publish(img, sig))
                published_sig = sig
                pending_since = None
                last_publish = time.monotonic()
        else:
            pending_since = None

        await asyncio.sleep(args.poll_delay)


async def _maybe_await(result):
    # Let publish callbacks be either sync (push to a panel) or async.
    if asyncio.iscoroutine(result):
        await result


async def run_render(args, publish, width: int, height: int):
    # Launch the browser, load/prepare the page, and drive the render loop,
    # handing settled images to `publish`. Shared by `serve` (publish -> HTTP)
    # and `local` (publish -> Inky panel).
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(
            viewport={
                "width": int(width * (1 / args.scale)),
                "height": int(height * (1 / args.scale)),
            },
            color_scheme="light",
            is_mobile=False,
            # scale * supersample device pixels per CSS pixel; layout follows
            # --scale (viewport above), --supersample only raises pixel density.
            device_scale_factor=args.scale * args.supersample,
            locale=args.locale,
            # Block the Home Assistant PWA service worker. Otherwise it precaches
            # the frontend app shell and keeps serving the *old* frontend after a
            # HA core update — even across page reloads — until the whole browser
            # is restarted, which silently breaks version-pinned custom cards. With
            # it blocked, every (re)load fetches the current frontend from the
            # network, so the periodic/failure reloads actually recover.
            service_workers="block",
        )
        page = await context.new_page()
        # Injected before any page script on every navigation — used to seed auth
        # (e.g. Home Assistant's localStorage token) so the app starts logged in
        # without a trusted-network or a login redirect.
        if getattr(args, "init_script", None):
            try:
                with open(args.init_script) as f:
                    await page.add_init_script(script=f.read())
            except OSError as e:
                print(f"warning: --init-script failed: {e}", file=sys.stderr)
        await load_and_prepare(page, args)
        await render_loop(page, publish, width, height, args)
