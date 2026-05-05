# Deployment Guide (`dev`, with env toggle pattern)

This guide is the **default operator path** for deploying the Data Engineering Azure footprint using:

- Subscription deployment: `azure-infrastructure/bicep-templates/main.bicep`
- Phase 2 integration modules: `phase2-data-ingestion/*`
- Mandatory Day 2 updates: see `DAY2_UPDATES.md`

You can keep this guide as the base and use the toggle pattern below to switch between `dev` and `prod` naming/parameter tracks. For full private prod hardening sequence, still use `PRIVATE_DEPLOYMENT_GUIDE.md`.

## Canonical companion documents

- `PRIVATE_DEPLOYMENT_GUIDE.md` — `prod` subscription deployment + Phase 2 private module deployment flow
- `DAY2_UPDATES.md` — Day 2 updates using `day2-updates/parameters/dev/*`
- `PRIVATE_DAY2_UPDATES.md` — Day 2 updates using `day2-updates/parameters/prod/*`
- `HOW_DEPLOYMENT_FITS_TOGETHER.md` — how folders, templates, scripts, and artifacts connect

## Prerequisites

- Azure CLI installed and authenticated (`az login`)
- Permissions to deploy at **subscription scope** for `main.bicep`
- PowerShell on Windows (examples below use PowerShell)

## Important defaults (`main.bicep`)

- **`deployMlWorkspace` defaults to `true`** — Azure Machine Learning workspace resources are deployed without requiring extra flags.
- **`deployAks` remains optional** — Kubernetes is not required for this deployment path unless you explicitly enable it.

## 1) Session setup

```powershell
$WORKSPACE = "C:\Users\olanr\Desktop\blache"
$BICEP_TEMPLATES = Join-Path $WORKSPACE "data-pipelines\deployment\bicep\azure-infrastructure\bicep-templates"
$PHASE2 = Join-Path $WORKSPACE "data-pipelines\deployment\bicep\phase2-data-ingestion"
$SCRIPTS = Join-Path $WORKSPACE "data-pipelines\deployment\bicep\azure-infrastructure\scripts"

$LOCATION = "eastus2"
$ENVIRONMENT = "dev"   # dev | prod
$ORG_NAME = "payswitch"
$PROJECT_NAME = "creditscore"
$ADMIN_EMAIL = "your-admin-email@company.com"

if ($ENVIRONMENT -notin @("dev", "prod")) {
  throw "ENVIRONMENT must be dev or prod."
}

$DEPLOYMENT_NAME_PREFIX = "main-$ENVIRONMENT"
$DEPLOYMENT_NAME_MAIN = "$DEPLOYMENT_NAME_PREFIX-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
$PHASE2_PARAM_ENV = $ENVIRONMENT
$DAY2_PARAMS_DIR = Join-Path $WORKSPACE "data-pipelines\deployment\bicep\day2-updates\parameters\$ENVIRONMENT"
```

### Environment toggle notes

- `dev`: use this guide + `DAY2_UPDATES.md`.
- `prod`: prefer `PRIVATE_DEPLOYMENT_GUIDE.md` + `PRIVATE_DAY2_UPDATES.md` (private networking flow and prod-specific validation).
- If you execute commands manually from this guide for `prod`, ensure every parameter path and deployment-name prefix uses `$ENVIRONMENT`-derived values (no hardcoded `dev`).

## 2) Deploy `main.bicep` (`dev`)

This provisions the subscription-level resource groups and core platform modules, including **Azure ML workspace** by default.

```powershell
cd $BICEP_TEMPLATES

az deployment sub create `
  --name $DEPLOYMENT_NAME_MAIN `
  --location $LOCATION `
  --template-file ".\main.bicep" `
  --parameters environment=$ENVIRONMENT `
  --parameters primaryLocation=$LOCATION `
  --parameters orgName=$ORG_NAME `
  --parameters projectName=$PROJECT_NAME `
  --parameters adminEmail="$ADMIN_EMAIL" `
  --parameters deployJumpBox=false
```

Notes:

- If you truly need to disable ML for a special case, pass `--parameters deployMlWorkspace=false` (not required for normal deployments).

## 3) Load deployment outputs into variables

```powershell
cd $SCRIPTS
. .\set-vars-from-main-deployment.ps1 -DeploymentName $DEPLOYMENT_NAME_MAIN -RequireCoreValues

$SERVICEBUS_NAMESPACE = az servicebus namespace list -g $DATA_RG --query "[0].name" -o tsv
$KEYVAULT_NAME = az keyvault list -g $SECURITY_RG --query "[0].name" -o tsv
$BLOB_STORAGE_ACCOUNT = $MainBlobStorageAccountName
$DATALAKE_STORAGE_ACCOUNT = $MainDataLakeStorageAccountName
```

Optional (recommended) — verify or grant Key Vault secret write rights for your signed-in user (needed for Day 2 PostgreSQL secret bootstrap):

```powershell
$CURRENT_USER_OBJECT_ID = az ad signed-in-user show --query id -o tsv
$KEYVAULT_ID = az keyvault show -n $KEYVAULT_NAME -g $SECURITY_RG --query id -o tsv

# Check existing assignment
az role assignment list `
  --scope $KEYVAULT_ID `
  --assignee-object-id $CURRENT_USER_OBJECT_ID `
  --query "[?roleDefinitionName=='Key Vault Secrets Officer'] | length(@)" `
  -o tsv

# Grant if needed (idempotent at operator level: run only when check returns 0)
az role assignment create `
  --assignee-object-id $CURRENT_USER_OBJECT_ID `
  --assignee-principal-type User `
  --role "Key Vault Secrets Officer" `
  --scope $KEYVAULT_ID
```

## 4) Verify Azure Machine Learning workspace (recommended)

`main.bicep` emits `mlWorkspaceName` when ML is deployed.

```powershell
az deployment sub show `
  --name $DEPLOYMENT_NAME_MAIN `
  --query properties.outputs.mlWorkspaceName.value `
  -o tsv
```

Optional resource verification:

```powershell
az resource list `
  -g $ML_RG `
  --resource-type Microsoft.MachineLearningServices/workspaces `
  -o table
```

## 5) Deploy Phase 2 resources (`phase2-data-ingestion`)

Phase 2 deploys the integration layer (messaging, orchestration factory, hosting tier objects). Use the `dev` parameter files.

```powershell
# Service Bus
az deployment group create `
  --resource-group $DATA_RG `
  --template-file "$PHASE2\service-bus\service-bus.bicep" `
  --parameters "@$PHASE2\service-bus\parameters\dev.parameters.json"

# Azure Data Factory
az deployment group create `
  --resource-group $DATA_RG `
  --template-file "$PHASE2\azure-data-factory\data-factory.bicep" `
  --parameters "@$PHASE2\azure-data-factory\parameters\dev.parameters.json"

# Functions (choose one tier)
# Premium:
az deployment group create `
  --resource-group $DATA_RG `
  --template-file "$PHASE2\functions\functions-premium.bicep" `
  --parameters "@$PHASE2\functions\parameters\dev.parameters.json"

# OR consumption:
# az deployment group create `
#   --resource-group $DATA_RG `
#   --template-file "$PHASE2\functions\functions-consumption.bicep" `
#   --parameters "@$PHASE2\functions\parameters\dev.parameters.json"
```

## 6) Mandatory Day 2 updates (match environment track)

Continue in:

- `DAY2_UPDATES.md` for `dev` or `prod`
- `PRIVATE_DAY2_UPDATES.md` for `prod`

## 7) Application packaging / releases

Function code deployment is handled per app (ZIP deploy, Core Tools publish, or CI/CD). This repository contains per-function deployment scripts under:

- `data-pipelines/functions/*/deploy.ps1`
