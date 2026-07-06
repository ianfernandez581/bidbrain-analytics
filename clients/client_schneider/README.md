# clients/client_schneider/ — Schneider Electric **Pacific** · **live (deployed 2026-06-04)**

> **Dashboard branded "Pacific"** (a sibling Schneider Electric dashboard for another SE region is
> planned, so this one is explicitly the Pacific book). The underlying programme is still Schneider's
> APAC Content Syndication, scoped to the Pacific markets / 5 lead-gen programs.
>
> Schneider Electric's APAC **Content Syndication** programme (run via the agency **Transmission**) —
> a [`client_mongodb`](../client_mongodb/README.md)-style dashboard scoped to the **5 Salesforce
> lead-gen programs**. Filter the shared raw layers to SE's slice, model it in BigQuery views, export
> one JSON, serve it from a password-gated web app. Reporting currency **AUD**.

**Plain English:** Schneider runs lead-gen ("content syndication") for 5 programs — **Water &
Environment, EBA, Heavy Industries, Global Rebrand, AirSeT** — backed by 9 Salesforce campaigns. This
dashboard (modelled on MongoDB's) shows, per program: live **Salesforce leads vs the media-plan MQL+HQL
target** (Content Syndication tab), the **DV360 / Trade Desk / LinkedIn paid delivery** behind them
(Paid Media tab), and a **market-vs-market comparison** (CS Comparison tab).

**Status:** 🟢 **Live on GCP.** Restructured **2026-06-22** into a **3-tab mongodb clone** (Paid Media ·
Content Syndication · CS Comparison) **scoped to the 5 lead-gen programs** — the earlier 6-tab Pacific
paid-media dashboard is superseded. 28 BigQuery views + 7 CSV-loaded `seed_*` tables; `schneider.json`,
the `schneider-export` job and `schneider-dash` service deployed; the `*/10` self-gating scheduler runs.
Salesforce leads are **CRM-raw** (all status `New` — the CRM hasn't graded MQL/SQL/HQL yet), so the CS
tab shows total leads vs target, not "MQLs achieved". Targets/CPL come from the media plan
(`data/media_plan.csv`, version-controlled — the committed-CSV→BQ targets standard); see
[`INTAKE.md`](INTAKE.md) for the client-flagged discrepancies (EBA MQL 157
vs old 300, W&E/Heavy/EBA budgets, NEL added).

**Update 2026-07-02** (dash rev `schneider-dash-00021`): (0) the campaign dropdown now leads with an
**"All campaigns" portfolio view** (a synthesized pseudo-campaign summing all 5 across the Paid Media,
Content Syndication and CS Comparison tabs — helpers use an `inCamp()` match-all predicate; the "Other
Channels" tab stays per-campaign), and the dashboard **defaults to it** (`activeCampaign = ALL_ID` on
boot; flip back to a single default by restoring `cs[0].id`). (1) the **Campaign selector moved to a
dropdown in the top nav bar** (Cloudflare pattern), off the control-bar filter row. (2) **Region simplified to
Australia + New Zealand** — the ANZ and Other chips are gone. (3) **EBA (EcoStruxure Building Activate)
paid media now renders**: its Trade Desk delivery (5.2M imps / A$6.3k) was always in BigQuery but the
region was parsed only from the campaign name, so it fell into the "Other" bucket (`SE_EBA_Activate_AWR_June4`
has no country in the campaign name — the AU/NZ split lives in the ad-group names). `sql/03_stg_tradedesk.sql`
now reads the country from `AD_GROUP_NAME` first, splitting EBA into Australia (A$5.0k) + New Zealand (A$1.3k);
AirSeT's Trade Desk resolves the same way. The **Heavy Industries trade-publication** thought-leadership line
was already in the plan and renders under **Heavy → Other Channels** (a plan-only line — a publisher
sponsorship has no ad-platform feed, so only its plan targets show).

**Update 2026-07-03** (`dash/dashboard.html` + `dash/report.py`; needs a `schneider-dash` redeploy to go live):
(1) the deck **cover/eyebrow brand** now reads **"TRANSMISSION × Schneider Electric Pacific"** (was "…Schneider
Electric" — `BB_THEME.brand`); every other surface already said "Schneider Electric Pacific". (2) **Spend vs budget**
(client ask, from Gabby): the **Paid Media** tab has a new **"Spend vs budget"** card — measured DV360/TTD/LinkedIn
spend vs the planned media-plan **paid-media budget**, plus a time-to-date (elapsed-flight pro-rata) pace. It is
**whole-flight / all-markets** (independent of the region + date filters, which the plan budget isn't split by), so
label it as such. The **Content Syndication** tab's leads-vs-target note now also shows **≈ est. spend (delivered
leads × plan CPL) of the committed CS budget**. All budget maths is **client-side** from the already-emitted
`campaigns[].channels[]` (`spend` + `group`) + `committed_spend` — **no job / view / seed change** (verified: All-
campaigns paid budget A$163,441, CS committed A$97,288, total A$270,729 = Σ `plan_budget.budget_aud`). The deck
payload gains a `plan.budget` block (`paid` / `paid_spend` / `paid_ttd` / `cs_committed` / `cs_est_spend` / `total`),
and `report.py`'s per-client guardrail now tells the model to surface an explicit spent-vs-budgeted **budget** KPI
(paid = measured, CS = estimated / per-lead, kept distinct).

## Data model (mongodb concept → Schneider source)
- **Campaign** (**top-nav dropdown** in the nav bar — the Cloudflare `dash-select` pattern) = the 5
  programs (`water_env` · `eba` · `heavy` · `global_rebrand` · `airset`).
- **Programme** (the CS breakdown) = the Salesforce `pillar_label` (9), from `seed_salesforce_map`.
- **Market / Region chips** = **Australia / New Zealand only** (no ANZ, no Other). CS leads are
  AU/NZ-native; paid delivery's AU/NZ split is resolved from **`AD_GROUP_NAME`** (then `CAMPAIGN_NAME`)
  in `sql/03_stg_tradedesk.sql` — several ANZ-level campaigns (EBA `SE_EBA_Activate_AWR_June4`, AirSeT
  `SE AirSeT_ANZ_HighImpact…`) carry the country only in the ad-group name, so the old campaign-name-only
  parse stranded that delivery (notably **all of EBA's Trade Desk** — 5.2M imps) in an Unmapped/Other
  bucket. `sql/20_pm_delivery.sql` folds any tiny unsplittable combined-ANZ residual (e.g. AirSeT's
  `RM AirSeT – Retargeting – ANZ` LinkedIn line, ~$500) into **Australia** so it stays in the paid totals.
- **Target** (per campaign) = Σ MQL+HQL `lead_target` from `seed_media_plan`; **Plan CPL tiers** = each
  lead line's spend ÷ lead_target; **committed spend** = Σ lead-line spend; **flight** from `seed_plan_budget`.
- **Scoped to the 5:** `pm_delivery` (`sql/20`) is `WHERE program IN (the 5)`; the CS views read only the
  9 SF ids via `seed_salesforce_map`. The old Pacific `portfolio` toggle and the other ~20 APAC programs
  are **gone from the dashboard** — the seed tables still carry them for the `match_pattern` tagging.
  (Historical Pacific-carve-out EDA: [`_eda/pacific_eda.md`](_eda/pacific_eda.md).)

---

## What's different from STT (the archetype)
- **It's a [`client_mongodb`](../client_mongodb/) clone, not the STT layout** — 3 tabs, a single-select
  Campaign control, Region chips + a date picker, scoped to the 5 lead-gen programs (Schneider skin —
  the mongodb *layout*, Schneider's green/dark theme + logo).
- **Three ad platforms** (DV360 + TradeDesk + LinkedIn), AUD (USD→AUD @1.50, SGD→AUD @1.15 placeholders;
  LinkedIn currency inferred from the `_USD`/`_AUD`/`_SGD` account suffix). **No GA4 website tab** in the
  clone (the `40–46 ga4_*` views still apply but are unused by the job).
- **Salesforce Content Syndication is the focus**: `stg_salesforce` + `cs_by_programme` / `cs_weekly`
  (`sql/17–19`) read SE's 9 SF campaigns via `seed_salesforce_map`; `pm_delivery` (`sql/20`) tags paid
  delivery to its program via the `match_pattern` join (replicating the old client-side `idOf` in SQL,
  first-match-wins by `seq`), scoped to the 5.
- **Seeds are CSV-loaded** via [`load_seeds.py`](load_seeds.py) into `seed_*` tables. The media-plan
  **targets** (`media_plan` / `targets` / `plan_budget`) **and `campaign_map`** (campaign display names +
  match_patterns) live in [`data/`](data/), version-controlled via `.gitignore` `!` exceptions; the
  remaining dimension seeds also read from `data/` (gitignored / BQ-only — see *Updating targets*).

## The dashboard tabs (`dash/dashboard.html`) — a global **Executive Scorecard** + **per-campaign** tabs
**Executive Scorecard** (default tab, added 2026-07-06) is **global / portfolio-wide** — it spans all 5
programs (region-filterable; the Campaign dropdown is hidden here) and reframes the dashboard from lead
*volume* to lead *quality*, per the deep-research finding that senior B2B marketers value quality/pacing
over raw counts. It shows: portfolio KPIs (leads vs target, pace vs plan, **accounts reached**, blended
plan CPL); **program × Schneider-strategy-pillar** pace cards (each program tagged with the corporate
pillar it advances — Advancing Energy Technology / EcoStruxure Buildings / AirSeT SF6-free / Water &
Environment / Heavy Industries); a **job-function** doughnut + **seniority** bar; and a **top-accounts**
(ABM) list. All from `21_cs_audience` (account / function / seniority from the Salesforce feed's
`COMPANY_NAME`/`JOB_FUNCTION`/`JOB_LEVEL` — verified 100%/100%/~40% populated; industry/asset/state/revenue
are empty for SE so are intentionally not shown). `renderScorecard()` in `dashboard.html`.

The remaining tabs are **per-campaign**. Filters: **Campaign** (the 5 programs) is a **dropdown in the top nav bar** (Cloudflare pattern); the
**Region** chips (Australia / New Zealand) + **Date range** stay on the control bar under the tabs.
**The tab bar adapts to the selected campaign** — each campaign shows only the channels it actually
uses. The job derives `campaigns[].tabs` from that campaign's media-plan channels
([`data/media_plan.csv`](data/media_plan.csv) `channel` column, bucketed by `chan_group`):
**Paid Media** (a Programmatic/LinkedIn line, or real `pm_delivery`), **Content Syndication** (a
lead-gen line, or real leads), **CS Comparison** (only when the campaign has leads), and **Other
Channels** (plan-only lines with no warehouse feed — Search, publisher sponsorships, trade press,
email — shown as plan targets + a "Plan only · no feed" badge). Live result: `eba`/`water_env` →
Paid·CS·Compare; `airset` → Paid·CS; `heavy` → Paid·CS·Compare·Other(Trade Publication);
`global_rebrand` (Advancing Energy Technology) → Paid·Other(Search + Capital Brief/Energy Magazine/
Innovation Aus). Default campaign = the one with most leads (EBA today); default tab = its first tab.
The tab bar is built in `renderControls()`; switching campaign resets to a valid tab (`setCampaign`).

1. **Paid Media** — for the selected program: KPI snapshot (spend / imps / clicks / blended CPC), a
   **platform comparison** table (DV360 / TTD / LinkedIn), a daily delivery chart (Month/Week/Day +
   Relative/Absolute toggles), spend-by-platform + spend-by-market, a market table, and the **Flight
   windows across the portfolio** Gantt. Heavy / Global Rebrand have no paid delivery yet (leads-only) —
   the tab says so rather than showing zeros.
2. **Content Syndication** — Salesforce leads vs the media-plan **MQL+HQL** target: the snapshot strip
   (Overall / Pacing / Delivery / Outlook), the **Plan-CPL** banner, **Leads-vs-target** + **Progress**
   panels, a **Weekly pacing** chart (real dated weekly leads vs the even target pace), **Leads-by-market**
   + **Leads-by-programme** doughnuts, a by-market summary, and a programme × market table. Leads are
   **CRM-raw** (`New`) — total leads vs target, not "MQLs achieved".
3. **CS Comparison** — pick two markets (e.g. Australia vs New Zealand) for the selected program and
   compare lead volume, share, programme mix and weekly pacing side by side.

## How it works (3 stages — same shape as every client)
```
 (1) SOURCE → RAW (shared)              (2) RAW → VIEWS → JSON              (3) JSON → FRONTEND
 snowflake_data_pull fills              clients/client_schneider/sql/*.sql filter   schneider-dash (Cloud Run service)
 raw_snowflake.{dv360_apac,             SE's slice + roll it up + seeds;    shows a login page, then
 tradedesk_apac_all, linkedin_ads_apac} schneider-export (Cloud Run JOB)    dashboard.html, which fetches
 (google_analytics_apac_all when GA4 on) reads views → schneider.json       /data.json and draws the charts
```
Read-only on BigQuery (it only SELECTs views + writes JSON). No `src_*` landing, no bootstrap failure.

| What to change | Edit | Stage |
|---|---|---|
| SE filter / FX rate | `sql/01_stg_dv360.sql` · `02_stg_linkedin.sql` · `03_stg_tradedesk.sql` (+ `05_kpi.sql`) | 2 |
| Media-plan **targets** (media_plan / targets / plan_budget) + **campaign_map** (display names / match_patterns) | `data/*.csv` (version-controlled — tracked via `.gitignore` `!` exceptions) → re-run `load_seeds.py` | 2 |
| Other seeds (plan_flighting / channel_split / salesforce_map) | `data/*.csv` → `load_seeds.py` (NB: currently BQ-only, no committed CSV) | 2 |
| CS + paid views (`stg_salesforce` / `cs_by_programme` / `cs_weekly` / `pm_delivery`) | `sql/17–20_*.sql` | 2 |
| Which 5 programs are in scope | `data/salesforce_map.csv` (the 9 SF ids) + the `CS_PROGRAMS` list in `job/main.py` + `WHERE program IN (…)` in `sql/20_pm_delivery.sql` | 2 |
| JSON shape | `job/main.py` (the `env = {...}` dict) | 2 |
| Charts / tabs / branding | `dash/dashboard.html` | 3 |
| Login / how JSON is served | `dash/main.py` (rarely) | 3 |

### Updating targets (committed CSV → BQ)

The media-plan **targets** are the version-controlled source of truth in [`data/`](data/)
(`media_plan.csv`, `targets.csv`, `plan_budget.csv`, `campaign_map.csv`). `data/` is gitignored
repo-wide (`clients/*/data/*`), so those four files are **kept tracked by explicit `!` exceptions in
the root `.gitignore`** — edit them freely and they travel with the repo (other clients keep their
tracked targets in a separate `targets/` dir; schneider consolidated everything into `data/`). To
change a target: edit the CSV → `.\.venv\Scripts\python.exe clients\client_schneider\load_seeds.py`
(all seeds now load from `data/`) → run the export job with `FORCE_REBUILD=1`. The remaining seeds
(plan_flighting / channel_split / salesforce_map) stay **gitignored / BQ-only** (no committed CSV);
add matching `.gitignore` `!` exceptions if you want schneider fully repo-reproducible.

## Deploy / refresh (copy-paste, PowerShell)
Project `bidbrain-analytics`, region `australia-southeast1`. **First-time stand-up:** run
[`deploy_schneider.ps1`](deploy_schneider.ps1) once (idempotent — bucket, dataset, SAs, IAM, secrets,
both Cloud Run units, scheduler; its step [5/7] now loads the seed CSVs before applying the views).
Note `deploy_schneider.ps1` seeds the scheduler at a fixed daily cron; [`scheduler.ps1`](scheduler.ps1)
flips it to the binding `*/10` self-gating cadence (the live schedule). **Prefer the per-stage scripts**
— [`deploy_seeds_schneider.ps1`](deploy_seeds_schneider.ps1) (edited `data/*.csv`),
[`sql/deploy_views_schneider.ps1`](sql/deploy_views_schneider.ps1) (edited a view — loads seeds first),
[`job/deploy_job_schneider.ps1`](job/deploy_job_schneider.ps1) (edited `job/main.py`),
[`dash/deploy_dash_schneider.ps1`](dash/deploy_dash_schneider.ps1) (edited the dashboard). The raw
commands each wraps:

```powershell
# ⓪ edited a seed CSV (data/*.csv) — reload the seed_* tables, then re-run the job (FORCE_REBUILD,
#    because seeds are NOT an upstream the freshness gate watches). load_seeds.py runs BEFORE views.
.\.venv\Scripts\python.exe clients\client_schneider\load_seeds.py
gcloud run jobs execute schneider-export --region australia-southeast1 --update-env-vars FORCE_REBUILD=1 --wait

# ① refresh data now (scheduler schneider-export-daily runs */10 UTC, self-gating)
.\.venv\Scripts\python.exe ingest\snowflake_data_pull\loader.py     # optional: refresh shared raw layer
gcloud run jobs execute schneider-export --region australia-southeast1 --wait

# ② edited a view (sql/*.sql) — load seeds (stg_salesforce needs seed_salesforce_map), apply, re-run
.\.venv\Scripts\python.exe clients\client_schneider\load_seeds.py
.\.venv\Scripts\python.exe clients\client_schneider\create_views.py
gcloud run jobs execute schneider-export --region australia-southeast1 --update-env-vars FORCE_REBUILD=1 --wait

# ③ edited job/main.py (JSON shape) — build, deploy, run
$IMG = "australia-southeast1-docker.pkg.dev/bidbrain-analytics/bidbrain/schneider-export:$(git rev-parse --short HEAD)"
gcloud builds submit clients/client_schneider/job --tag $IMG --region australia-southeast1
gcloud run jobs deploy schneider-export --image $IMG --region australia-southeast1 --service-account schneider-dash-job@bidbrain-analytics.iam.gserviceaccount.com --memory 1Gi
gcloud run jobs execute schneider-export --region australia-southeast1 --wait

# ④ edited dash/dashboard.html or dash/main.py — build + redeploy the service
$IMG = "australia-southeast1-docker.pkg.dev/bidbrain-analytics/bidbrain/schneider-dash:$(git rev-parse --short HEAD)"
gcloud builds submit clients/client_schneider/dash --tag $IMG --region australia-southeast1
gcloud run services update schneider-dash --image $IMG --region australia-southeast1
```
> Don't use `gcloud builds submit --config cloudbuild.yaml` from a laptop — its deploy step fails on
> `iam.serviceaccounts.actAs`. Build the image, deploy as yourself (above). The `cloudbuild.yaml`
> files are for a future push-to-main trigger.

## Coordinates
| | |
|---|---|
| GCP project / region | `bidbrain-analytics` / `australia-southeast1` |
| BigQuery dataset | `client_schneider` (28 views + 7 CSV-loaded `seed_*` tables) |
| Data bucket / object | `bidbrain-analytics-schneider-dash` / `schneider.json` |
| Export job | `schneider-export` (runtime SA `schneider-dash-job@…`, read-only BigQuery + bucket write) |
| Web service | `schneider-dash` (runtime SA `schneider-dash-web@…`) → see [`dash/LIVE_URL.md`](dash/LIVE_URL.md) |
| Secrets | `schneider-dash-password` · `schneider-dash-session-key` |
| Refresh | Cloud Scheduler `schneider-export-daily` — `*/10` UTC, **self-gating** (rebuilds within ~10 min of new upstream data; most ticks no-op) |
| Access path | via the platform front-door — `https://dashboards.bidbrain.ai/d/schneider/` (no per-client subdomain) |

## Files
- [`DASHBOARD_GUIDE.md`](DASHBOARD_GUIDE.md) — **comprehensive client-facing guide** (built from the
  client's `raw_files/` + live BigQuery): what every tab/card/number is and how it's computed, the
  campaign-ID reconciliation, and a **client-vs-dashboard gap list** (incl. the live AirSeT lead-ID
  mismatch). Written for a client review / chatbot Q&A. Start here for "how does this dashboard work".
- [`data/`](data/) — the human-editable seed CSVs (campaign map / budgets / targets / flighting /
  channel split / media plan / salesforce map), loaded to `seed_*` tables by [`load_seeds.py`](load_seeds.py).
- [`sql/`](sql/README.md) — the 28 BigQuery views (filter + CS leads + paid delivery + `cs_audience` + unused GA4).
- [`job/`](job/README.md) — the export job (stage 2): views + seed tables → `schneider.json`.
- [`dash/`](dash/README.md) — the web app (stage 3): password gate + `dashboard.html`.
- [`INTAKE.md`](INTAKE.md) — the resolved data slice + open items handed to the client.

## See also
- [Root README](../../README.md) · the [`client_STT`](../client_STT/README.md) archetype · [`snowflake_data_pull`](../../ingest/snowflake_data_pull/README.md).
