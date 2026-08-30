# clients/client_geocon/sql/ — the BigQuery view definitions (the stage-2 transform)

> The version-controlled `CREATE OR REPLACE VIEW` files that turn shared raw platform data into
> Geocon's dashboard-ready numbers. The export job ([`../job/main.py`](../job/README.md)) reads
> these views to build `geocon.json`.

**Plain English:** the raw warehouse tables are shared across every client and every platform.
These saved queries pick out *only Geocon's* rows, split them by **development** (Gateway Braddon
vs Northbourne Gateway), and shape them into the exact figures the dashboard shows. **This is where
the business logic lives.** If a number on the dashboard looks wrong, it is almost always here.

These files are the **source of truth** — edit them and re-apply, rather than editing views in the
BigQuery console (or the two drift). The `NN_` filename prefix sets apply order: staging views
(`stg_*`) must exist before the models that read them.

**Where this sits:** `raw_windsor.*` + `raw_google_ads.*` → **[these views]** →
[`../job/`](../job/README.md) → `geocon.json`.

> **This README was a stale copy of `client_mongodb/sql/README.md`** until 2026-08-24 — it described
> Trade Desk advertisers, Salesforce campaign IDs and pixel views that have never existed in this
> client. If you are following a geocon doc that mentions MongoDB, it is wrong.

---

## The views (in dependency order)

| File | View | What it does |
|---|---|---|
| [`01_stg_meta.sql`](01_stg_meta.sql) | `stg_meta` | Meta slice: `raw_windsor.perf_meta` filtered to **account `3754165911553001`** (100% Digital - Clients) **AND** campaign prefix `Geocon_` — both are required, because the table carries six ad accounts and that account hosts three of our clients. Classifies `funnel_stage` from the campaign name and resolves `property` (the development) against `seed_property_map`. |
| [`02_fact.sql`](02_fact.sql) | `fact` | The Meta fact, one row per (date × campaign × adset × ad). **Unchanged by the 2026-08 multi-channel work and deliberately kept**, so `fact_all`'s Meta arm can be diffed against it. |
| [`03_targets.sql`](03_targets.sql) | `targets` | Flat key/value targets **per development**, from `seed_targets`. A `PENDING` row may carry an empty value (Northbourne's lead targets do — the plan commits no lead number), which reads through as NULL and renders as `-`. |
| [`04_budget.sql`](04_budget.sql) | `budget` | Budget + flight window **per development**, from `seed_budget`. Carries `measurable_budget_aud` — see the note below. |
| [`05_breakdowns.sql`](05_breakdowns.sql) | `breakdowns` | Meta-only audience (age × gender) + placement facts from the geocon-only `raw_windsor.geocon_meta_breakdown`. Property-resolved from the **same seed** `01_stg_meta` uses, so the charts can never disagree with the KPIs above them. |
| [`06_media_plan.sql`](06_media_plan.sql) | `media_plan` | The signed media plan, one row per bought LINE, from `seed_media_plan`. Carries each line's own impression / click / CPM / CTR target, its `measurable` flag and its `match_pattern`. **Nothing on the dashboard renders it today** (the Media Plan tab was removed on request); it is kept because it holds the per-platform targets the platform lanes will be measured against, and its `channel` list feeds the coming-soon placeholder. |
| [`07_stg_linkedin.sql`](07_stg_linkedin.sql) | `stg_linkedin` | LinkedIn slice of the shared `raw_windsor.perf_linkedin`. **Returns zero rows today** — there is no Geocon LinkedIn account in Windsor yet. |
| [`08_stg_ttd.sql`](08_stg_ttd.sql) | `stg_ttd` | Trade Desk slice of the shared `raw_windsor.perf_the_trade_desk`. **LIVE since 2026-08-20** — advertiser `Geocon Group`, the Northbourne **High Impact** line (plan seq 1). Its explicit `CAST(NULL AS INT64)` on `leads` / `reach` / `landing_page_views` is what drives the dashboard's awareness mode: a metric the platform does not report is NULL, never 0. |
| [`09_stg_google_ads.sql`](09_stg_google_ads.sql) | `stg_google_ads` | Google Ads slice of the **native DTS export**, customer `5457742070` (Geocon Group) under MCC `3451896252`. The three Northbourne campaigns exist and are PAUSED, so it returns zero rows until they are switched on. |
| [`10_fact_all.sql`](10_fact_all.sql) | `fact_all` | **The fact the job ships.** Meta (verbatim from `fact`) + LinkedIn + Trade Desk + Google Ads, with each row's media-plan LINE resolved. |

---

## Five rules this folder encodes

**1. Only the Meta arm may fall back to a development.** `01_stg_meta`'s scope (ad account +
`Geocon_` prefix) is exact, so its catch-all `ELSE Gateway Braddon` is safe. The other three
channels read tables shared with six-to-eleven other clients, so they must match a development
**by name** or land in `'Unmapped'` — which the export job **alarms on** rather than absorbs. A
Geocon Trade Desk campaign nobody told us about therefore appears as a loud warning in the job log,
not as an invisible A$40k added to a live client's spend.

**2. `p_ads_CampaignBasicStats`, never `p_ads_CampaignStats`.** CampaignStats is additionally
segmented by `click_type`, which **duplicates impressions**: over one week of a live account it
reported 22,892 impressions where BasicStats reported the true 21,008. Clicks happen to agree, so
the error is silent on the metric people spot-check first.

**3. Measurable vs committed budget.** Two of Northbourne's nine lines can never be reported on —
the SEO retainer (A$9,600, no ad server) and the Google Search management fee (A$7,500, an agency
fee). That is A$17,100 of A$205,600. Pacing against the committed figure would report a permanent
8.3% shortfall no amount of delivery could close, so `measurable_budget_aud` is what the dashboard
paces on and the committed total is shown beside it.

**4. `seed_property_map.status` is the coming-soon switch.** `coming_soon` makes the dashboard show
a placeholder for that development **however much delivery has landed** - Northbourne's Trade Desk
line can be live while the campaign waits on creative and approvals elsewhere. It is deliberately
not inferred from row counts. Flipping to `live` is a one-word CSV edit + re-seed + a forced export.

**5. Rates never enter a fact.** No view here stores a ratio — CTR/CPM/CPC/CPL are recomputed
client-side from summed components, so any date sub-range is exact (the repo-wide rule).

---

## Known gaps at 2026-08-28

- **No Geocon LinkedIn account in Windsor** (A$6,000, plan seq 4) - the view is written and returns
  nothing; it lights up on its own the first day a row lands. **Trade Desk was granted and went live
  on 2026-08-20** and is the only Northbourne line reporting today.
- **A NULL metric is not a zero, and the dashboard depends on that.** `08_stg_ttd` casts `leads`,
  `reach` and `landing_page_views` to NULL because Trade Desk does not measure them on this buy;
  `dash/dashboard.html` reads exactly that nullness to decide which panels a development can render
  (see the client README → "Awareness mode"). If a future staging view coalesces one of those to 0
  to "tidy up", the dashboard will draw a lead funnel that dead-ends at zero on an awareness buy.
- **Google Ads carries no video metric.** Neither `CampaignBasicStats`, `CampaignStats` nor the
  (empty) `VideoStats` table has views, view rate or quartiles, and `raw_windsor.perf_google_ads`
  has no video columns either. The YouTube line's 24,000-view target and A$0.50 CPV therefore
  **cannot be measured** until the DTS export is extended. The dashboard says so on screen rather
  than reporting zero.
- **Meta is frozen at 2026-08-10** — the Windsor Meta grant lapsed on 2026-08-11 (estate-wide, not
  a geocon problem). Northbourne's Meta line cannot report until it is re-authed.

---

## Apply them

```powershell
# seeds FIRST - 06/07/08/09/10 all read seed_property_map or seed_media_plan
.\.venv\Scripts\python.exe clients\client_geocon\seed_static.py
.\.venv\Scripts\python.exe clients\client_geocon\create_views.py
# a seed/view change is invisible to the freshness gate, so force the export:
gcloud run jobs execute geocon-export --region australia-southeast1 --update-env-vars FORCE_REBUILD=1 --wait
```

## Verifying a change

```sql
-- fact_all must equal fact on Gateway Braddon (the Meta arm is fact verbatim)
SELECT (SELECT ROUND(SUM(spend),4) FROM `bidbrain-analytics.client_geocon.fact`)      AS fact_spend,
       (SELECT ROUND(SUM(spend),4) FROM `bidbrain-analytics.client_geocon.fact_all`)  AS all_spend;

-- nothing may sit in 'Unmapped', and every non-Meta row should claim a plan line
SELECT property, channel, plan_line, COUNT(*) n, ROUND(SUM(spend),2) spend
FROM `bidbrain-analytics.client_geocon.fact_all` GROUP BY 1,2,3 ORDER BY 1,2,3;

-- day one of any new channel: confirm the campaign names match the property tokens
SELECT DISTINCT channel, campaign_name, property, plan_line
FROM `bidbrain-analytics.client_geocon.fact_all` ORDER BY 1,2;
```

## See also

- [`../README.md`](../README.md) — the client overview and the 3-stage pipeline.
- [`../job/README.md`](../job/README.md) — reads these views; documents the JSON contract.
- [`../targets/`](../targets/) — the committed CSVs behind every `seed_*` table.
