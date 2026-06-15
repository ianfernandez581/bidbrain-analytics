"""Bidbrain Campaign Dashboards — the front-door platform (dashboards.bidbrain.ai).

ONE password box, three outcomes (resolved against Firestore by `store.resolve_password`):
  - an AGENCY password  -> a portal of every dashboard in that agency; clicking any opens it
                           with NO further password (a `bb_sso` cookie pre-authorises them).
  - a single DASHBOARD password -> straight to that one dashboard.
  - the ADMIN password  -> the editable admin tree (the screenshot): agencies -> clients ->
                           campaigns, add/edit/remove, persisted to Firestore.

How "no second password" works (see platform_sso.py): on login the platform sets a signed
`bb_sso` cookie scoped to `.bidbrain.ai` listing the client keys you may open. Every dashboard
(served on `<c>.bidbrain.ai`) trusts that cookie *in addition to* its own password. Per-agency
scoping is real: the cookie only lists that agency's clients, so 100% Digital can't open
Transmission's dashboards. The platform itself never stores a row of client data — only the
agency/client/campaign registry and (hashed) passwords, in Firestore.

Serving pattern mirrors every other dash in this repo: thin Flask gate, gunicorn, no-store,
private by default, deployed with --no-invoker-iam-check so this app's gate is the only door.
"""
import os
from pathlib import Path

from flask import (
    Flask, request, redirect, session, render_template, abort, jsonify, make_response
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
                               clients=clients)
    if kind == "client":
        url = session.get("client_url")
        if url:
            return redirect(url)
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

    # single dashboard
    session["kind"] = "client"
    session["client_url"] = payload.get("url", "")
    resp = make_response(redirect(payload.get("url") or "/"))
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
