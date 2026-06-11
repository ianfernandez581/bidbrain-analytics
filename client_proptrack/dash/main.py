"""PropTrack (Transmission) dashboard web app (Cloud Run service).

Thin password gate + static server. It renders a login screen, and once a
session is authenticated it serves `dashboard.html` and proxies the private
`proptrack.json` from GCS at `/data.json`. All presentation logic — the Overview /
Programmatic / Paid Social tabs and every chart — lives in `dashboard.html`; this
file only decides *who* may see it, not *what* it shows.

Same service pattern as client_STT/dash/main.py (byte-for-byte on the auth/serve/proxy
logic); only the login-page branding and the default data object differ. The org policy
that blocks --allow-unauthenticated is handled the same way — the deploy flips
--no-invoker-iam-check so this app's own password gate is the only door.
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
DATA_OBJECT = os.environ.get("DATA_OBJECT", "proptrack.json")  # object inside it

_storage = storage.Client()

# Dashboard HTML is baked into the container at build time, next to this file.
# Anchor to __file__ so it loads regardless of the process working directory.
try:
    DASHBOARD_HTML = (Path(__file__).resolve().parent / "dashboard.html").read_text(encoding="utf-8")
except FileNotFoundError:
    DASHBOARD_HTML = None

LOGIN_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PropTrack · Dashboard</title>
<style>
  *{box-sizing:border-box}
  body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
       font-family:-apple-system,BlinkMacSystemFont,"Inter","Segoe UI",Roboto,sans-serif;
       background:radial-gradient(1200px 600px at 50% -10%,#10403B 0%,#0C2E2B 55%,#08201E 100%)}
  .card{width:100%;max-width:360px;padding:36px 32px;background:#fff;
        border:1px solid rgba(0,0,0,.06);border-radius:16px;
        box-shadow:0 20px 64px rgba(0,0,0,.34)}
  .logo{display:flex;justify-content:center;margin-bottom:18px}
  .wordmark{display:inline-flex;align-items:center;gap:9px;font-weight:800;font-size:24px;
            letter-spacing:-.4px;color:#0C7C84}
  .wordmark .pin{width:13px;height:13px;border-radius:50% 50% 50% 2px;transform:rotate(45deg);
                 background:linear-gradient(135deg,#0C7C84,#0E6E64)}
  .brand{font-size:11px;font-weight:700;letter-spacing:1.6px;color:#0C7C84;margin-bottom:14px;text-align:center}
  h1{font-size:18px;font-weight:700;margin:0 0 4px;color:#13302E;text-align:center}
  p{font-size:13px;color:#5E7572;margin:0 0 22px;text-align:center}
  input{width:100%;padding:12px 13px;font-size:15px;color:#13302E;background:#fff;
        border:1px solid #E2E9E8;border-radius:10px;outline:none}
  input:focus{border-color:#0C7C84;box-shadow:0 0 0 3px rgba(12,124,132,.12)}
  button{width:100%;margin-top:12px;padding:12px;font-size:15px;font-weight:700;cursor:pointer;
         background:#0C7C84;color:#fff;border:none;border-radius:10px}
  button:hover{background:#0A5C56}
  .err{margin-top:12px;font-size:13px;color:#C8362A;min-height:16px;text-align:center}
</style>
</head>
<body>
  <form class="card" method="POST" action="/login">
    <div class="logo">
      <span class="wordmark"><span class="pin"></span>PropTrack</span>
    </div>
    <div class="brand">TRANSMISSION · PROPTRACK</div>
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
