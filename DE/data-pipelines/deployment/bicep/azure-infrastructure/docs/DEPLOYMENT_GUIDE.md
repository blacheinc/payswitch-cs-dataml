# Deployment Guide (environment toggle)

This guide is the **default operator path** for deploying the Data Engineering Azure footprint using:

- Subscription deployment: `azure-infrastructure/bicep-templates/main.default.bicep`
- Phase 2 integration modules: `phase2-data-ingestion/*`
- Mandatory Day 2 updates: see `DAY2_UPDATES.md`

Use **`$ENVIRONMENT`** (session setup below) so paths and deployment names stay aligned with your parameter files. For **private connectivity** (jump host, private endpoints, Phase 2 private orchestration scripts), follow **`PRIVATE_DEPLOYMENT_GUIDE.md`** instead.

## Before You Run Anything (exact files to fill)

Fill these files in order before running commands:

1. **Main subscription deployment (required)**
   - File: `bicep-templates/main.parameters.json` (or `bicep-templates/main.prod.parameters.json`)
   - Fill at minimum: `orgName`, `projectName`, `environment`, `primaryLocation`, `tags`, `adminEmail`, and relevant feature flags.

2. **Phase 2 deployment (required if you deploy Phase 2)**
   - Files: `phase2-data-ingestion/**/parameters/*.json` for the same environment
   - Fill values required by each module parameter file (or hydrate them after `main.bicep` as described later in this guide).

3. **Day 2 updates (required for Day 2 runbook)**
   - Files: `day2-updates/parameters/<environment>/*.json`
   - Fill module-specific Day 2 values for the selected environment folder.

Session variables help, but they are not a replacement for parameter files:
- `Sync-EnvFromMainParameters.ps1` loads naming values from your `main.*.parameters.json` into `$env:*`.
- `set-vars-from-main-deployment.ps1` loads live deployment outputs (resource groups, storage names, etc.) after `main.bicep` succeeds.

## Edit the parameter files

**You change deployment behavior by editing the JSON parameter files—not by editing `main.bicep` for routine settings.**

| What you change | Where you edit |
|-----------------|----------------|
| Subscription deploy (`main.default.bicep`) — region, environment, tags, jump VM, etc. | **`bicep-templates/main.parameters.json`** and/or **`main.prod.parameters.json`** (pick one file per deploy and point **`$MAIN_PARAMS`** at it). |
| Phase 2 modules | **`phase2-data-ingestion/**/parameters/*.json`** for the environment you deploy (for example `dev.parameters.json`, `prod.parameters.json`). |
| Day 2 deltas | **`day2-updates/parameters/<environment>/`** per the Day 2 runbooks. |

Then run **`az deployment sub create ... --parameters "@$MAIN_PARAMS"`** so Azure reads your edits.

## Canonical companion documents

- `PRIVATE_DEPLOYMENT_GUIDE.md` — private-network subscription deployment + Phase 2 private stack
- `DAY2_UPDATES.md` — Day 2 updates with parameters under `day2-updates/parameters/<environment>/`
- `PRIVATE_DAY2_UPDATES.md` — Day 2 updates for the private deployment guide with parameters under `day2-updates/parameters/<environment>/`
- `HOW_DEPLOYMENT_FITS_TOGETHER.md` — how folders, templates, scripts, and artifacts connect
- `TEARDOWN.md` — delete subscription resource groups created by `main.bicep` (`destroy.ps1` / `destroy.sh`)

## Prerequisites

- Azure CLI installed and authenticated (`az login`)
- Permissions to deploy at **subscription scope** for `main.bicep`
- PowerShell on Windows (examples below use PowerShell)

## Important defaults (`main.bicep`)

- **`deployMlWorkspace` defaults to `true`** — Azure Machine Learning workspace resources are deployed without requiring extra flags.
- **`deployAks` remains optional** — Kubernetes is not required for this deployment path unless you explicitly enable it.
- **`privateNetworkMode` defaults to `false`** in `main.bicep` — Key Vault and the data layer stay **operator-friendly** (Key Vault network **Allow** by default). Set **`privateNetworkMode`** to **`true`** in parameters only when you intentionally want the private posture (see **`PRIVATE_DEPLOYMENT_GUIDE.md`**).

## 1) Session setup

Fill **`bicep-templates/main.parameters.json`** (or your chosen file) first — see **[OPERATOR_CONFIGURATION.md](OPERATOR_CONFIGURATION.md)**. Optionally dot-source **`scripts/Sync-EnvFromMainParameters.ps1`** so `ORG_NAME` / `PROJECT_NAME` / `ENVIRONMENT` match that file.

```powershell
$WORKSPACE = "C:\path\to\your\repo-clone"
$BICEP_TEMPLATES = Join-Path $WORKSPACE "data-pipelines\deployment\bicep\azure-infrastructure\bicep-templates"
$PHASE2 = Join-Path $WORKSPACE "data-pipelines\deployment\bicep\phase2-data-ingestion"
$SCRIPTS = Join-Path $WORKSPACE "data-pipelines\deployment\bicep\azure-infrastructure\scripts"

# Must match `primaryLocation` in your main parameter file (e.g. main.parameters.json → eastus2).
$LOCATION = "eastus2"
$ENVIRONMENT = "<environment>"   # must match parameter file prefix / folders (see Phase 2 + Day 2 checked-in names)
$ORG_NAME = "<orgName from your main.parameters.json>"
$PROJECT_NAME = "<projectName from your main.parameters.json>"
$ADMIN_EMAIL = "your-admin-email@company.com"

if ($ENVIRONMENT -notin @("dev", "prod")) {
  throw "ENVIRONMENT must be dev or prod."
}

$DEPLOYMENT_NAME_PREFIX = "main-$ENVIRONMENT"
$DEPLOYMENT_NAME_MAIN = "$DEPLOYMENT_NAME_PREFIX-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
$PHASE2_PARAM_ENV = $ENVIRONMENT
$DAY2_PARAMS_DIR = Join-Path $WORKSPACE "data-pipelines\deployment\bicep\day2-updates\parameters\$ENVIRONMENT"

# Subscription deploy input — pick the JSON next to main.bicep (examples: main.parameters.json, main.prod.parameters.json).
$MAIN_PARAMS = Join-Path $BICEP_TEMPLATES "main.parameters.json"
```

### Environment toggle notes

- **Default / non-private footprint:** this guide + `DAY2_UPDATES.md`; set **`$ENVIRONMENT`** to the subdirectory name under `day2-updates/parameters/` that you use with this guide.
- **Private footprint:** prefer `PRIVATE_DEPLOYMENT_GUIDE.md` + `PRIVATE_DAY2_UPDATES.md`; set **`$ENVIRONMENT`** to the subdirectory under `day2-updates/parameters/` that matches the private deployment parameter set.
- Whatever value you set for **`$ENVIRONMENT`**, keep parameter paths, `-Environment` arguments, and deployment-name prefixes derived from it—do not mix tracks.

## 2) Deploy `main.bicep`

This provisions the subscription-level resource groups and core platform modules, including **Azure ML workspace** by default.

Use **`--parameters "@$MAIN_PARAMS"`** so **`environment`**, **`primaryLocation`**, **`privateNetworkMode`**, and the rest come from the JSON next to `main.bicep`—not from duplicate inline flags. Set **`$MAIN_PARAMS`** in section 1 (for example `main.parameters.json` or `main.prod.parameters.json`). **`$LOCATION`** must match **`primaryLocation`** in that same file (both **`eastus2`** in the checked-in examples).

```powershell
cd $BICEP_TEMPLATES

az deployment sub create `
  --name $DEPLOYMENT_NAME_MAIN `
  --location $LOCATION `
  --template-file ".\main.default.bicep" `
  --parameters "@$MAIN_PARAMS"
```

Optional overrides (only when you need to change one value without editing the JSON):

```powershell
az deployment sub create `
  --name $DEPLOYMENT_NAME_MAIN `
  --location $LOCATION `
  --template-file ".\main.default.bicep" `
  --parameters "@$MAIN_PARAMS" `
  --parameters deployJumpBox=false
```

Notes:

- If you truly need to disable ML for a special case, add `--parameters deployMlWorkspace=false` (not required for normal deployments).

## 3) Hydrate Phase 2 parameter files — pass **1** of **2** (after `main.bicep`)

Run this **after** `main.bicep` succeeds so Phase 2 JSON under `phase2-data-ingestion/` is filled from subscription deployment outputs (and live Azure discovery where needed).

**Script (repo-relative path):** `deployment/bicep/azure-infrastructure/scripts/hydrate-phase2-parameters.ps1`  
From **section 1**, use `$SCRIPTS` (`Join-Path $WORKSPACE "data-pipelines\deployment\bicep\azure-infrastructure\scripts"`).

This script updates **every** Phase 2 environment parameter file it knows about—not only Functions—including for example `service-bus/`, `azure-data-factory/`, `private-network/`, and `functions/` (both `*.parameters.json` and `*.consumption.parameters.json` for the chosen `-Environment`).

```powershell
cd $SCRIPTS

.\hydrate-phase2-parameters.ps1 `
  -Environment $ENVIRONMENT `
  -SubscriptionDeploymentName $DEPLOYMENT_NAME_MAIN
```

**Git:** Do **not** commit hydrated JSON that contains deployment-specific names, IDs, or storage account names to a shared branch if your policy treats those as environment metadata—keep them local or restore placeholders before commit.

Some values (for example Service Bus namespace name consumed inside ADF parameters) may stay empty until Phase 2 creates those resources; **pass 2** (section 7) refreshes them.

## 4) Load deployment outputs into variables

```powershell
cd $SCRIPTS
. .\set-vars-from-main-deployment.ps1 -DeploymentName $DEPLOYMENT_NAME_MAIN -RequireCoreValues -ResolveDataRgResources

$BLOB_STORAGE_ACCOUNT = $MainBlobStorageAccountName
$DATALAKE_STORAGE_ACCOUNT = $MainDataLakeStorageAccountName
```

What gets populated:

| Variable | Source |
|----------|--------|
| `$KEYVAULT_NAME` | `main.bicep` output (`MainKeyVaultName`) |
| `$SERVICEBUS_NAMESPACE`, `$ADF_NAME`, `$ADF_RG`, `$FUNCTION_APP_NAMES` | Azure queries against `$DATA_RG` when you pass **`-ResolveDataRgResources`** |

Until Phase 2 is deployed, Service Bus, ADF, and Functions resolves may be **empty**. After **sections 6–7** (Phase 2 deploy + hydrate pass 2), run the same `set-vars-from-main-deployment.ps1` line again (with `-ResolveDataRgResources`) so those names fill in.

`set-vars-from-main-deployment.ps1` also sets **`$ML_RG`** (Azure ML workspace resource group). Use it for ML verification commands in the next section.

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

## 5) Verify Azure Machine Learning workspace (recommended)

Complete **section 4** first so **`$ML_RG`** and **`$MainMlWorkspaceName`** are loaded.

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

## 6) Deploy Phase 2 resources (`phase2-data-ingestion`)

Prerequisite: **section 3** (hydrate pass 1) so the Phase 2 parameter files you will pass below (for example `dev.parameters.json`) match your subscription deployment (or edit those JSON files manually).

Phase 2 deploys the integration layer (messaging, orchestration factory, hosting tier objects). Template ↔ parameter file rules for Functions are in `phase2-data-ingestion/functions/parameters/README.md`.

### Service Bus and Azure Data Factory

Examples below use **`dev.*.json`** filenames. If you deploy another track, point `--parameters` at the matching files in each folder (for example `prod.parameters.json`, `staging.parameters.json`).

```powershell
az deployment group create `
  --resource-group $DATA_RG `
  --template-file "$PHASE2\service-bus\service-bus.bicep" `
  --parameters "@$PHASE2\service-bus\parameters\dev.parameters.json"

az deployment group create `
  --resource-group $DATA_RG `
  --template-file "$PHASE2\azure-data-factory\data-factory.bicep" `
  --parameters "@$PHASE2\azure-data-factory\parameters\dev.parameters.json"
```

### Functions (choose **one** tier — parameter file must match the template)

**Consumption** — must use `dev.consumption.parameters.json` (not `dev.parameters.json` for Premium):

```powershell
az deployment group create `
  --resource-group $DATA_RG `
  --template-file "$PHASE2\functions\functions-consumption.bicep" `
  --parameters "@$PHASE2\functions\parameters\dev.consumption.parameters.json"
```

**Premium** — uses `dev.parameters.json`:

```powershell
az deployment group create `
  --resource-group $DATA_RG `
  --template-file "$PHASE2\functions\functions-premium.bicep" `
  --parameters "@$PHASE2\functions\parameters\dev.parameters.json"
```

After these deployments succeed, continue to **section 7** (hydrate pass 2).

## 7) Hydrate Phase 2 parameter files — pass **2** of **2** (after Phase 2 module deployments)

Run the **same** script again so parameters that depend on Phase 2–created resources (for example Service Bus namespace name wired into ADF parameter files) resolve from Azure:

**Script (repo-relative path):** `deployment/bicep/azure-infrastructure/scripts/hydrate-phase2-parameters.ps1`

```powershell
cd $SCRIPTS

.\hydrate-phase2-parameters.ps1 `
  -Environment $ENVIRONMENT `
  -SubscriptionDeploymentName $DEPLOYMENT_NAME_MAIN
```

**Git:** Same caution as section 3—avoid committing tenant-specific hydrated JSON if policy requires.

Then re-run **section 4** with `-ResolveDataRgResources` if you need refreshed `$SERVICEBUS_NAMESPACE` / `$ADF_NAME` session variables for Day 2.

## 8) Mandatory Day 2 updates (match environment track)

Continue in:

- `DAY2_UPDATES.md` when you followed this guide (parameters under `day2-updates/parameters/<environment>/`)
- `PRIVATE_DAY2_UPDATES.md` when you followed `PRIVATE_DEPLOYMENT_GUIDE.md`

Then run ADF completion/dependency checks:

- `../phase2-data-ingestion/azure-data-factory/ADF_COMPLETION_RUNBOOK.md`

## 9) Application packaging / releases

Function code deployment is handled per app (ZIP deploy, Core Tools publish, or CI/CD). This repository contains per-function deployment scripts under:

- `data-pipelines/functions/*/deploy.ps1`

## 10) Teardown (optional)

To remove the **subscription-level resource groups** deployed by **`main.bicep`** (and resources inside them), use **`TEARDOWN.md`**. It documents **`scripts/destroy.ps1`** and **`scripts/destroy.sh`**.

Copy **`§1`** session values into process environment variables (**`$env:ENVIRONMENT`**, **`$env:ORG_NAME`**, **`$env:PROJECT_NAME`**) before running **`destroy.ps1`**, or answer the script prompts. Details and bash **`export`** examples are in **`TEARDOWN.md`**.
