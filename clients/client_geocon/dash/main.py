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

LOGIN_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Geocon Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;600;700;800;900&display=swap" rel="stylesheet">
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{min-height:100vh;display:flex;align-items:center;justify-content:center;
       font-family:"Montserrat","Inter",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
       background:#231A17;color:#FFFEEC;position:relative;overflow:hidden}
  body::after{content:'';position:absolute;bottom:0;left:0;right:0;height:3px;
              background:#6C291B}
  .card{width:100%;max-width:390px;padding:40px 34px;background:#6C291B;
        border:1px solid rgba(255,254,236,.16);border-radius:8px;
        box-shadow:0 22px 70px rgba(0,0,0,.42)}
  .logo-wrap{text-align:center;margin-bottom:24px}
  .logo-wrap img{max-height:60px;max-width:250px;opacity:.96}
  .brand{font-size:10px;font-weight:800;letter-spacing:2.2px;color:#BD9A8E;margin-bottom:8px;text-transform:uppercase}
  h1{font-size:22px;font-weight:900;margin:0 0 5px;letter-spacing:0}
  p{font-size:13px;color:rgba(255,254,236,.68);margin:0 0 24px}
  input{width:100%;padding:13px 15px;font-size:15px;color:#FFFEEC;background:rgba(35,26,23,.5);
        border:1px solid rgba(255,254,236,.18);border-radius:8px;outline:none;transition:border-color .15s}
  input:focus{border-color:#FFFEEC}
  input::placeholder{color:rgba(255,254,236,.38)}
  button{width:100%;margin-top:14px;padding:13px;font-size:15px;font-weight:700;cursor:pointer;
         background:#FFFEEC;color:#231A17;border:none;border-radius:8px;
         transition:transform .1s ease,box-shadow .2s ease;letter-spacing:.3px}
  button:hover{transform:translateY(-1px);box-shadow:0 8px 22px rgba(35,26,23,.28)}
  button:active{transform:translateY(0)}
  .err{margin-top:14px;font-size:13px;color:#FFDED5;min-height:16px;text-align:center}
</style>
</head>
<body>
  <form class="card" method="POST" action="/login">
    <div class="logo-wrap">
      <img src="/logo.png" alt="Gateway Braddon" onerror="this.style.display='none'">
    </div>
    <div class="brand">BidBrain · Geocon</div>
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


@app.get("/healthz")
def healthz():
    return "ok"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
