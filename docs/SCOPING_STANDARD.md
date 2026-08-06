# Campaign Scoping Standard (SOP)

How every client pipeline scopes ad-platform delivery data. Written 2026-08-06 alongside the
Transmission scoping standardization ([verification report](../md/SCOPING_VERIFICATION_TRANSMISSION_2026-08-06.md));
the underlying audit is [md/CAMPAIGN_SCOPING_AUDIT_2026-08-06.md](../md/CAMPAIGN_SCOPING_AUDIT_2026-08-06.md).

## The rule

**Scope at the lowest level of the platform hierarchy that maps one-to-one with a client, and
prefer IDs over names at every level.** When a campaign changes on the platform - new, paused,
removed, renamed - the dashboard must stay correct without a code change. Account/advertiser scope
gives you that; campaign-name scope does not. Names get renamed (PropTrack's advertiser, STT's SGD
Google account, every `NNNN_`-prefixed Transmission campaign), corrected, and grow whitespace. IDs
do not.

| Platform | Hierarchy | Scope here |
|---|---|---|
| The Trade Desk | Partner > Advertiser > Campaign > Ad Group | **Advertiser** |
| LinkedIn | Ad Account > Campaign Group > Campaign (ad set) | **Ad Account** |
| Google Ads | MCC > Customer Account > Campaign > Ad Group | **Customer Account** |
| DV360 | Partner > Advertiser > IO > Line Item | **Advertiser** |
| Meta | Business > Ad Account > Campaign > Ad Set | **Ad Account** (see 100% Digital caveat below) |

Never scope at partner/MCC/business level - those span multiple clients. A campaign-name pattern
is allowed only ON TOP of a proper account/advertiser scope (e.g. LQAI's `%LQAIDC%` narrows the
Schneider advertiser to one brief; Cloudflare's `NOT LIKE '%dooh%'` excludes one format), never as
the only filter.

## The canonical filter pattern

ID first, name as fallback (reference implementation: `clients/client_caltex/sql/01_stg_ttd.sql`):

```sql
WHERE advertiser_id = '0lw3hp6'
   OR LOWER(TRIM(advertiser_name)) LIKE 'caltex%'
```

When the feed has **no ID column** (true today for ALL Snowflake TTD/DV360 delivery - see the
caveat below), harden the name instead: case-fold, trim, and accept every spelling the feed has
ever carried:

```sql
WHERE LOWER(TRIM(ADVERTISER_NAME)) IN ('poptrack', 'proptrack')   -- proptrack, renamed on-platform 2026-07-22
```

If a campaign-level match is unavoidable (a single-campaign dashboard), strip the brief-number
prefix on the feed side before comparing - never exact-match a raw campaign name
(AGENTS.md "Campaign names are NOT stable keys"):

```sql
WHERE REGEXP_REPLACE(TRIM(CAMPAIGN_GROUP_NAME), r'^[0-9]+_', '') IN ('CLOUD_ACQ_..._ANZ-PEYC', ...)
  AND ACCOUNT_NAME = 'Cloudflare APAC'
```

## Reference IDs (verified in the platform UIs, 2026-08-06)

### TTD advertisers (Transmission seats)

| Client | Advertiser ID | Partner |
|---|---|---|
| Cloudflare | `olt0fli` | Transmission Media AU - USD (`3kecaw8`) |
| MongoDB | `9c1w83i` | Transmission Media AU - USD (`3kecaw8`) |
| Schneider Electric | `lu5koiw` | Transmission Media AU (`j5lbnyt`) |
| PropTrack | `gb75r2p` | Transmission Media AU (`j5lbnyt`) |
| HireRight | `4gy2q4h` | Transmission Media AU (`j5lbnyt`) |

The Templates / Template Advertiser / Sohiie AI advertisers under these partners are not ours;
advertiser-level scoping excludes them by construction.

> **CAVEAT - Snowflake TTD carries no ID columns.** `raw_snowflake.tradedesk_apac_all` (a
> `SELECT *` mirror of Transmission's `"TradeDesk_APAC ALL"` share) has ONLY name columns, so
> these advertiser IDs cannot be used in the Snowflake-fed pipelines yet - they are recorded here
> for the day Transmission adds ID columns to the export (standing ask; the conversion export
> `tradedesk_apac_conversion` already has ADVERTISER_ID, so it is possible). Until then the
> Snowflake TTD filters are hardened names. The Windsor feed (`raw_windsor.perf_the_trade_desk`,
> 100% Digital seat) DOES carry `advertiser_id` - use it there, always.

### LinkedIn ad accounts (all single-client; source `raw_snowflake.linkedin_ads_apac` unless noted)

| Account name | ID | Client |
|---|---|---|
| SchneiderElectric_TransmissionSG_AUD | 517045062 | Schneider |
| SchneiderElectric_TransmissionSG_SGD | 516221072 | Schneider |
| SchneiderElectric_TransmissionSG_USD | 504047196 | Schneider |
| APAC - STT GDC - SGD (NAME HAS A TRAILING SPACE in the feed) | 515691430 | STT |
| STTGDC_TransmissionSG_USD | 511609128 | STT |
| Cloudflare APAC | 520254094 | Cloudflare |
| PropTrack_TransmissionSG_AUD | 510177932 | PropTrack |
| HireRight_TransmissionSG_USD | 513554482 | HireRight |
| MongoDB | 502299829 | MongoDB (Windsor feed; connector 500s, see the linkedin ingest README) |

The trailing space on the STT SGD account name is why STT filters on `ACCOUNT_ID` - never
"simplify" that filter to a name match.

### Google Ads customer accounts

| Client | Customer ID | Note |
|---|---|---|
| STT | `1641370256` | "STT (USD)", delivery Jun-Aug 2025 |
| STT | `4825242697` | SGD account - its NAME was renamed `STT GDC_SGD` -> `STT Global Data` on 2026-05-31, which is exactly why the filter is ID-based |

(100% Digital Google Ads customer IDs live in `ingest/dts_data_pull/sql/perf_google_ads.sql`'s
CASE map; they ride the DTS bridge, and client views filter the bridge's `account_name` slice.)

### DV360 advertisers

| Client | Advertiser ID |
|---|---|
| STT | `7572338345`, `6466367438` |
| Schneider | name-scoped `ADVERTISER_NAME LIKE 'APAC | Schneider Electric%'` (no ID in the share) |
| HireRight | name-scoped `LOWER(ADVERTISER_NAME) LIKE '%hireright%'` (no ID in the share) |

## Onboarding checklist - new client, new platform lane

1. **Find the account/advertiser ID** in the platform UI (TTD: the id in the advertiser URL;
   LinkedIn: Campaign Manager account id; Google Ads: the customer id). Record it in the table
   above IN THE SAME CHANGE.
2. **Confirm the account is single-client.** If it hosts more than one client (e.g. the shared
   100% Digital Meta account), account scope alone is NOT sufficient - account AND a name prefix,
   belt and braces.
3. **Check the feed for an ID column** before writing the filter (`INFORMATION_SCHEMA.COLUMNS`).
   ID column present -> canonical ID-first pattern. Name only -> `LOWER(TRIM(...))` + every
   spelling seen, and note the platform-UI ID in the SQL header for later.
4. **Write the filter ONCE, in the staging view** (`sql/01_stg_*.sql`). Everything downstream
   reads staging. Never re-filter raw tables in later views.
5. **Verify the row count against the platform UI** (spend + impressions for the flight window),
   and record before/after aggregates in the commit message for any later filter change: row
   count, total spend, min/max date, distinct campaigns. If a number moves unexpectedly, stop.
6. **Mirror the filter into the status-dash checks** (`status_dashboard/job/main.py`) - but as a
   whole-account/advertiser total, so the check can NEVER go circular with a campaign-level
   parse (AGENTS.md rule). Keep both sides in sync in the same commit, or the accuracy monitor
   goes red.
7. **Update the client README's data-contract row** with the literal filter.

## The MongoDB exception (deliberate - do not "simplify")

`client_mongodb` pins TTD + LinkedIn scope to `seed_campaign_ids` (the committed mirror of
Transmission's campaign-reference sheet) **on top of** its advertiser filter
(`ADVERTISER_NAME = "MongoDB"`). The seed is not redundant scoping:

- it is the **source of PROGRAMME / MARKET / CAMPAIGN_ID** (the delivery mirror has no ID column,
  and name-parsing those dimensions is what silently misattributed $11,906 in the 2026-08-04
  `2265_` prefix incident);
- it is the **drift alarm**: an unseeded campaign is excluded AND flagged (status-dash
  "Delivery outside the seeded campaign scope" + the export job's scope-audit warning), instead
  of silently absorbed with garbage dimensions.

Advertiser-level scoping alone would return the same rows only coincidentally, and would invert
the failure mode from loud to silent. New MongoDB campaign -> update the sheet +
`targets/campaign_ids.csv` -> `seed_static.py` -> forced job run.

## 100% Digital clients (standardized 2026-08-06, second pass)

All 100% Digital pipelines ride Windsor feeds, which DO carry ID columns
(`perf_the_trade_desk.advertiser_id`, `perf_meta.account_id`) - so unlike the Snowflake-fed
Transmission pipelines, every filter here is ID-first. Verification:
[md/SCOPING_VERIFICATION_100DIGITAL_2026-08-06.md](../md/SCOPING_VERIFICATION_100DIGITAL_2026-08-06.md).

### TTD advertisers (100% Digital seat, Windsor account `484`)

| Client | Advertiser ID | Filter status |
|---|---|---|
| Caltex | `0lw3hp6` | canonical (the reference pattern) |
| ResetData | `lxp46o9` | ID-first since 2026-08-06 |
| The Little Marionette | `mor6pp1` | ID-first since 2026-08-06 |
| VMCH | `sif8zx0` | ID-first since 2026-08-06 (retired the trailing-space name literal `'VMCH '`) |
| City Perfume | `l4dj1fw` (observed in the Windsor feed, 2026-08-06 - **confirm in the TTD UI before switching**) | still `advertiser_name = 'City Perfume'` - PENDING |

### Meta ad accounts (`raw_windsor.perf_meta`)

| Account | account_id | Client(s) |
|---|---|---|
| 100% Digital - Clients | `3754165911553001` | geocon + bellshakespeare + nextsmile (SHARED - see below) |
| Cityperfume.com.au | `1126027130805483` | cityperfume |
| Reset backup – Ad account (name carries an EN-DASH - filter on the ID) | `465058559225771` | resetdata |
| Ad Assembly - BuyerX / ACRS | `927205350157043` / `910485528634664` | not ours - excluded by account scope |

### Google Ads customer accounts (DTS bridge `perf_google_ads`)

| Client | Customer ID |
|---|---|
| City Perfume | `2617916504` |
| ResetData | `1054407474` |
| The Little Marionette | `1869745895` |

Client views filter the bridge's `account_name` slice ('City Perfume' / 'Reset Data' / 'The
Little Marionette') - names WE assign in `ingest/dts_data_pull/sql/perf_google_ads.sql`'s CASE
map keyed on these customer IDs, so they are stable by construction (unlike platform-side names).

### The shared-Meta-account case - when a client filter IS required on top of account scope

The `100% Digital - Clients` Meta account (act `3754165911553001`) genuinely hosts multiple
clients - geocon, bellshakespeare and nextsmile all run inside it. This is the codebase's one
confirmed case where account scope alone cannot separate clients, so the standard there is
**account ID AND campaign prefix, both required**:

```sql
WHERE account_id = '3754165911553001'   -- 100% Digital - Clients
  AND STARTS_WITH(campaign_name, 'Geocon_')
```

- The account_id keeps other advertisers' campaigns out no matter what they are named
  (perf_meta is shared across six accounts including other agencies').
- The prefix splits the co-tenants apart - and remains a naming-convention dependency
  (`Geocon_` / `Bell Shakespeare_` / `Next Smile Australia_`): a campaign launched in this
  account WITHOUT the client prefix will not reach any dashboard. That is the price of
  co-tenancy; prefer giving each client its own ad account when there is a choice.
- ResetData Reddit is the same shape one level down: `perf_reddit` is shared, the
  `client_slug` tag comes from the loader's `REDDIT_ACCOUNT_TO_CLIENT` map, and the 2026-07
  incident (Cloudflare's account mis-mapped to resetdata) shows the map IS the scope - verify
  it whenever a Reddit account is granted/re-granted (verified correct 2026-08-06).
