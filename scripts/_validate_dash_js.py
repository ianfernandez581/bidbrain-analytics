r"""Validate the inline <script> JS in a dashboard.html (or any HTML) file.

A syntax error in a dashboard's inline JS leaves the page stuck on
"Loading dashboard…", so this is the pre-deploy gate for every dash edit.

    .\.venv\Scripts\python.exe scripts/_validate_dash_js.py clients/client_<c>/dash/dashboard.html

Exit 0 = all inline scripts parse. Exit 1 = a real syntax error (prints it).

ENGINE (changed 2026-08-17): prefers **`node --check`**, which understands every syntax a browser
does. It falls back to the `esprima` package (repo venv) only when Node is absent.

Why it changed: esprima 4.x is frozen at ES2019, so it rejects optional chaining (`?.`) and nullish
coalescing (`??`) - syntax every browser has supported since 2020. `client_mongodb`'s dashboard uses
`?.` and therefore failed this gate on EVERY run, and the old advice was to eyeball the line and call
it a known-parser-limitation pass. A gate that cries wolf on one file every time is a gate nobody
reads: a real unbalanced brace in that same file would have looked identical to the false alarm. With
Node the gate is exact, so a failure now always means a genuine syntax error.

The `esprima` fallback keeps its old blind spot, so it SAYS SO in the output rather than failing
silently - if you see the fallback banner and a `?.` / `??` complaint, install Node.
"""
import re
import shutil
import subprocess
import sys
import tempfile
import os

_NODE = shutil.which("node")


def _check_with_node(body):
    """Return None if it parses, else the error text. Tries script then module grammar."""
    fd, path = tempfile.mkstemp(suffix=".js")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
        r = subprocess.run([_NODE, "--check", path], capture_output=True, text=True)
        if r.returncode == 0:
            return None
        script_err = (r.stderr or "").strip()
        # A module-only construct (top-level await, import/export) is valid in a
        # <script type="module">, so retry under module grammar before failing.
        r2 = subprocess.run([_NODE, "--input-type=module", "--check", "-"],
                            input=body, capture_output=True, text=True)
        if r2.returncode == 0:
            return None
        return _tidy(script_err, path)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _tidy(err, path):
    """Drop the temp path and Node's stack frames; keep the line/column and the message."""
    out = []
    for line in err.splitlines():
        if "node:internal" in line or line.startswith("    at "):
            continue
        out.append(line.replace(path, "<inline script>"))
        if len(out) >= 6:
            break
    return " | ".join(x.strip() for x in out if x.strip())


def _check_with_esprima(body):
    import esprima
    try:
        esprima.parseModule(body, tolerant=False)
        return None
    except Exception:
        try:
            esprima.parseScript(body, tolerant=False)
            return None
        except Exception as e:  # noqa: BLE001
            return str(e)


def validate(path):
    with open(path, encoding="utf-8") as f:
        html = f.read()
    # inline <script> blocks only (skip ones with a src= attribute, e.g. the Chart.js CDN)
    blocks = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S | re.I)
    if not blocks:
        print(f"{path}: no inline <script> blocks found")
        return True
    check = _check_with_node if _NODE else _check_with_esprima
    ok = True
    for i, body in enumerate(blocks):
        if not body.strip():
            continue
        err = check(body)
        if err:
            ok = False
            print(f"{path}: inline <script> #{i} FAILED to parse -> {err}")
    if ok:
        engine = "node --check" if _NODE else "esprima (ES2019 - no ?. or ??)"
        print(f"{path}: OK ({len(blocks)} inline script block(s) parse clean, {engine})")
    elif not _NODE:
        print("  NOTE: parsed with esprima 4.x, which predates optional chaining (?.) and nullish "
              "coalescing (??). If the error names one of those, it is a parser limitation, not a "
              "bug - install Node so this gate can be trusted.")
    return ok


if __name__ == "__main__":
    paths = sys.argv[1:]
    if not paths:
        raise SystemExit("usage: _validate_dash_js.py <dashboard.html> [more.html ...]")
    all_ok = all(validate(p) for p in paths)
    raise SystemExit(0 if all_ok else 1)
