"""Geocon dashboard web app (Cloud Run service).

Thin password gate + static server. It renders a login screen, and once a
session is authenticated it serves `dashboard.html` and proxies the private
`geocon.json` from GCS at `/data.json`. All presentation logic — the Performance
and Optimise tabs — lives in `dashboard.html`; this file only decides *who* may
see it, not *what* it shows.
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
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{min-height:100vh;display:flex;align-items:center;justify-content:center;
       font-family:"Inter",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
       background:linear-gradient(135deg,#0E1A2B 0%,#1B2D44 100%);color:#fff;position:relative;overflow:hidden}
  body::after{content:'';position:absolute;bottom:0;left:0;right:0;height:3px;
              background:linear-gradient(90deg,#C8A55B 0%,#E0C88A 50%,#C8A55B 100%)}
  .card{width:100%;max-width:380px;padding:40px 34px;background:rgba(27,45,68,.85);
        border:1px solid rgba(255,255,255,.08);border-radius:16px;
        box-shadow:0 20px 60px rgba(0,0,0,.5);backdrop-filter:blur(10px)}
  .logo-wrap{text-align:center;margin-bottom:24px}
  .logo-wrap img{max-height:48px;max-width:220px;filter:brightness(0) invert(1);opacity:.9}
  .brand{font-size:11px;font-weight:700;letter-spacing:1.6px;color:#C8A55B;margin-bottom:6px;text-transform:uppercase}
  h1{font-size:20px;font-weight:700;margin:0 0 4px;letter-spacing:-.3px}
  p{font-size:13px;color:rgba(255,255,255,.55);margin:0 0 24px}
  input{width:100%;padding:13px 15px;font-size:15px;color:#fff;background:rgba(14,26,43,.6);
        border:1px solid rgba(255,255,255,.14);border-radius:10px;outline:none;transition:border-color .15s}
  input:focus{border-color:#C8A55B}
  input::placeholder{color:rgba(255,255,255,.3)}
  button{width:100%;margin-top:14px;padding:13px;font-size:15px;font-weight:700;cursor:pointer;
         background:linear-gradient(135deg,#C8A55B 0%,#E0C88A 100%);color:#0E1A2B;border:none;border-radius:10px;
         transition:transform .1s ease,box-shadow .2s ease;letter-spacing:.3px}
  button:hover{transform:translateY(-1px);box-shadow:0 6px 20px rgba(200,165,91,.3)}
  button:active{transform:translateY(0)}
  .err{margin-top:14px;font-size:13px;color:#FF8B80;min-height:16px;text-align:center}
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