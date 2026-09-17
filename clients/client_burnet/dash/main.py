"""Burnet Institute dashboard web app (Cloud Run service).

Thin password gate + static server, the same shape as every other tenant in the estate: it renders
a login screen, and once a session is authenticated it serves `dashboard.html` and proxies the
private `burnet.json` from GCS at `/data.json`. All presentation logic lives in `dashboard.html`;
this file only decides *who* may see it, not *what* it shows.

SESSION SCOPE. A session here opens Burnet and nothing else. There are two ways in and neither
crosses a tenant boundary: this dashboard's OWN password (`session["ok"]`, signed with a
Burnet-only SESSION_SECRET, so a cookie minted by another dashboard cannot be read here), or the
platform's `bb_sso` cookie, which carries the list of clients that session may open and is checked
against CLIENT_KEY below. Everything private is behind `authed()` - the dashboard, the payload and
the internal notes - and the data bucket itself stays private, read only by this service's own
service account.

PREVIEW TENANT. Burnet has no data pipeline yet (no BigQuery dataset, no sql/ views, no export
job), so the bucket is empty and `/data.json` falls back to the baked-in sample payload
`placeholder.json`, which carries `meta.placeholder=true`. The dashboard renders its preview notice
and every placeholder marker off that one flag. The moment an export job writes a real burnet.json
to the bucket, that wins and all of it disappears - no code change, no redeploy. See README.md ->
"Flipping preview to live".

There is deliberately NO `/report` endpoint: the AI deck needs `roles/aiplatform.user` and a
client-specific prompt set, and neither is warranted while every number on the page is invented.
"""
import hashlib
import hmac
import os
from pathlib import Path

from flask import (
    Flask, Response, abort, redirect, render_template_string, request, session
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
GCS_BUCKET = os.environ.get("GCS_BUCKET", "")                # private data bucket (empty until a job exists)
DATA_OBJECT = os.environ.get("DATA_OBJECT", "burnet.json")   # object inside it

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
# The supplied Burnet lockup, as VECTOR. The login page is served from the service root, so it can
# reference this route; the DASHBOARD cannot, because behind the platform proxy it is served at
# /d/burnet/ where a root-relative path resolves to the platform's namespace and 404s - so the
# dashboard carries the same SVG inline, injected by gen_brand_assets.py between markers. Both come
# from creatives/burnet-lockup.svg, so neither is hand-maintained.
LOGO_SVG = _read_bytes("logo.svg")
ICON_PNG = _read_bytes("icon.png")   # the MARK alone, rasterised, for the browser tab


def _rev(b):
    """Short content hash, used to cache-bust the brand assets.

    They are served with `max-age=86400`, which is right for artwork - but it means that when a
    logo is replaced, every browser that has already opened the login keeps serving the OLD one for
    a day and the deploy looks like it silently failed. That happened on the Lacevo standup and the
    client spotted it before we did. Hashing the bytes into the URL keeps the long cache correct AND
    makes a swap visible immediately."""
    return hashlib.sha1(b).hexdigest()[:10] if b else "0"


LOGO_REV = _rev(LOGO_SVG)
ICON_REV = _rev(ICON_PNG)

# STAFF-ONLY content for the Internal Notes tab, kept OUT of data.json on purpose - the precedent is
# client_schneidersecpwr's Reports tab and client_lacevo's notes tab, whose content is fetched from
# its own endpoint so that hiding the tab is not the only thing protecting it. Read the honest
# limitation in README.md -> "Internal Notes": this service can authenticate a visitor but cannot
# yet tell a staff session from a client one, so the route below is gated on being logged in, not
# on being staff.
INTERNAL_NOTES_JSON = _read_bytes("internal_notes.json")

LOGIN_HTML = """<!doctype html>
<html lang="en-AU">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Burnet Institute Dashboard</title>
<link rel="icon" type="image/png" href="/icon.png?v={{ icon_rev }}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400..700&display=swap" rel="stylesheet">
<style>
  /* Burnet login: a PEACH card on a white field, which is the arrangement burnet.edu.au itself
     uses - white page, warm panels. The dashboard behind it is light too, so unlike the Lacevo
     login there is no inversion to manage between the two surfaces.

     THE COLOUR RULE, same as the dashboard's: BRAND ORANGE IS A FILL, NEVER TEXT. #F76E3B on
     white is 2.9:1 and fails at any size, and white on #F76E3B is the same 2.9:1 the other way -
     so the submit button is filled with the DEEP #BD572F (4.6:1 under white text), and any orange
     that has to be read is the deep one too. The bright accent survives as the rule under the
     card, the dot beside the eyebrow and the focus glow, where nothing has to be read off it. */
  *{box-sizing:border-box;margin:0;padding:0}
  body{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px;
       font-family:Inter,-apple-system,"Segoe UI",Roboto,sans-serif;
       background:#FFFFFF;color:#27272A;position:relative;overflow:hidden;
       -webkit-font-smoothing:antialiased}
  body::before{content:'';position:absolute;inset:0;pointer-events:none;
       background:
         radial-gradient(900px 560px at 50% -14%, rgba(253,240,234,.95), transparent 62%),
         radial-gradient(680px 460px at 94% 4%, rgba(249,212,196,.55), transparent 64%),
         radial-gradient(760px 600px at 0% 96%, rgba(253,240,234,.85), transparent 62%)}
  body::after{content:'';position:absolute;bottom:0;left:0;right:0;height:3px;
       background:linear-gradient(90deg,#BD572F 0%,#F76E3B 54%,#F9D4C4 100%)}
  /* Two shadows: a tight contact shadow that seats the card on the page, and a wide soft one that
     is the light falling past it. The inset top edge is what makes a card read as a surface
     rather than a hole. */
  .card{position:relative;width:100%;max-width:420px;padding:42px 38px 32px;background:#FDF0EA;
        border:1px solid #F9D4C4;border-radius:16px;
        box-shadow:0 2px 4px rgba(74,42,26,.05),
                   0 30px 60px -26px rgba(74,42,26,.30),
                   inset 0 1px 0 rgba(255,255,255,.85)}
  .logo-wrap{text-align:center;margin-bottom:26px}
  /* The lockup is wide, not square: constrain its WIDTH and let height follow, or a max-height on
     a 3:1 image leaves it tiny in a 420px card. */
  .logo-wrap img{width:196px;max-width:64%;height:auto;display:inline-block}
  .brand{display:flex;align-items:center;justify-content:center;gap:.5rem;
         font-size:10px;font-weight:700;letter-spacing:2.2px;color:#BD572F;
         margin-bottom:10px;text-transform:uppercase}
  .brand i{width:7px;height:7px;border-radius:50%;background:#F76E3B;flex:0 0 auto}
  /* No typeset "Burnet Institute" here: the lockup IS the wordmark, and repeating it underneath
     would be the brand name twice, the second time in the wrong typeface. */
  p.sub{font-size:13px;color:#63636B;margin:0 0 24px;text-align:center;line-height:1.55}
  input{width:100%;padding:14px 15px;font-size:15px;font-family:inherit;color:#27272A;
        background:#FFFFFF;border:1px solid rgba(39,39,42,.14);border-radius:10px;outline:none;
        transition:border-color .18s,box-shadow .18s}
  input:focus{border-color:#BD572F;box-shadow:0 0 0 3px rgba(247,110,59,.20)}
  input::placeholder{color:#8A8A92}
  button[type="submit"]{width:100%;margin-top:14px;padding:14px;font-size:15px;font-weight:600;
         cursor:pointer;font-family:inherit;letter-spacing:.3px;
         background:linear-gradient(180deg,#C9613A,#BD572F);color:#FFFFFF;
         border:1px solid #A94D29;border-radius:10px;
         transition:translate .1s ease,box-shadow .2s ease,filter .18s ease}
  /* `translate`, never the `transform` shorthand: the login kit centres its show/hide control
     with a translate, and a `transform` on the bare button selector would outrank and replace it,
     dropping the control half its own height down the field on hover. */
  button[type="submit"]:hover{translate:0 -1px;box-shadow:0 12px 26px -10px rgba(189,87,47,.58);
         filter:brightness(1.04)}
  button[type="submit"]:active{translate:0 0}
  .err{margin-top:14px;font-size:13px;color:#A33B22;min-height:16px;text-align:center}
  .foot{margin-top:24px;padding-top:16px;border-top:1px solid #F9D4C4;
        font-size:11px;color:#8A8A92;text-align:center;line-height:1.6}
</style>
</head>
<body>
<form class="card" method="post" action="login">
  <div class="logo-wrap"><img src="/logo.svg?v={{ logo_rev }}" alt="Burnet Institute"></div>
  <div class="brand"><i></i>100% Digital</div>
  <p class="sub">Campaign reporting for Burnet Institute</p>
  <input type="password" name="password" placeholder="Password" autofocus autocomplete="current-password">
  <button type="submit">Open dashboard</button>
  <div class="err">{{ error or "" }}</div>
  <div class="foot">Preview build - the feeds are not connected yet.</div>
</form>
</body>
</html>"""


def authed():
    """Authenticated by THIS dashboard's own password (session["ok"]) OR by a platform-issued SSO
    cookie from dashboards.bidbrain.ai that names this client. Fail-closed and fail-safe: any
    problem falls back to password-only, so this can never break the existing gate, and neither
    path can be satisfied by a session belonging to another tenant."""
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


@app.get("/logout")
def logout():
    session.clear()
    return redirect("/")


@app.get("/logo.svg")
def logo():
    """The client lockup, baked into the container. Public - the login page, which is itself
    unauthenticated, renders it."""
    if LOGO_SVG is None:
        abort(404)
    return Response(LOGO_SVG, mimetype="image/svg+xml",
                    headers={"Cache-Control": "public, max-age=86400"})


@app.get("/icon.png")
def icon():
    """The browser tab icon: the MARK alone, in brand orange on transparent. The wordmark is
    illegible at 16px, and orange carries on both light and dark browser chrome. Public, like
    /logo.svg - the unauthenticated login page references it."""
    if ICON_PNG is None:
        abort(404)
    return Response(ICON_PNG, mimetype="image/png",
                    headers={"Cache-Control": "public, max-age=86400"})


@app.get("/data.json")
def data():
    """The dashboard fetches this. Only an authenticated session gets it; everyone else gets 401,
    and the bucket itself stays private.

    PLACEHOLDER FALLBACK: until an export job has written a real burnet.json to the bucket, serve
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
    """Content for the staff-only Internal Notes tab, fetched lazily when that tab is opened.

    It is a SEPARATE object from /data.json on purpose: keeping it off the payload every session
    downloads means hiding the tab is not the only thing standing between a client and it. The
    limitation to be honest about is that this route AUTHENTICATES BUT DOES NOT AUTHORIZE BY ROLE -
    the bb_sso cookie carries the allowed-client list, not the role - so a logged-in client who
    guessed the path would be served it. Closing that gap means putting the role in the SSO token in
    bidbrain-platform/dash/platform_sso.py, which is vendored into every dashboard in the estate.
    Until then, nothing genuinely sensitive goes in internal_notes.json; feed status and questions
    to ask are the right ceiling for it."""
    if not authed():
        abort(401)
    if INTERNAL_NOTES_JSON is None:
        abort(404)
    return Response(INTERNAL_NOTES_JSON, mimetype="application/json",
                    headers={"Cache-Control": "no-store"})


@app.get("/healthz")
def healthz():
    return Response("ok", mimetype="text/plain")
