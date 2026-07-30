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
    if opt.get("extra_args"):
        cmd += shlex.split(opt["extra_args"])

    print("exec: " + " ".join(shlex.quote(c) for c in cmd), flush=True)
    os.execvp(cmd[0], cmd)


if __name__ == "__main__":
    main()
