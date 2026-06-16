# clients/client_cityperfume/dash_total/ — the 2nd City Perfume web app (ALL SALES)

A Cloud Run **Service** (`cityperfume-total-dash`): the **all-sales** sibling of
[`dash/`](../dash/README.md). The online-only dashboard reports **Website + Marketplace** only; this
one reports **all first-party sales — In-store POS + Website + Marketplace** (In-store POS is in fact
City Perfume's *largest* channel: ~A$13.5M vs Website ~A$6.4M vs Marketplace ~A$1.7M).

**It is a FRONT-END-ONLY fork.** The export job already ships every channel into `cityperfume.json`
(`sales_by_channel` / `sales_by_channel_daily` carry all `channel_group`s; `kpi`/`sales_kpi` carry
`revenue_total`/`revenue_instore`), and the online-only restriction was purely the dashboard's
`CHANNELS = ['Website','Marketplace']` array. So this service:

- **reuses the SAME pipeline** — same private bucket `bidbrain-analytics-cityperfume-dash`, same
  `cityperfume.json`, same export job, scheduler, dataset and views. **No new data plumbing.**
- **reuses the SAME web SA** `cityperfume-dash-web@` and the **same password + session secrets**
  (`cityperfume-dash-password`, `cityperfume-dash-session-key`) — one login opens both dashboards.
- differs from `dash/` ONLY in the bundled `dashboard.html` (+ login title/brand in `main.py`).

| File | What it is |
|---|---|
| `main.py` | Serving-identical to `dash/main.py` (login gate + `/data.json` proxy). Only the login `<title>`/brand say "All-Sales". Reads `GCS_BUCKET` + `DATA_OBJECT=cityperfume.json` from env. |
| `dashboard.html` | The all-sales UI — same 6 tabs/Chart.js/branding, but `CHANNELS` is the full universe (In-store POS + Website + Marketplace + Other) so headline revenue/orders/AOV reconcile to `revenue_total`. |
| `requirements.txt`, `Dockerfile` | Identical to `dash/` (`COPY main.py platform_sso.py dashboard.html`). |
| `platform_sso.py` | Vendored SSO trust (inert unless a real domain is wired), same as every dashboard. |
| `deploy_dash_cityperfume_total.ps1` | Stand up / redeploy this service (build image → `run deploy` → `--no-invoker-iam-check`). Idempotent; reuses the existing SA/bucket/secrets so there's no IAM step. |

**ROAS framing (the one analytical difference).** Including in-store changes what ROAS can honestly
mean, so this dashboard shows **two lenses**:
- **Headline = blended Marketing Efficiency Ratio (MER)** = *all sales ÷ ad spend* (`mer()`; backed by
  `kpi.roas_blended`). It deliberately credits the omnichannel halo onto in-store, so it is **not
  causal** and not margin-based — labelled as such everywhere it appears.
- **Secondary = the incremental ONLINE margin-ROAS** (the online dashboard's canonical metric):
  `REV_ROAS_ONLINE` × **online** gross margin, computed on `ONLINE_CHANNELS = ['Website','Marketplace']`
  only (in-store is not ad-attributable that way). The "Profit advertising adds" chart stays on this
  online-incremental basis (uses `revenue_online`), explicitly labelled "stricter lens".

**Security / runtime:** identical model to `dash/` — private bucket, `/data.json` returns 401 without
the password, JSON is aggregates-only, `--no-invoker-iam-check` (org blocks `--allow-unauthenticated`).

Redeploy after editing `dashboard.html`/`main.py`: `./deploy_dash_cityperfume_total.ps1`. The service
serves with `Cache-Control: no-store` and always reads the current JSON, so changes are live
immediately. The online-only `dash/` service (`cityperfume-dash`) is untouched.
