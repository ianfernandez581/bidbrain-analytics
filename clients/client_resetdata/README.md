# clients/client_resetdata/ — ResetData (Australia) · B2B sovereign-AI / data-centre

> The effect of paid media on the ResetData website: spend → traffic → engagement → leads / key
> events. Built on the [`client_STT`](../client_STT/README.md) archetype (the lean "ads → website
> traffic" pattern that reads straight from the shared raw layers, no Snowflake final-model step).
> **ResetData tells the same B2B story as STT — NOT the e-commerce shape:** there is no
> revenue / ROAS / AOV / transactions. Conversions here are leads / form-fills / key events.

**Plain English:** ResetData is an Australian sovereign-AI / data-centre infrastructure brand, run
by the agency **100 Digital**. It advertises on **Google Ads** (paid search), **Meta** (paid social),
**The Trade Desk** (programmatic display) and **Reddit** (community awareness / traffic). This
dashboard puts that ad spend next to what happened on the ResetData **website** (Google Analytics 4) —
sessions, engagement, and the demand-gen key events (lead form, sign-up, $50-credit click, file downloads).

**Reporting currency: AUD.** Status: built 2026-06-08; see [`dash/LIVE_URL.md`](dash/LIVE_URL.md).

---

## What's different from `client_STT` (the deltas)

| | STT | **ResetData** |
|---|---|---|
| Platforms | Google Ads · LinkedIn · DV360 | **Google Ads · Meta · The Trade Desk · Reddit** |
| Source datasets | all `raw_snowflake` | **three layers**: `raw_google_ads` · `raw_windsor` · `raw_ga4` |
| GA4 source | Snowflake event-grain (reconstructed) | **`raw_ga4.perf_ga4`** — already Traffic-Acquisition grain → `stg_ga4` is a plain filter |
| Currency | SGD (FX_USD_SGD=1.34) | **AUD** (FX_USD_AUD=1.50, TTD only) |
| Geography | 9 APAC markets + Country filter | **AU-only — no Country filter** |
| Conversions | GA4 key events | GA4 key events **+ platform-reported** (Google solid, Meta sparse, TTD none) |

## The six sources (three raw datasets) + the exact slice filters

| Source | Raw table | ResetData filter | Currency | Contributes |
|---|---|---|---|---|
| **Google Ads** (paid search) | `raw_google_ads.perf_google_ads` | `account_name = 'Reset Data'` | AUD | imps / clicks / **spend (already AUD — not micros)** / conversions (83) |
| **Meta** (paid social) | `raw_windsor.perf_meta` | `account_name = 'Reset backup – Ad account'` (**en-dash –**) | AUD | imps / clicks / spend / **leads** (the "Signup Button" custom pixel conversion) / creative mix |
| **The Trade Desk** (display) | `raw_windsor.perf_the_trade_desk` | `advertiser_name = 'ResetData'` | **USD → AUD ×1.50** | imps / clicks / spend |
| **Reddit** (community awareness / traffic) | `raw_windsor.perf_reddit` | `client_slug = 'resetdata'` | AUD (native) | imps / clicks / spend / **page visits** / sign-up+lead conversions (sparse) |
| **GA4** (the outcome) | `raw_ga4.perf_ga4` | `client_slug = 'reset-data'` | — | sessions / users / engagement / channels / conversions |
| **GA4 events** | `raw_ga4.perf_ga4_events` | `client_slug = 'reset-data'` | — | key events by name (leads / sign-ups / …) |

> **Slug split (important):** Google Ads + GA4 tag the client `reset-data` (hyphen); Meta + TTD + Reddit
> tag it `resetdata` (no hyphen). Each `stg_*` view filters by the **stable per-table key** above
> (account / advertiser name, or `client_slug` for Reddit), not a single shared slug.
>
> **Reddit notes:** 3 top-of-funnel "Community" campaigns (Feb–Jun 2026), objectives CONVERSIONS + CLICKS.
> Native engagement (upvotes/downvotes/comments) and all video metrics are NULL upstream, so only delivery
> + page visits + sparse conversions are surfaced. `reach` is non-additive across days, so it is not summed.
>
> **Audience / creative / keywords (added 2026-07-02; views 31–33):** Overview **Audience** = **Google Ads**
> inferred age / gender / device (`ga_audience`, from the `ads_AgeRange*`/`ads_Gender*` DTS tables scoped to
> customer_id `1054407474`; `cost_micros`/1e6 → AUD). It is "who the **ads** reached", **not** site visitors —
> **GA4 `DemographicDetails` is EMPTY** (Google thresholds demographics on this low-traffic property) and Google
> Ads **geo is country-only** (~all Australia), so neither is used; label it as Google-Ads-only + directional.
> Paid-Media **Creative gallery** = **Meta** `meta_creatives` (thumbnail / title / body / `link_url` per `creative_id`;
> `creative_thumbnail_url` is a Meta CDN link that can EXPIRE — the view keeps the most-recent URL and the export
> refreshes it each rebuild, with a graceful "preview unavailable" fallback). Shows the **top 10 by impressions**;
> **clicking a card opens a zoom lightbox** (`openCreative`) with the enlarged image + FULL copy + metrics + an
> "Open ad destination" link (`link_url`) — so the creative is readable even when the thumbnail link has expired
> (Meta exposes no public campaign URL, so we link to the ad's destination, not a campaign page).
> **Image persistence (2026-07-02):** Meta thumbnail URLs are signed + short-lived and 403 once an ad ends, so the
> export job **caches the top-10 images to the bucket** (`cache_creative_images` → `gs://…-resetdata-dash/creatives/<id>`,
> best-effort, never breaks the export) and emits `img_cached`; the dash serves the permanent copy at **`/creative-img/<id>`**
> (same auth as `/data.json`). When there's no cached image the card shows a **branded headline tile** (`ccFallback`),
> not a blank box. Caveat: this only preserves creatives whose URL is still live at export time — already-expired ones
> can't be recovered without the Meta Marketing API. **"Who we targeted"** = top **Google
> Ads keywords** (`ga_keywords`, search intent — more meaningful than audience segments for a search account).
> Job emits `ga_audience` / `ga_keywords` / `meta_creatives`.

## Currency & FX

Everything is **AUD**. Google Ads `spend` from the native DTS table is **already whole AUD dollars**
(verified ~A$8 CPM — do **not** divide by 1,000,000). Meta `cost` is already AUD. Reddit's
`account_currency` is **AUD native** (no FX). The Trade Desk bills **USD**, converted once in
[`sql/04_stg_ttd.sql`](sql/04_stg_ttd.sql) at **`FX_USD_AUD = 1.50`** (the same constant
`client_schneider` uses) and surfaced as `kpi.fx_usd_aud`. _If the real rate differs, edit the
`1.50` in `04_stg_ttd.sql` and re-run the views._

## GA4 conversion health (read honestly)

GA4 key-event tracking **is live and does populate**, but volumes are **modest** for this B2B / low-traffic
site (~72 key events over the window). The configured GA4 conversion event is **`Leadform_submit`**; other
demand events — `sign_up`, `start_$50_free_credit_click`, `file_download`, `learn_more_click` — also fire.
The dashboard shows these as **directional demand signals, not a high-volume funnel**, and flags the
caveat in-app. Platform-reported conversions are separate: **Google Ads = 83 (reliable)**, **Meta leads ≈ 51**
(the advertiser's **"Signup Button"** custom pixel conversion, `signup_button_conversions` — the generic
`actions_lead` is ~2 noise and is kept only as `platform_leads_actions`), **The Trade Desk = none reported
upstream** (its `conversions` JSON is null → cost-per-lead "—").

**GA4 channel blend:** Paid Search ≈ Google Ads (clean); Paid Social also carries Reddit traffic; Display
also carries Google PMax/Demand-Gen — so the platform↔channel mapping (Google↔Search, Meta↔Social,
TTD↔Display) is approximate. The Ads→Traffic correlation uses mapped paid sessions for the selected platforms.

## The 5 dashboard tabs (`dash/dashboard.html`)

Two filters (top of page, on Overview + Ads → Traffic; Website Traffic shows none):
- **Platform** — Google Ads · Meta · Trade Desk · Reddit. Scopes ad-delivery figures; on Ads → Traffic also
  scopes the mapped GA4 channel sessions (Meta + Reddit both map to Paid Social — counted once). (Paid Media
  ignores Platform — it always compares all four.)
- **Campaign** — searchable multi-select of every delivering campaign (grouped by platform, sorted by
  spend), all selected by default. Scopes **ad delivery only**; the GA4/website side stays whole. Powered
  by the campaign-grained `ad_campaign*` views, summed client-side.

> **Campaign display names are auto-cleaned** by `cleanCampaign()` (the "naming agent" in `dash/dashboard.html`):
> raw ad-platform names — Google Ads' `[TAG] Theme | S | Max Conv` / `100D | S | HT | Theme` convention — are
> normalised on the fly (strip the `[TAG]` + account/channel/bid-strategy codes, expand HT→High-Intent / GPU /
> LLM / ANZ…, Title-Case while preserving acronyms & good casing), so **new campaigns need no hand-editing**.
> Rules-based (deterministic), **display-only** — the raw name stays the join/filter key. `CAMPAIGN_LABELS` is
> now just an **override** map for the few names where the auto-label isn't ideal:
> `displayName = CAMPAIGN_LABELS[raw] || cleanCampaign(raw)`, used by the filter dropdown + every campaign table.

> **Chart toggles default to Absolute + Day** (client preference, 2026-07-02) — this client deliberately
> diverges from the repo-wide "Relative" default. The defaults live in the `grain`/`scale` objects in
> `dash/dashboard.html` (`syncToggleDefaults()` highlights the matching AXIS/VIEW-BY buttons at load);
> don't "fix" them back to Relative/Month.

1. **Overview** — KPI cards (media spend · impressions · clicks · sessions · ad-driven sessions · engaged ·
   key events), hero monthly **spend (stacked by platform) vs sessions** with key-events dashed line, and
   channel-mix / spend-by-platform donuts, and an **Audience** section (age bar + gender / device donuts =
   Google Ads *ad-audience* demographics; see the data-source note). **KPI cards that map to a chart line are clickable toggles**:
   Media spend, Impressions, Clicks, Website sessions and Key events hide/show their matching series on the
   hero chart (the card dims when off) — the same effect as clicking the chart's legend, driven from the
   card. Wired via `trendCard`'s `toggle` spec → `toggleKpiCard`/`applyKpiToChart` (keyed by chart-series
   label, so `mkChart` reapplies it on every grain/date re-render). **Clickable cards are grouped on the
   LEFT, static cards on the RIGHT** of each KPI row, so it reads which respond. Ad-driven & Engaged sessions
   (no hero line) and the CRM funnel cards (HubSpot snapshot, no time series) are intentionally static. The
   **Website Traffic** tab applies the same: **Sessions** and **Ad-driven** are clickable (toggling the
   webTrend "All sessions" / "Ad-driven (paid)" lines); Users / Engaged / Page views / Key events are static.
2. **Paid Media** — platform comparison table (CTR/CPM/CPC/conv/CPL across all four), monthly spend by
   platform, per-platform campaign tables (Google / Meta / TTD), the Meta creative mix, a **Creative gallery**
   (Meta ad thumbnails + copy + per-creative delivery), a **"Who we targeted"** panel (top Google Ads search
   keywords + conversions), and a **Reddit
   community-awareness deep-dive** (KPI cards with cost-per-outcome, an **efficiency trend** — impressions
   bars vs CPM/CPC lines, reframing the old spend-vs-impressions view so the *rising cost of a narrow AU
   auction*, not performance, explains the impression taper — and the 3 campaigns by objective with page
   visits + sign-up/lead conversions).
3. **Website Traffic** (GA4) — sessions / users / engagement KPIs, sessions by channel, total-vs-ad-driven
   trend, **key events by type**, and top sources/mediums (ad platforms flagged `AD`).
4. **Ads → Traffic** — monthly spend vs sessions, weekly impressions vs mapped sessions, a **Pearson-r
   correlation scatter**, and conversions / cost-per-lead by platform.
5. **Signups & CRM** (HubSpot) — answers Caroline's six questions. Reads HubSpot via
   `raw_windsor.hubspot_contacts` / `hubspot_owners` (a **live snapshot**, NOT scoped by the ad filters,
   which are hidden on this tab). The funnel Caroline cares about: **Leads → App signups → Loaded balance
   → Paying → Customers**, where *signup* = created an `app.reset.ai` account (`contact_rd_created_at`),
   *loaded balance* = `rd_billing_balance > 0` (mostly the free $50 credit) and *paying* = `rd_total_spend
   > 0` (actually spent). Sections: the funnel KPI row; **weekly signups stacked by source** + a paying
   line + this-week/QTD callout (Q1+Q2); a **source-quality table** (paying vs free-only, pay-rate, deals,
   ad-id matches — Q3+Q5); **lifecycle × owner** stacked bar + lifecycle donut (Q4, owner ids resolved to
   names via the owner dim); and the **BDM lead queue** (NEW / unassigned by status & owner — Q6).
   **Caveat surfaced in-app: HubSpot's own attribution is thin** (most signups land `Offline`/`Direct`),
   so the `gclid`/`fbclid` "Ad-ID" column and the Paid Media / Ads→Traffic tabs are the reliable ad signals.

> **CRM data source (HubSpot).** The Signups & CRM tab is fed by the shared `ingest/windsor_data_pull/hubspot/`
> loader (`raw_windsor.hubspot_contacts` ~4.7k, `hubspot_deals` ~242, `hubspot_owners` ~26 — a WRITE_TRUNCATE
> snapshot, all-STRING). The client views (`sql/24_stg_hubspot` … `30_crm_lead_queue`) type + aggregate that
> slice. The export job now also **gates on `raw_windsor.hubspot_contacts`**. The HubSpot loader is **not yet
> scheduled** — re-run it from a laptop to refresh the CRM numbers (`.\.venv\Scripts\python.exe
> ingest\windsor_data_pull\hubspot\hubspot_loader.py`); the daily ad-data ticks will then re-export the dash.

## How it works (3 stages — same shape as every client)

```
 (1) SOURCE → RAW (shared)              (2) RAW → VIEWS → JSON              (3) JSON → FRONTEND
 raw_google_ads.perf_google_ads         clients/client_resetdata/sql/*.sql filter   resetdata-dash (Cloud Run service)
 raw_windsor.perf_meta / _the_trade_desk ResetData's slice + roll it up;     shows a login page, then
 raw_ga4.perf_ga4 / perf_ga4_events     resetdata-export (Cloud Run JOB)     dashboard.html, which fetches
                                        reads the views → writes             /data.json and draws the charts
                                        resetdata.json to the private bucket
```

The job is **read-only on BigQuery** (it only SELECTs the views, across all three raw datasets, and writes
JSON to GCS). The data contract is matched by name across three files:
`sql/*.sql view column → job/main.py env key → dashboard.html data.* key`.

## Deploy / refresh (PowerShell, project `bidbrain-analytics`, region `australia-southeast1`)

**First-time stand-up:** `.\client_resetdata\deploy_resetdata.ps1` once (idempotent — bucket, dataset,
SAs, IAM, secrets, both Cloud Run units, the daily scheduler). The job SA gets **project-scoped**
`roles/bigquery.dataViewer`, which covers all three raw datasets — don't narrow it. After that:

```powershell
# ① edited a view (sql/*.sql) → reapply + re-run the job:
.\client_resetdata\sql\deploy_views_resetdata.ps1
# ② edited job/main.py (JSON shape) → rebuild + deploy + run the job:
.\client_resetdata\job\deploy_job_resetdata.ps1
# ③ edited dash/dashboard.html or dash/main.py → rebuild + redeploy the service:
.\client_resetdata\dash\deploy_dash_resetdata.ps1
```

> **Views are applied via `create_views.py` (the venv python BigQuery client), NOT `Get-Content | bq query`** —
> one filter contains an en-dash (`Reset backup – Ad account`) and WinPS `Get-Content` re-encoding corrupts
> non-ASCII SQL. `create_views.py` reads files as UTF-8. (It needs ADC authed as an account with access to
> `bidbrain-analytics` — `gcloud auth application-default login`.) Never run `gcloud builds submit --config
> cloudbuild.yaml` from a laptop (fails on `iam.serviceaccounts.actAs`); build the image + deploy as yourself.

## Branding

Skinned to **ResetData's brand**: crimson-pink accent (`#E84A6F`, from the logo + website) on deep navy.
The **100% Digital** agency mark and the **ResetData** wordmark are inlined as base64 (sourced from
[`creatives/`](creatives/README.md)) — agency mark · divider · client wordmark in the topbar and on the login
page. `agency_slug` in the data is `100-digital`. To re-skin later, edit the `:root` palette + the `.logo`
block in `dash/dashboard.html` and the `LOGIN_HTML` block in `dash/main.py`.

## What was skipped / noted (no-blockers)

- **Revenue / ROAS / AOV / transactions** — omitted entirely (B2B; `total_revenue` & `transactions` are 0).
- **Trade Desk conversions** — none reported upstream (`conversions` JSON null) → no TTD cost-per-lead.
- **GA4 conversion volume** — modest; shown honestly as directional (see above).
- **Country filter** — none (AU-only).

## Coordinates

| | |
|---|---|
| BigQuery dataset | `client_resetdata` (31 views — 23 ads/GA4 + 7 HubSpot CRM, reading `raw_windsor.hubspot_*`) |
| Data bucket / object | `bidbrain-analytics-resetdata-dash` / `resetdata.json` |
| Export job | `resetdata-export` (runtime SA `resetdata-dash-job@…`, read-only BQ + bucket write) |
| Web service | `resetdata-dash` (runtime SA `resetdata-dash-web@…`) → [`dash/LIVE_URL.md`](dash/LIVE_URL.md) |
| Secrets | `resetdata-dash-password` · `resetdata-dash-session-key` |
| Refresh | Cloud Scheduler `resetdata-export-daily` — `*/10` UTC, **self-gating** (rebuilds within ~10 min of new upstream data; most ticks no-op) |

## Files

- [`sql/`](sql/README.md) — 31 BigQuery views (filter + model; 24–30 are the HubSpot CRM layer); `create_views.py` applies them in `NN_` order.
- [`job/`](job/README.md) — the export job (stage 2): views → `resetdata.json`.
- [`dash/`](dash/README.md) — the web app (stage 3): password gate + `dashboard.html`.
- [`creatives/`](creatives/README.md) — branding source assets (the ResetData wordmark + a site
  screenshot), now wired in as inline base64 / the sampled palette.
- [`data/`](data) — a one-off reference export (`resetdata_reddit_febmar26.csv`, Reddit Feb–Mar 2026
  ad delivery). **Not read by the views/job** — it predates the live Reddit wiring and is kept only as a
  manual reference. Reddit is now a first-class platform: the pipeline reads `raw_windsor.perf_reddit`
  via [`sql/04b_stg_reddit.sql`](sql/04b_stg_reddit.sql) (Reddit traffic also still blends into the GA4
  Paid Social channel).
