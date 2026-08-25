"""Caltex dashboard web app (Cloud Run service).

Thin password gate + static server. It renders a login screen, and once a
session is authenticated it serves `dashboard.html` and proxies the private
`caltex.json` from GCS at `/data.json`. All presentation logic - the Executive /
Media Buyer / Client Story views - lives in `dashboard.html`; this file only
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
    Flask, request, redirect, session, Response, render_template_string, abort, jsonify
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

# --- "Sign in with Google" on THIS service (the client is NOT given dashboards.bidbrain.ai, which
# is internal-only). Additive: the password box still works, and if GOOGLE_OAUTH_CLIENT_ID is unset
# the button simply isn't rendered.
#   GOOGLE_OAUTH_CLIENT_ID  - the same OAuth client the platform uses; this service's URL must be
#                             listed as an Authorized JavaScript origin on it or Google refuses the
#                             button with origin_mismatch.
#   ALLOWED_EMAILS          - comma-separated exact addresses (the client contacts).
#   ALLOWED_EMAIL_DOMAINS   - comma-separated domains always allowed (our own staff).
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "").strip()
ALLOWED_EMAILS = {e.strip().lower() for e in os.environ.get("ALLOWED_EMAILS", "").split(",") if e.strip()}
ALLOWED_EMAIL_DOMAINS = {d.strip().lower().lstrip("@")
                         for d in os.environ.get("ALLOWED_EMAIL_DOMAINS", "100.digital").split(",") if d.strip()}


def email_allowed(email):
    """Allowlist check on an ALREADY-VERIFIED Google email. Exact address OR trusted domain.

    Split on the LAST '@' and require both halves non-empty, so neither a bare '@domain' nor a
    lookalike like 'tilly@iddigital.com.au.attacker.com' can match (the latter's domain is the
    attacker's, not ours). Google has already verified the address by the time we get here; this
    is the second gate, not the first."""
    email = (email or "").strip().lower()
    local, _, domain = email.rpartition("@")
    if not local or not domain:
        return False
    return email in ALLOWED_EMAILS or domain in ALLOWED_EMAIL_DOMAINS
GCS_BUCKET = os.environ.get("GCS_BUCKET", "")               # private data bucket ("" until standup)
DATA_OBJECT = os.environ.get("DATA_OBJECT", "caltex.json")   # object inside it

_storage = storage.Client()

# Dashboard HTML is baked into the container at build time, next to this file.
# Anchor to __file__ so it loads regardless of the process working directory.
_dash_dir = Path(__file__).resolve().parent
try:
    DASHBOARD_HTML = (_dash_dir / "dashboard.html").read_text(encoding="utf-8")
except FileNotFoundError:
    DASHBOARD_HTML = None

# Logo PNG baked into the container (COPY'd in the Dockerfile). Served publicly so the login page
# and the AI deck builder (bbDeckLogos() fetches 'logo.png') can brand themselves.
try:
    LOGO_PNG = (_dash_dir / "logo.png").read_bytes()
except FileNotFoundError:
    LOGO_PNG = None

# PLACEHOLDER data baked into the container - a Caltex-branded SAMPLE payload (flagged
# meta.placeholder=true, which dashboard.html renders behind a loud "sample data" banner). It lets
# the scaffold render end-to-end BEFORE any real data is connected. The moment the export job writes
# the real caltex.json to the bucket, /data.json serves THAT instead and the banner disappears.
try:
    PLACEHOLDER_JSON = (_dash_dir / "placeholder.json").read_bytes()
except FileNotFoundError:
    PLACEHOLDER_JSON = None

# Shared, theme-driven slide-deck builder (vendored - the canonical copy is re-copied into each dash
# folder). Served as a static asset so the dashboard's <script src="bb_deck.js"> loads it (relative →
# /bb_deck.js direct, or /d/caltex/bb_deck.js through the platform proxy).
try:
    BB_DECK_JS = (_dash_dir / "bb_deck.js").read_text(encoding="utf-8")
except FileNotFoundError:
    BB_DECK_JS = ""

LOGIN_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Caltex Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Archivo:wght@600;700;800&display=swap" rel="stylesheet">
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{min-height:100vh;display:flex;align-items:center;justify-content:center;
       font-family:"Inter",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
       background:#07171C;color:#EEF4F5;position:relative;overflow:hidden}
  body::before{content:'';position:absolute;inset:0;pointer-events:none;
       background:radial-gradient(880px 460px at 50% -8%, rgba(228,0,43,.085), transparent 66%),
                  radial-gradient(560px 320px at 50% -2%, rgba(46,140,166,.12), transparent 66%)}
  body::after{content:'';position:absolute;bottom:0;left:0;right:0;height:3px;
              background:#E4002B}
  .card{position:relative;width:100%;max-width:364px;padding:36px 30px;
        background:linear-gradient(180deg,#123241 0%,#0E2831 42%,#0C242D 100%);
        border:1px solid rgba(255,255,255,.11);border-radius:16px;
        box-shadow:0 1px 0 rgba(255,255,255,.07) inset,
                   0 28px 80px -28px rgba(0,0,0,.72),
                   0 0 60px -30px rgba(228,0,43,.30)}
  .logo-wrap{text-align:center;margin-bottom:20px}
  .logo-wrap img{max-height:92px;max-width:210px;display:inline-block}
  .brand{font-size:10px;font-weight:700;letter-spacing:2.6px;color:#7C9AA1;margin-bottom:9px;text-transform:uppercase}
  h1{font-family:"Archivo","Inter",sans-serif;font-size:22px;font-weight:700;margin:0 0 5px;letter-spacing:-.35px}
  p{font-size:13px;color:rgba(238,244,245,.62);margin:0 0 21px;line-height:1.5}
  input{width:100%;padding:12px 14px;font-size:14.5px;color:#EEF4F5;background:rgba(255,255,255,.045);
        border:1px solid rgba(255,255,255,.13);border-radius:9px;outline:none;transition:border-color .15s}
  input:focus{border-color:#E4002B}
  input::placeholder{color:rgba(238,244,245,.38)}
  button{width:100%;margin-top:13px;padding:12px;font-size:14.5px;font-weight:700;cursor:pointer;
         background:linear-gradient(180deg,#EC0730 0%,#D40027 100%);color:#fff;border:none;border-radius:10px;
         transition:transform .1s ease,box-shadow .2s ease;letter-spacing:.3px}
  button:hover{translate:0 -1px;box-shadow:0 8px 20px rgba(228,0,43,.26)}
  button:active{transform:translateY(0)}
  .err{margin-top:14px;font-size:13px;color:#FFB3C0;min-height:16px;text-align:center}
  .sep{display:flex;align-items:center;gap:11px;margin:20px 0 5px;color:#6F8B92;font-size:10px;
       text-transform:uppercase;letter-spacing:1.8px}
  .sep::before,.sep::after{content:"";flex:1;height:1px;background:rgba(255,255,255,.12)}
  .gwrap{display:flex;justify-content:center;margin-top:12px;min-height:44px}
  /* ==== Caltex: live glow (client override, NOT part of the login kit) ====================
     The kit ships three drifting orbs, but this dashboard's palette was calmed on 2026-08-25
     and that damped them to the point of looking static. Tuned back up here rather than in
     the kit block, because apply_login_kit.py rewrites that block and would drop the edit.

     Selectors are `body .bb-lgfx ...` ON PURPOSE: this stylesheet sits ABOVE the kit block, so
     at equal specificity the kit would win. The extra `body` outranks it from earlier in the file.

     Tuned on ALPHA + TRAVEL DISTANCE, never by adding layers - three animated full-screen
     layers is already the budget, and a slow keyframe over a short distance reads as STILL no
     matter how bright it is. Transform-only, so it stays on the compositor. No canvas and no
     rAF loop: a login page should not run one.
     ====================================================================================== */
  body .bb-lgfx .o1{animation:cxOrb1 17s ease-in-out infinite;
    background:radial-gradient(circle,rgba(228,0,43,0.20) 0%,transparent 68%)}
  body .bb-lgfx .o2{animation:cxOrb2 21s ease-in-out infinite;
    background:radial-gradient(circle,rgba(46,140,166,0.16) 0%,transparent 68%)}
  body .bb-lgfx .o3{animation:cxOrb3 25s ease-in-out infinite;
    background:radial-gradient(circle,rgba(255,59,84,0.115) 0%,transparent 70%)}
  @keyframes cxOrb1{
    0%,100%{transform:translate(0,0) scale(1)}
    33%{transform:translate(150px,86px) scale(1.16)}
    66%{transform:translate(64px,150px) scale(1.05)}}
  @keyframes cxOrb2{
    0%,100%{transform:translate(0,0) scale(1)}
    33%{transform:translate(-138px,-96px) scale(1.14)}
    66%{transform:translate(-58px,-150px) scale(1.06)}}
  @keyframes cxOrb3{
    0%,100%{transform:translate(0,0) scale(1)}
    50%{transform:translate(-124px,104px) scale(1.18)}}

  /* The card's own red halo breathes, so the area immediately behind it is alive too.
     box-shadow (not transform) because this one must not move the card itself. */
  .card{animation:cxCardGlow 11s ease-in-out infinite}
  @keyframes cxCardGlow{
    0%,100%{box-shadow:0 1px 0 rgba(255,255,255,.07) inset,
                       0 28px 80px -28px rgba(0,0,0,.72),
                       0 0 60px -30px rgba(228,0,43,.30)}
    50%    {box-shadow:0 1px 0 rgba(255,255,255,.09) inset,
                       0 28px 80px -28px rgba(0,0,0,.72),
                       0 0 96px -26px rgba(228,0,43,.52)}}

  /* Motion is decoration here; never let it be the reason someone cannot use the form. */
  @media (prefers-reduced-motion:reduce){
    body .bb-lgfx .o1,body .bb-lgfx .o2,body .bb-lgfx .o3,.card{animation:none !important}
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
  :root{--bl-accent:rgb(228,0,43);--bl-glow:rgba(228,0,43,0.24);--bl-ease:cubic-bezier(.22,1,.36,1)}

  /* the wash: three big soft orbs on their own slow cycles, behind everything, transform-only.
     position:fixed keeps them out of the flex flow of the centred body. */
  .bb-lgfx{position:fixed;inset:0;z-index:0;pointer-events:none;overflow:hidden}
  .bb-lgfx span{position:absolute;display:block;border-radius:50%;will-change:transform}
  .bb-lgfx .o1{width:62vw;height:56vh;top:-16%;left:-10%;animation:blOrb1 24s ease-in-out infinite;
    background:radial-gradient(circle,rgba(228,0,43,0.11) 0%,transparent 68%)}
  .bb-lgfx .o2{width:54vw;height:48vh;bottom:-18%;right:-12%;animation:blOrb2 29s ease-in-out infinite;
    background:radial-gradient(circle,rgba(46,140,166,0.077) 0%,transparent 68%)}
  .bb-lgfx .o3{width:46vw;height:42vh;top:28%;right:4%;animation:blOrb3 33s ease-in-out infinite;
    background:radial-gradient(circle,rgba(255,59,84,0.061) 0%,transparent 70%)}
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
  input::placeholder{color:rgba(255,255,255,.52);opacity:1}

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
    color:rgba(255,255,255,.52);background:transparent;border:1px solid rgba(255,255,255,.20);border-radius:6px;
    transition:color .18s var(--bl-ease),border-color .18s var(--bl-ease),
               background-color .18s var(--bl-ease),scale .12s var(--bl-ease)}
  .bb-pw-t:hover{color:var(--bl-accent);border-color:var(--bl-accent);background:rgba(228,0,43,0.1)}
  .bb-pw-t:active{scale:.94}
  .bb-pw-t:focus-visible{outline:2px solid var(--bl-accent);outline-offset:2px}

  /* Caps Lock: silent until it matters, and it never moves the layout when it appears */
  .bb-caps{overflow:hidden;max-height:0;opacity:0;margin:0;text-align:center;
    font-size:11.5px;font-weight:600;letter-spacing:.02em;color:#F5B942;
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
{% if google_client_id %}<script src="https://accounts.google.com/gsi/client" async defer></script>{% endif %}
</head>
<body><!-- BB-LOGIN-KIT:fx v1 -->
<div class="bb-lgfx" aria-hidden="true"><span class="o1"></span><span class="o2"></span><span class="o3"></span></div><!-- /BB-LOGIN-KIT:fx -->
  <form class="card" method="POST" action="/login">
    <div class="logo-wrap">
      <img src="data:image/png;base64,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" alt="Caltex">
    </div>
    <div class="brand">BidBrain · Caltex</div>
    <h1>Dashboard Access</h1>
    <p>Enter the password to continue.</p>
    <!-- BB-LOGIN-KIT:pw v1 --><div class="bb-pw">
    <input type="password" name="password" placeholder="Password" autofocus
           autocomplete="current-password">
    <button class="bb-pw-t" type="button" aria-label="Show password">Show</button>
  </div>
  <div class="bb-caps" role="status" aria-live="polite"></div>
  <!-- /BB-LOGIN-KIT:pw -->
    <button type="submit">Unlock Dashboard</button>
    <div class="err">{{ error or "" }}</div>
{% if google_client_id %}
    <div class="sep">or</div>
    <div class="gwrap" id="gbtn"></div>
{% endif %}
  </form>
{% if google_client_id %}
<script>
  // GIS posts a signed ID token to /auth/google, which verifies it server-side and checks the
  // email against the allowlist. Nothing is trusted client-side.
  function bbGoogleCb(resp){
    var err=document.querySelector(".err"); err.textContent="Checking your Google account\u2026";
    fetch("/auth/google",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({credential:(resp&&resp.credential)||""})})
      .then(function(r){return r.json();})
      .then(function(j){ if(j&&j.ok){ location.href="/"; } else { err.textContent=(j&&j.error)||"Sign-in failed."; } })
      .catch(function(){ err.textContent="Sign-in failed - please try the password."; });
  }
  // the GIS script is async, so wait for it rather than racing it
  (function waitGIS(n){
    if(window.google&&google.accounts&&google.accounts.id){
      google.accounts.id.initialize({client_id:"{{ google_client_id }}",callback:bbGoogleCb});
      google.accounts.id.renderButton(document.getElementById("gbtn"),
        {theme:"filled_black",size:"large",shape:"pill",text:"signin_with",width:260});
    } else if(n<60){ setTimeout(function(){waitGIS(n+1);},100); }
  })(0);
</script>
{% endif %}
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
</html>"""


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
        return render_template_string(LOGIN_HTML, error=None, google_client_id=GOOGLE_CLIENT_ID)
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
    return render_template_string(LOGIN_HTML, error="Incorrect password.",
                                  google_client_id=GOOGLE_CLIENT_ID), 401


@app.post("/auth/google")
def auth_google():
    """Verify a Google ID token and, if the email is allowlisted, grant the normal session.

    Mirrors the platform's verifier (bidbrain-platform/dash/main.py auth_google): the signature,
    issuer and audience are checked by google-auth against OUR client id - a token minted for any
    other app is rejected - and we additionally require email_verified. Only then does the email go
    through the allowlist. The password path is untouched."""
    if not GOOGLE_CLIENT_ID:
        return jsonify(ok=False, error="Google sign-in is not configured for this dashboard."), 400
    token = ((request.get_json(silent=True) or {}).get("credential") or "").strip()
    if not token:
        return jsonify(ok=False, error="Missing Google credential."), 400
    try:
        from google.oauth2 import id_token
        from google.auth.transport import requests as ga_requests
        info = id_token.verify_oauth2_token(token, ga_requests.Request(), GOOGLE_CLIENT_ID,
                                            clock_skew_in_seconds=10)
    except Exception as e:   # malformed/expired, wrong aud, clock skew, cert fetch failure, ...
        app.logger.warning("google id_token verification failed: %s", e)
        return jsonify(ok=False, error="Could not verify your Google sign-in."), 401
    if not info.get("email") or not info.get("email_verified"):
        return jsonify(ok=False, error="Your Google account has no verified email."), 401
    email = info["email"].strip().lower()
    if not email_allowed(email):
        app.logger.warning("google sign-in DENIED for %s (not allowlisted)", email)
        return jsonify(ok=False,
                       error=f"{email} does not have access to this dashboard."), 403
    session["ok"] = True
    session["email"] = email
    session.permanent = True
    app.logger.info("google sign-in OK for %s", email)
    return jsonify(ok=True)


@app.get("/logout")
def logout():
    session.clear()
    return redirect("/")


@app.get("/data.json")
def data():
    # The dashboard fetches this. Only an authenticated session gets it;
    # everyone else gets 401. The bucket itself stays private.
    #
    # PLACEHOLDER FALLBACK: until the export job has written a real caltex.json to the bucket (i.e.
    # data isn't connected yet), serve the baked-in SAMPLE payload so the dashboard renders end-to-end
    # behind its "sample data" banner. Real data always wins the moment it exists.
    if not authed():
        abort(401)
    if GCS_BUCKET:
        try:
            blob = _storage.bucket(GCS_BUCKET).blob(DATA_OBJECT)
            if blob.exists():
                return Response(blob.download_as_bytes(), mimetype="application/json",
                                headers={"Cache-Control": "no-store"})
        except Exception:
            app.logger.exception("data.json bucket read failed; serving placeholder")
    if PLACEHOLDER_JSON is not None:
        return Response(PLACEHOLDER_JSON, mimetype="application/json",
                        headers={"Cache-Control": "no-store"})
    abort(404)


@app.get("/creative-img/<cid>")
def creative_img(cid):
    # Serve a Meta creative image cached in our bucket (creatives/<id>) by the export job - a permanent
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
    # the cache key is just client + data_through - the deck regenerates at most once per data refresh.
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
    ckey = "".join(c for c in str(summary.get("client") or "caltex").lower()
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
    """Serve the client logo (baked into the container). Public - no auth needed."""
    if LOGO_PNG is None:
        abort(404)
    return Response(LOGO_PNG, mimetype="image/png",
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
