"""ResetData B2B dashboard web app (Cloud Run service).

Thin password gate + static server. It renders a login screen, and once a session
is authenticated it serves `dashboard.html` and proxies the private `resetdata.json`
from GCS at `/data.json`. All presentation logic — the Overview / Paid Media /
Website Traffic / Ads → Traffic tabs and every chart — lives in `dashboard.html`;
this file only decides *who* may see it, not *what* it shows.

Same service pattern as client_STT/dash/main.py (byte-for-byte on the auth/serve/
proxy logic); only the login-page branding and the default data object differ. The
org policy that blocks --allow-unauthenticated is handled the same way — the deploy
flips --no-invoker-iam-check so this app's own password gate is the only door.
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
DATA_OBJECT = os.environ.get("DATA_OBJECT", "resetdata.json")  # object inside it

_storage = storage.Client()

# Dashboard HTML is baked into the container at build time, next to this file.
# Anchor to __file__ so it loads regardless of the process working directory.
try:
    DASHBOARD_HTML = (Path(__file__).resolve().parent / "dashboard.html").read_text(encoding="utf-8")
except FileNotFoundError:
    DASHBOARD_HTML = None

# ============================================================================
# Branding: the 100% Digital agency mark + the ResetData wordmark are inlined as
# base64 (from client_resetdata/creatives/). Palette is ResetData's crimson-pink
# (#E84A6F) accent on deep navy — taken from the brand logo + website.
# ============================================================================
LOGIN_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ResetData · Performance Dashboard</title>
<style>
  *{box-sizing:border-box}
  body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
       font-family:-apple-system,BlinkMacSystemFont,"Inter","Segoe UI",Roboto,sans-serif;
       background:radial-gradient(1200px 600px at 50% -10%,#13233B 0%,#0E1726 55%,#080C14 100%)}
  .card{width:100%;max-width:360px;padding:36px 32px;background:#0F1A2B;
        border:1px solid rgba(232,74,111,.22);border-radius:16px;
        box-shadow:0 20px 64px rgba(0,0,0,.55)}
  .logo{display:flex;align-items:center;justify-content:center;gap:13px;margin-bottom:8px}
  .logo .agency{height:26px;width:auto;display:block}
  .logo .divider{width:1px;height:26px;background:#25364B;display:inline-block}
  .logo .client{height:26px;width:auto;display:block}
  .brand{font-size:10.5px;font-weight:700;letter-spacing:1.8px;color:#F472A0;margin:14px 0;text-align:center}
  h1{font-size:18px;font-weight:700;margin:0 0 4px;color:#E8F0FA;text-align:center}
  p{font-size:13px;color:#8CA0B8;margin:0 0 22px;text-align:center}
  input{width:100%;padding:12px 13px;font-size:15px;color:#E8F0FA;background:#0A1422;
        border:1px solid #25364B;border-radius:10px;outline:none}
  input::placeholder{color:#5C7187}
  input:focus{border-color:#E84A6F;box-shadow:0 0 0 3px rgba(232,74,111,.18)}
  button{width:100%;margin-top:12px;padding:12px;font-size:15px;font-weight:700;cursor:pointer;
         background:#E84A6F;color:#fff;border:none;border-radius:10px}
  button:hover{background:#D43F62}
  .err{margin-top:12px;font-size:13px;color:#FB7185;min-height:16px;text-align:center}
</style>
</head>
<body>
  <form class="card" method="POST" action="/login">
    <!-- 100% Digital agency mark · divider · ResetData wordmark (both inline base64) -->
    <div class="logo">
      <img class="agency" src="data:image/webp;base64,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" alt="100% Digital">
      <span class="divider"></span>
      <img class="client" src="data:image/webp;base64,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" alt="ResetData">
    </div>
    <div class="brand">100% DIGITAL · RESETDATA</div>
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
    return session.get("ok") is True


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
