# Private Deployment Guide (`prod`)

This guide is the **canonical private deployment path** for `environment=prod`:

- Subscription deployment: `azure-infrastructure/bicep-templates/main.bicep` using `main.prod.parameters.json`
- Phase 2 integration deployment (private module stack): `phase2-data-ingestion/*` using `parameters/prod.parameters.json`
- Mandatory Day 2 updates: see `PRIVATE_DAY2_UPDATES.md`

## Canonical companion documents

- `DEPLOYMENT_GUIDE.md` — `dev`or `prod` subscription deployment + Phase 2 `dev`or `prod` parameters
- `DAY2_UPDATES.md` — Day 2 updates using `day2-updates/parameters/dev/*`
- `PRIVATE_DAY2_UPDATES.md` — Day 2 updates using `day2-updates/parameters/prod/*`
- `HOW_DEPLOYMENT_FITS_TOGETHER.md` — how folders, templates, scripts, and artifacts connect

## Prerequisites

- Azure CLI installed and authenticated (`az login`)
- Permissions to deploy at **subscription scope** for `main.bicep`
- Permissions for resource-group deployments in the target data resource group
- PowerShell on Windows

## Important defaults (`main.bicep`)

- **`deployMlWorkspace` defaults to `true`** — Azure Machine Learning workspace resources deploy without extra flags.
- **`deployAks` remains optional** — Kubernetes is not required unless explicitly enabled.

## 1) Session variables (copy/paste)

Adjust paths if your workspace root differs.

```powershell
$WORKSPACE = "C:\Users\olanr\Desktop\blache"

$LOCATION = "eastus2"
$ENVIRONMENT = "prod"

$ADMIN_EMAIL = "your-admin-email@company.com"
$JUMP_VM_ADMIN_PASSWORD = Read-Host "Enter Windows jump VM admin password" -MaskInput

$BICEP_TEMPLATES = Join-Path $WORKSPACE "data-pipelines\deployment\bicep\azure-infrastructure\bicep-templates"
$MAIN_PARAMS_PROD = Join-Path $BICEP_TEMPLATES "main.prod.parameters.json"

$SCRIPTS  = Join-Path $WORKSPACE "data-pipelines\deployment\bicep\azure-infrastructure\scripts"
$PHASE2   = Join-Path $WORKSPACE "data-pipelines\deployment\bicep\phase2-data-ingestion"

$DEPLOYMENT_NAME_MAIN = "main-prod-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
```

## 2) Part A — Deploy `main.bicep` (`prod`)

### 2.1 Preview (recommended)

```powershell
cd $BICEP_TEMPLATES

az deployment sub what-if `
  --location $LOCATION `
  --template-file main.bicep `
  --parameters "@main.prod.parameters.json" `
  --parameters adminEmail="$ADMIN_EMAIL" `
  --parameters jumpVmAdminPassword="$JUMP_VM_ADMIN_PASSWORD"
```

### 2.2 Apply

```powershell
az deployment sub create `
  --name $DEPLOYMENT_NAME_MAIN `
  --location $LOCATION `
  --template-file main.bicep `
  --parameters "@main.prod.parameters.json" `
  --parameters adminEmail="$ADMIN_EMAIL" `
  --parameters jumpVmAdminPassword="$JUMP_VM_ADMIN_PASSWORD"
```

### 2.3 Capture outputs

```powershell
az deployment sub show `
  --name $DEPLOYMENT_NAME_MAIN `
  --query properties.outputs `
  -o json
```

Load standardized aliases used by the Phase 2 scripts:

```powershell
cd $SCRIPTS
. .\set-vars-from-main-deployment.ps1 -DeploymentName $DEPLOYMENT_NAME_MAIN
```

### 2.4 Verify Azure Machine Learning workspace (recommended)

```powershell
az deployment sub show `
  --name $DEPLOYMENT_NAME_MAIN `
  --query properties.outputs.mlWorkspaceName.value `
  -o tsv
```

## 3) Part B — Hydrate Phase 2 `prod.parameters.json` files (recommended)

This repo includes automation to populate Phase 2 parameter files from deployment outputs:

```powershell
cd $SCRIPTS

.\hydrate-phase2-parameters.ps1 `
  -Environment prod `
  -SubscriptionDeploymentName $DEPLOYMENT_NAME_MAIN
```

## 4) Part C — Phase 2 private stack (`phase2-data-ingestion`)

Preferred: use the orchestration scripts (they preserve module order and naming alignment):

```powershell
cd $SCRIPTS

.\whatif-phase2-private.ps1 -Environment prod -DataResourceGroup $DATA_RG

.\deploy-phase2-private.ps1 -Environment prod -DataResourceGroup $DATA_RG
```

### Manual module order (same as orchestration)

If you must run modules individually, follow this order:

1. `service-bus/service-bus.bicep`
2. `azure-data-factory/data-factory.bicep`
3. `private-network/private-endpoints.bicep`
4. `functions/functions-premium.bicep` (or consumption equivalents)

Use each module’s `parameters/prod.parameters.json`.

## 5) Part D — Mandatory Day 2 updates (`prod` parameter track)

Continue in `PRIVATE_DAY2_UPDATES.md`.

Then run ADF completion/dependency checks:

- `../phase2-data-ingestion/azure-data-factory/ADF_COMPLETION_RUNBOOK.md`

## 6) Post-deploy operational checklist (minimum)

- Confirm deployments succeeded (`Succeeded`) for subscription deployment and each Phase 2 group deployment.
- Confirm Azure ML workspace exists and compute objects exist as expected.
- Continue with Day 2 updates and functional smoke tests defined in your operational standards.
