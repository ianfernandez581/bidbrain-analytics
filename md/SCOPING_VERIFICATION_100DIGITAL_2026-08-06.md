# Scoping Standardization - 100% Digital Clients - Verification Report

**Date:** 2026-08-06 (second pass, after the [Transmission pass](SCOPING_VERIFICATION_TRANSMISSION_2026-08-06.md))
**Scope:** geocon, bellshakespeare, nextsmile, VMCH, ResetData, City Perfume, The Little Marionette, Caltex.
Transmission pipelines untouched. SOP extended in place: [docs/SCOPING_STANDARD.md](../docs/SCOPING_STANDARD.md).

All numbers from BigQuery on 2026-08-06, measured as the exact filter each view runs (spend = feed-native `cost`, AUD unless noted). **No number moved on any fix - as required.**

---

## Fix 1 - Meta prefix-only scoping -> account ID + prefix (commit `cd14ece`)

`raw_windsor.perf_meta` carries `account_id`, so the added scope is ID-based (stronger than the
name): `WHERE account_id = '3754165911553001'  -- 100% Digital - Clients` above the existing
prefix. Both conditions are required - the shared account genuinely hosts several 100-digital
clients, so this is the codebase's one confirmed "account scope alone is insufficient" case.

Current accounts in `perf_meta` (for the record): Cityperfume.com.au (1126027130805483),
Ad Assembly - BuyerX (927205350157043), Reset backup – Ad account (465058559225771),
100% Digital - Clients (3754165911553001), Ad Assembly - ACRS (910485528634664).

| File | | rows | spend | min day | max day | campaigns |
|---|---|---|---|---|---|---|
| `client_geocon/sql/01_stg_meta.sql` | Before (prefix only) | 261 | $13,073.96 | 2026-05-05 | 2026-08-04 | 3 |
| | After (account + prefix) | 261 | $13,073.96 | 2026-05-05 | 2026-08-04 | 3 |
| | `Geocon_` rows OUTSIDE the account (leak check) | **0** | - | - | - | 0 |
| `client_bellshakespeare/sql/01_stg_meta.sql` | Before / After | 0 / 0 | - | - | - | 0 (placeholder - no delivery in perf_meta yet) |
| `client_nextsmile/sql/01_stg_meta.sql` | Before / After | 0 / 0 | - | - | - | 0 (placeholder - no delivery in perf_meta yet) |

`client_geocon/sql/05_breakdowns.sql` (dedicated single-tenant table) left untouched, per the brief.

---

## Fix 2 - VMCH TTD trailing-space literal -> advertiser-ID-first (commit `612f998`)

**File:** `clients/client_vmch/sql/03_stg_ttd.sql`
`WHERE advertiser_name = 'VMCH '` -> `WHERE advertiser_id = 'sif8zx0' OR LOWER(TRIM(advertiser_name)) LIKE 'vmch%'`

`raw_windsor.perf_the_trade_desk` has the `advertiser_id` column (confirmed), and the feed holds
exactly one VMCH advertiser: id `sif8zx0`, name `[VMCH ]` - the trailing space confirmed in-data,
matching the brief's diagnosis that it originates in the Windsor feed (the TTD UI shows `VMCH`).

| | rows | spend | min day | max day | campaigns |
|---|---|---|---|---|---|
| Before | 9,113 | $29,298.27 | 2026-04-01 | 2026-08-04 | 4 |
| After | 9,113 | $29,298.27 | 2026-04-01 | 2026-08-04 | 4 |

**Mirrors:** 4 status-dash VMCH TTD check filters moved in the same commit.

---

## Fix 3 - ResetData Meta en-dash literal -> account-ID-first (commit `d00fdd2`)

**File:** `clients/client_resetdata/sql/03_stg_meta.sql`
`WHERE account_name = 'Reset backup – Ad account'` (en-dash) -> `WHERE account_id = '465058559225771' OR account_name LIKE 'Reset backup%'`

One step past the prescribed `LIKE`: `perf_meta` carries `account_id` and the standard prefers
IDs, so the ID leads and the LIKE is the fallback. All three forms (en-dash exact / LIKE prefix /
account_id) verified to return the same rows before switching:

| | rows | spend | min day | max day | campaigns |
|---|---|---|---|---|---|
| Before (en-dash exact) | 318 | $4,813.03 | 2026-04-25 | 2026-07-07 | 5 |
| After (ID + LIKE) | 318 | $4,813.03 | 2026-04-25 | 2026-07-07 | 5 |

**Also fixed:** the SAME en-dash literal in `clients/client_resetdata/sql/33_meta_creatives.sql`
(not listed in the brief, same defect/same client - same filter applied, reads the same 318-row
slice); 4 status-dash ResetData Meta check filters; the `md/AGENTS.md` gotcha note.

---

## Fix 4 - TLM + ResetData TTD advertiser IDs (commit `794be2a`)

`perf_the_trade_desk` has `advertiser_id`; both confirmed IDs match the feed exactly.

| File | Filter change | | rows | spend | min day | max day | campaigns |
|---|---|---|---|---|---|---|---|
| `client_tlm/sql/02_stg_ttd.sql` | `= 'The Little Marionette'` -> `advertiser_id = 'mor6pp1' OR LOWER(TRIM(advertiser_name)) = 'the little marionette'` | Before | 2,219 | $3,690.79 | 2026-04-30 | 2026-08-04 | 1 |
| | | After | 2,219 | $3,690.79 | 2026-04-30 | 2026-08-04 | 1 |
| `client_resetdata/sql/04_stg_ttd.sql` | `= 'ResetData'` -> `advertiser_id = 'lxp46o9' OR LOWER(TRIM(advertiser_name)) = 'resetdata'` | Before | 4,357 | $22,706.73 | 2026-03-16 | 2026-08-04 | 2 |
| | | After | 4,357 | $22,706.73 | 2026-03-16 | 2026-08-04 | 2 |

**Mirrors:** 8 status-dash TTD check filters (both clients) moved in the same commit.

**City Perfume - outstanding, but the missing value is now known:** left as-is per the brief
(`advertiser_name = 'City Perfume'`), but the feed itself carries its advertiser id:
**`l4dj1fw`** (477 rows / $7,500.02 / 2026-05-01..2026-08-04, 1 campaign). Confirm `l4dj1fw`
in the TTD UI, then apply the same ID-first pattern - recorded in the SOP as pending.

---

## ResetData Reddit - loader map VERIFIED CORRECT, no change (report only)

The brief asked to verify `ingest/windsor_data_pull/reddit/reddit_loader.py`'s
`REDDIT_ACCOUNT_TO_CLIENT` after the July/August mis-map. Verified two ways:

1. **The map** (loader source): `a2_igd0szmw7roq` -> (resetdata, 100-digital);
   `a2_iq3fdsq6rem5` -> (cloudflare, transmission). Correct, with the incident history
   documented inline (the 2026-07-16 re-grant had connected Cloudflare's account under
   `client_slug='resetdata'`; fixed 2026-08-05, ResetData's account re-granted with its
   original id).
2. **The table** (`raw_windsor.perf_reddit` actuals):

| client_slug | account | rows | spend | dates | CLOUD_ACQ rows |
|---|---|---|---|---|---|
| resetdata | a2_igd0szmw7roq / ResetData Ad Account (100Digital) | 1,827 | $4,571.56 | 2026-02-04..2026-07-31 | **0** |
| cloudflare | a2_iq3fdsq6rem5 / Transmission_Cloudflare | 408 | $10,261.80 | 2026-04-01..2026-06-29 | 408 (all - correctly tagged; no dashboard reads them) |

No Cloudflare leakage under the resetdata slug, and ResetData's deleted Feb-Jun history is back
(min date 2026-02-04). The `client_slug = 'resetdata'` filter shape stays as-is.

---

## Commits

| Commit | Fix | Numbers |
|---|---|---|
| `cd14ece` | Fix 1 - Meta account scope x3 | geocon 261/$13,073.96 identical; placeholders 0->0 |
| `612f998` | Fix 2 - VMCH TTD ID-first | 9,113/$29,298.27 identical |
| `d00fdd2` | Fix 3 - ResetData Meta ID-first | 318/$4,813.03 identical |
| `794be2a` | Fix 4 - TLM + ResetData TTD IDs | 2,219/$3,690.79 and 4,357/$22,706.73, both identical |
| (this commit) | SOP 100% Digital section, this report, lineage regen | no code change |

Post-deploy note: `/go` will reapply the changed views (geocon, vmch, resetdata, tlm - bell/nextsmile
have no deployed views yet, their files are picked up at go-live) and redeploy the status job.
