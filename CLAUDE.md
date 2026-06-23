# CLAUDE.md — Bidbrain Analytics

Monorepo of self-hosted client marketing dashboards on GCP. One repeatable pattern, many clients:
**MongoDB is the template**; **STT** is the archetype every lean paid-media client is copied from.
**Ten client dashboards are live**, plus a meta **Status dashboard** and the **Platform front-door**
(dashboards.bidbrain.ai — one login over all of them). The root `README.md` is the
full human map — **this file (CLAUDE.md) is the canonical agent fast-path** and the single source of
truth for fixed facts + deploy commands. **Keep it current: see _Keep this file current_ at the
bottom — updating it is part of finishing a task, not an afterthought.**

**`status_dashboard/`** is the pipeline-health backend that monitors all Snowflake-sourced clients —
proves whether a stale dashboard is Transmission's fault (Snowflake source not updating) or 100%
Digital's (our pipeline behind), and that each dashboard number equals Snowflake. **Its UI is now
MERGED INTO the platform front-door** (Overview health badges + a Data Accuracy tab — see
`bidbrain-platform/`); the standalone `status-dash` web service + `/d/status/` proxy are retired. What
remains here is the data + deploy plumbing: the **`status-export`** job (writes `status.json`; SA
`status-dash-job@`, needs `snowflake-bq-key` + objectViewer on every client bucket) and the new
**`status-deploy`** job (`status_dashboard/deploy/`, SA `status-deploy@`) — the privileged "Make this
live" worker the platform triggers. CS verification queries are now BUILT from each client's
`definitions.json` (single source of truth; LIVE copy at
`gs://bidbrain-analytics-status-dash/definitions/<c>.json`), so editing it changes BOTH the dashboard
(via seed tables) and the check. bucket `bidbrain-analytics-status-dash`. See `status_dashboard/README.md`.

**`bidbrain-platform/`** is the front-door: ONE password box over all the dashboards. **LIVE on its
Cloud Run URL** (`platform-dash-…run.app`; no custom domain needed). It's a **REVERSE PROXY**: each
dashboard is served under the platform's own origin at `/d/<client>/`, and the platform logs into the
upstream `<c>-dash` once (server-side, with that dashboard's own Secret-Manager password) — so after the
ONE platform login the dashboards open with **no second password**, on raw run.app, no domain required.
An **agency** password opens a portal of that agency's clients;
a single **dashboard** password opens just that one; the **admin** password opens an editable
agencies→clients→campaigns tree; the **super-admin** password opens a god-mode console
(`templates/superadmin.html`, gold theme) that **reveals AND rotates every password** — agencies,
dashboards, admin — and opens any dashboard. Revealing works because the registry now keeps a
recoverable `password_plain` beside each pbkdf2 hash (a hash can't be un-hashed); a hash-only live
registry self-heals via `Store.backfill_plaintext` (recovers seed values that still verify). Rotating
a **dashboard** password is true god-mode: it writes a new `<c>-dash-password` secret version **and
restarts that `<c>-dash` service** so the new password takes effect everywhere (needs the extra IAM
from `scripts/enable_super_admin.ps1`). Super admin resolves first in `store.resolve_password`
(registry hash, else the bootstrap `SUPER_ADMIN_PW` env / secret `platform-super-admin-password`).
Web-only service `platform-dash` (SA `platform-dash-web@`,
`storage.objectAdmin`), registry = ONE private JSON `gs://bidbrain-analytics-platform-dash/platform.json`
(same private-bucket pattern as the dashboards — no database), no job/scheduler of its own.
**Merged-in pipeline status (2026-06-23):** the homepage (agency portal + admin tree) is now TABBED —
an **Overview** tab (each client shows an uploadable **logo** + a data-sync **health badge** +
time-since-update, from the status pipeline's `status.json`) and a **Data Accuracy** tab (the per-client
Snowflake-vs-dashboard checks, with **editable definitions** + a **"Make this live"** deploy). Editing is
OPEN — anyone who can open a client may edit its `definitions.json`; the only gate is a required **name**,
shown as a `last_edited_by` tag. "Make this live" triggers the `status-deploy` job (platform SA needs
`run.invoker` on it + `objectAdmin` on `gs://bidbrain-analytics-status-dash`, granted by
`status_dashboard/deploy/deploy_job_status_deploy.ps1`). Logos upload via the admin client row → stored at
`gs://bidbrain-analytics-platform-dash/logos/<c>`, served at `/logo/<c>`. New `dash/main.py` routes:
`/api/status`, `/logo/<c>`, `/admin/api/client-logo`, `/definitions/<c>` (GET/POST), `/deploy/<c>`; shared
UI in `templates/_status_merge.html`. See `bidbrain-platform/README.md`.
"No second password" = a signed **`bb_sso`** cookie scoped to `.bidbrain.ai` listing the client keys
you may open; each dashboard's `authed()` was extended (additively — its own password still works) to
trust it via the vendored `platform_sso.py` (`SSO_SECRET`+`CLIENT_KEY` env, shared signer secret
`platform-sso-key`). Agencies: **100% Digital** {cityperfume, vmch, tlm, resetdata, +bellshakespeare/geocon
*coming soon*}, **Transmission** {schneider, cloudflare, proptrack, mongodb, +status (the meta
Pipeline-Status dash, surfaced here so Transmission can watch data health)}; **stt/hireright unassigned**.
No-second-password is delivered by the **proxy** (`/d/<client>/` in `dash/main.py`), NOT a cookie —
the `bb_sso`/`platform_sso.py` machinery stays deployed but inert, and would only take over if a real
domain is later wired (Cloud DNS + Cloud Run domain mappings; `australia-southeast1` supports `gcloud
run domain-mappings`; **NO Cloudflare**). Platform SA `platform-dash-web@` has `secretAccessor` on every
`<c>-dash-password` (to log into upstreams). **Feedback:** the proxy injects a self-contained
**Feedback widget** (text **or** a voice note via `MediaRecorder`, **plus an html2canvas page
screenshot**) into every proxied dashboard — same `</body>`-injection as the logout pill
(`feedback.py` storage + `feedback_ai.py` Gemini transcribe/interpret + `_FEEDBACK_WIDGET`/`/feedback*`
in `dash/main.py`). Notes land in the platform's OWN private bucket (`gs://bidbrain-analytics-platform-dash/
feedback/<client>/…`: JSON + the recording + the screenshot; no email yet). Admin/super read them at
`/feedback/admin` as **Raw feedback | AI summary | Screenshot** — voice is transcribed + interpreted
into action items by Gemini (`GEMINI_API_KEY`, run lazily on view & cached back). See `bidbrain-platform/README.md`.

## Fixed facts (memorize; never re-derive)
- GCP project: `bidbrain-analytics` (project # 516554645957)
- Region: `australia-southeast1` — **EVERYTHING**, never another region.
- Artifact Registry docker repo: `bidbrain` (shared by all clients)
- Local dev: Windows + PowerShell. Use the repo venv: `.\.venv\Scripts\python.exe`
- Per client `<c>` everything derives from the key: dataset `client_<c>`,
  bucket `bidbrain-analytics-<c>-dash`, export job `<c>-export`, web service `<c>-dash`,
  subdomain `<c>.bidbrain.ai`.
  (`<c>` ∈ {mongodb, cloudflare, stt, schneider, hireright, cityperfume, resetdata, proptrack, tlm, vmch})
- **Repo layout:** per-client dashboards live in `clients/client_<c>/` (each with `sql/` `job/` `dash/`);
  the shared raw-layer loaders live in `ingest/<source>_data_pull/`. `status_dashboard/` + `scripts/` stay at root.

## What's in the repo (so you don't have to go hunting)
**10 client dashboards** — each is `clients/client_<c>/` with `sql/` + `job/` + `dash/`, dataset `client_<c>`,
job `<c>-export`, service `<c>-dash`. All LIVE and self-gating `*/10`. The non-derivable facts:

| `<c>` | Reports | Currency | Views | Watch out for |
|---|---|---|---|---|
| `mongodb` | TEMPLATE — Trade Desk paid media + Content Syndication (Salesforce, 3 DNB + KGA/IDC campaigns) + a TTD **Universal Pixel** content-engagement snapshot | USD | 13 | CS map: Accepted/Rejected/New(=Unresponsive+New). KGA(IDC) campaign (`701RG00001NKKwQYAX`) has a NULL PROGRAMME_LABEL → normalised in dash (`progLabel`/`campaignOf`); its delivered leads = Unresponsive+Do Not Contact+New ONLY (client def, no Accepted/Rejected lifecycle) — the campaign-conditional `CASE WHEN PROGRAMME_LABEL IS NULL` in `05_cs_leads_by_programme.sql`. CS markets are case-normalised (`UPPER(TRIM)` in `02_stg_salesforce.sql`) and off-plan countries (China/Japan) sit in a 5th `OTHER` region (in `all_markets`) so CS totals are complete. **Pixel section** (views `11_stg_tradedesk_pixel`→`pixel_assets`/`pixel_summary`) is **LIVE** from `raw_snowflake.tradedesk_apac_conversion` (per-fire TTD Universal Pixel, `ADVERTISER_ID='9c1w83i'`) — the manual CSV seed (`seed_pixel.py`) + the device/env/creative-size dimension charts were retired. click vs view-through is derived (`DISPLAY_CLICK_COUNT>0`); per-fire DNB vs KGA(IDC) from the attributed campaign (`COALESCE(FIRST_DISPLAY_CLICK_CAMPAIGN_NAME, FIRST_IMPRESSION_CAMPAIGN_NAME)`→`SPLIT("_")[2]`→`campaignOf`, 100% attributed, 0 unattributed). **Driven by the DNB/KGA(IDC) campaign toggle** (still independent of region/date) on the Paid Media tab; KGA(IDC) is legitimately sparse (122 content LP views) — render, don't hide. Default pixel = view-through site visits (label as reach, not leads); under DNB, Gartner MQ Leader ≈30× any other content asset. |
| `cloudflare` | TTD+LinkedIn+Reddit+LINE + CS + 3 single-campaign LinkedIn dashes (CF1 also has a content-syndication lane) | USD (LINE JPY→USD@155) | 14 | **On the standard pattern since 2026-06-17** (was the lone Snowflake-modelled exception). **CS definitions seed-driven (2026-06-23):** the 12-campaign filter + KR/RIG segment ID sets + RIG assets + market chips + status buckets now live in `definitions.json` → `client_cloudflare.seed_*` (`definitions_seed.py`), read live by `sql/10`+`sql/14`; the SAME file is the single source of truth the status verifier builds its checks from, and is editable from the platform Data Accuracy tab ("Make this live"). FIRST PILOT of the definitions model. BQ now owns the model: staging+model views over `raw_snowflake.*` mirrors + 3 BQ static seed tables (`seed_real_targets`/`seed_tiers`/`seed_line_cf`, pulled once to `data/` — gitignored per `clients/*/data/` — via `pull_static.py`→`seed_static.py`). CS campaign filter (12 IDs) lives in `sql/10_salesforce_leads_live.sql`; CS map is OPPOSITE of mongodb. **KR + RIG are CLIENT-DEFINED CS segments (2026-06-19), not geographic** (in `sql/10` REGION_GRP, carried through `sql/13` `MARKET_REGION=REGION_GRP`): **KR**=Korea + the 6 El* campaigns only (~164); **RIG**=non-Korea + `ASSET_2 IN ('A-MAM-2','A-MAM-3')` (gaming Modernize-Apps asset, only A-MAM-3 populated) + the 3 Final Funnel campaigns (~180) — asset-based so evaluated BEFORE the 5 geographic buckets (pulls leads out of them); a ~42-lead `OTHER` residual drops out of the dash (not in `ALL_MARKETS`). Reference DDL `snowflake_v_salesforce_leads_live.sql` keeps the OLD geographic logic (legacy R2 export) — BQ region logic now diverges. Status dash verifies KR/RIG straight from raw Snowflake. Pacing tier sub-split is non-deterministic in the source model (742 conflicting tier names, 349 tier-ambiguous accepted leads) — headline lead totals are exact, the Tier 2/3/Other split flickers run-to-run as it always did. The `snowflake_v_*.sql` files are now just reference for Cloudflare's OWN legacy R2 export, NOT our pipeline. **CF1 content-syndication lane (2026-06-22):** the "CF1 India" single-campaign view (`campaigns.cf1_india`) now also carries a `cs` block (Double Touch MQLs) from `sql/14_cf1_cs` — the 2 CF1 CS campaign IDs (`701RG00001NJd6NYAT`/`701RG00001NIYRKYA5`, vendors→CaptureIQ→Integrate→Salesforce; ALSO in the core 12-campaign filter, but this is a separate CF1-scoped lane). **Target 110** (the one knob, hardcoded `CF1_CS_TARGET` in `job/main.py`); accepted IS the delivered-MQL count (every lead is double-touch). `DT_CREATED` is a single bulk-load instant — the cumulative-delivery line keys on `DAY`. UI: the CF1 view is split into **LinkedIn Paid Media | Content Syndication tabs** (`setupCmpTabs`/`switchCmpTab`); the tab bar shows only when a campaign has a `cs` block, so peyc/coles_hyper stay a single tab-less LinkedIn view. |
| `stt` | ARCHETYPE — GA4 web traffic vs Google Ads+LinkedIn+DV360 | SGD (USD@1.34) | 28 | `client_Adriatic_Furniture/` is a separate OPEN sample dash — don't copy its no-auth pattern; genuine time-series charts have Month/Week/Day + Relative/Absolute toggles (daily views 25–28) |
| `schneider` | **`client_mongodb`-clone Content-Syndication dashboard** (3 tabs: Paid Media · Content Syndication · CS Comparison) — DV360+TTD+LinkedIn paid delivery + Salesforce CS leads, **scoped to 5 lead-gen programs** | AUD (USD@1.50, SGD@1.15) | 27 (+7 seed tables) | **RESTRUCTURED 2026-06-22** from a 6-tab Pacific paid-media dashboard into a **mongodb clone SCOPED to 5 lead-gen programs** {water_env, eba, heavy, global_rebrand, airset} = the 9 SF campaign IDs in `data/salesforce_map.csv`; the other ~20 APAC programs are GONE from the dash (seed tables keep them for the match_pattern tag). Model: **Campaign**=program (single-select seg), **Programme**=SF `pillar_label`, **Market**=normalized `COUNTRY_NAME` (Australia/NZ/ANZ/Other). Data layer: `sql/17_stg_salesforce` (adds campaign/programme/market; buckets status on **LEAD_STATUS only** — STATUS/LEAD_STATUS_SF are INT64/all-NULL; DAY is already DATE so **NO `DATE()` wrapper**), `18_cs_by_programme`, `19_cs_weekly`, **`20_pm_delivery`** (replicates the old client-side `idOf` match_pattern join IN SQL — first-match-wins across ALL 28 seed rows by `seq`, THEN filter to the 5; market normalized). job emits `campaigns[]` (target=Σ MQL+HQL `lead_target`; `cpl_tiers`=spend÷lead_target per media-plan lead line; committed=Σ lead-line spend; flight from `seed_plan_budget`), `cs_by_programme`, `cs_weekly`, `pm_delivery`, `all_markets`, `window` — **NO GA4** (40–46 apply but unused). 95 in-flight leads (eba 42/water_env 28/heavy 25; all `New` — CRM-raw, not graded MQLs). **Leads are CLAMPED to each program's flight window** (`stg_salesforce` LEFT JOINs `seed_plan_budget` — `DAY` between flight_start/end), so pre-flight spillover is excluded (EBA had 4 leads before its 2026-05-25 start). heavy+global_rebrand have **NO paid delivery** (leads-only). Seeds CSV-loaded (`data/`→`seed_*` via `load_seeds.py`, run BEFORE `create_views.py`). Targets from the media-plan sheet (EBA MQL 157 not 300; W&E/Heavy/EBA budgets changed; NEL added) — flagged in `INTAKE.md`. GATING adds `salesforce_cs_apac_all`. Pacific-carve-out history: `_eda/pacific_eda.md`. The `data/`+`load_seeds.py` CSV-seed pattern is the cross-client template. |
| `hireright` | Pure delivery DV360+TTD+LinkedIn | USD (AUD@0.65) | 16 | No GA4, no media plan |
| `cityperfume` | E-commerce — Neto `v_sales`=revenue truth + Google/Meta/TTD/GA4 | AUD (no FX) | 36 | `dash/` DEFAULTS to **Website-only** (Marketplace excluded — not ad-addressable — still a selectable chip; margin/ROAS/profit track the SELECTED channels via `onlineMargin()`→`chanOk`, NOT the fixed universe). Headline reframed to the **ad spend → attributed revenue → ad-attributed profit** chain ("how many $ did ads make"): attributed revenue = spend ×`REV_ROAS_ONLINE` (7× incremental rev ROAS); profit = ×Website Maropost gross margin (~38.5%) = ~2.69× margin ROAS. **Interim "quick" calc** — real regression/Maropost calc is a follow-up; `7×` is the one knob (`REV_ROAS_ONLINE`). **aggregates-only JSON, no PII**; GA4 degraded since ~Oct 2025 (sessions-by-channel missing programmatic display — follow-up). **TWO web services off ONE pipeline:** `cityperfume-dash` (`dash/`, online-only, default) **+** `cityperfume-total-dash` (`dash_total/`, **all-sales** incl. In-store POS — the *largest* channel ~A$13.5M; **front-end-only fork**, same JSON/SA/secrets/password; headline = blended MER, online-incremental ROAS kept as 2nd lens). Redeploy 2nd: `clients/client_cityperfume/dash_total/deploy_dash_cityperfume_total.ps1`. |
| `resetdata` | B2B Google Ads+Meta+TTD+Reddit vs GA4 (leads, **no revenue/ROAS**) **+ HubSpot CRM** (Signups & CRM tab) | AUD (TTD USD@1.50; Reddit AUD native) | 31 | agency = 100-digital; Meta account filter contains an EN-DASH; Reddit slice `client_slug='resetdata'` (only Reddit client), engagement/video metrics NULL upstream; **Reddit `spend_aud` = raw spend ×2** (intentional agency billed-rate markup — so Reddit sits on a different cost basis than Google/Meta/TTD media cost on shared spend charts); trend charts have Month/Week/Day + Relative/Absolute toggles (daily / ad_campaign_daily / ga4_key_events_daily feeds). **Signups & CRM tab (views 24–30)** reads HubSpot via `raw_windsor.hubspot_contacts`/`_owners` (snapshot, NOT scoped by the ad filters): funnel = leads → app signups (`contact_rd_created_at`) → loaded balance (`rd_billing_balance>0`, mostly the free $50) → paying (`rd_total_spend>0`, 64) → customers; owner ids resolved to names via the owner dim; **HubSpot attribution is thin** (most signups land Offline/Direct) so the `gclid`/`fbclid` "Ad-ID" column + the ad tabs are the real ad attribution. Job also gates on `raw_windsor.hubspot_contacts`. See `clients/client_resetdata/README.md`. |
| `proptrack` | Banking ABM — TTD (advertiser `PopTrack`) + LinkedIn | AUD (no FX) | 15 | TTD impressions come from `IMPRESSION` (singular); LinkedIn `PropTrack_TransmissionSG_AUD` |
| `tlm` | The Little Marionette — e-comm coffee: Google Ads (DTS) search/shopping/PMax + Trade Desk display | AUD (TTD FX@1.50 unused) | 15 | Google spend already AUD (NOT micros); ROAS/CPA Google-only (TTD pixels anonymous, no revenue); light cream+slate-blue theme; `ttd_creative` is whole-flight (not date-scoped); hero/google/perf trend charts have Month/Week/Day + Relative/Absolute toggles (daily + ad_campaign_daily, views 14–15) |
| `vmch` | Villa Maria Catholic Homes — aged-care **NFP** brand awareness: Trade Desk display (4 service-line campaigns RAC/RL/SAH/Disability) vs GA4 website | AUD (no FX) | 26 | SINGLE platform (TTD only) + SINGLE market (`*_market` views are vestigial 'Australia' rows; dash reads flat `kpi`/`monthly`/`ga4_channels_market`); **no revenue** — outcomes are GA4 enquiry key events (phone/email/contact) **+ TTD-attributed conversions**. **Display is upper-funnel** — frame impact as reach + clicks + **post-view/post-click attributed conversions** (`stg_ttd` parses Windsor's double-encoded `conversions` JSON; pixels come in DUPLICATE PAIRS so sum ONLY distinct pixels **{01,03,05}**, NOT 01–05; `conversion_touch_*` = total pixel fires, NOT ad-attributed, never use it; flight totals ≈113 post-view / 13 post-click), NOT last-click "Display" sessions (~25). **`01_stg_ga4.sql` EXCLUDES the `programmatic-display / *` source** — it's non-credible junk (predates spend, 2.5s engagement, 12k Apr sessions from 144 clicks) that GA4 mislabels "Unassigned"; do NOT resurrect it as a "display win". Dashboard **defaults to all-time** (flight Apr 2026 marked by the `flightMarker` Chart.js plugin); **enquiry charts clamp to the flight** (`inFlight()`) because 2025 used a non-comparable GA4 enquiry taxonomy (~110k vs flight 2,736 — would read as a false collapse). orange-red `#EB3300` + maroon `#4C2736` theme; logos inlined via `creatives/inject_logos.py`; trend charts have Month/Week/Day + Relative/Absolute toggles (daily/ad_campaign_daily/ga4_daily_market/ga4_key_events_daily, views 30–33). **Overview tab = combined story:** the `OV` IIFE in `dash/dashboard.html` embeds the standalone `VMCH_Campaign_Analysis.html` retrospective as a HARD-CODED daily array (Oct'25–Mar'26) and stitches it to the live `DATA` (Apr'26 →, contiguous, no overlap) into one continuous timeline — so the Overview's data is NOT purely from `data.json`/the data contract; hero = spend stacked by platform vs sessions + legend-toggleable per-channel imps/clicks lines. **April RAC+SAH delivery is MODELLED** (client monthly totals ÷30/day; `sql/03b_stg_april_modelled.sql` UNION'd into `stg_ad_delivery`, which `04_kpi`/`05_monthly`/`12_weekly`/`30_daily` now read — stray real Apr-30 RAC/SAH slivers dropped, real Apr Disability kept) because TTD's full April never reached Windsor; `stg_ttd` stays pure-measured so `ttd_adgroups`/`ttd_creative` are unaffected. **Dashboard consolidated to ONE page (2026-06-18):** the Trade Desk, Website and Media→Traffic tabs were removed and the keepers folded into the single Overview; campaign selection is the **panel's Campaign chips** (no top-bar dropdown); **Retargeting spend is folded into Disability** in `OV.combined()`; **Enquiries-by-type is now a heat-table** (`renderEnqHeatmap`, one additive column per campaign). The **`STATISTICAL MODEL` campaign-effect panel** (OLS of total sessions on total ad spend over the full Oct'25→ timeline → **additive spend-share attribution**, campaigns sum to the all-campaigns total) and the spend-share-scaled **Sessions trend** moved onto the Overview with it. Dropped: the Overview retrospective sections (first-visits/engagement/ramp/conversion-breakdown/ROAS-LTV/recommendations), the exec summary, the GA4 KPI strip and the "Enquiry events by type" chart — **full detail in `clients/client_vmch/README.md`**. **GA4 source = native DTS with a Windsor fallback** (2026-06-18): VMCH's GA4 Data Transfer (property 287370621) is failing on a permission error (frozen 2026-06-01), so `01_stg_ga4`/`02_stg_ga4_events` read **DTS-first, then `raw_windsor.perf_ga4(+events)` for any missing date** (per-date precedence → no dup; DTS resumes precedence if re-authed). Refresh Windsor via `ingest/windsor_data_pull/ga4/{ga4,events}_loader.py <from> <to>`; gate now also watches the Windsor GA4 tables. Not yet a scheduled job — re-auth the DTS or schedule the Windsor loaders for ongoing freshness. See `clients/client_vmch/README.md`. |

**4 shared ingest units** fill the `raw_*` layers for everyone (no dashboard of their own):
- `ingest/snowflake_data_pull/` → `raw_snowflake` (8 tables, 1:1 mirror). **Self-gating `*/10`** — the exception
  that watermarks BQ `raw_snowflake._sync_state`, not a GCS `_freshness.json` sidecar.
- `ingest/windsor_data_pull/` → `raw_windsor` (Meta, Trade Desk, GA4 +events, Google Ads, Reddit). **Fixed daily**
  Cloud Run jobs (`windsor-meta-ingest`, `windsor-tradedesk-ingest`); Reddit not yet wired; TTD connector down.
  Plus `fields/` → `raw_windsor.windsor_fields`, the **field CATALOGUE** (metadata): all ~37.8k Windsor fields ×
  242 connectors from the public `connectors.windsor.ai/all/fields`, refreshed daily (`windsor-fields-ingest`)
  with `first_seen`/`last_seen` so newly-added fields are queryable.
  Plus `hubspot/` → `raw_windsor.hubspot_contacts` (~4.7k) + `hubspot_deals` (~242) — **Reset Data's HubSpot CRM**
  (connector `hubspot`, account `45274177`), a **WRITE_TRUNCATE snapshot** (CRM state, not a date series; all-STRING
  raw + typed `v_hubspot_*` views). Crown jewel `contact_rd_billing_balance` = the client's **RdBillingBalance**
  custom property; for the (not-yet-built) Reset Data CRM dashboard. **Not scheduled** — run from a laptop. See
  `ingest/windsor_data_pull/hubspot/README.md`.
- `ingest/dts_data_pull/` → `raw_google_ads` + `raw_ga4` via **native BigQuery DTS** (no job; daily, free). 3 bridge views.
- `ingest/neto_data_pull/` → `raw_neto.orders` (City Perfume sales). **Fixed daily** Cloud Run job `neto-orders-ingest`.

**`status_dashboard/`** — meta dash (`status.bidbrain.ai`), no dataset/views; reads the other clients'
resources, self-gating `*/15`. **`scripts/`** — `setup.ps1`, `start_day.ps1`, `deploy_ingest_jobs.ps1`
(deploys the 4 ingest jobs as `ingest-runner@`). For anything client-specific, open `clients/client_<c>/README.md`.

## Dashboard edits — the common task. READ THIS FIRST.
Each client's UI is ONE big file: `clients/client_<c>/dash/dashboard.html` (~1,300–2,400 lines).

- **Do NOT read, reformat, or edit the logo blocks.** They are static, enormous, and never
  change: a wall of `<svg … aria-label="…"><path …></svg>` (STT, MongoDB) or an inline
  `<img src="data:image/jpeg;base64,…">` (Cloudflare). The STT logo SVG is **duplicated** in
  `clients/client_STT/dash/main.py` (LOGIN_HTML) — same rule there.
- **grep to the target** (a chart canvas `id`, a KPI element `id`, a render function name)
  and edit in place. Don't slurp the whole file to change a colour/label/card.
- Pure visual tweaks (colours, labels, spacing, a new card) live entirely in `dashboard.html`.
  Colours are CSS vars in `:root` at the top.
- **Time-series charts carry a grain + scale toggle (all 10 clients).** Every genuine time-series
  line/bar/mixed chart has a `.seg` "VIEW BY" Month/Week/Day control and an "AXIS" Relative/Absolute
  control (**default Relative**). Relative indexes overlay LINE series to peak=100 on a shared 0–100
  axis (or 100%-stacks pure-composition bars); tooltips always show the TRUE value. Categorical /
  Gantt / scatter / doughnut / YoY / synthetic-series charts are intentionally excluded. Reference
  impls: `clients/client_resetdata` + `clients/client_tlm`. The 6 ex-month/week clients (stt,
  schneider, hireright, resetdata, tlm, vmch) gained daily SQL views (`*_daily`) to back the Day grain;
  cloudflare/cityperfume/mongodb/proptrack already shipped daily data so they are frontend-only.

## The data contract — when an edit needs NEW data, not just layout
A value on screen traces through three files, matched **by name**:

    sql/*.sql view column  →  job/main.py (the env={…} dict key)  →  dashboard.html (data.* key)

So "add metric X" is usually three edits: surface it in the right `sql/*.sql` view, expose it
in `job/main.py`, THEN render it in `dashboard.html`. Editing only the HTML renders nothing.
Renaming a key anywhere breaks the next stage — fix both ends.

## Redeploy after an edit — manual. Do NOT use cloudbuild from a laptop.
`gcloud builds submit --config .../cloudbuild.yaml` FAILS from a laptop
(`iam.serviceaccounts.actAs` — Cloud Build's SA can't act as the runtime SA). Those configs
are for a future push-to-main trigger. Build the image, deploy as yourself.

**Prefer the per-stage scripts** — each now lives in the stage subfolder it deploys and wraps
exactly the commands below (self-contained, paths resolve from `$PSScriptRoot`, idempotent).
Reach for the matching one by edit:
- `dash/deploy_dash_<c>.ps1`   — edited `dash/dashboard.html` or `dash/main.py` → rebuild + update SERVICE
- `job/deploy_job_<c>.ps1`     — edited `job/main.py` (JSON shape) → rebuild + deploy + run JOB
- `sql/deploy_views_<c>.ps1`   — edited a `sql/*.sql` view → reapply views (`create_views.py`) + run JOB
- **Platform front-door:** `bidbrain-platform/dash/deploy_dash_platform.ps1` — edited `main.py`/`store.py`/
  templates → rebuild + update SERVICE. Standup once with `bidbrain-platform/deploy_platform.ps1`; then
  `scripts/enable_platform_sso.ps1` injects `SSO_SECRET`+`CLIENT_KEY` into the 10 dashboards. **For the
  super-admin god-mode console, after deploying the new image run `scripts/enable_super_admin.ps1` once**
  — it creates the bootstrap secret + mounts `SUPER_ADMIN_PW`/`REGION` on the platform and grants the
  platform SA the extra IAM for dashboard-password rotation (secretVersionAdder + project run.developer +
  serviceAccountUser on each `<c>-dash` runtime SA). Agency/client/campaign DATA + all password reveals/
  rotations are done in the UI, NOT by redeploy. See `bidbrain-platform/README.md`.

The one-shot `deploy_<c>.ps1` (still at the `clients/client_<c>/` root) is only for first-time standup (APIs, SAs, IAM, secrets,
scheduler). The raw commands each stage script runs, for reference:

    # edited dashboard.html or dash/main.py → rebuild + redeploy the SERVICE:
    $IMG = "australia-southeast1-docker.pkg.dev/bidbrain-analytics/bidbrain/<c>-dash:$(git rev-parse --short HEAD)"
    gcloud builds submit clients/client_<c>/dash --tag $IMG --region australia-southeast1
    gcloud run services update <c>-dash --image $IMG --region australia-southeast1

    # edited a sql/*.sql view → reapply views + re-run the JOB (no service redeploy):
    .\.venv\Scripts\python.exe clients\client_<c>\create_views.py
    # FORCE_REBUILD=1 is REQUIRED: a view edit does NOT advance the upstream tables the
    # freshness gate watches, so without it the job exits 0 and skips the rebuild (stale JSON).
    gcloud run jobs execute <c>-export --region australia-southeast1 --update-env-vars FORCE_REBUILD=1 --wait

    # edited job/main.py (the JSON shape) → rebuild + deploy + run the JOB:
    $IMG = "australia-southeast1-docker.pkg.dev/bidbrain-analytics/bidbrain/<c>-export:$(git rev-parse --short HEAD)"
    gcloud builds submit clients/client_<c>/job --tag $IMG --region australia-southeast1
    gcloud run jobs deploy <c>-export --image $IMG --region australia-southeast1 `
      --service-account <c>-dash-job@bidbrain-analytics.iam.gserviceaccount.com --memory 1Gi
    # FORCE_REBUILD=1 as above — a new image is not a new upstream watermark, so force the rebuild:
    gcloud run jobs execute <c>-export --region australia-southeast1 --update-env-vars FORCE_REBUILD=1 --wait

The service serves `dashboard.html` with `Cache-Control: no-store`, so a redeploy shows
immediately. The service always reads whatever JSON is currently in the bucket.

## Freshness contract (binding — definition-of-done for every export job + `ingest/snowflake_data_pull`)
Every dashboard must refresh **within ~10 min of its upstream data updating**, NOT on a fixed daily
cron. The mechanism is a SELF-GATING job: on a frequent (`*/10` UTC) Cloud Scheduler tick it cheaply
checks whether the upstream it reads has new data and only does the full rebuild + upload when
something advanced. A job is **not "done"** until it satisfies 1–4.

1. **Self-gating.** Probe upstream freshness; rebuild + upload ONLY when an upstream object advanced
   past its stored watermark — otherwise exit 0 without pulling or uploading. Honor `FORCE_REBUILD=1`
   to bypass the gate for manual runs.
2. **Gate source = whatever the job READS** (derive from the code, never guess):
   - **Snowflake-direct** (`ingest/snowflake_data_pull` only) → probe Snowflake PUBLIC
     `INFORMATION_SCHEMA.TABLES.LAST_ALTERED`. Metadata-only — **no warehouse credits, never resumes
     `APAC_IN_WH`**.
   - **BigQuery-reading** (every client, incl. `client_cloudflare` since 2026-06-17, via `raw_snowflake` /
     `raw_windsor` / `raw_ga4` / `raw_google_ads` / `raw_neto` mirrors) → probe `__TABLES__.last_modified_time`.
   Never watermark a **VIEW** (its `LAST_ALTERED` only moves on DDL) — watermark the base/mirror
   TABLES the views read.
3. **Watermark** = a tiny JSON sidecar in the client's own GCS bucket (`_freshness.json`).
   `ingest/snowflake_data_pull` instead keeps a per-table BQ `raw_snowflake._sync_state` (refresh table T
   iff T advanced). Order matters: **upload first, write watermark second**, so a failed upload
   simply retries next tick.
4. **Schedule** = Cloud Scheduler `*/10 * * * *` UTC (tunable; parameterize the scheduler script). No
   dashboard may hardcode a fixed refresh time in its copy — show `last_updated` (build time) and
   `data_through` (newest upstream `LAST_ALTERED`/`last_modified`, UTC) instead.
5. **New clients inherit this by copying the template:** vendor `freshness.py` into `job/` (add it to
   the Dockerfile `COPY`), set `GATING_TABLES` + `WATERMARK_OBJECT`, add the gate to the top of
   `main()`, write the watermark after a successful upload, and flip the scheduler to `*/10`.

**Helper:** `freshness.py` (vendored per job folder, like `sf_connect`) —
`probe_snowflake_last_altered(cn, names)`, `probe_bq_last_modified(bq, ["dataset.table", …])`,
`read_watermark`/`write_watermark` (GCS sidecar), `is_stale(observed, watermark)`. It does **no heavy
top-level imports**; keep `pandas`/`pyarrow` off the no-op tick's import path (lazy-import on the
rebuild path) so an idle tick stays a light, fast container.

**Cost:** the driver is rebuild WAKE episodes + `APAC_IN_WH`'s 600s auto-suspend idle tail, NOT the
`*/10` polling (metadata probes never resume the warehouse; BQ-reading jobs never touch it). If the
idle tail ever becomes material, an optional dedicated XS export warehouse at `auto_suspend=60s`
would cut it (needs SYSADMIN; do **not** change `APAC_IN_WH`'s shared 600s auto-suspend).

**Static re-seeds** (e.g. `seed_static.py`) change inputs the gate does NOT watch — so you MUST force
the rebuild, or the job exits 0 without re-exporting: `gcloud run jobs execute <c>-export --region
australia-southeast1 --update-env-vars FORCE_REBUILD=1 --wait`. (`--update-env-vars` is a per-execution
override and does NOT persist on the job.) The same applies after any view-only or `seed_static` change.

## Never
- Never commit secrets/keys (`*.p8`, `*credentials*.json`, `.env`, bare `*_key`). They live in
  Secret Manager + the local `bidbrain-vault/` (gitignored).
- Never make the data JSON public. The private bucket + the Flask password gate IS the security
  model — don't regress to the old public-R2 pattern.
- Never edit views in the BigQuery console. `sql/*.sql` is the source of truth or they drift.

## Keep this file current — definition of done (IMPORTANT)
Updating the docs is part of finishing the work, not an afterthought. **After ANY change, before you
report done, update whatever this change just made stale — in the SAME change.** This file (CLAUDE.md)
is the canonical agent doc; the per-folder `README.md`s carry the detail. Concretely:

- **Changed what a client reports / its currency / view count, or added a client or ingest unit?**
  Fix the row in **What's in the repo** above AND that folder's `README.md`.
- **Changed a deploy step, a script name, or a command?** Fix the matching block in **Redeploy after an
  edit** above — this file is the single source of truth for deploy commands; the READMEs only link here.
- **Changed the freshness mechanism** (gate source, watermark, schedule, `freshness.py` signature)?
  Update the **Freshness contract** above + the client's `job/README.md`.
- **Renamed or added a data key?** The 3-stage contract is matched BY NAME — fix `sql` → `job/main.py` →
  `dashboard.html` in the same change (renaming one stage breaks the next).
- **Hit a non-obvious gotcha** a future session would get wrong? Add ONE terse line to the right place —
  repo-wide here, single-client in `clients/client_<c>/README.md`. **Volatile status (a date, a live URL,
  "verified on…") goes in a README, never in CLAUDE.md** (it rots, and a wrong instruction is worse than none).
- **Found a stale instruction** (a path/command/file that no longer exists)? Fix or delete it now.
- Edit in place and merge into the right section. **Do NOT create new summary / notes / changelog `.md`
  files** to record what you did — the git commit is the changelog. Keep this file lean (≈150 lines);
  push depth into the folder READMEs and link to them rather than inlining it here.

> Doc home, decided 2026-06-13: **CLAUDE.md is canonical** because Claude Code reads it natively (it does
> NOT read `AGENTS.md`). If a non-Claude agent (Cursor/Codex/Copilot) ever works this repo, move the
> shared rules into `AGENTS.md` and make `CLAUDE.md` a one-line `@AGENTS.md` pointer — do not symlink on
> Windows, and never keep two copies of the same prose.