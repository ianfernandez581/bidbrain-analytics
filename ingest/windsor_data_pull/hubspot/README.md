# windsor_data_pull/hubspot/ — Reset Data HubSpot CRM (`raw_windsor.hubspot_contacts` / `hubspot_deals`)

> A windsor loader, but **CRM state, not ad performance**. Snapshots Reset Data's HubSpot
> Contacts + Deals (via Windsor connector `hubspot`, account `45274177`) into BigQuery to power
> the Reset Data marketing dashboard (lifecycle/owner/source breakdowns, deal-ROI, app-signup
> timeline, **RdBillingBalance** per contact, ad/source attribution).

## What it pulls
- **`raw_windsor.hubspot_contacts`** — one row per HubSpot contact (~4,700), **147 contact fields**
  incl. Reset Data's custom `contact_rd_*` properties (the app/billing fields).
- **`raw_windsor.hubspot_deals`** — one row per deal (~242), **40 deal fields**.

Both come back in a **single request each** (no pagination at this scale). Every column is
**STRING** — a lossless raw mirror; **typing is the dashboard view's job** (repo rule: raw mirrors,
views type). Plus `account_id`, `client_slug='resetdata'`, `agency_slug='100-digital'`, `_pulled_at`,
and a `raw_row` JSON of the full original record.

The exact Windsor field tokens were chosen by searching the **per-account** field catalogue
(`https://connectors.windsor.ai/hubspot/fields` — 2,144 fields incl. custom props, a superset of the
public 1,070-field `raw_windsor.windsor_fields` catalogue) across the dashboard's 6 data categories.
**Crown jewel:** `contact_rd_billing_balance` = the client's **RdBillingBalance** custom property
(108 contacts carry a non-zero balance).

## Snapshot, not incremental
HubSpot here is **current-state** (one row per object, no date grain), so each run **WRITE_TRUNCATE**s
— the table always equals "HubSpot right now". (The ad-platform windsor loaders MERGE because they're
date-series; this one does not.)

## Run
```powershell
.\.venv\Scripts\python.exe ingest\windsor_data_pull\hubspot\hubspot_loader.py
```
Reads the Windsor key from Secret Manager (`windsor-api-key`) via ADC — never inline it. The connector
data endpoint **does** need the key (unlike the public `/all/fields` catalogue).

## Re-discover fields (incl. new custom properties)
The authoritative, account-specific field list (with custom `contact_rd_*` props) is:
```
GET https://connectors.windsor.ai/hubspot/fields?api_key=<windsor-api-key>
```
Returns ~2,144 `{id, name, type, table, ...}` objects; `table` ∈ {contact, deal, company, owner, …}.
Pass any `id` in `fields=` to pull it. **Always include `contact_hs_object_id` / `deal_hs_object_id`**
or Windsor dedupes to distinct value-combos instead of one row per object.

## NOT yet wired (follow-ups)
- **Not scheduled.** Run from a laptop for now. To productionise, add it to
  `scripts/deploy_ingest_jobs.ps1` as `windsor-hubspot-ingest` (daily, like meta/tradedesk) — there is
  **no `_freshness.json` watermark** for windsor loaders (they're fixed-daily by design).
- **Typed dashboard views + the dashboard itself** are the next step (this unit only lands the raw layer).
  See `create_hubspot_views.sql` for a starter typed view over the STRING columns.
