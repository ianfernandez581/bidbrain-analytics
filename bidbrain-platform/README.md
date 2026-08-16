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

**Portal tabs (2026-08-04):** Overview · Data Accuracy · **The Grid** · **The Brain**. The Brain is a
styled work-in-progress placeholder (future pacing/industry-trend optimization recommendations).

### The Grid tab — spend pacing (rebuilt 2026-08-05)
Pane header (gradient "Spend Pacing" wordmark + agency/Active chips) → the **executive pacing line**
(`#bbgrid-exec`) → a **client accordion**: one collapsed row per client, expanding to one **bullet bar
per campaign flight**.

**Executive pacing line** = ONE 12px bar pooling **all** campaigns across every client
(budget-weighted, identical maths to a client row), with a status badge and a one-item legend. It is
**deliberately figure-free** — no dollars, no percentages, no ratio (a 4-cell KPI scorecard was built
first and replaced on request, 2026-08-05); the badge states the read in words. The harness asserts no
`$`, `%` or `×` can appear inside it, so don't "helpfully" add one back.

> **The expected-pace reference is deliberately NOT rendered on this bar (2026-08-05).** Both the pale
> "expected" underlay and the "where spend should be today" marker are omitted, leaving only the
> spend-to-date fill. Reason: the central Live Campaigns sheet behind `ROWS` is not current, so the
> apparent underspend is largely **reporting lag, not real under-delivery** — most of those lines are
> believed to be on pace. Marking a stale expectation would tell the client we are behind when we are
> not. The CSS (`.exectrack .e` / `.m`, `.execlegend i.mk`) is still in place and the script carries the
> exact three spans to paste back; the **accordion below intentionally keeps its per-campaign markers**,
> and the harness asserts both facts (marker absent above, present below) so neither drifts.
> **Known gap while this stands:** the campaign rows still show markers *and* amber BEHIND badges driven
> by the same stale expectations, so the detail view can still read "behind" even though the headline no
> longer does. Fixing that properly means refreshing the sheet, not hiding more UI.

**Caveat on pooling:** it makes the headline read ON PACE (≈0.72×) while Schneider — 75% of the book at
$624k — is BEHIND, because the finished STT/MongoDB/PropTrack flights sit near 100% spent and lift the
blend. Reviewed and accepted (2026-08-05): the per-client accordion sits directly underneath, so the
detail is one click away and nothing is hidden. **Note the badge is still computed from `t.pe`** — the
same expected figures the marker was pulled for — so if the sheet lag ever pushes the pooled ratio below
0.65 the headline will flip to BEHIND on data we do not trust.
Track = the full campaign budget; the pale underlay + the bright 2px marker (`#a8b8d8`) sit at **% of
the flight elapsed**; the colored fill is **% of budget spent** (capped at 100%). Fill short of the
marker = behind, past it = over. Client rows roll up spend÷budget with elapsed **weighted by each
line's budget**. Campaign rows carry a channel tag, both flight dates, `$spent of $budget` and a hover
tooltip (`Spent X% | Expected Y%`); the channel is a TAG, not a grouping level (the old
client→platform→campaign drill-down was replaced).

**Bar widths are applied by JS, not inline** — every fill ships as `data-w="<pct>"` with CSS
`width:0`, and `reveal()` sets the real width on the next frame so bars grow into place (client bars
on load; a client's campaign bars the first time it expands, since they sit inside a `max-height:0`
panel). The expected-marker fades in via `.campaign-list.revealed`. Both are `transition:none` under
`prefers-reduced-motion`. **Consequence: a `data-w` attribute with no matching JS = an empty bar**, so
if you add a bar, give it `data-w` and make sure it is inside a scope `reveal()` is called on.

**Pacing thresholds are deliberately lenient** so a normal delivery wobble doesn't read as an alarm:
`% elapsed <= 5%` → **EARLY** (grey — a ratio off a near-zero denominator is meaningless, so it is
NOT colored green), else ratio = `% spent ÷ % elapsed` → `>1.25` **OVER PACE** (red), `<0.65`
**BEHIND** (amber), otherwise **ON PACE** (green). The pane carries its own scoped palette
(`#pane-grid{--p-*}`) so the pacing colors don't disturb the shared `:root` portal theme.

**Data = a FROZEN SNAPSHOT hardcoded in `portal.html`**, keyed by agency slug (only `transmission`
has data; other agencies see a "being connected" note). Base source is the committed
**`Data/pacing_data.xlsx`** ("Pacing Data" tab) — a manual export of the Transmission section of the
Live Campaigns Google Sheet, pre-filtered to **Active campaigns with spend > $0** (lines still at $0
are listed on the xlsx's Notes tab and excluded). To refresh: re-export the xlsx and re-transcribe the
`ROWS` object (grouped by client: `[campaign, channel, start, end, budget, spent, pctSpent,
pctElapsed]` = cols B,C,D,E,F,G,H,I). The data date is recorded **only in the `ROWS` comment** — an
on-screen "Snapshot · <date>" chip was built and then removed on request (2026-08-05), so nothing in
the UI reveals how old the numbers are. **Never recompute `% elapsed` from today's date** (the
pre-rebuild code did): spend cannot be refreshed the same way, so a live-moving marker against frozen
spend drags every line toward BEHIND on its own — which, with no date shown, would now be invisible.
Statuses are recomputed in JS from `pctSpent`/`pctElapsed` rather than read from the sheet's col K —
verified to reproduce every one of the xlsx's own `Pacing Status` values, so the thresholds live in
exactly one place. Client-row logos reuse `/logo/<key>` (none uploaded yet, so they self-hide). Wiring
this to live grid-core/Pulse pacing is the intended follow-up.

> **The 3 `Ecoconsult` lines are a MANUAL OVERRIDE (2026-08-05) and the xlsx does NOT agree with them.**
> The sheet had all three at `$10,500 / $2,247.52` — one figure copied across all three rows. Correct
> values (from Charles): AWR `$10,500 / $2,623.97`, 21 Jul→19 Sep, ON PACE · CNS `$9,000 / $167.43`,
> 3 Aug→30 Nov, EARLY · CVS `$4,500 / $42.83`, 4 Aug→30 Nov, EARLY. Budgets, flight dates AND spend all
> differ from the sheet, so **re-exporting the xlsx will silently reintroduce the stale numbers** — fix
> the source sheet, or re-apply the override block (it is comment-marked in `ROWS`). These three are
> also dated **2026-08-05** while the other 28 rows are the **2026-08-04** export; the stamp shows the
> newer date, so 28 rows are at most one day generously dated (immaterial to elapsed %).

**Remaining source-data caveat** (faithful to the sheet, not a render bug): two `Industrial Edge W3
Prefab` LinkedIn lines share one campaign name and differ only by budget ($7,000 / $7,500), so they
render as near-identical adjacent rows. Campaign names display with the brief-number prefix stripped
(`2463_SE_ANZ …` → `SE ANZ …`) and `_` → space, per the repo-wide "campaign names are not stable
keys" rule.

### Agencies (seeded from `dash/config.py`)
- **100% Digital** (`100d2026`): City Perfume, VMCH, The Little Marionette, ResetData,
  Bell Shakespeare *(coming soon)*, Geocon *(coming soon)*.
- **Transmission** (`transmission2026`): Schneider Electric, Cloudflare, PropTrack, MongoDB, STT,
  Pipeline Status *(the meta `status-dash`, surfaced here so Transmission can watch data health;
  proxied like any client — the platform SA has `secretAccessor` on `status-dash-password`)*.
- **Extrablack** (`extrablack` — no committed password, see below): Geocon, ResetData
  *(both DUAL-VISIBILITY — the same client records also sit in 100% Digital)*, Geyer Valmont
  *(coming soon)*. Branded login at **`/extrablack`**; portal tabs Overview + Data Accuracy only;
  no sync button. See [Extrablack](#extrablack-agency-portal) below.
- **Unassigned** (not in any agency, reachable only by their own dashboard password): **HireRight**.
  Add clients to an agency anytime via the admin UI.

## Extrablack agency portal

Extrablack is the first **EXTERNAL tenant** — an outside company, not part of 100% Digital.

### `external: true` — the agency type

ONE key on the agency record flips **every** optional setting to its safe value. Internal agencies
carry no `external` key and resolve to today's behaviour, byte for byte. **Adding the next external
tenant is this one flag, not a checklist**, and a NEW setting added later is safe for external
tenants by default (add it to `store.EXTERNAL_SAFE_DEFAULTS` with its safe value).

| resolved setting | external | what it does (internal default in brackets) |
|---|---|---|
| `show_sync` | off | no "Sync all dashboards now" — an outside agency must not trigger another agency's export jobs. The read-only "Last synced" stamp still renders from `status.json`'s `generated_at`. [on] |
| `show_grid_brain` | off | Overview + Data Accuracy tabs only — and the frozen pacing snapshot (other clients' budgets/spend) is kept out of the page SOURCE, not just the UI. [on] |
| `internal_notes` | off | the staff-only Internal Notes + Assistant widget is never injected. [on] |
| `show_slides` | off | no AI deck generator (paid runs; writes narrative in our voice). `/d/<c>/report` is 403 too. [on] |
| `edit_definitions` | off | cannot stage or deploy accuracy-check definitions. [on] |
| `show_check_internals` | off | `/api/status` is rebuilt from an ALLOW-LIST: no check SQL, no internal note text, no internal table names. [on] |
| `allow_feedback` | off | no feedback widget, and `/feedback` returns 403. [on] |
| `show_spend_multiplier` | off | the client-billed markup factor is never injected — see "Spend figures" below. [on] |
| `scrub_payload` | on | proxied JSON payloads are scrubbed of named individuals (`owner`, `email`, …). [off] |

A genuine exception can still be granted one setting at a time:
`{"external": True, "allow_feedback": True}`.

`google_allowlist: []` is the INERT v1 Google seam: a verified Google email on this list signs in
straight into this portal via the MAIN login page's Google button (`store.resolve_email`;
precedence: explicit `users` record → agency allow-list → `@100.digital` domain auto-admin).

### Deny-by-default routing

`_external_deny_by_default` (a `before_request` hook in `main.py`) denies **every** route to an
external session except an explicit allow-list — `_EXTERNAL_ALLOWED_ENDPOINTS`, keyed on Flask
**endpoint names**, so **a route added in future is closed until someone deliberately opens it**.
Permitted: the branded login, the portal, `/api/status` (already client-scoped), their own clients'
logos, the proxied dashboards for their own clients, logout, and the public health/icon routes.
Every denial is logged (`WARNING external-deny agency=… endpoint=… path=…`).

### Spend figures shown to an external tenant — BILLED ONLY

An external session sees **the same figures the client sees**: the payload is grossed by the markup
factor **server-side** (`_gross_external_payload`) and no factor is injected, so the dashboard's own
shim is a no-op and both sessions render identical numbers. Raw media cost is never sent. Every
derived metric (CPM/CPC/CPL/cost-per-LPV/pacing) follows automatically because the dashboards
compute them in the browser from these fields.

`_EXTERNAL_SPEND_SPEC` mirrors each dashboard's own shim; a few fields the shims leave raw
(`geocon.breakdowns[].spend`, `resetdata.ga_audience`) are grossed here too, because a raw figure
sitting beside a grossed one for the same money gives the ratio by division.

**Fail closed, and it is strict.** A channel with **no factor defined** is SUPPRESSED (`null`),
never shown raw — as is an unmapped platform, and a blended total whose parts were suppressed.
So **a channel that genuinely carries no markup must be set to `1` explicitly**; that is a
deliberate human statement, distinct from "nobody has decided yet". (`clean_multipliers` now stores
an explicit `1`; it previously discarded it as a no-op.) Practical consequence: a client with no
multipliers configured shows an external tenant **no spend figures at all** until they are set.

### Whole tabs excluded for an external tenant

`_EXTERNAL_EXCLUDED_BLOCKS` / `_EXTERNAL_EXCLUDED_TABS` remove a tab's **payload and its tab
button**. **Both are EMPTY today** — nothing is excluded. ResetData's "Signups & CRM" used to be
removed here; that was reversed 2026-08-09 because the tab reports CAMPAIGN OUTCOME (signups, source
quality, lead volumes, balances, paying customers), which an agency sharing the client needs. It
carries `crm.lifecycle_owner[].owner` / `lead_queue[].owner` — **17 named ResetData staff**, shipped
deliberately via `_SCRUB_EXEMPT_BLOCKS`; drop `"crm"` from that map to scrub the names (the tab still
renders, the two by-owner sections just lose their split).

**Before excluding anything, find what else reads it.** Excluding `crm` also blanked the *Overview*
"Paying customers" card and the hero's paying line, which rendered **`0` instead of 143** — a zero is
a factual claim, and it was being made on data we had chosen not to send.

### Withheld ≠ zero (both dashboards)

Suppression sets a field to `null`. The dashboards now keep `null` intact to the formatter, which
renders the existing `-` placeholder: `nAdd`/`nMul`/`sumMoney`/`heldNum` + a `div` that guards a null
numerator (`null/5` is **0** in JS — that one coercion was turning every withheld figure into a
confident `A$0`). Charts plot `null` as a gap, and a chart whose data is entirely withheld is removed
with a one-line note rather than drawn empty. Scope is **money only**: a null *count*
(`conversions`/`users`/`leads`) already means "none reported" and is left alone.

### Local runs cannot mutate production

A local run (`DEV=1`) uses REAL credentials and buckets, so `_prod_mutation_blocked` refuses
state-changing calls (`/sync-all`, staging/deploying definitions, password rotation, logo upload,
feedback save) with a loud 503. Reads still hit production — treat anything you see locally as
production truth. Override deliberately with `ALLOW_PROD_MUTATIONS=1`.

**Dual visibility.** `geocon` + `resetdata` are ONE client record each, referenced from both
agencies' `client_keys`. Everything per-client (passwords, spend multipliers, campaigns, logos,
status.json accuracy rows) is shared automatically. Two caveats: (1) the **admin UI's client
"Edit" form single-homes** — saving geocon/resetdata with an agency selected strips the other
membership (`store.upsert_client`'s detach loop); re-run `enable_extrablack.py` to restore.
(2) The super-admin console groups each dashboard under its FIRST agency by registry order, so
both show under 100% Digital there; the admin headline client count dedupes (one record = one).

**Branded login.** `GET/POST /extrablack` (`templates/extrablack_login.html`, black/amber
Extrablack brand per the approved mock — self-contained, no external requests, and deliberately
separate from `templates/login.html`, which is untouched). The POST verifies against ONLY the
extrablack agency's registry hash — a Transmission/admin password typed there is rejected, and an
unset password fails closed. A correct password establishes the exact same agency session as the
main login, so `/api/status` scoping and the `/d/<client>/` proxy behave identically. The main
login page still works for Extrablack too (`resolve_password` checks every agency).

**Login hardening.** `/extrablack` throttles failed passwords (5 per IP per 15 min → a 15-minute
lockout, every attempt logged) and is `noindex` via both a meta tag and an `X-Robots-Tag` header.
The pre-login page deliberately does NOT name the client accounts — it is a public URL. The
throttle is per-process and in-memory, so with several Cloud Run instances the effective limit is
(instances × 5); edge rate-limiting (Cloudflare WAF) remains the real control.

**Data Accuracy.** Geocon (6 Meta checks) + ResetData (13 checks) rows come from the existing
`status_dashboard` BQ_CLIENTS specs — nothing new. Geyer Valmont has no check spec yet, so its
client record carries **`show_pending_row: true`**: `/api/status` returns it in a `pending` list
and `_status_merge.html` renders a greyed header-only row with an "awaiting connection" chip.
The flag is opt-in per client precisely so the OTHER spec-less clients (Bell Shakespeare,
Next Smile) keep their no-row behaviour everywhere.

**Setting the Extrablack password** (never committed; `AGENCY_EXTRABLACK_PW` defaults to empty =
fail closed):
```powershell
$env:CLOUDSDK_CORE_ACCOUNT="ian@100.digital"
$env:GCS_BUCKET="bidbrain-analytics-platform-dash"
$env:AGENCY_EXTRABLACK_PW="<from the password manager>"
.\.venv\Scripts\python.exe bidbrain-platform\dash\enable_extrablack.py --yes   # dry-run without --yes
```
`enable_extrablack.py` is the one-time (idempotent) live-registry standup: it creates/updates the
agency + flags + dual client_keys + the geyervalmont placeholder, never touches 100% Digital, and
only sets the password when the env var is present. Rotate later by re-running with the env set,
or in the super-admin console (agency passwords are registry-owned).

**Enabling Google sign-in for Extrablack later:** add the person's Gmail/Workspace address to the
extrablack agency's `google_allowlist` in the live registry (load `platform.json`, append to the
list, save — or extend `enable_extrablack.py`). They then use the "Sign in with Google" button on
the MAIN login page (`/`); `resolve_email` maps the verified email to the extrablack portal. No
new OAuth setup — it reuses the existing `GOOGLE_OAUTH_CLIENT_ID`.

**Flipping Geyer Valmont live** once its dashboard exists: build/deploy `geyervalmont-dash` the
normal way, then set `status: "active"` + the run.app `url` on the client record (admin UI or a
`set_caltex_tile.py`-style upsert) — the tile becomes openable and the proxy serves it at
`/d/geyervalmont/`. When its export pipeline lands, add a `BQ_CLIENTS` spec in
`status_dashboard/job/main.py` (the geocon entry is the worked example) and remove
`show_pending_row` so the real accuracy row replaces the placeholder.

The **admin agencies page** (`templates/admin.html`) renders these as per-agency **accordion cards**
(collapsed by default; open state kept client-side in `sessionStorage`) in the house style, each
with each agency's **dark logo tile** from `ADMIN_AGENCY_LOGOS` — a black-ground badge loaded from
`admlogo_<slug>.svg/.jpg/.png` in `dash/`, **admin-page only and separate from the portal's
`AGENCY_LOGOS`** so the two surfaces can differ (the route passes it to the template as `agency_logos`;
falls back to initials on a neutral tile) — plus a name/client **search box**. Every action (Enter
portal / Add client / Edit / Delete / + Campaign / Logo / Remove / Sync all) and its endpoint is
unchanged — the redesign (2026-07-02) is presentation only.

**House accent = bright cornflower blue** `--accent:#4C8DFF` / `--accent-strong:#6EA8FF` (+ 12% tint),
with a subtle blue top-glow. It's declared per-file in each template's `:root`, so a re-theme means
editing **`templates/login.html`, `templates/admin.html`, and the `_FEEDBACK_ADMIN_HTML` string in
`main.py`**. `templates/_status_merge.html` is SHARED with the portal and keeps its own semantic
palette (blue = Snowflake, teal = dashboard, green = healthy/match); the admin view only overrides its
active-tab underline to the accent. Each Data Accuracy card also shows a **"Source data through
&lt;date&gt;"** strip — the newest DATE each source actually holds (`status.json`'s
`source_data_through` / `source_dates`, NOT the last-modified timestamp) with a per-source breakdown,
flagged **red at 3+ days behind** today in UTC, and only for sources that were still EXPECTED to
deliver — a source whose flight has ended, or a standby fallback whose primary is current, reports a
neutral **"idle"** instead (per-source modes come from `status.json`'s
`freshness.source_expectations`; `weekdays` sources such as Salesforce CS age in business days, so a
weekend gap is not staleness). The flag is computed in the browser, so a stale date turns red on its
own the next day. `freshFlag()` in `_status_merge.html` is the one place the thresholds live. See
`status_dashboard/README.md` -> "behind vs idle". Semantic status colours (Completed = green, etc.) are
kept separate from the accent.

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

## Login "How Bidbrain works" explainer (2026-07-09)
The login page (`templates/login.html`) leads with an animated **"How Bidbrain works"** panel above the
password/Google/Microsoft controls: messy raw-data tokens stream in from the left (the existing Brief→Results
background), the box lights **Layer 1 · The Engine** (20-yrs expertise · statistical analysis · industry
research) then **Layer 2 · Automated Action** (Dashboards & Reports · Automatic Optimisation & Alerts) in
sequence, then a glowing green result metric (`Conversions ↑`, `ROAS ↑`, `CPA ↓`…) flies out the right.
A **"Hide explanation"** toggle collapses it to the compact login (link flips to **"See how the engine
works"**); the choice is remembered in `localStorage` (`bb_login_explain`) and **defaults to shown**. Pure
front-end / decorative — no server contract changed, auth JS untouched, disabled under `prefers-reduced-motion`.

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

## Sign in with Microsoft (Teams / M365 — the twin of Google)
The exact same additive pattern for the team's Microsoft world. A **"Sign in with Microsoft"** button
sits **beneath** the Google button (a "Sign in with Teams" login is just a Microsoft **work/school
account** — there's no separate Teams identity, so the button carries Microsoft's standard label). Off
until switched on: it needs **both** `MICROSOFT_OAUTH_CLIENT_ID` **and** `MICROSOFT_OAUTH_TENANT`
(single-tenant); either unset ⇒ the button is hidden and `/auth/microsoft` is inert (password + Google
unaffected).

**How it works.** The login page loads **MSAL.js** and, on click, opens a Microsoft **login popup**
that returns a signed **ID token (JWT)**; the browser posts it to `/auth/microsoft` (same-origin fetch).
The server verifies it with **PyJWT** against the tenant's **JWKS** (`.../{tenant}/discovery/v2.0/keys`)
— RS256 signature, `aud` = our client id, `exp`, and the issuer pinned to
`https://login.microsoftonline.com/{tid}/v2.0` (plus `tid` == our tenant when the tenant is given as a
GUID) — then maps the **verified email** (`email`, else the UPN in `preferred_username`) to a role with
the **same `store.resolve_email`**. So password / Google / Microsoft are identical from
`_establish_session` on, and the allow-list (registry `users` map) is **shared** — one grant works for
either provider. Public-client model like Google: **no client secret**, the signed JWT is the proof.

**Single-tenant is the safety.** `MICROSOFT_OAUTH_TENANT` is **our own Entra tenant** (its GUID, or a
verified domain). It pins both the authority the button talks to and the issuer/`tid` the server
accepts, so **only our organisation's accounts** can sign in — which is what makes the `@100.digital`
**domain auto-admin** rule (shared with Google, via `record_domain_admin`) safe over Microsoft: a
foreign tenant can't mint a token our tenant-scoped keys will verify. A work/school UPN is
org-controlled, so it's authoritative — that's why no `email_verified` claim is required (Microsoft ID
tokens don't carry one; Google's do, hence the asymmetry in the two routes).

**Switch it on (one-time).** The app registration can't be created with gcloud — make it in Entra,
then inject the two ids:
```powershell
# 1. entra.microsoft.com -> App registrations -> New registration; "single tenant";
#    Redirect URI platform = "Single-page application (SPA)": https://dashboards.bidbrain.ai
#    (+ the raw https://platform-dash-...run.app). Copy the Application (client) ID + Directory (tenant) ID.
# 2. Inject both (re-runnable; password + Google login unaffected):
.\scripts\enable_microsoft_login.ps1 -ClientId '<application-client-id>' -Tenant '<directory-tenant-id>'
```

## How "no second password" works TODAY — a reverse proxy
The platform is live on the custom domain **https://dashboards.bidbrain.ai**. The individual
dashboards have **no** `<c>.bidbrain.ai` subdomains, and a shared SSO cookie can't span raw `run.app`
hosts (public-suffix). So the platform **reverse-proxies** each dashboard under its own origin:

- Portal/admin tiles link to **`/d/<client>/`** (not the dashboard's run.app URL).
- `proxy()` in `main.py` checks your platform session may open that client, then forwards to the
  upstream `https://<c>-dash-…run.app/`, logging in **once per instance** with that dashboard's own
  password (read from Secret Manager `<c>-dash-password`; the platform SA has `secretAccessor`). The
  upstream session cookie is cached and reused; the dashboard's **absolute same-origin paths are
  rewritten** to `/d/<client>/…` so they stay inside the proxy: `/data.json`, mongodb's `'/report'`,
  and `/creative-img/` (resetdata's cached creative-gallery images). **GOTCHA:** any NEW absolute path a
  dashboard fetches (an `<img src="/…">`, a `fetch('/…')`) MUST be added to this rewrite list in
  `proxy()` — otherwise it resolves to the platform ROOT through the proxy and 404s (works only on the
  raw run.app URL, which hides the bug). This is exactly what broke resetdata's creative previews.
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

### Tools group — The Grid (Central) (internal, staff-only, org-private proxied)
A **Tools** group (config `TOOLS`, separate from `CLIENTS`/`AGENCIES`) surfaces internal apps that are
NOT client dashboards. The single entry is **The Grid (Central)** — the `grid-core` app
(`the-grid.html`: Pulse/Brain/Central/Register/Executive) on its own `central-grid` Cloud Run service —
at **`/d/central/`**, live pacing/margin-at-risk across every client. (The older `pacing`/pacing-grid
tile was **retired 2026-07-20**; Central supersedes it. Its repo `C:\Users\DELL\pacing-site` + the
`pacing-grid` service still exist but are no longer surfaced here.) It renders as a tile on the
**super-admin console only** (`{% if tools %}`; the admin tree intentionally omits it), and `_may_open`
gates it to **superadmin/admin** — never agency/client, since it exposes cross-client margins. Two things
differ from a normal dashboard, both keyed on `client in config.TOOLS` (so the 10 real dashboards proxy
byte-for-byte unchanged): (1) `_upstream_base` falls back to `TOOLS` (registry-free — no `--force`
re-seed needed); (2) `central-grid` is **org-private** (DRS policy forbids `allUsers`), so `_tool_headers`
mints an **IAM ID token** (platform SA has `run.invoker`) and adds it as a Bearer header on the login +
every forward — on top of the normal form-login (secret `central-dash-password`). The tile's **Sync now**
/ **Last synced** drive Central's OWN sync directly through the proxy — `POST /d/central/api/central/sync`
(BQ metric overlay; Central does not auto-sync by default) and `GET /d/central/api/central/sync/status`
(returns `{lastRun:{at}}`) — so there is no platform-side sync endpoint; the proxy gives
`api/central/sync` a 300s timeout (`_forward`) since it scans BigQuery across every client. One-time
standup: create secret `central-dash-password`; grant platform SA `secretAccessor` + `run.invoker` on
`central-grid` and the grid's runtime SA `secretAccessor`; redeploy `central-grid` with
`--update-secrets` for its password.

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

## Feedback Loop tab (Transmission portal, STAFF-ONLY — LIVE on the real sheet since 2026-08-17)
A fifth portal tab after The Brain: a registry of every report deck sent + every piece of client
feedback (submit -> feedback -> final loop).

**Who sees it (`_feedback_loop_flags()` in `main.py`, the ONE place all three flags resolve):**
100% Digital staff ALWAYS do — any admin/super-admin viewing that portal via `/enter-agency`.
The agency's OWN login sees it only while the per-agency **`feedback_loop`** setting is on, and it
is **off by default for every agency type** (`INTERNAL_DEFAULTS["feedback_loop"] = False` in
`store.py` — the one setting that is opt-in even for an internal agency, because Transmission
carries no `external` flag and type-based defaults would otherwise have handed its own login a
registry of what went wrong on whose report).

Staff flip it from the tab itself: a **visibility button** in the pane toolbar reading "Hidden
from the agency" (amber dot) / "Visible to the agency" (green dot), POSTing to
`/admin/api/feedback-loop-visibility` -> `store.set_agency_setting(slug, "feedback_loop", bool)`.
That route guards on `_admin_kind()`, NOT `_require_admin()`, because it is clicked from inside
the agency portal where `session["kind"]` is `"agency"` for the duration of the visit. The button
is a convenience, never the boundary: the server re-checks the admin identity on the POST and
re-decides the gate on the next render. `window.BB_FBL_ADMIN` / `BB_FBL_VISIBLE` (emitted in
`portal.html` immediately before the include, staff sessions only) are what reveal the button —
an agency session gets neither, so its page carries no hint the control exists.

**The gate is the Jinja `{% if %}` around the include, never CSS** — the verbatims are inlined
into the portal HTML, so a merely hidden pane would still sit in view source; skipping the include
also means the sheet is never read for that session. It renders as an INLINE `.bbpane`
(`templates/_feedback_loop_pane.html`, included by `portal.html`), not an iframe, so the portal's
background, cursor glow and hover feel run across it unbroken; `main.py _fill_feedback_loop()`
substitutes the data for the pane's `__FEEDBACK_DATA_JSON__` sentinel at request time.

**Data is READ LIVE from the compilation sheet** ("Report Feedback Tracker", owner
calvin@100.digital) by `dash/feedback_loop_data.py` — its CSV export, no auth (the sheet is
link-shared, so there is no service account or OAuth token to hold), transformed into the pane's
contract on the way through. **Nothing to re-run after someone adds a row**: the read is cached
~60s per instance (`FEEDBACK_SHEET_TTL`), so a new row appears within a minute and `?fbl=fresh`
bypasses the cache. Overridable by env: `FEEDBACK_SHEET_ID` / `FEEDBACK_SHEET_GID` /
`FEEDBACK_SHEET_TTL` / `FEEDBACK_SHEET_TIMEOUT` (defaults are baked in, so a plain deploy works).

Fallback chain, so a Google hiccup can never blank the pane: fresh fetch -> the instance's own
copy even if stale -> last-known-good at `gs://bidbrain-analytics-platform-dash/feedback-loop/
data.json` (written on every successful read; private bucket, the same trust boundary as the
feedback widget's recordings — client verbatims never enter git) -> the vendored
`templates/feedback_loop_sample.json`, which flies the amber SAMPLE DATA pill so a reader can
always tell a degraded pane from a real one. `build()` also REFUSES to publish an empty registry
(the caltex pattern), so a mangled sheet keeps the last good data instead of blanking the tab.
Which source served is in the request log (`feedback-loop: served from ...`).

`feedback_loop_data.py` is the SINGLE source of truth for the sheet -> JSON rules (month parsing,
client canonicalisation, report merging, flagging); `prototypes/transmission-feedback-v0/
sheet_to_json.py` imports `build()` from it and is now only for producing a hand-shareable
SNAPSHOT file (`meta.live: false`, and the page says so) plus the review report of every judgment
call. Required sheet columns: `Client | Campaign | Month | Link to submitted deck | Link to final
deck | Client feedback`. Optional and honoured the moment they exist — no code change, no
redeploy: `Sent on | Sent by | Notes | Sentiment | Type | Source | Author | Feedback date`. Until
a Sentiment/Type column exists every entry is neutral/general (the Inaccuracies and Incidents
metrics therefore read 0); nothing is ever inferred from the verbatim text.

The pane template + sample JSON are VENDORED copies — canonical source is
`prototypes/transmission-feedback-v0/`; after editing `index.html` there re-run its
`make_portal_template.py` and redeploy the platform.

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
  A **filter bar** at the top of the tracker filters the cards by **status, agency (100% Digital /
  Transmission / Unassigned) and client** — each dropdown lists only values present in the notes, with
  a live count chip; client-side only (the three AND-combine), re-counts as you change a status or
  delete a note. Agency membership comes from the registry (`agency_of` client→agency map). The
  tracker was restyled to the house palette (2026-07-02).
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

## Internal Notes + Internal Assistant (staff-only, on every dashboard — 2026-08-05)

Every proxied dashboard carries a **staff-only widget**: an **"Internal Notes" TAB** appended to
the dashboard's own tab rail, plus an **"Assistant"** pill bottom-left (the internal chatbot). It
is injected by `proxy()` exactly like the feedback widget, but **only when
`_internal_allowed(client)`** — session kind `superadmin` / `admin` / the client's **owning
agency** (via `_may_open`). A **client session never receives a byte of it**, and a raw `<c>-dash`
run.app URL never shows it (no proxy → no injection).

**How the tab works:** every dashboard marks up its rail as `.tabs > .tab`, so the script clones
the rail's last `.tab` (native look for free), strips its `id`/`onclick`/`data-*`/`style` wiring,
labels it "Internal Notes" and appends it. Its click handler runs in the **capture phase with
`stopPropagation`** so host dashboards with DELEGATED rail listeners (resetdata/tlm read
`e.target.dataset.tab`) never see the click; opening shows a full-screen overlay (`#bbin-ovl`)
with the notes UI, and clicking any native tab / the backdrop / Esc / the X closes it. The active
class is detected per dashboard (`active`/`on`/`selected`) and moved onto the injected tab while
open. A MutationObserver re-appends the tab on rails that are REBUILT per render
(schneider/schneiderlqai). Fallback when no rail exists: a floating "Internal Notes" pill.

- **Internal Notes** — free-text team notes per dashboard, add/edit/delete straight from the panel.
  Storage = ONE private JSON per client, `gs://bidbrain-analytics-platform-dash/internal_notes/
  <client>.json` (`internal_notes.py`; same trust boundary as the registry/feedback). Routes:
  `GET|POST /internal-notes/<client>` (+ `/edit`, `/delete`), all gated by `_internal_allowed`.
  Note author = the signed-in email (or tier). **Cloudflare's dashboard additionally mounts the
  same notes UI inline** into its Admin-View **"Internal Notes" tab** (renamed 2026-08-05 from
  "Data from Transmission"; the committed Source-ID/pacing tables remain below the notes) — the
  widget looks for a `#bbNotesMount` element and mounts there too; any dashboard can opt in by
  adding that div.
- **Assistant** — `POST /internal-chat/<client>` (`internal_chat.py`) runs ONE Gemini turn
  (`gemini-2.5-flash`, same `GEMINI_API_KEY` as feedback) over: the client's **live `data.json`**
  (fetched via the proxy's own upstream login, 5-min cache `_CHAT_DATA_CACHE`), a committed
  **lineage digest** (`dash/lineage/<c>.txt` — client README + every `sql/*.sql` header, built by
  `build_lineage.py`; re-run it after meaningful README/sql changes), and the current internal
  notes. So it can state any number on the dashboard AND its provenance (raw source → BigQuery
  view → job key → screen). It has **function-calling tools to add/edit/delete the internal
  notes** (executed server-side against `internal_notes.py`; the widget refreshes the notes list
  when `notes_changed` comes back). **Thinking is shown**: `thinkingConfig.includeThoughts` — the
  thought summaries render as a collapsible THINKING block on each reply.
- **Gemini gotchas (both bitten 2026-08-05):** (1) a synthetic `model:"Understood."` primer turn
  before the real question makes flash intermittently return `finishReason=STOP` with **zero
  parts** on large contexts — the DATA/LINEAGE/NOTES context therefore rides in
  `systemInstruction`, and `contents` is purely the real conversation; don't move it back.
  (2) a `functionCall` part carries a `thoughtSignature` that MUST be echoed back **verbatim**
  in the follow-up round — `chat()` appends the original part dicts, not rebuilt ones.
- The spend multiplier is irrelevant here by design: the audience is internal, so the assistant
  reasons over RAW spend (its system prompt says it may discuss billed-vs-raw openly). Keep it
  that way — never inject this widget for client sessions.
- **Voice input:** the Assistant's mic button dictates into the textarea via the browser's free
  built-in Web Speech API (`webkitSpeechRecognition` — Chrome/Edge/Safari; the button hides itself
  where the API is missing, e.g. Firefox). Dictation is reviewable text — Send still submits.

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

## Client-billed spend multiplier (2026-07-08)

The agency bills clients a marked-up "client spent to date" that is higher than the real media
(partner) spend our dashboards pull. This lets a super admin show each client the **billed** figure
without ever feeding the agency's central margin sheet into the pipeline.

- **Where:** super-admin console → a **"Multiplier"** button beside each client's **Open →** → a modal
  with a per-channel factor (Google / Meta / LinkedIn / Reddit / The Trade Desk / DV360 / LINE /
  youdooh). Blank/`1` = no change. It's **per-channel** because the markup varies by channel (Google &
  Meta are often ×1, The Trade Desk ×3–7).
- **Storage:** `client.spend_multipliers` in the registry (`store.get/set_spend_multipliers`,
  sanitised by `clean_multipliers` — drops `1.0`/invalid). Endpoint `POST /super/api/spend-multiplier`
  (`{key, multipliers}`), super-admin only.
- **Delivery:** the proxy injects `<script>window.BB_SPEND_MULT={…}</script>` into `<head>` of every
  proxied dashboard (`_spend_mult_script` in `dash/main.py`). **Changing a value is live — no dashboard
  redeploy.** Empty map ⇒ nothing injected changes anything.
- **Dashboard side:** each `dashboard.html` has a vendored gross-up shim (`bbMultFor` +
  `bbApplySpendMult`, called right after `DATA` is parsed) that grosses RAW row spend by the row's
  channel factor (stashing `_rawSpend`, idempotent). Every cost metric (CPM/CPC/CPL/CPA/cost-per-X) and
  budget pacing derive from summed spend, so they follow. **Counts/CTR stay raw. Revenue/ROAS/MER stay
  on REAL spend** — tlm repoints ROAS `×BBG`, cityperfume (`dash` + `dash_total`) reads a parallel
  `rawspend` sum for attributed revenue/profit + blended MER, mongodb folds the `ttd` factor into its
  existing `MARGIN_TARGET` MULT.
- **Behaviour to know:** the multiplier only flows through the **front-door proxy**, so opening a
  dashboard's own `<c>-dash` URL directly (internal) shows **real** cost; the client (via
  dashboards.bidbrain.ai) sees **billed**. Budget/pacing dollars are grossed too, so pacing % is
  invariant. The grossed figure = live spend × the factor (it won't equal a sheet snapshot exactly —
  the factor is the control).

## Layout
```
bidbrain-platform/
  deploy_platform.ps1            one-shot standup (APIs, bucket, SA+IAM, secrets, build, deploy, seed)
  dash/
    main.py                      Flask: login (password + Google /auth/google + Microsoft /auth/microsoft) → tier resolution → SSO cookie → portal / admin / CRUD
    store.py                     GCS-JSON registry layer + password hashing + login resolution (password & Google/Microsoft email; memory backend for dev)
    config.py                    SEED source of truth: agencies, clients, campaigns, passwords, Google + Microsoft client ids + users
    platform_sso.py              shared SSO token (issuer here; VENDORED into every dashboard as the verifier)
    feedback.py                  feedback capture: save()/list_recent()/update_record()/load_blob() over the platform's GCS bucket
    feedback_ai.py               one Gemini call: transcribe the voice note + interpret feedback into summary + action items
    internal_notes.py            staff-only Internal Notes store (one JSON per client in the platform bucket)
    internal_chat.py             staff-only Assistant: Gemini turn over live data.json + lineage digest, with note tools + visible thinking
    build_lineage.py             builds lineage/<c>.txt digests from clients/*/README.md + sql/ headers (run after doc/sql changes)
    lineage/                     committed per-client lineage digests, shipped in the image (COPY lineage)
    seed_registry.py             push config.py → the registry JSON in GCS (idempotent; --force to overwrite)
    templates/                   login.html · portal.html · admin.html · superadmin.html (dark theme, Bidbrain logo)
    logo.svg  Dockerfile  requirements.txt  deploy_dash_platform.ps1
  Creatives/                     the design screenshot + source logo.svg
scripts/enable_super_admin.ps1   one-time: bootstrap super-admin secret + god-mode IAM (see "Super admin")
scripts/enable_google_login.ps1  one-time: inject the public OAuth client id for Google sign-in (see "Sign in with Google")
scripts/enable_microsoft_login.ps1 one-time: inject the Microsoft app (client) id + tenant id for Microsoft sign-in (see "Sign in with Microsoft")
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

# Enable native "Sign in with Microsoft" (one-time; create the Entra app registration first — see
# "Sign in with Microsoft"). Re-runnable; password + Google login unaffected:
.\scripts\enable_microsoft_login.ps1 -ClientId '<application-client-id>' -Tenant '<directory-tenant-id>'
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
`GOOGLE_OAUTH_CLIENT_ID` (public OAuth client id for native Google sign-in; no secret) ·
`MICROSOFT_OAUTH_CLIENT_ID` + `MICROSOFT_OAUTH_TENANT` (public app + tenant id for single-tenant
Microsoft sign-in; no secret) · registry
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
