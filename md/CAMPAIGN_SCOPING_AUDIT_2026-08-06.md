# Campaign Scoping Audit - Hierarchy Level per Client Pipeline

**Date:** 2026-08-06
**Scope:** every SQL file under `clients/` that filters campaign- or ad-level delivery data (staging, models, plus the one job-embedded SQL that scopes campaign data). Literal filters quoted verbatim.

**Reference hierarchies:**
- TTD: Partner -> Advertiser -> Campaign -> Ad Group
- LinkedIn: Ad Account -> Campaign Group -> Campaign (ad set)
- Google Ads: MCC -> Customer Account -> Campaign -> Ad Group
- (DV360, Meta, Reddit rows are classified at the analogous Advertiser / Ad Account level.)

**Headline:** no pipeline scopes at partner level. 24 of 30 filters sit correctly at Advertiser / Ad Account / Customer Account level. The flags are: 1 name-pattern-only Google Ads filter (STT), 3 name-pattern-only Meta filters (geocon + the 2 placeholder clones), 1 exact-campaign-group-name list with no account scope (cloudflare single-campaign dashes), and 2 fragile literals (VMCH trailing space, PropTrack misspelling). MongoDB's ID pin is **justified** - see Section 3.

---

## 1. Master table

| Client | Platform | SQL File | Literal Filter | Hierarchy Level | Correct? | Risk |
|---|---|---|---|---|---|---|
| mongodb | TTD delivery | [01_stg_tradedesk.sql:43](../clients/client_mongodb/sql/01_stg_tradedesk.sql#L43) | `WHERE ADVERTISER_NAME = "MongoDB"` then `JOIN (SELECT CAMPAIGN_ID, PROGRAMME, MARKET, REGEXP_REPLACE(TRIM(CAMPAIGN_NAME), r'^[0-9]+_', '') AS CAMPAIGN_NAME_NORM FROM seed_campaign_ids WHERE PLATFORM = "tradedesk") s USING (CAMPAIGN_NAME_NORM)` | Advertiser + explicit campaign ID list (seed joined on normalised name) | OK | Seed must track the reference sheet; unseeded campaign is excluded (by design, alarmed by status-dash) |
| mongodb | TTD pixel | [11_stg_tradedesk_pixel.sql:53](../clients/client_mongodb/sql/11_stg_tradedesk_pixel.sql#L53) | `WHERE ADVERTISER_ID = '9c1w83i'` | Advertiser (ID) | OK | None - ID, not name |
| mongodb | LinkedIn | [14_stg_linkedin.sql:74-77](../clients/client_mongodb/sql/14_stg_linkedin.sql#L74-L77) | `WHERE TRIM(campaign_id) IN (SELECT TRIM(CAMPAIGN_ID) FROM seed_campaign_ids WHERE PLATFORM = 'linkedin')` | Explicit campaign ID list (no account scope above) | OK | LinkedIn campaign IDs are globally unique, so no cross-client bleed; new campaign invisible until seeded (by design) |
| cloudflare | TTD | [03_stg_tradedesk.sql:29,37](../clients/client_cloudflare/sql/03_stg_tradedesk.sql#L29) | `WHERE ADVERTISER_NAME = 'Cloudflare' AND LOWER(IFNULL(CAMPAIGN_NAME, '')) NOT LIKE '%dooh%'` | Advertiser (+ name-pattern exclusion) | OK | `'%dooh%'` exclusion is name-dependent; mirrored in status-dash checks, keep in sync |
| cloudflare | LinkedIn (core) | [01_stg_linkedin.sql:22](../clients/client_cloudflare/sql/01_stg_linkedin.sql#L22) | `WHERE ACCOUNT_NAME = 'Cloudflare APAC'` | Ad Account | OK | Account 520254094 is single-client; name-keyed but stable |
| cloudflare | LinkedIn (models) | [05_paid_media_model.sql:41](../clients/client_cloudflare/sql/05_paid_media_model.sql#L41), [06_paid_creatives_model.sql:26](../clients/client_cloudflare/sql/06_paid_creatives_model.sql#L26) | `WHERE STARTS_WITH(CAMPAIGN_NAME_NORM, 'CLOUD_ACQ_')` | Campaign name pattern (with account/advertiser scope beneath, prefix-normalised) | OK | Depends on the `CLOUD_ACQ_` prefix convention |
| cloudflare | LinkedIn (3 single-campaign dashes) | [job/main.py:251](../clients/client_cloudflare/job/main.py#L251) (SQL string) | `WHERE CAMPAIGN_GROUP_NAME IN ('CLOUD_ACQ_2026-Q2_CNC_LINKEDIN_GENERAL_SI_APAC-ANZ_ANZ_MOFU_GENERAL_X_AWR-CONS_ANZ-PEYC', 'CLOUD_ACQ_2026-Q2_CNC_LINKEDIN_GENERAL_SI_APAC-IN_IN_MOFU_GENERAL_X_AWR-CONS_CF1-Integrated', 'CLOUD_ACQ_2026-Q2_MDS_LINKEDIN_GENERAL_SI_APAC-ANZ_ANZ_MOFU_GENERAL_X_AWR-CONS_Hyper_COLES')` | Campaign-group exact-name list, no account scope | **FLAG** | A brief-number prefix rename (`2103_...`) zeroes all three dashes silently - the exact defect class AGENTS.md documents |
| cloudflare | Reddit | [02_stg_reddit.sql:7](../clients/client_cloudflare/sql/02_stg_reddit.sql#L7) | `WHERE ACCOUNT_NAME = 'Transmission_Cloudflare'` | Ad Account | OK | Single-client account |
| cloudflare | LINE | (seed table `seed_line_cf`, manual CSV) | no platform filter - client-supplied data | N/A | OK | Manual pipeline, no shared-table exposure |
| stt | LinkedIn | [02_stg_linkedin.sql:28](../clients/client_STT/sql/02_stg_linkedin.sql#L28) | `WHERE ACCOUNT_ID IN ('515691430', '511609128')` | Ad Account (IDs, both SGD + USD accounts) | OK | ID-based - immune to the SGD account's trailing-space name |
| stt | DV360 | [03_stg_dv360.sql:35](../clients/client_STT/sql/03_stg_dv360.sql#L35) | `WHERE ADVERTISER_ID IN ('7572338345', '6466367438')` | Advertiser (IDs) | OK | None |
| stt | Google Ads | [03b_stg_google.sql:33](../clients/client_STT/sql/03b_stg_google.sql#L33) | `WHERE CAMPAIGN_NAME LIKE '%STT%'` | Campaign name pattern ONLY - no account scope | **FLAG** | Shared `raw_snowflake.google_ads_apac`; depends on the substring `STT`; over- and under-match risk (see Section 4.1) |
| schneider | DV360 | [01_stg_dv360.sql:63](../clients/client_schneider/sql/01_stg_dv360.sql#L63) | `WHERE ADVERTISER_NAME LIKE 'APAC \| Schneider Electric%'` | Advertiser (name prefix) | OK | Name-keyed, stable so far |
| schneider | LinkedIn | [02_stg_linkedin.sql:63](../clients/client_schneider/sql/02_stg_linkedin.sql#L63) | `WHERE ACCOUNT_NAME LIKE 'SchneiderElectric_TransmissionSG%'` | Ad Account (prefix covers all 3: _AUD, _SGD, _USD) | OK | Covers every Schneider account - see Section 5 |
| schneider | TTD | [03_stg_tradedesk.sql:55](../clients/client_schneider/sql/03_stg_tradedesk.sql#L55) | `WHERE ADVERTISER_NAME = 'Schneider Electric'` | Advertiser | OK | None |
| schneider | program tagging (all 3 platforms) | [20_pm_delivery.sql:24-26,41](../clients/client_schneider/sql/20_pm_delivery.sql#L24-L26) | `WHERE EXISTS (SELECT 1 FROM UNNEST(SPLIT(m.pat, '\|')) tok WHERE TRIM(tok) != '' AND STRPOS(LOWER(c.campaign), TRIM(tok)) > 0)` ... `WHERE cm.program IN ('water_env','eba','heavy','global_rebrand','airset','nel','microgrid','ecoconsult')` | Campaign name tokens (seed-driven), applied ON TOP of advertiser/account-scoped staging | OK | Token list is data (editable seed), but a delivering campaign matching no token silently drops from the program views - the `2281_HI_*` incident |
| schneiderlqai | LinkedIn | [01_stg_linkedin.sql:49-50](../clients/client_schneiderlqai/sql/01_stg_linkedin.sql#L49-L50) | `WHERE ACCOUNT_NAME LIKE 'SchneiderElectric_TransmissionSG%' AND UPPER(CAMPAIGN_NAME) LIKE '%LQAIDC%'` | Ad Account + campaign name substring | OK | Depends on the `LQAIDC` token (substring - survives prefix renames) |
| schneiderlqai | TTD | [02_stg_tradedesk.sql:46-47](../clients/client_schneiderlqai/sql/02_stg_tradedesk.sql#L46-L47) | `WHERE ADVERTISER_NAME = 'Schneider Electric' AND UPPER(CAMPAIGN_NAME) LIKE '%LQAIDC%'` | Advertiser + campaign name substring | OK | Same `LQAIDC` dependency |
| hireright | DV360 | [01_stg_dv360.sql:46](../clients/client_hireright/sql/01_stg_dv360.sql#L46) | `WHERE LOWER(ADVERTISER_NAME) LIKE '%hireright%'` | Advertiser (name substring) | OK | Substring is loose but the token is distinctive |
| hireright | LinkedIn | [02_stg_linkedin.sql:38](../clients/client_hireright/sql/02_stg_linkedin.sql#L38) | `WHERE LOWER(ACCOUNT_NAME) LIKE 'hireright%'` | Ad Account (name prefix) | OK | Matches `HireRight_TransmissionSG_USD` |
| hireright | TTD | [03_stg_tradedesk.sql:25](../clients/client_hireright/sql/03_stg_tradedesk.sql#L25) | `WHERE ADVERTISER_NAME = 'HireRight'` | Advertiser | OK | None |
| cityperfume | Google Ads | [01_stg_google.sql:20](../clients/client_cityperfume/sql/01_stg_google.sql#L20) | `WHERE account_name = 'City Perfume'` | Customer Account (bridge view maps customer_id 2617916504) | OK | Name assigned by our own DTS bridge view - stable |
| cityperfume | Meta | [02_stg_meta.sql:48](../clients/client_cityperfume/sql/02_stg_meta.sql#L48) | `WHERE account_name = 'Cityperfume.com.au'` | Ad Account | OK | None |
| cityperfume | TTD | [03_stg_ttd.sql:26](../clients/client_cityperfume/sql/03_stg_ttd.sql#L26) | `WHERE advertiser_name = 'City Perfume'` | Advertiser | OK | None |
| resetdata | Google Ads | [02_stg_google.sql:23](../clients/client_resetdata/sql/02_stg_google.sql#L23) | `WHERE account_name = 'Reset Data'` | Customer Account | OK | None |
| resetdata | Google Ads (audience/keywords) | [31_ga_audience.sql:25,34,43](../clients/client_resetdata/sql/31_ga_audience.sql#L25), [32_ga_keywords.sql:19,29](../clients/client_resetdata/sql/32_ga_keywords.sql#L19) | `WHERE customer_id = 1054407474` | Customer Account (ID, on the raw DTS tables) | OK | None |
| resetdata | Meta | [03_stg_meta.sql:29](../clients/client_resetdata/sql/03_stg_meta.sql#L29) | `WHERE account_name = 'Reset backup – Ad account'` | Ad Account | OK | The literal contains an EN-DASH - retyping it with a hyphen silently zeroes the view |
| resetdata | TTD | [04_stg_ttd.sql:25](../clients/client_resetdata/sql/04_stg_ttd.sql#L25) | `WHERE advertiser_name = 'ResetData'` | Advertiser | OK | None |
| resetdata | Reddit | [04b_stg_reddit.sql:27](../clients/client_resetdata/sql/04b_stg_reddit.sql#L27) | `WHERE client_slug = 'resetdata'` | Ad Account (loader-assigned tag; `perf_reddit` also holds Cloudflare's account) | OK | Tag correctness depends on the loader's `ACCOUNT_TO_CLIENT` map - the 2026-07/08 mis-map incident |
| proptrack | TTD | [01_stg_tradedesk.sql:27](../clients/client_proptrack/sql/01_stg_tradedesk.sql#L27) | `WHERE ADVERTISER_NAME = 'PopTrack'` | Advertiser | OK* | Keyed on TTD's **misspelling** `PopTrack` - if the advertiser is ever renamed to `PropTrack`, the dash zeroes |
| proptrack | LinkedIn | [02_stg_linkedin.sql:34](../clients/client_proptrack/sql/02_stg_linkedin.sql#L34) | `WHERE ACCOUNT_NAME = 'PropTrack_TransmissionSG_AUD'` | Ad Account | OK | Single-client account 510177932 |
| tlm | Google Ads | [01_stg_google.sql:24](../clients/client_tlm/sql/01_stg_google.sql#L24) | `WHERE account_name = 'The Little Marionette'` | Customer Account | OK | None |
| tlm | TTD | [02_stg_ttd.sql:30](../clients/client_tlm/sql/02_stg_ttd.sql#L30) | `WHERE advertiser_name = 'The Little Marionette'` | Advertiser | OK | None |
| vmch | TTD | [03_stg_ttd.sql:28](../clients/client_vmch/sql/03_stg_ttd.sql#L28) | `WHERE advertiser_name = 'VMCH '` | Advertiser | OK* | **Trailing space in the literal** - matches the feed today, breaks the day Windsor trims it |
| caltex | TTD | [01_stg_ttd.sql:31-32](../clients/client_caltex/sql/01_stg_ttd.sql#L31-L32) | `WHERE advertiser_id = '0lw3hp6' OR LOWER(TRIM(advertiser_name)) LIKE 'caltex%'` | Advertiser (ID + name fallback) | OK | The most robust TTD filter in the repo - copy this pattern |
| geocon | Meta | [01_stg_meta.sql:47](../clients/client_geocon/sql/01_stg_meta.sql#L47) | `WHERE STARTS_WITH(campaign_name, 'Geocon_')` | Campaign name pattern ONLY - no account scope | **FLAG** | Shared `raw_windsor.perf_meta` (6 accounts incl. other agencies'); depends on the `Geocon_` prefix |
| geocon | Meta breakdowns | [05_breakdowns.sql](../clients/client_geocon/sql/05_breakdowns.sql) | no filter - reads dedicated `raw_windsor.geocon_meta_breakdown` | N/A (single-tenant table) | OK | None |
| bellshakespeare | Meta (placeholder) | [01_stg_meta.sql:47](../clients/client_bellshakespeare/sql/01_stg_meta.sql#L47) | `WHERE STARTS_WITH(campaign_name, 'Bell Shakespeare_')` | Campaign name pattern ONLY - no account scope | **FLAG** | Same as geocon; depends on `Bell Shakespeare_` |
| nextsmile | Meta (placeholder) | [01_stg_meta.sql:47](../clients/client_nextsmile/sql/01_stg_meta.sql#L47) | `WHERE STARTS_WITH(campaign_name, 'Next Smile Australia_')` | Campaign name pattern ONLY - no account scope | **FLAG** | Same as geocon; depends on `Next Smile Australia_` |

Out of the ad hierarchy (for completeness, not flagged): GA4 property filters (`stt` `WHERE PROPERTY_ID = '318963196'`; `vmch` `WHERE property_id = '287370621'` with `account_name = 'VMCH Website - GA4'` Windsor fallback; `cityperfume`/`resetdata` `client_slug` slices; `schneider` 40/40b hold the placeholder `WHERE property_id IN ('REPLACE_WITH_SE_GA4_PROPERTY_ID')` - shipped disabled, matches no rows by design). Salesforce / HubSpot CRM lanes (mongodb 02, cloudflare 10/14, schneider 17, resetdata 24-30/34) filter on CRM campaign IDs, not ad-platform hierarchy.

---

## 2. Partner-level check

**No pipeline scopes at partner level.** The raw layers ARE partner-wide - `raw_snowflake.tradedesk_apac_all` spans all Transmission seats (so it mixes Schneider/HireRight/PropTrack under `j5lbnyt` with Cloudflare/MongoDB under `3kecaw8`), and `raw_windsor.perf_the_trade_desk` rides the single Windsor seat account `484` - but every client view narrows to its own advertiser before anything reaches a dashboard. The "Templates"/"Template Advertiser"/"Sohiie AI" advertisers under the same partners are excluded everywhere by construction.

---

## 3. MongoDB deep-dive: ID pin vs advertiser-level filter

MongoDB is its own TTD advertiser under Transmission Media AU - USD (`3kecaw8`), and [01_stg_tradedesk.sql](../clients/client_mongodb/sql/01_stg_tradedesk.sql) **already has the advertiser filter** - `WHERE ADVERTISER_NAME = "MongoDB"` at line 43. The seed INNER JOIN is layered on top of it, not instead of it. So the question is really: what does the join add?

**Would advertiser-only return the same rows?** Today, almost certainly yes at the delivery level: the reference sheet lists exactly the 8 seeded campaigns for the MongoDB advertiser, and both name forms (`2265_MONGODB_...` and `MONGODB_...`) normalise onto seed rows. But it is only coincidentally identical - equality holds only while the advertiser's entire delivery history is seeded. Any test campaign, any next-quarter flight, any campaign the media team launches before the sheet is updated breaks the equality.

**What breaks if we replace the pin with advertiser-only:**
1. **`PROGRAMME` and `MARKET` disappear.** They are selected from the seed (`s.PROGRAMME, s.MARKET`), NOT parsed from names, precisely because fixed-offset name parsing silently misattributed $11,906 of delivery when the `2265_` prefix landed (2026-08-04 defect). Advertiser-only means re-deriving them by name parsing - reinstating the exact failure mode the pin was built to kill.
2. **`CAMPAIGN_ID` disappears.** `tradedesk_apac_all` has no campaign-id column; the seed is the only source. The dashboard and the AI deck carry it as the stable anchor.
3. **The failure mode inverts, from loud to silent.** Today an unseeded campaign is EXCLUDED and ALARMED (the status-dash "Delivery outside the seeded campaign scope" check + the export job's scope-audit WARNING). Advertiser-only silently includes it with NULL/garbage programme+market, and the dashboard's chip filters (`marketOk()`) then drop it from every KPI without any alarm - invisible under-reporting.

**Verdict: keep the pin.** The ID list is not redundant scoping - it is the dimension source and the drift alarm. The advertiser filter already provides the "don't pull other clients" guarantee; the seed provides correctness of attribution. (Same logic for the LinkedIn lane: `campaign_id IN (seed)` could in principle become an account filter on `502299829` - a single-client account - but the account is currently unreadable (Windsor 500), the seed also carries PROGRAMME/MARKET, and IDs are stable; no benefit to switching.)

---

## 4. Flagged issues and recommended fixes

### 4.1 STT Google Ads - name pattern with no account scope (highest priority)
[clients/client_STT/sql/03b_stg_google.sql:33](../clients/client_STT/sql/03b_stg_google.sql#L33): `WHERE CAMPAIGN_NAME LIKE '%STT%'` over the shared `raw_snowflake.google_ads_apac`.
- Under-match: a campaign renamed without the `STT` token vanishes silently.
- Over-match: any other client's campaign whose name contains `STT` (as a substring of any word) leaks into STT's spend.
- The view already SELECTs `ACCOUNT_NAME`, so the fix is one line: `WHERE ACCOUNT_NAME IN ('STT (USD)', 'STT GDC_SGD')` (the two accounts per [clients/client_STT/INTAKE.md](../clients/client_STT/INTAKE.md): 1641370256 / 4825242697; use `ACCOUNT_ID IN (...)` instead if the mirror carries it - ID beats name). Keep the `LIKE '%STT%'` as an extra belt if desired, but it must not be the only scope.

### 4.2 geocon / bellshakespeare / nextsmile Meta - prefix-only over the shared perf_meta
`WHERE STARTS_WITH(campaign_name, 'Geocon_')` / `'Bell Shakespeare_'` / `'Next Smile Australia_'` with no account filter, over `raw_windsor.perf_meta` which carries 6 Meta ad accounts including non-100-digital ones.
- Exact strings the pipelines depend on: `Geocon_`, `Bell Shakespeare_`, `Next Smile Australia_`. A campaign named without the prefix (or a brief-number prefix landing in front, Transmission-style) silently drops delivery; another advertiser launching a campaign with the same prefix silently leaks in.
- Fix: add the account scope above the prefix - these three clients all run in the `100% Digital - Clients` Meta account (act 3754165911553001), so `AND account_name = '100% Digital - Clients'` (verify the exact `account_name` value in `perf_meta` first). Keep the prefix (the account hosts multiple 100-digital clients, so account alone is insufficient) - the fix is account AND prefix, belt and braces.

### 4.3 Cloudflare single-campaign LinkedIn dashes - exact campaign-group names, no account scope
[clients/client_cloudflare/job/main.py:234-251](../clients/client_cloudflare/job/main.py#L234-L251): `WHERE CAMPAIGN_GROUP_NAME IN (...)` with three full-length literal names (PEYC / CF1-Integrated / Hyper_COLES).
- AGENTS.md already documents this class: a brief-number prefix rename zeroes exact-name matches outright, and the same campaign can exist under both name forms simultaneously, halving any name-keyed aggregate.
- Fix: (a) match on the normalised name - `REGEXP_REPLACE(TRIM(CAMPAIGN_GROUP_NAME), r'^[0-9]+_', '') IN (...)` with the prefixes stripped from the three literals; and (b) add `AND ACCOUNT_NAME = 'Cloudflare APAC'` so a name collision in another account can never leak in. Longer-term, seed the three campaign-group IDs mongodb-style.

### 4.4 VMCH TTD - trailing-space literal
[clients/client_vmch/sql/03_stg_ttd.sql:28](../clients/client_vmch/sql/03_stg_ttd.sql#L28): `WHERE advertiser_name = 'VMCH '` (trailing space). Matches the feed as-is today; the day Windsor or TTD trims the name, the dashboard zeroes with no error.
- Fix: `WHERE TRIM(advertiser_name) = 'VMCH'`, or better, adopt the caltex ID+name pattern (`advertiser_id = '<vmch id>' OR LOWER(TRIM(advertiser_name)) LIKE 'vmch%'`).

### 4.5 PropTrack TTD - keyed on a platform-side misspelling
[clients/client_proptrack/sql/01_stg_tradedesk.sql:27](../clients/client_proptrack/sql/01_stg_tradedesk.sql#L27): `WHERE ADVERTISER_NAME = 'PopTrack'`. Correct level (Advertiser), but the literal is TTD's misspelling - if anyone at Transmission "fixes" the advertiser name to `PropTrack`, the dash zeroes.
- Fix: widen to `WHERE ADVERTISER_NAME IN ('PopTrack', 'PropTrack')` now (free), and get the advertiser ID from the TTD URL to move to an ID filter like caltex.

### 4.6 ResetData Meta - en-dash literal
[clients/client_resetdata/sql/03_stg_meta.sql:29](../clients/client_resetdata/sql/03_stg_meta.sql#L29): `WHERE account_name = 'Reset backup – Ad account'`. Correct level; the risk is purely editorial - the dash in the literal is an EN-DASH, and any future editor retyping it as a hyphen silently empties the view. A one-line comment flagging the en-dash exists in the file header; consider `WHERE account_name LIKE 'Reset backup%'` to remove the trap.

### 4.7 Name-pattern dependency inventory (what breaks on a naming-convention change)
All patterns that sit ABOVE a proper account/advertiser scope (lower risk, listed for completeness):
- `CLOUD_ACQ_` prefix - cloudflare models (05/06); prefix-normalised, so brief numbers are already survivable.
- `%LQAIDC%` substring - both schneiderlqai stagings; substring, survives prefixes; breaks only if the token itself changes.
- `%dooh%` exclusion - cloudflare TTD; must stay in sync with the status-dash mirror.
- schneider `seed_campaign_map` match tokens (data-driven; the `2281_HI_*` and `SE_AET` incidents show new naming shapes need a token added - the miss is silent in the program views).
- STT market parse regex `_(?:AlwaysOn26|DemandNurture)_([A-Z]{2})_` - misparse lands in 'Other', visible.
- mongodb `STRATEGY`/`OBJECTIVE` fixed offsets on `*_NORM` names - cosmetic fields only; PROGRAMME/MARKET no longer depend on parsing.
These need no immediate change, but any campaign-naming-convention discussion with Transmission should check this list first.

### 4.8 Explicit ID lists vs advertiser-level scoping
The only explicit campaign-ID lists in the repo are MongoDB's two seed pins. Verdict (Section 3): justified - they carry dimensions and drift-alarming that advertiser scoping cannot, and the advertiser filter is already present underneath the TTD pin. No pipeline uses an ID list where a plain advertiser filter would do the same job.

---

## 5. LinkedIn account coverage check

Per-pipeline accounts actually filtered, against the confirmed 7-account structure:

| Pipeline | Filter | Accounts captured | Missing? |
|---|---|---|---|
| schneider [02_stg_linkedin.sql:63](../clients/client_schneider/sql/02_stg_linkedin.sql#L63) | `ACCOUNT_NAME LIKE 'SchneiderElectric_TransmissionSG%'` | 517045062 (_AUD), 516221072 (_SGD), 504047196 (_USD) | **No - all three covered** (the FX CASE at lines 44-46 even converts per-account: `_USD` x1.50, `_SGD` x1.15) |
| schneiderlqai [01_stg_linkedin.sql:49](../clients/client_schneiderlqai/sql/01_stg_linkedin.sql#L49) | same prefix + `%LQAIDC%` | all three Schneider accounts (then narrowed to LQAI campaigns) | No |
| stt [02_stg_linkedin.sql:28](../clients/client_STT/sql/02_stg_linkedin.sql#L28) | `ACCOUNT_ID IN ('515691430', '511609128')` | both STT accounts, incl. the USD one (converted at 1.34) | **No - 511609128 included** |
| cloudflare [01_stg_linkedin.sql:22](../clients/client_cloudflare/sql/01_stg_linkedin.sql#L22) | `ACCOUNT_NAME = 'Cloudflare APAC'` | 520254094 | No (single-client account) |
| proptrack [02_stg_linkedin.sql:34](../clients/client_proptrack/sql/02_stg_linkedin.sql#L34) | `ACCOUNT_NAME = 'PropTrack_TransmissionSG_AUD'` | 510177932 | No (single-client account) |
| hireright [02_stg_linkedin.sql:38](../clients/client_hireright/sql/02_stg_linkedin.sql#L38) | `LOWER(ACCOUNT_NAME) LIKE 'hireright%'` | HireRight_TransmissionSG_USD (513554482, not in the 7-account list but confirmed in the Windsor roster) | No |
| mongodb [14_stg_linkedin.sql:74](../clients/client_mongodb/sql/14_stg_linkedin.sql#L74) | seeded `campaign_id IN (...)` - no account filter | (implicitly) the MongoDB account 502299829, currently unreadable (Windsor 500) | No account-level filter by design; see Section 3 |

**Answer: no LinkedIn pipeline misses a Schneider account or the second STT account.** The two prefix/ID-set filters were built precisely to catch the multi-currency account splits. One related caveat: STT filters by ACCOUNT_ID specifically because the SGD account's NAME carries a trailing space (`'APAC - STT GDC - SGD '`) - anyone "simplifying" that filter to a name match will hit it.

---

## 6. Method

Greps across `clients/**/sql/*.sql` for every scoping shape (`ADVERTISER_NAME/ID`, `ACCOUNT_NAME/ID`, `client_slug`, `customer_id`, `property_id`, `LIKE`/`STARTS_WITH`/`CONTAINS_SUBSTR`/`STRPOS`, seed joins), then a reverse pass listing every SQL file that reads a `raw_*` table to confirm nothing reads shared raw data unscoped. Views not listed here read already-scoped staging views. The one non-`.sql` scoping filter (cloudflare's single-campaign LinkedIn SQL embedded in `job/main.py`) is included because it queries the shared raw layer directly.
