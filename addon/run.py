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

    print("exec: " + " ".join(shlex.quote(c) for c in cmd), flush=True)
    os.execvp(cmd[0], cmd)


if __name__ == "__main__":
    main()
