# deploy_dash_foodbank.ps1 (shim) - the estate's ship flow (scripts/merge-branches.ps1
# Resolve-DeployPlan) looks for dash/deploy_dash_<c>.ps1 when anything under dash/ changes.
# This client keeps its deploy scripts in deploy/ (per its build brief), so this shim just
# forwards there. Excluded from the container by dash/.dockerignore (*.ps1).
& (Join-Path $PSScriptRoot "..\deploy\deploy_dash_foodbank.ps1") @args
exit $LASTEXITCODE
