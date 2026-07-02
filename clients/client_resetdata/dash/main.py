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
import re
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
  .logo .agency{height:32px;width:auto;display:block}
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
      <img class="agency" src="data:image/png;base64,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" alt="100% Digital">
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


@app.get("/creative-img/<cid>")
def creative_img(cid):
    # Serve a Meta creative image cached in our bucket (creatives/<id>) by the export job — a
    # permanent copy that survives after Meta's signed CDN URL expires. Same auth as /data.json.
    if not authed():
        abort(401)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", cid or ""):   # only simple ids (no path traversal)
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


@app.get("/healthz")
def healthz():
    return "ok"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
