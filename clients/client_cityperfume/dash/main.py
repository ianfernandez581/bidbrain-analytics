"""City Perfume marketing dashboard web app (Cloud Run service).

Thin password gate + static server. It renders a login screen, and once a session is
authenticated it serves `dashboard.html` and proxies the PRIVATE `cityperfume.json` from
GCS at `/data.json`. All presentation logic — the Overview / Paid Media / Website & GA4 /
Sales & Products / Ads -> Revenue tabs and every chart — lives in `dashboard.html`; this
file only decides *who* may see it, not *what* it shows.

Same service pattern as client_STT/dash/main.py (BYTE-FOR-BYTE on the auth/serve/proxy
logic) — only the login-page branding and the default data object differ. v_sales is real
customer data, so the private bucket + this password gate IS the security model (never the
open/no-auth Adriatic sample pattern). The org policy that blocks --allow-unauthenticated is
handled the same way — the deploy flips --no-invoker-iam-check so this app's own password
gate is the only door. SameSite=None+Secure lets the session cookie survive the cross-origin
iframe on dashboards.bidbrain.ai.
"""
import os
import hmac
from pathlib import Path
from flask import (
    Flask, request, redirect, session, Response, render_template_string, abort
)
from google.cloud import storage

app = Flask(__name__)
app.secret_key = os.environ["SESSION_SECRET"]
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_SAMESITE="None",  # cross-site iframe on dashboards.bidbrain.ai (None requires Secure)
    PERMANENT_SESSION_LIFETIME=60 * 60 * 12,  # stay logged in 12h
)

# --- config (injected by Cloud Run) ------------------------------------------
DASH_PASSWORD = os.environ["DASH_PASSWORD"].rstrip("\r\n")        # from Secret Manager
GCS_BUCKET = os.environ["GCS_BUCKET"]                             # private data bucket
DATA_OBJECT = os.environ.get("DATA_OBJECT", "cityperfume.json")  # object inside it

_storage = storage.Client()

# Dashboard HTML is baked into the container at build time, next to this file.
# Anchor to __file__ so it loads regardless of the process working directory.
try:
    DASHBOARD_HTML = (Path(__file__).resolve().parent / "dashboard.html").read_text(encoding="utf-8")
except FileNotFoundError:
    DASHBOARD_HTML = None

# Login page carries the City Perfume logo inlined as base64 (the topbar holds both the
# 100% Digital + City Perfume marks). Rebrand here only — auth/serve logic stays as STT's.
LOGIN_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>City Perfume · Marketing Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Karla:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  *{box-sizing:border-box}
  body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
       font-family:"Karla",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
       background:radial-gradient(1200px 600px at 50% -10%,#2A2422 0%,#1C1815 55%,#141110 100%)}
  .card{width:100%;max-width:360px;padding:40px 32px;background:#FBF8F4;
        border:1px solid rgba(0,0,0,.06);border-radius:16px;
        box-shadow:0 20px 64px rgba(0,0,0,.42)}
  .logo{font-family:"Karla",Georgia,serif;font-size:24px;font-weight:600;letter-spacing:2px;
        color:#1C1815;text-align:center;margin-bottom:6px}
  .brand{font-size:11px;font-weight:700;letter-spacing:1.8px;color:#B08D57;margin-bottom:18px;text-align:center}
  h1{font-size:18px;font-weight:700;margin:0 0 4px;color:#1C1815;text-align:center}
  p{font-size:13px;color:#7A726B;margin:0 0 22px;text-align:center}
  input{width:100%;padding:12px 13px;font-size:15px;color:#1C1815;background:#fff;
        border:1px solid #E7E0D7;border-radius:10px;outline:none}
  input:focus{border-color:#B08D57;box-shadow:0 0 0 3px rgba(176,141,87,.18)}
  button{width:100%;margin-top:12px;padding:12px;font-size:15px;font-weight:700;cursor:pointer;
         background:#1C1815;color:#fff;border:none;border-radius:10px;letter-spacing:.4px}
  button:hover{background:#B08D57}
  .err{margin-top:12px;font-size:13px;color:#C8362A;min-height:16px;text-align:center}


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
  :root{--bl-accent:rgb(176,141,87);--bl-glow:rgba(176,141,87,0.42);--bl-ease:cubic-bezier(.22,1,.36,1)}

  /* the wash: three big soft orbs on their own slow cycles, behind everything, transform-only.
     position:fixed keeps them out of the flex flow of the centred body. */
  .bb-lgfx{position:fixed;inset:0;z-index:0;pointer-events:none;overflow:hidden}
  .bb-lgfx span{position:absolute;display:block;border-radius:50%;will-change:transform}
  .bb-lgfx .o1{width:62vw;height:56vh;top:-16%;left:-10%;animation:blOrb1 24s ease-in-out infinite;
    background:radial-gradient(circle,rgba(176,141,87,0.2) 0%,transparent 68%)}
  .bb-lgfx .o2{width:54vw;height:48vh;bottom:-18%;right:-12%;animation:blOrb2 29s ease-in-out infinite;
    background:radial-gradient(circle,rgba(201,139,122,0.14) 0%,transparent 68%)}
  .bb-lgfx .o3{width:46vw;height:42vh;top:28%;right:4%;animation:blOrb3 33s ease-in-out infinite;
    background:radial-gradient(circle,rgba(142,110,124,0.11) 0%,transparent 70%)}
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
  .bb-pw input{padding-right:74px}
  /* Centred with `translate`, NOT `transform`: four of these logins carry a
     `button:hover{transform:translateY(-1px)}` on the bare element selector, which is MORE
     specific than this class rule and would replace a `transform` here outright - dropping the
     -50% and making the control jump half its height down the field the moment you hover it.
     `translate` is a separate property, so their lift composes with the centring instead. */
  .bb-pw-t{position:absolute;right:7px;top:50%;translate:0 -50%;
    height:30px;padding:0 11px;margin:0;width:auto;cursor:pointer;
    font:600 10.5px/1 inherit;letter-spacing:.09em;text-transform:uppercase;
    color:rgba(0,0,0,.45);background:transparent;border:1px solid rgba(0,0,0,.14);border-radius:8px;
    transition:color .18s var(--bl-ease),border-color .18s var(--bl-ease),
               background-color .18s var(--bl-ease),scale .12s var(--bl-ease)}
  .bb-pw-t:hover{color:var(--bl-accent);border-color:var(--bl-accent);background:rgba(176,141,87,0.1)}
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
<body><!-- BB-LOGIN-KIT:fx v1 -->
<div class="bb-lgfx" aria-hidden="true"><span class="o1"></span><span class="o2"></span><span class="o3"></span></div><!-- /BB-LOGIN-KIT:fx -->
  <form class="card" method="POST" action="/login">
    <img src="data:image/png;base64,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" alt="City Perfume" style="display:block;margin:0 auto 10px;height:78px;width:auto">
    <div class="brand">100% DIGITAL · MARKETING DASHBOARD</div>
    <h1>Dashboard access</h1>
    <p>Enter the password to continue.</p>
    <!-- BB-LOGIN-KIT:pw v1 --><div class="bb-pw">
    <input type="password" name="password" placeholder="Password" autofocus
           autocomplete="current-password">
    <button class="bb-pw-t" type="button" aria-label="Show password">Show</button>
  </div>
  <div class="bb-caps" role="status" aria-live="polite"></div>
  <!-- /BB-LOGIN-KIT:pw -->
    <button type="submit">Unlock</button>
    <div class="err">{{ error or "" }}</div>
  </form>
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
        return render_template_string(LOGIN_HTML, error=None)
    if DASHBOARD_HTML is None:
        return Response("dashboard.html is missing from the deploy.", status=500)
    # no-store so a redeploy of the dashboard is picked up immediately, never
    # served stale from the browser or any proxy (matches /data.json).
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


@app.get("/healthz")
def healthz():
    return "ok"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
