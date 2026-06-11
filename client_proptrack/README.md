# client_proptrack/ — PropTrack (REA Group), via Transmission

Paid-media dashboard for PropTrack's **Banking ABM** story: an always-on **LinkedIn** presence plus a
concentrated May–Jun 2026 programmatic ABM burst on **The Trade Desk**. Built on the
[`client_STT`](../client_STT/README.md) scaffold — the lean, paid-media-only archetype that reads
straight from the shared `raw_snowflake` layer (no `src_*` step). **Single currency = AUD; there is no FX.**

**3 stages (same shape as every client):** `sql/*.sql` filter + roll up PropTrack's two sources →
`job/main.py` writes one `proptrack.json` to a private bucket → `dash/` serves it behind a password gate.

**Two sources, two spellings of the client (same advertiser):**
- **The Trade Desk** — `raw_snowflake.tradedesk_apac_all`, `ADVERTISER_NAME = 'PopTrack'`. ⚠️ Impressions
  come from `IMPRESSION` (singular); the plural `IMPRESSIONS` is NULL here. Conversions are pixel conv.
- **LinkedIn** — `raw_snowflake.linkedin_ads_apac`, `ACCOUNT_NAME = 'PropTrack_TransmissionSG_AUD'`. Spend
  is native AUD (no ×1.34). Delivery is intermittent (real gaps Sep/Oct 2025, Mar/Apr 2026).

**Deploy (PowerShell, project `bidbrain-analytics` / `australia-southeast1`):**
- First-time stand-up: `.\client_proptrack\deploy_proptrack.ps1` (idempotent — bucket, dataset, SAs, IAM, secrets, job, scheduler, service).
- Edited a view → `.\client_proptrack\sql\deploy_views_proptrack.ps1` · edited `job/main.py` → `.\client_proptrack\job\deploy_job_proptrack.ps1` · edited `dash/` → `.\client_proptrack\dash\deploy_dash_proptrack.ps1`.

| | |
|---|---|
| Dataset / bucket / object | `client_proptrack` / `bidbrain-analytics-proptrack-dash` / `proptrack.json` |
| Export job / web service | `proptrack-export` / `proptrack-dash` (SAs `proptrack-dash-job@…` / `proptrack-dash-web@…`) |
| Secrets / scheduler | `proptrack-dash-password` · `proptrack-dash-session-key` / `proptrack-export-daily` (`*/10` UTC, self-gating) |
