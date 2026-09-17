r"""Derive Burnet's served brand assets from the supplied artwork. Regenerate, never hand-edit.

The supplied lockup is a SINGLE-COLOUR VECTOR (creatives/burnet-lockup.svg, 7 paths, one fill), so
unlike client_lacevo - whose master is a raster on solid white and needs a luminance key - there is
nothing to key out here and a recolour is one attribute. What this script does instead is put the
same vector on the three surfaces that each need it in a different form:

  dash/logo.svg   the full lockup, SERVED at /logo.svg. The login page is served from the service
                  ROOT, so a root-relative path resolves there.
  dash/icon.png   the MARK ALONE, rasterised, for the browser tab. A tab icon has to be a raster
                  for the widest support, and the wordmark is illegible at 16px - so the tab gets
                  the glyph, which is what the brand uses as its own mark.
  dashboard.html  the lockup INLINED between BB-BURNET:lockup markers. It cannot use the route:
                  behind the platform proxy the dashboard is served at /d/burnet/, where a
                  root-relative /logo.svg resolves to the PLATFORM's namespace and 404s. That is
                  the same "logo ships twice" gotcha client_geyervalmont and client_lacevo carry -
                  the difference here is that the second copy is INJECTED, between markers, so the
                  two cannot drift.

Rasterising needs a Chromium: there is no SVG rasteriser in the repo venv (PIL cannot read SVG) and
adding cairosvg would drag the cairo DLLs onto every Windows box. Chrome or Edge is already on every
dev machine here, and the estate already drives headless Chrome to render dashboards for
verification. If neither is found the script says so and leaves the existing icon.png alone.

    .\.venv\Scripts\python.exe clients\client_burnet\gen_brand_assets.py
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CREATIVES = ROOT / "creatives"
DASH = ROOT / "dash"

# The tab icon is the BRAND ORANGE, not the deep shade: #F76E3B carries on both a light and a dark
# browser tab strip, and the deep #BD572F goes muddy against dark chrome.
ICON_COLOUR = "#F76E3B"
ICON_PX = 96          # sized to its DISPLAY (browsers ask for 16-48); past this is bytes for detail
                      # a 6-path glyph does not have.

MARK_OPEN, MARK_CLOSE = "<!-- BB-BURNET:lockup -->", "<!-- /BB-BURNET:lockup -->"


def _chrome():
    """Find a Chromium to rasterise with. Explicit override first, then the usual install paths."""
    env = os.environ.get("CHROME_PATH")
    if env and Path(env).exists():
        return env
    for c in ("chrome", "google-chrome", "chromium", "msedge"):
        found = shutil.which(c)
        if found:
            return found
    for p in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
              "/usr/bin/chromium-browser"):
        if Path(p).exists():
            return p
    return None


def _svg(name):
    """Read one of the committed source SVGs, stripping the leading comment."""
    txt = (CREATIVES / name).read_text(encoding="utf-8")
    return re.sub(r"^\s*<!--.*?-->\s*", "", txt, flags=re.S).strip()


def _recolour(svg, colour):
    return re.sub(r'fill="#[0-9A-Fa-f]{6}"', 'fill="%s"' % colour, svg, count=1)


def write_logo_svg():
    """The served lockup. Identical bytes to the source - this is a copy, not a transform, and it
    exists only so dash/ is self-contained in the container build context."""
    out = DASH / "logo.svg"
    out.write_text(_svg("burnet-lockup.svg") + "\n", encoding="utf-8")
    print("wrote %s (%d bytes)" % (out.name, out.stat().st_size))


def write_icon_png():
    """Rasterise the MARK to a square transparent PNG for the browser tab."""
    chrome = _chrome()
    if not chrome:
        print("!! no Chrome/Edge found - icon.png NOT regenerated (set CHROME_PATH to override).")
        return False
    mark = _recolour(_svg("burnet-mark.svg"), ICON_COLOUR)
    # The glyph is 47.72 x 40, so it is padded into a SQUARE viewport rather than stretched: a tab
    # icon is square, and squashing a mark to fit is the tell of a generated favicon.
    page = ("<!doctype html><meta charset=utf-8>"
            "<style>html,body{margin:0;padding:0;background:transparent}"
            "div{width:%dpx;height:%dpx;display:flex;align-items:center;justify-content:center}"
            "svg{width:92%%;height:auto;display:block}</style>"
            "<div>%s</div>" % (ICON_PX, ICON_PX, mark))
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "icon.html"
        src.write_text(page, encoding="utf-8")
        cmd = [chrome, "--headless", "--disable-gpu", "--hide-scrollbars", "--no-sandbox",
               "--force-device-scale-factor=1",
               # transparency: without this Chrome paints its own white page behind the mark and
               # the tab icon ships as an orange glyph on a white tile.
               "--default-background-color=00000000",
               "--screenshot=%s" % (Path(td) / "icon.png"),
               "--window-size=%d,%d" % (ICON_PX, ICON_PX),
               src.as_uri()]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        shot = Path(td) / "icon.png"
        if not shot.exists():
            print("!! Chrome produced no screenshot (%s)\n%s" % (r.returncode, r.stderr[-800:]))
            return False
        (DASH / "icon.png").write_bytes(shot.read_bytes())
    print("wrote icon.png (%d bytes, %dpx)" % ((DASH / "icon.png").stat().st_size, ICON_PX))
    return True


def inject_lockup():
    """Put the lockup inline in dashboard.html, between markers, so the topbar mark and the served
    one can never disagree. Written INK-free: the SVG carries its own fill, and the dashboard sets
    a CSS `fill` on .brand-lockup path when it needs another colourway."""
    page = DASH / "dashboard.html"
    if not page.exists():
        print("   (dashboard.html not written yet - skipping the inline injection)")
        return
    html = page.read_text(encoding="utf-8")
    if MARK_OPEN not in html or MARK_CLOSE not in html:
        print("!! dashboard.html carries no BB-BURNET:lockup markers - nothing injected.")
        return
    block = MARK_OPEN + "\n" + _svg("burnet-lockup.svg") + "\n" + MARK_CLOSE
    new = re.sub(re.escape(MARK_OPEN) + r".*?" + re.escape(MARK_CLOSE), lambda _: block, html, flags=re.S)
    if new == html:
        print("   dashboard.html lockup already current.")
        return
    page.write_text(new, encoding="utf-8")
    print("injected the lockup into dashboard.html")


if __name__ == "__main__":
    DASH.mkdir(exist_ok=True)
    write_logo_svg()
    ok = write_icon_png()
    inject_lockup()
    sys.exit(0 if ok else 1)
