# `clients/client_hireright/targets/` — the media plan, version-controlled

`media_plan.csv` is the **source of truth** for every target and flight date on the HireRight
dashboard, following the repo-wide committed-CSV → BigQuery standard (see `md/AGENTS.md` →
"Targets = committed-CSV→BQ"). It is **tracked in git on purpose** — a target that lives only in
someone's spreadsheet is a number nobody can audit six months later.

## Status: EMPTY / PENDING

Every value row is blank today. HireRight has **no signed media plan in this repo** — the dashboard
was built as a pure delivery baseline, so there is nothing to pace against yet. While the file is
blank the job emits `has_targets: false` and the dashboard **hides the whole pacing section**
rather than drawing `0 / 0` cards at 0%. Nothing incomplete reaches the client.

**This is the only file that needs to change to turn pacing on.**

## Filling it in

One row per platform line item on the plan. Leave any cell blank if the plan does not commit to it —
blank means "not bought", not zero, and the dashboard omits that metric rather than showing a red
miss against a KPI nobody agreed to. (Repo rule, learned on `client_caltex`: a target we invented
ourselves must be labelled `DERIVED` or not shown at all.)

| column | meaning |
|---|---|
| `platform` | `dv360` / `tradedesk` / `linkedin` — must match the platform keys in `stg_ad_delivery` |
| `line_item` | the plan's own line-item name (Awareness / Consideration / …). Blank if the plan buys the platform as one line. |
| `flight_start`, `flight_end` | `YYYY-MM-DD`. Blank ⇒ the dashboard falls back to OBSERVED first/last delivery and says "live since", never "flight". |
| `budget_usd` | committed spend for the line, in USD. Convert AUD lines at the rate in `sql/00_fx.sql` and note it below. |
| `imp_target`, `click_target`, `lead_target` | volume commitments |
| `ctr_target`, `cpm_target_usd`, `cpc_target_usd` | efficiency commitments |

Then:

```powershell
.\.venv\Scripts\python.exe clients\client_hireright\seed_static.py
.\.venv\Scripts\python.exe clients\client_hireright\create_views.py
gcloud run jobs execute hireright-export --region australia-southeast1 `
  --update-env-vars FORCE_REBUILD=1 --wait
```

The forced run is **required**: the freshness gate watches the three raw Snowflake tables, not seed
tables or views, so a targets edit is invisible to it and would otherwise sit unpublished until the
next upstream change.

## Open questions for whoever supplies the plan

1. **Is `budget_usd` the client-billed budget or the media cost?** The dashboard applies the
   platform's per-channel billed-spend multiplier to DELIVERED spend; if the plan budget is already
   billed-rate, it must not be grossed again or pacing will read low.
2. **Currency.** Two feeds bill in AUD. If the plan is written in AUD, state the rate it was booked
   at — `sql/00_fx.sql` currently carries an unconfirmed placeholder of 0.65.
3. **Which lead definition does the plan commit to?** The dashboard reports LinkedIn lead-gen form
   submissions and DV360/TradeDesk attributed conversions as two separate measures and never adds
   them (see `sql/04_stg_ad_delivery.sql`). A `lead_target` needs to say which one it is against.
