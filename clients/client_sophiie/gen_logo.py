r"""Generate dash/logo.png - the PLACEHOLDER Sophiie AI mark (aurora curtains on deep navy).

Sophiie have not supplied artwork, and `dash/deploy_dash_sophiie.ps1` hard-fails without a
`dash/logo.png` (the login page and the AI deck builder both need a raster mark). So this renders
one from the brand palette instead of shipping a broken image: the same AURORA CURTAIN motif the
dashboard background animates, frozen into a rounded tile.

It is deliberately dependency-free (zlib + struct, no Pillow - the repo venv has no imaging
library), deterministic, and 3x supersampled so the curves are smooth.

    .\.venv\Scripts\python.exe clients\client_sophiie\gen_logo.py

REPLACING IT with real artwork: drop the supplied PNG in as `dash/logo.png` and delete this file's
output step from your head - nothing imports it. Then re-inline the artwork in the topbar of
`dash/dashboard.html` (base64) and in `dash/main.py`'s LOGIN_HTML, per the "the logo ships twice"
note in README.md. The hand-written SVG twin of this motif lives inline in both of those files.
"""
import math
import os
import struct
import zlib

OUT = os.path.join(os.path.dirname(__file__), "dash", "logo.png")

SIZE = 256          # final pixels (square)
SS = 3              # supersampling factor
RADIUS = 0.27       # corner radius as a fraction of SIZE

BG = (0x14, 0x09, 0x34)          # --s-deep #140934, Sophiie's deep navy
# Aurora curtains, left to right: primary blue -> sky -> cyan -> secondary blue.
# (x_centre, width, colour, phase, amplitude) - all as fractions of the tile.
CURTAINS = [
    (0.26, 0.095, (0x2b, 0x84, 0xb4), 0.35, 0.055),
    (0.42, 0.115, (0x50, 0xaa, 0xe6), 1.90, 0.075),
    (0.60, 0.100, (0x22, 0xd3, 0xee), 3.10, 0.065),
    (0.75, 0.085, (0x20, 0x63, 0x87), 4.70, 0.050),
]


def _rounded_alpha(fx, fy, r):
    """Coverage of the rounded-square tile at fractional coords (0..1). Hard edge; SS smooths it."""
    # distance outside the rounded rect, computed on the inset box
    dx = max(r - fx, fx - (1.0 - r), 0.0)
    dy = max(r - fy, fy - (1.0 - r), 0.0)
    if dx > 0.0 and dy > 0.0:
        return 1.0 if (dx * dx + dy * dy) <= r * r else 0.0
    return 1.0 if (0.0 <= fx <= 1.0 and 0.0 <= fy <= 1.0) else 0.0


def _curtain_alpha(fx, fy, cx, w, phase, amp):
    """Coverage of one swaying vertical light band at fractional coords."""
    # The band sways with a two-term sine (the same shape the canvas animation draws) ...
    sway = (math.sin(fy * 3.1 + phase) * 0.62 + math.sin(fy * 5.3 - phase * 1.3) * 0.30) * amp
    d = abs(fx - (cx + sway))
    half = w * 0.5
    if d >= half:
        return 0.0
    # ... soft across its width (feathered edges) ...
    across = 1.0 - (d / half) ** 1.7
    # ... and fades top and bottom like a real curtain.
    if fy < 0.12:
        along = fy / 0.12
    elif fy > 0.86:
        along = max(0.0, (1.0 - fy) / 0.14)
    else:
        along = 1.0
    return across * (0.35 + 0.65 * along)


def render():
    w = h = SIZE
    rows = []
    for py in range(h):
        row = bytearray()
        for px in range(w):
            acc_r = acc_g = acc_b = acc_a = 0.0
            for sy in range(SS):
                for sx in range(SS):
                    fx = (px + (sx + 0.5) / SS) / w
                    fy = (py + (sy + 0.5) / SS) / h
                    tile = _rounded_alpha(fx, fy, RADIUS)
                    if tile <= 0.0:
                        continue
                    r, g, b = BG
                    for (cx, cw, col, phase, amp) in CURTAINS:
                        a = _curtain_alpha(fx, fy, cx, cw, phase, amp)
                        if a > 0.0:
                            a *= 0.92
                            r = r + (col[0] - r) * a
                            g = g + (col[1] - g) * a
                            b = b + (col[2] - b) * a
                    acc_r += r * tile
                    acc_g += g * tile
                    acc_b += b * tile
                    acc_a += tile
            n = SS * SS
            if acc_a <= 0.0:
                row += b"\x00\x00\x00\x00"
            else:
                row += bytes((int(round(acc_r / acc_a)), int(round(acc_g / acc_a)),
                              int(round(acc_b / acc_a)), int(round(acc_a / n * 255))))
        rows.append(bytes(row))
    return w, h, rows


def write_png(path, w, h, rows):
    raw = b"".join(b"\x00" + r for r in rows)            # filter byte 0 (None) per scanline

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))   # 8-bit RGBA
           + chunk(b"IDAT", zlib.compress(raw, 9))
           + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)


if __name__ == "__main__":
    w, h, rows = render()
    write_png(OUT, w, h, rows)
    print(f"wrote {OUT} ({w}x{h}, {os.path.getsize(OUT):,} bytes)")
