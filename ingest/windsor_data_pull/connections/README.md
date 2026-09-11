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
| `billing_blocked` | Windsor has paused reads for the WHOLE account (plan limit). Not a grant, and not per-connector | once per episode, at account level |
| `broken` | DTS only: the transfer config's own last run is `FAILED`. The fix text carries the real error, read from that run's log | yes |
| `checking` | connector errored on ONE probe. Held for one hour to see if it repeats | **no, by design** |
| `error` | connector error on two consecutive probes (or LinkedIn's `'start'` 500) | yes |
| `idle` | expected quiet: `expected` = `ended` / `retired` / `standby`, or an account Windsor holds that the loader does not list | never |

`billing_blocked` is the only ACCOUNT-level state. On 2026-09-10 Windsor stopped serving the
whole account over a plan limit and answered `HTTP 200` with one well-formed row whose every
string field was the notice ("Uh-oh! These are not your real numbers: reads are paused because
you have 8 data sources connected and your Standard plan includes 7..."). Unrecognised, that
read as "granted, nothing delivered today" on every connector at once: Trade Desk showed `ok`
for every live client while the feed was dead, and the block surfaced only as three unrelated
`frozen` accounts on three different connectors - so the tab's advice was to go re-grant three
connectors, none of which could have worked. Three rules follow, and they are the reason this
is not just another state:

* **Detected on the RAW BODY, before the status branches** (`_BLOCKED_RE` in `probe.py`), and
  matched on the two prose fragments Windsor repeats, never the whole sentence - the plan
  counts in it change. `rows` is forced to `None` so the notice row can never be counted as a
  delivery.
* **It bypasses `frozen_after_days`.** That tolerance exists so a normal day of feed lag does
  not flap the tab; a billing block is certain on its first occurrence, so the anti-flap delay
  would simply be three days of silence on the one signal that never flaps.
* **Reported ONCE, at `account_block` in the payload** - one banner on the tab, one email per
  episode, and the per-account problem cards for it are suppressed. Per-account rows still
  carry the state so no row claims `ok`, and `standby`/`ended` accounts stay `idle` (a block
  reaches them too, but nothing on a dashboard reads them). Re-grant links are withheld
  wherever the state is live: under a block that is the most available wrong action on the page.

The same notice was written into BigQuery as a ROW by the loaders, one per table per failed
run, which made `sibling_newest_day` report today's date on tables whose newest real delivery
was days earlier. `newest_days()` drops any key matching the sentinel. **Refusing to WRITE
those rows is a loader fix and is not done here** - see the loaders, and purge the rows already
written.

`checking` exists because the two-strike rule used to be implemented by reporting the FIRST
error as `ok` - so the tab printed "granted and delivering" about a connector that had just
errored, and only the fix column disagreed. It splits the two questions that were tangled:
**what we know** (it errored once, so never again call it healthy) from **whether to page**
(unchanged - `checking` is in no BAD_STATES, and the second consecutive error produces a real
`checking -> error` transition that alerts through the existing change machinery). Email volume
is identical; only the pill in between is honest.

**`frozen_after_days` is per-datasource** as of 2026-09-11, defaulting to the global 3. Trade
Desk keeps 3 - the probe asks it for `today-2` because TTD refuses unfinalised days, so a
healthy TTD feed already sits 1 day behind. Meta / GA4 / LinkedIn / Reddit are asked for
`today-1` (floor 0) and drop to 2, which catches a stalled feed at **3 days behind instead of
4**. Note what that does NOT do: a 2-day-behind feed still reads `ok`, which is exactly what
the 2026-09-11 pause looked like - `billing_blocked` is what catches that, on the first probe,
independent of this tolerance. The values are REASONED from the request windows and the daily
schedules, not measured: `ingested_at` is in each loader's `_MERGE_SET_COLS`, so a re-fetch
rewrites it and the tables cannot answer "what is normal lag?" (checked 2026-09-11 - it reports
an 8-day median lag on a feed that lands daily).

`broken` exists because freshness alone CANNOT see a failing transfer: a broken feed and a
property with no traffic both land no rows, so eight failing GA4 transfers sat on the tab as
`idle` - which reads as "expected to be quiet". The transfer's own run state is the more
specific fact, so it outranks freshness. Two rules for it: the config's state is not enough on
its own (a run reports `SUCCEEDED` while loading nothing - the 2026-08-18 MCC failure), so the
RUN log is fetched for a `FAILED` config and its error carried into the fix text; and configs
are keyed on `params.property_id` / `params.customer_id`, never `displayName`, which is typed
by hand. Needs **`roles/bigquery.user`** on the job SA - its only transfer permission is the read
one this needs (`bigquery.transfers.get`). There is NO `roles/bigquerydatatransfer.viewer`: that
name was assumed here once and the API rejects it outright ("Role ... is not supported for this
resource"), which the deploy script had silenced behind `*> $null` - so the job deployed green,
the grant was absent, and the check did nothing. Without the grant the probe logs
`transfer states unavailable` and falls back to freshness, so it degrades rather than breaks.

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
