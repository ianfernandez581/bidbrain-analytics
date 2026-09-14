r"""Generate `dash/logo.png` - a PLACEHOLDER Lacevo mark.

THIS IS NOT THE BRAND ASSET. It is the same droplet geometry as the placeholder `<svg>` in the
approved preview file, rendered to a PNG because main.py serves `/logo.png` for the login page and
the browser tab icon. Replace it the moment the real Lacevo droplet lands:

    1. drop the supplied artwork in as clients/client_lacevo/dash/logo.png (square, >=256px), and
    2. replace the inline <svg class="mark"> in dash/dashboard.html - the topbar mark is INLINE on
       purpose, because a root-relative asset path does not resolve behind the platform proxy at
       /d/lacevo/ (the geyervalmont "logo ships twice" gotcha).
    3. DELETE this script. Its only remaining effect would be to overwrite the real artwork - which
       is exactly what happened on client_sophiie, where the equivalent generator was deleted the
       day the real mark arrived.

    .\.venv\Scripts\python.exe clients\client_lacevo\gen_logo.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent / "dash" / "logo.png"

BONE = (228, 224, 218, 255)    # #E4E0DA - the droplet body
CLAY = (150, 95, 72, 255)      # #965F48

S = 512          # final size
SS = 4           # supersample factor - draw big, downsample once, so the curves are clean


def droplet(d, cx, cy, w, h, fill):
    """A teardrop: a circle for the belly, a triangle for the point. Matches the proportions of the
    reference SVG path (a 17x22 box whose point sits at the top)."""
    r = w / 2
    belly_cy = cy + h / 2 - r
    d.ellipse([cx - r, belly_cy - r, cx + r, belly_cy + r], fill=fill)
    d.polygon([(cx, cy - h / 2), (cx - r, belly_cy + r * 0.16), (cx + r, belly_cy + r * 0.16)],
              fill=fill)


def main():
    n = S * SS
    # TRANSPARENT background, not the brand ink. The mark is served to the login card (#242220),
    # the browser tab and anywhere else a future surface puts it; baking a near-black field into
    # the PNG paints a visible square chip wherever the surface is not exactly that same black,
    # which is precisely what it did on the login card.
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # bone droplet
    droplet(d, n / 2, n / 2, n * 0.40, n * 0.54, BONE)

    # The clay inner curve - the reference mark's single stroke. It must sit INSIDE the bone
    # droplet: the belly is centred on 0.57n with radius 0.20n, so an arc any wider than that reads
    # as a stray crescent stuck to the outside of the shape rather than a line drawn within it.
    # Nudged right of centre so the curve bulges LEFT, matching the reference SVG path.
    lw = max(2, int(n * 0.030))
    bx, by, bw = n * 0.525, n * 0.585, n * 0.115
    d.arc([bx - bw, by - bw, bx + bw, by + bw], start=105, end=255, fill=CLAY, width=lw)

    img.resize((S, S), Image.LANCZOS).save(OUT, "PNG", optimize=True)
    print(f"wrote {OUT} ({OUT.stat().st_size:,} bytes, {S}x{S}) - PLACEHOLDER, swap for the real mark")


if __name__ == "__main__":
    main()
