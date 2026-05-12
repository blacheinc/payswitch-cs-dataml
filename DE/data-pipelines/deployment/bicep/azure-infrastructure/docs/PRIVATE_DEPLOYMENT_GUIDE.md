# Private Deployment Guide

This guide is the **canonical private connectivity deployment path**:

- Subscription deployment: `azure-infrastructure/bicep-templates/main.private.bicep` using **`main.$ENVIRONMENT.parameters.json`** under `bicep-templates/`
- Phase 2 integration deployment (private module stack): `phase2-data-ingestion/*` using `<environment>.parameters.json` under each module’s `parameters/` folder
- Mandatory Day 2 updates: see `PRIVATE_DAY2_UPDATES.md`

## Before You Run Anything (exact files to fill)

Fill these files in order before running commands:

1. **Main subscription deployment (required)**
   - File: `bicep-templates/main.parameters.json` or `bicep-templates/main.prod.parameters.json`
   - Fill at minimum: `orgName`, `projectName`, `environment`, `primaryLocation`, `tags`, `adminEmail`, and jump box values if enabled.

2. **Phase 2 private deployment (required)**
   - Files: `phase2-data-ingestion/**/parameters/*.json` for the same environment
   - Ensure private settings are aligned for Service Bus, ADF, Functions, and private endpoints.

3. **Private Day 2 updates (required for Day 2 private runbook)**
   - Files: `day2-updates/parameters/<environment>/*.json`
   - Fill module-specific Day 2 values for the selected environment folder.

Session variables help, but they are not a replacement for parameter files:
- `Sync-EnvFromMainParameters.ps1` loads naming values from your `main.*.parameters.json` into `$env:*`.
- `set-vars-from-main-deployment.ps1` loads live deployment outputs (resource groups, storage names, etc.) after `main.bicep` succeeds.

## Edit the parameter files

**Change deployment settings by editing the JSON parameter files.** For `main.private.bicep`, edit **`main.parameters.json`** / **`main.prod.parameters.json`** (whichever you deploy with) before **`az deployment sub create`**—especially **`primaryLocation`**, **`environment`**, **`deployJumpBox`**, **`jumpVmAdminPassword`**, and **`adminEmail`**. For Phase 2, edit each module’s **`phase2-data-ingestion/**/parameters/*.json`** files (`privateNetworkMode`, naming, hydrated values). Pass **`--parameters "@…"`** pointing at the **`main.*.parameters.json`** file you edited.

## Canonical companion documents

- `DEPLOYMENT_GUIDE.md` — default subscription deployment + Phase 2 when **not** using this private stack
- `DAY2_UPDATES.md` — Day 2 updates with parameters under `day2-updates/parameters/<environment>/`
- `PRIVATE_DAY2_UPDATES.md` — Day 2 updates for the private deployment guide with parameters under `day2-updates/parameters/<environment>/`
- `HOW_DEPLOYMENT_FITS_TOGETHER.md` — how folders, templates, scripts, and artifacts connect
- `TEARDOWN.md` — delete subscription resource groups created by `main.bicep` (`destroy.ps1` / `destroy.sh`)

## Prerequisites

- Azure CLI installed and authenticated (`az login`)
- Permissions to deploy at **subscription scope** for `main.bicep`
- Permissions for resource-group deployments in the target data resource group
- PowerShell on Windows

## Important defaults (`main.bicep`)

- **`deployMlWorkspace` defaults to `true`** — Azure Machine Learning workspace resources deploy without extra flags.
- **`deployAks` remains optional** — Kubernetes is not required unless explicitly enabled.

## Private networking parameters (`main.bicep` + Phase 2)

Use this checklist when moving from **default** (permissive Key Vault + data-layer networking) to **private** posture.

### 1) Subscription — `main.private.bicep`

In your `main.<environment>.parameters.json`:

| Parameter | Default / normal deployment | Private posture |
|-----------|------------------------------|-----------------|
| **`privateNetworkMode`** | N/A in this guide | Always **`true`** via `main.private.bicep` |

`main.private.bicep` calls `main.bicep` with `privateNetworkMode: true`, which then passes private posture to `security/keyvault.bicep` and `data/data-services.bicep`, and passes `vnetId` / `mlSubnetId` into the data layer so PostgreSQL can use delegated subnet + private DNS.

Effects (see Bicep for details):

- **Key Vault** — `networkAcls.defaultAction` is **Deny** (and public access off) only when **`privateNetworkMode`** is **`true`**. When **`false`**, default action is **Allow** so authenticated CLI (`az keyvault secret …`) works from your workstation subject to RBAC.
- **Storage accounts + ADLS + Functions runtime storage** — **Deny** default with VNet rules when the data module is in **production** networking mode (`privateNetworkMode` drives **`environment`** = **`production`** in `main.bicep`).
- **PostgreSQL Flexible Server** — private delegation + private DNS zone when **`privateNetworkMode`** is **`true`** and VNet/subnet IDs are supplied.
- **Redis** — public network access follows the same production networking flag.

**Jump host:** Keep **`deployJumpBox`** **`true`** (and supply **`jumpVmAdminPassword`**) when operators reach Key Vault or private endpoints via Bastion + jump VM.

Redeploy **`main.private.bicep`** at subscription scope after private-related changes.

### 2) Phase 2 — `phase2-data-ingestion`

Align **`privateNetworkMode`** in each Phase 2 parameter file you deploy (must match your intent for Service Bus, ADF, Functions):

- `service-bus/parameters/<environment>.parameters.json`
- `azure-data-factory/parameters/<environment>.parameters.json`
- `functions/parameters/<environment>.parameters.json` (and **Consumption** variants if used)

Then deploy with **`deploy-phase2-private.ps1`** / **`whatif-phase2-private.ps1`** so **`private-network/private-endpoints.bicep`** and module-level private settings stay consistent.

### 3) Operational note

Once Key Vault uses **Deny** and **public access disabled**, run hydration and secret-management commands from a **trusted network path** (jump VM, allowlisted IP, or pipeline identity)—not necessarily from an unrestricted laptop.

## 1) Session variables (copy/paste)

Adjust paths if your workspace root differs. Set **`$ENVIRONMENT`** to match your **`main.<environment>.parameters.json`** file and the Phase 2 / Day 2 parameter filenames for that track.

```powershell
$WORKSPACE = "C:\path\to\your\repo-clone"

$LOCATION = "eastus2"
$ENVIRONMENT = "<environment>"

$ADMIN_EMAIL = "your-admin-email@company.com"
$JUMP_VM_ADMIN_PASSWORD = Read-Host "Enter Windows jump VM admin password" -MaskInput

$BICEP_TEMPLATES = Join-Path $WORKSPACE "data-pipelines\deployment\bicep\azure-infrastructure\bicep-templates"
$MAIN_PARAMS = Join-Path $BICEP_TEMPLATES "main.$ENVIRONMENT.parameters.json"

$SCRIPTS  = Join-Path $WORKSPACE "data-pipelines\deployment\bicep\azure-infrastructure\scripts"
$PHASE2   = Join-Path $WORKSPACE "data-pipelines\deployment\bicep\phase2-data-ingestion"

$DEPLOYMENT_NAME_MAIN = "main-$ENVIRONMENT-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
```

## 2) Part A — Deploy `main.bicep`

### 2.1 Preview (recommended)

```powershell
cd $BICEP_TEMPLATES

az deployment sub what-if `
  --location $LOCATION `
  --template-file main.private.bicep `
  --parameters "@$MAIN_PARAMS" `
  --parameters adminEmail="$ADMIN_EMAIL" `
  --parameters jumpVmAdminPassword="$JUMP_VM_ADMIN_PASSWORD"
```

### 2.2 Apply

```powershell
az deployment sub create `
  --name $DEPLOYMENT_NAME_MAIN `
  --location $LOCATION `
  --template-file main.private.bicep `
  --parameters "@$MAIN_PARAMS" `
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

After **2.3**, **`$ML_RG`** is the ML resource group name (alias for `MainRgMl` from deployment outputs).

```powershell
az deployment sub show `
  --name $DEPLOYMENT_NAME_MAIN `
  --query properties.outputs.mlWorkspaceName.value `
  -o tsv
```

Optional resource listing:

```powershell
az resource list `
  -g $ML_RG `
  --resource-type Microsoft.MachineLearningServices/workspaces `
  -o table
```

## 3) Part B — Hydrate Phase 2 parameter files — pass **1** of **2** (after `main.bicep`)

Phase 2 parameter files under `phase2-data-ingestion/` are checked in with placeholders. Populate them **after** Part A using this script (reads `main.bicep` outputs and Azure resource names).

**Script (repo-relative path):** `deployment/bicep/azure-infrastructure/scripts/hydrate-phase2-parameters.ps1`  
Use **`$SCRIPTS`** from section 1 (`Join-Path $WORKSPACE "data-pipelines\deployment\bicep\azure-infrastructure\scripts"`).

This updates **all** Phase 2 parameter JSON the script manages (Service Bus, Data Factory, private-network, Functions Premium **and** Functions Consumption files for **`-Environment $ENVIRONMENT`**), not only Functions.

```powershell
cd $SCRIPTS

.\hydrate-phase2-parameters.ps1 `
  -Environment $ENVIRONMENT `
  -SubscriptionDeploymentName $DEPLOYMENT_NAME_MAIN
```

**Git:** Do **not** commit hydrated JSON containing tenant-specific names or IDs to a shared repository if your policy treats them as sensitive environment metadata.

Some fields stay empty until Phase 2 resources exist; run **pass 2** after Part C.

## 4) Part C — Phase 2 private stack (`phase2-data-ingestion`)

Prerequisite: **Part B (hydrate pass 1)** so Phase 2 `parameters/*.json` files match your subscription deployment.

Preferred: use the orchestration scripts (they preserve module order and naming alignment):

```powershell
cd $SCRIPTS

.\whatif-phase2-private.ps1 -Environment $ENVIRONMENT -DataResourceGroup $DATA_RG

.\deploy-phase2-private.ps1 -Environment $ENVIRONMENT -DataResourceGroup $DATA_RG
```

### Manual module order (same as orchestration)

If you must run modules individually, follow this order:

1. `service-bus/service-bus.bicep`
2. `azure-data-factory/data-factory.bicep`
3. `private-network/private-endpoints.bicep`
4. `functions/functions-premium.bicep` (or consumption equivalents)

Pass the parameter files that exist under each module’s `parameters/` folder for your track (for example **`prod.parameters.json`** and, for Consumption, **`prod.consumption.parameters.json`**). Those names are fixed on disk; they are not built from a PowerShell variable.

## 5) Hydrate Phase 2 parameter files — pass **2** of **2** (after Part C deployments)

Run the **same** hydration script again so values that depend on Phase 2 resources (for example Service Bus namespace wired into ADF parameters) refresh from Azure:

**Script (repo-relative path):** `deployment/bicep/azure-infrastructure/scripts/hydrate-phase2-parameters.ps1`

```powershell
cd $SCRIPTS

.\hydrate-phase2-parameters.ps1 `
  -Environment $ENVIRONMENT `
  -SubscriptionDeploymentName $DEPLOYMENT_NAME_MAIN
```

**Git:** Same guidance as Part B—avoid committing tenant-filled JSON when policy requires.

Optional: reload session variables from outputs (`set-vars-from-main-deployment.ps1` with `-ResolveDataRgResources`) before Day 2.

## 6) Part D — Mandatory Day 2 updates

Continue in `PRIVATE_DAY2_UPDATES.md`.

Then run ADF completion/dependency checks:

- `../phase2-data-ingestion/azure-data-factory/ADF_COMPLETION_RUNBOOK.md`

## 7) Post-deploy operational checklist (minimum)

- Confirm deployments succeeded (`Succeeded`) for subscription deployment and each Phase 2 group deployment.
- Confirm Azure ML workspace exists and compute objects exist as expected.
- Continue with Day 2 updates and functional smoke tests defined in your operational standards.
