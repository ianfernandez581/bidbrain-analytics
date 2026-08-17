#!/usr/bin/env python3
"""Generate the portal's inline Feedback Loop pane from the standalone prototype.

The Feedback Loop renders as INLINE CONTENT inside the portal page (a `.bbpane`
sibling of Overview / Data Accuracy / The Grid / The Brain) — not an iframe. That
is what makes the portal's own cursor glow, background and hover feel continuous
across it: there is only one document.

    prototypes/transmission-feedback-v0/index.html      (standalone, file:// preview)
                     |  this script
                     v
    bidbrain-platform/dash/templates/_feedback_loop_pane.html   (Jinja include)
    bidbrain-platform/dash/templates/feedback_loop_sample.json  (seed data)

Transformations applied on the way (each one exists because inline content shares
the portal's document, where the standalone page owned it alone):

  CSS   every selector is scoped under `.feedback-loop-pane`, so nothing collides
        with the portal's own `.wrap` / `.btn` / `.spacer` rules. `:root` custom
        properties move onto the pane (scoped, cannot leak out); the `body` rule
        keeps only typography (its background/margin would fight the portal's).
        The scrollbar rules stay global but gate on `html.fbl-on`, so the branded
        scrollbar applies to the MAIN page scroll only while this tab is open and
        no other tab's appearance changes.
  DOM   the standalone chrome is dropped — topbar, wordmark and tab rail all
        already exist on the portal page. The sample pill and the window/freshness
        line are kept and move into the pane's own header row.
  GLOW  the prototype's `#cursorGlow` is removed entirely. The portal already
        paints `.bb-cursor-glow` across the whole document, so reusing it is what
        guarantees ONE unified glow rather than two overlapping ones.
  IDS   ids are prefixed `fbl-` in both markup and script, so the pane can never
        collide with a portal id (`#app`, `#data`, `#metrics` are generic enough
        to be worth defending even though nothing collides today).

RE-RUN AFTER ANY EDIT to index.html or sample_data.json, then redeploy:

    .\\.venv\\Scripts\\python.exe prototypes\\transmission-feedback-v0\\make_portal_template.py
    .\\bidbrain-platform\\dash\\deploy_dash_platform.ps1
"""
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEST = HERE.parent.parent / "bidbrain-platform" / "dash" / "templates"

PANE = ".feedback-loop-pane"
ROOT = "html.fbl-on"
SENTINEL = "__FEEDBACK_DATA_JSON__"

# ids that get an `fbl-` prefix in both the markup and the script
IDS = ["data", "samplePill", "windowLine", "fClient", "fPeriod", "fType", "fSent",
       "fQ", "btnClear", "btnLog", "btnPrint", "metrics", "app", "btnZeroClear",
       "footNote", "btnVis"]

# selectors that exist only to support the standalone page — dropped wholesale
DROP_SELECTORS = {
    "#cursorGlow",
    ".topbar", ".topbar .brand b", ".topbar .brand span",
    ".wordmark", ".wordmark .dot",
    ".tabs", ".tab", ".tab:hover", ".tab.active",
    ".topbar, .wordmark, .window-line, .wrap, footer",
    "*, *::before, *::after",
}
# body declarations worth keeping once the portal owns the page background
BODY_KEEP = {"color", "font", "-webkit-font-smoothing", "letter-spacing"}


def strip_comments(css):
    """Remove /* */ comments. Without this a comment sitting above a rule is read as
    part of that rule's selector, and its internal commas split into bogus selectors."""
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def split_blocks(css):
    """Yield (at_rule_or_None, selector, body) for each top-level block."""
    out, i, n = [], 0, len(css)
    while i < n:
        brace = css.find("{", i)
        if brace == -1:
            break
        head = css[i:brace].strip()
        depth, j = 1, brace + 1
        while j < n and depth:
            if css[j] == "{":
                depth += 1
            elif css[j] == "}":
                depth -= 1
            j += 1
        body = css[brace + 1:j - 1]
        out.append((head, body) if head.startswith("@") else (None, head, body))
        if head.startswith("@"):
            out[-1] = (head, None, body)
        i = j
    return out


def scope_selector(sel):
    """Rewrite one selector for life inside the portal document. None = drop it."""
    sel = sel.strip()
    if not sel or sel in DROP_SELECTORS or sel.startswith(".embedded"):
        return None
    if sel == ":root":
        return PANE
    if sel == "html":
        return ROOT
    if sel == "body":
        return PANE
    if sel.startswith("::-webkit-scrollbar"):
        return ROOT + sel
    parts = []
    for one in sel.split(","):
        one = one.strip()
        if not one:
            continue
        if one.startswith(".embedded"):
            continue
        parts.append(one if one.startswith(PANE) else PANE + " " + one)
    return ", ".join(parts) or None


def filter_body_decls(body):
    keep = []
    for decl in body.split(";"):
        if ":" not in decl:
            continue
        prop = decl.split(":", 1)[0].strip()
        if prop in BODY_KEEP:
            keep.append(decl.strip())
    keep.append("background: transparent")   # the portal paints the page, not us
    return "; ".join(keep) + ";"


def scope_css(css):
    out = []
    for block in split_blocks(strip_comments(css)):
        if len(block) == 3 and block[0] and block[0].startswith("@"):
            at, _, inner = block
            nested = scope_css(inner)
            if nested.strip():
                out.append("%s{\n%s\n}" % (at, nested))
            continue
        _, sel, body = block
        new_sel = scope_selector(sel)
        if not new_sel:
            continue
        if sel.strip() == "body":
            body = filter_body_decls(body)
        out.append("%s{%s}" % (new_sel, body))
    return "\n".join(out)


def prefix_ids(text):
    for i in IDS:
        text = text.replace('id="%s"' % i, 'id="fbl-%s"' % i)
        text = text.replace("getElementById('%s')" % i, "getElementById('fbl-%s')" % i)
        text = text.replace("getElementById(\"%s\")" % i, "getElementById(\"fbl-%s\")" % i)
    return text


def main():
    html = (HERE / "index.html").read_text(encoding="utf-8")

    css = re.search(r"<style>(.*?)</style>", html, re.S).group(1)
    scripts = re.findall(r'<script(?![^>]*\bsrc=)([^>]*)>(.*?)</script>', html, re.S)
    body = re.search(r"<body>(.*?)</body>", html, re.S).group(1)

    # The prototype's <head> one-liner (embedded-mode detection) is dropped; its main block
    # holds the glow IIFE AND the app IIFE, so keep only the part after the APP marker —
    # the portal already paints the glow.
    APP_MARKER = "/* ═══ APP ═══ */"
    combined = next(b for a, b in scripts if "application/json" not in a and "JSON.parse" in b)
    if APP_MARKER not in combined:
        raise SystemExit("ERROR: APP marker missing from index.html — cannot separate the glow IIFE")
    app_js = combined.split(APP_MARKER, 1)[1]
    assert "JSON.parse" in app_js and "cursorGlow" not in app_js, "app/glow split failed"

    # --- markup: keep only the parts the portal does not already provide
    toolbar = re.search(r'(<div class="toolbar">.*?</div>\s*</div>)', body, re.S).group(1)
    # greedy on purpose: run to the LAST </div> before <footer>, i.e. the wrap's own close
    content = re.search(r'(<div class="wrap">\s*<div class="metrics".*</div>)\s*<footer', body, re.S).group(1)
    footer = re.search(r"(<footer\b[^>]*>.*?</footer>)", body, re.S).group(1)
    window_line = re.search(r'(<p class="window-line"[^>]*></p>)', body).group(1)
    sample_pill = re.search(r'(<span class="sample-pill"[^>]*>.*?</span>)', body, re.S).group(1)

    # Print summary moves out of the toolbar and up into the header row. The portal's content
    # column is 1080px wide — narrower than the standalone page — and with `flex-wrap: wrap`
    # the browser wraps rather than shrinks, so once the "Filtered — clear all" link appears
    # the row overflowed and orphaned a single button on a second line. Print is the secondary
    # action and the header row is nearly empty, so it lands there next to the sample pill and
    # the search box keeps a usable width.
    print_btn = re.search(r'(<button class="btn btn-secondary" id="btnPrint">.*?</button>)', toolbar, re.S)
    if not print_btn:
        raise SystemExit("ERROR: Print summary button not found in the toolbar")
    toolbar = toolbar.replace(print_btn.group(1), "").replace("\n    \n", "\n")

    pane = (
        '<div class="bbpane feedback-loop-pane" id="pane-feedbackloop">\n'
        '  <div class="fbl-head">\n    %s\n'
        '    <div class="fbl-head-actions">%s%s</div>\n  </div>\n%s\n%s\n%s\n</div>'
        % (window_line, print_btn.group(1), sample_pill, toolbar, content, footer)
    )

    # pane-local styling that only makes sense inline
    extra_css = """
/* --- inline-pane integration (generated) --- */
.feedback-loop-pane .fbl-head{display:flex;align-items:center;justify-content:space-between;
  gap:12px;flex-wrap:wrap;margin:0 0 4px}
.feedback-loop-pane .fbl-head .window-line{text-align:left;margin:0}
.feedback-loop-pane .fbl-head-actions{display:flex;align-items:center;gap:10px;flex:0 0 auto}
/* the portal's .wrap already sets the page gutter — pass through inside the pane */
.feedback-loop-pane .wrap{max-width:none;margin:0;padding:0}
/* Sticks below the portal's own sticky topbar (height measured at runtime).
   It is INVISIBLE until it actually sticks: a flat opaque bar sitting on the portal's
   gradient reads as a separate dark box with a hard border, which is exactly what makes
   an inline pane look bolted on. Margins/padding stay constant in both states so gaining
   the background on scroll cannot shift the layout. */
.feedback-loop-pane .toolbar{top:var(--fbl-top,52px);margin:0 -28px;padding:0 28px;
  background:transparent;border-bottom:0;
  backdrop-filter:none;-webkit-backdrop-filter:none;
  transition:background .18s ease,border-color .18s ease}
.feedback-loop-pane .toolbar.stuck{background:rgba(10,14,22,.92);
  backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);
  border-bottom:1px solid var(--border)}
.feedback-loop-pane .toolbar .wrap{max-width:none}
@media print{
  /* printing the portal with this tab open: drop the portal chrome too, keep the wordmark */
  html.fbl-on .topbar,html.fbl-on .bbtabs,html.fbl-on .bbsyncbar{display:none !important}
  html.fbl-on .bb-cursor-glow,html.fbl-on .bbh-stage{display:none !important}
}
"""

    integration_js = """
/* --- inline-pane integration (generated) ---
   The portal's own .bb-cursor-glow already covers this pane, so there is deliberately
   no glow code here: one document, one glow. This only syncs the branded scrollbar and
   the sticky offset to whether the tab is showing. */
(function(){
  'use strict';
  var pane = document.getElementById('pane-feedbackloop');
  if (!pane) return;
  var root = document.documentElement;
  function apply(on){
    root.classList.toggle('fbl-on', on);
    if (on){
      var bar = document.querySelector('.topbar');
      if (bar) pane.style.setProperty('--fbl-top', Math.round(bar.getBoundingClientRect().height) + 'px');
    }
  }
  function sync(){ apply(pane.classList.contains('on')); }
  // Read the clicked tab directly: synchronous, and independent of whether our
  // listener runs before or after the portal's own tab handler.
  var rail = document.querySelector('.bbtabs');
  if (rail) rail.addEventListener('click', function(e){
    var t = e.target && e.target.closest && e.target.closest('.bbtab');
    if (t) apply(t.dataset.pane === 'feedbackloop');
  });
  // Safety net for any other code path that shows/hides panes (MutationObserver is async).
  new MutationObserver(sync).observe(pane, { attributes:true, attributeFilter:['class'] });
  window.addEventListener('resize', sync);

  // The toolbar only paints a background once it is actually stuck, so at rest it is
  // invisible against the portal's gradient instead of a dark band with a border.
  var tb = pane.querySelector('.toolbar');
  function stuck(){
    if (!tb) return;
    var top = parseFloat(getComputedStyle(tb).top) || 0;
    tb.classList.toggle('stuck', tb.getBoundingClientRect().top <= top + 1);
  }
  window.addEventListener('scroll', stuck, { passive:true });
  window.addEventListener('resize', stuck);

  sync();
  stuck();
})();
"""

    out = (
        "{# GENERATED by prototypes/transmission-feedback-v0/make_portal_template.py\n"
        "   Do not edit by hand — edit the prototype and re-run that script. #}\n"
        "<style>\n%s\n%s</style>\n%s\n"
        '<script id="fbl-data" type="application/json">%s</script>\n'
        "<script>\n%s\n%s</script>\n"
        % (scope_css(css), extra_css, prefix_ids(pane), SENTINEL,
           prefix_ids(app_js).strip(), integration_js)
    )
    (DEST / "_feedback_loop_pane.html").write_text(out, encoding="utf-8")

    sample = (HERE / "sample_data.json").read_text(encoding="utf-8")
    json.loads(sample)   # refuse to vendor a broken sample
    (DEST / "feedback_loop_sample.json").write_text(sample, encoding="utf-8")

    print("vendored -> %s" % (DEST / "_feedback_loop_pane.html"))
    print("vendored -> %s" % (DEST / "feedback_loop_sample.json"))
    print("portal.html includes the pane; main.py substitutes %s at request time" % SENTINEL)


if __name__ == "__main__":
    main()
