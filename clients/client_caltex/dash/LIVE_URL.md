# Caltex Dashboard — status + go-live runbook

> **DEPLOYED 2026-07-29; waiting only on the next ingest run.** The pipeline reads
> `raw_windsor.perf_the_trade_desk` filtered to TTD advertiser **`0lw3hp6`** (campaign
> **"Caltex Star Card | QLD+WA | Jul-Oct 2026"**, ad groups `Display Standard | QLD+WA`,
> `AI Contextual | QLD+WA`, `Attention-Optimised | QLD+WA`). Views, seeds, the export job and its
> `*/10` scheduler are all live. Until the export writes a real `caltex.json`, the service serves
> the baked-in SAMPLE payload (`dash/placeholder.json`, `meta.placeholder=true`) behind a
> "sample data" banner, which clears itself on the first real build.

**Service URL:** https://caltex-dash-516554645957.australia-southeast1.run.app
**Password:** Secret Manager secret `caltex-dash-password`. Portal tile is live (100% Digital).

## How the client gets in - the two access paths (verified vs resetdata, 2026-07-31)

There is **no** `caltex.bidbrain.ai` subdomain, and no client has one (`resetdata` documents the same:
"There is no `resetdata.bidbrain.ai` subdomain"). Every dashboard has exactly two ways in:

| Path | URL | Login | Billed-spend gross-up |
|---|---|---|---|
| **Its own dashboard URL** (per-client, what most clients are given) | https://caltex-dash-516554645957.australia-southeast1.run.app | the dashboard's OWN password, Secret Manager `caltex-dash-password` | **NOT applied - shows RAW media cost** |
| **Platform front-door** | https://dashboards.bidbrain.ai/d/caltex/ | one platform login (password, or Google / Microsoft sign-in) | **Applied** - shows client-billed spend |

Read the dashboard password (never commit it):

```powershell
gcloud secrets versions access latest --secret=caltex-dash-password
# rotate (no redeploy - the service reads :latest):
#   printf '%s' 'NEW' | gcloud secrets versions add caltex-dash-password --data-file=-
```

The `…run.app` URL is harmless without the password (login screen only); `caltex.json` lives in a
**private** bucket and is served solely to an authenticated session via `/data.json`, never publicly.

### CHOOSE THE PATH ON WHETHER SPEND IS MARKED UP

`window.BB_SPEND_MULT` (the super-admin "Multiplier" panel) is injected by the **proxy only**, so:

- Caltex is billed **at raw media cost** -> either path is fine.
- Caltex is billed **above** raw media cost (the agency does do this - e.g. geocon runs `meta` x2.0,
  and TTD markups of x3-7 are normal here) -> the client MUST come in through the front-door, and a
  `ttd` multiplier must be set for caltex. Handing out the `…run.app` URL in that case shows the
  client the REAL media cost and leaks the margin.

As of 2026-07-31 caltex has **no** multiplier set (`spend_multipliers: {}`), so both paths currently
show identical, raw numbers. Set one before sharing the direct URL if the plan's A$5,000/month is a
billed rate rather than pass-through media cost.

### Google / Microsoft sign-in (front-door only)

Client-side users can be granted sign-in access scoped to THIS dashboard alone, so they see no other
100% Digital client:

```powershell
$env:GCS_BUCKET="bidbrain-analytics-platform-dash"
.\.venv\Scripts\python.exe -c "from store import Store; Store().upsert_user('someone@client.com', role='client', client_key='caltex')"
# (or use the super-admin console's "Google sign-in access" panel)
```

Granted 2026-07-31: `tilly@iddigital.com.au` -> role `client`, scoped to `caltex`.

## Why it wasn't live on day one (diagnosed 2026-07-29 - NOT a Windsor grant problem)

The advertiser **is** granted and visible in Windsor (verified directly against the API: advertiser
`0lw3hp6` / "Caltex", all three ad groups, 22,443 impressions + 33 clicks). The campaign simply
**started delivering on 2026-07-28**, and the shared TTD loader walks backward from *yesterday* -
its 2026-07-28 21:35 UTC run therefore covered only through 07-27, one day before first delivery.
So `raw_windsor.perf_the_trade_desk` legitimately held no Caltex rows.

**This self-heals.** `windsor-tradedesk-ingest` runs daily at **21:35 UTC**; its next run's first
chunk (07-26 to 07-28) includes the delivery, and `caltex-export`'s `*/10` gate then publishes
within ~10 minutes. An earlier version of this runbook wrongly told you to grant the advertiser in
Windsor - no grant is needed.

## To go live IMMEDIATELY instead of waiting for the nightly run

Needs valid local Google credentials (the org's reauth window is ~1h, so re-run these whenever a
command fails with "Reauthentication is needed"):

```powershell
gcloud auth login ian@100.digital            # deploys need ian@ (charles@ has no deploy perms)
gcloud auth application-default login        # ADC for the python loaders/venv

# 1. pull the delivered days into the shared raw table (fixed range; MERGE is idempotent)
.\.venv\Scripts\python.exe ingest\windsor_data_pull\tradedesk\tradedesk_loader.py 2026-07-28 2026-07-29

# 2. publish (bypasses the freshness gate)
gcloud run jobs execute caltex-export --region australia-southeast1 --update-env-vars FORCE_REBUILD=1 --wait
```

Then confirm the rows landed and the tactic parse is right:

```powershell
bq query --use_legacy_sql=false "
SELECT ad_group_name, COUNT(*) n, SUM(impressions) imps, SUM(clicks) clicks, ROUND(SUM(cost),2) cost
FROM \`bidbrain-analytics.raw_windsor.perf_the_trade_desk\`
WHERE advertiser_id='0lw3hp6' GROUP BY 1 ORDER BY imps DESC"
```

Expect the three `Tactic | QLD+WA` names. The export refuses to upload an empty fact (guard in
`job/main.py`), so a premature run can never replace the placeholder with a blank dashboard.

## Step 2 — stand up / go live

```powershell
# One-shot standup if never deployed (APIs, SAs, IAM, bucket, secrets, placeholder service):
.\clients\client_caltex\deploy_caltex.ps1

# Full pipeline once Step 1 verifies data (seeds + views + job + scheduler):
.\.venv\Scripts\python.exe clients\client_caltex\seed_static.py
.\clients\client_caltex\deploy_caltex.ps1 -WithData

# If the service/job were already stood up, just refresh the stages that changed:
.\clients\client_caltex\dash\deploy_dash_caltex.ps1                       # new dashboard.html/main.py/report.py
.\clients\client_caltex\job\deploy_job_caltex.ps1                         # new job/main.py
.\.venv\Scripts\python.exe clients\client_caltex\create_views.py          # new sql/*.sql
gcloud run jobs execute caltex-export --region australia-southeast1 --update-env-vars FORCE_REBUILD=1 --wait
```

The moment `caltex-export` writes `caltex.json` to the bucket, `/data.json` prefers it over the
placeholder and the "sample data" banner clears automatically.

## Step 3 — surface it on the platform

```powershell
# Portal tile (if not already present):
$env:GCS_BUCKET="bidbrain-analytics-platform-dash"
.\.venv\Scripts\python.exe bidbrain-platform\dash\add_caltex_placeholder.py --yes
```
Then in the platform admin UI flip the tile to `active` with the run.app URL, and (super-admin)
set the **ttd spend multiplier** for caltex if the client is billed above raw media cost
(`window.BB_SPEND_MULT` — the dashboard's `bbApplySpendMult` shim is wired for channel `ttd`).

## Step 4 — once real data lands, verify the model

1. **Conversion slots:** if site actions appear, check whether TTD exported duplicate tracker
   pairs (`SELECT raw_row ... LIMIT 5`) — if so, switch `sql/01_stg_ttd.sql` to one column per
   pair (the VMCH `{01,03,05}` pattern) and re-run the export.
2. **Targets:** replace the `PENDING` placeholders in `targets/*.csv` (flight window, A$30k
   budget, CPM/CTR/CPC/impression targets) with the signed media plan → `seed_static.py` →
   export `FORCE_REBUILD=1`.
3. **Stage mapping:** confirm with the client that Attention-Optimised sits in the Consideration
   lane (one-line CASE in `sql/01_stg_ttd.sql`).
4. **Status dashboard:** add caltex to `status_dashboard`'s `BQ_CLIENTS` spec so the platform's
   Overview health badge + Data Accuracy tab cover it.

## What gets deployed

| Thing | Value |
|---|---|
| Project / Region | `bidbrain-analytics` / `australia-southeast1` |
| Raw source | `raw_windsor.perf_the_trade_desk` (advertiser `0lw3hp6`) |
| Views dataset | `client_caltex` (`stg_ttd`, `fact`, `targets`, `budget` + 2 seed tables) |
| Export Job | `caltex-export` (self-gating `*/10` UTC via `caltex-export-daily`) |
| Dash Service | `caltex-dash` (serves `dashboard.html`; `/data.json` = bucket, else `placeholder.json`) |
| Data bucket / file | `bidbrain-analytics-caltex-dash` / `caltex.json` |
| Job SA | `caltex-dash-job@…` (BQ jobUser + dataViewer, Storage objectAdmin on bucket) |
| Web SA | `caltex-dash-web@…` (Storage objectViewer on bucket, Secret accessor) |
| Secrets | `caltex-dash-password`, `caltex-dash-session-key` |
