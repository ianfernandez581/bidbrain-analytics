"""Validate the inline <script> JS in a dashboard.html (or any HTML) file.

A syntax error in a dashboard's inline JS leaves the page stuck on
"Loading dashboard…", so this is the pre-deploy gate for every dash edit.
There is no Node on this box; we parse with the `esprima` package (in the repo
venv). Run with the venv python:

    .\.venv\Scripts\python.exe scripts/_validate_dash_js.py clients/client_<c>/dash/dashboard.html

Exit 0 = all inline scripts parse. Exit 1 = a real syntax error (prints it).

Caveat: esprima 4.x predates optional chaining (`?.`) / nullish coalescing
(`??`). If the ONLY failure mentions those tokens on a line you've confirmed is
valid modern JS, treat it as a known-parser-limitation pass — but any other
syntax error (unbalanced braces/parens, stray comma, bad string) is blocking.
"""
import re
import sys

import esprima


def validate(path):
    with open(path, encoding="utf-8") as f:
        html = f.read()
    # inline <script> blocks only (skip ones with a src= attribute, e.g. the Chart.js CDN)
    blocks = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S | re.I)
    if not blocks:
        print(f"{path}: no inline <script> blocks found")
        return True
    ok = True
    for i, body in enumerate(blocks):
        if not body.strip():
            continue
        try:
            esprima.parseModule(body, tolerant=False)
        except Exception:
            try:
                esprima.parseScript(body, tolerant=False)
            except Exception as e:  # noqa: BLE001
                ok = False
                print(f"{path}: inline <script> #{i} FAILED to parse -> {e}")
    if ok:
        print(f"{path}: OK ({len(blocks)} inline script block(s) parse clean)")
    return ok


if __name__ == "__main__":
    paths = sys.argv[1:]
    if not paths:
        raise SystemExit("usage: _validate_dash_js.py <dashboard.html> [more.html ...]")
    all_ok = all(validate(p) for p in paths)
    raise SystemExit(0 if all_ok else 1)
