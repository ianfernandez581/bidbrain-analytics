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

**Enter agency view (admin & super).** From the admin tree (each agency's **Enter portal →**) or the
god-mode console (**Enter agency portal →**), an admin/super can step into any agency's own portal —
exactly what that agency sees, correctly scoped. It flips the session to that `agency` kind (reusing
every agency-scoped path: the portal, `/api/status`, the proxy's `_may_open`) and stashes the role to
restore; the portal then shows a **▸ Viewing agency portal** pill and a **← Back to admin / super
console** link (`GET /enter-agency/<slug>` · `GET /exit-agency`). Log out clears everything.

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

> **Gotcha — two passwords open one dashboard, and they are NOT auto-synced.** A *single-dashboard*
> front-door login (`resolve_password` → `('client', c)`) verifies the typed password against the
> **registry** `clients[<key>].password_hash`. That is a DIFFERENT credential from the dashboard's own
> `<c>-dash-password` Secret Manager value (used for direct `…run.app` access **and** the server-side
> proxy login). They start equal because both are seeded from `config.CLIENT_PASSWORDS[<key>]`, but
> rotating one does NOT update the other: the super-admin "rotate dashboard password" (and a manual
> `gcloud secrets versions add <c>-dash-password`) only touches the **secret**. To change the password
> a user types at `dashboards.bidbrain.ai` to open just that dashboard, update the **registry** hash
> too — load `gs://bidbrain-analytics-platform-dash/platform.json`, set
> `clients[<key>].password_hash` = `store.hash_pw(new)` (and `password_plain` = new), save. Keep both
> in sync if you want one password everywhere.

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

## Sign in with Google (native, alongside the password)
Users can log in **either** with a password **or** with their Google account — Google sign-in is an
**additive** second path that never replaces the password box. It's off until you switch it on
(`GOOGLE_OAUTH_CLIENT_ID` unset ⇒ the button is hidden and `/auth/google` is disabled; passwords keep
working exactly as before).

**How it works.** The login page renders Google's official **GIS button**; the browser posts the
signed **ID token (JWT)** to the platform's `/auth/google` via a *same-origin fetch*. The server
verifies the JWT against the OAuth **client id** (the JWT `aud`) with `google-auth`
(`id_token.verify_oauth2_token`), checks `email_verified`, then maps the **verified email** to a role
with `store.resolve_email` — the email twin of `resolve_password`, with the same four outcomes. The
OAuth **client id is public** (it ships in the login HTML) and there is **no client secret** — the
signed JWT is the proof, so there's nothing secret to leak and no redirect flow to configure. The
same-origin fetch sidesteps third-party-cookie / `SameSite` issues entirely.

**Who gets in.** Only an email that's been granted access resolves; every other Google account is
rejected *after* a valid sign-in (a clear "not authorised — ask an admin" message). The allow-list is
the registry's **`users`** map:

| email mapped to… | opens… |
|---|---|
| `superadmin` | the god-mode console |
| `admin` | the agencies → clients → campaigns tree |
| `agency` (+ `agency_slug`) | that agency's portal |
| `client` (+ `client_key`) | just that one dashboard |

`ian@100.digital` is the **baked-in super admin** (config `USERS`) — it always resolves even on a
pre-existing registry (config fallback in `resolve_email`, the same fail-safe idea as the
`SUPER_ADMIN_PW` env), so you can never lock it out; deleting it in the UI can't actually revoke it
(it's shown as "baked-in — permanent"). Manage everyone else in the super-admin console's **"Google
sign-in access"** panel: add an email, pick a role, and (for agency/client) pick the target. Emails
match case-insensitively.

**Domain auto-admin (`@100.digital`).** So the whole team doesn't have to be added one email at a
time, any verified Google email whose **domain** is in `config.ADMIN_EMAIL_DOMAINS` (default
`100.digital`; override with the comma-separated `ADMIN_EMAIL_DOMAINS` env, empty ⇒ feature off) is
granted the **admin** role automatically:
- `resolve_email` has a **domain fallback** — when an email has *no* explicit `users`/seed record and
  its domain matches, it resolves to `admin`. This makes the very *first* sign-in succeed (no 403).
- `/auth/google` then calls **`store.record_domain_admin(email)`**, which writes that email into the
  registry `users` map as `admin` — so it shows up in the "Google sign-in access" panel like any other
  account and can be **re-scoped or removed** there. (Removing it just re-grants admin on the next
  sign-in while the domain rule is on; to truly restrict someone, re-scope them to `client`/`agency` —
  an explicit record always beats the domain fallback.)
- **Precedence:** explicit registry row → config `USERS` seed → domain fallback. So the seed super
  admin `ian@100.digital` stays **superadmin** (never downgraded), and `record_domain_admin` no-ops for
  any email that already has a record. Match is **exact domain** — `x@evil.100.digital` (a subdomain)
  does *not* match `100.digital`. Trust rests on `100.digital` being a **Google Workspace domain the
  company controls** (Google verifies domain ownership and we require `email_verified`), so a stranger
  can't mint a `@100.digital` Google account.

**Switch it on (one-time).** The OAuth client can't be created with gcloud — make it in the Console,
then inject its id:
```powershell
# 1. Console -> APIs & Services -> Credentials -> Create credentials -> OAuth client ID ->
#    "Web application"; Authorized JavaScript origin: https://dashboards.bidbrain.ai
#    (+ the raw https://platform-dash-...run.app). NO redirect URI (GIS button + same-origin fetch).
# 2. Inject the client id (re-runnable; password login unaffected):
.\scripts\enable_google_login.ps1 -ClientId '1234...apps.googleusercontent.com'
```

## How "no second password" works TODAY — a reverse proxy
The platform is live on the custom domain **https://dashboards.bidbrain.ai**. The individual
dashboards have **no** `<c>.bidbrain.ai` subdomains, and a shared SSO cookie can't span raw `run.app`
hosts (public-suffix). So the platform **reverse-proxies** each dashboard under its own origin:

- Portal/admin tiles link to **`/d/<client>/`** (not the dashboard's run.app URL).
- `proxy()` in `main.py` checks your platform session may open that client, then forwards to the
  upstream `https://<c>-dash-…run.app/`, logging in **once per instance** with that dashboard's own
  password (read from Secret Manager `<c>-dash-password`; the platform SA has `secretAccessor`). The
  upstream session cookie is cached and reused; the dashboard's `/data.json` is rewritten to
  `/d/<client>/data.json` so it stays inside the proxy.
- `proxy()` also **injects a floating "Log out" pill** (`_LOGOUT_BUTTON`, fully inline-styled, max
  z-index) into the bottom of every proxied dashboard page — the dashboards have no logout of their
  own. It links to the platform's `/logout` (root-relative, so `dashboards.bidbrain.ai/logout`, NOT
  through `/d/`), which clears the session + `bb_sso` cookie exactly like the portal/admin pages.
- Result: after the single platform login, dashboards just open — **no second password** — all on the
  one `dashboards.bidbrain.ai` origin. Per-agency scoping is enforced on `/d/<client>/`.

The `bb_sso` cookie machinery below is also deployed but **inert**. The platform itself now has a custom
domain, but the cookie path would only take over if each *dashboard* got its own `<c>.bidbrain.ai`
subdomain too (then you'd switch the registry URLs to `https://<c>.<domain>/`) — today they don't, so it
stays dormant.

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

## Feedback (every dashboard: text / voice / screenshot, with AI interpretation)
A small **Feedback** pill is injected into the bottom-right of every proxied dashboard — the exact
same `</body>`-injection mechanism as the logout pill, so all 10 dashboards get it from ONE
`platform-dash` deploy (no per-client work). The panel lets a viewer **type a note**, **record a
voice message** (`MediaRecorder`), or both, plus an OPTIONAL **reporter name** and **preferred
deadline** (date); on open it also grabs a **page screenshot** (lazy-loaded `html2canvas`, viewport
only, the widget hidden from the shot). It POSTs to the platform's `/feedback` (`reporter`/`deadline`
ride along as plain form fields; both stored on the record, blank when not given).

- **Auth:** `/feedback` uses the same `_may_open(client)` check as the proxy — you can only file
  feedback against a dashboard you're allowed to open. The client key is baked into the widget per
  dashboard at injection time.
- **Storage (no email yet):** `feedback.save()` writes to the platform's OWN private bucket —
  `gs://bidbrain-analytics-platform-dash/feedback/<client>/<ts>-<id>.json` plus the recording
  (`.webm`/`.m4a`) and the screenshot (`.jpg`) when present. Same private-bucket trust boundary as
  the registry; `storage.objectAdmin` on `platform-dash-web@` already covers it — no new storage IAM.
- **AI transcription + interpretation:** `feedback_ai.py` makes ONE Gemini call
  (`gemini-2.5-flash`) that transcribes the voice note (Gemini accepts the browser's `audio/webm`
  inline — no Cloud Speech-to-Text, no transcoding) AND interprets the feedback into a short summary
  + concrete action items. It runs **lazily on the `/feedback/admin` view** (bounded to 15 calls per
  load) and is **cached back into the record** (`transcript`/`ai_summary`/`ai_actions`/`ai_done`), so
  it costs one call per note. Needs `GEMINI_API_KEY` (secret `gemini-api-key`, granted to
  `platform-dash-web@` + mounted on the service); if unset, notes still store and just show no summary.
  **Gotcha (fixed 2026-06-24):** `gemini-2.5-flash` spends *thinking* tokens out of `maxOutputTokens`,
  so the old `maxOutputTokens:1024` got eaten on a LONG transcript and the JSON came back truncated
  (`Unterminated string` → `json.loads` raised → the note never set `ai_done` → stuck on "Processing
  on next load…" forever, retrying each view). `interpret()` now sends `thinkingConfig.thinkingBudget:0`
  + `maxOutputTokens:4096` and `_parse_json()` tolerates a truncated reply (salvages whatever fields
  finished). Short notes were unaffected — that's why only the one long resetdata note was stuck.
- **Track it:** sign in as **admin/super** → **`/feedback/admin`** (also a "Feedback →" link in the
  super-admin/admin top bars). Every note newest-first in three columns — **Notes** (the editable
  typed text + voice transcript + audio player) · **AI summary** (interpretation + action items) ·
  **Screenshot** (thumbnail → full image). Audio/images stream via `/feedback/file/<client>/<f>`,
  which honors HTTP **Range** (`Accept-Ranges`/`206`) so the player can seek. MediaRecorder `.webm`
  voice notes carry **no duration in their header** (the player would show `0:00 / 0:00`), so the
  admin page forces a seek-to-end on `loadedmetadata` to make the browser compute the real length,
  then rewinds (`audio.vn` handler); `<audio preload="metadata">` loads it up front (fixed 2026-06-24).
- **Triage:** each note has a **status** dropdown (`feedback.STATUSES` = Not yet started → Ongoing →
  On Hold → Completed; new notes default to the first) → `POST /feedback/status`, and a **Delete**
  button → `POST /feedback/delete` (removes the JSON + audio + screenshot, which share the rid prefix).
  A **filter bar** at the top of the tracker filters the cards by status (All + each status, each with
  a live count chip) — client-side only, re-counts as you change a status or delete a note.
- **Hand-edit (admin/super):** an edit bar on each note makes the human fields fully editable — the
  **reporter** name, **two dates** (`date_reported`, defaulting to the submission day, and the
  **target deadline**), and the **Notes** text — saved via `POST /feedback/edit` (merges only the
  posted keys; dates are the browser's `YYYY-MM-DD` strings or `""`). The AI summary/actions and
  transcript stay read-only (they're derived; `ai_done` keeps Gemini from re-running on an edit).
- **Caps:** voice 2 min; the service rejects bodies over `MAX_AUDIO_BYTES + MAX_IMAGE_BYTES` (~24 MB);
  an oversized screenshot is dropped rather than failing the note.
- **Wiring:** `feedback.py` (storage) + `feedback_ai.py` (Gemini) + `_FEEDBACK_WIDGET` / `_enrich()` /
  the `/feedback*` routes in `dash/main.py`. Email/Slack alerting to ian@100.digital is a deliberate
  TODO — drop it into `feedback_submit()` after `feedback.save()`.
- **Caveats:** delivered via the PROXY, so it appears on dashboards opened through the platform
  (the normal path), not on a raw `<c>-dash` run.app URL. The screenshot is an html2canvas DOM
  re-render (Chart.js canvases capture fine; the odd web-font/cross-origin image may render
  imperfectly) and `html2canvas` is lazy-loaded from a CDN — if blocked, the note just sends without
  an image. Both are vendorable later if needed.

## Open slides (AI decks — the "Open slides" button)

The agency portal's **Overview** tab shows a per-client **"Open slides"** button (rendered only for
clients in `SLIDES_CLIENTS` in `dash/main.py` = {mongodb, cloudflare, schneider, proptrack, geocon}). It
replaces the old in-dashboard toolbar button — the deck is now reachable **only from the agency login**.

**Flow (all same-origin, no new server machinery on the platform):**
1. Click → the portal opens the client's dashboard in a **hidden iframe** at `/d/<c>/?bbslides=1` (the
   reverse proxy already logs into the upstream and serves it same-origin).
2. The dashboard, seeing `?bbslides=1`, runs headless: `buildDeckPayload()` assembles the **full-flight**
   `summary` (mirroring the dashboard's own aggregators, so the deck can never disagree with the screen),
   POSTs it to `/report`, then calls the shared **`bb_deck.js`** builder.
3. `/report` (on the client's `<c>-dash`, `report.py`) runs a two-stage **Claude Opus 4.8** call —
   web-research analyst notes → strict slide JSON — with a **Gemini fallback**, cached in the client's
   bucket under `reports/` keyed by view identity + data version (so re-downloads cost no model calls).
4. `bb_deck.js` builds a 4-slide `.pptx` (Cover · What happened · Why · Recommended actions) in the
   **MongoDB brand deck's design language** (serif headlines, "ALL CAPS" mono accent pills, organic
   corner blobs, logo top-right, dark cover + light content), **recoloured per client** from a `BB_THEME`
   const in each `dashboard.html`. It returns the `.pptx` as a **Blob**; the iframe `postMessage`s it to
   the portal.
5. The portal shows a **chooser modal** (`#slidesModal` in `portal.html`) with two actions:
   - **Open in Google Slides** — a **browser-side** Google OAuth *token* flow (`google.accounts.oauth2`
     from the GIS library, reusing the platform's existing `GOOGLE_OAUTH_CLIENT_ID`) requests the
     `drive.file` scope, uploads the `.pptx` Blob straight to the signed-in user's **own** Google Drive as
     a **native Google Slides** doc (Drive multipart upload with `mimeType:
     application/vnd.google-apps.presentation` → Drive converts it), and opens the resulting presentation
     in a **new tab**. No server secrets, no service account, nothing link-shared — the deck lives in the
     user's Drive. Requires the **Drive API** enabled (it is) and the **`drive.file` scope** allowed on
     that OAuth client's consent screen (an *Internal* consent screen needs no verification). The button
     is only rendered when `GOOGLE_OAUTH_CLIENT_ID` is set (else the modal is Download-only).
   - **Download .pptx** — downloads the Blob directly (the original behavior).

**Vendored, config-driven.** `bb_deck.js` (one canonical copy in `clients/client_mongodb/dash/`) and the
generic `report.py` are copied into each participating dash; `report.py`'s per-client `CONFIG` block
(client / currency / business model / guardrails / category tokens) is the only thing that differs.
**Provisioning:** each client needs `dash/enable_report_<c>.ps1` run once (binds `secretAccessor` on the
shared `anthropic-api-key`/`gemini-api-key`, `objectAdmin` on its data bucket, mounts the keys, bumps
`--timeout` to 900) then a normal `deploy_dash_<c>.ps1`. To add a client: give its dash a `report.py`
(CONFIG), `buildDeckPayload()` + `BB_THEME` + the `?bbslides=1` bootstrap, the `/report` + `/bb_deck.js`
routes, copy `bb_deck.js`, and add its key to `SLIDES_CLIENTS`.

## Layout
```
bidbrain-platform/
  deploy_platform.ps1            one-shot standup (APIs, bucket, SA+IAM, secrets, build, deploy, seed)
  dash/
    main.py                      Flask: login (password + Google /auth/google) → tier resolution → SSO cookie → portal / admin / CRUD
    store.py                     GCS-JSON registry layer + password hashing + login resolution (password & Google email; memory backend for dev)
    config.py                    SEED source of truth: agencies, clients, campaigns, passwords, Google client id + users
    platform_sso.py              shared SSO token (issuer here; VENDORED into every dashboard as the verifier)
    feedback.py                  feedback capture: save()/list_recent()/update_record()/load_blob() over the platform's GCS bucket
    feedback_ai.py               one Gemini call: transcribe the voice note + interpret feedback into summary + action items
    seed_registry.py             push config.py → the registry JSON in GCS (idempotent; --force to overwrite)
    templates/                   login.html · portal.html · admin.html · superadmin.html (dark theme, Bidbrain logo)
    logo.svg  Dockerfile  requirements.txt  deploy_dash_platform.ps1
  Creatives/                     the design screenshot + source logo.svg
scripts/enable_super_admin.ps1   one-time: bootstrap super-admin secret + god-mode IAM (see "Super admin")
scripts/enable_google_login.ps1  one-time: inject the public OAuth client id for Google sign-in (see "Sign in with Google")
```

## Deploy & operate
```powershell
# First-time standup (idempotent). DONE — platform is LIVE at:
#   https://dashboards.bidbrain.ai  (custom domain on the platform-dash service; also on its raw
#   https://platform-dash-p32gk2wuia-ts.a.run.app URL). Tiles open each dashboard at /d/<client>/.
.\bidbrain-platform\deploy_platform.ps1

# Activate SSO on the dashboards (DONE — injects SSO_SECRET/CLIENT_KEY into all 10). Stays INERT:
# the proxy delivers no-second-password today, and the cookie only takes over if each dashboard
# also gets its own <c>.bidbrain.ai subdomain (see "To turn on cookie SSO" below):
.\scripts\enable_platform_sso.ps1

# To turn on cookie-based SSO later (only needed if you give each dashboard its own subdomain):
#   1. Host the bidbrain.ai zone wherever DNS lives (Cloudflare DNS today, or Cloud DNS).
#   2. `gcloud beta run domain-mappings create --service=<c>-dash --domain=<c>.bidbrain.ai --region=australia-southeast1`
#      for each dashboard (Google auto-issues managed TLS). australia-southeast1 IS supported.
#   3. Add the returned records; update the registry URLs to https://<c>.bidbrain.ai/.

# Redeploy the platform after a code/template edit (data edits use the admin UI, not a redeploy):
.\bidbrain-platform\dash\deploy_dash_platform.ps1

# Re-seed the registry from config.py (rare; refuses to clobber live edits unless --force):
$env:GCS_BUCKET="bidbrain-analytics-platform-dash"; .\.venv\Scripts\python.exe bidbrain-platform\dash\seed_registry.py

# Enable the super-admin god-mode console (one-time, AFTER deploying the new image — see "Super admin"):
.\scripts\enable_super_admin.ps1 -SuperPw 'a-strong-password'

# Enable native "Sign in with Google" (one-time; create the OAuth client in the Console first — see
# "Sign in with Google"). Re-runnable; password login is unaffected:
.\scripts\enable_google_login.ps1 -ClientId '1234...apps.googleusercontent.com'
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
`platform-dash-session-key`, `platform-sso-key`, `platform-super-admin-password` · env
`GOOGLE_OAUTH_CLIENT_ID` (public OAuth client id for native Google sign-in; no secret) · registry
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
