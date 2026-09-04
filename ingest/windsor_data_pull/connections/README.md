# windsor-connections-probe - per-account Windsor connector health

Hourly Cloud Run job that probes every Windsor account we ingest, classifies it, writes
`gs://bidbrain-analytics-status-dash/windsor_connections.json`, and emails
`ian@100.digital` + `charles@100.digital` on a state change. **The Grid -> Connections tab**
(`grid-core/src/connections/connections.js`) renders that JSON and nothing else, so the tab and
the emails can never disagree.

## The problem it closes

A lapsed Windsor grant fails nothing. The loader exits green while at least one account still
resolves (its abort guard fires only at 100% skipped); the raw table keeps a fresh
`last_modified` from the surviving accounts, so the status pipeline's table-grain freshness
stays green; the export job rebuilds on schedule; and the dashboards on the dead accounts serve
last week's numbers under today's date. Three live cases: Meta (all 6 accounts, 2026-08-11 ->
re-granted 08-25 but only 2 came back), Trade Desk (seat 484 lapsed 08-21, re-grant issued NEW
seat 569 so the loader stayed pinned to a dead id), LinkedIn (30 of 34 accounts dead since
2026-07-21, still). Each was found by a person noticing a number.

## Files

| file | role |
|---|---|
| `config.json` | **the source of truth**: datasources, accounts -> client, `expected` cadence, `alerts` flag, and the **grant ledger** (`last_reauth`, `reauth_by`, `token_lifetime_days`) |
| `probe.py` | the job: probe + BigQuery newest-day + classify + carry-forward + write + alert decisions |
| `mailer.py` | the three Gmail templates (state change / morning digest / estimated expiry) + `send_gmail` |
| `gen_gmail_token.py` | ONE-TIME local: mint the `gmail.send` token -> Secret Manager `windsor-alerts-gmail-oauth` |
| `deploy_job_connections.ps1` | build + deploy + grants + hourly scheduler (+ `-Run`) |

## States (decided here, rendered there)

| state | meaning | emails? |
|---|---|---|
| `ok` | granted and the raw table is current (<= `frozen_after_days` behind) | recovery only |
| `frozen` | granted AND Windsor still returns rows for the window, but BigQuery is behind -> **a loader fault, ours** | yes |
| `quiet` | granted, Windsor returns NO rows for the window, BigQuery behind -> the platform reports no delivery (paused / finished campaign, or upstream) | no |
| `not_granted` | Windsor no longer holds the account (400 "not available"); the body names what it DOES hold | yes |
| `error` | connector error on two consecutive probes (or LinkedIn's `'start'` 500) | yes |
| `idle` | expected quiet: `expected` = `ended` / `retired` / `standby`, or an account Windsor holds that the loader does not list | never |

`alerts:false` on an account means it SHOWS on the tab but cannot page us. Use it for every
account no dashboard reads from Windsor - all the LinkedIn accounts today (those clients read
Transmission's Snowflake mirror), Cloudflare's Reddit, VMCH's fallback GA4, offboarded City
Perfume. The nav badge counts only `alerts:true` reds for the same reason.

## Emails (Gmail API, one token, send scope only)

- **State change** - one email per run that changed something, listing every change with the
  old -> new pill, what it means, the newest data day, and the exact next step; plus a
  "still red from earlier" tail. Only for `alerts:true` accounts entering or leaving a red state.
- **Morning digest** - first run at/after `digest_hour_utc` (22 UTC = 08:00 Sydney) while
  anything is still red, once per day.
- **Estimated expiry** - once per (datasource, `last_reauth`) when the estimate is within
  `expiry_warn_days`.

Never one per probe: a week-long outage is one email and six digests.

**Token:** run `gen_gmail_token.py` as the sending mailbox (its header is the runbook). Set the
OAuth consent screen to **INTERNAL** - an External app left in Testing issues 7-day refresh
tokens, which would make the expiry monitor the first thing to expire. No token = the job runs,
records each alert as `sent:false`, and the tab shows "Email alerts off".

## The expiry estimate is OURS, not Windsor's - but the re-auth date is observed, not typed

Verified against Windsor's API on 2026-09-04. What exists: `GET onboard.windsor.ai/api/common/
ds-accounts?datasource=all&api_key=...` lists every account each connector currently holds
(`account_id`, `account_name`, `datasource` - **nothing else**: no status, no expiry, no granted-on
date). Also `generate-co-user-url` (mints an "authorise via link" URL, 4-day life) and
`co-user-linked-accounts` (empty for us). Their auth-errors doc says only that "API tokens have a
limited lifespan and need periodic renewal". **So no expiry date is obtainable from Windsor**, and
the platforms cannot tell us either because Windsor holds the tokens, not us.

What the probe does instead:
- **`held` = that ds-accounts list** (authoritative, named), with the 400-text parse as fallback.
  An account Windsor holds that the loader does not list surfaces as `Unconfigured` WITH its name
  (e.g. Meta `1022273853436237` = "Calvin Pinnegar").
- **Re-grants are OBSERVED**: when a connector holds ids it did not hold on the previous run, or an
  account flips `not_granted -> granted`, `grant.observed.reauth` = today (with the evidence). A
  lapse (ids lost, or a daily account losing its grant) sets `grant.observed.lapse`. Over time the
  gap between the two IS the real token lifetime for that connector.
- `expiry_estimate = max(config.last_reauth, observed.reauth) + token_lifetime_days`. The config
  date is a seed for history; nobody has to edit it when Calvin re-grants. Lifetimes seeded: Meta
  60 d (long-lived user token - the 08-11 lapse was exactly this), LinkedIn 365 d, TTD / Reddit /
  Google / HubSpot `null` (no published lifetime or non-expiring while in use). Every surface
  labels the result **est.**

## Adding / changing an account

Edit `config.json` (`id` exactly as the LOADER stores it, prefix-free; `client` = registry key;
`expected`; `alerts`; `consumers`), then `deploy_job_connections.ps1 -Run`. The probe does not
read the loaders' `SELECT_ACCOUNTS` lists on purpose: the config carries what the loader cannot
(client, cadence, whether anyone reads it), and an account Windsor holds that neither lists
surfaces as an `Unconfigured` idle row - the 484 -> 569 shape.

## Local run (real Windsor + BigQuery, no email, no bucket write)

```
$env:CLOUDSDK_ACTIVE_CONFIG_NAME='personal'
.\.venv\Scripts\python.exe ingest\windsor_data_pull\connections\probe.py --local grid-core\data\windsor_connections.json --no-email
```
Then `node grid-core\server.js` and open `http://localhost:8787/the-grid.html#view=connections`
(the server falls back to `data/windsor_connections.json` when `GRID_CONNECTIONS_BUCKET` is unset;
set `GRID_CONNECTIONS_PROBE_CMD` to that python line to make the tab's "Probe now" work locally).

## Gotchas

- **Meta / LinkedIn / Reddit go through the blended `/all` endpoint with a prefixed
  `select_accounts`** (`facebook__`, `linkedin__`, `reddit__`); TTD / GA4 use their dedicated
  endpoints with bare ids; HubSpot takes no account. The probe mirrors each loader's own request
  shape so a grant that works for the probe works for the loader.
- **TTD is ONE seat carrying six advertisers.** The seat is probed once; per-advertiser state comes
  from the probe rows grouped by `advertiser_id` plus BigQuery's per-advertiser newest day. TTD
  refuses unfinalised days, so its window ends at today-2 and a "not published" 400 counts as granted.
- **GA4 probes only the pinned properties** (`GA4_ACCOUNTS` on the loader = the two Geocon ones);
  the other 20 laptop-list properties are not in config on purpose.
- **Probe request volume:** ~48/hour (34 of them LinkedIn ids that mostly 400 in milliseconds).
- `error` needs two consecutive probes before it alerts; a single transient 5xx is not news.
- The status pipeline (`status_dashboard`) is TABLE-grain and stays as is - this job is the
  ACCOUNT-grain complement, not a replacement.
