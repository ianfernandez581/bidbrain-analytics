"""Geyer Valmont dashboard web app (Cloud Run service).

Thin password gate + static server. It renders a login screen, and once a
session is authenticated it serves `dashboard.html` and proxies the private
`geyervalmont.json` from GCS at `/data.json`. All presentation logic — the Executive /
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
GCS_BUCKET = os.environ.get("GCS_BUCKET", "")               # private data bucket ("" until standup)
DATA_OBJECT = os.environ.get("DATA_OBJECT", "geyervalmont.json")   # object inside it

_storage = storage.Client()

# Dashboard HTML is baked into the container at build time, next to this file.
# Anchor to __file__ so it loads regardless of the process working directory.
_dash_dir = Path(__file__).resolve().parent
try:
    DASHBOARD_HTML = (_dash_dir / "dashboard.html").read_text(encoding="utf-8")
except FileNotFoundError:
    DASHBOARD_HTML = None

# PLACEHOLDER data baked into the container — a Geyer Valmont-branded SAMPLE payload (flagged
# meta.placeholder=true, which dashboard.html renders behind a loud "sample data" banner). It lets
# the scaffold render end-to-end BEFORE any real data is connected. The moment the export job writes
# the real geyervalmont.json to the bucket, /data.json serves THAT instead and the banner disappears.
try:
    PLACEHOLDER_JSON = (_dash_dir / "placeholder.json").read_bytes()
except FileNotFoundError:
    PLACEHOLDER_JSON = None

# Logo PNG baked into the container (COPY'd in the Dockerfile). Served publicly so the login page and
# the AI deck builder (bbDeckLogos() fetches 'logo.png') can brand themselves. NOTE: the DASHBOARD
# itself does NOT use this route — it inlines the same artwork as a base64 data URI, because through
# the platform reverse proxy at /d/geyervalmont/ a root-relative asset path does not resolve.
try:
    LOGO_PNG = (_dash_dir / "logo.png").read_bytes()
except FileNotFoundError:
    LOGO_PNG = None

# Shared, theme-driven slide-deck builder (vendored — the canonical copy is re-copied into each dash
# folder). Served as a static asset so the dashboard's <script src="bb_deck.js"> loads it (relative →
# /bb_deck.js direct, or /d/geyervalmont/bb_deck.js through the platform proxy).
try:
    BB_DECK_JS = (_dash_dir / "bb_deck.js").read_text(encoding="utf-8")
except FileNotFoundError:
    BB_DECK_JS = ""

LOGIN_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Geyer Valmont Dashboard</title>
<link rel="icon" type="image/png" href="/logo.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  /* Geyer Valmont: white card on a lime-bloomed white canvas, navy ink. Lime is an accent only,
     and text sitting ON lime is always navy (#131B46) - never white. */
  *{box-sizing:border-box;margin:0;padding:0}
  body{min-height:100vh;display:flex;align-items:center;justify-content:center;
       font-family:"Space Grotesk","Inter",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
       background:#F7F8F1;color:#131B46;position:relative;overflow:hidden}
  body::before{content:'';position:absolute;inset:0;pointer-events:none;
       background:radial-gradient(760px 420px at 50% -8%, rgba(230,255,49,.50), transparent 62%),
                  radial-gradient(560px 320px at 50% -2%, rgba(233,253,94,.38), transparent 66%),
                  radial-gradient(680px 340px at 86% 6%, rgba(87,65,30,.08), transparent 68%)}
  body::after{content:'';position:absolute;bottom:0;left:0;right:0;height:3px;
              background:linear-gradient(90deg,#E6FF31 0%,#E9FD5E 46%,#57411E 100%)}
  .card{position:relative;width:100%;max-width:390px;padding:40px 34px;background:#FFFFFF;
        border:1px solid #E6E8DC;border-radius:16px;
        box-shadow:0 22px 60px -22px rgba(19,27,70,.30),0 0 44px -18px rgba(230,255,49,.65)}
  .logo-wrap{text-align:center;margin-bottom:24px}
  .logo-wrap img{max-height:96px;max-width:96px;display:inline-block;border-radius:14px;
        box-shadow:0 0 0 1px rgba(19,27,70,.10),0 10px 26px -10px rgba(185,206,0,.95)}
  .brand{font-size:10px;font-weight:700;letter-spacing:2.2px;color:#57411E;margin-bottom:8px;text-transform:uppercase}
  h1{font-size:22px;font-weight:700;margin:0 0 5px;letter-spacing:-.2px}
  p{font-size:13px;color:rgba(19,27,70,.62);margin:0 0 24px}
  input{width:100%;padding:13px 15px;font-size:15px;color:#131B46;background:#F7F8F1;
        border:1px solid #D4D8C4;border-radius:8px;outline:none;transition:border-color .15s,box-shadow .15s}
  input:focus{border-color:#B9CE00;box-shadow:0 0 0 3px rgba(230,255,49,.45)}
  input::placeholder{color:rgba(19,27,70,.42)}
  /* navy on lime - the brand's one hard contrast rule */
  button{width:100%;margin-top:14px;padding:13px;font-size:15px;font-weight:700;cursor:pointer;
         background:#E6FF31;color:#131B46;border:1px solid #B9CE00;border-radius:8px;
         transition:transform .1s ease,box-shadow .2s ease;letter-spacing:.3px}
  button:hover{transform:translateY(-1px);box-shadow:0 8px 22px -6px rgba(185,206,0,.85)}
  button:active{transform:translateY(0)}
  .err{margin-top:14px;font-size:13px;color:#C0392B;min-height:16px;text-align:center}
</style>
</head>
<body>
  <form class="card" method="POST" action="/login">
    <div class="logo-wrap">
      <img src="/logo.png" alt="Geyer Valmont">
    </div>
    <div class="brand">BidBrain · Geyer Valmont</div>
    <h1>Dashboard Access</h1>
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


@app.get("/logout")
def logout():
    session.clear()
    return redirect("/")


@app.get("/data.json")
def data():
    # The dashboard fetches this. Only an authenticated session gets it;
    # everyone else gets 401. The bucket itself stays private.
    #
    # PLACEHOLDER FALLBACK: until the export job has written a real geyervalmont.json to the bucket (i.e.
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
    ckey = "".join(c for c in str(summary.get("client") or "geyervalmont").lower()
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
