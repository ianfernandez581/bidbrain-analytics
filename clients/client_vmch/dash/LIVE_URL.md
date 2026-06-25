# VMCH — Live URL

**URL:** https://vmch-dash-p32gk2wuia-ts.a.run.app
(canonical: https://vmch-dash-516554645957.australia-southeast1.run.app)

**Status:** ✅ Live — revision `vmch-dash-00003-xtj` (rewritten + rebranded dashboard, 2026-06-14).
Export job `vmch-export` + scheduler `vmch-export-daily` (`*/10` UTC) are running.

The service is password-gated. Contact the team for the dashboard password.
Redeploy the UI with `dash/deploy_dash_vmch.ps1`; refresh data with `sql/deploy_views_vmch.ps1`
or `gcloud run jobs execute vmch-export --region australia-southeast1 --wait`.

## How it's accessed — the platform front-door

The normal way in is the **platform front-door — https://dashboards.bidbrain.ai/d/vmch/** (one login
over all dashboards; the front-door reverse-proxies this service and logs into it for you, so no second
password). The `…run.app` URL above is the upstream the proxy talks to and stays individually
password-gated for direct access. There is **no** `vmch.bidbrain.ai` subdomain — the front-door is the
access path. See [`bidbrain-platform/README.md`](../../../bidbrain-platform/README.md).
