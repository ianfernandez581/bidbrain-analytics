"""Sophiie AI dashboard web app (Cloud Run service).

Thin password gate + static server. It renders a login screen, and once a
session is authenticated it serves `dashboard.html` and proxies the private
`sophiie.json` from GCS at `/data.json`. All presentation logic - the aurora skin, the
Overview / Paid Media / Creative tabs - lives in `dashboard.html`; this file only
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
GCS_BUCKET = os.environ.get("GCS_BUCKET", "")               # private data bucket ("" until standup)
DATA_OBJECT = os.environ.get("DATA_OBJECT", "sophiie.json")   # object inside it

_storage = storage.Client()

# Dashboard HTML is baked into the container at build time, next to this file.
# Anchor to __file__ so it loads regardless of the process working directory.
_dash_dir = Path(__file__).resolve().parent
try:
    DASHBOARD_HTML = (_dash_dir / "dashboard.html").read_text(encoding="utf-8")
except FileNotFoundError:
    DASHBOARD_HTML = None

# PLACEHOLDER data baked into the container - a Sophiie AI-shaped SAMPLE payload (flagged
# meta.placeholder=true, which dashboard.html renders behind a loud "sample data" banner). It lets
# the scaffold render end-to-end BEFORE any real data is connected. The moment the export job writes
# the real sophiie.json to the bucket, /data.json serves THAT instead and the banner disappears.
try:
    PLACEHOLDER_JSON = (_dash_dir / "placeholder.json").read_bytes()
except FileNotFoundError:
    PLACEHOLDER_JSON = None

# Logo PNG baked into the container (COPY'd in the Dockerfile) - Sophiie's supplied mark. Served publicly so the login page and
# the AI deck builder (bbDeckLogos() fetches 'logo.png') can brand themselves. NOTE: the DASHBOARD
# itself does NOT use this route - it inlines the same artwork as a base64 data URI, because through
# the platform reverse proxy at /d/sophiie/ a root-relative asset path does not resolve.
try:
    LOGO_PNG = (_dash_dir / "logo.png").read_bytes()
except FileNotFoundError:
    LOGO_PNG = None

# Shared, theme-driven slide-deck builder (vendored - the canonical copy is re-copied into each dash
# folder). Served as a static asset so the dashboard's <script src="bb_deck.js"> loads it (relative →
# /bb_deck.js direct, or /d/sophiie/bb_deck.js through the platform proxy).
try:
    BB_DECK_JS = (_dash_dir / "bb_deck.js").read_text(encoding="utf-8")
except FileNotFoundError:
    BB_DECK_JS = ""

LOGIN_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sophiie AI Dashboard</title>
<link rel="icon" type="image/png" href="/logo.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:ital,opsz,wght@0,14..32,100..900;1,14..32,100..900&display=swap" rel="stylesheet">
<style>
  /* Sophiie AI - the same skin as the dashboard, so the login reads as its front door rather than a
     different product: "Chronicle - marble", now set entirely in Inter Variable (the three-face
     one value the user types) on a marble card lifted on shadow, over the drifting aurora.
     CSS ONLY here - no canvas and no JS, because a login page should render instantly and has no
     business running a requestAnimationFrame loop. So the aurora here is the two CSS layers only
     (orbs + diagonal bands); the canvas curtain layer is dashboard-side.
     Keep the two in step: every literal below mirrors a :root token in dashboard.html. */
  *{box-sizing:border-box;margin:0;padding:0}
  body{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px;
       font-family:'Inter Variable', Inter, system-ui, sans-serif;
       background:#EFEEEB;color:#0F0E0D;position:relative;overflow:hidden}

  /* layer 1 - ambient orbs */
  .orb{position:fixed;border-radius:50%;filter:blur(120px);pointer-events:none;z-index:0}
  .orb1{width:60vw;height:50vh;top:-8%;left:-10%;animation:amb1 9s ease-in-out infinite;
        background:radial-gradient(circle,rgba(116,170,212,.46) 0%,transparent 70%)}
  .orb2{width:50vw;height:45vh;top:4%;right:-8%;animation:amb2 11s ease-in-out infinite;
        background:radial-gradient(circle,rgba(126,198,220,.38) 0%,transparent 70%)}
  .orb3{width:55vw;height:50vh;bottom:-12%;left:14%;animation:amb3 12s ease-in-out infinite;
        background:radial-gradient(circle,rgba(124,176,216,.30) 0%,transparent 70%)}
  @keyframes amb1{0%,100%{transform:translate(0,0) scale(1)}50%{transform:translate(180px,130px) scale(1.22)}}
  @keyframes amb2{0%,100%{transform:translate(0,0) scale(1)}50%{transform:translate(-165px,120px) scale(1.20)}}
  @keyframes amb3{0%,100%{transform:translate(0,0) scale(1)}50%{transform:translate(130px,-175px) scale(1.18)}}

  /* layer 2 - the diagonal signature bands. Each keeps its own rotate() in EVERY keyframe: a
     transform is one property, so a frame that omits the rotation snaps the band flat. */
  .diag{position:fixed;pointer-events:none;z-index:0;transform-origin:center center}
  .d1{width:160%;height:300px;top:-6%;left:-30%;transform:rotate(-18deg);animation:sw1 5.5s ease-in-out infinite;
      background:linear-gradient(180deg,transparent 0%,rgba(116,170,212,.24) 20%,rgba(126,198,220,.44) 45%,rgba(140,206,228,.48) 55%,rgba(116,170,212,.24) 80%,transparent 100%)}
  .d2{width:150%;height:250px;top:26%;left:-25%;transform:rotate(-22deg);animation:sw2 7s ease-in-out infinite;
      background:linear-gradient(180deg,transparent 0%,rgba(126,198,220,.20) 20%,rgba(132,180,222,.38) 45%,rgba(140,206,228,.42) 55%,rgba(126,198,220,.20) 80%,transparent 100%)}
  .d3{width:160%;height:290px;top:62%;left:-30%;transform:rotate(-15deg);animation:sw3 5s ease-in-out infinite;
      background:linear-gradient(180deg,transparent 0%,rgba(126,198,220,.18) 20%,rgba(116,170,212,.34) 45%,rgba(126,198,220,.38) 55%,rgba(126,198,220,.18) 80%,transparent 100%)}
  @keyframes sw1{0%{transform:rotate(-18deg) translate(0,0);opacity:.8}25%{transform:rotate(-18deg) translate(70px,52px);opacity:1}50%{transform:rotate(-18deg) translate(-38px,100px);opacity:.7}75%{transform:rotate(-18deg) translate(54px,26px);opacity:1}100%{transform:rotate(-18deg) translate(0,0);opacity:.8}}
  @keyframes sw2{0%{transform:rotate(-22deg) translate(0,0);opacity:.7}30%{transform:rotate(-22deg) translate(-88px,70px);opacity:1}60%{transform:rotate(-22deg) translate(54px,-36px);opacity:.8}100%{transform:rotate(-22deg) translate(0,0);opacity:.7}}
  @keyframes sw3{0%{transform:rotate(-15deg) translate(0,0);opacity:.9}33%{transform:rotate(-15deg) translate(62px,-62px);opacity:.7}66%{transform:rotate(-15deg) translate(-45px,80px);opacity:1}100%{transform:rotate(-15deg) translate(0,0);opacity:.9}}

  /* The card - SOLID over the moving light (never translucent: see dashboard.html :root), on the same
     marble as the dashboard's KPI tiles with the same white wash, and lifted on shadow with NO border.
     `overflow:hidden` plus `border-radius:inherit` on the wash, or the overlay paints square corners
     over the rounded card. */
  .card{position:relative;z-index:1;width:100%;max-width:392px;padding:40px 36px 36px;border:0;border-radius:14px;
        background:#fff url("marble-cell.jpg") 34% 42%/230% no-repeat;overflow:hidden;
        box-shadow:0 2px 6px rgba(15,14,13,.06),0 26px 56px -20px rgba(15,14,13,.30)}
  .card::after{content:"";position:absolute;inset:0;border-radius:inherit;pointer-events:none;
        background:rgba(255,255,255,.42)}
  .card>*{position:relative;z-index:1}
  .logo-wrap{text-align:center;margin-bottom:22px}
  /* Sophiie's supplied mark is a white-field icon, so on a white card it needs no chip and no glow -
     just size. (The placeholder it replaced was a dark tile, which did want both.) */
  /* The mark has NO alpha channel (indexed PNG on a white field), so over marble its white field
     would read as a stray rectangle. A rounded chip makes the white deliberate - the same fix the
     dashboard topbar uses. */
  .logo-wrap img{height:74px;width:74px;display:inline-block;background:#fff;border-radius:16px;padding:5px;
        box-shadow:0 1px 2px rgba(15,14,13,.04),0 8px 20px -10px rgba(15,14,13,.22)}
  /* eyebrow / display title / dek - the dashboard's three-tier heading pattern */
  .brand{font-size:9px;font-weight:500;letter-spacing:.24em;color:#6A6660;margin-bottom:11px;text-transform:uppercase;text-align:center}
  h1{font-family:'Inter Variable', Inter, system-ui, sans-serif;font-size:29px;font-weight:500;margin:0 0 7px;
     letter-spacing:-.025em;text-align:center;color:#0F0E0D;line-height:1.15}
  p{font-size:12.5px;color:#3A3733;margin:0 0 24px;text-align:center;line-height:1.6}
  /* the one value the user types is set in the mono, like every measured figure on the dashboard */
  input{width:100%;padding:13px 15px;font-size:14px;font-family:'Inter Variable', Inter, system-ui, sans-serif;
        letter-spacing:.02em;color:#0F0E0D;background:#fff;
        border:.5px solid rgba(15,14,13,.20);border-radius:9px;outline:none;transition:border-color .15s,box-shadow .15s}
  input:focus{border-color:#0F0E0D;box-shadow:none}
  input::placeholder{color:#A8A29A;letter-spacing:.14em;text-transform:uppercase;font-size:11px}
  /* WHITE on the Sophiie blue - the brand's accent is dark enough to carry it (the opposite of the
     lime-brand dashboards, whose accent must carry ink). */
  button{width:100%;margin-top:12px;padding:14px;font-size:10px;font-weight:500;cursor:pointer;font-family:inherit;
         letter-spacing:.24em;text-transform:uppercase;
         background:#0F0E0D;color:#fff;border:none;border-radius:9px;
         transition:transform .22s cubic-bezier(.2,.7,.3,1),box-shadow .22s cubic-bezier(.2,.7,.3,1)}
  button:hover{transform:translateY(-2px);box-shadow:0 2px 6px rgba(15,14,13,.06),0 18px 34px -14px rgba(15,14,13,.40)}
  button:active{transform:translateY(0)}
  .err{margin-top:14px;font-family:'Inter Variable', Inter, system-ui, sans-serif;font-size:11.5px;color:#7A241F;min-height:16px;text-align:center}
  @media (prefers-reduced-motion: reduce){.orb,.diag{animation:none !important}button:hover{transform:none}}
</style>
</head>
<body>
  <div class="orb orb1"></div><div class="orb orb2"></div><div class="orb orb3"></div>
  <div class="diag d1"></div><div class="diag d2"></div><div class="diag d3"></div>
  <form class="card" method="POST" action="/login">
    <div class="logo-wrap">
      <img src="/logo.png" alt="Sophiie AI">
    </div>
    <div class="brand">BidBrain · Sophiie AI</div>
    <h1>Dashboard access</h1>
    <p>Enter the password to continue.</p>
    <input type="password" name="password" placeholder="Password" autofocus
           autocomplete="current-password">
    <button type="submit">Unlock Dashboard</button>
    <div class="err">{{ error or "" }}</div>
  </form>
</body>
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


@app.get("/logo.png")
def logo():
    """Serve the client logo (baked into the container). Public - no auth needed (the login page,
    which is itself unauthenticated, renders it)."""
    if LOGO_PNG is None:
        abort(404)
    return Response(LOGO_PNG, mimetype="image/png",
                    headers={"Cache-Control": "public, max-age=86400"})


# The Chronicle skin's marble textures. PUBLIC like /logo.png: they are decorative, they carry no
# client data, and the login page's own styling may want them later. Whitelisted by exact name so
# this can never become an arbitrary file read.
_MARBLE = {"marble-band.jpg", "marble-cell.jpg", "marble-tile.jpg"}
_MARBLE_CACHE = {}


@app.get("/<name>.jpg")
def marble(name):
    fn = f"{name}.jpg"
    if fn not in _MARBLE:
        abort(404)
    if fn not in _MARBLE_CACHE:
        try:
            _MARBLE_CACHE[fn] = (_dash_dir / fn).read_bytes()
        except FileNotFoundError:
            abort(404)
    return Response(_MARBLE_CACHE[fn], mimetype="image/jpeg",
                    headers={"Cache-Control": "public, max-age=604800"})   # immutable art, cache a week


@app.get("/logout")
def logout():
    session.clear()
    return redirect("/")


@app.get("/data.json")
def data():
    # The dashboard fetches this. Only an authenticated session gets it;
    # everyone else gets 401. The bucket itself stays private.
    #
    # PLACEHOLDER FALLBACK: until the export job has written a real sophiie.json to the bucket (i.e.
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
    ckey = "".join(c for c in str(summary.get("client") or "sophiie").lower()
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
