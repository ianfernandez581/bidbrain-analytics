# Fast-path: re-apply TLM BigQuery views (does NOT provision infra).
# Run from the repo root with the venv active:
#   .\clients\client_tlm\sql\deploy_views_tlm.ps1
#   or: python clients\client_tlm\create_views.py
$DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
python "$DIR\..\create_views.py"

# A view-only change does NOT advance the upstream tables the freshness gate watches, so the export
# job will skip the rebuild unless forced. Re-export with FORCE_REBUILD=1 or the dashboard JSON stays stale:
Write-Host "Views reapplied. Now re-export the dashboard JSON (required after a view-only edit):"
Write-Host "  gcloud run jobs execute tlm-export --region=australia-southeast1 --project=bidbrain-analytics --update-env-vars FORCE_REBUILD=1 --wait"