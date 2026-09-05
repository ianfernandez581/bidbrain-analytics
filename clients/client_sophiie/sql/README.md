# clients/client_sophiie/sql/ — the BigQuery view definitions (the stage-2 transform)

> The version-controlled `CREATE OR REPLACE VIEW` files that turn the shared Windsor Trade Desk
> raw table into Sophiie's dashboard-ready fact. The export job ([`../job/main.py`](../job/README.md))
> reads these views to build `sophiie.json`.

**Plain English:** the raw warehouse data is generic and shared. These saved queries pick out
*only Sophiie's* rows (TTD advertiser `0lw3hp6`), parse the ad-group naming into tactic + market,
classify each row Awareness vs Consideration, and shape ONE compact fact table. **This is where
the business logic lives.**

These files are the **source of truth** — edit them and re-apply, never edit views in the
BigQuery console (or the two drift). The `NN_` prefix sets apply order.

**Where this sits:** `raw_windsor.perf_the_trade_desk` → **[these views]** → [`../job/`](../job/README.md) → `sophiie.json`.

## The views (in dependency order)

| File | View | What it does |
|---|---|---|
| [`01_stg_ttd.sql`](01_stg_ttd.sql) | `stg_ttd` | Filters `raw_windsor.perf_the_trade_desk` to **advertiser `0lw3hp6`** (name-fallback `sophiie%`). Parses `ad_group_name` "Tactic \| Market" → `tactic` + `market`; classifies `funnel_stage` (Display Standard → Awareness; AI Contextual / Attention-Optimised → Consideration — an ASSUMPTION, revisit with the media plan). Sums the anonymous TTD conversion slots into `post_view_conv` / `post_click_conv` (all 12 slots each; `conversion_touch_*` deliberately unused — see the VMCH duplicate-pair caveat in the file header). |
| [`02_fact.sql`](02_fact.sql) | `fact` | ONE row per (date × campaign × ad group × creative): sums spend/impressions/clicks/video quartiles/conversions; ad_format kept via `ANY_VALUE`. The job ships this whole as `rows[]`; the dashboard rolls everything up client-side. Ratios are NEVER stored. |
| [`03_targets.sql`](03_targets.sql) | `targets` | Thin pass-through over `seed_targets` (from `targets/targets.csv` via `../seed_static.py`). Rows with `status='PENDING'` are planning assumptions awaiting sign-off — the UI marks them. |
| [`04_budget.sql`](04_budget.sql) | `budget` | Thin pass-through over `seed_budget` (from `targets/budget.csv`): flight window + budget for `campaign_key='SOPHIIE'`. |

> **The per-client filter is the main thing you'd change** copying this folder: the advertiser id
> in `01_*` and the tactic/stage mapping.

> **Conversion slots = "Site visits" (live 2026-08-10).** Exactly ONE tracker is attached to the
> campaign's conversion reporting: the URL-scoped `Landing Page Visit` (`4tyuvnj`), so the slots
> count ad-attributed visits to the **Star Card landing page** — not all site traffic, not
> applications. `01_stg_ttd.sql` sums all 12 slots per kind (the rest are zero) so a future second
> tracker is never silently dropped — but when one IS attached (applications, once the pixel reaches
> `oa.starcard.com.au`) it must be **split out** into its own metric, here and in the status-dash
> check, never folded into site visits.
>
> **Duplicate-pair caveat (VMCH):** TTD can export one tracker as a DUPLICATE column pair. If the
> per-slot breakdown ever shows byte-identical neighbours, switch `01_stg_ttd.sql` to sum only the
> first column of each pair (the VMCH `{01,03,05}` pattern).

## Apply them

```powershell
.\.venv\Scripts\python.exe clients\client_sophiie\create_views.py
# then force the export (a view edit does not advance the freshness gate):
gcloud run jobs execute sophiie-export --region australia-southeast1 --update-env-vars FORCE_REBUILD=1 --wait
```

## See also

- [`../README.md`](../README.md) — the client overview and the 3-stage pipeline.
- [`../job/README.md`](../job/README.md) — reads these views; documents the JSON contract.
- [`../../../ingest/windsor_data_pull/tradedesk/README.md`](../../../ingest/windsor_data_pull/tradedesk/README.md) — fills `raw_windsor.perf_the_trade_desk`.
