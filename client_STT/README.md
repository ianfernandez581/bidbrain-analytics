# client_STT/ — ST Telemedia GDC (intake only, on hold)

> A prospective client folder. **No dashboard is built yet.** This holds the pre-build research
> so the build can start the moment the agency confirms scope.

**Plain English:** STT GDC (ST Telemedia Global Data Centres), via the agency Transmission, is a
client we're getting ready to build a dashboard for. The good news: their advertising data is
**already flowing** into our shared warehouse. The hold-up isn't technical — we're waiting on a
few **business decisions** from the agency (which accounts/currency count, where leads come
from, etc.) before we can correctly slice the data. Until then, this folder is just notes.

**Status:** ⏸️ **On hold** — data is in `raw_snowflake`; waiting on Transmission to confirm
scope. See the full breakdown and the ready-to-send message in [`INTAKE.md`](INTAKE.md).

---

## What's in here

| File | What it does |
|---|---|
| [`INTAKE.md`](INTAKE.md) | The complete intake analysis: which media-plan channel maps to which `raw_snowflake` table + STT identifier, what's already resolved, the open scoping questions, and a ready-to-send message to Transmission. |
| `README.md` | This file (status + orientation). |

---

## Where this will sit when it's built

STT will follow the [`client_mongodb/`](../client_mongodb/README.md) template: filter the shared
[`raw_snowflake`](../snowflake_data_pull/README.md) tables down to STT's slice, derive
market/phase/objective from the campaign-naming convention, then job → JSON → gated web app.

The data is already mirrored — STT's slice spans:

| Plan channel | `raw_snowflake` table | Notes |
|---|---|---|
| Search | `google_ads_apac` | USD account → SGD account mid-campaign |
| Social (Awareness + Lead Gen) | `linkedin_ads_apac` | USD → SGD account; naming inconsistent |
| Programmatic Display | `dv360_apac` | DV360 only — **no Trade Desk activity for STT** |

Already resolved by the data (no need to ask): TradeDesk has no STT rows; the Salesforce CS
leads table has **zero** STT rows (that feed is MongoDB-specific).

---

## What's blocking the build

Scoping decisions only Transmission/the client can confirm (full detail in
[`INTAKE.md`](INTAKE.md)):

1. **Dual account / currency** — each platform flips from a USD account to an SGD account
   ~Sept 2025; confirm both are in scope, the reporting currency, and the FX rate.
2. **SOW 2 boundary** — which POs/campaigns are SOW 2 vs older FY24 / "Organic Boosting".
3. **Leads / conversions source** — platform-native vs a CRM/Salesforce export.
4. **"Data Center Map" USA line** — in scope for this APAC dashboard?
5. **Targets** — confirm the approved plan; ideally the source spreadsheet, not a PDF.

## When unblocked

1. Copy [`client_mongodb/`](../client_mongodb/README.md) → `client_STT/` (job/, dash/, sql/),
   set `CLIENT = "stt"`.
2. Write the `sql/` filter views against the three `raw_snowflake` tables above, using the STT
   identifiers in [`INTAKE.md`](INTAKE.md), and derive market/phase from the campaign names.
3. Provision GCP + deploy per the [root playbook](../README.md#10-playbook-add-a-new-client)
   (Cloudflare's [`deploy_cloudflare.ps1`](../client_cloudflare/deploy_cloudflare.ps1) is a good
   one-shot template to copy).

## See also

- [Root README](../README.md) — the platform map and the add-a-client playbook.
- [`../client_mongodb/`](../client_mongodb/README.md) — the template STT will follow.
- [`../snowflake_data_pull/`](../snowflake_data_pull/README.md) — the shared raw layer STT will filter.
