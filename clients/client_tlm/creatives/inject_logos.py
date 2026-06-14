"""Inline the real The Little Marionette logo into the dashboard + login.

Source: creatives/TLM__logo_white.avif (white wordmark + marionette, transparent bg).
 - DASHBOARD (light cream theme)  -> recolour to navy slate, set <img class="brandlogo"> src
 - LOGIN     (dark slate theme)   -> pure white,           set <img class="client">    src

Idempotent: matches the <img> by class and rewrites its src=, so re-running is safe even
after the token has already been replaced. Run:  python creatives/inject_logos.py
"""
import os
import re
import io
import base64
from PIL import Image

HERE = os.path.dirname(__file__)
DASH = os.path.normpath(os.path.join(HERE, "..", "dash"))
SRC = os.path.join(HERE, "TLM__logo_white.avif")

NAVY = (38, 48, 59)        # #26303B — dark slate-blue, for the light dashboard
WHITE = (255, 255, 255)    # for the dark slate login


def recolour(im, rgb):
    """Keep the alpha (shape/anti-aliasing); replace RGB with a flat colour."""
    alpha = im.split()[3]
    out = Image.new("RGBA", im.size, rgb + (0,))
    out.putalpha(alpha)
    return out


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
    im = im.crop(bbox)
    print(f"cropped logo to {im.size}")

    navy_png = os.path.join(HERE, "TLM_logo_navy.png")
    recolour(im, NAVY).save(navy_png)   # keep a reference copy of the recoloured asset
    print(f"  wrote {os.path.basename(navy_png)}")

    set_img_src(os.path.join(DASH, "dashboard.html"), "brandlogo", data_uri(recolour(im, NAVY)))
    set_img_src(os.path.join(DASH, "main.py"), "client", data_uri(recolour(im, WHITE)))
    print("done.")


if __name__ == "__main__":
    main()
