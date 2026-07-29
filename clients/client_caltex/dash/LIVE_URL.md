# Caltex Dashboard — status + go-live runbook

> **REBUILT FOR THE TRADE DESK (2026-07-29), awaiting data verification.** The pipeline now reads
> `raw_windsor.perf_the_trade_desk` filtered to TTD advertiser **`0lw3hp6`**
> (desk.thetradedesk.com/app/home/advertiser/0lw3hp6 — ad groups `Display Standard | QLD+WA`,
> `AI Contextual | QLD+WA`, `Attention-Optimised | QLD+WA`). Until the export job writes a real
> `caltex.json`, the service serves the baked-in TTD-shaped SAMPLE payload
> (`dash/placeholder.json`, `meta.placeholder=true`) behind a "sample data" banner.

**Intended service URL (once deployed):** https://caltex-dash-516554645957.australia-southeast1.run.app
**Password (once created):** Secret Manager secret `caltex-dash-password`.

## Step 0 — reauth (blocking; interactive, human-only)

Both `ian@100.digital` and `charles@100.digital` gcloud tokens expired 2026-07-27 and ADC needs a
browser reauth, so nothing below runs until you do (in an interactive terminal):

```powershell
gcloud auth login ian@100.digital            # deploys need ian@ (charles@ has no deploy perms)
gcloud auth application-default login        # ADC for the python loaders/venv
```

## Step 1 — is Caltex's TTD data already flowing? (the key question)

Other 100% Digital clients (cityperfume/vmch/tlm/resetdata) get their Trade Desk data through the
**shared Windsor TTD connector** → `raw_windsor.perf_the_trade_desk` (loader
`ingest/windsor_data_pull/tradedesk/tradedesk_loader.py`, Windsor account **484** = the agency's
TTD seat). If the Caltex advertiser sits on the same seat, its rows may already be arriving:

```powershell
bq query --use_legacy_sql=false "
SELECT advertiser_id, advertiser_name, MIN(metric_date) first_day, MAX(metric_date) last_day,
       COUNT(*) n, ROUND(SUM(cost),2) cost, ANY_VALUE(currency) cur
FROM \`bidbrain-analytics.raw_windsor.perf_the_trade_desk\`
WHERE advertiser_id = '0lw3hp6' OR LOWER(advertiser_name) LIKE '%caltex%'
GROUP BY 1,2"
```

- **Rows found** → data is flowing; go to Step 2. (Check `last_day` is recent; if history is
  short, backfill: `.\.venv\Scripts\python.exe ingest\windsor_data_pull\tradedesk\tradedesk_loader.py 2026-07-01 <today>`.)
- **No rows** → the advertiser isn't granted to Windsor yet. A human must grant it at
  **https://onboard.windsor.ai?datasource=tradedesk** (add advertiser `0lw3hp6` / the Caltex seat),
  then read the new numeric account id from Windsor and **append it to `SELECT_ACCOUNTS`** in
  `ingest/windsor_data_pull/tradedesk/tradedesk_loader.py`, redeploy the ingest job
  (`scripts/deploy_ingest_jobs.ps1`) and run a backfill (command above). The loader's
  `CLIENT_TO_AGENCY` already maps `caltex → 100-digital` (added 2026-07-29).

Also sanity-check the ad-group parse once rows exist:

```powershell
bq query --use_legacy_sql=false "
SELECT ad_group_name, COUNT(*) n, SUM(impressions) imps
FROM \`bidbrain-analytics.raw_windsor.perf_the_trade_desk\`
WHERE advertiser_id='0lw3hp6' GROUP BY 1 ORDER BY imps DESC"
```
Expect the three `Tactic | QLD+WA` names. If TTD reports a different advertiser_id format, adjust
the filter in `sql/01_stg_ttd.sql`.

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
