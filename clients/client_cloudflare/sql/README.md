# client_cloudflare — BigQuery view definitions (DDL)

The export job ([../job/main.py](../job/main.py)) reads the **final** views here to
build `cloudflare.json`. Apply them with `python clients/client_cloudflare/create_views.py`
(runner one level up; the `NN_` prefix encodes dependency order).

**Plain English:** these files hold Cloudflare's business logic — **BigQuery owns the
model** now (since 2026-06-17), exactly like every other client. They were ported from
the Snowflake `CLOUDFLARE_SANDBOX.*` views and read the shared `raw_snowflake.*` mirrors
+ the `client_cloudflare.seed_*` static tables. (Previously these were *thin* pass-throughs
of a Snowflake-modelled `src_*` copy — that exception is gone; see
[../README.md](../README.md#bigquery-owns-the-model-was-the-snowflake-modelled-exception).)

**Where this sits:** `raw_snowflake.*` mirrors + `seed_*` static → **[these views]** →
`cloudflare.json`.

## Views (dependency order)

| file | view | reads | ported from (Snowflake) |
|---|---|---|---|
| `01_stg_linkedin.sql`        | `stg_linkedin`        | `raw_snowflake.linkedin_ads_apac` (ACCOUNT_NAME='Cloudflare APAC') + `CAMPAIGN_NAME_NORM` + `PROGRAM` | `V_STG_LINKEDIN_CF` |
| `02_stg_reddit.sql`          | `stg_reddit`          | `raw_snowflake.reddit_ads_apac_all` (ACCOUNT_NAME='Transmission_Cloudflare') | `V_STG_REDDIT_CF` |
| `03_stg_tradedesk.sql`       | `stg_tradedesk`       | `raw_snowflake.tradedesk_apac_all` (ADVERTISER_NAME='Cloudflare') + campaign-name parsing **off `CAMPAIGN_NAME_NORM`** + `PROGRAM` | `V_STG_TRADEDESK_CF` |
| `04_stg_line.sql`            | `stg_line`            | `seed_line_cf` (static) | `V_STG_LINE_CF` |
| `05_paid_media_model.sql`    | `paid_media_model`    | the four `stg_*` (union, **`PROGRAM` as col 2**, market CASE, week key, JPY→USD@155) | `V_PAID_ADS_FINAL_MODEL` |
| `06_paid_creatives_model.sql`| `paid_creatives_model`| the four `stg_*` at creative grain (**+ `PROGRAM`**) | (was `PAID_CREATIVES_SQL` in the job) |
| `07_benchmarks_channel.sql`  | `benchmarks_channel`  | — (literal constants) | `V_BENCHMARKS_CHANNEL` |
| `08_benchmarks_market.sql`   | `benchmarks_market`   | — (literal constants) | `V_BENCHMARKS_MARKET` |
| `09_li_weekly_targets.sql`   | `li_weekly_targets`   | — (literal constants) | `V_LI_WEEKLY_TARGETS` |
| `10_salesforce_leads_live.sql`| `salesforce_leads_live`| `raw_snowflake.salesforce_cs_apac_all` (the 13-ID CS filter + region/publisher/offer; **KR + RIG are client-defined, not geographic** — see below) | `V_SALESFORCE_LEADS_LIVE` (region logic now DIVERGES) |
| `11_tier_mapping_cleaned.sql`| `tier_mapping_cleaned`| `seed_tiers` (static) | `V_TIER_MAPPING_CLEANED` |
| `12_targets_v2_norm.sql`     | `targets_v2_norm`     | `seed_real_targets` (static) | `V_TARGETS_V2_NORM` |
| `13_pacing_model.sql`        | `pacing_model`        | `salesforce_leads_live` + `tier_mapping_cleaned` + `targets_v2_norm` | `V_PACING_FINAL_MODEL` |
| `14_cf1_cs.sql`              | `cf1_cs`              | `raw_snowflake.salesforce_cs_apac_all` (the 2 CF1 content-syndication campaign IDs; publisher/region/topic + status bucket per `DAY`) | new (2026-06-22; client query) |
| `15_cs_qoq.sql`              | `cs_qoq`              | `salesforce_leads_live` (Q3-to-date vs the same opening window of Q2, accepted leads by market/status) | new (2026-07-14) |
| `16_stg_cs_leads_v2.sql`     | `stg_cs_leads_v2`     | `raw_snowflake.salesforce_cs_apac_all` scoped by **campaign NAME** (`STARTS_WITH('2026_Q3')`), not the 13-ID allowlist — which is what brings **EMEA** in. theatre / **book** / market / vendor / theatre-anchored `WEEK_START`; theatre placed by the `seed_cs_emea_campaign_ids` / `seed_cs_campaign_ids` **id allowlists first** (2026-09-05), then the id name-vote, then the per-lead token, never defaulted. **Parallel to `10_*`, which is untouched.** | `CS_REPORTING.V_CS_LEADS_V2` |
| `17_cs_pacing_v2.sql`        | `cs_pacing_v2`        | `stg_cs_leads_v2` + `seed_cs_targets_q3` (FULL OUTER JOIN, **book** × week × market × vendor, aggregated / PII-free) | `CS_REPORTING.V_CS_PACING_V2` |

| `18_cs_compare_v2.sql`       | `cs_compare_v2`       | `stg_cs_leads_v2` (day × market × country × service × asset, both theatres; NO targets) — the EMEA CS Comparison panels | — |
| `19_cs_composition_v2.sql`   | `cs_composition_v2`   | `stg_cs_leads_v2` (theatre × book × vendor × market × **dim × value**, LONG format, campaign to date, accepted + New) — the five composition donuts off-theatre; each dim sums to `cs_pacing_v2` accepted per (theatre, book), asserted by the job | — |

### 16 + 17 — the "Pacing detail" pair (2026-08-24)

Feed the **Pacing detail** section on the Content Syndication tab (APAC + EMEA). They are a
**second, parallel read** of the same raw mirror as `10_salesforce_leads_live`, which is
deliberately left alone: `10_*` is scoped by the campaign-ID allowlist, which makes it
**APAC-only** (verified 2026-08-24: 5,873 rows, **zero** EMEA), and every headline CS figure,
donut, QoQ number and status-dashboard accuracy check hangs off it. Nothing downstream of
`10_*` reads `16`/`17`, so they cannot move a live number.

Five things to know before editing them:

- **PACING IS `ACCEPTED / TARGET`. Delivered is a count, never a pacing basis** (2026-09-03, Jade).
  `IS_DELIVERED` is `Accepted|Rejected` — the *reviewed* leads — so it is the right denominator for
  the acceptance and rejection RATES (they sum to 100%) and the right numerator for a "how much has
  this publisher delivered" count. It is the WRONG numerator against a TARGET, because the plan is
  bought in accepted leads. `17_*`'s `WEEKLY_PACING` divided DELIVERED by TARGET while
  `LEAD_DEFICIT` in the same `SELECT` measured ACCEPTED, so the two columns disagreed by a week's
  rejections; fixed 2026-09-03. Neither column reaches the dashboard (`job/main.py` carries only the
  counts, deliberately — the rates are grain-specific and must never be summed), so that fix is for
  ad-hoc queries against the view. The dashboard's own basis is covered in the client README →
  "One basis for every pacing figure".

- **`BOOK` is a dimension, and it is not the same thing as `THEATRE`** (added 2026-08-27 with the
  regional campaigns). `Core DG` is the bought plan the seeded targets cover; `Regional` is the
  ANZ DnB book (DemandAI / Interlink, and SitPub when it starts delivering), which runs in ANZ —
  i.e. inside APAC, on the same Monday anchor — so it is a second *plan*, not a second *region*.
  It is on the JOIN key in `17_*` and in the seed CSV, which is what stops Regional delivery from
  being paced against a Core DG target. Its `CASE` in `16_*` lists the Core DG programmes
  **explicitly** and sends anything else to `Unclassified` rather than defaulting to Core DG: the
  Core DG target is fixed at 2,290 / 830, so a new programme folded in would inflate delivery
  against a target that never grew. The job log names anything that lands in `Unclassified`.

- **The week math is not the Snowflake original.** `MOD(x,7)` returns a *negative* for a day
  before the anchor, which lands `WEEK_START` **after** the lead date. Live cases: 26 EMEA
  leads dated `2026-08-06` (one day before the Friday anchor — 8.5% of EMEA delivery) and 5
  APAC leads back to March. `16_*` uses `MOD(MOD(x,7)+7,7)` plus a `GREATEST(..., anchor)`
  clamp, so pre-anchor leads fold into week 1 instead of inventing a week outside the 13-week
  grid the dashboard renders. That clamp is what keeps **sum-of-weeks == campaign-to-date
  total** (EMEA 234, APAC 1,591). Remove it and the two silently stop reconciling.
- **`THEATRE` is resolved from `CAMPAIGN_ID` first, the name second, and is NEVER defaulted**
  (2026-09-04). The port read it off the token prefix with `ELSE 'APAC'`, so Acquisition's
  `VER-FINANCE` campaigns - named `2026_Q3_DACH_ACQUISITION_...` with no `EMEA-` prefix - put 64
  EMEA leads on the APJ lane. Now the `id_theatre` / `id_resolved` CTEs vote each id's theatre from
  its unambiguous name forms (>= 80% one side), the name is the fallback, and anything left is
  `UNRESOLVED` - carried, counted, WARNed by the job and shown in Admin View, on neither lane.
  `REGION_SOURCE` / `REGION_CONFLICT` are the audit columns. The market `CASE` accepts EMEA tokens
  with or without the prefix; a name market from the other theatre than the id becomes `UNMAPPED`
  + `REGION_CONFLICT=1`. Full detail: client README -> "EMEA Acquisition leads were counted as APJ".
- **The accepted bucket is the CLIENT's** (`Accepted|Replied|Unresponsive`, as in `sql/10`, `sql/15`
  and the status verifier), not the Snowflake port's bare `Accepted` (2026-09-04). Zero effect today;
  it stops the KPI strip and this band splitting the day a post-acceptance status appears. The
  matching legacy-side fixes (VRSM into `segments.KR`, the quarter clamp on `DAY`) are in the client
  README -> "Headline vs Pacing detail: the 1,650 / 1,661 fix".
- **The scope predicate is `STARTS_WITH`, never `LIKE '2026_Q3%'`** — `_` is a LIKE wildcard
  (repo-wide rule). A no-op today at 1,974 rows either way; forward protection.
- **The fixed `SPLIT` offsets are anchored to the `2026_Q3` token.** If those Salesforce
  campaign names ever gain a brief-number prefix, `STARTS_WITH` stops matching and the view
  returns **zero** rows — a total, loud failure rather than the silent one-field shift that
  bit mongodb. `job/main.py` warns when the raw mirror has `2026_Q3` rows but the view has
  none, so it surfaces in the job log.

Targets come from the **version-controlled** `targets/cs_targets_q3.csv` →
`seed_cs_targets_q3` (`seed_static.py`), totals **APAC 2,290 / EMEA 830** — every row `BOOK`
`Core DG`, because that is the only book the client has ever issued a pacing sheet for. A
regional sheet is CSV rows and no code change. Its `MARKET_SEQ`
column is the chart's market **display order** — re-order the CSV, re-seed, and the chart
follows with no code change. That is what keeps the dashboard component free of a hardcoded
market list. Reconciles exactly to the client's pacing sheet: EMEA delivered 234 / accepted
208 / rejected 26, `NEEDS_REVIEW` 0 in both theatres.

## Porting notes (Snowflake → BigQuery)

- `TRUNC(d,'WEEK')` / `DATE_TRUNC('WEEK',d)` → `DATE_TRUNC(d, WEEK(MONDAY))` (Snowflake weeks start Monday — verified).
- `ILIKE '%x%'` → `LOWER(col) LIKE '%x%'`; `LIKE 'CLOUD\_ACQ\_%' ESCAPE` → `STARTS_WITH(...,'CLOUD_ACQ_')`.
- `SPLIT_PART(s,'_',N)` → `IFNULL(SPLIT(s,'_')[SAFE_OFFSET(N-1)], '')` (mirror Snowflake's empty-string-on-overflow).
- **NEVER parse a campaign name by fixed offset off the RAW name — use `CAMPAIGN_NAME_NORM` (2026-08-04).**
  Campaign names progressively gain a leading `"<brief>_"` token (`1160_`, `2103_`, `2265_`, `2479_` …) as
  briefs roll out, which shifts every field one position. `stg_tradedesk` / `stg_linkedin` strip it once
  (`REGEXP_REPLACE(TRIM(CAMPAIGN_NAME), r'^[0-9]+_', '')`) and every downstream token, `STARTS_WITH` and
  market `CASE` keys off that. Before the fix TTD `MARKET_L3` read `APAC-ANZ` instead of `ANZ`, which is
  non-empty so the rows survived `paid_media_model` but matched no dashboard chip and vanished from every
  KPI, chart and table. The SAME campaign also exists under BOTH name forms in the feed (15 raw names →
  8 real campaigns for the Q3 MDS line), so the halves never summed. Cost: 4,989,809 imps invisible, plus
  7,360,518 more dropped outright because the short-form DOOH / High Impact names have no offset-8 token
  (now recovered via a `" - AU"/" - NZ"/" - ANZ"` suffix fallback). Total 36,053,269 imps now render, vs
  23,702,942 before. The reference check is Ian's normalised-name pull: the 8 `*_MDS_TTD_*COREDG-Q3`
  campaigns = **5,516,027 imps / 4,788 clicks / $14,499.98**.
- **`PROGRAM` splits the paid book into the dashboard's two lanes (2026-08-14).** `CORE_DG` (briefs
  1160 / 2103 Q2 / 2479 Q3) or `SURROUND_ABM` (brief **2193**, Trade Desk only — 5 campaigns named
  `..._<MKT>-SURROUND-ABM`). Defined ONCE, identically, in `03_stg_tradedesk.sql` and
  `01_stg_linkedin.sql`; `05` carries it as **column 2 of every union arm** (the union is `SELECT *`,
  so position matters) and `06` carries it too, because creative rows have no date and nothing else
  could separate them. LinkedIn/Reddit repeat the rule defensively (neither has Surround ABM delivery
  today); LINE is a constant `'CORE_DG'` (manual CSV, no campaign names).
  It is a **substring match on the RAW name** (`'%surround%abm%'`, plus a `2193_` prefix arm), never a
  fixed offset — the same rule as the prefix fix above, and it spans both name vintages in the feed.
  The `ELSE` is `CORE_DG`, so a brand-new brief joins Core rather than disappearing; splitting it out
  is one extra `WHEN` here plus one entry in `PROGRAMS` in `dash/dashboard.html`.
  **Adding an arm moves numbers out of Core DG** — that is the point, but say so before shipping.
  The export job prints a per-program rows/imps/spend line every run, which is the cheap check that
  the parse still works.
- `REGEXP_REPLACE(...,'i')` → RE2 `(?i)` inline flag; `UUID_STRING()` → `GENERATE_UUID()`; `QUALIFY` is native.
- The 13-ID CS campaign filter lives in `10_salesforce_leads_live.sql` (this is now its source of truth, not the Snowflake view).
- **KR + RIG are client-defined CS segments (2026-06-19), redefined in `10_salesforce_leads_live.sql`'s `REGION_GRP`** — they are NO LONGER purely geographic, and the BQ region logic now DIVERGES from the reference Snowflake view (`snowflake_v_salesforce_leads_live.sql`, which keeps the old geographic logic for Cloudflare's own legacy R2 export):
  - **KR** = Country `'Korea, Republic of'` **AND** a Core DG CS campaign: the 6 ORIGINAL El* campaigns (3 Roverpath + 3 Final Funnel) + the Q3 VRSM Lead Magnet campaign since 2026-09-04 (seed-driven via `seed_kr_campaign_ids`, 7 IDs - see the client README's 1,650 / 1,661 gotcha). Korea leads from the Connectivity-Cloud / Modernize campaigns are excluded → land in `OTHER`. (~164 leads.) **Reverted to this rule 2026-07-02** at the client's request (between 2026-06-25 and 2026-07-02 KR was ALL Korea in the 12 campaigns).
  - **RIG** = **NON-Korea AND** `ASSET_2 IN ('A-MAM-2','A-MAM-3')` (the gaming-vertical Modernize-Applications asset; only `A-MAM-3` has data today) **AND** the 3 Final Funnel campaigns. RIG is asset-based, spans every country, and is evaluated **before** the five geographic buckets — so it pulls those leads out of ANZ/ASEAN/SAARC/GCR/JP (intentional overlap). (~180 leads.)
  - The geographic regions stay purely geographic (split to the 11-market grain in the 2026-06-25 rework — AU/NZ, SIM/RoA, GCR-CN/TW/HK — and case-normalised so mis-cased countries route to their real market). A residual **`OTHER`** bucket (~55 leads: Korea outside the KR campaigns) is NOT one of the dashboard's 11 market chips, so it is excluded from the dash — the headline totals sum over the chips, so there is no total-vs-sum drift on screen (the ~55 leftover Korea leads simply aren't counted anywhere on the dash). `13_pacing_model.sql` sets `MARKET_REGION = REGION_GRP` verbatim (the old "Computer Games + Tier 2 → RIG" override was removed so RIG equals the exact client def). Verified live 2026-07-02: KR 164 / RIG 180 / OTHER 55 (total Korea 219 = 164 + 55); the status dashboard reproduces KR/RIG and reconciles the `OTHER` residual straight from Snowflake.
- **`14_cf1_cs.sql` is a separate CF1-scoped content-syndication lane (2026-06-22)**, not part of the ported pacing model. It filters the same `raw_snowflake.salesforce_cs_apac_all` to the **2 CF1 CS campaign IDs** (`701RG00001NJd6NYAT` Roverpath + `701RG00001NIYRKYA5` Final Funnel CF1) — which are ALSO in the core 13-ID filter (`10_salesforce_leads_live.sql`), where they feed the geographic pacing model. This lane mirrors the client's exact query (Total = New+Accepted, Accepted, Rejected) against a **110 Double Touch MQL target**. Every lead is a double-touch lead (CAMPAIGN ends in "Double Touch"; ASSET_1 AND ASSET_2 both populated), so accepted = delivered MQLs. Publisher/region/topic are parsed from the CAMPAIGN string; grain is per-`DAY` (the per-lead delivery date — `DT_CREATED` is a single bulk-load instant with no daily signal). The job (`job/main.py`) reads it into `campaigns.cf1_india.cs`.
- **`pacing_model` tier sub-split is non-deterministic** (inherited from the source model — see [../README.md](../README.md#bigquery-owns-the-model-was-the-snowflake-modelled-exception)). Dummy rows use `GENERATE_UUID()` so their `LEAD_ID_SF` differs each run (always `DUMMY_*`, excluded from lead counts).

## See also

- [`../README.md`](../README.md) — client overview + the cutover/parity notes.
- [`../job/README.md`](../job/README.md) — reads these views; documents the JSON contract.
- [`../../client_mongodb/sql/README.md`](../../client_mongodb/sql/README.md) — the template's views.
