# bidbrain-platform — the front-door (dashboards.bidbrain.ai)

One password box in front of all the client dashboards. It does **not** hold or show any client
data — it's a thin Flask gate + an editable registry of agencies → clients → campaigns, stored
as a single **private JSON object in GCS** (`gs://bidbrain-analytics-platform-dash/platform.json`)
— the same private-bucket pattern every dashboard uses, no database. Same serving pattern as every
other dash in this repo (gunicorn, `no-store`, private, `--no-invoker-iam-check`).

## What a password does (resolved against the registry by `store.resolve_password`)
| You type… | You get… |
|---|---|
| an **agency** password (e.g. `100d2026`) | a portal of every dashboard in that agency; click any to open it with **no further password** |
| a single **dashboard** password | straight to that one dashboard |
| the **admin** password | the editable admin tree (add/edit/remove agencies, clients, campaigns) |
| the **super-admin** password | the **god-mode console** — reveal AND rotate every password + open any dashboard. See [Super admin](#super-admin-god-mode-console) below. |

### Agencies (seeded from `dash/config.py`)
- **100% Digital** (`100d2026`): City Perfume, VMCH, The Little Marionette, ResetData,
  Bell Shakespeare *(coming soon)*, Geocon *(coming soon)*.
- **Transmission** (`transmission2026`): Schneider Electric, Cloudflare, PropTrack, MongoDB,
  Pipeline Status *(the meta `status-dash`, surfaced here so Transmission can watch data health;
  proxied like any client — the platform SA has `secretAccessor` on `status-dash-password`)*.
- **Unassigned** (not in any agency, reachable only by their own dashboard password): **STT**
  (on hold), **HireRight**. Add them to an agency anytime via the admin UI.

Admin password defaults to `bidbrain-admin-2026` — override with the `ADMIN_PW` env before
seeding, or rotate later by re-seeding with a new `ADMIN_PW`.

## Super admin (god-mode console)
The **super-admin** password opens `templates/superadmin.html` — a gold-themed console headed
**“WELCOME, SUPER ADMIN”** that does three things no other tier can:

1. **Reveal every password** — each agency password, each dashboard's real login, and the admin
   password, shown masked with a click-to-reveal eye + copy button.
2. **Rotate any password** — inline “Change”. Agency/admin/super passwords are stored in the private
   registry (instant). A **dashboard** password is *true* rotation: it writes a new
   `<c>-dash-password` Secret Manager version **and restarts that `<c>-dash` service** so the new
   password takes effect for the standalone dashboard everywhere (the dashboard is briefly
   unavailable, ~20–40s, while it restarts). The platform's own proxy cache is updated in-process.
3. **Open any dashboard** — same one-click, no-second-password access as admin.
   It also links to the full admin tree at `/admin` (super admin inherits every admin power).

**How revealing is possible.** Passwords were previously stored only as one-way pbkdf2 hashes — a hash
can't be un-hashed. The registry now keeps a recoverable `password_plain` *beside* each hash (it lives
only in the **private** GCS registry — the same trust boundary that already holds every dashboard's
plaintext `<c>-dash-password` secret). A registry seeded before this feature is hash-only;
`Store.backfill_plaintext` self-heals it on first super-admin load by recovering any seed value
(from `config.py`) that still verifies against the stored hash. Anything rotated away from its seed
value stays hidden until the super admin sets it explicitly in the console.

**Login resolution.** `store.resolve_password` checks super admin **first**: against the registry
`super_admin_password_hash` if set, else the bootstrap `SUPER_ADMIN_PW` env (Secret Manager
`platform-super-admin-password`) so the login works the moment the secret is mounted, before any
re-seed. Setting a super password in the console moves it into the registry and the env fallback stops.

**Enabling it (one-time, after deploying the new image):**
```powershell
.\bidbrain-platform\dash\deploy_dash_platform.ps1      # ships the console + the google-cloud-run dep
.\scripts\enable_super_admin.ps1 -SuperPw 'a-strong-password'   # IAM + bootstrap secret + env mount
```
`enable_super_admin.ps1` creates `platform-super-admin-password`, mounts `SUPER_ADMIN_PW`+`REGION` on
the platform service, and grants the platform SA the extra IAM dashboard rotation needs:
`secretmanager.secretVersionAdder` on each `<c>-dash-password`, project `run.developer` (create a new
`<c>-dash` revision), and `iam.serviceAccountUser` on each `<c>-dash` runtime SA (actAs, required to
deploy the revision). **There is no committed default super-admin password** — pass `-SuperPw`, or omit
it and the script generates a strong random one and prints it **once** (save it; the config default is
empty so an unconfigured deploy fails *closed*, never open). Change it any time in the console (that
moves it into the registry and supersedes the secret). If a dashboard rotation's auto-restart ever
fails (e.g. IAM not yet propagated), the console tells you the exact `gcloud run services update …` to
finish it by hand.

## How "no second password" works TODAY — a reverse proxy (no domain needed)
No `<c>.bidbrain.ai` subdomains exist, and a shared SSO cookie can't span raw `run.app` hosts
(public-suffix). So the platform **reverse-proxies** each dashboard under its own origin:

- Portal/admin tiles link to **`/d/<client>/`** (not the dashboard's run.app URL).
- `proxy()` in `main.py` checks your platform session may open that client, then forwards to the
  upstream `https://<c>-dash-…run.app/`, logging in **once per instance** with that dashboard's own
  password (read from Secret Manager `<c>-dash-password`; the platform SA has `secretAccessor`). The
  upstream session cookie is cached and reused; the dashboard's `/data.json` is rewritten to
  `/d/<client>/data.json` so it stays inside the proxy.
- Result: after the single platform login, dashboards just open — **no second password** — on raw
  run.app, no domain required. Per-agency scoping is enforced on `/d/<client>/`.

The `bb_sso` cookie machinery below is also deployed but **inert** — it would only take over if a real
domain is wired later (then you'd switch the registry URLs to `https://<c>.<domain>/`).

## (Future) cookie-based SSO once a domain exists
The dashboards were already built for this: each sets `SESSION_COOKIE_SAMESITE=None; Secure`, but
its session cookie is **host-only** (won't span subdomains). So the platform issues a **separate**
signed cookie:

- On login the platform sets **`bb_sso`** — a timed, signed (`itsdangerous`) token listing the
  client keys you may open — scoped to the parent domain **`.bidbrain.ai`** so it reaches every
  `<c>.bidbrain.ai`.
- Each dashboard's `authed()` was extended (additively, fail-safe) to also accept that cookie
  **iff this client key is in the list** — see the vendored `platform_sso.py` in every
  `clients/client_<c>/dash/`. Per-agency scoping is real: a 100% Digital token never lists
  Transmission's clients. **The dashboard's own password always remains a valid fallback**, so
  this can never lock anyone out, and a dashboard deployed before SSO is wired just ignores it.

Signing keys: `platform-sso-key` (shared, in Secret Manager — the platform signs, every
dashboard verifies) and `platform-dash-session-key` (the platform's own session). **Don't rotate
`platform-sso-key` casually** — it invalidates every live SSO session across all dashboards.

**Two preconditions for SSO to actually fire** (until both hold, dashboards just use their own
password — nothing breaks): each dashboard must (1) run the rebuilt image that contains
`platform_sso.py` + the extended `authed()`, and (2) be served on `<c>.bidbrain.ai` (a raw
`*.run.app` host never receives a `.bidbrain.ai` cookie).

## Layout
```
bidbrain-platform/
  deploy_platform.ps1            one-shot standup (APIs, bucket, SA+IAM, secrets, build, deploy, seed)
  dash/
    main.py                      Flask: login → tier resolution → SSO cookie → portal / admin / CRUD
    store.py                     GCS-JSON registry layer + password hashing + login resolution (memory backend for dev)
    config.py                    SEED source of truth: agencies, clients, campaigns, passwords
    platform_sso.py              shared SSO token (issuer here; VENDORED into every dashboard as the verifier)
    seed_registry.py             push config.py → the registry JSON in GCS (idempotent; --force to overwrite)
    templates/                   login.html · portal.html · admin.html · superadmin.html (dark theme, Bidbrain logo)
    logo.svg  Dockerfile  requirements.txt  deploy_dash_platform.ps1
  Creatives/                     the design screenshot + source logo.svg
scripts/enable_super_admin.ps1   one-time: bootstrap super-admin secret + god-mode IAM (see "Super admin")
```

## Deploy & operate
```powershell
# First-time standup (idempotent). DONE — platform is live at:
#   https://platform-dash-p32gk2wuia-ts.a.run.app  (logs in; tiles link to each dashboard's run.app URL)
.\bidbrain-platform\deploy_platform.ps1

# Activate SSO on the dashboards (DONE — injects SSO_SECRET/CLIENT_KEY into all 10). Stays dormant
# until a custom domain is wired (see "To turn on real SSO" below):
.\scripts\enable_platform_sso.ps1

# To turn on real single-sign-on later — 100% GCP, NO Cloudflare:
#   1. Register a domain (Cloud Domains) and host its zone in Cloud DNS.
#   2. `gcloud beta run domain-mappings create --service=<svc> --domain=<host> --region=australia-southeast1`
#      for platform-dash + each <c>-dash (Google auto-issues managed TLS). australia-southeast1 IS supported.
#   3. Add the returned records in Cloud DNS; update the registry URLs to https://<c>.<domain>/.

# Redeploy the platform after a code/template edit (data edits use the admin UI, not a redeploy):
.\bidbrain-platform\dash\deploy_dash_platform.ps1

# Re-seed the registry from config.py (rare; refuses to clobber live edits unless --force):
$env:GCS_BUCKET="bidbrain-analytics-platform-dash"; .\.venv\Scripts\python.exe bidbrain-platform\dash\seed_registry.py

# Enable the super-admin god-mode console (one-time, AFTER deploying the new image — see "Super admin"):
.\scripts\enable_super_admin.ps1 -SuperPw 'a-strong-password'
```

## Local dev (no GCP)
```powershell
$env:PLATFORM_BACKEND="memory"; $env:DEV="1"; $env:SESSION_SECRET="x"; $env:SSO_SECRET="y"; $env:COOKIE_DOMAIN=""
.\.venv\Scripts\python.exe bidbrain-platform\dash\main.py   # needs Flask in the env; serves on :8080
```
`PLATFORM_BACKEND=memory` loads `config.py` into an in-process store (edits lost on restart).

## Coordinates
Project `bidbrain-analytics` · region `australia-southeast1` · service `platform-dash` ·
web SA `platform-dash-web@` (`roles/storage.objectAdmin` on its bucket + `secretAccessor`; **+ for
super-admin god-mode**: `secretmanager.secretVersionAdder` on each `<c>-dash-password`, project
`run.developer`, and `iam.serviceAccountUser` on each `<c>-dash` runtime SA) · secrets
`platform-dash-session-key`, `platform-sso-key`, `platform-super-admin-password` · registry
`gs://bidbrain-analytics-platform-dash/platform.json` (private). No database, no export job, no scheduler.

## Hardening / known trade-offs
Reviewed adversarially; the items below are deliberate trade-offs for an internal, admin-gated
front door, not open bugs:
- **No in-app login rate-limiting.** `/login` (here and on every client dash) doesn't throttle —
  matching the repo's existing posture. Mitigate at the edge: turn on **Cloudflare rate-limiting /
  WAF** for `dashboards.bidbrain.ai`, and **set a strong `ADMIN_PW`** before seeding (the default
  `bidbrain-admin-2026` is a placeholder). Agency passwords are your chosen values.
- **SSO grant is a stateless 12h signed cookie.** Deleting an agency / detaching a client / rotating
  a password doesn't revoke already-issued `bb_sso` cookies until they expire (≤12h). For an
  immediate offboard, also rotate that dashboard's own `<c>-dash-password` (its password is always
  the real gate; SSO is additive). Rotating `platform-sso-key` revokes *everything* at once.
- **Campaigns are edited by positional index.** Two admins editing the same client's campaigns
  concurrently (or from a stale tab) can mis-edit a row. Single-admin use makes this unlikely; it's
  a recoverable registry edit, not data loss.
- **Super admin stores recoverable plaintext passwords.** To let the god-mode console *reveal*
  passwords (a pbkdf2 hash can't be un-hashed), the registry keeps a `password_plain` beside each
  hash. This is a deliberate choice scoped to the **private** registry — the same trust boundary that
  already stores every dashboard's plaintext `<c>-dash-password` secret — and gated behind the
  super-admin password. The pbkdf2 hash is still what `/login` verifies against; the plaintext is
  reveal-only. There is **no committed default** super-admin password — `SUPER_ADMIN_PW` defaults to
  empty so an unconfigured deploy fails *closed*; `enable_super_admin.ps1` takes `-SuperPw` (or mints
  a random one). Super admin is god-mode by design: it can rotate the **real** standalone dashboard
  secrets and restart those services.

## Cost
One scale-to-zero Cloud Run service ≈ **$0/mo** (free tier), or **~$13–16/mo** if you set
`min-instances=1` to avoid the ~1–3s cold start. The registry is one tiny JSON in GCS (a few KB) ≈
$0. Cloudflare DNS/proxy is free. No database, no load balancer.
