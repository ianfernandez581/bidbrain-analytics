r"""Apply (or re-apply) the BB LOGIN KIT to every client dashboard's login page.

    .\.venv\Scripts\python.exe scripts\apply_login_kit.py            # all targets
    .\.venv\Scripts\python.exe scripts\apply_login_kit.py mongodb    # one
    .\.venv\Scripts\python.exe scripts\apply_login_kit.py --check
    .\.venv\Scripts\python.exe scripts\apply_login_kit.py --revert

The login page is the first thing a client sees and the plainest thing in the estate: a centred
white or dark card, a bare input, a button with no press. This adds a slow brand wash, an
arriving card, one hover/press/focus vocabulary - and three pieces of REAL behaviour: show/hide
password, a Caps Lock warning, and a submit state that stops a double post.

Every target's LOGIN_HTML lives inside a triple-quoted string in `dash/main.py`, and is rendered
through JINJA (`render_template_string`), so nothing injected may contain `{{`, `{%` or `{#`.
That is asserted, not assumed - see FORBIDDEN.

DELIBERATE EXCLUSIONS:
  - client_cloudflare : its dark-glow login was re-skinned to match its own motion layer already.
  - client_sophiie    : left alone on purpose, like its dashboard.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from string import Template

ROOT = Path(__file__).resolve().parent.parent
TPL = Path(__file__).resolve().parent / "motion_kit"

# page  : the BODY background behind the card ('dark' | 'light') - drives the wash alphas
# card  : the CARD background ('dark' | 'light') - drives the toggle / hint / placeholder colours
# accent: the ring, caret and glow. The brand accent, except where that colour cannot carry a 1px
#         edge on its own card (geyervalmont's lime is a FILL, so its citron --accent-edge is
#         used; cityperfume rings in its champagne gold rather than its near-black button).
# wash  : False on a login that already carries its own decorative layers and does not want more.
CLIENTS: dict[str, dict] = {
    "STT":             dict(page="dark",  card="light", accent=(214, 40, 40),
                            orbs=[(214, 40, 40), (14, 124, 134), (185, 116, 0)]),
    "bellshakespeare": dict(page="light", card="light", accent=(62, 107, 79),
                            orbs=[(90, 138, 110), (160, 190, 165), (62, 107, 79)]),
    "caltex":          dict(page="dark",  card="dark",  accent=(228, 0, 43),
                            orbs=[(228, 0, 43), (46, 140, 166), (255, 59, 84)]),
    "cityperfume":     dict(page="dark",  card="light", accent=(176, 141, 87),
                            orbs=[(176, 141, 87), (201, 139, 122), (142, 110, 124)]),
    # geocon's DASHBOARD is monochrome near-black, but its LOGIN is the inverse - warm light grey
    # concrete with a paper cell - so the login palette is light and the accent is the brand's
    # near-black ink, not the off-white it uses on the dark dashboard. Getting this backwards makes
    # the show/hide toggle white-on-white.
    "geocon":          dict(page="light", card="light", accent=(10, 10, 10), wash=False,
                            orbs=[(10, 10, 10), (107, 107, 104), (10, 10, 10)]),
    "geyervalmont":    dict(page="light", card="light", accent=(185, 206, 0),
                            orbs=[(230, 255, 49), (233, 253, 94), (87, 65, 30)]),
    "hireright":       dict(page="dark",  card="light", accent=(237, 28, 36),
                            orbs=[(237, 28, 36), (74, 131, 199), (42, 165, 176)]),
    "mongodb":         dict(page="dark",  card="dark",  accent=(0, 237, 100),
                            orbs=[(0, 237, 100), (0, 184, 124), (72, 216, 136)]),
    "nextsmile":       dict(page="light", card="light", accent=(43, 108, 230),
                            orbs=[(43, 108, 230), (176, 137, 90), (91, 143, 240)]),
    "proptrack":       dict(page="dark",  card="light", accent=(31, 111, 235),
                            orbs=[(31, 111, 235), (76, 141, 255), (34, 211, 238)]),
    "resetdata":       dict(page="dark",  card="dark",  accent=(232, 74, 111),
                            orbs=[(232, 74, 111), (72, 130, 255), (232, 74, 111)]),
    "schneider":       dict(page="dark",  card="light", accent=(0, 149, 48),
                            orbs=[(0, 149, 48), (62, 99, 150), (196, 144, 46)]),
    "schneiderlqai":   dict(page="dark",  card="light", accent=(0, 149, 48),
                            orbs=[(0, 149, 48), (18, 181, 201), (62, 99, 150)]),
    "schneidersecpwr": dict(page="dark",  card="light", accent=(0, 149, 48),
                            orbs=[(0, 149, 48), (62, 99, 150), (40, 103, 178)]),
    "tlm":             dict(page="dark",  card="dark",  accent=(79, 114, 144),
                            orbs=[(189, 107, 76), (79, 114, 144), (189, 107, 76)]),
    "vmch":            dict(page="dark",  card="light", accent=(235, 51, 0),
                            orbs=[(235, 51, 0), (76, 39, 54), (46, 139, 114)]),
}
EXTRA_TARGETS = {"cityperfume_total": ("clients/client_cityperfume/dash_total/main.py", "cityperfume")}

# The platform front door + the Extrablack tenant portal are STANDALONE Jinja templates, not a
# LOGIN_HTML string inside a main.py, so the whole file is the block. Extrablack already carries
# its own ambient field (glow + halftone + the services rail) and its card is `.login-card`, which
# the kit's entrance rule deliberately does not name - it gets the behaviour and the press/focus
# vocabulary, nothing that could reorder its existing layers.
TEMPLATE_TARGETS: dict[str, dict] = {
    "platform": dict(path="bidbrain-platform/dash/templates/login.html",
                     page="dark", card="dark", accent=(76, 141, 255),
                     orbs=[(76, 141, 255), (110, 168, 255), (61, 220, 132)]),
    "extrablack": dict(path="bidbrain-platform/dash/templates/extrablack_login.html",
                       page="dark", card="dark", accent=(255, 160, 46), wash=False,
                       orbs=[(255, 160, 46), (255, 246, 234), (255, 160, 46)]),
}

# The four logins that already paint their own static wash (body::before) take it lower, so the
# two do not stack into a haze.
QUIET_WASH = {"bellshakespeare", "caltex", "nextsmile", "geyervalmont"}
WASH_A = {"dark": (0.20, 0.14, 0.11), "light": (0.13, 0.09, 0.08)}

MARKERS = {
    "css": ("/* BB-LOGIN-KIT:css v1 */", "/* /BB-LOGIN-KIT:css */"),
    "fx":  ("<!-- BB-LOGIN-KIT:fx v1 -->", "<!-- /BB-LOGIN-KIT:fx -->"),
    "pw":  ("<!-- BB-LOGIN-KIT:pw v1 -->", "<!-- /BB-LOGIN-KIT:pw -->"),
    "js":  ("<!-- BB-LOGIN-KIT:js v1 -->", "<!-- /BB-LOGIN-KIT:js -->"),
}
# Jinja renders these templates, so an injected `{{` or `{%` would be parsed as markup and blow up
# the login page. `"""` would end the Python string literal the whole page lives in.
FORBIDDEN = ("{{", "{%", "{#", '"""')

FX_DIV = ('\n<div class="bb-lgfx" aria-hidden="true">'
          '<span class="o1"></span><span class="o2"></span><span class="o3"></span></div>')


def rgba(rgb, a):
    return f"{rgb[0]},{rgb[1]},{rgb[2]},{a}"


def css_for(key: str, cfg: dict) -> str:
    a1, a2, a3 = WASH_A[cfg["page"]]
    if key in QUIET_WASH:
        a1, a2, a3 = a1 * 0.55, a2 * 0.55, a3 * 0.55
    ac, orbs = cfg["accent"], cfg["orbs"]
    dark_card = cfg["card"] == "dark"
    subs = dict(
        ACCENT=f"rgb({ac[0]},{ac[1]},{ac[2]})",
        GLOW=f"rgba({rgba(ac, 0.42)})",
        MUTED="rgba(255,255,255,.52)" if dark_card else "rgba(0,0,0,.45)",
        LINE="rgba(255,255,255,.20)" if dark_card else "rgba(0,0,0,.14)",
        TINT=f"rgba({rgba(ac, 0.10)})",
        WARN="#F5B942" if dark_card else "#9A6400",
        ORB1=rgba(orbs[0], round(a1, 3)), ORB2=rgba(orbs[1], round(a2, 3)),
        ORB3=rgba(orbs[2], round(a3, 3)),
    )
    return Template((TPL / "login_css.tpl").read_text(encoding="utf-8")).substitute(subs)


def wrap(kind: str, body: str) -> str:
    for bad in FORBIDDEN:
        if bad in body:
            raise SystemExit(f"  ! login kit '{kind}' contains the forbidden literal {bad!r}")
    a, b = MARKERS[kind]
    return f"{a}{body}{b}"


def span(text: str, kind: str):
    """(start, end) of a marked block, or None."""
    a, b = MARKERS[kind]
    i = text.find(a)
    if i < 0:
        return None
    j = text.find(b, i)
    if j < 0:
        raise SystemExit(f"  ! unterminated {kind} marker")
    return i, j + len(b)


def strip_all(block: str) -> str:
    """Remove every kit insertion, restoring the bare <input> from inside the pw wrapper. The
    padded region collapses back to the single newline that was there before it, so an
    apply -> revert round trip is byte-identical to the original."""
    s = span(block, "pw")
    if s:
        inner = block[s[0]:s[1]]
        m = re.search(r'<input[^>]*>', inner, re.S)
        block = block[:s[0]] + (m.group(0) if m else "") + block[s[1]:]
    for kind in ("css", "fx", "js"):
        a, b = MARKERS[kind]
        pat = re.compile(r"\n?[ \t]*" + re.escape(a) + r".*?" + re.escape(b) + r"[ \t]*\n?", re.S)
        block = pat.sub("\n", block)
    return block


def build(key: str, cfg: dict, block: str) -> str:
    block = strip_all(block)

    # 1. CSS, last thing in the stylesheet so it wins the cascade
    i = block.index("</style>")
    block = block[:i] + wrap("css", "\n" + css_for(key, cfg)) + "\n" + block[i:]

    # 2. the wash, first child of <body> (position:fixed, so it is not a flex item)
    if cfg.get("wash", True):
        m = re.search(r"<body[^>]*>", block)
        if not m:
            raise SystemExit(f"  ! {key}: no <body> in LOGIN_HTML")
        block = block[:m.end()] + wrap("fx", FX_DIV) + block[m.end():]

    # 3. the password field gets its reveal control + the Caps Lock hint
    inputs = list(re.finditer(r'<input[^>]*type="password"[^>]*>', block, re.S))
    if len(inputs) != 1:
        raise SystemExit(f"  ! {key}: expected 1 password input, found {len(inputs)}")
    m = inputs[0]
    # the Caps Lock hint ships EMPTY - the script fills it only while Caps Lock is actually on, so
    # a screen reader never reads a permanent "Caps Lock is on" out of the live region
    pw = (f'\n    {m.group(0)}'
          f'\n    <button class="bb-pw-t" type="button" aria-label="Show password">Show</button>'
          f'\n  </div>'
          f'\n  <div class="bb-caps" role="status" aria-live="polite"></div>')
    block = block[:m.start()] + wrap("pw", '<div class="bb-pw">' + pw + "\n  ") + block[m.end():]

    # 4. the behaviour, last thing on the page
    i = block.rindex("</body>")
    block = block[:i] + wrap("js", (TPL / "login_js.tpl").read_text(encoding="utf-8")) + block[i:]
    return block


def process(path: Path, key: str, cfg: dict, revert: bool, check: bool) -> bool:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".html":              # a standalone template: the file IS the block
        i, j = 0, len(text)
    else:                                  # a LOGIN_HTML string inside a main.py
        i = text.index('LOGIN_HTML = """')
        j = text.index('"""', i + 16)
    block = text[i:j]
    if check:
        have = [k for k in MARKERS if MARKERS[k][0] in block]
        print(f"  {key:20s} {'login kit v1: ' + ','.join(sorted(have)) if have else 'no kit'}")
        return False
    new = strip_all(block) if revert else build(key, cfg, block)
    if new == block:
        return False
    path.write_text(text[:i] + new + text[j:], encoding="utf-8", newline="\n")
    return True


def main(argv):
    revert, check = "--revert" in argv, "--check" in argv
    only = [a.lower() for a in argv if not a.startswith("-")]

    targets = [(k, ROOT / f"clients/client_{k}/dash/main.py", c) for k, c in CLIENTS.items()]
    targets += [(k, ROOT / rel, CLIENTS[src]) for k, (rel, src) in EXTRA_TARGETS.items()]
    targets += [(k, ROOT / c["path"], c) for k, c in TEMPLATE_TARGETS.items()]
    if only:
        targets = [t for t in targets if t[0].lower() in only]
        if not targets:
            raise SystemExit(f"no target matches {only}. "
                             f"Known: {sorted(list(CLIENTS) + list(EXTRA_TARGETS) + list(TEMPLATE_TARGETS))}")

    changed = 0
    for key, path, cfg in targets:
        if not path.exists():
            print(f"  ! {key}: {path} missing")
            continue
        did = process(path, key, cfg, revert, check)
        changed += bool(did)
        if not check:
            print(f"  {key:20s} {'reverted' if revert else 'applied'}{'' if did else ' (no change)'}")
    if not check:
        print(f"\n{changed} file(s) written.")


if __name__ == "__main__":
    main(sys.argv[1:])
