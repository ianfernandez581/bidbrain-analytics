r"""Apply (or re-apply) the BB MOTION KIT to every client dashboard - the portable, subtler
descendant of the premium motion layer built for `client_cloudflare`.

    .\.venv\Scripts\python.exe scripts\apply_motion_kit.py            # apply to every target
    .\.venv\Scripts\python.exe scripts\apply_motion_kit.py mongodb    # just one
    .\.venv\Scripts\python.exe scripts\apply_motion_kit.py --check    # report, change nothing
    .\.venv\Scripts\python.exe scripts\apply_motion_kit.py --revert   # strip the kit back out

WHY A SCRIPT AND NOT 17 HAND EDITS: the kit is one body of CSS + JS that has to be IDENTICAL
everywhere or the estate drifts and a fix has to be found 17 times. Templates live in
scripts/motion_kit/; the only per-client thing is the PALETTE in CLIENTS below. Re-running is
safe: each of the four insertions is wrapped in a marker pair and replaced in place.

WHAT IT TOUCHES, per `clients/client_<c>/dash/dashboard.html`:
  1. a <script> right after the Chart.js tag  - the bootstrap + Chart.js motion defaults
  2. the CSS block, last thing before </style> - so it wins the cascade over what it re-times
  3. two <div>s right after <body>             - the ambient wash + the scroll rail
  4. a <script> right before </body>           - the engine

DELIBERATE EXCLUSIONS:
  - client_cloudflare : has the richer, client-approved original. The kit is its portable subset;
                        do not "unify" them, cloudflare's is signed off as-is.
  - client_sophiie    : its aurora IS its design, and it was explicitly left alone.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from string import Template

ROOT = Path(__file__).resolve().parent.parent
TPL = Path(__file__).resolve().parent / "motion_kit"

# --- per-client palette -------------------------------------------------------------------
# canvas : the PAGE background behind the cards ('dark' | 'light') - drives the wash alphas and
#          the scrollbars.
# surface: what the CARDS are ('dark' | 'light') - drives the hover lift shadow and the table row
#          tint. The two differ on the Schneider dashboards: white cards on a dark green canvas.
# accent : rgb triple used for the focus ring, the scroll rail, the row edge and the glow. Taken
#          from the dashboard's own brand accent - except where that colour cannot carry an edge
#          on its own background (geyervalmont's lime is a FILL, so its --accent-edge citron is
#          used instead; tlm rings in its slate blue but washes in its terracotta glow).
# orbs   : the three wash hues, brand family only. A hue outside the theme reads as a bug.
CLIENTS: dict[str, dict] = {
    "STT":              dict(canvas="light", surface="light", accent=(214, 40, 40),
                             orbs=[(214, 40, 40), (14, 124, 134), (185, 116, 0)]),
    "bellshakespeare":  dict(canvas="light", surface="light", accent=(62, 107, 79),
                             orbs=[(90, 138, 110), (160, 190, 165), (62, 107, 79)]),
    "caltex":           dict(canvas="dark", surface="dark", accent=(228, 0, 43),
                             orbs=[(228, 0, 43), (46, 140, 166), (255, 59, 84)]),
    "cityperfume":      dict(canvas="light", surface="light", accent=(176, 141, 87),
                             orbs=[(176, 141, 87), (201, 139, 122), (142, 110, 124)]),
    "geocon":           dict(canvas="dark", surface="dark", accent=(237, 237, 235),
                             orbs=[(237, 237, 235), (255, 255, 255), (140, 156, 145)]),
    "geyervalmont":     dict(canvas="light", surface="light", accent=(185, 206, 0),
                             orbs=[(230, 255, 49), (233, 253, 94), (87, 65, 30)]),
    "hireright":        dict(canvas="dark", surface="dark", accent=(237, 28, 36),
                             orbs=[(237, 28, 36), (74, 131, 199), (42, 165, 176)]),
    "mongodb":          dict(canvas="dark", surface="dark", accent=(0, 237, 100),
                             orbs=[(0, 237, 100), (0, 184, 124), (72, 216, 136)]),
    "nextsmile":        dict(canvas="light", surface="light", accent=(43, 108, 230),
                             orbs=[(43, 108, 230), (176, 137, 90), (91, 143, 240)]),
    "proptrack":        dict(canvas="dark", surface="dark", accent=(31, 111, 235),
                             orbs=[(31, 111, 235), (76, 141, 255), (34, 211, 238)]),
    "resetdata":        dict(canvas="dark", surface="dark", accent=(232, 74, 111),
                             orbs=[(232, 74, 111), (72, 130, 255), (232, 74, 111)]),
    "schneider":        dict(canvas="dark", surface="light", accent=(0, 149, 48),
                             orbs=[(0, 149, 48), (62, 99, 150), (196, 144, 46)]),
    "schneiderlqai":    dict(canvas="dark", surface="light", accent=(0, 149, 48),
                             orbs=[(0, 149, 48), (18, 181, 201), (62, 99, 150)]),
    "schneidersecpwr":  dict(canvas="dark", surface="light", accent=(0, 149, 48),
                             orbs=[(0, 149, 48), (62, 99, 150), (40, 103, 178)]),
    "tlm":              dict(canvas="light", surface="light", accent=(79, 114, 144),
                             orbs=[(189, 107, 76), (79, 114, 144), (189, 107, 76)]),
    "vmch":             dict(canvas="light", surface="light", accent=(235, 51, 0),
                             orbs=[(235, 51, 0), (76, 39, 54), (46, 139, 114)]),
}

# City Perfume ships TWO web services off one pipeline; the all-sales fork is a front-end copy and
# gets the same treatment or the two drift apart.
EXTRA_TARGETS = {"cityperfume_total": ("clients/client_cityperfume/dash_total/dashboard.html", "cityperfume")}

# The wash is the one thing tuned by CANVAS: light adds over a dark page and subtracts nothing, so
# a dark canvas takes roughly double the alpha before it reads at all.
WASH = {"dark": (0.17, 0.12, 0.10), "light": (0.11, 0.08, 0.07)}
DURATIONS = ("26s", "31s", "35s")

MARKERS = {
    "head": ("<!-- BB-MOTION-KIT:head v1 -->", "<!-- /BB-MOTION-KIT:head -->"),
    "css":  ("/* BB-MOTION-KIT:css v1 */", "/* /BB-MOTION-KIT:css */"),
    "dom":  ("<!-- BB-MOTION-KIT:dom v1 -->", "<!-- /BB-MOTION-KIT:dom -->"),
    "js":   ("<!-- BB-MOTION-KIT:js v1 -->", "<!-- /BB-MOTION-KIT:js -->"),
}


def rgba(rgb, a):
    return f"{rgb[0]},{rgb[1]},{rgb[2]},{a}"


def css_for(cfg) -> str:
    a1, a2, a3 = WASH[cfg["canvas"]]
    ac, orbs = cfg["accent"], cfg["orbs"]
    dark_surface = cfg["surface"] == "dark"
    dark_canvas = cfg["canvas"] == "dark"
    subs = dict(
        ACCENT=f"rgb({ac[0]},{ac[1]},{ac[2]})",
        GLOW=f"rgba({rgba(ac, 0.28 if dark_surface else 0.22)})",
        LIFT=("0 18px 40px -22px rgba(0,0,0,.82),0 0 28px -16px var(--bb-glow)" if dark_surface
              else "0 16px 34px -18px rgba(20,24,28,.28),0 0 26px -16px var(--bb-glow)"),
        LINE="rgba(255,255,255,.12)" if dark_surface else "rgba(0,0,0,.10)",
        ROWHOVER="rgba(255,255,255,.035)" if dark_surface else "rgba(0,0,0,.028)",
        BARSHADOW=("0 20px 44px -32px rgba(0,0,0,.85),0 0 26px -18px var(--bb-glow)" if dark_canvas
                   else "0 16px 34px -28px rgba(20,24,28,.34),0 0 22px -16px var(--bb-glow)"),
        RAIL=(f"var(--bb-accent),rgba({rgba(orbs[1], 0.95)}) 55%,var(--bb-accent)"),
        SBTRACK="rgba(255,255,255,.04)" if dark_canvas else "rgba(0,0,0,.045)",
        SBTHUMB=f"rgba({rgba(ac, 0.40 if dark_canvas else 0.34)})",
        SBTHUMBH=f"rgba({rgba(ac, 0.70 if dark_canvas else 0.60)})",
        ORB1=rgba(orbs[0], a1), ORB2=rgba(orbs[1], a2), ORB3=rgba(orbs[2], a3),
        D1=DURATIONS[0], D2=DURATIONS[1], D3=DURATIONS[2],
    )
    return Template((TPL / "kit_css.tpl").read_text(encoding="utf-8")).substitute(subs)


# Strings an injected block must NEVER contain. The first four would confuse this script's own
# anchors; the last three are literals the PLATFORM PROXY string-replaces across the whole page
# (main.py `_proxy`: /data.json -> /d/<c>/data.json, '/report', /creative-img/). A stray one of
# those inside our CSS or JS - even inside a comment - would be silently rewritten in the proxied
# copy, or worse, would move where the proxy injects its own widgets.
FORBIDDEN = ("</body>", "</head>", "</style>", "<body", "/data.json", "'/report'", "/creative-img/")


def wrap(kind: str, body: str) -> str:
    for bad in FORBIDDEN:
        if bad in body:
            raise SystemExit(f"  ! kit template for '{kind}' contains the forbidden literal "
                             f"{bad!r} - see FORBIDDEN in this script")
    a, b = MARKERS[kind]
    return f"{a}{body}{b}"


def strip_block(text: str, kind: str) -> tuple[str, bool]:
    """Remove a marked block AND the blank line the insertion added, so `--revert` gives a file
    that differs from the original by nothing at all - the whole padded region collapses back to
    the single newline that was there before it."""
    a, b = MARKERS[kind]
    pat = re.compile(r"\n?[ \t]*" + re.escape(a) + r".*?" + re.escape(b) + r"[ \t]*\n?", re.S)
    out, n = pat.subn("\n", text)
    return out, bool(n)


def insert_after(text: str, anchor_re: str, block: str, label: str) -> str:
    m = list(re.finditer(anchor_re, text))
    if len(m) != 1:
        raise SystemExit(f"  ! {label}: expected exactly 1 anchor, found {len(m)} - not touched")
    i = m[0].end()
    return text[:i] + block + text[i:]


def insert_before(text: str, anchor: str, block: str, label: str, last_before: str | None = None) -> str:
    if last_before:                      # e.g. the last </style> that is still inside <head>
        cut = text.index(last_before)
        i = text.rindex(anchor, 0, cut)
    else:
        if text.count(anchor) != 1:
            raise SystemExit(f"  ! {label}: expected exactly 1 '{anchor}', found {text.count(anchor)}")
        i = text.index(anchor)
    return text[:i] + block + text[i:]


def apply_to(path: Path, cfg: dict, revert: bool) -> bool:
    src = original = path.read_text(encoding="utf-8")
    for kind in MARKERS:
        src, _ = strip_block(src, kind)
    if revert:
        if src != original:
            path.write_text(src, encoding="utf-8", newline="\n")
        return src != original

    head = wrap("head", "\n" + (TPL / "kit_head.tpl").read_text(encoding="utf-8"))
    css = wrap("css", "\n" + css_for(cfg))
    dom = wrap("dom", (TPL / "kit_dom.tpl").read_text(encoding="utf-8"))
    js = wrap("js", "\n" + (TPL / "kit_js.tpl").read_text(encoding="utf-8"))

    src = insert_after(src, r"<script src=\"https://cdn\.jsdelivr\.net/npm/chart\.js[^\n]*</script>",
                       "\n" + head, "head bootstrap")
    src = insert_before(src, "</style>", css + "\n", "css block", last_before="</head>")
    src = insert_after(src, r"<body[^>]*>", dom, "wash + rail")
    src = insert_before(src, "</body>", js + "\n", "engine")

    path.write_text(src, encoding="utf-8", newline="\n")
    return src != original


def main(argv):
    revert = "--revert" in argv
    check = "--check" in argv
    only = [a for a in argv if not a.startswith("-")]

    targets: list[tuple[str, Path, dict]] = []
    for key, cfg in CLIENTS.items():
        targets.append((key, ROOT / f"clients/client_{key}/dash/dashboard.html", cfg))
    for key, (rel, cfgkey) in EXTRA_TARGETS.items():
        targets.append((key, ROOT / rel, CLIENTS[cfgkey]))

    if only:
        targets = [t for t in targets if t[0] in only or t[0].lower() in [o.lower() for o in only]]
        if not targets:
            raise SystemExit(f"no target matches {only}. "
                             f"Known: {sorted(list(CLIENTS) + list(EXTRA_TARGETS))}")

    changed = 0
    for key, path, cfg in targets:
        if not path.exists():
            print(f"  ! {key}: {path} missing")
            continue
        if check:
            txt = path.read_text(encoding="utf-8")
            have = [k for k in MARKERS if MARKERS[k][0] in txt]
            print(f"  {key:20s} {'kit v1: ' + ','.join(sorted(have)) if have else 'no kit'}")
            continue
        did = apply_to(path, cfg, revert)
        changed += bool(did)
        print(f"  {key:20s} {'reverted' if revert else 'applied'}{'' if did else ' (no change)'}")
    if not check:
        print(f"\n{changed} file(s) written.")


if __name__ == "__main__":
    main(sys.argv[1:])
