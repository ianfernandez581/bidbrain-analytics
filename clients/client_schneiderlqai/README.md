# client_schneiderlqai — Schneider Electric "Liquid AI Data Center" (LQAIDC)

A **single-campaign, paid-media-only** dashboard for Schneider Electric's **Liquid AI Data Center**
(LQAIDC) push — a TOFU / **Awareness** campaign for *Liquid Cooling for AI Data Centers*, run by
**Transmission**. It is a lean sibling of `client_schneider` (same aesthetic + engines), NOT part of
the multi-program Schneider Pacific dashboard.

- **Channels:** LinkedIn (single-image Sponsored Content) + The Trade Desk (programmatic display).
- **Countries (6):** India (dominant), Brazil, Australia, Chile, Saudi Arabia (KSA), UAE.
  Media-plan regions: South America (BR+CL), MEA (SA+AE), Pacific (AU), India.
- **Awareness only** — objective is Website visits / display reach. **No leads, no conversions, no
  Salesforce/CS, no GA4.** The story is reach (impressions), clicks, CTR, cost efficiency (CPM/CPC),
  and pacing vs the media-plan targets.
- **Currency:** AUD (both channels native AUD; targets treated as AUD — see INTAKE.md).
- **Flight:** 15 May → 31 Dec 2026. Data started 16 May (LinkedIn) / 18 May (Trade Desk).

## Live
- **Service:** `schneiderlqai-dash` · https://schneiderlqai-dash-516554645957.australia-southeast1.run.app
- **Front-door:** https://dashboards.bidbrain.ai/d/schneiderlqai/ (Transmission agency) — see `dash/LIVE_URL.md`.
- Password-gated (Secret Manager `schneiderlqai-dash-password`); the platform logs in server-side so
  there is no second password via the front-door.

## Tabs
1. **Overview** — delivery KPIs (spend / impressions / clicks / CTR + CPM/CPC), a **pace-to-plan** card
   (delivered vs media-plan targets over the flight), a delivery-over-time hero chart (grain + Relative/
   Absolute toggles), a LinkedIn-vs-Trade-Desk channel table, spend-by-channel + spend-by-country charts,
   and a country summary table.
2. **Creative** — LinkedIn message concepts (3), Trade Desk display concepts (Accelerate AI / Cooling
   Performance / Cool & Smart / Every Degree / Generic) + banner-format mix, best creatives by CTR, and
   a sortable/searchable creative detail table.
3. **Media Plan** — budget tiles, delivered-vs-target pacing per live channel, and the full 7-line brief
   media plan (LinkedIn / Trade Desk / Search / Reddit × Awareness + Retargeting) with Live/Planned tags.
   Search, Reddit and the Retargeting lines are **planned (tbc), not yet live** — targets shown for context.

## Architecture (standard 3-stage pattern)
```
raw_snowflake.{linkedin_ads_apac, tradedesk_apac_all}          (shared mirrors, filled by ingest/)
  -> sql/01_stg_linkedin, 02_stg_tradedesk                     (scope: Schneider account + '%LQAIDC%')
  -> sql/03_delivery (platform x date x country x region fact) + sql/04_creative
  + data/media_plan.csv -> seed_media_plan  (load_seeds.py)    (the brief targets)
  -> job/main.py  -> gs://bidbrain-analytics-schneiderlqai-dash/schneiderlqai.json
  -> dash/main.py (Flask gate) serves dashboard.html + /data.json
```
- **Scope filter** keys on `CAMPAIGN_NAME LIKE '%LQAIDC%'` (LinkedIn ad-set name / Trade Desk campaign
  name) so it rolls up **both** raw name forms — the campaign name gained a `2306_` prefix mid-flight
  (~6-7 Jul 2026); same ad-set/ad-group IDs. (The Enterprise IT `1958_SE_EntIT_*` campaigns in the same
  Trade Desk export are a DIFFERENT brief and are deliberately out of scope.)
- **Country** is parsed from the LinkedIn ad-set `CAMPAIGN_NAME` / Trade Desk `AD_GROUP_NAME`.
- **Targets** (`plan.channels`) are summed over the media-plan lines flagged `live=1` (LinkedIn Awareness
  + both Trade Desk Awareness lines): LinkedIn 925,600 imp / 5,091 clk / A$69,420; Trade Desk 9,196,000
  imp / 34,176 clk / A$138,840. Live budget A$208,260; full plan A$473,124.
- **Spend multiplier:** the dashboard's `bbApplySpendMult` grosses delivered `spend_aud` by
  `window.BB_SPEND_MULT` per channel (linkedin / ttd). Plan **targets are NOT grossed** — they are the
  media-plan (billed) budget, so grossed-delivery-vs-billed-budget paces correctly on the front-door.

## Freshness
Self-gating `*/10` UTC (`schneiderlqai-export-daily`). Gate watches
`raw_snowflake.{linkedin_ads_apac, tradedesk_apac_all}` `__TABLES__.last_modified`; watermark =
`gs://...-schneiderlqai-dash/_freshness.json`. **Static re-seeds (media plan) need `FORCE_REBUILD=1`.**

## Deploy / edit (root CLAUDE.md is the canonical command source)
- Edited `dash/dashboard.html` or `dash/main.py` -> `dash/deploy_dash_schneiderlqai.ps1`
- Edited `job/main.py` -> `job/deploy_job_schneiderlqai.ps1`
- Edited a `sql/*.sql` view -> `sql/deploy_views_schneiderlqai.ps1`
- Edited `data/media_plan.csv` (targets) -> `deploy_seeds_schneiderlqai.ps1` (forces the rebuild)
- First-time standup (idempotent): `deploy_schneiderlqai.ps1`
- Optional "Download slides" (AI deck): `dash/enable_report_schneiderlqai.ps1` once, then redeploy the dash.

## GCP facts
- Project `bidbrain-analytics`, region `australia-southeast1`.
- Dataset `client_schneiderlqai` · bucket `bidbrain-analytics-schneiderlqai-dash` ·
  job `schneiderlqai-export` · service `schneiderlqai-dash`.
- SAs `schneiderlqai-dash-job@` (BQ read + bucket write) · `schneiderlqai-dash-web@` (bucket read +
  secretAccessor). Secrets `schneiderlqai-dash-password`, `schneiderlqai-dash-session-key`.
