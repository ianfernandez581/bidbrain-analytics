"""Geocon dashboard web app (Cloud Run service).

Thin password gate + static server. It renders a login screen, and once a
session is authenticated it serves `dashboard.html` and proxies the private
`geocon.json` from GCS at `/data.json`. All presentation logic — the Executive /
Media Buyer / Client Story views — lives in `dashboard.html`; this file only
decides *who* may see it, not *what* it shows. It also exposes `/report`, the
AI "Download report" endpoint (Claude Opus 4.8 + web research -> a 3-slide deck;
see report.py), gated and cached the same way as the dashboard data.
"""
import os
import re
import hmac
import json
import hashlib
from pathlib import Path
from flask import (
    Flask, request, redirect, session, Response, render_template_string, abort
)
from google.cloud import storage

from report import generate_report

app = Flask(__name__)
app.secret_key = os.environ["SESSION_SECRET"]
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_SAMESITE="None",  # cross-site iframe on dashboards.bidbrain.ai (None requires Secure)
    PERMANENT_SESSION_LIFETIME=60 * 60 * 12,  # stay logged in 12h
    # Hard cap on request bodies (Werkzeug 413s anything larger). The /report POST is the only
    # sizeable body; everything else is tiny.
    MAX_CONTENT_LENGTH=256 * 1024,
)

# --- config (injected by Cloud Run) ------------------------------------------
DASH_PASSWORD = os.environ["DASH_PASSWORD"].rstrip("\r\n")   # from Secret Manager
GCS_BUCKET = os.environ["GCS_BUCKET"]                        # private data bucket
DATA_OBJECT = os.environ.get("DATA_OBJECT", "geocon.json")   # object inside it

_storage = storage.Client()

# Dashboard HTML is baked into the container at build time, next to this file.
# Anchor to __file__ so it loads regardless of the process working directory.
_dash_dir = Path(__file__).resolve().parent
try:
    DASHBOARD_HTML = (_dash_dir / "dashboard.html").read_text(encoding="utf-8")
except FileNotFoundError:
    DASHBOARD_HTML = None

# Logo PNG baked into the container (COPY'd in the Dockerfile).
try:
    LOGO_PNG = (_dash_dir / "logo.png").read_bytes()
except FileNotFoundError:
    LOGO_PNG = None

# The GEOCON CORPORATE wordmark, used by the login page only (the dashboard header carries the
# Gateway Braddon property logo above). Copied into dash/ on purpose: `creatives/` is NOT in this
# folder's Docker build context, so a path into it 404s once deployed.
try:
    GEOCON_MARK_PNG = (_dash_dir / "geocon-mark.png").read_bytes()
except FileNotFoundError:
    GEOCON_MARK_PNG = None

# Shared, theme-driven slide-deck builder (vendored — the canonical copy is re-copied into each dash
# folder). Served as a static asset so the dashboard's <script src="bb_deck.js"> loads it (relative →
# /bb_deck.js direct, or /d/geocon/bb_deck.js through the platform proxy).
try:
    BB_DECK_JS = (_dash_dir / "bb_deck.js").read_text(encoding="utf-8")
except FileNotFoundError:
    BB_DECK_JS = ""

LOGIN_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Geocon Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Anton&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  /* GEOCON CORPORATE LOGIN - built from the geocon.com.au footer/CTA treatment: warm light-grey
     canvas, near-black heavy CONDENSED uppercase display type, hairline outlined rounded CTA with
     the diagonal arrow the site uses, and the dotted rule it uses as a divider.
     LAYOUT (2026-08-19): ONE CENTRED CELL, so this page matches every other dashboard login in the
     estate (they are all a single centred card). The background carries the brand work instead.
     NOTE the deliberate split: this LOGIN wears GEOCON CORPORATE, while the dashboard behind it
     stays on the dark Gateway Braddon PROPERTY palette (that campaign brand board lives at
     clients/client_geocon/creatives/Gateway-Braddon-Brand-Board.png). Two brands, two jobs - do not
     "unify" them without asking. */
  :root{
    --bg:#EDEDEB;          /* warm light grey sampled from the site footer */
    --card:#F7F7F5;        /* a half-step lighter so the cell reads as paper on concrete */
    --ink:#0A0A0A;
    --muted:#6B6B68;
    --line:rgba(10,10,10,.26);
    --hair:rgba(10,10,10,.09);
    --err:#B3261E;
  }
  *{box-sizing:border-box;margin:0;padding:0}
  html,body{min-height:100%}
  body{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:32px 20px;
       background:var(--bg);color:var(--ink);position:relative;overflow:hidden;
       font-family:"Inter",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
       -webkit-font-smoothing:antialiased}

  /* ---------- background: a DRAFTING SHEET, the honest metaphor for a property developer ----------
     Four stacked layers, all pure CSS (nothing to load, nothing to 404):
       .sheet - a hairline drafting grid with a heavier module every 5th line, masked so it fades
                toward the edges and never reads as a wireframe screenshot.
       .plan  - oversized architectural plan geometry (thin rings + a long diagonal) at very low
                alpha: enough to feel drawn, never enough to compete with the type.
       .band  - the dotted divider from the site, repeated as two long horizons.
       .glow  - a soft centre vignette that lifts the cell off the canvas.
     Keep the alphas LOW: on a light canvas anything past ~.09 stops reading as texture and starts
     reading as clutter. */
  .sheet,.plan,.band,.glow{position:fixed;inset:0;pointer-events:none;z-index:0}
  .sheet{
    background-image:
      linear-gradient(to right, var(--hair) 1px, transparent 1px),
      linear-gradient(to bottom, var(--hair) 1px, transparent 1px),
      linear-gradient(to right, rgba(10,10,10,.05) 1px, transparent 1px),
      linear-gradient(to bottom, rgba(10,10,10,.05) 1px, transparent 1px);
    background-size:26px 26px, 26px 26px, 130px 130px, 130px 130px;
    -webkit-mask-image:radial-gradient(120% 90% at 50% 45%, #000 35%, rgba(0,0,0,.35) 70%, transparent 100%);
            mask-image:radial-gradient(120% 90% at 50% 45%, #000 35%, rgba(0,0,0,.35) 70%, transparent 100%)}
  .plan{opacity:.55}
  .plan i{position:absolute;border:1px solid rgba(10,10,10,.075);border-radius:50%}
  .plan i:nth-child(1){width:78vmin;height:78vmin;left:-16vmin;bottom:-26vmin}
  .plan i:nth-child(2){width:52vmin;height:52vmin;left:-3vmin;bottom:-13vmin}
  .plan i:nth-child(3){width:96vmin;height:96vmin;right:-30vmin;top:-34vmin;border-radius:0;
                       transform:rotate(45deg)}
  .plan b{position:absolute;left:-10%;right:-10%;top:50%;height:1px;background:rgba(10,10,10,.07);
          transform:rotate(-11deg)}
  .band{background-image:radial-gradient(circle, rgba(10,10,10,.5) 1.3px, transparent 1.4px);
        background-size:11px 3px;background-repeat:repeat-x;
        background-position:0 22vh, 0 78vh;opacity:.5}
  /* One slow, almost-imperceptible breath. The page is otherwise dead still: a property developer
     brand should not bounce. Off entirely for reduced-motion users. */
  .glow{background:radial-gradient(46vmax 34vmax at 50% 42%, rgba(255,255,255,.85), transparent 70%);
        animation:breathe 22s ease-in-out infinite}
  @keyframes breathe{0%,100%{opacity:.75;transform:scale(1)}50%{opacity:1;transform:scale(1.04)}}
  @media (prefers-reduced-motion:reduce){.glow{animation:none}}

  /* ---------- the one centred cell ---------- */
  .cell{position:relative;z-index:1;width:100%;max-width:452px;background:var(--card);
        border:1px solid var(--hair);border-radius:16px;padding:38px 34px 26px;
        box-shadow:0 1px 0 rgba(255,255,255,.9) inset, 0 26px 60px -28px rgba(10,10,10,.28),
                   0 3px 10px -6px rgba(10,10,10,.18)}
  /* The supplied wordmark is WHITE type baked onto an OPAQUE BLACK square (no alpha), so it would
     read as a black tile. invert() flips it to black-on-white, then multiply drops the white to the
     surface colour, leaving the wordmark alone the way the site sets it. Keep BOTH properties:
     either one on its own looks broken. The asset is CROPPED to its ink bounds, so this height is
     the height of the LETTERS (as the original 447x447 square it rendered microscopic). */
  .mark img{height:22px;width:auto;display:block;filter:invert(1);mix-blend-mode:multiply}
  .eyebrow{margin-top:22px;font-size:10.5px;font-weight:600;letter-spacing:2.2px;
           text-transform:uppercase;color:var(--muted)}
  h1{font-family:"Anton","Inter",sans-serif;font-weight:400;text-transform:uppercase;
     font-size:clamp(34px,7vw,44px);line-height:.92;letter-spacing:-.3px;margin:8px 0 14px}
  .lede{font-size:13.5px;color:var(--muted);line-height:1.55;margin:0 0 22px}
  form{display:flex;flex-direction:column;gap:10px}
  input{width:100%;padding:16px 18px;font:inherit;font-size:13.5px;letter-spacing:1.3px;
         text-transform:uppercase;color:var(--ink);background:#FFF;
         border:1px solid var(--line);border-radius:10px;outline:none;transition:border-color .16s}
  input::placeholder{color:var(--muted);letter-spacing:1.3px}
  input:focus{border-color:var(--ink)}
  /* the CTA from the site: transparent, hairline border, uppercase label + diagonal arrow, fills on hover */
  button{display:flex;align-items:center;justify-content:space-between;cursor:pointer;
         padding:16px 22px;font:inherit;font-size:13.5px;font-weight:600;letter-spacing:1.5px;
         text-transform:uppercase;color:var(--ink);background:transparent;
         border:1px solid var(--ink);border-radius:10px;
         transition:background-color .18s ease,color .18s ease}
  button .arw{font-size:16px;line-height:1;transition:transform .18s ease}
  button:hover{background:var(--ink);color:var(--card)}
  button:hover .arw{transform:translate(3px,-3px)}
  button:focus-visible{outline:2px solid var(--ink);outline-offset:3px}
  .err{font-size:11.5px;font-weight:600;letter-spacing:1.3px;text-transform:uppercase;
       color:var(--err);min-height:14px}
  .rule{height:3px;margin:22px 0 14px;
        background-image:radial-gradient(circle,var(--ink) 1.3px,transparent 1.4px);
        background-size:11px 3px;background-repeat:repeat-x;opacity:.6}
  /* stacked on purpose: side-by-side half-wraps at this cell width, which looks accidental */
  .meta{display:flex;flex-direction:column;gap:3px;
        font-size:9.5px;font-weight:600;letter-spacing:1.8px;text-transform:uppercase;color:var(--muted)}
  @media (max-width:420px){
    .cell{padding:30px 22px 22px}
  }
/* BB-LOGIN-KIT:css v1 */

  /* ==========================================================================
     BB LOGIN KIT v1 - the client-facing front door.
     Canonical source: scripts/motion_kit/ (re-apply with scripts/apply_login_kit.py).
     Do NOT hand-edit this block in a main.py - edit the template and re-run.

     Mostly presentation - a slow brand-tinted wash, a card that arrives rather than appears, and
     one press/hover/focus vocabulary - plus three small pieces of REAL behaviour that a password
     gate should have had all along: a show/hide toggle, a Caps Lock warning (the most common
     reason a correct password is typed wrong), and a submit state so nobody double-posts and
     wonders whether the click registered. Those three live in the script at the end of the page.

     Geometry uses `translate`/`scale`, never the `transform` shorthand, so it composes with an
     existing transform instead of replacing it. Everything stops under prefers-reduced-motion.
     ========================================================================== */
  :root{--bl-accent:rgb(10,10,10);--bl-glow:rgba(10,10,10,0.42);--bl-ease:cubic-bezier(.22,1,.36,1)}

  /* the wash: three big soft orbs on their own slow cycles, behind everything, transform-only.
     position:fixed keeps them out of the flex flow of the centred body. */
  .bb-lgfx{position:fixed;inset:0;z-index:0;pointer-events:none;overflow:hidden}
  .bb-lgfx span{position:absolute;display:block;border-radius:50%;will-change:transform}
  .bb-lgfx .o1{width:62vw;height:56vh;top:-16%;left:-10%;animation:blOrb1 24s ease-in-out infinite;
    background:radial-gradient(circle,rgba(10,10,10,0.13) 0%,transparent 68%)}
  .bb-lgfx .o2{width:54vw;height:48vh;bottom:-18%;right:-12%;animation:blOrb2 29s ease-in-out infinite;
    background:radial-gradient(circle,rgba(107,107,104,0.09) 0%,transparent 68%)}
  .bb-lgfx .o3{width:46vw;height:42vh;top:28%;right:4%;animation:blOrb3 33s ease-in-out infinite;
    background:radial-gradient(circle,rgba(10,10,10,0.08) 0%,transparent 70%)}
  @keyframes blOrb1{0%,100%{transform:translate(0,0) scale(1)}50%{transform:translate(70px,54px) scale(1.10)}}
  @keyframes blOrb2{0%,100%{transform:translate(0,0) scale(1)}50%{transform:translate(-64px,-48px) scale(1.09)}}
  @keyframes blOrb3{0%,100%{transform:translate(0,0) scale(1)}50%{transform:translate(-52px,44px) scale(1.08)}}

  /* the card arrives */
  form.card,main.cell{position:relative;z-index:1;animation:blIn .66s var(--bl-ease) both}
  @keyframes blIn{from{opacity:0;translate:0 12px;scale:.99}to{opacity:1;translate:none;scale:none}}

  /* Inputs: a brand caret, a legible placeholder, and the field's own focus treatment eased in
     rather than snapped on. Deliberately NO focus ring added here - every one of these logins
     already styles input:focus, and a second offset outline on top of it reads as an error
     state. The ring below is for the two controls that had no focus style at all. */
  input{transition:border-color .18s var(--bl-ease),box-shadow .22s var(--bl-ease),
                   background-color .18s var(--bl-ease);caret-color:var(--bl-accent)}
  input::placeholder{color:rgba(0,0,0,.45);opacity:1}

  /* the password field carries its own reveal control */
  .bb-pw{position:relative;display:block}
  .bb-pw input{padding-right:58px}
  /* Centred with `translate`, NOT `transform`: four of these logins carry a
     `button:hover{transform:translateY(-1px)}` on the bare element selector, which is MORE
     specific than this class rule and would replace a `transform` here outright - dropping the
     -50% and making the control jump half its height down the field the moment you hover it.
     `translate` is a separate property, so their lift composes with the centring instead. */
  .bb-pw-t{position:absolute;right:6px;top:50%;translate:0 -50%;
    height:21px;padding:0 7px;margin:0;width:auto;cursor:pointer;
    /* LONGHANDS, never the `font` shorthand: `font:600 10.5px/1 inherit` is INVALID - `inherit`
       is not a legal component of the shorthand - so the whole declaration was dropped and the
       control inherited the client's own `button{font-size:15px}`. That is why it rendered at
       15px in a 76x30 slab instead of the small pill it was meant to be. */
    font-family:inherit;font-size:9px;font-weight:600;line-height:1;
    letter-spacing:.06em;text-transform:uppercase;
    color:rgba(0,0,0,.45);background:transparent;border:1px solid rgba(0,0,0,.14);border-radius:6px;
    transition:color .18s var(--bl-ease),border-color .18s var(--bl-ease),
               background-color .18s var(--bl-ease),scale .12s var(--bl-ease)}
  .bb-pw-t:hover{color:var(--bl-accent);border-color:var(--bl-accent);background:rgba(10,10,10,0.1)}
  .bb-pw-t:active{scale:.94}
  .bb-pw-t:focus-visible{outline:2px solid var(--bl-accent);outline-offset:2px}

  /* Caps Lock: silent until it matters, and it never moves the layout when it appears */
  .bb-caps{overflow:hidden;max-height:0;opacity:0;margin:0;text-align:center;
    font-size:11.5px;font-weight:600;letter-spacing:.02em;color:#9A6400;
    transition:max-height .24s var(--bl-ease),opacity .24s var(--bl-ease),margin .24s var(--bl-ease)}
  .bb-caps.on{max-height:24px;opacity:1;margin:9px 0 0}

  /* the button depresses, lifts and glows - and says something while the round trip happens */
  button[type="submit"]{transition:background-color .18s var(--bl-ease),box-shadow .24s var(--bl-ease),
    filter .18s var(--bl-ease),translate .16s var(--bl-ease),scale .1s var(--bl-ease),opacity .18s}
  button[type="submit"]:hover{translate:0 -1px;box-shadow:0 12px 28px -14px var(--bl-glow);filter:brightness(1.05)}
  button[type="submit"]:active{translate:0 0;scale:.985}
  button[type="submit"]:focus-visible{outline:2px solid var(--bl-accent);outline-offset:3px}
  button[type="submit"][disabled]{opacity:.72;cursor:progress;translate:none;scale:none;
    box-shadow:none;filter:none}

  /* A server-rendered error shakes ONCE, on load, flagged by the script. It is deliberately not
     `.err:not(:empty)` - the Google sign-in flow writes progress text into the same element, and
     shaking an informational message is wrong. */
  .err.bb-shake{animation:blShake .42s var(--bl-ease) both}
  @keyframes blShake{0%,100%{translate:0}18%{translate:-5px}38%{translate:4px}58%{translate:-3px}78%{translate:2px}}

  @media (prefers-reduced-motion: reduce){
    .bb-lgfx span{animation:none !important}
    form.card,main.cell{animation:none !important}
    .err.bb-shake{animation:none !important}
    input,button[type="submit"],.bb-pw-t,.bb-caps{transition:none !important}
    button[type="submit"]:hover,button[type="submit"]:active{translate:none !important;scale:none !important}
    /* NOT `translate:none` on the toggle - that IS its vertical centring, not an animation */
    .bb-pw-t:active{scale:none !important}
  }
  /* BB LOGIN KIT v1 ends */
/* /BB-LOGIN-KIT:css */
</style>
</head>
<body>
  <div class="sheet"></div>
  <div class="plan"><i></i><i></i><i></i><b></b></div>
  <div class="band"></div>
  <div class="glow"></div>

  <main class="cell">
    <div class="mark"><img src="/geocon-mark.png" alt="Geocon"
         onerror="this.style.display='none'"></div>
    <div class="eyebrow">Geocon x 100% Digital</div>
    <h1>Performance<br>dashboard</h1>
    <p class="lede">Live paid-media reporting for the Geocon developments. Enter your password to continue.</p>
    <form method="POST" action="/login">
      <!-- BB-LOGIN-KIT:pw v1 --><div class="bb-pw">
    <input type="password" name="password" placeholder="Password" autofocus
             autocomplete="current-password" aria-label="Password">
    <button class="bb-pw-t" type="button" aria-label="Show password">Show</button>
  </div>
  <div class="bb-caps" role="status" aria-live="polite"></div>
  <!-- /BB-LOGIN-KIT:pw -->
      <button type="submit">Enter <span class="arw" aria-hidden="true">&#8599;</span></button>
      <div class="err">{{ error or "" }}</div>
    </form>
    <div class="rule"></div>
    <div class="meta"><span>Gateway Braddon &middot; Northbourne Gateway</span><span>Reporting by 100% Digital</span></div>
  </main>
<!-- BB-LOGIN-KIT:js v1 -->
<script>
/* BB LOGIN KIT v1 - the three behavioural bits. Canonical source scripts/motion_kit/.
   Everything here degrades to the plain form if any of it is missing: the input, the button and
   the POST are untouched, so a login can never fail because of this script. */
(function(){
  var form = document.querySelector('form[action="/login"]') || document.querySelector('form');
  var pw   = document.querySelector('.bb-pw input') ||
             document.querySelector('input[name="password"]');
  var togg = document.querySelector('.bb-pw-t');
  var caps = document.querySelector('.bb-caps');
  var btn  = form && (form.querySelector('button[type="submit"]') || form.querySelector('button'));

  /* 1. show / hide. Type is flipped in place, so the field keeps its value, its name and its
        position in the tab order; the caret is put back where the user was. */
  if (togg && pw){
    togg.addEventListener('click', function(){
      var hidden = pw.type === 'password';
      var at = pw.value.length;
      pw.type = hidden ? 'text' : 'password';
      togg.textContent = hidden ? 'Hide' : 'Show';
      togg.setAttribute('aria-label', (hidden ? 'Hide' : 'Show') + ' password');
      pw.focus();
      try { pw.setSelectionRange(at, at); } catch(e){}
    });
  }

  /* 2. Caps Lock. getModifierState is only meaningful on a real key event, so it is read on the
        field's own keys - no global listener, nothing polled.
        The TEXT is written here rather than sitting in the markup: the element is a live region,
        and a permanent "Caps Lock is on" string would be read out by a screen reader whenever the
        form is traversed, whether it is on or not. Empty when off, filled when on - which is also
        what makes role=status announce it at the right moment. */
  if (caps && pw){
    var CAPS_MSG = 'Caps Lock is on';
    var set = function(on){
      if (caps.classList.contains('on') === on) return;
      caps.classList.toggle('on', on);
      caps.textContent = on ? CAPS_MSG : '';
    };
    var check = function(e){
      if (typeof e.getModifierState !== 'function') return;
      set(e.getModifierState('CapsLock'));
    };
    pw.addEventListener('keydown', check);
    pw.addEventListener('keyup', check);
    pw.addEventListener('blur', function(){ set(false); });
  }

  /* 3. Submit state. The disable happens on the NEXT tick, after the browser has already started
        the POST, so it stops a second submission without ever blocking the first. Only the label
        of a plain text button is swapped - a button with markup inside (an arrow, an icon) keeps
        its contents.
        The `pageshow` reset is NOT optional: log in, then press Back, and the browser restores
        this page from its cache exactly as it was - disabled button, "Checking..." still on it -
        which would strand someone on a login form they cannot submit. pageshow fires on every
        restore, so the control is always live again. */
  if (form && btn){
    var label0 = btn.textContent;
    form.addEventListener('submit', function(){
      setTimeout(function(){
        btn.disabled = true;
        if (!btn.children.length) btn.textContent = 'Checking...';
      }, 0);
    });
    window.addEventListener('pageshow', function(){
      btn.disabled = false;
      if (!btn.children.length) btn.textContent = label0;
    });
  }

  /* 4. A server-rendered error announces itself once. */
  var err = document.querySelector('.err');
  if (err && err.textContent.trim()) err.classList.add('bb-shake');
})();
</script>
<!-- /BB-LOGIN-KIT:js --></body>
</html>
"""


def authed():
    # Authenticated by THIS dashboard's own password (session["ok"]) OR by a platform-issued
    # SSO cookie from dashboards.bidbrain.ai that lists this client. Fail-closed + fail-safe:
    # any problem falls back to password-only, so this can never break the existing gate.
    if session.get("ok") is True:
        return True
    try:
        from platform_sso import sso_allows
        return sso_allows(request)
    except Exception:
        return False


@app.get("/")
def home():
    if not authed():
        return render_template_string(LOGIN_HTML, error=None)
    if DASHBOARD_HTML is None:
        return Response("dashboard.html is missing from the deploy.", status=500)
    # no-store so a redeploy of the tabbed dashboard is picked up immediately,
    # never served stale from the browser or the Cloudflare proxy (matches /data.json).
    return Response(DASHBOARD_HTML, mimetype="text/html",
                    headers={"Cache-Control": "no-store"})


@app.post("/login")
def login():
    if hmac.compare_digest(request.form.get("password", ""), DASH_PASSWORD):
        session["ok"] = True
        session.permanent = True
        return redirect("/")
    return render_template_string(LOGIN_HTML, error="Incorrect password."), 401


@app.get("/logout")
def logout():
    session.clear()
    return redirect("/")


@app.get("/data.json")
def data():
    # The dashboard fetches this. Only an authenticated session gets it;
    # everyone else gets 401. The bucket itself stays private.
    if not authed():
        abort(401)
    blob = _storage.bucket(GCS_BUCKET).blob(DATA_OBJECT)
    if not blob.exists():
        abort(404)
    return Response(
        blob.download_as_bytes(),
        mimetype="application/json",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/creative-img/<cid>")
def creative_img(cid):
    # Serve a Meta creative image cached in our bucket (creatives/<id>) by the export job — a permanent
    # copy that survives after Meta's signed CDN URL expires. Same auth as /data.json.
    if not authed():
        abort(401)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", cid or ""):   # simple ids only (no path traversal)
        abort(404)
    blob = _storage.bucket(GCS_BUCKET).blob(f"creatives/{cid}")
    if not blob.exists():
        abort(404)
    blob.reload()
    return Response(
        blob.download_as_bytes(),
        mimetype=blob.content_type or "image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},   # our copy is stable; let the browser cache it
    )


# Bump to invalidate every cached report when the prompts/schema change (see report.py).
REPORT_CACHE_VERSION = "1"


def _json_err(msg, code):
    return Response(json.dumps({"error": msg}), status=code, mimetype="application/json")


@app.post("/report")
def report_route():
    # AI account report ("Download report"). Auth-gated like the dashboard. The browser POSTs the
    # current account numbers (the same figures it renders); we cache the generated report in the
    # private bucket keyed by DATA VERSION, so re-downloading the same data costs no model calls and
    # regenerates only when the underlying data advances. The report always describes the FULL
    # account (every funnel stage / campaign), independent of the on-screen stage/search filters, so
    # the cache key is just client + data_through — the deck regenerates at most once per data refresh.
    if not authed():
        abort(401)
    if request.content_length and request.content_length > 256 * 1024:
        return _json_err("request too large", 413)
    summary = request.get_json(silent=True)
    if not isinstance(summary, dict):
        return _json_err("invalid request body", 400)

    ctx = summary.get("context") or {}
    key_src = json.dumps({
        "client": summary.get("client"),
        "data_through": ctx.get("data_through"),
        "v": REPORT_CACHE_VERSION,
    }, sort_keys=True)
    h = hashlib.sha256(key_src.encode("utf-8")).hexdigest()[:16]
    ckey = "".join(c for c in str(summary.get("client") or "geocon").lower()
                   if c.isalnum() or c in "-_")[:40] or "client"
    blob = _storage.bucket(GCS_BUCKET).blob(f"reports/{ckey}_{h}.json")

    # Cache hit -> instant, no model cost.
    try:
        if blob.exists():
            cached = json.loads(blob.download_as_bytes())
            cached["cached"] = True
            return Response(json.dumps(cached), mimetype="application/json",
                            headers={"Cache-Control": "no-store"})
    except Exception:
        app.logger.exception("report cache read failed")

    try:
        rpt = generate_report(summary)
    except Exception as e:
        app.logger.exception("report generation failed")
        # Only surface our own vetted RuntimeError messages; anything else (anthropic SDK /
        # google.cloud.storage) may embed URLs, request-ids, or response fragments -> log it,
        # show a generic message.
        msg = str(e) if isinstance(e, RuntimeError) else "report generation failed"
        return _json_err(msg or "report generation failed", 502)

    rpt["cached"] = False
    try:
        blob.upload_from_string(json.dumps(rpt), content_type="application/json")
    except Exception:
        app.logger.exception("report cache write failed")
    return Response(json.dumps(rpt), mimetype="application/json", headers={"Cache-Control": "no-store"})


@app.get("/logo.png")
def logo():
    """Serve the client logo (baked into the container). Public — no auth needed."""
    if LOGO_PNG is None:
        abort(404)
    return Response(LOGO_PNG, mimetype="image/png",
                    headers={"Cache-Control": "public, max-age=86400"})


@app.get("/geocon-mark.png")
def geocon_mark():
    """Serve the Geocon corporate wordmark. Public - the LOGIN page renders it, so requiring auth
    here would leave a broken image on the one page nobody is authenticated for yet."""
    if GEOCON_MARK_PNG is None:
        abort(404)
    return Response(GEOCON_MARK_PNG, mimetype="image/png",
                    headers={"Cache-Control": "public, max-age=86400"})


@app.get("/bb_deck.js")
def bb_deck_js():
    """The slide-deck builder. Auth-gated like the dashboard (the deck reveals report content)."""
    if not authed():
        abort(401)
    if not BB_DECK_JS:
        return Response("// bb_deck.js missing from the deploy", status=500, mimetype="application/javascript")
    return Response(BB_DECK_JS, mimetype="application/javascript",
                    headers={"Cache-Control": "no-store"})


@app.get("/healthz")
def healthz():
    return "ok"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
