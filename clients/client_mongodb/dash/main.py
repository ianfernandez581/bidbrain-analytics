"""MongoDB APAC dashboard web app (Cloud Run service).

Thin password gate + static server. It renders a login screen, and once a
session is authenticated it serves `dashboard.html` and proxies the private
`<client>.json` from GCS at `/data.json`. All presentation logic — the
Paid Media / Content Syndication tabs, the DNB vs KGA(IDC) campaign toggle,
and the regional filter — lives in `dashboard.html`; this file only decides
*who* may see it, not *what* it shows.
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
    # Hard cap on request bodies (Werkzeug 413s anything larger, even chunked / no Content-Length).
    # The /report POST is the only sizeable body; everything else is tiny.
    MAX_CONTENT_LENGTH=256 * 1024,
)

# --- config (injected by Cloud Run) ------------------------------------------
DASH_PASSWORD = os.environ["DASH_PASSWORD"].rstrip("\r\n")   # from Secret Manager
GCS_BUCKET = os.environ["GCS_BUCKET"]                        # private data bucket
DATA_OBJECT = os.environ.get("DATA_OBJECT", "mongodb.json")  # object inside it

_storage = storage.Client()

# Dashboard HTML is baked into the container at build time, next to this file.
# Anchor to __file__ so it loads regardless of the process working directory.
try:
    DASHBOARD_HTML = (Path(__file__).resolve().parent / "dashboard.html").read_text(encoding="utf-8")
except FileNotFoundError:
    DASHBOARD_HTML = None

# Shared, theme-driven slide-deck builder (vendored — the canonical copy is re-copied into each
# dash folder). Served as a static asset so the dashboard's <script src="bb_deck.js"> loads it
# (relative → /bb_deck.js direct, or /d/<c>/bb_deck.js through the platform proxy).
try:
    BB_DECK_JS = (Path(__file__).resolve().parent / "bb_deck.js").read_text(encoding="utf-8")
except FileNotFoundError:
    BB_DECK_JS = ""

LOGIN_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MongoDB APAC Dashboard</title>
<style>
  *{box-sizing:border-box}
  body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
       font-family:-apple-system,BlinkMacSystemFont,"Inter","Segoe UI",Roboto,sans-serif;
       background:#001E2B;color:#fff}
  .card{width:100%;max-width:340px;padding:34px 30px;background:#03293A;
        border:1px solid rgba(255,255,255,.08);border-radius:14px;
        box-shadow:0 12px 44px rgba(0,0,0,.4)}
  .brand{font-size:12px;font-weight:700;letter-spacing:1.4px;color:#00ED64;margin-bottom:18px}
  h1{font-size:18px;font-weight:700;margin:0 0 4px}
  p{font-size:13px;color:rgba(255,255,255,.6);margin:0 0 22px}
  input{width:100%;padding:12px 13px;font-size:15px;color:#fff;background:#001E2B;
        border:1px solid rgba(255,255,255,.16);border-radius:9px;outline:none}
  input:focus{border-color:#00ED64}
  button{width:100%;margin-top:12px;padding:12px;font-size:15px;font-weight:700;cursor:pointer;
         background:#00ED64;color:#001E2B;border:none;border-radius:9px}
  button:hover{background:#00d459}
  .err{margin-top:12px;font-size:13px;color:#FF6B6B;min-height:16px}
</style>
</head>
<body>
  <form class="card" method="POST" action="/login">
    <div class="brand">TRANSMISSION · MONGODB APAC</div>
    <h1>Dashboard access</h1>
    <p>Enter the password to continue.</p>
    <input type="password" name="password" placeholder="Password" autofocus
           autocomplete="current-password">
    <button type="submit">Unlock</button>
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


@app.get("/bb_deck.js")
def bb_deck_js():
    # The slide-deck builder. Auth-gated like the dashboard (the deck reveals report content).
    if not authed():
        abort(401)
    if not BB_DECK_JS:
        return Response("// bb_deck.js missing from the deploy", status=500, mimetype="application/javascript")
    return Response(BB_DECK_JS, mimetype="application/javascript",
                    headers={"Cache-Control": "no-store"})


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
    # AI account report. Auth-gated like the dashboard. The browser POSTs the current view's
    # numbers (the same figures it renders); we cache the generated report in the private bucket
    # keyed by VIEW IDENTITY + DATA VERSION, so re-downloading the same view costs no model calls
    # and regenerates only when the underlying data advances. (Two users hitting the SAME uncached
    # view at once may both generate once — accepted: low traffic, and the UI disables the button
    # during generation so a single user can't double-fire.)
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
        "campaign": ctx.get("campaign_key"),
        "markets": sorted(ctx.get("markets") or []),
        "date_filter": ctx.get("date_filter") or {},
        "data_through": ctx.get("data_through"),
        "v": REPORT_CACHE_VERSION,
    }, sort_keys=True)
    h = hashlib.sha256(key_src.encode("utf-8")).hexdigest()[:16]
    ckey = "".join(c for c in str(summary.get("client") or "mongodb").lower()
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


@app.get("/healthz")
def healthz():
    return "ok"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
