# Fast-path: re-apply TLM BigQuery views (does NOT provision infra).
# Run from the repo root with the venv active:
#   .\clients\client_tlm\sql\deploy_views_tlm.ps1
#   or: python clients\client_tlm\create_views.py
$DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
python "$DIR\..\create_views.py"