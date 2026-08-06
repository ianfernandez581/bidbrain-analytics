# Scoping Standardization - Transmission Clients - Verification Report

**Date:** 2026-08-06
**Scope:** Cloudflare, Schneider Electric, Schneider LQAI, MongoDB, STT GDC, PropTrack, HireRight.
100% Digital clients untouched (separate task; observations at the end).
Companion docs: the audit that motivated this ([md/CAMPAIGN_SCOPING_AUDIT_2026-08-06.md](CAMPAIGN_SCOPING_AUDIT_2026-08-06.md)) and the new SOP ([docs/SCOPING_STANDARD.md](../docs/SCOPING_STANDARD.md)).

All numbers below are from BigQuery on 2026-08-06, measured as the exact filter the view/job runs (spend = feed-native `COSTS`, unconverted).

---

## Fix 1 - STT Google Ads: campaign-name LIKE -> customer-account IDs (APPLIED, commit `09c931a`)

**File:** `clients/client_STT/sql/03b_stg_google.sql`
**Filter:** `WHERE CAMPAIGN_NAME LIKE '%STT%'` -> `WHERE ACCOUNT_ID IN ('1641370256', '4825242697')`

| | rows | spend | min day | max day | distinct campaigns |
|---|---|---|---|---|---|
| Before (name LIKE) | 49,648 | $100,333.17 | 2025-06-11 | 2026-08-01 | 22 |
| After (account IDs) | 49,648 | $100,333.17 | 2025-06-11 | 2026-08-01 | 22 |
| Delta | **0** | **0** | - | - | 0 |

The name LIKE was **dropped**, not kept as a second condition, per the task rule (account filter alone returns identical rows, so the LIKE only added risk).

**Why ID and not account NAME:** the shared `google_ads_apac` table revealed that account `4825242697`'s name was itself **renamed on the platform** - `STT GDC_SGD` (rows to 2026-05-30) -> `STT Global Data` (rows from 2026-05-31). A name-based account filter would have silently lost everything after May 31. Names rot at every level; the two ACCOUNT_IDs cover all three name variants.

**Mirrors moved in the same commit:** status-dash STT Google Ads checks (4 SQL filters in `status_dashboard/job/main.py`, now consistent with the LinkedIn/DV360 checks which were already ID-based), `clients/client_STT/README.md`, `clients/client_STT/sql/README.md`.

---

## Fix 2 - Cloudflare single-campaign LinkedIn dashes: prefix-normalised + account-scoped (APPLIED, commit `fb387e9`)

**File:** `clients/client_cloudflare/job/main.py` (the `li_sql` string)
**Filter:** `WHERE CAMPAIGN_GROUP_NAME IN (3 exact literals)` -> `WHERE REGEXP_REPLACE(TRIM(CAMPAIGN_GROUP_NAME), r'^[0-9]+_', '') IN (same literals) AND ACCOUNT_NAME = 'Cloudflare APAC'`, with the SQL returning the **normalised** name so the downstream per-group split is unchanged.

Measured as the job query's aggregated output (day x group x campaign grain):

| | out rows | spend | imps | min day | max day |
|---|---|---|---|---|---|
| Before (exact names) | 450 | $45,382.74 | 910,994 | 2026-04-30 | 2026-06-30 |
| After (normalised + account) | 450 | $45,382.74 | 910,994 | 2026-04-30 | 2026-06-30 |
| Delta | **0** | **0** | 0 | - | - |

**Recovery quantified - $0.00 for all three groups, and here the data disagrees with the task brief's framing.** The brief expected the dashes to be "returning zero rows today" because of the platform renames. In fact:

| Group | rows (any name form) | spend | last delivery |
|---|---|---|---|
| ANZ-PEYC | 1,202 | $26,105.27 | 2026-06-30 |
| CF1-Integrated | 161 | $6,226.82 | 2026-06-30 |
| Hyper_COLES | 590 | $13,050.66 | 2026-06-30 |

The Snowflake mirror contains **no prefixed (`2388_`/`2356_`/`2413_`) rows at all** - historical rows still carry the original names, so the exact match was still returning the complete history. All three Q2 groups stopped delivering exactly at quarter end (2026-06-30) while the Cloudflare APAC account feed overall is fresh through 2026-08-05. So the dashboards were showing full history, not zeroes - and per the task's own rule, "still zero after the fix" means **genuinely absent, not misnamed**: the paused PEYC/COLES are simply done, and CF1-Integrated ("Active" per the export) has not delivered since 06-30 under any name form. If CF1 resumes under its `2413_` name, the normalised match now picks it up automatically - that is the value of this fix.

---

## Fix 3 - PropTrack TTD: span both advertiser spellings (APPLIED, commit `a44255e`) - EXPECTED MOVEMENT

**File:** `clients/client_proptrack/sql/01_stg_tradedesk.sql`
**Filter:** `WHERE ADVERTISER_NAME = 'PopTrack'` -> `WHERE LOWER(TRIM(ADVERTISER_NAME)) IN ('poptrack', 'proptrack')`

State report first, as mandated - the dashboard was **not dead, but frozen**:

| Advertiser name in feed | rows | spend | min day | max day |
|---|---|---|---|---|
| `PopTrack` (what the old filter caught) | 9,180 | $17,112.80 | 2026-05-20 | **2026-07-21** |
| `PropTrack` (invisible to the old filter) | 233 | $1,724.88 | **2026-07-22** | 2026-08-05 |

TTD corrected the advertiser's misspelling on-platform on **2026-07-22** (matching the Grid's 2026-07-23 observation of the rename starting; the corrected advertiser has since become the only one emitting spend). The old filter had been blind to **15 days of delivery ($1,724.88)**.

| | rows | spend | min day | max day | distinct campaigns |
|---|---|---|---|---|---|
| Before | 9,180 | $17,112.80 | 2026-05-20 | 2026-07-21 | 3 |
| After | 9,413 | $18,837.67 | 2026-05-20 | 2026-08-05 | 3 |
| Delta | **+233** | **+$1,724.88** | - | **+15 days** | 0 |

Double-count check: the two spellings' date ranges are **disjoint** (07-21 / 07-22 boundary), so spanning both cannot double-count. The change is name-keyed (not `ADVERTISER_ID = 'gb75r2p'` as the brief prescribed) because the mirror has no ID column - see Fix 4. The ID is documented in the SQL header and the SOP for when it does.

**Mirrors moved in the same commit:** status-dash PropTrack TTD checks (7 filters - without this the accuracy monitor would go red the moment the dashboard included the recovered rows), `clients/client_proptrack/README.md`, `sql/README.md`, `job/main.py` docstring, the `md/AGENTS.md` client row.

**Post-deploy note:** the view change needs `sql/deploy_views_proptrack.ps1` (reapply + job run) to reach the live dashboard - `/go` picks it up automatically, along with the cloudflare job, STT views and status job.

---

## Fix 4 - Advertiser IDs on the Snowflake TTD filters: NOT APPLIED (blocked upstream, by design of the check)

The brief: add `ADVERTISER_ID` alternatives (`olt0fli` Cloudflare, `lu5koiw` Schneider x2, `4gy2q4h` HireRight, optional `9c1w83i` MongoDB) - **only if the source table has the column**.

**It does not.** `raw_snowflake.tradedesk_apac_all` carries NO ID columns of any kind (verified via INFORMATION_SCHEMA: name columns only - ADVERTISER_NAME / CAMPAIGN_NAME / AD_GROUP_NAME / CREATIVE_NAME / PARTNER_NAME). And since `ingest/snowflake_data_pull/loader.py` is a deliberate `SELECT *` full copy, the columns are missing in **Transmission's Snowflake share itself** (`APAC_ALL_PLATFORM.PUBLIC."TradeDesk_APAC ALL"`), not dropped by our loader. The same applies to `linkedin_ads_apac`'s campaign-group level (no CAMPAIGN_GROUP_ID) - though LinkedIn ACCOUNT_ID does exist and is already used where it matters.

The contrast the task asked me to report: `raw_windsor.perf_the_trade_desk` (the 100% Digital seat's Windsor feed) **does** carry `advertiser_id` / `campaign_id` / `ad_group_id` - which is why caltex can run the canonical ID-first filter and the Transmission pipelines cannot.

**Consequences:**
- The 4 planned ID additions (and MongoDB's optional one) are impossible today. The five confirmed TTD advertiser IDs are preserved in [docs/SCOPING_STANDARD.md](../docs/SCOPING_STANDARD.md) so the swap is a five-minute job the day the share grows ID columns.
- **Recommended upstream ask to Transmission:** add Advertiser ID / Campaign ID / Ad Group ID columns to the `TradeDesk_APAC ALL` export (they exist in every native TTD report template). That single change unlocks ID-first scoping for all five Transmission TTD pipelines and would have prevented both the PropTrack freeze and the MongoDB `2265_` incident class.
- MongoDB's pixel lane already ID-scopes (`ADVERTISER_ID = '9c1w83i'`) because the **conversion** export (`tradedesk_apac_conversion`) does carry the column - proof Transmission can export IDs when the report template includes them.
- No row-count table for this fix: no code changed.

---

## Explicitly verified, no change needed

- **MongoDB seed pin** (`01_stg_tradedesk.sql`): advertiser filter + seed join both present and correct; the seed carries PROGRAMME/MARKET/CAMPAIGN_ID and the drift alarm. Untouched per the brief.
- **Schneider `seed_campaign_map` token matching** (`20_pm_delivery.sql`): sits on account-scoped staging, data-driven. Untouched.
- **Schneider LinkedIn** `ACCOUNT_NAME LIKE 'SchneiderElectric_TransmissionSG%'`: covers all three currency accounts (517045062 / 516221072 / 504047196). Untouched.
- **STT LinkedIn** `ACCOUNT_ID IN ('515691430','511609128')`: both accounts, ID-keyed. Untouched.
- Cloudflare's `NOT LIKE '%dooh%'` exclusion and LQAI's `%LQAIDC%` substring: preserved exactly.

## 100% Digital observations (NOT changed - separate task)

1. **geocon / bellshakespeare / nextsmile Meta**: `STARTS_WITH(campaign_name, '<Client>_')` prefix is the ONLY scope over the shared 6-account `perf_meta`. Fix shape: `AND account_name = '100% Digital - Clients'` (verify literal) + keep the prefix (multi-client account).
2. **VMCH TTD**: `advertiser_name = 'VMCH '` - load-bearing trailing space. Windsor TTD carries `advertiser_id`, so VMCH can adopt the full caltex ID-first pattern (get the id from the TTD UI).
3. **ResetData Meta**: `account_name = 'Reset backup – Ad account'` contains an en-dash - editorial trap, `LIKE 'Reset backup%'` would remove it.
4. **caltex**: already the canonical pattern; used as the SOP's reference example.

## Commits

| Commit | Fix | Numbers |
|---|---|---|
| `09c931a` | Fix 1 - STT Google Ads account-ID scope | 49,648 rows / $100,333.17 -> identical |
| `fb387e9` | Fix 2 - Cloudflare dashes normalised + account-scoped | 450 rows / $45,382.74 -> identical; $0 recovery (nothing misnamed in mirror) |
| `a44255e` | Fix 3 - PropTrack both spellings | 9,180 -> 9,413 rows; +$1,724.88 (15 days recovered) |
| (this commit) | Fix 4 report, verification report, SOP, lineage regen | no code change |
