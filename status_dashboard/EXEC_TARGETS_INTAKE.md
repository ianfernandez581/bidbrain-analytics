# Executive dashboard — media-plan target intake

The Executive dashboard paces each client's headline metric against its **media-plan target**.
Those targets are NOT reliably in the pipeline data, so we lift them from each client's media plan
**by hand, via a separate extraction chat**, and store the clean result in
[`exec_targets.json`](./exec_targets.json) (the single source of truth the exec build reads).

**Do not commit the raw media plans.** They are inconsistent (different layouts, override notes on
top of printed dates, etc.). Let the extraction chat absorb that mess and emit a clean record; only
the clean record lands in the repo.

## Workflow
1. Open a fresh chat, paste the **brief below**, and attach/paste **one client's media plan**.
2. It returns a JSON object for that client.
3. Paste that object into `exec_targets.json` under `clients.<client-key>` (the keys are already there,
   pre-filled with the correct currency and primary metric — you're only filling numbers and dates).
4. When plans are in, tell Claude Code and it wires the pacing to read this file.

Client keys: `cloudflare, stt, schneider, resetdata, vmch, mongodb, schneiderlqai, proptrack, tlm`.
(`hireright` excluded for now; `cityperfume` dropped, no longer a client.)

> **Headline KPIs updated 2026-07-22** (re-derive the table rows below when we resume this task):
> STT = **clicks** (was leads) · MongoDB = **impressions / engagement** (was leads) · VMCH = **enquiries** with reach beside it.
> The other clients are unchanged.

---

## Brief to paste into the extraction chat

> You'll be given ONE client's **media plan**. Extract the target/KPI numbers below and return a single
> JSON object in the schema at the bottom. Rules:
> - Use `null` for anything the plan does not state. **Do not guess or infer.**
> - Numbers raw: no `k`/`M`, no currency symbols, no `%` sign (put percentages as a plain number, e.g. `0.42`).
> - Dates as `YYYY-MM-DD`.
> - **`flight_start` / `flight_end` must be the ACTUAL effective dates.** Media plans often carry a note
>   overriding the printed start/end ("live from 12 May", "paused", "extended to..."). Honor the note, use
>   the real date, and record the discrepancy in `notes`. These two dates are the single most important
>   fields — pacing "where should we be today" is impossible without them.
> - If the plan phases the target or budget by month, capture `..._by_month` — a monthly breakdown is far
>   more valuable than a single total (it replaces a straight-line pacing assumption with the real plan).
> - Capture any breakdown by channel / market / program the plan provides.
> - State the `currency` and the exact `primary_target_period` each target covers (full flight / quarter / month).
> - If anything is ambiguous, put it in `notes` rather than force a number.

### What the primary metric + KPI benchmarks are, per client

| Client | Currency | Primary target to find | KPI benchmarks to find |
|---|---|---|---|
| cloudflare | USD | Accepted CS **leads** (Q3 total + by market/region if split) | CPL, LinkedIn lead target, acceptance rate |
| stt | SGD | **Lead / conversion** target (total + monthly) | CPL/CPA, sessions, paid sessions |
| schneider | AUD | **MQL + HQL** target **per program** (water_env, eba, heavy, airset, global_rebrand) | CPL & committed spend per program |
| resetdata | AUD | **Lead** target (total + monthly) | CPL, app-signup target, paying-customer target |
| vmch | AUD | **Enquiry** target (phone+email+contact) | reach/impression target, cost-per-enquiry, budget |
| mongodb | USD | Accepted CS **leads** (total + DNB vs KGA/IDC split) | CPL; also impression + engagement targets |
| schneiderlqai | AUD | **Impression** target per channel (LinkedIn & Trade Desk) + total | CTR, CPM, live budget |
| proptrack | AUD | **Impression / reach** target (flight total) | CTR, clicks target, budget |
| cityperfume | AUD | **Target ROAS** (confirm 7x) + target online revenue | MER, revenue, AOV, budget |
| tlm | AUD | **Target ROAS** (Google) + target revenue | budget, CPA, conversions |

### Return schema
```json
{
  "client": "<key>",
  "currency": "AUD | USD | SGD",
  "flight_start": "YYYY-MM-DD or null",
  "flight_end": "YYYY-MM-DD or null",
  "primary_metric": "<as listed for this client>",
  "primary_target_total": 0,
  "primary_target_period": "full flight | quarter | month",
  "primary_target_by_month": [{ "month": "YYYY-MM", "target": 0 }],
  "primary_target_breakdown": [{ "segment": "ANZ | DNB | water_env | linkedin | ...", "target": 0 }],
  "kpi_targets": { "cpl": null, "cpm": null, "ctr_pct": null, "roas": null, "revenue": null, "budget_total": null, "budget_by_month": null },
  "notes": "anything ambiguous, or the real vs printed start date"
}
```
(Use `null` for any block that doesn't apply. The `kpi_targets` keys vary by client — see the table; add
whichever the plan actually gives.)
