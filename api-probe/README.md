# api-probe

A tiny, **read-only** Node.js CLI that answers one question before you build the
real executive dashboard: **do we actually have working reporting API access to
each ad platform?**

For each platform it makes the *minimal authenticated call* that returns
last-7-days campaign spend / impressions, then prints:

```
PLATFORM | AUTH OK? | DATA OK? | STATUS | ERROR
```

...and a readiness summary (**GREEN** ready · **YELLOW** auth ok but no data /
scope missing · **RED** blocked / needs account-team enablement) plus setup
instructions for anything not configured.

It **never makes a write/mutate call** — reporting reads only. (Where a platform's
reporting genuinely *requires* a POST — TTD auth + report query, Reddit's report
endpoint — that POST is a reporting read, not a campaign change. DV360's real
spend needs a Bid Manager query *run*, which is a write, so the probe stops at
confirming auth + reporting-API reachability there.)

## Run

Zero runtime dependencies — needs only Node 18+ (uses the built-in global `fetch`).

```bash
cp .env.example .env      # then fill in whatever creds you have
node index.js             # probe everything configured
node index.js --only meta # just one platform
node index.js --json      # machine-readable
node index.js --verbose   # include raw provider error detail
node index.js --help
```

No `npm install` required. `.env` is git-ignored — **never commit real creds.**
Any platform whose required vars are blank is reported `NOT CONFIGURED` and
skipped (with setup notes), so you can probe one platform at a time as creds
arrive.

Exit code is `1` if any platform is **RED** (CI signal); `NOT CONFIGURED` alone
never fails the run.

## Structure — reused verbatim by the real app

Each platform is an isolated module in [`connectors/`](connectors/) exporting
`async fetchReport({ env, start, end })`, which returns rows in **one normalized
shape** (the contract the executive dashboard will consume):

```js
{ campaign, channel, spend, clientSpent, impressions, budget, start, end }
```

- `spend` — media cost in the account currency
- `clientSpent` — what the client is billed (== `spend` unless there's a markup,
  e.g. ResetData bills Reddit at 2×)
- `budget` — campaign/line budget if the report exposes it, else `null`

Connectors throw a `ProbeError` carrying a **stage** (`auth` / `scope` / `data` /
`enablement`) so the runner can tell "bad password" from "missing scope" from
"your TTD rep hasn't turned this on". Shared helpers live in [`lib/`](lib/)
(env loader, HTTP+timeout, Google OAuth refresh, table rendering).

## Platforms & the exact call each makes

| Platform | Call | Notes |
|---|---|---|
| **Google Ads** | `POST googleAds:search` (GAQL, `LAST_7_DAYS`, `LIMIT 1`) | needs developer token + OAuth2 refresh token + MCC `login-customer-id`; `cost_micros ÷ 1e6`. Bump `GOOGLE_ADS_API_VERSION` if the version 404s. |
| **Meta** | `GET /act_{id}/insights?date_preset=last_7d` | System-User token; account id digits only. |
| **LinkedIn** | `GET /rest/adAnalytics` (finder `q=analytics`, pivot CAMPAIGN) | needs `r_ads_reporting`; a 403 → scope missing (YELLOW). |
| **Reddit Ads** | refresh-token OAuth, then `POST /ad_accounts/{id}/reports` | needs `ads.read`; descriptive User-Agent required. |
| **The Trade Desk** | `POST /authentication`, then `POST /myreports/reportexecution/query/partners` | **3rd-party My Reports API is off by default** — a 403 here is surfaced as `enablement` (RED): your rep must enable it. Real spend needs a scheduled report template. |
| **DV360** | OAuth2, then read-only reachability of DV360 API + Bid Manager | confirms auth + reporting access; fresh spend needs a Bid Manager query *run* (a write), out of scope for a read-only probe. |

## Interpreting the result

- **GREEN** — the minimal report call returned rows. You can build against it now.
- **YELLOW** — authenticated, but no rows / a missing scope / reporting reachable
  but no report to read. Usually a self-serve fix (re-consent a scope, schedule a
  report, or there was just no spend in the window).
- **RED** — either auth failed (wrong/expired creds) or the platform needs an
  external party to enable access (the TTD case). Blocked until someone acts.

> Feasibility note: run with dummy creds, all six endpoints respond with proper
> API auth errors (not DNS/404), which confirms every URL + request shape is
> correct. Swap in real credentials and GREEN/YELLOW/RED becomes the real answer.
