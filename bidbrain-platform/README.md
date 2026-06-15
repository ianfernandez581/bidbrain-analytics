# bidbrain-platform — the front-door (dashboards.bidbrain.ai)

One password box in front of all the client dashboards. It does **not** hold or show any client
data — it's a thin Flask gate + an editable registry of agencies → clients → campaigns, backed
by Firestore. Same serving pattern as every other dash in this repo (gunicorn, `no-store`,
private, `--no-invoker-iam-check`).

## What a password does (resolved against Firestore by `store.resolve_password`)
| You type… | You get… |
|---|---|
| an **agency** password (e.g. `100d2026`) | a portal of every dashboard in that agency; click any to open it with **no further password** |
| a single **dashboard** password | straight to that one dashboard |
| the **admin** password | the editable admin tree (add/edit/remove agencies, clients, campaigns) |

### Agencies (seeded from `dash/config.py`)
- **100% Digital** (`100d2026`): City Perfume, VMCH, The Little Marionette, ResetData,
  Bell Shakespeare *(coming soon)*, Geocon *(coming soon)*.
- **Transmission** (`Transmission2026`): Schneider Electric, Cloudflare, PropTrack, MongoDB.
- **Unassigned** (not in any agency, reachable only by their own dashboard password): **STT**
  (on hold), **HireRight**. Add them to an agency anytime via the admin UI.

Admin password defaults to `bidbrain-admin-2026` — override with the `ADMIN_PW` env before
seeding, or rotate later in Firestore.

## How "no second password" works — the SSO cookie
The dashboards were already built for this: each sets `SESSION_COOKIE_SAMESITE=None; Secure`
"for the iframe on dashboards.bidbrain.ai", but its session cookie is **host-only** (won't span
subdomains). So the platform issues a **separate** signed cookie:

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
  deploy_platform.ps1            one-shot standup (APIs, Firestore, SA+IAM, secrets, build, deploy, seed)
  dash/
    main.py                      Flask: login → tier resolution → SSO cookie → portal / admin / CRUD
    store.py                     Firestore layer + password hashing + login resolution (memory backend for dev)
    config.py                    SEED source of truth: agencies, clients, campaigns, passwords
    platform_sso.py              shared SSO token (issuer here; VENDORED into every dashboard as the verifier)
    seed_firestore.py            push config.py → Firestore (idempotent; --force to overwrite)
    templates/                   login.html · portal.html · admin.html (dark theme, Bidbrain logo)
    logo.svg  Dockerfile  requirements.txt  deploy_dash_platform.ps1
  Creatives/                     the design screenshot + source logo.svg
```

## Deploy & operate
```powershell
# First-time standup (idempotent):
.\bidbrain-platform\deploy_platform.ps1
#   then, in Cloudflare, point dashboards.bidbrain.ai at the platform-dash service
#   (CNAME + Host Header Override, exactly like the client dashboards — see root README §6.4).

# Activate SSO on the dashboards (grants each SA the shared key + injects SSO_SECRET/CLIENT_KEY):
.\scripts\enable_platform_sso.ps1
#   prereq: each dashboard rebuilt with the new image (clients\client_<c>\dash\deploy_dash_<c>.ps1)
#   and served on <c>.bidbrain.ai.

# Redeploy the platform after a code/template edit (data edits use the admin UI, not a redeploy):
.\bidbrain-platform\dash\deploy_dash_platform.ps1

# Re-seed Firestore from config.py (rare; refuses to clobber live edits unless --force):
.\.venv\Scripts\python.exe bidbrain-platform\dash\seed_firestore.py
```

## Local dev (no GCP)
```powershell
$env:PLATFORM_BACKEND="memory"; $env:DEV="1"; $env:SESSION_SECRET="x"; $env:SSO_SECRET="y"; $env:COOKIE_DOMAIN=""
.\.venv\Scripts\python.exe bidbrain-platform\dash\main.py   # needs Flask in the env; serves on :8080
```
`PLATFORM_BACKEND=memory` loads `config.py` into an in-process store (edits lost on restart).

## Coordinates
Project `bidbrain-analytics` · region `australia-southeast1` · service `platform-dash` ·
web SA `platform-dash-web@` (`roles/datastore.user` + `secretAccessor`) · secrets
`platform-dash-session-key`, `platform-sso-key` · Firestore collections `platform_agencies`,
`platform_clients`, `platform_meta`. No bucket, no export job, no scheduler.

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

## Cost
One scale-to-zero Cloud Run service ≈ **$0/mo** (free tier), or **~$13–16/mo** if you set
`min-instances=1` to avoid the ~1–3s cold start. Firestore free tier (1 GiB, 50k reads/day)
covers the registry at ~$0. Cloudflare DNS/proxy is free. No load balancer.
