"""VMCH dashboard web app (Cloud Run service).

Thin password gate + static server. It renders a login screen, and once a
session is authenticated it serves `dashboard.html` and proxies the private
`vmch.json` from GCS at `/data.json`. All presentation logic — the Overview /
Trade Desk / Website / Media \u2192 Traffic tabs and every chart — lives in
`dashboard.html`; this file only decides *who* may see it, not *what* it shows.

Same service pattern as client_STT/dash/main.py (byte-for-byte on the
auth/serve/proxy logic); only the login-page branding and the default data
object differ. The org policy that blocks --allow-unauthenticated is handled the
same way — the deploy flips --no-invoker-iam-check so this app's own password
gate is the only door.
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
    SESSION_COOKIE_SAMESITE="None",
    PERMANENT_SESSION_LIFETIME=60 * 60 * 12,
)

# --- config (injected by Cloud Run) ------------------------------------------
DASH_PASSWORD = os.environ["DASH_PASSWORD"].rstrip("\r\n")
GCS_BUCKET = os.environ["GCS_BUCKET"]
DATA_OBJECT = os.environ.get("DATA_OBJECT", "vmch.json")

_storage = storage.Client()

try:
    DASHBOARD_HTML = (Path(__file__).resolve().parent / "dashboard.html").read_text(encoding="utf-8")
except FileNotFoundError:
    DASHBOARD_HTML = None

LOGIN_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>VMCH · Villa Maria Catholic Homes · Dashboard</title>
<style>
  *{box-sizing:border-box}
  body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
       font-family:-apple-system,BlinkMacSystemFont,"Inter","Segoe UI",Roboto,sans-serif;
       background:radial-gradient(1100px 560px at 50% -8%,#6B3A48 0%,#4C2736 55%,#341822 100%)}
  .card{width:100%;max-width:368px;padding:34px 32px;background:#fff;
        border:1px solid rgba(0,0,0,.05);border-radius:16px;
        box-shadow:0 22px 64px rgba(36,19,24,.40)}
  .logo{display:flex;justify-content:center;margin-bottom:14px}
  .logo img{height:44px;width:auto;display:block}
  .agency{display:flex;align-items:center;justify-content:center;gap:7px;margin-bottom:20px;
          font-size:10.5px;font-weight:700;letter-spacing:1.4px;color:#8C7E80;text-transform:uppercase}
  .agency b{color:#2A1E20;font-weight:800}
  .agency .pc{color:#EB3300}
  .agency .sep{width:4px;height:4px;border-radius:50%;background:#D9CFC8}
  h1{font-size:18px;font-weight:700;margin:0 0 4px;color:#2A1E20;text-align:center}
  p{font-size:13px;color:#8C7E80;margin:0 0 22px;text-align:center}
  input{width:100%;padding:12px 13px;font-size:15px;color:#2A1E20;background:#fff;
        border:1px solid #ECE3D9;border-radius:10px;outline:none}
  input:focus{border-color:#EB3300;box-shadow:0 0 0 3px rgba(235,51,0,.14)}
  button{width:100%;margin-top:12px;padding:12px;font-size:15px;font-weight:700;cursor:pointer;
         background:#EB3300;color:#fff;border:none;border-radius:10px}
  button:hover{background:#C22A00}
  .err{margin-top:12px;font-size:13px;color:#C8362A;min-height:16px;text-align:center}
</style>
</head>
<body>
  <form class="card" method="POST" action="/login">
    <!-- VMCH client logo (inlined data URI by creatives/inject_logos.py) -->
    <div class="logo"><img class="client" src="data:image/png;base64,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" alt="VMCH — Villa Maria Catholic Homes"></div>
    <div class="agency"><b>100<span class="pc">%</span> Digital</b><span class="sep"></span>VMCH dashboard</div>
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