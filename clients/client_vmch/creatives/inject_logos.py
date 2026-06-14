"""Inline the real VMCH logo into the dashboard topbar + the login screen.

Source: creatives/Logo.webp (orange-red "VMCH" wordmark, transparent bg, client-supplied).
Both surfaces are LIGHT (white topbar, white login card), so the logo is used at its
true brand colour (#EB3300) on both — no recolour needed.

  - DASHBOARD topbar -> set <img class="brandlogo"> src   (dash/dashboard.html)
  - LOGIN card       -> set <img class="client">    src   (dash/main.py)

The 100% Digital agency mark is an inline SVG wordmark authored directly in those files
(no raster asset exists), so it is NOT touched here — only the VMCH raster logo is inlined.

Idempotent: matches each <img> by class and rewrites its src=, so re-running is safe even
after the data URI is already in place. Run:  python clients/client_vmch/creatives/inject_logos.py
"""
import os
import re
import io
import base64
from PIL import Image

HERE = os.path.dirname(__file__)
DASH = os.path.normpath(os.path.join(HERE, "..", "dash"))
SRC = os.path.join(HERE, "Logo.webp")


def data_uri(im):
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def set_img_src(path, css_class, uri):
    with open(path, encoding="utf-8") as f:
        txt = f.read()
    pat = re.compile(r'(<img class="' + re.escape(css_class) + r'" src=")[^"]*(")')
    new, n = pat.subn(lambda m: m.group(1) + uri + m.group(2), txt)
    if n != 1:
        raise SystemExit(f"  !! expected exactly 1 <img class=\"{css_class}\"> in "
                         f"{os.path.basename(path)}, found {n}")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(new)
    print(f"  set {css_class} src in {os.path.basename(path)} ({len(uri)//1024} KB data URI)")


def main():
    im = Image.open(SRC).convert("RGBA")
    bbox = im.split()[3].getbbox()      # crop away transparent margin -> tight in the topbar
    if bbox:
        im = im.crop(bbox)
    print(f"cropped logo to {im.size}")
    uri = data_uri(im)
    set_img_src(os.path.join(DASH, "dashboard.html"), "brandlogo", uri)
    set_img_src(os.path.join(DASH, "main.py"), "client", uri)
    print("done.")


if __name__ == "__main__":
    main()
