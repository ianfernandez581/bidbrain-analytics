"""Lacevo dashboard web app (Cloud Run service).

Thin password gate + static server, the same shape as every other tenant in the estate: it renders
a login screen, and once a session is authenticated it serves `dashboard.html` and proxies the
private `lacevo.json` from GCS at `/data.json`. All presentation logic lives in `dashboard.html`;
this file only decides *who* may see it, not *what* it shows.

PREVIEW TENANT. Lacevo has no data pipeline yet (no BigQuery dataset, no sql/ views, no export
job), so the bucket is empty and `/data.json` falls back to the baked-in sample payload
`placeholder.json`, which carries `meta.placeholder=true`. The dashboard renders its preview notice
off that one flag. The moment an export job writes a real `lacevo.json` to the bucket, that wins and
the notice disappears - no code change, no redeploy. See README.md -> "Flipping preview to live".

There is deliberately NO `/report` endpoint here: the AI deck needs `roles/aiplatform.user` and a
client-specific prompt set, and neither is warranted while every number on the page is a placeholder.
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
    MAX_CONTENT_LENGTH=64 * 1024,             # nothing here takes a sizeable body
)

# --- config (injected by Cloud Run) ------------------------------------------
DASH_PASSWORD = os.environ["DASH_PASSWORD"].rstrip("\r\n")   # from Secret Manager
GCS_BUCKET = os.environ.get("GCS_BUCKET", "")               # private data bucket (empty until the job exists)
DATA_OBJECT = os.environ.get("DATA_OBJECT", "lacevo.json")  # object inside it

_storage = storage.Client()

# Baked into the container at build time, next to this file. Anchored to __file__ so they load
# regardless of the process working directory.
_dash_dir = Path(__file__).resolve().parent


def _read_bytes(name):
    try:
        return (_dash_dir / name).read_bytes()
    except FileNotFoundError:
        return None


def _read_text(name):
    try:
        return (_dash_dir / name).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


DASHBOARD_HTML = _read_text("dashboard.html")
PLACEHOLDER_JSON = _read_bytes("placeholder.json")
# Two brand assets, because the surfaces need different colourways. Both are derived from
# creatives/LACEVO-master.webp by gen_brand_assets.py - regenerate, never hand-edit.
LOGO_PNG = _read_bytes("logo.png")    # the full lockup in INK, for the WHITE login card
ICON_PNG = _read_bytes("icon.png")    # the droplet in CLAY, for the browser tab


def _rev(b):
    """Short content hash, used to cache-bust the brand assets.

    Both are served with `max-age=86400`, which is right for artwork - but it meant that when the
    real Lacevo lockup replaced the placeholder droplet, every browser that had already opened the
    login kept showing the PLACEHOLDER for a day and the deploy looked like it had silently failed.
    Hashing the bytes into the URL makes it change whenever the file does, so the long cache stays
    correct AND a swap is visible immediately."""
    import hashlib
    return hashlib.sha1(b).hexdigest()[:10] if b else "0"


LOGO_REV = _rev(LOGO_PNG)
ICON_REV = _rev(ICON_PNG)

# STAFF-ONLY content for the Internal notes tab, kept OUT of data.json on purpose - the precedent is
# client_schneidersecpwr's Reports tab, whose ad-set targeting is fetched from its own endpoint so
# that hiding the tab is not the only thing protecting it. Read the honest limitation in README.md
# -> "Internal notes": this service can authenticate a visitor but cannot yet tell a staff session
# from a client one, so the route below is gated on being logged in, not on being staff.
INTERNAL_NOTES_JSON = _read_bytes("internal_notes.json")

LOGIN_HTML = """<!doctype html>
<html lang="en-AU">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lacevo Dashboard</title>
<link rel="icon" type="image/png" href="/icon.png?v={{ icon_rev }}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600;700&family=Montserrat:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  /* Lacevo login: a WHITE card on a lit warm-white field.
     It was ink-on-ink until 2026-09-14 and read as a dark slab on a dark slab - the black header
     is the DASHBOARD's furniture, and repeating it here just made two dark rectangles. The
     lighting language is the dashboard's: a warm key light high on the page, a clay bounce off
     to one side, and a falloff at the bottom. LIGHT NEEDS SHADE TO READ AGAINST, which is what
     that last gradient is for - without it a light wash on a light field is invisible.

     On white the base clay #965F48 is legible as TEXT and as a hairline, so the lifted #C98A6E
     is demoted to decoration here. That is the exact inverse of the dark dashboard shell, and
     getting it backwards in either direction is how a brand colour becomes an invisible border. */
  *{box-sizing:border-box;margin:0;padding:0}
  body{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px;
       font-family:Montserrat,"Helvetica Neue",Arial,sans-serif;
       background:#F7F4F0;color:#1C1C1C;position:relative;overflow:hidden;
       -webkit-font-smoothing:antialiased}
  body::before{content:'';position:absolute;inset:0;pointer-events:none;
       background:
         radial-gradient(1100px 660px at 50% -18%, rgba(255,255,255,1), rgba(255,255,255,0) 58%),
         radial-gradient(760px 520px at 92% -4%, rgba(255,214,188,.55), transparent 62%),
         radial-gradient(680px 560px at 2% 22%, rgba(236,224,208,.60), transparent 64%),
         radial-gradient(1200px 700px at 50% 122%, rgba(126,88,66,.16), transparent 62%)}
  body::after{content:'';position:absolute;bottom:0;left:0;right:0;height:3px;
              background:linear-gradient(90deg,#965F48 0%,#C98A6E 52%,#E4E0DA 100%)}
  /* Two shadows: a tight contact shadow that seats the card on the page, and a wide soft one
     that is the light falling past it. Plus the specular top edge - on a white card that single
     inset line is most of what makes it read as a surface rather than a hole. */
  .card{position:relative;width:100%;max-width:400px;padding:44px 36px 34px;background:#FFFFFF;
        border:1px solid rgba(28,28,28,.07);border-radius:18px;
        box-shadow:0 2px 4px rgba(58,44,36,.05),
                   0 30px 60px -26px rgba(58,44,36,.28),
                   inset 0 1px 0 rgba(255,255,255,.9)}
  /* The lockup is wide, not square: constrain its WIDTH and let height follow, or a
     max-height on a 2.3:1 image leaves it tiny in a 400px card. */
  .logo-wrap{text-align:center;margin-bottom:30px}
  .logo-wrap img{width:186px;max-width:60%;height:auto;display:inline-block}
  .brand{font-family:"Instrument Sans",Montserrat,Arial,sans-serif;
         font-size:10px;font-weight:600;letter-spacing:2.2px;color:#965F48;
         margin-bottom:9px;text-transform:uppercase;text-align:center}
  /* No <h1> here: the lockup IS the wordmark, and a typeset "Lacevo" underneath it was the
     brand name twice, the second time in the wrong typeface. */
  p.sub{font-size:13px;color:#6E675F;margin:0 0 26px;text-align:center;line-height:1.5}
  input{width:100%;padding:14px 15px;font-size:15px;color:#1C1C1C;background:#F7F4F0;
        border:1px solid rgba(28,28,28,.12);border-radius:10px;outline:none;
        transition:border-color .18s,box-shadow .18s,background-color .18s}
  input:focus{border-color:#965F48;background:#FFFFFF;box-shadow:0 0 0 3px rgba(150,95,72,.16)}
  input::placeholder{color:#9A928A}
  button{width:100%;margin-top:14px;padding:14px;font-size:15px;font-weight:600;cursor:pointer;
         font-family:"Instrument Sans",Montserrat,Arial,sans-serif;
         background:linear-gradient(180deg,#A66B51,#965F48);color:#FFFFFF;
         border:1px solid #8A5641;border-radius:10px;
         transition:transform .1s ease,box-shadow .2s ease,filter .18s ease;letter-spacing:.3px}
  button:hover{transform:translateY(-1px);box-shadow:0 12px 26px -10px rgba(150,95,72,.62);filter:brightness(1.04)}
  button:active{transform:translateY(0)}
  .err{margin-top:14px;font-size:13px;color:#B24A32;min-height:16px;text-align:center}
  .foot{margin-top:26px;padding-top:18px;border-top:1px solid rgba(28,28,28,.08);
        font-size:11px;color:#9A928A;text-align:center;line-height:1.6}
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
  :root{--bl-accent:rgb(150,95,72);--bl-glow:rgba(150,95,72,0.42);--bl-ease:cubic-bezier(.22,1,.36,1)}

  /* the wash: three big soft orbs on their own slow cycles, behind everything, transform-only.
     position:fixed keeps them out of the flex flow of the centred body. */
  .bb-lgfx{position:fixed;inset:0;z-index:0;pointer-events:none;overflow:hidden}
  .bb-lgfx span{position:absolute;display:block;border-radius:50%;will-change:transform}
  .bb-lgfx .o1{width:62vw;height:56vh;top:-16%;left:-10%;animation:blOrb1 24s ease-in-out infinite;
    background:radial-gradient(circle,rgba(150,95,72,0.072) 0%,transparent 68%)}
  .bb-lgfx .o2{width:54vw;height:48vh;bottom:-18%;right:-12%;animation:blOrb2 29s ease-in-out infinite;
    background:radial-gradient(circle,rgba(201,138,110,0.05) 0%,transparent 68%)}
  .bb-lgfx .o3{width:46vw;height:42vh;top:28%;right:4%;animation:blOrb3 33s ease-in-out infinite;
    background:radial-gradient(circle,rgba(219,208,196,0.044) 0%,transparent 70%)}
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
  .bb-pw-t:hover{color:var(--bl-accent);border-color:var(--bl-accent);background:rgba(150,95,72,0.1)}
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
<form class="card" method="post" action="login">
  <div class="logo-wrap"><img src="/logo.png?v={{ logo_rev }}" alt="Lacevo"></div>
  <div class="brand">100% Digital</div>
  <p class="sub">Trading and paid media dashboard</p>
  <!-- BB-LOGIN-KIT:pw v1 --><div class="bb-pw">
    <input type="password" name="password" placeholder="Password" autofocus autocomplete="current-password">
    <button class="bb-pw-t" type="button" aria-label="Show password">Show</button>
  </div>
  <div class="bb-caps" role="status" aria-live="polite"></div>
  <!-- /BB-LOGIN-KIT:pw -->
  <button type="submit">Open dashboard</button>
  <div class="err">{{ error or "" }}</div>
  <div class="foot">Preview build - the feeds are not connected yet.</div>
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
    # Authenticated by THIS dashboard's own password (session["ok"]) OR by a platform-issued SSO
    # cookie from dashboards.bidbrain.ai that lists this client. Fail-closed + fail-safe: any
    # problem falls back to password-only, so this can never break the existing gate.
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
        return render_template_string(LOGIN_HTML, error=None, logo_rev=LOGO_REV, icon_rev=ICON_REV)
    if DASHBOARD_HTML is None:
        return Response("dashboard.html is missing from the deploy.", status=500)
    # no-store so a redeploy is picked up immediately, never served stale from the browser or the
    # platform proxy (matches /data.json).
    return Response(DASHBOARD_HTML, mimetype="text/html",
                    headers={"Cache-Control": "no-store"})


@app.post("/login")
def login():
    if hmac.compare_digest(request.form.get("password", ""), DASH_PASSWORD):
        session["ok"] = True
        session.permanent = True
        return redirect("/")
    return render_template_string(LOGIN_HTML, error="Incorrect password.",
                                  logo_rev=LOGO_REV, icon_rev=ICON_REV), 401


@app.get("/icon.png")
def icon():
    """The browser tab icon: the droplet in CLAY, not the bone lockup. A near-white mark is
    invisible on a light tab strip, and clay carries on both light and dark browser chrome.
    Public, like /logo.png - the unauthenticated login page references it."""
    if ICON_PNG is None:
        abort(404)
    return Response(ICON_PNG, mimetype="image/png",
                    headers={"Cache-Control": "public, max-age=86400"})


@app.get("/logout")
def logout():
    session.clear()
    return redirect("/")


@app.get("/logo.png")
def logo():
    """Serve the client mark (baked into the container). Public - the login page, which is itself
    unauthenticated, renders it."""
    if LOGO_PNG is None:
        abort(404)
    return Response(LOGO_PNG, mimetype="image/png",
                    headers={"Cache-Control": "public, max-age=86400"})


@app.get("/data.json")
def data():
    """The dashboard fetches this. Only an authenticated session gets it; everyone else gets 401,
    and the bucket itself stays private.

    PLACEHOLDER FALLBACK: until an export job has written a real lacevo.json to the bucket, serve
    the baked-in SAMPLE payload so the dashboard renders end to end behind its preview notice. Real
    data always wins the moment it exists."""
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


@app.get("/internal/notes.json")
def internal_notes():
    """Content for the staff-only Internal notes tab, fetched lazily when that tab is opened.

    It is a SEPARATE object from /data.json on purpose: keeping it off the payload every session
    downloads means hiding the tab is not the only thing standing between a client and it. The
    limitation to be honest about is that this service cannot yet tell a STAFF session from a CLIENT
    one - the bb_sso cookie carries the allowed-client list, not the role - so this route
    authenticates but does not authorize by role. Closing that gap means putting the role in the SSO
    token in bidbrain-platform/dash/platform_sso.py, which is vendored into every dashboard. Until
    then, nothing genuinely sensitive goes in internal_notes.json."""
    if not authed():
        abort(401)
    if INTERNAL_NOTES_JSON is None:
        abort(404)
    return Response(INTERNAL_NOTES_JSON, mimetype="application/json",
                    headers={"Cache-Control": "no-store"})


@app.get("/healthz")
def healthz():
    return Response("ok", mimetype="text/plain")
