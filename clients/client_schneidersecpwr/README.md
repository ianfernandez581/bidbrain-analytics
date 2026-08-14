# client_schneidersecpwr — Schneider Electric "Secure Power"

The **THIRD** Schneider dashboard, and a lean sibling of `client_schneiderlqai` (same engines, same
aesthetic, same 3-stage pattern). It reports the **three Secure Power briefs** that are deliberately
OUT of `client_schneider`'s scope because **they have separate stakeholders** — a different group of
people views this dashboard:

| Campaign | Brief | Channels | Markets |
|---|---|---|---|
| **Enterprise IT Expansion** (`ent_it`) | 1958 | LinkedIn + Trade Desk | India · MEA · South America · Pacific |
| **Industrial Edge / Prefab** (`ind_edge`) | 2463 | LinkedIn + Trade Desk | Australia · New Zealand (+ combined ANZ) |
| **Software First EcoStruxure** (`software_first`) | 2305 | LinkedIn + Trade Desk | Australia · New Zealand |

- **Paid media only.** No Salesforce / content syndication, no GA4, no conversions. The story is
  reach (impressions), clicks, CTR and cost efficiency (CPM / CPC) per brief, per market.
- **DELIVERY-ONLY — there are NO targets.** None of the three has a signed media plan, so there is no
  pacing card, no budget tile and no vs-plan column anywhere. Each campaign's flight is **observed**
  ("live since <first delivery day>"), never presented as a booked window.
- **Currency:** AUD (both channels native AUD; USD@1.50 / SGD@1.15 arms kept for robustness).

## Relationship to the other two Schneider dashboards
| | Scope |
|---|---|
| `client_schneider` | The multi-program Pacific dashboard — the 8 programs on the client's own intake sheet. These three are explicitly excluded (client, 2026-08-10). |
| `client_schneiderlqai` | Single campaign: Liquid AI Data Center (brief 2306). |
| **`client_schneidersecpwr`** | **These three briefs. Separate stakeholders.** |

All three read the same shared raw mirrors but are **fully self-contained** — this dashboard does NOT
read `client_schneider`'s views, so a scope change there cannot move numbers here.

## Tabs
1. **Overview** — delivery KPIs (spend / impressions / clicks / CTR + CPM/CPC), a **campaign
   comparison** table (which replaces LQAI's pace-to-plan card, since there are no targets), a
   delivery-over-time hero chart with grain + Relative/Absolute toggles, a LinkedIn-vs-Trade-Desk
   channel table, spend by channel + by market, and a market summary.
2. **Campaigns** — one card per brief (spend / imps / clicks / CTR, channels, markets, live-since,
   and LinkedIn lead-form leads where a brief runs Lead Generation ad sets), plus campaign × channel
   and campaign × market breakdowns and a spend-by-campaign / impressions-by-region pair of charts.
3. **Creative** — concepts, formats, best creatives by CTR, and a sortable/searchable detail table.

Filters: a **Campaign dropdown in the top nav bar** (the `client_schneider` / Cloudflare pattern -
`#campSelect` + `setCampaign()`), plus **Market** chips and a **date range** (Overview + Campaigns;
the Creative feed carries no date column, so the picker is hidden there).

**The Campaign dropdown is single-select** and leads with **"All campaigns"** - unlike
`client_schneider`, whose portfolio option was retired, the combined three-brief view is the whole
point of this dashboard, so it is the default. Switching campaign **re-opens every market chip**
(`setCampaign` resets `activeMarkets` from `marketRoster()`): the three briefs run in DIFFERENT
markets, so carrying a market selection across would silently zero the incoming campaign's numbers.
**`.dash-select` must keep a SOLID background** - Chrome paints the native `<option>` list from the
select's own background, so a translucent value makes every option invisible on the dark nav bar.

## Architecture (standard 3-stage pattern)
```
raw_snowflake.{linkedin_ads_apac, tradedesk_apac_all}      (shared mirrors, filled by ingest/)
  -> sql/01_stg_linkedin, 02_stg_tradedesk                 (scope: 3 briefs; campaign + market tagging)
  -> sql/03_delivery (campaign x platform x market x day)  + sql/04_creative (whole-flight)
  -> job/main.py -> gs://bidbrain-analytics-schneidersecpwr-dash/schneidersecpwr.json
  -> dash/main.py (Flask password gate) serves dashboard.html + /data.json
```
There is **no seed table and no `data/` dir** — nothing to seed, because there are no targets.

## Campaign tagging — the part to get right
Every match is a **substring token on CAMPAIGN_NAME**, never a fixed offset, because Transmission is
progressively prefixing campaign names with the brief number and the SAME campaign appears under both
`SE_*` and `<brief>_SE_*` forms (repo-wide rule in `md/AGENTS.md`). The three token sets are disjoint,
verified against every Schneider campaign before the views were written.

| Campaign | Tokens | Why |
|---|---|---|
| `ent_it` | `EntIT` | catches `SE_EntIT_2026_*` and `1958_SE_EntIT_2026_*` |
| `ind_edge` | `SE_Industrial Edge_`, `Industrial Edge Wave3`, `Industrial Edge W3`, `2463_` | **WAVE 3 ONLY.** The bare `Industrial Edge` token also sweeps in the 2025 `1839_Schneider_Electric_Pacific_*` wave (~A$8.7k) — a different brief. Widen only on an explicit instruction. |
| `software_first` | `Software First`, `EcoStruxureIT`, `2305_` | **`2305_` alone is NOT enough** — the Trade Desk line ran as `SE_EcoStruxureIT_AWR_2026` from 2026-06-17 and only gained the prefix on 07-06, so a prefix-only token silently drops ~A$2.3k. |

**Match on CAMPAIGN_NAME, never CAMPAIGN_GROUP_NAME.** LinkedIn's group names are mislabelled here: a
group named `2305_SE_ANZ Industrial Edge W3 Prefab` holds campaigns named
`2463_SE_Industrial Edge Wave3_*`. Keying on the group would cross-tag two different briefs.

## Markets — NOT folded to AU/NZ
`client_schneider`'s `pm_delivery` folds everything to Australia / New Zealand. **This dashboard must
not**, because Enterprise IT genuinely runs across India / MEA / South America / Pacific and only
~12% of it is Pacific — folding would report the rest as Australia. The staging views therefore keep
the market the parser resolved, and `03_delivery` adds a `region` rollup (Pacific covers Australia,
New Zealand, the combined `ANZ` residual and Enterprise IT's own `Pacific` token). Anything
unparseable lands in `Unmapped` and shows as a loud trailing chip rather than being absorbed silently.

Parser: ad-group first then campaign name on Trade Desk (Industrial Edge and Software First carry
their country only in the ad-group name); campaign name on LinkedIn. Country tokens beat coarse
region tokens, ANZ beats Pacific, first match wins — the same proven parser `client_schneider` uses.

## Freshness
Self-gating `*/10` UTC (`schneidersecpwr-export-daily`). The gate watches
`raw_snowflake.{linkedin_ads_apac, tradedesk_apac_all}` `__TABLES__.last_modified`; watermark =
`gs://...-schneidersecpwr-dash/_freshness.json`. Any **view-only change needs a forced run**
(`FORCE_REBUILD=1`) — the gate does not watch views.

The job **refuses to publish an empty fact**: if the delivery view returns 0 rows it aborts rather
than overwriting a good JSON, so a scope regression (a renamed campaign no token matches) surfaces as
a failed run instead of a dashboard that reads "campaign stopped".

## Deploy / edit (root CLAUDE.md is the canonical command source)
- Edited `dash/dashboard.html` or `dash/main.py` -> `dash/deploy_dash_schneidersecpwr.ps1`
- Edited `job/main.py` -> `job/deploy_job_schneidersecpwr.ps1`
- Edited a `sql/*.sql` view -> `sql/deploy_views_schneidersecpwr.ps1` (reapplies + forces a job run)
- First-time standup (idempotent) -> `deploy_schneidersecpwr.ps1`
- Sanity-check the dashboard JS before deploying:
  `.\.venv\Scripts\python.exe scripts\_validate_dash_js.py clients\client_schneidersecpwr\dash\dashboard.html`

## GCP facts
- Project `bidbrain-analytics`, region `australia-southeast1`.
- Dataset `client_schneidersecpwr` · bucket `bidbrain-analytics-schneidersecpwr-dash` ·
  job `schneidersecpwr-export` · service `schneidersecpwr-dash`.
- SAs `schneidersecpwr-dash-job@` (BQ read + bucket write) · `schneidersecpwr-dash-web@` (bucket read
  + secretAccessor). Secrets `schneidersecpwr-dash-password`, `schneidersecpwr-dash-session-key`.
- **NEW-CLIENT GOTCHA (md/AGENTS.md):** grant `platform-dash-web@` `secretAccessor` on
  `schneidersecpwr-dash-password`, or the front-door tile's Open button returns a bare **500** with
  nothing in this service's own log. Also add `schneidersecpwr` to `$CLIENTS` in
  `scripts/enable_super_admin.ps1` so god-mode reveal/rotate works.

## Known follow-ups
- **AI slide deck (`/report`) is DORMANT.** `dash/report.py` + `bb_deck.js` are vendored so the routes
  exist, but the prompts are still LQAI's single-campaign awareness language and the service has no
  `roles/aiplatform.user`. Re-template the prompts for three separate briefs BEFORE running
  an `enable_report_*` script. `buildReportPayload()` already emits the correct three-campaign shape
  and explicitly tells the model there are no targets.
- **If a media plan ever lands** for any brief, add it the repo-standard way — a committed
  `data/media_plan.csv` -> `seed_media_plan` via a `load_seeds.py`, read by `job/main.py` — and port
  `paceBar()` / `renderPacing()` back from `client_schneiderlqai/dash/dashboard.html`. Do not
  hardcode targets.
