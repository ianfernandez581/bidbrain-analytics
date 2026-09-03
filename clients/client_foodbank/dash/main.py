"""Foodbank Australia dashboard web app - password gate + static server (Flask).

Thin password gate + static server, the same service pattern as every other client dash in this
repo. It renders a login screen and, once a session is authenticated, serves the dashboard and the
campaign payload at `/data.json`. All presentation logic lives in templates/ + static/; this file
only decides *who* may see it, not *what* it shows.

PORTED GATE - do not re-invent. The auth mechanism is copied from
`clients/client_cloudflare/dash/main.py` (authed() / home() / login() / logout() / gated data.json:
`hmac.compare_digest` against a server-side password, `session["ok"]` in a signed, HttpOnly cookie
with a hard 12h lifetime) and the login-kit behaviours (show/hide, Caps Lock, submit-once) from the
same template as ported into `clients/client_geyervalmont/dash/main.py`. `platform_sso.py` is the
vendored SSO verifier every dashboard carries; it is inert until SSO_SECRET + CLIENT_KEY are set.

CONFIG LIVES HERE AND NOWHERE ELSE. AGENCY / CLIENT are the only place either name is written;
templates read them, the JS reads `window.BRAND`. The next agency client is a config entry, not a
fork.

Local run (one command, from the repo root):
    .\\clients\\client_foodbank\\run.ps1
which is just:
    .\\.venv\\Scripts\\python.exe clients\\client_foodbank\\dash\\main.py
Password: env FOODBANK_DASH_PASSWORD (Cloud Run injects DASH_PASSWORD from Secret Manager). With
neither set, a DEV password is used and printed to the console on start - never to the page.
"""
import hmac
import json
import os
import secrets
import sys
from pathlib import Path

from flask import Flask, Response, abort, redirect, render_template, request, session

HERE = Path(__file__).resolve().parent            # .../client_foodbank/dash
ROOT = HERE.parent                                # .../client_foodbank

# ================================================================================================
# Brand + agency config - THE ONLY PLACE EITHER NAME LIVES
# ================================================================================================
AGENCY = {
    "name": "Think HQ",
    "slug": "thinkhq",
    "logo_dark": "img/thinkhq-logo-cream.png",    # for dark / purple surfaces
    "logo_light": "img/thinkhq-logo-ink.png",     # for white surfaces
    "contact_phrase": "your Think HQ contact",     # used in the login error copy
}
CLIENT = {
    "name": "Foodbank Australia",
    "short": "Foodbank",
    "slug": "foodbank",
    "logo": "img/foodbank-logo.svg",              # cream lockup - sits on purple, never on bare white
    "logo_light": "img/foodbank-logo-purple.png",  # purple lockup - for white surfaces
    "favicon": "img/favicon.png",
    "site": "foodbank.org.au",
}
# 100% Digital does not appear anywhere in this build. The seam is kept behind a flag, not deleted.
SHOW_PLATFORM_CREDIT = False
PLATFORM_CREDIT = "Reporting by 100% Digital"

# "sample" serves data/foodbank_sample.json (the deterministic generator's output) and turns on every
# sample-only affordance (the header chip, the footer tag, the methodology note). Flip to "live" to
# read <DATA_OBJECT> from the private GCS bucket instead - the ONLY edit needed to point at a real
# source; nothing else in the app branches on it.
DATA_MODE = "sample"

GCS_BUCKET = os.environ.get("GCS_BUCKET", f"bidbrain-analytics-{CLIENT['slug']}-dash")
DATA_OBJECT = os.environ.get("DATA_OBJECT", f"{CLIENT['slug']}.json")
# The deploy script copies the sample JSON into dash/ for the Docker build context; locally it is
# read straight from data/. First match wins.
SAMPLE_JSON_CANDIDATES = [HERE / "foodbank_sample.json", ROOT / "data" / "foodbank_sample.json"]

# ================================================================================================
# App + session
# ================================================================================================
app = Flask(__name__, template_folder=str(HERE / "templates"), static_folder=str(HERE / "static"),
            static_url_path="/static")

ON_CLOUD_RUN = bool(os.environ.get("K_SERVICE"))
COOKIE_SECURE = ON_CLOUD_RUN or os.environ.get("COOKIE_SECURE") == "1"
app.secret_key = os.environ.get("SESSION_SECRET") or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    # Secure + SameSite=None on Cloud Run (cross-site iframe on dashboards.bidbrain.ai). Over plain
    # http on a laptop a Secure cookie is never stored and login would loop, so it relaxes to Lax.
    SESSION_COOKIE_SECURE=COOKIE_SECURE,
    SESSION_COOKIE_SAMESITE="None" if COOKIE_SECURE else "Lax",
    PERMANENT_SESSION_LIFETIME=60 * 60 * 12,   # hard 12h cap, same as every other dash
    MAX_CONTENT_LENGTH=64 * 1024,              # the login form is the only POST
)

DEV_PASSWORD = "foodbank-preview-2026"
_env_pw = (os.environ.get("FOODBANK_DASH_PASSWORD") or os.environ.get("DASH_PASSWORD") or "").rstrip("\r\n")
USING_DEV_PASSWORD = not _env_pw
DASH_PASSWORD = _env_pw or DEV_PASSWORD


def _announce():
    """Console only. The password is never rendered into any page."""
    if USING_DEV_PASSWORD:
        print(f"[{CLIENT['slug']}-dash] DATA_MODE={DATA_MODE}  dev password (no FOODBANK_DASH_PASSWORD set): "
              f"{DEV_PASSWORD}", file=sys.stderr, flush=True)
    else:
        src = "FOODBANK_DASH_PASSWORD" if os.environ.get("FOODBANK_DASH_PASSWORD") else "DASH_PASSWORD"
        print(f"[{CLIENT['slug']}-dash] DATA_MODE={DATA_MODE}  password from env {src}", file=sys.stderr, flush=True)


# ================================================================================================
# Template context
# ================================================================================================
def _brand_ctx():
    brand = {
        "agency": AGENCY["name"],
        "agency_slug": AGENCY["slug"],
        "client": CLIENT["name"],
        "client_short": CLIENT["short"],
        "client_slug": CLIENT["slug"],
        "data_mode": DATA_MODE,
        "show_platform_credit": SHOW_PLATFORM_CREDIT,
        "platform_credit": PLATFORM_CREDIT if SHOW_PLATFORM_CREDIT else "",
    }
    return {
        "agency": AGENCY,
        "client": CLIENT,
        "data_mode": DATA_MODE,
        "is_sample": DATA_MODE == "sample",
        "show_platform_credit": SHOW_PLATFORM_CREDIT,
        "platform_credit": PLATFORM_CREDIT,
        "brand_json": json.dumps(brand),
        # RELATIVE asset paths on purpose: behind the platform proxy at /d/<slug>/ a root-relative
        # "/static/..." does not resolve (the estate-wide lesson); "static/..." does, on both.
        "asset": lambda p: "static/" + p,
        "page_title": f"{CLIENT['name']} — campaign performance | {AGENCY['name']}",
    }


# ================================================================================================
# Auth (ported verbatim in mechanism from client_cloudflare/dash/main.py)
# ================================================================================================
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
        return render_template("login.html", error=None, **_brand_ctx())
    # no-store so a redeploy is picked up immediately, never served stale (matches /data.json).
    return Response(render_template("dashboard.html", **_brand_ctx()), mimetype="text/html",
                    headers={"Cache-Control": "no-store"})


@app.post("/login")
def login():
    if hmac.compare_digest(request.form.get("password", ""), DASH_PASSWORD):
        session["ok"] = True
        session.permanent = True
        return redirect("./")
    err = f"That password didn't work. Check with {AGENCY['contact_phrase']}."
    return render_template("login.html", error=err, **_brand_ctx()), 401


@app.get("/logout")
def logout():
    session.clear()
    return redirect("./")


# ================================================================================================
# Data
# ================================================================================================
_sample_cache = {"path": None, "mtime": None, "bytes": None}


def _sample_bytes():
    for p in SAMPLE_JSON_CANDIDATES:
        if p.exists():
            m = p.stat().st_mtime
            if _sample_cache["path"] != p or _sample_cache["mtime"] != m:
                _sample_cache.update(path=p, mtime=m, bytes=p.read_bytes())
            return _sample_cache["bytes"]
    return None


@app.get("/data.json")
def data():
    # The dashboard fetches this. Only an authenticated session gets it; everyone else gets 401.
    if not authed():
        abort(401)
    if DATA_MODE == "live":
        # Lazy import: the local sample run needs neither the library nor GCP credentials.
        try:
            from google.cloud import storage
            blob = storage.Client().bucket(GCS_BUCKET).blob(DATA_OBJECT)
            if not blob.exists():
                return Response(json.dumps({"error": "live data object not found"}), status=503,
                                mimetype="application/json")
            return Response(blob.download_as_bytes(), mimetype="application/json",
                            headers={"Cache-Control": "no-store"})
        except Exception:
            app.logger.exception("live data.json read failed")
            return Response(json.dumps({"error": "live data unavailable"}), status=503,
                            mimetype="application/json")
    body = _sample_bytes()
    if body is None:
        return Response(json.dumps({"error": "sample data missing - run data/generate_sample.py"}),
                        status=503, mimetype="application/json")
    return Response(body, mimetype="application/json", headers={"Cache-Control": "no-store"})


@app.get("/healthz")
def healthz():
    return "ok"


_announce()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"[{CLIENT['slug']}-dash] serving http://127.0.0.1:{port}/", file=sys.stderr, flush=True)
    app.run(host="0.0.0.0", port=port, debug=False)
