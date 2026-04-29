# Production greenfield deployment — full command reference (private path)

**Purpose:** Step-by-step **PowerShell** and **Azure CLI** commands to deploy:

1. **Subscription template** `bicep-templates/main.bicep` (VNet, data services, Key Vault, monitoring, Bastion + jump VM, **no** AKS/AML in prod v1 by default)  
2. **Phase 2** modules: Service Bus → Data Factory → Private Endpoints → Premium Functions (five apps)

**You do not need to learn Bicep syntax to deploy.** Azure CLI compiles `.bicep` files automatically when you run `az deployment ... --template-file something.bicep`.

**Last updated:** April 2026  
**Region used in examples:** `eastus2`  
**Related plan:** `STAGED_PROD_GREENFIELD_PRIVATE_DEPLOYMENT_PLAN.md`

---

## Table of contents

1. [How this ties to Bicep (read once)](#1-how-this-ties-to-bicep-read-once)  
2. [Prerequisites and login](#2-prerequisites-and-login)  
3. [Set your session variables (copy/paste block)](#3-set-your-session-variables-copypaste-block)  
4. [Part A — Subscription deployment (`main.bicep`)](#4-part-a--subscription-deployment-mainbicep)  
5. [Part B — Read outputs and fill `REPLACE_*` in Phase 2 parameter files](#5-part-b--read-outputs-and-fill-replace_-in-phase-2-parameter-files)  
6. [Part C — Optional: validate Bicep compiles locally](#6-part-c--optional-validate-bicep-compiles-locally)  
7. [Part D — Phase 2: what-if, then deploy (script or each module)](#7-part-d--phase-2-what-if-then-deploy-script-or-each-module)  
8. [Part E — After deployment](#8-part-e--after-deployment)  
9. [Naming alignment (`main` vs Phase 2)](#9-naming-alignment-main-vs-phase-2)  
10. [Troubleshooting commands](#10-troubleshooting-commands)  
11. [Appendix A — Example `main.prod.parameters.json`](#appendix-a--example-mainprodparametersjson)  

---

## 1. How this ties to Bicep (read once)

| Concept | What you actually run |
|--------|------------------------|
| **Deploy infrastructure** | `az deployment sub create` (subscription level) or `az deployment group create` (resource group level) |
| **Preview changes** | `az deployment sub what-if` or `az deployment group what-if` |
| **Compile check only** (optional) | `az bicep build --file path\to\file.bicep` |
| **Parameters** | JSON files (`*.parameters.json`) passed as `--parameters @path\to\file.json` |
| **Override one value** | Add another `--parameters name=value` — later entries **override** earlier ones (same parameter name wins). Use this for **email** and secrets so admins only edit **PowerShell variables**, not JSON. |

There is **no separate “bicep deploy” command** — **`az deployment`** does the deployment and uses the Bicep file as the template.

---

## 2. Prerequisites and login

Run in **Windows PowerShell** or **PowerShell 7+**.

### 2.1 Install / verify Azure CLI

```powershell
az --version
```

Need **Azure CLI 2.50+** roughly. Install: https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-windows

### 2.2 Bicep (bundled with Azure CLI)

```powershell
az bicep version

# If missing or very old:
az bicep install
az bicep upgrade
```

### 2.3 Sign in and select subscription

```powershell
az login

# If you have more than one subscription:
az account list --output table

az account set --subscription "YOUR_SUBSCRIPTION_ID_OR_NAME"

az account show --output table
```

You need permission to deploy at **subscription scope** for Part A (e.g. **Owner**, or a role that allows deploying resource groups at subscription level).

---

## 3. Set your session variables (copy/paste block)

**Adjust paths** if your repo is not under `Desktop\blache`.

```powershell
# ============================================================
# WORKSPACE ROOT — change if your clone lives elsewhere
# ============================================================
$WORKSPACE = "C:\Users\olanr\Desktop\blache"

# ============================================================
# PROD SETTINGS
# ============================================================
$LOCATION = "eastus2"
$ENVIRONMENT = "prod"

# Optional: override Functions region only (leave "" to use parameter file location)
# Example when eastus2 quota is blocked: "westus2"
$FUNCTIONS_LOCATION_OVERRIDE = ""

# ------------------------------------------------------------
# REQUIRED for main.bicep — set once per session (no JSON edit)
# ------------------------------------------------------------
$ADMIN_EMAIL = "olujare.olanrewaju@gmail.com"

# Jump VM password — prompt interactively (used for Windows VM/RDP)
$JUMP_VM_ADMIN_PASSWORD = Read-Host "Enter Windows jump VM admin password" -MaskInput

# Must match Phase 2 parameter files (namingPrefix) — see Section 9
$NAMING_PREFIX = "payswitch-creditscore-prod"

# Resource group that Phase 2 script targets by default
$RG_DATA = "$NAMING_PREFIX-data-rg"

# Subscription deployment name (unique each run if you re-run)
$DEPLOYMENT_NAME_MAIN = "main-prod-$(Get-Date -Format 'yyyyMMdd-HHmmss')"

# Paths (data-pipelines track)
$BICEP_TEMPLATES = Join-Path $WORKSPACE "data-pipelines\deployment\bicep\azure-infrastructure\bicep-templates"
$MAIN_BICEP       = Join-Path $BICEP_TEMPLATES "main.bicep"
$MAIN_PARAMS_PROD = Join-Path $BICEP_TEMPLATES "main.prod.parameters.json"

$SCRIPTS          = Join-Path $WORKSPACE "data-pipelines\deployment\bicep\azure-infrastructure\scripts"
$PHASE2           = Join-Path $WORKSPACE "data-pipelines\deployment\bicep\phase2-data-ingestion"

# Verify files exist (if False: run the whole variable block above — $MAIN_PARAMS_PROD is empty if $WORKSPACE missing)
Test-Path $MAIN_BICEP
Test-Path $MAIN_PARAMS_PROD

# main.prod.parameters.json uses empty adminEmail / jumpVmAdminPassword — set
# $ADMIN_EMAIL and $JUMP_VM_ADMIN_PASSWORD above; Part A passes them with --parameters (overrides file).

# Optional after Part A succeeds: load real values from deployment outputs (recommended on every rerun)
#   cd $SCRIPTS
#   . .\set-vars-from-main-deployment.ps1 -DeploymentName $DEPLOYMENT_NAME_MAIN
#   # Uses standardized aliases: $DATA_RG, $SECURITY_RG, $NETWORK_RG, $VNET_NAME, ...
```

---

## 4. Part A — Subscription deployment (`main.bicep`)

Template file:

`data-pipelines\deployment\bicep\azure-infrastructure\bicep-templates\main.bicep`

Parameters file (you create):

`data-pipelines\deployment\bicep\azure-infrastructure\bicep-templates\main.prod.parameters.json`

See **Appendix A** for a complete example including `jumpVmAdminPassword`.

### 4.1 Preview changes (recommended)

Subscription-level deployments **require** `--location` (metadata region for the deployment itself — use `eastus2`).

```powershell
cd $BICEP_TEMPLATES

az deployment sub what-if `
  --location $LOCATION `
  --template-file main.bicep `
  --parameters "@main.prod.parameters.json" `
  --parameters adminEmail="$ADMIN_EMAIL" `
  --parameters jumpVmAdminPassword="$JUMP_VM_ADMIN_PASSWORD"
```

`--parameters` can be repeated: **values on the command line override** the same keys in the JSON file. Set **`$ADMIN_EMAIL`** and **`$JUMP_VM_ADMIN_PASSWORD`** in the variable block (Section 3) so you do not edit the JSON for every deploy.

Review the output. Fix parameter errors before applying.

### 4.2 Deploy

```powershell
cd $BICEP_TEMPLATES

az deployment sub create `
  --name $DEPLOYMENT_NAME_MAIN `
  --location $LOCATION `
  --template-file main.bicep `
  --parameters "@main.prod.parameters.json" `
  --parameters adminEmail="$ADMIN_EMAIL" `
  --parameters jumpVmAdminPassword="$JUMP_VM_ADMIN_PASSWORD"
```

Wait until the command finishes with **Succeeded**.

### 4.3 Show deployment result and outputs

```powershell
az deployment sub show `
  --name $DEPLOYMENT_NAME_MAIN `
  --query properties.provisioningState -o tsv

az deployment sub show `
  --name $DEPLOYMENT_NAME_MAIN `
  --query properties.outputs -o json
```

Save the JSON — useful keys for Phase 2 include **`blobStorageAccountName`** (or **`storageAccountName`**), **`dataLakeStorageAccountName`**, **`postgresServerFqdn`**, **`keyVaultName`**, **`vnetId`**, **`namingPrefix`**, and **`resourceGroupNames`**.

Immediately capture output values into standardized variables (warn-only checks):

```powershell
cd $SCRIPTS
. .\set-vars-from-main-deployment.ps1 -DeploymentName $DEPLOYMENT_NAME_MAIN

# Standardized aliases used throughout this guide:
# $DATA_RG, $SECURITY_RG, $NETWORK_RG, $VNET_ID, $VNET_NAME,
# $FUNCTIONS_SUBNET_ID, $PRIVATE_ENDPOINTS_SUBNET_ID

$required = @(
  "DATA_RG","SECURITY_RG","NETWORK_RG","VNET_NAME",
  "FUNCTIONS_SUBNET_ID","PRIVATE_ENDPOINTS_SUBNET_ID",
  "MainBlobStorageAccountName","MainDataLakeStorageAccountName",
  "MainKeyVaultName","MainPostgresServerName","MainRedisName"
)

$required | ForEach-Object {
  $val = (Get-Variable -Name $_ -Scope Global -ErrorAction SilentlyContinue).Value
  if ([string]::IsNullOrWhiteSpace([string]$val)) {
    Write-Warning "Variable $_ is empty. Continue, but fix before dependent commands."
  } else {
    "{0} = {1}" -f $_, $val
  }
}

# Keep Phase 2 target RG aligned to outputs
$RG_DATA = $DATA_RG
```

---

## 5. Part B — Storage types, variables, and auto-filled Phase 2 parameters

### 5.1 Two storage accounts from `main.bicep` (already created)

The data module **`data\data-services.bicep`** provisions **two** accounts in the **data** resource group:

| ARM output | Account | Purpose |
|------------|---------|---------|
| **`blobStorageAccountName`** (alias of **`storageAccountName`**) | Storage (general-purpose **v2**), **no** hierarchical namespace | Backend-oriented blob usage: **`models`**, **`artifacts`**, **`data`** containers |
| **`dataLakeStorageAccountName`** | Same API kind, **`isHnsEnabled: true`** | **Azure Data Lake Storage Gen2**: **`raw`**, **`processed`**, **`curated`** “filesystems” for data engineering / ML |

Both are **StorageV2** in Azure; the difference is **hierarchical namespace** (ADLS Gen2) vs plain blob hierarchy.

### 5.2 Load deployment outputs into PowerShell variables (warn-only)

After Part A succeeds, **`$DEPLOYMENT_NAME_MAIN`** must match `--name` from `az deployment sub create`.

```powershell
cd $SCRIPTS

# Dot-source deployment outputs
. .\set-vars-from-main-deployment.ps1 `
  -DeploymentName $DEPLOYMENT_NAME_MAIN

# Script exports both Main* globals and standardized aliases used in this guide:
#   $DATA_RG, $SECURITY_RG, $NETWORK_RG, $VNET_ID, $VNET_NAME,
#   $FUNCTIONS_SUBNET_ID, $PRIVATE_ENDPOINTS_SUBNET_ID

# Print and verify in one shot (warn and continue if blank)
$required = @(
  "DATA_RG","SECURITY_RG","NETWORK_RG","VNET_NAME",
  "FUNCTIONS_SUBNET_ID","PRIVATE_ENDPOINTS_SUBNET_ID",
  "MainBlobStorageAccountName","MainDataLakeStorageAccountName",
  "MainKeyVaultName","MainPostgresServerName","MainRedisName"
)
$required | ForEach-Object {
  $val = (Get-Variable -Name $_ -Scope Global -ErrorAction SilentlyContinue).Value
  if ([string]::IsNullOrWhiteSpace([string]$val)) {
    Write-Warning "Variable $_ is empty. Continue, but fix before dependent commands."
  } else {
    "{0} = {1}" -f $_, $val
  }
}

# Standardized target resource group variable
$RG_DATA = $DATA_RG
```

### 5.3 Auto-fill Phase 2 `prod.parameters.json` files from `main` outputs

Script: **`scripts\hydrate-phase2-parameters.ps1`**

**Recommended:** pass the subscription deployment name so naming and resource names come from **`main`** outputs (works with **`payswitch-creditscore-prod`** or **`blache-cdtscr-prod`** without hand-editing JSON).

```powershell
cd $SCRIPTS

.\hydrate-phase2-parameters.ps1 `
  -Environment prod `
  -SubscriptionDeploymentName $DEPLOYMENT_NAME_MAIN
```

If your **`main`** subscription deployment was created **before** those outputs existed in the template (**`dataLakeStorageAccountName`**, **`postgresServerFqdn`**, **`namingPrefix`**), ARM will not return them — the script **fills gaps by querying Azure** using the **`resourceGroupNames`** from that deployment (ADLS account = storage account whose name contains **`dl`** in the data RG; Postgres FQDN from server name; **`namingPrefix`** inferred from **`…-data-rg`** → **`…`**). Redeploying **`main`** later is optional.

This updates:

| Path |
|------|
| `phase2-data-ingestion\service-bus\parameters\prod.parameters.json` |
| `phase2-data-ingestion\azure-data-factory\parameters\prod.parameters.json` |
| `phase2-data-ingestion\private-network\parameters\prod.parameters.json` |
| `phase2-data-ingestion\functions\parameters\prod.parameters.json` |

Mapped values include **`namingPrefix`**, blob storage (**`sourceBlobStorageAccountName`** / **`storageAccountName`** in PE), ADLS (**`dataLakeStorageAccountName`**), **`keyVaultName`**, **`postgresServerName`**, **`metadataPostgresServerFqdn`**, **`vnetId`**, subnet IDs (**`functions-subnet`**, **`private-endpoints-subnet`**), and resource group fields in the private-network parameters.

**ADF:** Parameters use **`deploymentEnvironment`** (`dev` / `staging` / **`prod`**), not **`environment`** (that name is used on the Service Bus template).

**Service Bus:** Deployed in **Phase 2**, not Part A. Hydrate leaves **`REPLACE_*` / placeholders** for **`serviceBusNamespaceName`** until a namespace exists in the data RG; run **`hydrate-phase2-parameters.ps1` again** after the Service Bus deployment (or rely on **`deploy-phase2-private.ps1`**, which passes the namespace on the CLI for ADF and private endpoints).

**Cosmos DB:** Not deployed by **`main.bicep`**. **`private-endpoints.bicep`** skips Cosmos private DNS/endpoint when **`cosmosAccountName`** is empty; hydrate clears **`REPLACE_PROD_COSMOS`** to `""` in that case.

### 5.4 Phase 2 deploy: point at the correct data resource group

If **`main`** used **`payswitch`** / **`creditscore`** naming, your data RG is like **`payswitch-creditscore-prod-data-rg`** — use standardized alias **`$DATA_RG`** after Section 5.2.

```powershell
.\deploy-phase2-private.ps1 -Environment prod -DataResourceGroup $DATA_RG

# Or hard-coded:
.\deploy-phase2-private.ps1 -Environment prod -DataResourceGroup "payswitch-creditscore-prod-data-rg"
```

### 5.5 Azure CLI verification block (DNS + approval + public access)
```powershell
# ---------- Required inputs ----------
#$DATA_RG = "<data-rg>"
#$SECURITY_RG = "<security-rg>"
#$NETWORK_RG = "<network-rg>"
#$VNET_NAME = "<vnet-name>"

# DNS zones may not live in $NETWORK_RG (in this repo they are typically created in $DATA_RG).
# Auto-discover DNS RG from one known zone and fall back to $DATA_RG.
$DNS_RG = az network private-dns zone list --query "[?name=='privatelink.servicebus.windows.net'] | [0].resourceGroup" -o tsv
if ([string]::IsNullOrWhiteSpace($DNS_RG)) { $DNS_RG = $DATA_RG }
"DNS_RG = $DNS_RG"

# ---------- 1) Private endpoints + state ----------
Write-Host "`n=== Private Endpoints (state) ===" -ForegroundColor Cyan
az network private-endpoint list -g $DATA_RG `
  --query "[].{name:name, state:provisioningState, subnet:subnet.id}" -o table

# ---------- 2) Private endpoint connections (approval) ----------
Write-Host "`n=== PE Connection Approval (Service Bus) ===" -ForegroundColor Cyan
$SB_ID = az servicebus namespace list -g $DATA_RG --query "[0].id" -o tsv
if ($SB_ID) { az network private-endpoint-connection list --id $SB_ID -o table } else { Write-Warning "No Service Bus namespace found." }

Write-Host "`n=== PE Connection Approval (Storage Accounts) ===" -ForegroundColor Cyan
$ST_IDS = az storage account list -g $DATA_RG --query "[].id" -o tsv
if ($ST_IDS) {
  foreach ($id in $ST_IDS -split "`n") {
    if ($id) { az network private-endpoint-connection list --id $id -o table }
  }
} else { Write-Warning "No Storage accounts found." }

Write-Host "`n=== PE Connection Approval (Postgres Flexible) ===" -ForegroundColor Cyan
$PG_IDS = az postgres flexible-server list -g $DATA_RG --query "[].id" -o tsv
if ($PG_IDS) {
  foreach ($id in $PG_IDS -split "`n") {
    if ($id) { az network private-endpoint-connection list --id $id -o table }
  }
} else { Write-Warning "No Postgres flexible servers found." }

Write-Host "`n=== PE Connection Approval (Redis) ===" -ForegroundColor Cyan
$REDIS_IDS = az redis list -g $DATA_RG --query "[].id" -o tsv
if ($REDIS_IDS) {
  foreach ($id in $REDIS_IDS -split "`n") {
    if ($id) { az network private-endpoint-connection list --id $id -o table }
  }
} else { Write-Warning "No Redis caches found." }

Write-Host "`n=== PE Connection Approval (Key Vault) ===" -ForegroundColor Cyan
$KV_IDS = az keyvault list -g $SECURITY_RG --query "[].id" -o tsv
if ($KV_IDS) {
  foreach ($id in $KV_IDS -split "`n") {
    if ($id) { az network private-endpoint-connection list --id $id -o table }
  }
} else { Write-Warning "No Key Vaults found." }

# ---------- 3) Private DNS zones + VNet links ----------
Write-Host "`n=== Private DNS Zones (DNS RG) ===" -ForegroundColor Cyan
az network private-dns zone list -g $DNS_RG --query "[].name" -o table

$zones = @(
  "privatelink.blob.core.windows.net",
  "privatelink.dfs.core.windows.net",
  "privatelink.vaultcore.azure.net",
  "privatelink.postgres.database.azure.com",
  "privatelink.servicebus.windows.net",
  "privatelink.redis.cache.windows.net"
)

foreach ($z in $zones) {
  Write-Host "`n--- Zone: $z ---" -ForegroundColor Yellow
  az network private-dns link vnet list -g $DNS_RG -z $z `
    --query "[].{link:name, vnet:virtualNetwork.id, reg:registrationEnabled}" -o table
  az network private-dns record-set a list -g $DNS_RG -z $z `
    --query "[].{record:name, ttl:TTL, ip:arecords[0].ipv4Address}" -o table
}

# ---------- 4) Public access hardening ----------
Write-Host "`n=== Public Access Checks ===" -ForegroundColor Cyan

Write-Host "`nService Bus:" -ForegroundColor Yellow
az servicebus namespace list -g $DATA_RG `
  --query "[].{name:name, publicAccess:publicNetworkAccess, sku:sku.tier}" -o table

Write-Host "`nStorage:" -ForegroundColor Yellow
az storage account list -g $DATA_RG `
  --query "[].{name:name, publicAccess:publicNetworkAccess, defaultAction:networkRuleSet.defaultAction}" -o table

Write-Host "`nKey Vault:" -ForegroundColor Yellow
az keyvault list -g $SECURITY_RG `
  --query "[].{name:name, publicAccess:properties.publicNetworkAccess, defaultAction:properties.networkAcls.defaultAction}" -o table

Write-Host "`nPostgres Flexible:" -ForegroundColor Yellow
az postgres flexible-server list -g $DATA_RG `
  --query "[].{name:name, publicAccess:network.publicNetworkAccessState}" -o table

Write-Host "`nRedis:" -ForegroundColor Yellow
az redis list -g $DATA_RG `
  --query "[].{name:name, publicAccess:publicNetworkAccess}" -o table
```

### 5.6 Manual subnet lookup (only if needed)

Replace resource group and VNet name with yours (from outputs / Portal).

```powershell
# Requires Section 5.2 block first (sets $NETWORK_RG and $VNET_NAME)
az network vnet list --resource-group $NETWORK_RG --query "[].{Name:name, Id:id}" -o table

az network vnet subnet show `
  --resource-group $NETWORK_RG `
  --vnet-name $VNET_NAME `
  --name "private-endpoints-subnet" `
  --query id -o tsv
```

**Blob trigger / cross-subscription ingestion:** If source blobs live elsewhere, also set ADF parameters **`sourceStorageSubscriptionId`** and **`sourceStorageResourceGroupName`**.

### 5.7 Cut public access (run after private checks pass)

Run this only after Section 5.5 confirms:
- private endpoints are `Succeeded`
- private endpoint connections are approved
- private DNS zones/links/records are present and correct

```powershell
# Required vars should already be set from Section 5.2
#   $DATA_RG, $SECURITY_RG

Write-Host "`n=== Disable Service Bus public access ===" -ForegroundColor Cyan
$sbNames = az servicebus namespace list -g $DATA_RG --query "[].name" -o tsv
foreach ($n in ($sbNames -split "`n")) {
  if (-not [string]::IsNullOrWhiteSpace($n)) {
    az servicebus namespace update -g $DATA_RG -n $n --public-network-access Disabled
  }
}

Write-Host "`n=== Disable Storage public access + enforce deny by default ===" -ForegroundColor Cyan
$stNames = az storage account list -g $DATA_RG --query "[].name" -o tsv
foreach ($n in ($stNames -split "`n")) {
  if (-not [string]::IsNullOrWhiteSpace($n)) {
    az storage account update -g $DATA_RG -n $n --public-network-access Disabled --default-action Deny
  }
}

Write-Host "`n=== Disable Key Vault public access ===" -ForegroundColor Cyan
$kvNames = az keyvault list -g $SECURITY_RG --query "[].name" -o tsv
foreach ($n in ($kvNames -split "`n")) {
  if (-not [string]::IsNullOrWhiteSpace($n)) {
    az keyvault update -g $SECURITY_RG -n $n --public-network-access Disabled --default-action Deny
  }
}

Write-Host "`n=== Disable Postgres Flexible public access ===" -ForegroundColor Cyan
$pgNames = az postgres flexible-server list -g $DATA_RG --query "[].name" -o tsv
foreach ($n in ($pgNames -split "`n")) {
  if (-not [string]::IsNullOrWhiteSpace($n)) {
    az postgres flexible-server update -g $DATA_RG -n $n --public-access none
  }
}

Write-Host "`n=== Disable Redis public access ===" -ForegroundColor Cyan
$redisNames = az redis list -g $DATA_RG --query "[].name" -o tsv
foreach ($n in ($redisNames -split "`n")) {
  if (-not [string]::IsNullOrWhiteSpace($n)) {
    az redis update -g $DATA_RG -n $n --set publicNetworkAccess=Disabled
  }
}

Write-Host "`n=== Optional: disable Data Factory public access (only if Managed VNet private path is fully validated) ===" -ForegroundColor Yellow
$adfNames = az datafactory list -g $DATA_RG --query "[].name" -o tsv
foreach ($n in ($adfNames -split "`n")) {
  if (-not [string]::IsNullOrWhiteSpace($n)) {
    # Uncomment after validation:
    # az datafactory update -g $DATA_RG -n $n --public-network-access Disabled
  }
}
```

Re-run Section 5.5 to confirm all public access fields now show `Disabled` / `Deny` as expected.

---

## 6. Part C — Optional: validate Bicep compiles locally

Optional sanity check — does **not** deploy anything.

```powershell
cd $BICEP_TEMPLATES
az bicep build --file main.bicep
```

Phase 2 (examples):

```powershell
cd (Join-Path $PHASE2 "service-bus")
az bicep build --file service-bus.bicep

cd (Join-Path $PHASE2 "azure-data-factory")
az bicep build --file data-factory.bicep

cd (Join-Path $PHASE2 "private-network")
az bicep build --file private-endpoints.bicep

cd (Join-Path $PHASE2 "functions")
az bicep build --file functions-premium.bicep
```

### 6.1 Bind ADF to prod output variables (recommended)

Use this after Service Bus + ADF deploy (and whenever you rerun). It applies the canonical
`pipeline-training-data-ingestion.json` with production variable values so dev names do not persist.

```powershell
# Prereq variables from earlier sections:
#   $RG_DATA, $SCRIPTS, $WORKSPACE, $SERVICEBUS_NAME,
#   $MainBlobStorageAccountName, $MainDataLakeStorageAccountName,
#   $MainKeyVaultName, $MainPostgresServerFqdn

$ADF_FACTORY_NAME = az datafactory list --resource-group $RG_DATA --query "[0].name" -o tsv
if ([string]::IsNullOrWhiteSpace($ADF_FACTORY_NAME)) { Write-Warning "Variable ADF_FACTORY_NAME is empty. Continue, but fix before dependent commands." } else { "ADF_FACTORY_NAME = $ADF_FACTORY_NAME" }

# Re-assert prod parameter files from outputs before pipeline import
cd $SCRIPTS
.\hydrate-phase2-parameters.ps1 -Environment prod -SubscriptionDeploymentName $DEPLOYMENT_NAME_MAIN

# Import canonical pipeline template (contains pipeline + required datasets)
$ADF_PIPELINE_TEMPLATE = Join-Path $WORKSPACE "data-pipelines\deployment\adf\pipeline-training-data-ingestion\pipeline-training-data-ingestion.json"
az deployment group create `
  --resource-group $RG_DATA `
  --template-file $ADF_PIPELINE_TEMPLATE `
  --parameters "factoryName=$ADF_FACTORY_NAME" `
  --parameters "data_ingested_ls=data_ingested_ls" `
  --parameters "metadata_postgres_ls=metadata_postgres_ls" `
  --parameters "data_awaits_ingestion_ls=data_awaits_ingestion_ls"
```

Quick checks that prod names are bound:

```powershell
az datafactory linked-service show -g $RG_DATA --factory-name $ADF_FACTORY_NAME -n key_vault_ls --query "properties.typeProperties.baseUrl" -o tsv
az datafactory linked-service show -g $RG_DATA --factory-name $ADF_FACTORY_NAME -n data_ingested_ls --query "properties.typeProperties.url" -o tsv
az datafactory linked-service show -g $RG_DATA --factory-name $ADF_FACTORY_NAME -n data_awaits_ingestion_ls --query "properties.typeProperties.serviceEndpoint" -o tsv
az datafactory linked-service show -g $RG_DATA --factory-name $ADF_FACTORY_NAME -n metadata_postgres_ls --query "properties.typeProperties.server" -o tsv
```

---

## 7. Part D — Phase 2: what-if, then deploy (script or each module)

**Prerequisite:** Resource group **`$RG_DATA`** (e.g. `blache-cdtscr-prod-data-rg`) must exist. It is normally created by **`main.bicep`**. If your naming from `main` differs, set `$RG_DATA` to the **actual** data resource group name.

### Option 1 — All-in-one script (recommended)

Scripts live in:

`data-pipelines\deployment\bicep\azure-infrastructure\scripts\`

**What-if only (no changes applied):**

```powershell
cd $SCRIPTS

# Premium functions what-if:
.\whatif-phase2-private.ps1 -Environment prod -DataResourceGroup $DATA_RG -FunctionsTier premium

# Consumption functions what-if:
.\whatif-phase2-private.ps1 -Environment prod -DataResourceGroup $DATA_RG -FunctionsTier consumption

# Consumption functions what-if in alternate region (quota fallback), e.g. westus2:
.\whatif-phase2-private.ps1 -Environment prod -DataResourceGroup $DATA_RG -FunctionsTier consumption -FunctionsLocationOverride "westus2"
```

If **`$RG_DATA`** from Section 3 does not match your real data resource group (e.g. **`main`** used **`payswitch-creditscore-prod`** naming), pass it explicitly — use **`$DATA_RG`** from Section 5.2, or the literal name:

```powershell
.\whatif-phase2-private.ps1 -Environment prod -DataResourceGroup $DATA_RG
```

**Deploy (applies changes):**

```powershell
.\deploy-phase2-private.ps1 -Environment prod -DataResourceGroup $DATA_RG

# Consumption functions deploy:
.\deploy-phase2-private.ps1 -Environment prod -DataResourceGroup $DATA_RG -FunctionsTier consumption

# Consumption functions deploy in alternate region (quota fallback), e.g. westus2:
.\deploy-phase2-private.ps1 -Environment prod -DataResourceGroup $DATA_RG -FunctionsTier consumption -FunctionsLocationOverride "westus2"
```

If you do not pass **`-DataResourceGroup`**, the script resolves it from **`$DATA_RG`** (global variable) or **`DATA_RG`** (environment variable) and throws if still empty. For reliability, always pass **`-DataResourceGroup $DATA_RG`**.

### Option 2 — Run each module manually (same order as the script)

All commands use **`az deployment group create`** because these templates target **one resource group** (`$RG_DATA`).

```powershell
# Use $DATA_RG from Section 5.2 and keep $RG_DATA synced to it
cd $PHASE2
```

**Step D.1 — Service Bus**

```powershell
az deployment group create `
  --resource-group $RG_DATA `
  --template-file "$PHASE2\service-bus\service-bus.bicep" `
  --parameters "@$PHASE2\service-bus\parameters\prod.parameters.json" `
  --name "sb-prod-$(Get-Date -Format 'yyyyMMdd-HHmmss')"

# Capture output needed by downstream modules
$SERVICEBUS_NAME = az resource list --resource-group $RG_DATA --query "[?type=='Microsoft.ServiceBus/namespaces'].name | [0]" -o tsv
if ([string]::IsNullOrWhiteSpace($SERVICEBUS_NAME)) { Write-Warning "SERVICEBUS_NAME is empty; rerun discovery before ADF/PE deploy." }
"SERVICEBUS_NAME = $SERVICEBUS_NAME"
```

**Step D.2 — Data Factory**

```powershell
az deployment group create `
  --resource-group $RG_DATA `
  --template-file "$PHASE2\azure-data-factory\data-factory.bicep" `
  --parameters "@$PHASE2\azure-data-factory\parameters\prod.parameters.json" `
  --name "adf-prod-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
```

**Step D.3 — Private endpoints**

```powershell
az deployment group create `
  --resource-group $RG_DATA `
  --template-file "$PHASE2\private-network\private-endpoints.bicep" `
  --parameters "@$PHASE2\private-network\parameters\prod.parameters.json" `
  --name "pe-prod-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
```

**Step D.4 — Premium Functions (five apps)**

```powershell
az deployment group create `
  --resource-group $RG_DATA `
  --template-file "$PHASE2\functions\functions-premium.bicep" `
  --parameters "@$PHASE2\functions\parameters\prod.parameters.json" `
  --name "func-prod-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
```

**Fallback Step D.4b — Consumption Functions (when Premium quota is unavailable)**

Use this only while Premium quota is blocked. Consumption does not provide the same private-only network posture as Premium.
Cross-region deployment (for example, Functions in `westus2` while data resources are in `eastus2`) can work for this setup, but with higher latency and egress considerations.

```powershell
az deployment group create `
  --resource-group $RG_DATA `
  --template-file "$PHASE2\functions\functions-consumption.bicep" `
  --parameters "@$PHASE2\functions\parameters\prod.consumption.parameters.json" `
  --name "func-consumption-prod-$(Get-Date -Format 'yyyyMMdd-HHmmss')"

# Optional region override if quota blocks eastus2
az deployment group create `
  --resource-group $RG_DATA `
  --template-file "$PHASE2\functions\functions-consumption.bicep" `
  --parameters "@$PHASE2\functions\parameters\prod.consumption.parameters.json" `
  --parameters "location=westus2" `
  --name "func-consumption-prod-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
```

Optional: lock down caller ranges by overriding CIDRs at deploy time:

```powershell
az deployment group create `
  --resource-group $RG_DATA `
  --template-file "$PHASE2\functions\functions-consumption.bicep" `
  --parameters "@$PHASE2\functions\parameters\prod.consumption.parameters.json" `
  --parameters allowedCallerCidrs="['<your-cidr-1>','<your-cidr-2>']" `
  --name "func-consumption-prod-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
```

### Per-step what-if (manual)

Replace `create` with `what-if`:

```powershell
az deployment group what-if `
  --resource-group $RG_DATA `
  --template-file "$PHASE2\service-bus\service-bus.bicep" `
  --parameters "@$PHASE2\service-bus\parameters\prod.parameters.json"
```

Repeat for ADF, private-endpoints, functions.

---

## 8. Part E — After deployment

These are **not** fully automated by the above Bicep alone:

1. **Publish Function code** to each Function App (`func azure functionapp publish`, ZIP deploy, or CI/CD).  
2. **ADF:** Clear or replace **dev defaults** on pipeline parameters (checksum URL/key, etc.) in Azure Portal or via automation.  
3. **RBAC:** Grant each Function App **managed identity** access to Key Vault, Storage, Service Bus as required by your apps.  
4. **Service Bus:** Confirm topics/subscriptions exist for your architecture (some may be created only by extended Bicep or manually).

---

## 9. Naming alignment (`main` vs Phase 2)

`main.bicep` builds `namingPrefix` from **`orgName`** + **`projectName`** + **`environment`** (defaults: `payswitch`, `creditscore`, … → `payswitch-creditscore-prod-*`).

Phase 2 sample parameter files use **`blache-cdtscr-prod`** as **`namingPrefix`**.

**You must align one side:**

- Either set **`orgName`** / **`projectName`** / **`environment`** in `main.prod.parameters.json` so created RGs match **`blache-cdtscr-prod-*`**, **or**  
- Keep `main` as-is and set **`namingPrefix`** (and **`dataResourceGroupName`** / RG names in PE params) to match whatever **`main`** actually created.

The **data** resource group name used by Phase 2 (`-DataResourceGroup` / `$RG_DATA`) **must exist** and must be the RG where Service Bus, ADF, and related resources deploy.

---

## 10. Troubleshooting commands

```powershell
# Recent deployments at subscription level
az deployment sub list --query "[].{Name:name, State:properties.provisioningState, Timestamp:properties.timestamp}" -o table

# Recent deployments in a resource group
az deployment group list --resource-group $RG_DATA -o table

# Show error from a failed deployment
az deployment operation sub list --name $DEPLOYMENT_NAME_MAIN --query "[?properties.provisioningState=='Failed']" -o table

az deployment operation group list --resource-group $RG_DATA --name "<deployment-name>"
```

---

## Appendix A — `main.prod.parameters.json` (repo copy)

**Path:** `data-pipelines\deployment\bicep\azure-infrastructure\bicep-templates\main.prod.parameters.json`

The committed file keeps **`adminEmail`** and **`jumpVmAdminPassword`** as **empty strings**. You supply real values from **PowerShell variables** (`$ADMIN_EMAIL`, `$JUMP_VM_ADMIN_PASSWORD`) using extra `--parameters` arguments (Section 4), so operators **only change the variable block** in Section 3 — not the JSON.

**Alternative:** Put the email or key directly in the JSON `"value"` fields instead of using CLI overrides (not recommended if the repo is committed to git).

If **`jumpVmAdminPassword`** stays empty **and** you do not override it with a non-empty CLI value, the Windows jump VM deployment will fail — pass it interactively from Section 3.

Example override pattern (repeat of Section 4):

```powershell
az deployment sub create `
  ... `
  --parameters "@main.prod.parameters.json" `
  --parameters adminEmail="$ADMIN_EMAIL" `
  --parameters jumpVmAdminPassword="$JUMP_VM_ADMIN_PASSWORD"
```

---

## Cross-references

| Document / script | Purpose |
|-------------------|---------|
| `STAGED_PROD_GREENFIELD_PRIVATE_DEPLOYMENT_PLAN.md` | Wave model, Service Bus topic map, architecture notes |
| `DEPLOYMENT_GUIDE_INDIVIDUAL_MODULES.md` | Module-by-module guide (alternate paths / older `credit-scoring` references may appear — prefer **paths in this file** for `data-pipelines`) |
| `scripts\deploy-phase2-private.ps1` | Ordered Phase 2 deploy |
| `scripts\whatif-phase2-private.ps1` | Ordered Phase 2 what-if |
