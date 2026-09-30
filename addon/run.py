#!/usr/bin/env python3
"""Add-on entrypoint: read Supervisor options and exec `inky-dashboard serve`.

Options come from /data/options.json (written by Supervisor from config.yaml's
`options`). Building the command in Python avoids shell-quoting pitfalls with the
--eval JavaScript string.
"""

import json
import os
import shlex

OPTIONS = "/data/options.json"


def main():
    with open(OPTIONS) as f:
        opt = json.load(f)

    cmd = [
        "inky-dashboard",
        "serve",
        opt["url"],
        "--width",
        str(opt["width"]),
        "--height",
        str(opt["height"]),
        "--scale",
        str(opt["scale"]),
        "--render-delay",
        str(opt["render_delay"]),
        "--port",
        "8080",
        # Fine-grained (sub-hour) power-graph buckets mean the live right-edge bar
        # changes every poll, so the render never "settles" and only publishes via
        # this max-staleness force. Keep it short so the first frame after any
        # restart/reload appears in ~1 min instead of ~5. Steady-state panel
        # cadence is unaffected (the Pi has its own longer min-refresh).
        "--refresh-delay",
        "60",
    ]
    if opt.get("wait_selector"):
        cmd += ["--wait-selector", opt["wait_selector"]]
    if opt.get("eval"):
        cmd += ["--eval", opt["eval"]]
    if opt.get("locale"):
        cmd += ["--locale", opt["locale"]]
    if opt.get("supersample"):
        cmd += ["--supersample", str(opt["supersample"])]
    # --inject-css expects a *file path*. Always inject the baked-in e-ink CSS
    # (/eink.css, COPYed in by the Dockerfile), and append the inject_css option
    # (a raw CSS string, since the add-on has no host mounts to point a path at).
    css_parts = []
    try:
        with open("/eink.css") as f:
            css_parts.append(f.read())
    except OSError:
        pass
    extra_css = opt.get("inject_css", "").strip()
    if extra_css:
        css_parts.append(extra_css)
    if css_parts:
        with open("/tmp/inject.css", "w") as f:
            f.write("\n".join(css_parts))
        cmd += ["--inject-css", "/tmp/inject.css"]

    # If a long-lived access token is configured, seed it into the frontend's
    # localStorage before the app loads so it starts authenticated (no trusted
    # network, no login redirect). hassUrl is derived from the page's own origin
    # so it always matches the instance being rendered.
    token = opt.get("token", "").strip()
    if token:
        init_js = (
            "(function(){try{"
            "localStorage.setItem('hassTokens', JSON.stringify({"
            "access_token: " + json.dumps(token) + ","
            "token_type: 'Bearer',"
            "expires_in: 315360000,"
            "hassUrl: location.protocol + '//' + location.host,"
            "clientId: null,"
            "expires: 9999999999999,"
            "refresh_token: ''"
            "}));}catch(e){}})();"
        )
        with open("/tmp/init.js", "w") as f:
            f.write(init_js)
        cmd += ["--init-script", "/tmp/init.js"]

    if opt.get("extra_args"):
        cmd += shlex.split(opt["extra_args"])

    # Startup diagnostic: report the installed renderer's freshness safeguards so
    # a glance at the add-on log confirms which code is deployed (this add-on
    # pins the tool to a git commit in the Dockerfile).
    try:
        import inspect as _inspect

        from inky_dashboard import render as _render

        _src = _inspect.getsource(_render)
        print(
            "renderer: reload_interval="
            + str(getattr(_render, "RELOAD_INTERVAL", "n/a"))
            + "s service_worker_block="
            + str('service_workers="block"' in _src)
            + " reconnect_reload="
            + str("HA reconnected" in _src),
            flush=True,
        )
    except Exception as _e:  # never block startup on a diagnostic
        print(f"renderer: self-check failed ({_e})", flush=True)

    print("exec: " + " ".join(shlex.quote(c) for c in cmd), flush=True)
    os.execvp(cmd[0], cmd)


if __name__ == "__main__":
    main()
