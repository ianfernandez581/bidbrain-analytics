import os
import hmac
from flask import (
    Flask, request, redirect, session, Response, render_template_string, abort
)
from google.cloud import storage

app = Flask(__name__)
app.secret_key = os.environ["SESSION_SECRET"]
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=60 * 60 * 12,  # stay logged in 12h
)

# --- config (injected by Cloud Run) ------------------------------------------
DASH_PASSWORD = os.environ["DASH_PASSWORD"].rstrip("\r\n")   # from Secret Manager
GCS_BUCKET = os.environ["GCS_BUCKET"]                        # private data bucket
DATA_OBJECT = os.environ.get("DATA_OBJECT", "mongodb.json")  # object inside it

_storage = storage.Client()

# Dashboard HTML is baked into the container at build time.
try:
    with open("dashboard.html", "r", encoding="utf-8") as _f:
        DASHBOARD_HTML = _f.read()
except FileNotFoundError:
    DASHBOARD_HTML = None

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
    return session.get("ok") is True


@app.get("/")
def home():
    if not authed():
        return render_template_string(LOGIN_HTML, error=None)
    if DASHBOARD_HTML is None:
        return Response("dashboard.html is missing from the deploy.", status=500)
    return Response(DASHBOARD_HTML, mimetype="text/html")


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
