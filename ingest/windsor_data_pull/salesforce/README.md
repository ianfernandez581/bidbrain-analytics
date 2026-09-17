# windsor-salesforce-ingest - Geocon CRM leads

Daily Cloud Run job (**21:05 UTC** = 07:05 AEST, first in the nightly ingest block) that mirrors **Geocon's Salesforce leads** from Windsor into
`raw_windsor.geocon_salesforce_leads`. It is the source behind the Geocon dashboard's **Enquiries
from the CRM** section (`client_geocon/sql/13_stg_salesforce.sql` -> the export's `crm` block).

| file | role |
|---|---|
| `create_salesforce_table.py` | one-time: creates the raw table (partitioned on `created_date`, clustered on project/source) |
| `salesforce_loader.py` | the job: fetch -> transform -> stage -> MERGE on `lead_id` |
| `Dockerfile` / `requirements.txt` | the container the scheduled job runs |

## The one Salesforce connection

Windsor holds **exactly one** Salesforce grant across the whole account:

```
{"account_id": "salesforce__calvin@100.digital", "account_name": null, "datasource": "salesforce"}
```

`ds-accounts` returns no org name, so the org was identified from the data: ACT property-law custom
objects (`Crown_Lease_of_the_Land__c`, `Date_for_Registration_of_Units_Plan__c`, `Block__c`) and
campaign names (Gateway Braddon, Abode Hotels, Midnight Hotel, Braddon Merchant, No10). That is
Geocon. The live catalogue exposes **325 objects**, not the 12 Windsor's public docs advertise,
because it reflects Geocon's real org including installed packages (`smagicinteract__` SMS Magic,
`et4ae5__` Marketing Cloud, `dfsle__`/`dsfs__` DocuSign, `congaworkflow__` Conga).

**If a second org is ever granted, this loader MUST gain an account filter** - there is no account
dimension in the request today, so two clients' leads would silently merge into one table. That is
the shared-mirror trap in `md/AGENTS.md`.

## Why this loader does not look like the ad loaders

| | ad loaders (meta/reddit/linkedin) | this one |
|---|---|---|
| grain | account x ad x date | **lead id** |
| measures | additive (impressions, spend) | **none** - a lead is a record |
| lookback | 7 days (conversions settle) | **90 days** - a lead's `Status` keeps moving for months |
| accounts | a loop over `SELECT_ACCOUNTS` | one connection, no `select_accounts` |
| MERGE key | account + ad + date | `lead_id` |

## NO PII, by design

The Salesforce lead object exposes **227 fields** including name, email, phone and date of birth.
This loader requests **seven**: `lead_id`, created date, project of interest (id + text),
development name, source, status.

The dashboard needs counts by day and development, and `geocon.json` is served to the client's
browser - so anything landing in this table is one view away from being published. Do not add a
personal field "just in case". (Precedent: `client_schneider/sql/17_stg_salesforce` drops
phone/email; `client_cloudflare` gates its per-lead table behind `BB_INTERNAL` and *still* ships the
numbers in its payload, which is the failure mode to avoid rather than copy.)

## Date semantics (verified against the live API, 2026-09-17)

- `date_from` / `date_to` filter on the lead's **created** date, not last-modified. A 32-day request
  returned rows whose min/max created dates were exactly the requested bounds, and 32 single-day
  requests summed to precisely the same total as one 32-day request (198) - so the window is honoured
  exactly and nothing is capped or paginated away.
- `created_at` arrives UTC (`+0000`); **`created_date` is derived in `Australia/Sydney`**, because
  the enquiry happened in Canberra and a UTC date files a 9am local enquiry under the previous day
  for ten hours out of every twenty-four. Every consumer reads `created_date`, so they cannot
  disagree.

## What it cannot see

Across three years and 7,918 leads, **zero** rows come back with `IsConverted`, `IsDeleted` or
`MasterRecordId` set. For a live CRM that is implausible, so Windsor is almost certainly excluding
converted, deleted and merged leads. The effect is a **level shift, not a trend break** (the same
exclusion applied in 2024), but a count from this table is *"open leads Windsor can see"*, not
*"every lead Salesforce holds"*. Reconcile against a Salesforce report before quoting it as the
latter.

## Running it

```powershell
# one-time, before the first load
.\.venv\Scripts\python.exe ingest\windsor_data_pull\salesforce\create_salesforce_table.py

# normal / scheduled: 90-day trailing re-pull, MERGEd
.\.venv\Scripts\python.exe ingest\windsor_data_pull\salesforce\salesforce_loader.py

# backfill / reconciliation: an explicit window
.\.venv\Scripts\python.exe ingest\windsor_data_pull\salesforce\salesforce_loader.py 2023-01-01 2026-09-17

# deploy + (re)schedule the Cloud Run job
.\scripts\deploy_ingest_jobs.ps1 -Only salesforce
```

Env overrides: `SF_LOOKBACK_DAYS` (90), `SF_CHUNK_DAYS` (365), `SF_TIMEOUT_SEC` (300),
`SF_MAX_ATTEMPTS` (6), `WINDSOR_API_KEY` (otherwise Secret Manager `windsor-api-key`).

An empty window is **success, not failure** (a quiet fortnight is legitimate) - the job logs it and
leaves the table untouched.

## Gotchas

- **The scope audit is the job log.** Every run prints the project breakdown (`The Grande=266,
  Gateway=260, ...`) and how many leads are not `Gateway`. Only `Gateway` reaches the dashboard, so
  a NEW Geocon development announces itself there rather than being silently absent.
- **This connector is NOT in `connections/config.json`**, so the Grid's Connections tab cannot see
  it and a lapsed grant will not alarm. Add it there when convenient - the loader itself will simply
  start failing on a 4xx, which is at least loud in the job's execution history.
- **`create_salesforce_table.py` must run before the loader.** The loader reads the live schema at
  runtime and never creates or alters the table, so staging/MERGE cannot drift from it.
