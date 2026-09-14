r"""Derive the Lacevo surface variants from the supplied master artwork.

REPLACES the old `gen_logo.py`, which fabricated a placeholder droplet and was deleted the day the
real art landed (the `client_sophiie` precedent: a generator whose only remaining effect would be to
overwrite real artwork is a liability, not a tool).

THE PROBLEM THIS SOLVES
-----------------------
The supplied file is a stacked lockup - droplet above wordmark - in near-black ink on a SOLID WHITE
background, with no alpha channel at all. Every surface it has to appear on in this dashboard is
DARK: the topbar is ink `#1C1C1C` and the login card is `#242220`. Dropped in as supplied it would
paint a white rectangle on both, and recolouring it to bone without first removing the background
would paint a bone rectangle instead.

So the white is keyed out by LUMINANCE, not by a colour match: `alpha = 255 - L`, with the RGB then
set flat to the target colour. That keeps every antialiased edge pixel at its correct partial
opacity, which a threshold or a "replace white with transparent" pass destroys - the mark would
acquire a ragged white fringe on a dark ground, which is exactly the tell of a logo someone
key-dropped badly.

WHAT IT WRITES
--------------
  dash/logo.png   full lockup, INK       - the login card (WHITE), served at /logo.png
  dash/icon.png   droplet only, CLAY     - the browser tab icon, served at /icon.png
  (file)          horizontal lockup, BONE - base64, for the inline topbar mark (the topbar is ink)

The two lockups are opposite colourways ON PURPOSE: the dashboard's topbar is the brand's black
site furniture, and the login is a white page. One asset cannot serve both.

The topbar mark is INLINE base64 rather than a file on purpose: a root-relative asset path does not
resolve behind the platform proxy at `/d/lacevo/`, so `<img src="/logo.png">` inside the dashboard
would 404 once deployed. The login page is served from the service root, so it can use the route.

The favicon is CLAY, not bone: a near-white mark on a browser's light tab strip is invisible, and
clay carries on both light and dark chrome.

    .\.venv\Scripts\python.exe clients\client_lacevo\gen_brand_assets.py
"""
import base64
import io
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
MASTER = HERE / "creatives" / "LACEVO-master.webp"
DASH = HERE / "dash"

BONE = (228, 224, 218)   # #E4E0DA - legible on the INK topbar
INK  = (28, 28, 28)      # #1C1C1C - the master's own colour, for the WHITE login card
CLAY = (150, 95, 72)     # #965F48 - the brand fill, carries on light AND dark browser chrome

# The master separates cleanly: a blank band at rows 79-83 divides the droplet from the wordmark.
# Found by horizontal ink projection rather than hardcoded from a ruler, so a re-export with
# different padding still splits correctly.
SPLIT_SEARCH = (0.30, 0.65)   # look for the gap in this vertical band of the ink span


def _ink(img):
    """Ink strength 0-255 from luminance. White paper -> 0, black ink -> 255."""
    return 255 - np.asarray(img.convert("L")).astype(int)


def _split_row(ink):
    """The blank band between the droplet and the wordmark."""
    rows = ink.sum(axis=1)
    thresh = rows.max() * 0.01
    nz = np.where(rows > thresh)[0]
    top, bot = int(nz.min()), int(nz.max())
    lo = top + int((bot - top) * SPLIT_SEARCH[0])
    hi = top + int((bot - top) * SPLIT_SEARCH[1])
    blank = [y for y in range(lo, hi + 1) if rows[y] < thresh]
    if not blank:
        raise SystemExit("no blank band between mark and wordmark - check the master export")
    return top, bot, blank[0], blank[-1]


def _tint(ink, rgb, pad=6):
    """Flat-colour RGBA at `rgb`, alpha taken from ink strength, cropped tight then padded."""
    ys, xs = np.where(ink > 6)
    if not len(ys):
        raise SystemExit("no ink found")
    y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
    a = ink[y0:y1 + 1, x0:x1 + 1]
    h, w = a.shape
    out = np.zeros((h + pad * 2, w + pad * 2, 4), dtype=np.uint8)
    out[pad:pad + h, pad:pad + w, 0] = rgb[0]
    out[pad:pad + h, pad:pad + w, 1] = rgb[1]
    out[pad:pad + h, pad:pad + w, 2] = rgb[2]
    out[pad:pad + h, pad:pad + w, 3] = np.clip(a, 0, 255).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


def _square(img, size=512):
    """Centre on a transparent square - a favicon that is not square gets stretched."""
    s = max(img.size)
    canvas = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    canvas.paste(img, ((s - img.width) // 2, (s - img.height) // 2), img)
    return canvas.resize((size, size), Image.LANCZOS)


def main():
    if not MASTER.exists():
        raise SystemExit(f"master artwork missing: {MASTER}")
    src = Image.open(MASTER)
    ink = _ink(src)
    top, bot, gap0, gap1 = _split_row(ink)
    print(f"master {src.size[0]}x{src.size[1]} | ink rows {top}-{bot} | gap {gap0}-{gap1}")

    mark_ink = ink[top:gap0, :]          # the droplet
    full_ink = ink[top:bot + 1, :]       # the whole lockup

    # 1. login card: the full lockup in INK, at 2x its display size.
    #    INK, not bone, because the login is a WHITE page - this is the master's own colour, so the
    #    login shows the artwork as supplied. Sized to the DISPLAY, not to a round number: the
    #    master is 300x166, so anything past ~2x upscales a low-res source and pays in bytes for
    #    detail that is not in the file.
    lockup = _tint(full_ink, INK)
    lockup = lockup.resize((lockup.width * 2, lockup.height * 2), Image.LANCZOS)
    lockup.save(DASH / "logo.png", "PNG", optimize=True)
    print(f"  dash/logo.png  {lockup.size[0]}x{lockup.size[1]} INK lockup "
          f"({(DASH / 'logo.png').stat().st_size:,} bytes)")

    # 2. favicon: the droplet in clay, square. 192px covers a browser tab, a bookmark and an
    #    Android home-screen icon; 512 was four times the bytes for a 16px surface.
    icon = _square(_tint(mark_ink, CLAY), 192)
    icon.save(DASH / "icon.png", "PNG", optimize=True)
    print(f"  dash/icon.png  192x192 clay droplet ({(DASH / 'icon.png').stat().st_size:,} bytes)")

    # 3. topbar: a HORIZONTAL lockup in bone, as base64 for inlining.
    #
    #    Why compose one rather than use the supplied stacked lockup: a stacked mark-over-wordmark
    #    does not fit a 50px horizontal bar without shrinking the wordmark to noise. The obvious
    #    alternative - the droplet beside the word "Lacevo" set in Instrument Sans, which is what
    #    the placeholder build did - puts a GROTESQUE next to the brand's own SERIF wordmark, and
    #    a font mismatch that size reads as a mistake rather than a choice.
    #
    #    So this places the master's own two elements side by side, unmodified and at their native
    #    proportions, vertically centred on the wordmark's optical middle. Nothing is redrawn or
    #    retyped. It is still a DERIVED arrangement: if Lacevo supply an official horizontal
    #    lockup, drop it in and delete this step (see README -> "The logo").
    mark = _tint(mark_ink, BONE, pad=0)
    word = _tint(ink[gap1 + 1:bot + 1, :], BONE, pad=0)

    # scale the droplet so it stands a little above the wordmark's cap height, the usual
    # relationship in a horizontal lockup
    target_h = int(word.height * 1.45)
    mark_r = mark.resize((max(1, round(mark.width * target_h / mark.height)), target_h), Image.LANCZOS)
    gap = int(mark_r.width * 0.34)
    W = mark_r.width + gap + word.width
    H = max(mark_r.height, word.height)
    lock = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    lock.paste(mark_r, (0, (H - mark_r.height) // 2), mark_r)
    lock.paste(word, (mark_r.width + gap, (H - word.height) // 2), word)
    # Rendered at 34px tall in the bar, so ~68px is the 2x retina target. The composition above is
    # already near that height at native resolution - upscaling it further only inflates the base64
    # that ships inside every page load.
    _disp_h = 68
    lock = lock.resize((max(1, round(lock.width * _disp_h / lock.height)), _disp_h), Image.LANCZOS)

    buf = io.BytesIO()
    lock.save(buf, "PNG", optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode()
    (HERE / "creatives" / "topbar_lockup.b64.txt").write_text(b64, encoding="utf-8")
    (HERE / "creatives" / "topbar_lockup.png").write_bytes(buf.getvalue())   # for eyeballing
    print(f"  topbar lockup  {lock.size[0]}x{lock.size[1]} bone horizontal, "
          f"{len(b64):,} base64 chars -> creatives/topbar_lockup.b64.txt")
    print("\nInline that base64 as the <img> in dashboard.html's .brandmark (see README).")


if __name__ == "__main__":
    main()
