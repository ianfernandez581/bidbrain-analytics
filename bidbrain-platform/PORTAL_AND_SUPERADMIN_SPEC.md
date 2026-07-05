# Multi-tenant Portal + Super-Admin Console — build spec

A portable, framework-agnostic spec for the access-control system used by the Bidbrain platform
front-door (`bidbrain-platform/dash/`). It's a **password-gated launcher + reverse proxy** in front of
many separate apps, with a four-role hierarchy, "reveal & rotate every password" god mode, and an
optional "log in once, open everything with no second password" proxy.

Reference implementation: `dash/store.py` (data + auth), `dash/main.py` (routes), `dash/config.py`
(seed), `dash/templates/{login,portal,admin,superadmin}.html`. This doc is what you need to rebuild it
elsewhere — copy the *patterns*, not necessarily the stack.

---

## 1. Architecture at a glance

- **One web service.** A single app (Flask here) serves the login, the three role views, and (optionally)
  proxies the downstream apps.
- **No database.** All state is **one private JSON blob** (a "registry"), read-modify-write on every
  mutation (last-write-wins — fine for a low-traffic, single-admin registry). Back it with anything:
  a private object-store file (our choice), a Redis key, one DB row, even a local file in dev.
- **Config is the seed.** A code file holds the initial agencies/clients/passwords; a one-shot `seed()`
  writes it into the blob. After that the UI edits the *live* blob, which may diverge from the seed
  (re-seed only deliberately, with `--force`).
- **Everything derives from the tenant key.** You store a short `key` per client; names of the
  downstream service / bucket / dataset are all derived from it, so the registry stays tiny.

```
browser ──login(password | Google/MS)──▶ platform
                                          ├─ superadmin → super console (reveal/rotate all, open any)
                                          ├─ admin      → editable agencies→clients tree
                                          ├─ agency     → portal of that agency's clients
                                          └─ client     → straight to its one app
platform ──/d/<client>/──▶ proxies to the upstream <client> app, logging in server-side (no 2nd pw)
```

---

## 2. Roles (strict hierarchy)

| Role | Sees | Can do |
|---|---|---|
| **super-admin** | Super console | Reveal + rotate EVERY password (admin, super, agency, dashboard), open any app, grant/revoke SSO emails |
| **admin** | Agencies→clients→campaigns tree | Edit the tree (CRUD), open any *live* app |
| **agency** | Portal of its own clients | Open its clients' apps |
| **client** | — | Open its one app only |

super-admin ⊇ admin (a super-admin passes every admin guard).

---

## 3. Data model — the entire registry

```jsonc
{
  "admin_password_hash": "pbkdf2_sha256$…", "admin_password_plain": "…",
  "super_admin_password_hash": "…",         "super_admin_password_plain": "…",
  "agencies": [
    { "name": "Agency A", "slug": "agency-a",
      "password_hash": "…", "password_plain": "…",
      "client_keys": ["acme", "globex"], "order": 0 }
  ],
  "clients": {
    "acme": { "key": "acme", "name": "Acme", "slug": "acme",
      "status": "active|coming_soon", "url": "https://acme-app.example/",
      "note": "optional blurb for coming_soon tiles",
      "password_hash": "…",                // the client app's OWN login password
      "campaigns": [ { "name": "Q3", "path": "/q3", "status": "active" } ],
      "order": 3 }
  },
  "users": {                               // SSO email → role (Google/Microsoft sign-in)
    "boss@company.com": { "role": "superadmin", "agency_slug": "", "client_key": "" },
    "pm@company.com":   { "role": "agency", "agency_slug": "agency-a", "client_key": "" }
  }
}
```

Notes:
- `status: "active"` = live, linkable, openable. `"coming_soon"` = shown but greyed / not client-facing.
- `url` = where the client app lives (used by the portal link + the proxy). Leave empty for a client
  with no app yet.
- `order` = display order within a group.
- Every password is stored **twice** — a one-way `*_hash` AND a recoverable `*_plain` (see §4).

---

## 4. Passwords: hash **and** a recoverable plaintext

The trick that lets a super-admin *reveal* a password: store both a verify-only hash and a recoverable
plaintext, side by side, **inside the private blob** (same trust boundary as your secrets).

```python
import hashlib, hmac, secrets

def hash_pw(pw: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 120_000)
    return f"pbkdf2_sha256$120000${salt.hex()}${dk.hex()}"

def verify_pw(pw: str, stored: str) -> bool:
    if not (pw and stored and stored.startswith("pbkdf2_sha256$")): return False
    _algo, iters, salt, h = stored.split("$")
    iters = int(iters)
    if not (1_000 <= iters <= 1_000_000): return False      # clamp: a bad stored count can't burn CPU
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), iters)
    return hmac.compare_digest(dk.hex(), h)                  # constant-time
```

- **Login** checks `verify_pw`.
- **Reveal** shows `*_plain`.
- **Self-heal** (`backfill_plaintext`): for a registry that only has hashes (older, or imported), test a
  set of *candidate* plaintexts (your seed values) against each hash; if one verifies, persist it as
  `*_plain`. Idempotent; runs on each super-console load. Anything rotated away from a seed value stays
  hidden until set explicitly in the UI.

For the downstream **app** passwords, prefer real secret storage (Secret Manager / Vault) over the
registry — the console reads them live from there (§7).

---

## 5. Login → one role-resolution function

Resolve a typed password to a role, **most-privileged first**:

```python
def resolve_password(pw):   # -> ('superadmin',None)|('admin',None)|('agency',a)|('client',c)|(None,None)
    doc = load()
    sh = doc.get("super_admin_password_hash")
    if sh:
        if verify_pw(pw, sh): return "superadmin", None
    elif BOOTSTRAP_SUPER_PW and hmac.compare_digest(pw.encode(), BOOTSTRAP_SUPER_PW.encode()):
        return "superadmin", None                            # bootstrap ONLY until one is set in the UI
    if verify_pw(pw, doc["admin_password_hash"]): return "admin", None
    for a in sorted(doc["agencies"], key=lambda a: a["order"]):
        if verify_pw(pw, a["password_hash"]): return "agency", a
    for key, c in doc["clients"].items():
        if verify_pw(pw, c["password_hash"]): return "client", c
    return None, None
```

**Critical security rule:** the bootstrap super password must default to **empty** and fail **closed** —
if the registry has no super hash *and* the env var is empty, there is NO super login. A shipped default
would fail *open* (anyone reading the repo logs in as god).

`resolve_email(email)` is the twin for SSO — same return shape, keyed on the `users` map (+ a seed +
an optional "any verified email on our workspace domain = admin" fallback).

### Sessions

One function turns `(kind, payload)` into a logged-in session — the *single* place password login and
SSO login converge:

```python
def establish_session(kind, payload):
    session.clear(); session.permanent = True
    session["kind"] = kind
    if kind == "agency":  session["agency_slug"] = payload["slug"]
    if kind == "client":  session["client_key"] = payload["key"]
    # (optionally compute the set of client keys this session may open, for a signed SSO cookie)
```

Cookie: `HttpOnly`, `Secure`, `SameSite=Lax`, a sane lifetime. Guards:

```python
def require_admin():  # admin OR super
    if session.get("kind") not in ("admin", "superadmin"): abort(403)
def require_super():
    if session.get("kind") != "superadmin": abort(403)
```

The `home()` route is just a dispatcher on `session["kind"]` → super console / admin tree / agency
portal / client redirect.

---

## 6. The three role views

All views are **rendered straight from the store**, so they can never disagree.

**Agency portal** — `agency_clients(agency)` returns the agency's clients (resolved from `client_keys`),
each with `status`/`url`/`note`/`campaigns`, **sorted active-first** (live tiles on top, coming-soon at
the bottom). Template: `status=="active"` → clickable tile → `/d/<key>/`; else greyed tile showing
`note`.

**Admin tree** — `get_state()` returns agencies with nested resolved clients + campaigns + an
"unassigned clients" bucket. CRUD APIs (`require_admin`): `upsert_agency`, `upsert_client`,
`set_campaign` — each is load-mutate-save on the blob, preserving password/note/order and re-parenting
`client_keys` membership.

**Super console** — `get_super_state()` returns:
- admin + super passwords in clear (from `*_plain`),
- agencies with their revealable passwords,
- dashboards **grouped by agency** and **tiered** so the have/have-not split is obvious:
  `active+url` → *live* (password + Open), `coming_soon+url` → *preview* (note + "Open preview"),
  `no url` → *nothing to reveal*. (Stable sort keeps this order.)
- the SSO `users` grants.

---

## 7. Super-admin capabilities (the god-mode APIs)

All gated by `require_super()`:

| Endpoint | Effect |
|---|---|
| `POST /super/api/admin-password` | `set_admin_password` → write hash+plain to the blob |
| `POST /super/api/super-password` | `set_super_password` → same (also disables the bootstrap env once set) |
| `POST /super/api/agency-password` | `set_agency_password(slug)` → same, per agency |
| `POST /super/api/dashboard-password` | **true rotation** of a downstream app's real login (see below) |
| `POST /super/api/user` | grant / change / revoke an SSO email's role |

**Reveal** (UI): the plaintext is server-rendered into a `data-pw` attribute on a masked field; a few
lines of JS toggle visibility + copy. The page is `Cache-Control: no-store` and super-only.

**Dashboard-password rotation** is the sharpest bit — it changes the *downstream app's own* password
everywhere, not a registry copy:
1. write a new secret version for `<client>-app-password` in your secret store,
2. update the proxy's in-process cached password,
3. **restart the downstream service** so it re-reads the secret at `:latest`.
If the restart fails, return the exact manual command so the operator can finish it.

**Reading live app passwords:** the console shows each downstream app's *actual* current password by
reading it from the secret store at render time (not from the registry) — so what you reveal is always
what the app is really using.

---

## 8. The reverse proxy — "log in once, open everything" (optional)

Portal/console links point at `/d/<client>/`. The proxy:

```python
def may_open(client):                       # THE real authorization boundary (not the UI)
    kind = session.get("kind")
    if kind == "superadmin": c = get_client(client); return bool(c and c.get("url"))
    if kind == "admin":      return client in active_client_keys()
    if kind == "agency":     a = get_agency(session["agency_slug"]); return a and client in a["client_keys"]
    if kind == "client":     return session.get("client_key") == client
    return False

def proxy(client, subpath):
    if not may_open(client): return redirect("/")
    base = get_client(client)["url"]
    cookies = cached_upstream_cookie(client) or upstream_login(client)   # log into the app w/ its own pw
    resp = forward(base, subpath, cookies)
    body = rewrite_same_origin_paths(resp.body, client)    # keep the app's /api, /data.json under /d/<client>/
    return body
```

Result: after ONE platform login, every app opens under the platform's origin with **no second
password**. `may_open` — not the tiles — is what actually enforces per-role scoping.

(There's also a signed cookie scoped to the parent domain listing the openable keys, for a
subdomain-based SSO variant; the proxy is the simpler mechanism and the one actually used.)

---

## 9. Google / Microsoft sign-in (optional, additive)

Never replaces the password box. The browser posts a **signed ID token (JWT)**; the server **verifies**
it and maps the verified email to a role:
- Google: verify against your public OAuth **client id** as the JWT `aud` (no client secret needed —
  you only verify).
- Microsoft: **single-tenant** — verify against the tenant JWKS with `aud` + issuer + `tid` pinned, so
  only your org's accounts can sign in.
Then `resolve_email(email)` → same `(kind, payload)` → same `establish_session`. Empty client id ⇒
button hidden, endpoint inert.

---

## 10. Security checklist (do not skip)

- [ ] Bootstrap super password defaults **empty** ⇒ fail **closed**. Never a committed default.
- [ ] Passwords stored only in the private blob / secret store; the blob is never public.
- [ ] `verify_pw` uses `hmac.compare_digest` and clamps the iteration count.
- [ ] `may_open` (server-side) is the authorization boundary — the UI is just convenience.
- [ ] Session cookie `HttpOnly` + `Secure`; `no-store` on any page that reveals secrets.
- [ ] A failed blob read must **fail closed** (never write an empty doc over a good registry — that's a
      full wipe). Let the exception propagate and abort the read-modify-write.
- [ ] Rotating an app password also restarts that app (or the old password lingers).

---

## 11. Minimal rebuild recipe

1. **Store class** — `load()` / `save()` over your chosen backend + a `memory` mode seeded from config.
   Methods: `resolve_password`, `resolve_email`, `get_state`, `get_super_state`, `agency_clients`,
   `upsert_agency/client`, `set_campaign`, `set_*_password`, `upsert/delete_user`, `backfill_plaintext`.
2. **Auth** — `hash_pw` / `verify_pw`; `resolve_*` most-privileged-first; one `establish_session`;
   `require_admin` / `require_super`.
3. **Routes** — `GET /` (dispatcher), `POST /login`, `GET /logout`, the `super/api/*` + `admin/api/*`
   mutations, and (optional) `/d/<client>/` proxy + `/auth/{google,microsoft}`.
4. **Four templates** — login, portal, admin tree, super console; all fed by the store.
5. Seed once from config; edit live thereafter.

Steal these ideas specifically: **hash + recoverable-plain** (reveal *and* verify), **one
`(kind,payload)` resolution** shared by password + SSO, **derive-everything-from-the-key**, **the store
is the single source of truth** for every view, and **`may_open` is the only real gate**.
