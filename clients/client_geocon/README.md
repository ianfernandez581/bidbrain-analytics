# client_geocon — Gateway Braddon (Meta paid media)

Self-hosted paid-media dashboard for **Geocon's Gateway Braddon** residential launch.
**Single channel** (Meta — Facebook + Instagram), **single local market** (Canberra / ACT),
**lead generation** (Meta-reported enquiries). Scaffolded from the `client_mongodb` template
but it is a leaner, Meta-only client — there is **no Snowflake / Trade Desk / Salesforce /
Content-Syndication lane** here (ignore those if you spot leftover template references).

## The 3 stages (data contract — matched BY NAME across the three files)

```
 raw_windsor.perf_meta            client_geocon/sql/*.sql        job/main.py            dash/dashboard.html
 (Windsor Meta connector,    →    views filter + roll up    →    reads views,      →    fetches /data.json,
  self-refreshing; shared)        Geocon's campaigns             writes geocon.json     draws the charts
                                   (the stage-2 transform)        (env={...} dict)       (all UI lives here)
        │                                  │                            │                        │
   (no stage-1 loader here)         geocon-export JOB (stage 2)                       geocon-dash SERVICE (3)
```

A value on screen traces `sql view column → job/main.py env key → dashboard.html data.* key`.
Renaming a key in one stage breaks the next — fix all three.

| I want to change… | Edit | Stage |
|---|---|---|
| Geocon's campaign filter / funnel-stage mapping | `sql/01_stg_meta.sql` etc. | 2 |
| Lead / CPL / CTR / budget **targets** | `targets/targets.csv` · `targets/budget.csv` → `seed_static.py` → export `FORCE_REBUILD=1` | 2 |
| Shape/keys of the JSON the frontend gets | `job/main.py` (`env = {...}`) | 2 |
| Charts, tabs, layout, colours, the AI report deck | `dash/dashboard.html` | 3 |
| Login / how the JSON + `/report` are served | `dash/main.py` | 3 |

## The dashboard (`dash/dashboard.html`)

One file, three **audience views** (top toggle): **Executive · Media Buyer · Client Story**.
Heritage-maroon theme; KPIs, budget pacing, funnel health, per-stage spend/leads, fatigue watch,
creative tables, and a retargeting-pool read.

- **Performance-over-time chart** carries the repo-standard **View by Month/Week/Day** grain +
  **Relative/Absolute axis** toggles (default Relative — lines indexed to peak=100 on a shared
  0–100 axis; tooltips always show true values). Additive metrics are summed per bucket; ratios
  (CTR/CPM/CPL) are recomputed from the summed components, never averaged.
- **AI "Download report"** (top-right of the control dock) → a board-ready **3-slide deck**
  (What happened · Why · Recommended actions) previewed on-screen, plus a **Download Google
  Slides** button that builds a 4-slide editable `.pptx` client-side (PptxGenJS). The KPI figures
  come VERBATIM from the live numbers; the model writes only the narrative. See below.

## AI report (`dash/report.py` + `/report` in `dash/main.py`)

Two-stage Claude Opus 4.8 call — **Stage A** web-grounded analyst notes (web_search/web_fetch),
**Stage B** strict-schema slide JSON — re-templated for **Meta paid-social lead-gen**: single
engine, funnel-stage framing (Awareness → Consideration → Conversion → Retargeting), honest
"Meta-reported enquiries" labelling (not CRM-qualified), the `area` taxonomy
(`reach/traffic/leads/efficiency/budget` · `creative/audience/budget_pacing/landing_page/funnel`),
and the no-PII / anti-injection / numbers-are-ground-truth guardrails. If Claude rate-limits / runs
out of credits, it **falls back to Gemini** (`gemini-2.5-pro`) so a report still comes back.

- The browser POSTs the **whole-account** numbers (independent of the on-screen stage/search
  filter), so the deck is stable and the report is **cached per data refresh**
  (`gs://…-geocon-dash/reports/…`, keyed by `client + data_through`) — regenerates at most once
  per data advance; re-downloads are instant.
- **One-time standup** (provisions IAM + mounts the keys + bumps the 900s timeout):
  `dash/enable_report_geocon.ps1` (resolves the Claude key from `-Key` / `$env:ANTHROPIC_API_KEY`
  / `bidbrain-vault\anthropic-api-key.txt`; Gemini key optional). Both `anthropic-api-key` and
  `gemini-api-key` are shared project secrets (already created for mongodb). After standup, normal
  image redeploys keep the mounts.

## Deploy (PowerShell; project `bidbrain-analytics`, region `australia-southeast1`)

Build the image, deploy as yourself — **do not** `gcloud builds submit --config cloudbuild.yaml`
from a laptop (its deploy step fails `iam.serviceaccounts.actAs`). The per-stage scripts wrap the
commands below:

```powershell
# edited dash/dashboard.html, dash/main.py, or dash/report.py → rebuild + swap the SERVICE:
.\clients\client_geocon\dash\deploy_dash_geocon.ps1

# edited a sql/*.sql view → reapply views + re-run the JOB (FORCE_REBUILD bypasses the freshness gate):
.\.venv\Scripts\python.exe clients\client_geocon\create_views.py
gcloud run jobs execute geocon-export --region australia-southeast1 --update-env-vars FORCE_REBUILD=1 --wait

# edited job/main.py (the JSON shape) → rebuild + deploy + run the JOB:
.\clients\client_geocon\job\deploy_job_geocon.ps1   # or the raw commands in the repo CLAUDE.md
```

The service serves `dashboard.html` with `Cache-Control: no-store`, so a redeploy is live
immediately; it always reads whatever `geocon.json` is currently in the bucket.

## Freshness

`geocon-export` is **self-gating** on a Cloud Scheduler `*/10` UTC tick (`scheduler.ps1`): each tick
cheaply probes whether `raw_windsor.perf_meta` advanced (`__TABLES__.last_modified` vs the
`_freshness.json` watermark) and rebuilds only when it did — so the dashboard refreshes within
~10 min of new Meta data. Static re-seeds (targets/budget) don't move the gate, so force them:
`gcloud run jobs execute geocon-export --region australia-southeast1 --update-env-vars FORCE_REBUILD=1 --wait`.

## Coordinates

| | |
|---|---|
| GCP project / region | `bidbrain-analytics` / `australia-southeast1` |
| Raw source | `raw_windsor.perf_meta` (shared Windsor connector — no stage-1 loader here) |
| Dataset | `client_geocon` |
| Job / Service | `geocon-export` / `geocon-dash` |
| Data bucket / file | `bidbrain-analytics-geocon-dash` / `geocon.json` (report cache in `reports/`) |
| Dash runtime SA | `geocon-dash-web@bidbrain-analytics.iam.gserviceaccount.com` |
| Report secrets | `anthropic-api-key` (required) · `gemini-api-key` (optional fallback) |

## See also

- [Root CLAUDE.md](../../CLAUDE.md) — canonical agent fast-path: fixed facts, deploy commands, freshness contract.
- [`dash/`](dash/README.md) · [`job/`](job/README.md) · [`sql/`](sql/README.md) — per-stage detail.
