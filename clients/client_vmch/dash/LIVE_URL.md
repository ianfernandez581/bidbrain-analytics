# VMCH — Live URL

**URL:** https://vmch-dash-p32gk2wuia-ts.a.run.app
(canonical: https://vmch-dash-516554645957.australia-southeast1.run.app)

**Status:** ✅ Live — revision `vmch-dash-00003-xtj` (rewritten + rebranded dashboard, 2026-06-14).
Export job `vmch-export` + scheduler `vmch-export-daily` (`*/10` UTC) are running.

The service is password-gated. Contact the team for the dashboard password.
Redeploy the UI with `dash/deploy_dash_vmch.ps1`; refresh data with `sql/deploy_views_vmch.ps1`
or `gcloud run jobs execute vmch-export --region australia-southeast1 --wait`.
