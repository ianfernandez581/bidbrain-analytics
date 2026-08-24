# clients/client_hireright/ — HireRight (paid media) · **live**

> All of HireRight's paid media in one place. Built on the
> [`client_STT`](../client_STT/README.md) template, stripped to a pure paid-media **delivery** baseline:
> filter the shared raw layers down to HireRight's slice, model it in BigQuery views, export one JSON,
> serve it from a password-gated web app.

**Plain English:** HireRight runs paid media across three platforms — **DV360** (programmatic display),
**The Trade Desk** (programmatic air-cover) and **LinkedIn** (paid social). This is a delivery
dashboard: spend, impressions, clicks, outcomes and efficiency in one view. There is **no GA4 /
website side** (HireRight's GA4 property can't be identified). A **pacing lane exists but is dormant** —
`targets/media_plan.csv` is committed and wired end to end, and stays hidden until a signed plan is
seeded into it (see [`targets/README.md`](targets/README.md)).

**Agency: Transmission** (since 2026-08-24). All three feeds have always come off Transmission's
Snowflake share; HireRight was simply the one live dashboard sitting in no agency in the platform
registry, so Transmission's own login could not see it. Now attached — see "Portal access" below.

**Status:** 🟢 Deployed & live (password-gated). Stood up via
[`deploy_hireright.ps1`](deploy_hireright.ps1); verified serving HTTP 200 (login) and `/data.json`
(401-gated / 200-after-login) on **2026-06-04**. See [`dash/LIVE_URL.md`](dash/LIVE_URL.md).

> ⚠️ **DV360 has been frozen upstream since 2026-07-01.** Transmission's `DV360 - APAC` Snowflake feed
> has delivered nothing since then, with live campaigns still running; our mirror matches their source
> exactly, so this is genuinely their connector and cannot be fixed from our side (read-only roles).
> It also affects `stt` and `schneider`. The dashboard now **detects this itself** and prints a named
> warning rather than presenting two-month-old totals as current — see "Stalled-feed detection".

---

## The story it tells

Three live ad sources, folded into one delivery narrative. **Reporting currency is USD.**

| Source | Raw table (shared) | HireRight filter | Currency → USD | Geo |
|---|---|---|---|---|
| **DV360** programmatic display | `raw_snowflake.dv360_apac` | `LOWER(ADVERTISER_NAME) LIKE '%hireright%'` | already USD | **real country** (`COUNTRY_NAME`) |
| **The Trade Desk** programmatic | `raw_snowflake.tradedesk_apac_all` | `ADVERTISER_NAME = 'HireRight'` | AUD → USD @ `0.65` | `'Global'` (persona/TAL, no geo) |
| **LinkedIn** paid social | `raw_snowflake.linkedin_ads_apac` | `LOWER(ACCOUNT_NAME) LIKE 'hireright%'` | already USD (`_AUD` acct → @0.65) | `'Global'` (audience combined) |

There are **no** Google Ads / Reddit / Salesforce / GA4 views — HireRight has no rows in those sources.

Confirmed against the raw layer at build time (window **2025-10-25 → 2026-06-02**): DV360 ≈ **$14.9k** /
15 country markets, LinkedIn ≈ **$22.6k**, TradeDesk ≈ A$6.8k → **~$4.4k** — combined **~$42k** USD.

**FX:** the rate lives in exactly one place — **`sql/00_fx.sql`** (`aud_usd = 0.65`). Every AUD source
CROSS JOINs that single row, and `sql/05_kpi.sql` reads the value it *surfaces* as `fx_aud_usd` from the
same row, so the rate printed on screen can never disagree with the rate the spend was converted at. Only
TradeDesk is actually converted today. **The 0.65 is an unconfirmed placeholder** carried over from the
original brief — nobody has checked it against what HireRight is invoiced at. Confirm the basis (spot /
booked / month-average) with Transmission before this dashboard is used as a billing reference.

---

## The 2 dashboard tabs (`dash/dashboard.html`)

Three filters at the top:
- **Platform** — DV360 · TradeDesk · LinkedIn. Scopes the **Overview** figures. (Paid Media always shows
  all three for comparison.)
- **Campaign** — a searchable multi-select dropdown of every delivering campaign (grouped by platform,
  sorted by spend), **all selected by default**. Scopes ad delivery everywhere, summed client-side from
  the campaign-grained `ad_campaign*` views.
- **Market** — DV360 country names + `'Global'`, **all selected by default**. Scopes the **by-market**
  charts only (DV360 has real countries; TradeDesk + LinkedIn are `'Global'` air-cover).

1. **Overview** — KPI tiles (spend, impressions, clicks, blended CTR, CPM, CPC, **LinkedIn leads**,
   **attributed conversions** — the last two auto-hide when their platform isn't selected); the **pacing**
   card (hidden until a plan is seeded); a monthly hero (spend by platform stacked + clicks line); a
   spend-mix doughnut; **efficiency over time** (CTR / CPM / CPC per platform, Month/Week); spend-by-market;
   and **spend-by-region** (auto-hides when the data resolves to one region).
2. **Paid Media** — monthly delivery by platform; a spend-share doughnut; **cumulative spend** (the burn
   curve, per platform); **platform mix over time** (100% stacked, auto-hides below two platforms); a
   platform comparison table; DV360 spend & impressions by country; **campaign efficiency** (spend vs CTR
   bubble, sized by impressions, against a blended-CTR reference line); a top-campaigns-by-spend table;
   a LinkedIn creative-mix doughnut; and a LinkedIn engagement funnel (impressions → clicks → video views
   → VCR = completions ÷ starts → lead-form opens → leads).

**The two outcome measures are never added together.** "LinkedIn leads" are lead-gen form submissions;
"attributed conversions" are DV360 + TradeDesk post-click **and post-view** counts that are not
de-duplicated across the two platforms. Until 2026-08-24 these were summed into a single "Conversions"
tile captioned *"DV360 + TradeDesk + LinkedIn leads"* — see "What changed" below.

---

## How it works (3 stages — same shape as every client)

```
 (1) SOURCE → RAW (shared)             (2) RAW → VIEWS → JSON              (3) JSON → FRONTEND
 ───────────────────────              ─────────────────────               ──────────────────
 snowflake_data_pull fills             clients/client_hireright/sql/*.sql filter    hireright-dash (Cloud Run service)
 raw_snowflake.{dv360_apac,            HireRight's slice + roll it up;      shows a login page, then
 tradedesk_apac_all,                   hireright-export (Cloud Run JOB)     dashboard.html, which fetches
 linkedin_ads_apac}                    reads the views → writes             /data.json and draws the charts
                                       hireright.json to the private bucket
```

The job is read-only on BigQuery — it only `SELECT`s the views and writes JSON to GCS (no Snowflake creds).

| What to change | Edit | Stage |
|---|---|---|
| HireRight's filter | `sql/01_stg_dv360.sql` · `02_stg_linkedin.sql` · `03_stg_tradedesk.sql` | 2 |
| FX rate `0.65` | **`sql/00_fx.sql` only** (one row; every consumer joins it) | 2 |
| Media-plan targets / pacing | `targets/media_plan.csv` → `seed_static.py` (see `targets/README.md`) | 2 |
| Roll-ups / new metrics | the relevant `sql/*.sql` view | 2 |
| JSON shape | `job/main.py` (the `env = {...}` dict) | 2 |
| Charts / tabs / branding | `dash/dashboard.html` | 3 |
| Login / how JSON is served | `dash/main.py` (rarely) | 3 |

> **BigQuery note.** These run as BigQuery views. BigQuery has no `ILIKE` / `LIKE … ESCAPE`, so the
> brief's `ILIKE '%HireRight%'` is written `LOWER(col) LIKE '%hireright%'` and the LinkedIn `_AUD` guard
> as `ENDS_WITH(ACCOUNT_NAME, '_AUD')` (same intent, valid Standard SQL). See [`sql/README.md`](sql/README.md).

---

## Deploy / refresh (copy-paste, PowerShell)

Project `bidbrain-analytics`, region `australia-southeast1`. Use the repo `.venv`
(`.\.venv\Scripts\python.exe`). **First-time stand-up:** run [`deploy_hireright.ps1`](deploy_hireright.ps1)
once (idempotent — bucket, dataset, SAs, IAM, secrets, both Cloud Run units, the Cloud Scheduler trigger; it
prompts for the dashboard password, or set `$env:DASH_PASSWORD` first). The export **job is self-gating**
(see the Coordinates table). Note: `deploy_hireright.ps1` still seeds the scheduler at the legacy daily
`0 22 * * *` default — run [`scheduler.ps1`](scheduler.ps1) (default `*/10 * * * *`) to flip it to the
self-gating cadence. After that:

**① Refresh the data now** (the `hireright-export-daily` Cloud Scheduler runs `*/10` UTC, self-gating):
```powershell
# (optional) refresh the shared raw layer first if you want the very latest source data:
.\.venv\Scripts\python.exe snowflake_data_pull\loader.py
gcloud run jobs execute hireright-export --region australia-southeast1 --wait    # views -> hireright.json
```

**② You edited a view (`sql/*.sql`) or `targets/media_plan.csv`** — seed, apply, then force the job.
The easy way is [`sql/deploy_views_hireright.ps1`](sql/deploy_views_hireright.ps1), which does all three:
```powershell
.\clients\client_hireright\sql\deploy_views_hireright.ps1
```
By hand — **seeds first**, because `sql/18_targets` is a view over `seed_media_plan` and BigQuery
validates a view's query at CREATE time:
```powershell
.\.venv\Scripts\python.exe clients\client_hireright\seed_static.py
.\.venv\Scripts\python.exe clients\client_hireright\create_views.py
gcloud run jobs execute hireright-export --region australia-southeast1 `
  --update-env-vars FORCE_REBUILD=1 --wait
```
The **`FORCE_REBUILD=1` is required**: the freshness gate watches the three raw Snowflake tables, so a
view or seed change is invisible to it and would sit unpublished until the next upstream change.

**③ You edited `job/main.py`** (the JSON shape) — build, deploy, run:
```powershell
$IMG = "australia-southeast1-docker.pkg.dev/bidbrain-analytics/bidbrain/hireright-export:$(git rev-parse --short HEAD)"
gcloud builds submit clients/client_hireright/job --tag $IMG --region australia-southeast1
gcloud run jobs deploy hireright-export --image $IMG --region australia-southeast1 --service-account hireright-dash-job@bidbrain-analytics.iam.gserviceaccount.com --memory 1Gi
gcloud run jobs execute hireright-export --region australia-southeast1 --wait
```

**④ You edited `dash/dashboard.html` or `dash/main.py`** — build + redeploy the service:
```powershell
$IMG = "australia-southeast1-docker.pkg.dev/bidbrain-analytics/bidbrain/hireright-dash:$(git rev-parse --short HEAD)"
gcloud builds submit clients/client_hireright/dash --tag $IMG --region australia-southeast1
gcloud run services update hireright-dash --image $IMG --region australia-southeast1
```
The service goes live as soon as the new revision is ready; it reads whatever JSON is in the bucket.

> Don't use `gcloud builds submit --config cloudbuild.yaml` from a laptop — its deploy step fails on
> `iam.serviceaccounts.actAs`. Build the image, deploy as yourself (above). The `cloudbuild.yaml` files
> are for a future push-to-main trigger.

---

## Coordinates

| | |
|---|---|
| GCP project / region | `bidbrain-analytics` / `australia-southeast1` |
| BigQuery dataset | `client_hireright` (21 views + 1 seed table `seed_media_plan`) |
| Data bucket / object | `bidbrain-analytics-hireright-dash` / `hireright.json` |
| Export job | `hireright-export` (runtime SA `hireright-dash-job@…`, read-only BigQuery + bucket write) |
| Web service | `hireright-dash` → see [`dash/LIVE_URL.md`](dash/LIVE_URL.md) (runtime SA `hireright-dash-web@…`) |
| Secrets | `hireright-dash-password` · `hireright-dash-session-key` |
| Refresh | Cloud Scheduler `hireright-export-daily` — `*/10` UTC, **self-gating** (rebuilds within ~10 min of new upstream data; most ticks no-op) |
| Access path | via the platform front-door — `https://dashboards.bidbrain.ai/d/hireright/` (no per-client subdomain; see `dash/LIVE_URL.md`) |
| Agency | **Transmission** (attached 2026-08-24 via `bidbrain-platform/dash/set_hireright_tile.py`) |

## Portal access (Transmission)

HireRight was the only live dashboard in `config.UNASSIGNED_CLIENTS`, so it never appeared on any agency
portal. Two things were needed, because `config.py` only **seeds** the registry — the running site reads a
JSON blob in GCS:

1. **Code** (done): `hireright` added to `CLIENTS` and to the Transmission agency's client list in
   [`bidbrain-platform/dash/config.py`](../../bidbrain-platform/dash/config.py); `UNASSIGNED_CLIENTS` is now empty.
2. **Live registry** (needs running as `ian@100.digital`):
   ```powershell
   $env:CLOUDSDK_CORE_ACCOUNT="ian@100.digital"
   $env:GCS_BUCKET="bidbrain-analytics-platform-dash"
   .\.venv\Scripts\python.exe bidbrain-platform\dash\set_hireright_tile.py          # dry run
   .\.venv\Scripts\python.exe bidbrain-platform\dash\set_hireright_tile.py --yes    # write
   ```
   Then redeploy the platform: `bidbrain-platform/dash/deploy_dash_platform.ps1`.

> This grants the **Transmission agency login** sight of HireRight. It does not create a HireRight client
> login. Never hand the agency password to the client — it opens every other Transmission client
> (Cloudflare, MongoDB, Schneider ×3, PropTrack, STT). For HireRight's own people, set their dashboard
> password or grant their Google/Microsoft email in the super-admin console.

---

## Campaign status: CONCLUDED (verified 2026-08-24)

**All HireRight campaigns have finished.** Verified directly against the raw layer, and the
distinction that matters is between *our pipeline being broken* and *the campaign being over*:

| Platform | HireRight's last delivery | The feed's last row (any client) | Verdict |
|---|---|---|---|
| DV360 | 2026-01-30 | 2026-07-01 | Campaign ended **206 days ago** |
| Trade Desk | 2026-06-22 | 2026-08-22 | **Feed is live** - campaign ended 63 days ago |
| LinkedIn | 2026-04-17 | 2026-08-23 | **Feed is live** - campaign ended 129 days ago |

Trade Desk and LinkedIn are both delivering current data for other clients, so nothing is broken -
HireRight simply stopped running. **The separate `DV360 - APAC` outage (frozen 2026-07-01) is
irrelevant to this client**: HireRight's DV360 line ended five months before that freeze. It still
affects `stt` and `schneider`; it does not affect anything on this dashboard.

Final figures: **US$41,994** across 28 campaigns, 2,329,328 impressions, 2,941 clicks, 62 Trade Desk
attributed conversions, 0 LinkedIn leads. Reconciles to Snowflake with **zero delta** on all 12
status-pipeline accuracy checks.

## Stalled-feed detection

The three feeds do not run concurrently and one can stop arriving while the others keep updating. When
that happens every whole-flight total still **includes** the stalled platform's historical delivery, so
the page looks healthy and stale numbers read as current. `stalledFeeds()` in `dash/dashboard.html`
compares each platform's last delivery day against the most recent day seen anywhere in the payload and
names any platform more than **14 days** behind, with the date and the gap, in an amber block on the
Overview note. It is computed from the payload rather than hardcoding any particular outage, so it
will catch the next one too. The export job prints the same three windows in its log every run.

**CONCLUDED beats STALLED.** If nothing has delivered on *any* platform for over 30 days
(`CONCLUDED_DAYS`), the campaign is finished and the dashboard says so plainly - "This campaign has
concluded, these are final figures" - in a neutral panel. It does **not** show the amber
"a feed has stopped updating / check with your agency" warning, which would be both wrong and
alarming on a completed campaign. That is HireRight's current state. The stall warning is reserved
for the genuine case: one platform falling behind while the others are still reporting.

---

## What changed on 2026-08-24

A correctness + build-out pass, ahead of handing the dashboard to Transmission:

- **The blended "Conversions" KPI is gone.** It summed DV360 Floodlight + TradeDesk click+view +
  LinkedIn LEADS — three different definitions — into one tile captioned *"DV360 + TradeDesk + LinkedIn
  leads"*. Post-view display conversions are not submitted lead forms, and the DV360/TTD tags are not
  de-duplicated against each other. Now two labelled measures: `li_leads` and `ad_attr_conv`. The
  status-pipeline check that verified the blend was split the same way.
- **Campaign names are normalised** (`brief` prefix stripped into its own column) — the repo-wide
  "campaign names are NOT stable keys" rule. Without it, the day Transmission prefixes a HireRight
  campaign every per-campaign aggregate silently splits in half.
- **FX lives in one place** (`sql/00_fx.sql`) instead of the literal `0.65` typed into four files.
- **Real geo.** Full ISO country map + a `region` rollup, replacing a map that folded five European
  countries into one "Europe" market while leaving every other country individual.
- **`sql/17_scope_audit`** makes the three name-based source filters legible, logged every run, with a
  WARNING when a source matches more than one entity (a silent scope widening pushes numbers *up*, which
  reads as performance rather than as a bug).
- **The job refuses to publish an empty fact** (the `client_caltex` pattern) — a broken filter now fails
  the run and leaves the last good JSON in place, instead of overwriting it with an all-zero dashboard.
- **Pacing wired end to end but dormant** (`targets/`), plus five new charts and the stalled-feed warning.

**Still open — needs Transmission / the client:** the signed media plan (`targets/README.md` lists the
three questions), confirmation of the FX basis, the DV360 feed outage, and whether a GA4 property exists.

---

## Files

- [`sql/`](sql/README.md) — the 21 BigQuery views (filter + model); `create_views.py` applies them.
- [`targets/`](targets/README.md) — the committed media-plan CSV that drives pacing (**currently empty**);
  `seed_static.py` loads it. **Run it before `create_views.py`** — `sql/18_targets` is a view over the seed.
- [`job/`](job/README.md) — the export job (stage 2): views → `hireright.json`.
- [`dash/`](dash/README.md) — the web app (stage 3): password gate + `dashboard.html`.
- [`INTAKE.md`](INTAKE.md) — the resolved build slice (filters, currency, platforms).

## See also

- [Root README](../../README.md) — platform map, security model, naming, add-a-client playbook.
- [`../client_STT/`](../client_STT/README.md) — the template this follows (the GA4 half stripped out).
- [`../snowflake_data_pull/`](../../ingest/snowflake_data_pull/README.md) — where the three HireRight raw layers come from.
