r"""Derive the Ray White Projects brand assets from the supplied artwork, and inject the topbar
lockup into dashboard.html.

NOTHING IS SUPPLIED YET, AND THIS SCRIPT DOES NOT INVENT ANYTHING.
-----------------------------------------------------------------
No Ray White Projects artwork has been handed over, so today this script prints exactly what it
needs and exits 1. That is deliberate: the estate has twice had to DELETE a generated placeholder
mark the day the real one arrived (client_sophiie, client_lacevo), and a fabricated lockup is worse
than an obvious stand-in because it looks finished. Until the files land, the mark on both the
login and the topbar is the typographic stand-in in markup - no binary in the repo, nothing to rot.

WHAT TO DROP IN
---------------
    creatives/raywhite-projects-lockup.svg    the horizontal lockup for the topbar and login
    creatives/raywhite-projects-mark.svg      the mark alone, for the browser tab

Projects uses the CONCRETE lockup on Monair, not the yellow one - ask for that colourway
specifically. Vector is strongly preferred: a single-colour vector recolours with one attribute,
where a raster master has to be luminance-keyed (the client_lacevo route) and then only works on
one background.

WHAT IT WILL THEN WRITE
-----------------------
    dash/logo.svg     the full lockup, SERVED at /logo.svg for the LOGIN page, which is served
                      from the service root and can reference a route.
    dash/icon.png     the MARK ALONE, rasterised, for the browser tab. A tab icon has to carry at
                      16px, where a wordmark is illegible.
    dashboard.html    the lockup INLINED between the BB-RWP:lockup markers. It cannot use the
                      route: behind the platform proxy the dashboard is served at
                      /d/raywhiteprojects/, where a root-relative /logo.svg resolves against the
                      PLATFORM namespace and 404s. Injecting between markers rather than pasting
                      is what stops the two copies drifting.

THREE EDITS GO WITH IT, in the same change
------------------------------------------
    1. dash/Dockerfile      add logo.svg and icon.png to the COPY line, or they are not in the image.
    2. dash/main.py         add the /logo.svg and /icon.png routes back (the shape is in
                            clients/client_burnet/dash/main.py) and point the login's <link
                            rel="icon"> and .client block at them instead of the inline stand-in.
                            Serve them content-HASHED: they carry max-age=86400, so without a
                            hash in the URL a browser that has already opened the login serves the
                            OLD art for a day and the deploy looks like it silently failed. That
                            happened on the Lacevo standup and the client noticed first.
    3. dash/deploy_dash_raywhiteprojects.ps1   add the two Test-Path guards.

    .\.venv\Scripts\python.exe clients\client_raywhiteprojects\gen_brand_assets.py
"""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CREATIVES = ROOT / "creatives"
DASH = ROOT / "dash"

LOCKUP_SRC = CREATIVES / "raywhite-projects-lockup.svg"
MARK_SRC = CREATIVES / "raywhite-projects-mark.svg"

# Brand tokens. CONCRETE is the lockup colourway used on Monair. The yellow is deliberately NOT
# here: it is a fill and a rule in this build, never a mark colour, and it fails contrast at every
# size on both the bone field and white.
INK = "#131311"
BONE = "#F4F2ED"
CONCRETE = "#8E8B83"

MARK_OPEN, MARK_CLOSE = "<!-- BB-RWP:lockup -->", "<!-- /BB-RWP:lockup -->"
ICON_PX = 256


def _missing():
    print("No Ray White Projects artwork found. Expected:")
    for p in (LOCKUP_SRC, MARK_SRC):
        print("    %s  %s" % ("OK    " if p.exists() else "MISSING", p.relative_to(ROOT)))
    print()
    print("Nothing was written. The login and topbar keep the typographic stand-in until the real")
    print("files are supplied - see this script's docstring for what to ask for and what to edit")
    print("once they land.")
    return 1


def _chrome():
    """Headless Chrome, for rasterising the mark. There is no SVG rasteriser in the repo venv, so
    this is how client_burnet produces its tab icon too."""
    for c in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
              shutil.which("chrome"), shutil.which("google-chrome")):
        if c and Path(c).exists():
            return c
    return None


def _svg(path):
    return path.read_text(encoding="utf-8").strip()


def _recolour(svg, colour):
    """Force every fill to one colour. Only safe on a SINGLE-COLOUR source - check the artwork is
    one flat colour before trusting this, or a two-tone lockup silently flattens."""
    svg = re.sub(r'fill="(?!none)[^"]*"', 'fill="%s"' % colour, svg)
    if "fill=" not in svg:
        svg = svg.replace("<svg", '<svg fill="%s"' % colour, 1)
    return svg


def write_logo_svg():
    """The served lockup, in CONCRETE for the dark login card."""
    out = DASH / "logo.svg"
    out.write_text(_recolour(_svg(LOCKUP_SRC), BONE) + "\n", encoding="utf-8")
    print("wrote %s (bone, for the ink login card)" % out.relative_to(ROOT))


def write_icon_png():
    """Rasterise the MARK to a square transparent PNG for the browser tab."""
    chrome = _chrome()
    if not chrome:
        print("!! Chrome not found - skipping icon.png. Install Chrome or rasterise the mark by hand.")
        return
    svg = _recolour(_svg(MARK_SRC), CONCRETE)
    with tempfile.TemporaryDirectory() as td:
        page = Path(td) / "icon.html"
        page.write_text(
            "<html><body style='margin:0;background:transparent'>"
            "<div style='width:%dpx;height:%dpx;display:grid;place-items:center'>%s</div>"
            "</body></html>" % (ICON_PX, ICON_PX, svg), encoding="utf-8")
        shot = Path(td) / "icon.png"
        subprocess.run([chrome, "--headless", "--disable-gpu", "--default-background-color=00000000",
                        "--screenshot=%s" % shot, "--window-size=%d,%d" % (ICON_PX, ICON_PX),
                        page.as_uri()], check=True, capture_output=True)
        shutil.copyfile(shot, DASH / "icon.png")
    print("wrote %s (%dpx, the mark alone)" % ((DASH / "icon.png").relative_to(ROOT), ICON_PX))


def inject_lockup():
    """Put the lockup inline in dashboard.html, between markers, so the topbar mark and the served
    logo can never drift."""
    html_path = DASH / "dashboard.html"
    if not html_path.exists():
        print("   (dashboard.html not written yet - skipping the inline injection)")
        return
    html = html_path.read_text(encoding="utf-8")
    if MARK_OPEN not in html or MARK_CLOSE not in html:
        print("!! dashboard.html carries no BB-RWP:lockup markers - nothing injected.")
        return
    # The topbar sits on ink, so the inline copy is the BONE colourway.
    block = (MARK_OPEN + "\n"
             + '<div class="client brand-lockup">' + _recolour(_svg(LOCKUP_SRC), BONE) + "</div>\n"
             + MARK_CLOSE)
    new = re.sub(re.escape(MARK_OPEN) + r".*?" + re.escape(MARK_CLOSE), lambda _: block, html, flags=re.S)
    if new == html:
        print("   dashboard.html lockup already current.")
        return
    html_path.write_text(new, encoding="utf-8")
    print("injected the lockup into dashboard.html")
    print("   REMEMBER the three edits in this script's docstring: the Dockerfile COPY line, the")
    print("   /logo.svg + /icon.png routes in main.py (content-hashed), and the deploy guards.")


def main():
    if not (LOCKUP_SRC.exists() and MARK_SRC.exists()):
        return _missing()
    write_logo_svg()
    write_icon_png()
    inject_lockup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
