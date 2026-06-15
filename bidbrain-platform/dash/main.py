"""Bidbrain Campaign Dashboards — the front-door platform (dashboards.bidbrain.ai).

ONE password box, three outcomes (resolved against Firestore by `store.resolve_password`):
  - an AGENCY password  -> a portal of every dashboard in that agency; clicking any opens it
                           with NO further password (a `bb_sso` cookie pre-authorises them).
  - a single DASHBOARD password -> straight to that one dashboard.
  - the ADMIN password  -> the editable admin tree (the screenshot): agencies -> clients ->
                           campaigns, add/edit/remove, persisted to Firestore.

How "no second password" works: a REVERSE PROXY. Because the dashboards live on raw `*.run.app`
(a public-suffix domain where a shared SSO cookie can't apply), the platform serves each dashboard
UNDER ITS OWN ORIGIN at `/d/<client>/`. It logs into the upstream `<c>-dash` service once
(server-side, with that dashboard's own password from Secret Manager) and proxies the dashboard
through — so once you're past the platform's single login, the dashboards just open. Per-agency
scoping is enforced on `/d/<client>/` (a 100% Digital session can't open Transmission's clients).
The registry (agencies/clients/campaigns + hashed passwords) is a private JSON in GCS.

(The `bb_sso` cookie / vendored `platform_sso.py` are also in place — they take over automatically
if a real domain is ever wired and the dashboards move to `<c>.<domain>/`; inert on run.app.)

Serving pattern mirrors every other dash in this repo: thin Flask gate, gunicorn, no-store,
private by default, deployed with --no-invoker-iam-check so this app's gate is the only door.
"""
import os
import base64
from pathlib import Path

import requests
from flask import (
    Flask, request, redirect, session, render_template, abort, jsonify, make_response, Response
)

import platform_sso
from store import Store

app = Flask(__name__)
app.secret_key = os.environ["SESSION_SECRET"]            # platform's own session (separate from SSO)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=os.environ.get("DEV") != "1",
    SESSION_COOKIE_SAMESITE="Lax",                       # platform is top-level, not iframed
    PERMANENT_SESSION_LIFETIME=platform_sso.DEFAULT_MAX_AGE,
)

# --- config injected by Cloud Run ---------------------------------------------------------
SSO_SECRET = os.environ["SSO_SECRET"]                    # shared with every dashboard
COOKIE_DOMAIN = os.environ.get("COOKIE_DOMAIN", ".bidbrain.ai")  # parent domain so the cookie spans subdomains
_SECURE = os.environ.get("DEV") != "1"

# Logo + Flask templates are baked into the container next to this file.
LOGO_SVG = ""
try:
    LOGO_SVG = (Path(__file__).resolve().parent / "logo.svg").read_text(encoding="utf-8")
except FileNotFoundError:
    LOGO_SVG = "<span style='font-weight:800'>Bidbrain.ai</span>"

store = Store()


# Per-agency logos shown on that agency's portal (loaded once, inlined). `light=True` means the
# mark needs a light backing on the dark theme (e.g. a green-on-white raster); white/transparent
# marks render plain. Drop an `agency_<slug>.svg`/`.jpg`/`.png` next to this file to add more.
def _load_agency_logos():
    here = Path(__file__).resolve().parent
    logos = {}
    for f in here.glob("agency_*"):
        slug = f.stem[len("agency_"):]
        try:
            if f.suffix == ".svg":
                logos[slug] = {"html": f.read_text(encoding="utf-8"), "light": False}
            elif f.suffix in (".jpg", ".jpeg", ".png"):
                mime = "png" if f.suffix == ".png" else "jpeg"
                b64 = base64.b64encode(f.read_bytes()).decode()
                logos[slug] = {"html": f'<img src="data:image/{mime};base64,{b64}" alt="">', "light": True}
        except OSError:
            pass
    return logos


AGENCY_LOGOS = _load_agency_logos()


# --- SSO cookie helpers -------------------------------------------------------------------
def _set_sso(resp, allowed):
    """Attach the signed cross-subdomain allow-list cookie to a response."""
    token = platform_sso.encode(SSO_SECRET, allowed)
    resp.set_cookie(
        platform_sso.COOKIE_NAME, token,
        max_age=platform_sso.DEFAULT_MAX_AGE,
        domain=COOKIE_DOMAIN or None, path="/",
        secure=_SECURE, httponly=True, samesite="None" if _SECURE else "Lax",
    )
    return resp


def _clear_sso(resp):
    resp.set_cookie(platform_sso.COOKIE_NAME, "", expires=0,
                    domain=COOKIE_DOMAIN or None, path="/")
    return resp


def _require_admin():
    if session.get("kind") != "admin":
        abort(403)


# --- views --------------------------------------------------------------------------------
@app.get("/")
def home():
    kind = session.get("kind")
    if kind == "admin":
        st = store.get_state()
        return render_template("admin.html", logo_svg=LOGO_SVG, **st)
    if kind == "agency":
        agency = store.get_agency(session.get("agency_slug", ""))
        if not agency:
            session.clear()
            return render_template("login.html", logo_svg=LOGO_SVG, error=None, next_url="")
        clients = store.agency_clients(agency)
        return render_template("portal.html", logo_svg=LOGO_SVG,
                               agency={"name": agency["name"], "slug": agency["slug"]},
                               agency_logo=AGENCY_LOGOS.get(agency["slug"]),
                               clients=clients)
    if kind == "client":
        key = session.get("client_key")
        if key:
            return redirect(f"/d/{key}/")
        session.clear()
    return render_template("login.html", logo_svg=LOGO_SVG, error=None, next_url="")


@app.post("/login")
def login():
    pw = request.form.get("password", "")
    kind, payload = store.resolve_password(pw)
    if kind is None:
        return render_template("login.html", logo_svg=LOGO_SVG,
                               error="Incorrect password.", next_url=""), 401

    session.permanent = True
    if kind == "admin":
        session["kind"] = "admin"
        allowed = store.active_client_keys()  # every LIVE dashboard (incl. unassigned, excl. coming_soon)
        resp = make_response(redirect("/"))
        return _set_sso(resp, allowed)

    if kind == "agency":
        session["kind"] = "agency"
        session["agency_slug"] = payload["slug"]
        allowed = list(payload.get("client_keys", []))
        resp = make_response(redirect("/"))
        return _set_sso(resp, allowed)

    # single dashboard -> straight into the proxied dashboard
    session["kind"] = "client"
    session["client_key"] = payload["key"]
    resp = make_response(redirect(f"/d/{payload['key']}/"))
    return _set_sso(resp, [payload["key"]])


@app.get("/logout")
def logout():
    session.clear()
    return _clear_sso(make_response(redirect("/")))


@app.get("/healthz")
def healthz():
    return "ok"


# --- admin CRUD API (admin session only) --------------------------------------------------
@app.post("/admin/api/agency")
def api_agency():
    _require_admin()
    d = request.get_json(silent=True) or {}
    action = d.get("action")
    try:
        if action == "delete":
            slug = (d.get("orig_slug") or "").strip()
            if not slug:
                return jsonify(ok=False, error="Missing agency slug."), 400
            store.delete_agency(slug)
        else:
            name = (d.get("name") or "").strip()
            slug = (d.get("slug") or "").strip()
            if not name or not slug:
                return jsonify(ok=False, error="Name and slug are required."), 400
            store.upsert_agency(d.get("orig_slug", ""), name, slug, d.get("password", ""))
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 400


@app.post("/admin/api/client")
def api_client():
    _require_admin()
    d = request.get_json(silent=True) or {}
    action = d.get("action")
    try:
        if action == "delete":
            key = (d.get("key") or "").strip()
            if not key:
                return jsonify(ok=False, error="Missing client key."), 400
            store.remove_client(key)
        else:
            key = (d.get("key") or "").strip()
            name = (d.get("name") or "").strip()
            if not key or not name:
                return jsonify(ok=False, error="Client key and name are required."), 400
            url = (d.get("url") or "").strip()
            if url and not (url.startswith("http://") or url.startswith("https://")):
                return jsonify(ok=False, error="URL must start with http:// or https://."), 400
            store.upsert_client(
                d.get("agency_slug", ""), key, name,
                (d.get("slug") or key).strip(),
                d.get("status", "active"), url,
            )
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 400


@app.post("/admin/api/campaign")
def api_campaign():
    _require_admin()
    d = request.get_json(silent=True) or {}
    action = d.get("action")
    try:
        if action == "delete":
            ck = (d.get("client_key") or "").strip()
            idx = d.get("index")
            if not ck or idx in (None, ""):
                return jsonify(ok=False, error="Missing client_key or index."), 400
            store.delete_campaign(ck, idx)
        else:
            name = (d.get("name") or "").strip()
            path = (d.get("path") or "").strip()
            if not name or not path:
                return jsonify(ok=False, error="Campaign name and path are required."), 400
            if path and not path.startswith("/"):
                path = "/" + path
            store.set_campaign(d["client_key"], d.get("index"), name, path,
                               d.get("status", "active"))
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 400


# --- reverse proxy: serve each dashboard under the platform's own origin ------------------
# Makes "no second password" work on raw run.app. The platform logs into the upstream <c>-dash
# ONCE per instance (with the dashboard's own password from Secret Manager) and proxies it under
# /d/<client>/. Visitors only ever see the platform origin + the platform's single login.
PROJECT = os.environ.get("GCP_PROJECT", "bidbrain-analytics")
_UPSTREAM_PW = {}       # client_key -> plaintext dashboard password (cached per instance)
_UPSTREAM_COOKIES = {}  # client_key -> upstream session cookies (cached per instance)


def _upstream_base(client):
    c = store.get_client(client)
    url = (c or {}).get("url", "")
    return url.rstrip("/") if url else None


def _upstream_pw(client):
    if client not in _UPSTREAM_PW:
        from google.cloud import secretmanager
        sm = secretmanager.SecretManagerServiceClient()
        name = f"projects/{PROJECT}/secrets/{client}-dash-password/versions/latest"
        _UPSTREAM_PW[client] = sm.access_secret_version(name=name).payload.data.decode().strip()
    return _UPSTREAM_PW[client]


def _upstream_login(client):
    base = _upstream_base(client)
    r = requests.post(f"{base}/login", data={"password": _upstream_pw(client)},
                      allow_redirects=False, timeout=30)
    _UPSTREAM_COOKIES[client] = r.cookies
    return r.cookies


def _may_open(client):
    kind = session.get("kind")
    if kind == "admin":
        return client in store.active_client_keys()
    if kind == "agency":
        a = store.get_agency(session.get("agency_slug", ""))
        return bool(a) and client in a.get("client_keys", [])
    if kind == "client":
        return session.get("client_key") == client
    return False


def _forward(client, subpath, cookies):
    url = f"{_upstream_base(client)}/{subpath}"
    if request.method == "POST":
        return requests.post(url, data=request.get_data(), params=request.args, cookies=cookies,
                             headers={"Content-Type": request.headers.get("Content-Type", "")},
                             allow_redirects=False, timeout=30)
    return requests.get(url, params=request.args, cookies=cookies, allow_redirects=False, timeout=30)


def _unauth(resp, subpath):
    if subpath == "data.json":
        return resp.status_code == 401
    # the dashboard page always references /data.json; the upstream login page never does
    if "text/html" in resp.headers.get("Content-Type", ""):
        return b"/data.json" not in resp.content
    return False


@app.route("/d/<client>/", defaults={"subpath": ""}, methods=["GET", "POST"])
@app.route("/d/<client>/<path:subpath>", methods=["GET", "POST"])
def proxy(client, subpath):
    if not _may_open(client):
        return redirect("/")
    if not _upstream_base(client):
        abort(404)
    cookies = _UPSTREAM_COOKIES.get(client) or _upstream_login(client)
    resp = _forward(client, subpath, cookies)
    if _unauth(resp, subpath):                      # cached upstream session expired -> re-login once
        resp = _forward(client, subpath, _upstream_login(client))
    ctype = resp.headers.get("Content-Type", "application/octet-stream")
    body = resp.content
    if "text/html" in ctype:                        # keep the dashboard's data fetch inside the proxy
        body = body.replace(b"/data.json", f"/d/{client}/data.json".encode())
    out = Response(body, status=resp.status_code, content_type=ctype)
    out.headers["Cache-Control"] = "no-store"
    loc = resp.headers.get("Location")
    if loc and loc.startswith("/"):
        out.headers["Location"] = f"/d/{client}{loc}"
    return out


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
