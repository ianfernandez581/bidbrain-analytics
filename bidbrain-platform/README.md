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

**Sophiie AI** (2026-08-18) is the newest 100% Digital client and follows the identical preview
pattern: `client_sophiie/` is a built, deployed-on-demand placeholder dashboard on SAMPLE data, tile
`coming_soon` + `show_pending_row`, added to the live registry with
`bidbrain-platform\dash\set_sophiie_tile.py --yes` (a surgical upsert, not a re-seed). Its flip-to-live
path is the same as Geyer Valmont's below, with one extra step: add `"sophiie-export"` to
`_SYNC_EXPORT_JOBS` in `dash/main.py` so **"Sync all dashboards now"** covers it — but **only once the
job exists**, since the Run Admin API 404s an unknown job and that failure sticks.

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

## The premium layer (`_premium.html` + `_premium_head.html`, 2026-08-26)

One shared look-and-feel layer across **login, agency portal, admin tree and super-admin console**.
It is the estate's own vocabulary (`scripts/motion_kit/`, which every client dashboard carries)
re-pointed at the platform's class names, so hovering, pressing and scrolling feels the same
everywhere. **Presentation only: no route, permission, password or registry field is touched.**

Two includes per page, and nothing else:
- `{% include "_premium_head.html" %}` in `<head>` - marks `<html class="bb-motion">` so the
  reveal CSS can only apply where JS is alive, and **removes that mark again** if the engine never
  reports in (3.5s) or the page throws. Hiding content until an observer fires means a missed
  callback could hide a PASSWORD; losing the animation is always the cheaper failure.
- `{% include "_premium.html" %}` as the LAST thing in `<body>` - it must sit after
  `_status_merge.html`, which injects its own `<style>` at the end of the document and would
  otherwise win on source order.

**Colour comes from ONE token.** `_premium.html` derives every colour from `--bb-accent`, declared
on `html` (a type selector, so a page's own `:root` beats it regardless of order) and defaulting
to that page's `--accent`. Each page sets it explicitly: login/admin/portal `#4C8DFF`,
superadmin `#f3c969` (the console is gold; its `--accent` is a stray blue), and the themed portal
block sets `--bb-accent: {{ theme.accent }}` so an agency skin pulls the whole layer into its own
palette with one line. There is no second place to edit.

What it adds: a slow drifting ambient wash (three transform-only orbs, no `filter:blur`), static
film grain at 3%, glass mastheads that sink a shadow and an accent hairline once scrolled, hover /
press / keyboard-focus on everything clickable, a cursor-tracking spotlight inside cards and tiles,
a sliding tab indicator that takes the **active tab's own computed colour** (so themed and house
palettes both come out right), scroll-reveal with a watchdog, count-up figures, a top scroll rail
on pages that actually scroll, themed scrollbars, and a sheen on primary actions only.

**Geometry uses `translate`/`scale`, never the `transform` shorthand** - the themed portal puts a
`bbTileIn` keyframe on `.tile` and the login transforms its own layer boxes; the shorthand would
replace those outright. The reveal offset and the hover lift compose through **two non-inheriting
`@property` variables inside one `translate`** (`--bb-rev` + `--bb-hov`): written as two rules the
reveal (scoped to `html.bb-motion`) outranks a plain `:hover` and the lift silently never fires,
which is why `portal.html`'s tile hover is expressed as `--bb-hov:-3px` and not as a translate.

**`@media print` un-hides everything and is not optional** - printing uses the styles computed at
that moment and does not re-run the observer, so without it an unscrolled card prints blank.
Somebody will print the password console.

Two things are deliberately NOT here. `templates/extrablack_login.html` keeps its own signed-off
tenant skin (the login kit only). And nothing in this layer may change a surface's SIZE: the
first build added a 6px dot inside `.pill.active`, which widened the chip enough to wrap
"Schneider Secure Power" onto two lines and change every tile height on the themed portal - it is
now a pseudo-element halo that occupies no layout at all. The one accepted exception is the two
super-admin hero badges, 3px wider because a counting figure must be tabular or the badge
re-widths every frame.

### Shell scale (2026-08-26, same pass)
The shells were capped at 1080px (portal) / 1120px (admin, super admin), which on a 1536px
viewport left ~200px of dead margin either side and made every page read oversized **at 100%
browser zoom**. That matters because **Chrome stores zoom per host**: staff who look at
`dashboards.bidbrain.ai` every day have a zoom saved for it (75% here) and have never seen the
page at the size a first-time client or agency actually gets.

Now: portal **1080 -> 1280**, admin + super admin **1120 -> 1320**, the god-mode headline
**clamp(34px,6vw,60px) -> clamp(30px,3.4vw,44px)** (the old clamp pinned at 60px on anything wider
than 1000px), and section heads / card titles down half a step. **Body copy is deliberately
UNCHANGED at 16px / 14px** - "less zoomed" must not become "harder to read", so only the shell and
the display type moved. The portal now lays out four client tiles per row instead of three.

**The login page was NOT rescaled**: it is a centred fixed-width card, not a shell, and its
internals already run down to 10px. Its QA assertion is the declared `max-width` rather than the
rendered box, because the embedded Google sign-in iframe measures itself and moves the card ~10px
run to run.

### Super-admin console filter
The one piece of real functionality in the pass, and the reason the console is usable at 17
dashboards: a search under the hero that filters **only rows carrying `data-bbf`** (agency cards,
dashboard rows, Google accounts, the two access keys), hides a `.dgroup` or a `.sec` once nothing
in it matches, rewrites a group's "9 dashboards" caption to "3 of 9 dashboards" from a stashed
original, and prints "3 of 26" beside the field. `/` focuses it (never while typing, never while a
password modal is open), Escape clears it. Nothing is removed from the DOM, so reveal, copy and
change-password keep working on a hidden row the moment the filter clears.

### Changing it
Edit `templates/_premium.html` (shared) or the per-page `PREMIUM PASS` block at the end of each
template (page-specific, placed after the include so it wins). Redeploy is the normal
`dash/deploy_dash_platform.ps1` - templates only, no job, view or JSON change.

### Fixed alongside it: the client marks never reached the image (2026-08-26)
`dash/Dockerfile` copies `agency_*` and `admlogo_*` by wildcard but never listed `clientlogo_*`,
so `main._load_client_logos()` found nothing in the container, `CLIENT_LOGOS` was empty and every
themed portal tile fell back to its plain text heading - the exact failure the Dockerfile's own
comment already warned about for agency logos, one glob down. The files have been committed since
2026-08-15 and had never shipped. **Adding a per-client mark is now just dropping
`clientlogo_<key>.png|.svg` in `dash/` and redeploying**, same as an agency logo.

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
- **A failed Send is almost always an EXPIRED SESSION, and it used to be unreadable (fixed
  2026-08-26).** `PERMANENT_SESSION_LIFETIME` is a **hard 12h cap**, not a sliding window — Flask
  re-sends the cookie on each request but never re-signs it — and a dashboard already rendered in the
  tab keeps looking healthy, because its own 5-min `/data.json` poll swallows the redirect in a bare
  `catch`. So the failing Feedback button was the ONLY symptom, and the widget's blanket
  *"could not send — please try again"* was advice that can never work for an auth failure. It cost a
  real client report (Transmission, 2026-08-25: three 403s, then the feedback went to Teams instead).
  Now: the route answers **401 with `reason:"auth"`** and an actionable message (403 is kept for the
  genuine policy refusal, an external tenant with `allow_feedback` off) and logs the denial;
  **`GET /feedback/ping`** runs the same two checks in the same order so probe and post can never
  disagree; the widget probes it **on panel open, on tab re-focus and every 10 min**, so a tab that
  died overnight flags ITSELF (amber ring + tooltip on the pill); a 401 shows a sign-in link instead
  of a dead end; any other failure prints the server's own message; and the typed note is kept in
  `localStorage` (`bbfb.draft.<client>`, cleared only on a confirmed 200) so it survives the reload
  that signing in again requires. `cloudflare-dash`'s vendored copy carries the same behaviour —
  **keep the two in step.**
  **Diagnosing the next report:** read the status code before touching the widget —
  `gcloud logging read 'resource.labels.service_name="platform-dash" AND httpRequest.requestUrl:"/feedback"'`.
  The tell for a dead tab is a **302 on `/d/<c>/data.json` on a fixed 5-minute cadence, for days,
  from a browser that never posts `/login`**.
- **Storage (no email yet):** `feedback.save()` writes to the platform's OWN private bucket —
  `gs://bidbrain-analytics-platform-dash/feedback/<client>/<ts>-<id>.json` plus the recording
  (`.webm`/`.m4a`) and the screenshot (`.jpg`) when present. Same private-bucket trust boundary as
  the registry; `storage.objectAdmin` on `platform-dash-web@` already covers it — no new storage IAM.
- **The proxy is no longer the only writer into `feedback/` (2026-08-20).** `cloudflare-dash` carries
  its OWN copy of the pill for people who open that service **directly** on its `…run.app` URL
  (Cloudflare's office network does not resolve `dashboards.bidbrain.ai`, so a direct hit — which
  never passes through this proxy — was the one path with no feedback button). It writes the SAME
  record shape into this bucket, so those notes show up in the tracker and get enriched here with no
  platform change; they are tagged `user_kind` **`client-direct`**. Its SA holds create-only
  (`roles/storage.objectCreator`) on this bucket, so it can add objects but overwrite nothing.
  `bidbrain-platform/dash/feedback.py` stays the source of truth for the record shape — change it and
  `clients/client_cloudflare/dash/feedback_widget.py` has to follow. Details + how to copy it to
  another client: `clients/client_cloudflare/dash/README.md`.
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
  super-admin/admin top bars). **Each note is a ONE-LINE ROW that expands to the full detail
  (2026-09-08)** — the row carries a status-coloured rail + dot, the client chip, the first line of
  the note, an overdue-red target deadline and the timestamp; clicking it reveals the three
  columns — **Notes** (the editable typed text + voice transcript + audio player)
  · **AI summary** (interpretation + action items) · **Screenshot** (thumbnail → full image). It was
  a stack of ~300px-tall cards, which put 3 of 70+ notes on a screen; the collapsed row fits ~15.
  `Expand all` acts on the **VISIBLE** cards only, so it follows the filters instead of opening
  every note on the page. Audio/images stream via `/feedback/file/<client>/<f>`, which honors HTTP
  **Range** (`Accept-Ranges`/`206`) so the player can seek. MediaRecorder `.webm` voice notes carry
  **no duration in their header** (the player would show `0:00 / 0:00`), so the
  admin page forces a seek-to-end on `loadedmetadata` to make the browser compute the real length,
  then rewinds (`audio.vn` handler); `<audio preload="metadata">` loads it up front (fixed 2026-06-24).
- **Triage:** each note has a **status** dropdown (`feedback.STATUSES` = Not yet started → Ongoing →
  On Hold → Completed; new notes default to the first) → `POST /feedback/status`, and a **Delete**
  button → `POST /feedback/delete` (removes the JSON + audio + screenshot, which share the rid prefix).
  A sticky **toolbar** at the top of the tracker filters the cards by **status, agency
  (100% Digital / Transmission / Unassigned) and client**, plus a **free-text search** over the note
  text, transcript, AI summary, reporter, page and client name (one prebuilt lowercase `data-q`
  haystack per card, so it is a substring test and not a DOM walk). Each dropdown lists only values
  present in the notes, with a live count chip; client-side only (all four AND-combine), and it
  re-counts as you change a status or delete one — a `n of N shown` readout is the cheap guard
  against a left-on filter being read as the whole queue. Agency membership comes from
  the registry (`agency_of` client→agency map). The tracker was restyled to the house palette
  (2026-07-02) and rebuilt as a scannable list (2026-09-08).
- **Hand-edit (admin/super):** an edit bar on each note makes the human fields fully editable — the
  **reporter** name, **two dates** (`date_reported`, defaulting to the submission day, and the
  **target deadline**), and the **Notes** text — saved via `POST /feedback/edit` (merges
  only the posted keys; dates are the browser's `YYYY-MM-DD` strings or `""`). The AI summary/actions and
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

### The assistant reads the knowledge base for its client (`kb_bridge.py`, 2026-09-15, behind `KNOWLEDGE_RETRIEVAL=on`)
The one bridge between the two AI surfaces, in one direction: the dashboard assistant reads the
library's WORDS for ITS client; `/kb` still cannot see a dashboard, and the customer assistant does
not come through here. **Two gates, both required**: the session may see this dashboard's staff
widget (`_internal_allowed`) AND may open `/kb` (`_kb_allowed` - every admin + 100% Digital), so an
outside agency sharing a dashboard, or an internal agency Ian has not admitted to `/kb`, gets no
passages. `KNOWLEDGE_RETRIEVAL` defaults off; when off the prompt carries no LIBRARY block at all.
- **Scope** = `kb_index.search(q, client=<key>)`: that client plus agency-wide, never another
  client (`doc_ids_for_client`). Six passages; a dashboard turn already carries `data.json`.
- **The query is shaped**: a short follow-up ("and for Q3?", "why?") is prefixed with the previous
  question, because on its own it retrieves nothing useful.
- **The prompt says what each source is for**: DATA is authoritative for live figures, LIBRARY for
  what was agreed/planned/decided; when they disagree the model says which says what. A **verified
  correction** is labelled in the context so the answer can say it follows a colleague's fix; when
  meaning search was unavailable the context says WORDING ONLY (the `/kb` rule: a gap must never
  read as absence).
- **Citations are real**: `[n]` in the answer maps to a *Library sources* list under the reply -
  title, folder, `verified` badge, the passage on click, and `↗` opening the document in `/kb`
  (`/kb/?doc=<id>`, a deep link `kb.js` now honours after the explorer loads).
- The **client profile** (`kb_memory.profile_block`: facts + confirmed campaign-name patterns) rides
  in the same context. Every dashboard question is logged into `kb_activity` (kind `question`,
  `source=dashboard`) so Observability counts it beside `/kb` questions.
- A library failure degrades to the dashboard-only answer and is logged; it never blocks the turn.

## Client Assistant (`client_chat.py` - BUILT, DARK; 2026-09-15)
The first chatbot a CLIENT would ever see on their own dashboard (`/d/<c>/`, bottom-RIGHT pill,
`#bbcc-*`, no INTERNAL badge). No client has one today and none will until Jerome + Ian decide.
**Three independent layers keep it dark, and all three default off:**

1. **`CLIENT_CHAT_ENABLED`** (env, default off) - the master switch. Off => `_client_chat_allowed`
   is False for every client, so the proxy injects nothing and `POST /client-chat/<c>` is 403.
2. **`client_chat`** per-client registry flag (absent = off; the super-admin console's
   "Customer chat · On/Off" per dashboard row, `POST /super/api/client-chat`, superadmin only).
   `EXTERNAL_SAFE_DEFAULTS["client_chat"] = False`, so an outside agency never receives it.
3. **Retrieval filters on a document field that does not exist yet.** `kb_bridge.retrieve_for_client`
   keeps only documents with `visibility == "client"` and never a meeting; Ian's documents carry no
   `visibility` (the held K7-02 change adds it, default internal), so the assistant retrieves
   NOTHING and would answer from dashboard data alone even with 1 and 2 on.

Gate `_client_chat_allowed` = master AND flag AND `_ext_setting("client_chat")` AND `_may_open` -
a `client` session reaches only its own dashboard; staff can preview. **What the client's model
sees** is `_customer_data_json()` = the SAME transform an external tenant's proxied JSON gets
(excluded blocks dropped, `_gross_external_payload` billed basis per `_EXTERNAL_SPEND_SPEC` - a
money field the spec does not cover, or a client with NO spec, is SUPPRESSED, never raw;
`_scrub_external_payload` for named individuals) + `glossary/<c>.md` (hand-reviewed, client-safe;
rules in `glossary/README.md`; a `.draft.md` is never read) + the client-audience retrieval above.
No tools, no thinking output. `client_chat.build_context` REFUSES a context carrying
`spend_multipliers` / `BB_SPEND_MULT` / `_rawSpend` / "margin" (502, never a leak); the route fails
CLOSED when the billed basis cannot be prepared. `CLIENT_CHAT_MODEL` picks the model (default
`gemini-2.5-flash`; Ian's Kimi-first `kb_chat` is the A/B candidate). Every turn is logged to
`<kb prefix>/client-chat-log/<c>/`. Red-team: `tests/test_red_team.py` (15 prompts; LIVE mode ran
15/15 on 2026-09-14 after two prompt fixes - re-run before any prompt change ships).
**Pilot prerequisite unchanged:** `_EXTERNAL_SPEND_SPEC` covers `geocon` + `resetdata` only.

## "How The Brain works" explainers (The Brain tab, 100% Digital portal, 2026-09-14)
Three interactive walkthroughs of the Bidbrain Premium retrieval system render as cards under the
work-in-progress card in **The Brain** tab: Part 1 *Documents to Vectors*, Part 2 *Inside the
Retriever*, Part 3 *Ask Your Campaigns* (which ends on the buyer-feedback step). Each opens in a new
tab at **`/brain/how-it-works/<slug>`**, served by the platform itself from `dash/explainers/*.html`
(`EXPLAINERS` in `main.py`; the Dockerfile copies the folder).
- **Why self-hosted, not a link:** they were authored as claude.ai artifacts, which are private to one
  account - nobody else on the team could open a link to them.
- **Who sees them:** the cards render only in the `x100-digital` portal (`show_explainers`, keyed on
  the PORTAL so staff viewing Transmission's portal see what Transmission sees). The route is the real
  gate (`_explainers_allowed`): staff from any session, otherwise only a 100% Digital agency session;
  partner agencies and clients get 403, logged-out visitors go to login. Scoped this way because the
  copy speaks as "our buyers" / "100% Digital". All data in them is illustrative and names no client.
- **Editing:** the files are self-contained (logos inlined as base64, Google Fonts linked). Edit the
  HTML in place and redeploy the platform; nothing else references them.
## The knowledge base (`/kb`, `kb_*.py`, 2026-09-14)
The agency's own written record, made answerable: media plans, briefs, meeting outcomes, platform
documentation, the playbook, and the corrections buyers have made to earlier answers. **Internal
only** - staff and 100% Digital. No client, and no other agency, can reach any part of it.

Reached from the **super-admin console** (a Knowledge base section beside Tools) and the **100%
Digital portal** (a `Documents` tab in the rail, plus two cards in The Brain tab under the three
"How The Brain works" walkthroughs that describe this exact system).

| Surface | What it is |
|---|---|
| `/kb/` | **Documents** - a Windows File Explorer: folder tree, breadcrumb address bar, sortable details list, icons view, multi-select, right-click menu, F2 rename, Delete, drag onto a folder to move, drag-and-drop upload with a progress row, and a per-row indexing state (`indexing` -> `searchable`). |
| `/kb/#ask` | **Ask** - a panel beside the list: knowledge base picker, streamed answer, citations that open the document at the passage, the model that answered, and the three-button feedback loop. |
| `/kb/observability` | **Observability** - reachability, index size, a probe box that runs the real retriever, the last fifty questions, activity, and the settings actually in force. **Staff only.** |

### Who can reach it
`KB_AGENCY = "x100-digital"` in `main.py`, next to `EXPLAINER_AGENCY`, and `_kb_allowed()` is a copy
of `_explainers_allowed()` (NOT of `_internal_allowed(client)`, which takes a client slug and answers
a different question). Staff from any session; otherwise only a 100% Digital agency session.
- **The ROUTE is the gate.** The portal tab and the console cards only decide what renders, and both
  are keyed on the PORTAL like `show_explainers`, so staff inside Transmission's portal see what
  Transmission sees.
- **An external agency is refused before the blueprint runs.** `_external_deny_by_default` denies
  every endpoint not on `_EXTERNAL_ALLOWED_ENDPOINTS`, and `kb.*` is deliberately not on it. Do not
  add it. A route added here is closed to outside tenants by construction, not by memory.
- Observability is narrower still: 100% Digital may read, ask and correct; the page listing every
  question anybody asked is staff only, enforced on the route.
- Gates are covered end to end in `dash/tests/test_kb.py` (staff yes, 100% Digital yes, Transmission
  403, client 403, external 403, logged out 401 or redirected).

### The modules
| File | What it owns |
|---|---|
| `kb_store.py` | Every object under `kb/` in the platform bucket. Documents, chunks, original files, conversations, feedback, the manifest. |
| `kb_chunk.py` | ~220-word passages with 40 of overlap, packed on structure, and the ONE tokenizer. |
| `kb_embed.py` | Vertex `text-embedding-005` in `australia-southeast1`, over stdlib `urllib`. |
| `kb_index.py` | BM25 + cosine fused by rank, the in-memory corpus, and `reindex_document`. |
| `kb_extract.py` | An upload into text: PDF via pypdf; Word, PowerPoint, Excel (python-docx / python-pptx / openpyxl, lazy) and WebVTT/SRT transcripts (2026-09-15, ported from the RAG branch) each writing its locator into the text like `[page N]`; text/Markdown/CSV; legacy .doc/.xls/.ppt and archives refused by name. |
| `kb_prompt.py` | The five prompt blocks, in a fixed order, identical for both providers. |
| `kb_chat.py` | Kimi streaming, Gemini as the named fallback. |
| `kb_feedback.py` | A correction into a trusted document that outranks what it corrects. |
| `kb_activity.py` | The usage record, one immutable object per event, and the Observability page's store. |
| `kb_trace.py` | Optional Phoenix spans. A genuine no-op when off. |
| `kb_routes.py` | Every HTTP surface, as one blueprint, with the gates injected rather than imported. |
| `dash/kb/HOW-BIDBRAIN-KB-WORKS.md` | The assistant's self-knowledge, shipped INSIDE the prompt on every turn. |
| `static/kb.js` · `kb_ask.js` · `kb_obs.js` · `kb.css` | The three pages. |

### Storage
```
gs://bidbrain-analytics-platform-dash/kb/
  docs/<id>.json          metadata + full text + revisions
  chunks/<id>.json        the passages + their vectors, WITH a copy of the document's metadata
  files/<id>/<name>       the original upload, byte for byte
  feedback/<id>.json      one record per correction
  chats/<actor>/<id>.json conversations
  activity/<YYYY-MM>/...  one object per event
  manifest.json           counts for the Observability page, and nothing else
```
`KB_PREFIX` overrides `kb`, which is how a local verification run writes into `kb-dev/` instead of
the real library. No database and no vector store: the corpus is thousands of chunks, not millions.

### The things that will bite somebody
- **🔴 The freshness signal is the OBJECT LISTING, not `manifest.json`.** A manifest is a mutable
  object every write must read-modify-write, and Cloud Run runs several instances: two uploads
  landing together lose an increment and the loser never notices a document again. `list_blobs` over
  `kb/chunks/` returns each object's GENERATION, which is atomic by construction and *is* the
  per-document version an incremental rebuild needs, so the check and the diff are one call.
  Measured in production: the signature check is ~27 ms and a whole search 0.35 s. (From a laptop
  the same figures are ~180 ms and ~2 s, which is the round trip to the region, not the design.)
- **🔴 The cache refreshes INCREMENTALLY.** Rebuilding from GCS is one GET per document, which at a
  few hundred documents is fifteen seconds after every write on every instance. Passages are keyed
  by object generation and only changed documents are re-fetched (verified: editing 1 of 3 reads
  exactly 1). Re-tokenising is still done in full, deliberately: caching token counters per chunk
  would put back the per-chunk dicts the array layout exists to avoid.
- **🔴 The index is PER PROCESS and the service runs two gunicorn workers.** Two copies of the
  corpus plus numpy per worker. The memory was raised off the original 512Mi for this;
  `deploy_dash_platform.ps1` is an image swap and will not set it, so it is a one-time
  `gcloud run services update platform-dash --region australia-southeast1 --memory 1Gi`.
- **🔴 There is no per-viewer visibility predicate**, unlike the system this is ported from. That
  one is private-by-default and enforces visibility inside the retriever. This one is not:
  everybody past the route gate reads all of it, and the only hard filter is SCOPE. Do not assume a
  document can be hidden from a colleague by putting it here.
- **🔴 `k3` accepts exactly one temperature.** Any value other than 0.6 returns
  `400 invalid temperature: only 0.6 is allowed for this model`, including the 0.2 that is right for
  a retrieval assistant everywhere else. `kb_chat` therefore sends NO temperature field and takes the
  provider's default; pinning 0.6 would break again the day a later model pins a different one. This
  is why the first live turn silently fell through to Gemini.
- **🔴 The Kimi code key only works against `https://api.kimi.com/coding/v1`.** Pointed at
  `api.moonshot.ai` it returns 401, which looks exactly like a revoked key. `KIMI_BASE_URL` overrides
  it so a plan change is an env var.
- **🔴 Kimi is SLOW from this region, and that is a decision to make, not a bug to hunt.** Measured
  in production on 2026-09-14: Kimi's first token lands at **5.6 to 6.8 s** and a whole answer takes
  **7.4 to 8.4 s**, against Gemini answering the same question completely in about **1 s**.
  Retrieval is 0.35 s of that, so essentially all the wait is the model. Kimi is first by decision,
  so swapping is an env var and not a code change:
  `gcloud run services update platform-dash --region australia-southeast1
  --update-env-vars KB_MODEL_ORDER=gemini,kimi`. A provider left out of the list is still a
  fallback, never silently unusable.
- **🔴 A title or a folder may never contain a line break.** A folder is a path STRING, so a pasted
  multi-line title becomes a folder of that name sitting in the rail forever. `kb_store.one_line` is
  the one place that is enforced; every title and folder goes through it.
- **🔴 The bookkeeping is set BEFORE the chunks are written**, not after. The chunks object carries
  the copy of the document's metadata that the file list reads, so writing it first publishes the
  previous run's `embed_error` and a document that failed to embed looks, in the list, exactly like
  one that succeeded.
- **🔴 A STREAMING ROUTE MAY NOT READ `session` INSIDE ITS GENERATOR, and the usage log learned
  that the hard way.** A Flask generator outlives the request context, so `_log_event` calling
  `_actor()` from inside `ask`'s generator raised `Working outside of request context` - and its own
  "never fail a request" except swallowed it. The result: every question the assistant answered
  recorded NOTHING, while uploads and plain searches recorded fine, so the Observability page read
  "1 question asked" after three. Hidden twice over, by the lost context and by a silent except.
  The actor is now captured before the generator and passed in, the failure logs at WARNING, and
  `test_a_streamed_question_is_actually_recorded` fails against the old code. Found live by counting
  objects in the bucket rather than trusting the page.
- **🔴 No class in `kb.css` may be `.card`, `.drow` or `.shead`.** The premium layer's scroll-reveal
  targets those by name and starts them at opacity 0 until an observer fires. On a list that
  re-renders on every click that means rows invisible until you scroll, which reads as data loss.
- **🔴 THE ROOT OF A SCOPE IS A FOLDER LIKE ANY OTHER (fixed 2026-09-16).** `/kb/docs?folder=`
  meant "no folder filter at all", so a document filed in Media plans was listed there AND at the
  client's root - one file in two places, which reads as filing gone wrong rather than as a listing
  bug, and made every folder row look like it had collected nothing. The root now lists only what
  sits directly in it, so anything that draws NO folder rows has to ask for the subtree: a search
  already passed `deep=1`, the Archived shelf did not and would have shown only unfiled documents.
  The rail's "No folder" node went with it - it had become a second name for the same list.
- **🔴 `continuous = true` DOES NOT MEAN "until I stop", AND `onresult` IS NOT THE WHOLE
  TRANSCRIPT (both fixed 2026-09-16).** Two independent defects with one symptom - pause for
  breath and the Ask panel's microphone lost what you had already said. (1) Chrome ends a speech
  session by itself after a few seconds of silence and fires `onend`; that used to switch the
  microphone off, so it has to be restarted (and the unfinalised tail banked first - a session
  that ends mid-sentence does not always finalise what it heard). (2) `onresult` hands you the
  results that CHANGED, from `e.resultIndex`, so writing that slice over the box made each new
  sentence replace the finished one before it: accumulate the finals yourself and redraw only the
  tail. `no-speech` and `aborted` are pauses, not failures; only `not-allowed`, `service-not-allowed`
  and `audio-capture` may stop it, plus a spin guard so a dead microphone cannot restart for ever.
  The same `onend` half is still in the dashboards' Internal Assistant widget (`main.py`).

### Trust, and why these numbers
One retriever's 40 candidates span 0.0064 of fused score. `TRUST_NUDGE = 0.004` lifts a
`trust: verified` document about 12 to 15 ranks: enough that a correction reliably surfaces, not
enough to beat a passage both retrievers ranked highly. What guarantees a correction outranks the
thing it corrects is TARGETED, not blanket: the correcting document names the passages it supersedes
and those take `SUPERSEDED_PENALTY = 0.02`, wider than the whole candidate span. Measured on the real
library: the corrected passage falls 0.03279 -> 0.01226 and rank 1 -> rank 5, while an unrelated
question is unaffected by the same verified document. The Observability probe box shows this by
re-running the identical query with trust switched OFF, rather than by asserting it.

### The feedback loop
Every answer carries **Right**, **Right, not here**, **Wrong**.
- **The person writes the rule, not the model.** A model-authored title would be an LLM writing into
  the trusted corpus with nobody approving it. The box prefills nothing it did not earn; their submit
  IS the approval.
- **"Right, not here" does not by itself make a document.** It means the answer was right and the
  citation was not, which is a retrieval signal, not new knowledge. Only a typed correction promotes.
- **Superseding is TICKED, not inferred.** Demoting every retrieved passage would punish seven for
  one wrong sentence, so the panel lists the citations and pre-ticks the top-ranked one, which can be
  unticked. A correction with nothing ticked still ranks up on trust; it just pushes nothing down.
- **A correction is never written into the document it corrects.** The original stands. Two documents
  that disagree is the true state of the world when a plan was superseded rather than rewritten, and
  the assistant is told to say which wins and why, naming who made the correction and when.
- **Withdrawing ARCHIVES the document it produced**, never deletes it: it leaves search and stays
  readable.

### Editing a document with the assistant (propose, approve, execute)
The assistant can keep the library current, and it never writes anything itself.

When a conversation settles something the library has wrong, missing or out of date, the model ends
its answer with one fenced ```bb-edit block. The browser strips that block from the prose **as it
streams** (otherwise raw JSON visibly types itself across the answer and then vanishes, which reads
as a glitch), and renders an **Approve card** showing which document, the heading, and the exact
text that would be added. Nothing happens until somebody presses the button.

- **🔴 Two verbs only: APPEND to a document, or CREATE a new one.** No rewrite, no replace, no
  delete, and the prompt forbids offering them. A whole-body rewrite generated by a model is a
  rewrite of everything it did not think to repeat, which is the likeliest way for an AI edit to
  quietly drop a paragraph somebody wrote. Appending cannot lose text: the worst case is a section
  nobody wanted, sitting visibly at the end, one revision from being undone.
- **🔴 The model names a PASSAGE NUMBER, never a document.** The number is resolved against that
  turn's own retrieval in the browser, so an invented or out-of-range number resolves to nothing
  and no card is offered. A model that could name a document id could name one it was never shown.
  Verified against hostile blocks: `passage: 9`, `passage: 0`, a bare `document_id`, an
  `action: "delete"`, an `action: "replace"`, empty text, malformed JSON and an unterminated fence
  all produce NO card, and none leak JSON into the prose.
- **🔴 It executes through the ordinary route, in the approving person's own session**
  (`POST /kb/docs/<id>/append`), with their gate and their revision trail. There is deliberately no
  service-to-service write path for the assistant: an internal write endpoint would bypass all of
  that and is the obvious way to end up with an AI editing a document nobody present may touch.
- **The block never survives into stored text.** It is stripped from the saved conversation and the
  feedback record. Fed back as a prior turn it would also teach the model that emitting one is
  simply how answers look, which is how proposals start appearing on questions that settle nothing.

### What an edit records, and where you see it
Every change writes a revision BEFORE it lands, so the newest revision is the state prior to the
most recent edit. Each carries **when** (`at`), **who** (`by`), **how** (`via`: `human` or
`assistant`) and **what** (`note`, which for an approved proposal is the exact one-line summary the
person read on the card). The document itself carries `updated_at` and `updated_by`.

Surfaced in three places: the details list has a **Modified by** column (tooltip: when, and how many
earlier versions); the document viewer says *added by X on <date>, last edited by Y on <date>, N
earlier versions*; and the **History** tab spells the mechanism out in words, not a badge:
*"drafted by the assistant, approved by <person>"* against *"edited by <person>"*. Restoring an
earlier version is itself an edit, so the assistant's change stays in the record rather than being
erased by the undo.

### The client dimension: a field, never a folder name
The library has two kinds of document: **agency-wide** (playbook, platform docs, standards) and
**a client's own** (their media plans, briefs, meetings). `client` is a first-class FIELD on the
document, holding a registry key, empty for agency-wide.

- **🔴 A FIELD, NOT A FOLDER CONVENTION.** This is the dimension the retriever isolates on, and it
  is what will scope the library when it is dropped into one client's dashboard or into the Grid's
  client view. A convention encoded in a folder string is one rename away from leaking one client's
  plan into another's answer.
- **🔴 ASKING AND BROWSING ARE DELIBERATELY DIFFERENT.** A client QUESTION reads that client PLUS
  agency-wide (`kb_index.doc_ids_for_client`), because an answer given without the playbook comes
  from a system that has forgotten its own standards. A client FOLDER VIEW shows that client only,
  because a file list that mixes in the playbook makes it impossible to see what a client holds.
  Verified both ways, including that agency-wide scope is NOT "everything".
- **The client list comes from the REGISTRY, scoped to the session** (`main._kb_clients`): staff
  see every dashboard, an agency session sees only its own clients, the same boundary `_may_open`
  enforces. A key the session has no business with resolves to agency-wide, never to somebody
  else's library, and `kb_store.client_key` rejects anything that is not a bare key (path
  traversal included).
- **🔴 `store.get_state()` HAS NO TOP-LEVEL `clients` KEY.** It returns
  `{agencies, unassigned, all_client_keys}` and the client records hang off each AGENCY. Reading a
  `"clients"` key returns an empty list and the picker silently offers no clients, which is exactly
  how this shipped the first time. Flatten across agencies and unassigned, deduped by key, because
  dual visibility puts one client under two agencies.

### The repo's markdown, mirrored (`scripts/kb_repo_sync.py`, 2026-09-17)
The `bidbrain-analytics` repo's own documentation - AGENTS.md, all 20 client READMEs, every ingest
unit, the Grid and platform guides - is in the library as a **`Bidbrain analytics` folder** holding
~880 documents from 164 markdown files, agency-wide (no `client` key), `kind: reference`. It syncs
itself: every push to `main` that touches a `.md` runs `.github/workflows/kb-sync.yml`, which runs
that script, which writes through `kb_index.reindex_document` exactly as an upload does.

**Edit the markdown in git. An edit made to one of these documents in the Explorer is replaced on
the next sync** - and kept, in full, as a revision on the document, so nothing typed is lost.

- **🔴 SECTIONS, NOT FILES, AND THAT IS THE WHOLE POINT.** `client_cloudflare/README.md` is 230,000
  characters. Loaded as one document, every passage in it would carry the title "README.md" into
  `kb_embed` (which attaches the title to EVERY chunk's vector) and into `kb_index`'s BM25 tokens
  (`tokenize(text + " " + title)`). Split at headings, a passage instead carries
  `clients/client_cloudflare/README.md > The motion layer`. Same text, same chunker, far better
  ranking, for no run-time cost.
- **🔴 `MAX_PER_DOC = 2` IS WHY OVERSIZED SECTIONS ARE SPLIT FURTHER.** A document contributes at
  most two passages to any answer however long it is, so a 40,000-character section is not merely a
  big document - it is ~180 passages of which two can ever be cited. Nothing is left above ~14,000
  characters; cuts are taken at blocks, then sentences, and every part is numbered in its title.
- **🔴 THE CLIENTS TABLE IN AGENTS.md IS ONE DOCUMENT PER ROW, NEVER PACKED.** That table is a row
  per client with the client's name stated once at the start of a line running to several thousand
  words. Packing two small rows together is the obvious economy and it destroys the only thing the
  split exists for: a passage about `proptrack` would carry a title naming four other clients.
- **SPLIT, NEVER REWRITE.** Nothing is paraphrased, summarised or reflowed - verified across all 164
  files at word level, zero words lost, and asserted on every run of `scripts/test_kb_repo_sync.py`.
  A library that improves its own sources answers from text that exists nowhere and sends the reader
  to a file that says something else.
- **Deterministic ids** (`repo_<sha1 of path + heading path>`) make it a sync rather than an import:
  a run updates in place instead of adding a second copy beside the first. **It only ever deletes ids
  with that prefix**, so a person's document is never at risk, and a markdown file deleted from the
  repo takes its own documents with it (git is the history; a tombstone here is just a stale answer
  waiting to be retrieved).
- **🔴 LINE ENDINGS ARE NORMALISED BEFORE THE CONTENT HASH.** This repo is `core.autocrlf=true`, so
  a Windows checkout is CRLF and CI is LF. Without that one line, every run from the other platform
  rewrites and re-embeds all 164 files to change nothing.
- **Not tagged to a client, deliberately.** `client` is what the retriever isolates on, and browsing
  a client shows that client ONLY - so tagging these would take them out of the agency-wide folder,
  while changing nothing about what a client question retrieves (a client scope already reads that
  client PLUS agency-wide). These are our engineering notes about how we built a dashboard, not the
  client's own plans and briefs.
- **Size, and the one-off stall.** 882 documents, 2,798 passages, 104 folders, ~2,650 object writes
  and ~880 Vertex calls on a first load (10 to 20 minutes; every later run touches only what
  changed). It roughly quadruples the library, so **the first search after the initial load rebuilds
  the whole cache - one GET per document, on each instance** and takes tens of seconds. That is the
  incremental cache filling, once, not a fault.
- **It shares the library with the business record, so use the SCOPE.** These are engineering notes;
  a question about a media plan can now retrieve a passage of AGENTS.md. The knowledge base picker's
  folders are the only HARD filter in `kb_index.search`, so narrowing to (or away from)
  `Bidbrain analytics` is how an ask is kept to one kind of document.
- **Two assistants, opposite outcomes, both correct.** The STAFF dashboard assistant
  (`kb_bridge.retrieve`) searches the client PLUS agency-wide, so from now on it can cite that
  client's own README and its row of AGENTS.md - which is the context a person on that dashboard
  actually wants. The CUSTOMER assistant (`kb_bridge.retrieve_for_client`) keeps only documents
  marked `visibility='client'`, and `kb_store.make_doc` has no such field, so **not one of these
  engineering documents can reach a customer - by construction, not by configuration**. Keep it that
  way when the held `visibility` change lands: these default to internal.
- **CI holds no key.** `scripts\setup_kb_sync_auth.ps1` sets up workload identity federation pinned
  to this repository, a dedicated `kb-sync` service account, and a storage grant **conditioned to the
  `kb/` prefix** - because `platform.json`, which holds every dashboard password, is in the same
  bucket and a CI identity has no business reading it. Listing comes from a custom role holding
  `storage.objects.list` alone, since that permission is checked against the bucket and cannot carry
  the condition.
- The scheduled reconcile is **four times a day, not hourly, and that is a billing decision**: this
  repo is private, so Actions minutes are metered and an hourly job that almost always finds nothing
  would spend most of a 2,000-minute free tier. Pushes are the real trigger. The schedule exists
  mainly to retry any document that was indexed WITHOUT VECTORS during a Vertex blip - those stay
  searchable by keyword and nothing on screen says the ranking is degraded.

### The Ask panel: a bubble, not a column
A launcher bubble bottom-right opens a floating, draggable, resizable panel (`kb_panel.css`,
`static/kb_ask.js`). Shaped after Sentinel's assistant panel because that shape is already trusted;
coloured like this console. The Explorer keeps two grid columns and never reflows when it opens.
Drawers slide over the conversation for **history** and **settings**; a phone gets a sheet with no
drag and no resize.

### Settings: which model, which voice
Stored per person at `kb/settings/<actor>.json`.

- **🔴 SERVER SIDE, NOT `localStorage`.** The model has to be chosen before a single token streams,
  so the server must be able to read it; and a choice that lives in one browser is a different
  assistant on a phone. localStorage keeps only what is genuinely per-device: whether the panel is
  open, and its size.
- **Every field falls back to a server default**, because a saved preference is a stale preference
  the moment a model is retired, and nobody migrates a settings file. `resolve()` also reports
  `model_effective` and a `model_note`, so a chosen model with no key on this deployment says so
  instead of being silently ignored.

### Three models, and the same gotcha twice
Kimi, Gemini and **Claude** (`claude-sonnet-5`, Anthropic Messages API, secret `anthropic-api-key`).

- **🔴 NEITHER KIMI NOR CLAUDE ACCEPTS A TEMPERATURE, FOR DIFFERENT REASONS.** `k3` answers
  `400 only 0.6 is allowed for this model`; `claude-sonnet-5` answers
  `400 temperature is deprecated for this model`. Either one fails the WHOLE request. Neither call
  sends one now. Claude's was caught because it fell back to Kimi on the first real turn, which is
  precisely what the fallback is for and precisely why the panel names the model that answered.
- Claude's system prompt is its own top-level `system` field, not a message with role `system`,
  which Anthropic rejects. `anthropic-version` is a required header. `max_tokens` is mandatory.
- Measured first token locally: **Claude 1.1s, Gemini 1.4s, Kimi 1.7s**.

### Voice, both ways
- **In**: the browser's own speech recognition, on the composer and on the feedback context box.
  🔴 Dictation lands in the box as editable text. **Nothing is ever sent by the microphone or by a
  pause** - you edit it and press Send.
- **Out**: the browser voice (free, never touches the server) or **Chirp 3 HD** / Gemini Flash TTS
  through `POST /kb/speak` (`kb_tts.py`), returning MP3 **bytes, never a URL**, so nothing needs a
  `media-src` for a third party.
- **🔴 THE RUNTIME SERVICE ACCOUNT NEEDS `roles/serviceusage.serviceUsageConsumer`.** Cloud TTS has
  no IAM role of its own and refuses a caller that may not "use" the project, with a 403 naming
  neither. This is the most likely reason a fresh deployment is silent.
- **🔴 LOCALLY, USER ADC ALSO NEEDS A QUOTA PROJECT**, sent as `x-goog-user-project`. Without it
  Cloud TTS 403s on a laptop while working fine on Cloud Run, which makes the feature untestable
  locally, which is the same as untested.
- A spoken reply is a **different reply**: `SPOKEN_STYLE` replaces the written rules with "talk, do
  not write, one to three sentences". That rule is also the cost control, since Chirp bills ~$30
  per million characters. Citations STAY in the text (they are clickable on screen) and are
  stripped from the audio, along with markdown and the space a removed bracket leaves before a
  full stop.
- A cloud voice failure falls back to the browser voice **and says so once in the log**, because a
  voice mode that simply goes quiet reads as broken.

### Feedback carries the reason, not just the verdict
Right / Right, not here / Wrong, and **all three open an optional context box**, including Right:
"it is right" and "it is right because the Q3 plan supersedes the Q2 one" are worth very different
amounts to the next person, and a thumbs-up with nowhere to explain it throws the second away. The
context box can be dictated too.

### Identity, stated rather than implied
Only Google and Microsoft sign-in set `session["email"]`. A typed admin password and the shared
100% Digital password identify a TIER, so `_kb_actor()` records `shared:superadmin` or
`agency:x100-digital`, several people share that identity, and conversations under it are shared.
The UI says so (`KB_SHARED_LOGIN`) instead of implying a privacy the platform cannot deliver, and
`kb_store.display_actor` turns the raw string into something readable before it reaches a sentence -
without it the assistant wrote "this follows a correction shared:superadmin made".

### Meetings: Fathom into the library, filed to the right client (2026-09-15)
`/kb/meetings` (`kb_fathom.py`, `kb_memory.py`, `kb_fathom_routes.py`, `kb_meetings.html` +
`static/kb_meetings.js`), same gate as Documents. ONE connected Fathom account - Charles's; a Fathom
API key is scoped to the user who created it, so his meetings are the corpus. Verified against
developers.fathom.ai 2026-09-14/15: `https://api.fathom.ai/external/v1`, header `X-Api-Key`,
`GET /meetings` (cursor, created_after, include_transcript, include_summary); webhooks HMAC-SHA256
over `{webhook-id}.{webhook-timestamp}.{body}`, secret `whsec_<base64>`, header `webhook-signature`
`v1,<b64>`, 5-min tolerance. Secrets `fathom-api-key` / `fathom-webhook-secret` as env
`FATHOM_API_KEY` / `FATHOM_WEBHOOK_SECRET`; unset = the page says "not connected", `POST
/kb/api/fathom/sync` and `POST /fathom/webhook` answer 503, nothing else changes.

- **A meeting becomes an ordinary document**: `kind=meeting`, `source=fathom` (added to
  `kb_store.SOURCES`), folder `Meetings` under the client, id `fathom-<recording_id>` so a
  re-delivered webhook re-indexes rather than duplicates. Body = summary FIRST (the outcomes the
  Meetings folder promises), then the transcript as `[HH:MM:SS] Speaker: text` lines - the inline
  locator convention of `kb_extract`. The raw meeting JSON is kept as the document's file. Fathom
  facts (recording id, url, invitees, who assigned it and on what evidence) ride on the doc object
  under `fathom`; `doc_meta` ignores them, so the index does not change shape.
- **The assignment ladder** (`kb_fathom.classify`), top rung wins, deterministic until the last:
  no external invitee -> a HINT to the model, not a filing (since 2026-09-16 - the invite list says
  who was there, only the transcript says what it was about); an external invitee's email domain
  matching exactly ONE client's DECLARED domains -> that client; `kb_memory.match` (a person or recurring title
  confirmed on exactly one client) -> that client; else an evidence bundle - entity match against
  every live dashboard's campaign/ad-group names (`main._fathom_entities`, 6h cache), a corpus vote
  over meetings already filed (`kb_index.search` + `all_meta`, meetings only), one
  `gemini-2.5-flash` synthesis over the CLOSED list of registry keys - and the meeting **waits in
  the queue** with that proposal pre-selected. `FATHOM_AUTO_ASSIGN` (default `0.95`) is the
  confidence at which rung 3 files without a click; `1.01` would mean never.
- **🔴 THE RULE (Jerome, 2026-09-16): 95-100% sure files itself; when the system is not sure, a
  person decides - and the deciding is done by the model over the transcript, the corpus vote and
  the memory hints, not by codified rules ("make use of AI, RAG and memory mainly for decisions").**
  The two SURE rungs (declared domain, memory) are 100% and file (`FATHOM_AUTO_FILE`, default
  `domain,memory`; set it empty and they become 100% guesses in "Ready to confirm" instead). The
  model files at `FATHOM_AUTO_ASSIGN` (default `0.95`; `1.01` = never), a client OR agency-wide
  alike; it also answers `work` - whether the call is about agency/client business at all - and a
  call it says is NOT work always waits, with that reason on the card. So an all-agency stand-up
  about the dashboards files itself as Agency-wide at 97%; an all-agency chat about the office move
  waits. Below the line the meeting waits with its guess pre-selected. `FATHOM_QUEUE_TITLES`
  (default 1:1, one on one, interview, hr, performance review, personal, salary, payroll, catch up)
  ALWAYS waits - Charles's Fathom records every meeting it joins, not only client calls. A model
  filing never teaches memory (`index_meeting` learns from domain/memory/human only), so a wrong 95%
  cannot teach the next one; fix one by moving the document in the Explorer.
- **Memory is written only by confirmed assignments** (human, domain, memory rung) - never by a
  model proposal, so a wrong guess cannot teach the next one. `<PREFIX>/fathom/memory/<client>.json`:
  people / titles / domains / patterns (learned), `client_domains` (declared, rung 1), `facts`
  (hand-written). `kb_memory.profile_block(client, audience)` renders facts (+ campaign patterns
  for staff) for a prompt; `client_safe()` is facts ONLY - people and domains never leave.
- **The queue is not the library**: `<PREFIX>/fathom/unassigned/<rid>/{meeting,proposal}.json`
  is never indexed, so an unplaced meeting is never retrievable. Assign / Ignore on the page.
- **The card says what Assign will teach** (`will_learn` on each queue item = `kb_memory.teaches`):
  "Will remember: priya@cloudflare.com · cloudflare.com · 'cloudflare weekly'", each with a tick
  box. Unticked items travel as `skip` on `POST /kb/api/fathom/assign` and `learn(skip=...)` leaves
  them out; the meeting is filed either way. Picking a client other than the proposal renames the
  button "Assign to <client>" so an override is visible before the click; assigning removes only
  that card (no queue rebuild, so edits on other cards survive).
- **🔴 The webhook REPLIES FIRST, then classifies** (`kb_fathom_routes.accept`, 2026-09-15). Fathom
  (Svix-style) retries an endpoint that does not answer within seconds, and the evidence rung reads
  every live dashboard's `data.json` - measured at over two minutes for 18 dashboards on a cold
  cache in the level-2 test. So: `already_indexed` (one GET) -> `store_unassigned` (the meeting is
  in the queue, with no proposal yet) -> `200 {decision: "accepted"}` -> the ladder runs in a
  daemon thread and writes the proposal (or files the meeting) when it finishes. **Sync now** has
  the same shape (`sync_in_progress` in `fathom/state.json`; the page polls every 5 s). The entity
  harvest itself (`main._fathom_entities`) never blocks either: a cold cache returns `{}` and warms
  in the background, so the very first meeting's evidence rung simply contributes nothing.
  **Cloud Run caveat, stated not solved:** with request-based CPU allocation the background thread
  can be throttled after the reply; the meeting is already queued, so the worst case is a proposal
  that never arrives and a person picks the client unaided. If that shows up in the pilot, give
  `platform-dash` CPU-always-allocated or move the ladder onto the next request / Sync.
- **🔴 Two facts about the LIVE Fathom API that the docs' examples do not show** (first real sync,
  2026-09-16, Christian's key): `default_summary` is an OBJECT `{template_name, markdown_formatted}`
  - read it through `kb_fathom.summary_text`, never `str()` it; and `is_external` is relative to
  the RECORDER's domain, so a 100.digital colleague on a bidbrain.ai recording is flagged external.
  `kb_memory.INTERNAL_DOMAINS` (env `FATHOM_INTERNAL_DOMAINS`, default `100.digital,bidbrain.ai`)
  makes an agency invitee internal whatever Fathom says - it gates the internal-only rung, the
  declared-domain rung, memory learning/matching and the card's "Will remember" list together.
- `kb_fathom.synthesise` says WHY the classifier was unavailable (no key vs no candidates) in the
  proposal's `why`, so the queue card never shows a bare "unavailable" again.
- A 🔴 for Ian's `CLIENT_FOLDERS` note "Outcomes, not transcripts": these documents DO carry the
  transcript after the summary. `MAX_PER_DOC=2` keeps a long transcript from crowding the library;
  if that is not enough, `kb_fathom.meeting_body` is the one place to drop it.

### Observability, and Phoenix
The page answers "why did it say that?" **with tracing switched off**, because the question record it
reads is the activity log in the bucket, not this instance's memory: the instance that answered is
rarely the one serving the page. Phoenix is optional (`PHOENIX_COLLECTOR_ENDPOINT`), a genuine no-op
when unset, and `KB_TRACE_CONTENT=off` stops passage text being captured for a Phoenix somebody else
can read.
- **Phoenix's OTLP/HTTP endpoint is protobuf only** (JSON gets a flat 415), so `kb_trace` uses the
  ENCODER half of the official exporter and posts the bytes with `requests`.
- **The otel version is load bearing**: `opentelemetry-*==1.27.0` pins protobuf to 4.x and breaks the
  whole `google-cloud-*` stack this service runs on. `1.44.0` coexists with protobuf 7. Verified.

### Running it locally
```powershell
$env:PLATFORM_BACKEND="memory"; $env:DEV="1"; $env:SESSION_SECRET="x"; $env:SSO_SECRET="y"
$env:COOKIE_DOMAIN=""; $env:GCS_BUCKET="bidbrain-analytics-platform-dash"; $env:KB_PREFIX="kb-dev"
.\.venv\Scripts\python.exe bidbrain-platform\dash\main.py
```
Writes are refused from a local run (`_prod_mutation_blocked`); `ALLOW_PROD_MUTATIONS=1` overrides,
and `KB_PREFIX` keeps them out of the real library. Tests:
```powershell
cd bidbrain-platform\dash; ..\..\.venv\Scripts\python.exe -m pytest tests -q
```
They touch REAL GCS under a throwaway `kb-test-<random>/` prefix and wipe it, on purpose: the design
rests on GCS generations behaving as the index assumes, and a fake storage layer would test the fake.

### Wiring (one-time, already done)
```powershell
gcloud projects add-iam-policy-binding bidbrain-analytics `
  --member="serviceAccount:platform-dash-web@bidbrain-analytics.iam.gserviceaccount.com" `
  --role="roles/aiplatform.user"
gcloud secrets add-iam-policy-binding kimi-api-key `
  --member="serviceAccount:platform-dash-web@bidbrain-analytics.iam.gserviceaccount.com" `
  --role="roles/secretmanager.secretAccessor"
gcloud run services update platform-dash --region australia-southeast1 `
  --update-secrets="KIMI_API_KEY=kimi-api-key:latest" --memory 1Gi
```

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
    internal_chat.py             staff-only Assistant: Gemini turn over live data.json + lineage digest (+ LIBRARY passages and the client profile when kb_bridge hands them over), with note tools + visible thinking
    kb_bridge.py                 the dashboard assistant's read of the knowledge base: shaped query, client+agency scope, numbered context, sources (2026-09-15); retrieve_for_client = the client-visible-only read
    client_chat.py               the Client Assistant turn (DARK: CLIENT_CHAT_ENABLED + per-client flag + visibility all default off); forbidden-token guard, billed basis only
    glossary_draft.py            drafts glossary/<c>.draft.md from the lineage digest for a human to review (one Gemini call); the assistant never reads a draft
    glossary/                    reviewed client-safe KPI glossaries (<c>.md) + README rules; resetdata.draft.md awaits review
    kb_store.py                  knowledge base storage: docs / chunks / files / chats / feedback under kb/ in the platform bucket
    kb_chunk.py                  ~220-word passages packed on structure, 40-word overlap, and the ONE tokenizer
    kb_embed.py                  Vertex text-embedding-005 over stdlib urllib; RETRIEVAL_DOCUMENT vs RETRIEVAL_QUERY; fails soft and says so
    kb_index.py                  BM25 + cosine fused by rank (RRF), incremental in-memory corpus, and the reindex write path
    kb_extract.py                an upload into text (PDF, Word, PowerPoint, Excel, WebVTT/SRT, text/Markdown/CSV; locators inline like [page N]); legacy binaries refused BY NAME, never stored as mojibake
    kb_prompt.py                 the five prompt blocks in a fixed order, identical for both providers
    kb_chat.py                   Kimi streaming with Gemini as the NAMED fallback (the panel says which answered)
    kb_feedback.py               a buyer's correction into a trusted document that outranks the passage it corrects
    kb_activity.py               the usage record: one immutable object per event, and the Observability page's store
    kb_trace.py                  optional Phoenix spans; a genuine no-op unless PHOENIX_COLLECTOR_ENDPOINT is set
    kb_settings.py               each person's model + voice choice, server side (kb/settings/<actor>.json)
    kb_tts.py                    Cloud Text-to-Speech: Chirp 3 HD / Gemini Flash TTS, returns MP3 bytes
    kb_routes.py                 every /kb HTTP surface as one blueprint, with the gates INJECTED (main.py imports this, not the reverse)
    kb_fathom.py                 Fathom meetings -> documents: webhook signature, meeting body, the assignment ladder, the queue (2026-09-15)
    kb_memory.py                 client profile memory: learned people/titles/domains/patterns, declared domains, facts; the ladder's rung 2
    kb_fathom_routes.py          /kb/meetings + /kb/api/fathom/* + POST /fathom/webhook, same injected gates as kb_routes
    templates/kb_meetings.html   the Meetings page (connection, queue, declared domains, memory)
    static/kb_meetings.js        the Meetings page's JS - talks only to /kb/api/fathom/*
    kb/HOW-BIDBRAIN-KB-WORKS.md  the assistant's self-knowledge, shipped INSIDE the prompt on every turn
    static/kb.js kb.css          the Documents explorer (client tiles, folders, the file list)
    static/kb_ask.js kb_panel.css   the floating Ask panel: bubble, drawers, voice, feedback
    static/kb_obs.js             the Observability page
    tests/test_kb.py             every gate in the access table, plus the feedback loop end to end (real GCS, throwaway prefix)
    build_lineage.py             builds lineage/<c>.txt digests from clients/*/README.md + sql/ headers (run after doc/sql changes)
    lineage/                     committed per-client lineage digests, shipped in the image (COPY lineage)
    seed_registry.py             push config.py → the registry JSON in GCS (idempotent; --force to overwrite)
    explainers/                  "How The Brain works" walkthrough pages, served at /brain/how-it-works/<slug> (100% Digital portal)
    templates/                   login.html · portal.html · admin.html · superadmin.html (dark theme, Bidbrain logo)
      _premium_head.html         premium layer bootstrap - include in <head> (see "The premium layer")
      _premium.html              premium layer CSS + engine - include LAST in <body>, after _status_merge.html
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
Microsoft sign-in; no secret) · `KIMI_API_KEY` (secret `kimi-api-key`, the knowledge base assistant)
· optional `KB_PREFIX`, `KB_EMBED=off`, `KB_MODEL_ORDER`, `KIMI_BASE_URL`, `KB_KIMI_MODEL`,
`KB_GEMINI_MODEL`, `PHOENIX_COLLECTOR_ENDPOINT`, `KB_TRACE_CONTENT` · registry
`gs://bidbrain-analytics-platform-dash/platform.json` (private). The knowledge base lives under
`kb/` in the same bucket. **`roles/aiplatform.user` on the project** for Vertex embeddings.
No database, no export job, no scheduler.

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
