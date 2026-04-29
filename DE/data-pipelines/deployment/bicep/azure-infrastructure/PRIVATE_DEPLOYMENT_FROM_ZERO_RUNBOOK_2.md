# Prod Private Deployment From Zero

This runbook deploys the Phase 2 data-ingestion infrastructure to a new `prod` environment using the Bicep modules in this repository, with private networking enabled.

It covers:
- Resource group creation
- Parameter hydration
- What-if validation
- Deployment
- Post-deploy private-network and security checks

## 0) Preconditions

- Azure CLI installed and authenticated (`az login`)
- PowerShell available
- Permissions to create/update network, private endpoints, DNS zones, Function Apps, Service Bus, ADF, and RBAC
- Subscription quota available for Premium Function resources

Repository root:

`c:\Users\olanr\Desktop\blache`

## 1) Set variables and select subscription

```powershell
cd c:\Users\olanr\Desktop\blache

$SUBSCRIPTION_ID = "<your-subscription-id>"
$LOCATION = "eastus2"
$ENV = "prod"

$DATA_RG = "blache-cdtscr-$ENV-data-rg"
$SECURITY_RG = "blache-cdtscr-$ENV-security-rg"
$NETWORK_RG = "blache-cdtscr-$ENV-network-rg"

az login
az account set --subscription $SUBSCRIPTION_ID
az account show --query "{name:name,id:id}" -o table

# Warn-only variable check (continue, but fix empties before dependent steps)
$required = @("SUBSCRIPTION_ID","LOCATION","ENV","DATA_RG","SECURITY_RG","NETWORK_RG")
$required | ForEach-Object {
  $val = (Get-Variable -Name $_ -ErrorAction SilentlyContinue).Value
  if ([string]::IsNullOrWhiteSpace([string]$val)) {
    Write-Warning "Variable $_ is empty. Continue, but fix before dependent commands."
  } else {
    "{0} = {1}" -f $_, $val
  }
}
```

If you deployed `main.bicep` already, prefer loading the real names from outputs (prevents empty/mismatched variables):

```powershell
cd .\data-pipelines\deployment\bicep\azure-infrastructure\scripts

$DEPLOYMENT_NAME_MAIN = "<your-main-deployment-name>"
. .\set-vars-from-main-deployment.ps1 -DeploymentName $DEPLOYMENT_NAME_MAIN -SubscriptionId $SUBSCRIPTION_ID

# These aliases are now set from outputs:
# $DATA_RG, $SECURITY_RG, $NETWORK_RG, $VNET_NAME, $FUNCTIONS_SUBNET_ID, $PRIVATE_ENDPOINTS_SUBNET_ID

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
```

## 2) Create prod resource groups (from zero)

```powershell
az group create --name $DATA_RG --location $LOCATION
az group create --name $SECURITY_RG --location $LOCATION
az group create --name $NETWORK_RG --location $LOCATION

az group list --query "[?name=='$DATA_RG' || name=='$SECURITY_RG' || name=='$NETWORK_RG'].{name:name,location:location}" -o table

# Capture + warn if any RG not found
$RG_CHECK = az group list --query "[?name=='$DATA_RG' || name=='$SECURITY_RG' || name=='$NETWORK_RG'].name" -o tsv
if ($RG_CHECK -notmatch $DATA_RG) { Write-Warning "DATA_RG not found: $DATA_RG" }
if ($RG_CHECK -notmatch $SECURITY_RG) { Write-Warning "SECURITY_RG not found: $SECURITY_RG" }
if ($RG_CHECK -notmatch $NETWORK_RG) { Write-Warning "NETWORK_RG not found: $NETWORK_RG" }
```

## 3) Ensure base network exists (VNet + required subnets)

The hydration/deployment scripts expect a VNet in `$NETWORK_RG` and these subnets:
- `functions-subnet`
- `private-endpoints-subnet`

Check:

```powershell
az network vnet list -g $NETWORK_RG -o table

# Capture first VNet name in network RG for downstream subnet commands
$VNET_NAME = az network vnet list -g $NETWORK_RG --query "[0].name" -o tsv
if ([string]::IsNullOrWhiteSpace($VNET_NAME)) {
  Write-Warning "Variable VNET_NAME is empty. Continue, but fix before dependent commands."
} else {
  "VNET_NAME = $VNET_NAME"
}
```

If no VNet exists, create one:

```powershell
$VNET_NAME = "blache-cdtscr-$ENV-vnet"
az network vnet create `
  --resource-group $NETWORK_RG `
  --name $VNET_NAME `
  --location $LOCATION `
  --address-prefixes 10.40.0.0/16 `
  --subnet-name functions-subnet `
  --subnet-prefixes 10.40.1.0/24

az network vnet subnet create `
  --resource-group $NETWORK_RG `
  --vnet-name $VNET_NAME `
  --name private-endpoints-subnet `
  --address-prefixes 10.40.2.0/24

# Capture subnet IDs for later modules
$FUNCTIONS_SUBNET_ID = az network vnet subnet show --resource-group $NETWORK_RG --vnet-name $VNET_NAME --name functions-subnet --query id -o tsv
$PRIVATE_ENDPOINTS_SUBNET_ID = az network vnet subnet show --resource-group $NETWORK_RG --vnet-name $VNET_NAME --name private-endpoints-subnet --query id -o tsv
if ([string]::IsNullOrWhiteSpace($FUNCTIONS_SUBNET_ID)) { Write-Warning "Variable FUNCTIONS_SUBNET_ID is empty. Continue, but fix before dependent commands." } else { "FUNCTIONS_SUBNET_ID = $FUNCTIONS_SUBNET_ID" }
if ([string]::IsNullOrWhiteSpace($PRIVATE_ENDPOINTS_SUBNET_ID)) { Write-Warning "Variable PRIVATE_ENDPOINTS_SUBNET_ID is empty. Continue, but fix before dependent commands." } else { "PRIVATE_ENDPOINTS_SUBNET_ID = $PRIVATE_ENDPOINTS_SUBNET_ID" }
```

## 4) Hydrate prod parameter files from current Azure resources

This script fills the `prod.parameters.json` files and forces private mode flags.

```powershell
.\data-pipelines\deployment\bicep\azure-infrastructure\scripts\hydrate-phase2-parameters.ps1 `
  -Environment prod `
  -SubscriptionId $SUBSCRIPTION_ID

# Re-capture aliases from deployment outputs after hydration (recommended)
cd .\data-pipelines\deployment\bicep\azure-infrastructure\scripts
. .\set-vars-from-main-deployment.ps1 -DeploymentName $DEPLOYMENT_NAME_MAIN -SubscriptionId $SUBSCRIPTION_ID
cd c:\Users\olanr\Desktop\blache
```

Files updated:
- `data-pipelines/deployment/bicep/phase2-data-ingestion/service-bus/parameters/prod.parameters.json`
- `data-pipelines/deployment/bicep/phase2-data-ingestion/azure-data-factory/parameters/prod.parameters.json`
- `data-pipelines/deployment/bicep/phase2-data-ingestion/private-network/parameters/prod.parameters.json`
- `data-pipelines/deployment/bicep/phase2-data-ingestion/functions/parameters/prod.parameters.json`

## 5) Manual parameter sanity check (required)

Open the four `prod.parameters.json` files and verify:
- `privateNetworkMode` is `true` where present
- `vnetId` points to prod VNet in `$NETWORK_RG`
- `functionsSubnetId` ends with `/subnets/functions-subnet`
- `privateEndpointsSubnetId` ends with `/subnets/private-endpoints-subnet`
- Resource names are prod names (not dev/staging)

## 6) Run what-if (safe preview)

```powershell
.\data-pipelines\deployment\bicep\azure-infrastructure\scripts\whatif-phase2-private.ps1 `
  -Environment prod `
  -DataResourceGroup $DATA_RG
```

Do not deploy if what-if returns failures.

## 7) Deploy Phase 2 private infra

```powershell
.\data-pipelines\deployment\bicep\azure-infrastructure\scripts\deploy-phase2-private.ps1 `
  -Environment prod `
  -DataResourceGroup $DATA_RG

# Capture key names emitted by deployment for verification commands
$SERVICEBUS_NAME = az servicebus namespace list -g $DATA_RG --query "[0].name" -o tsv
$ADF_NAME = az datafactory list -g $DATA_RG --query "[0].name" -o tsv
if ([string]::IsNullOrWhiteSpace($SERVICEBUS_NAME)) { Write-Warning "Variable SERVICEBUS_NAME is empty. Continue, but fix before dependent commands." } else { "SERVICEBUS_NAME = $SERVICEBUS_NAME" }
if ([string]::IsNullOrWhiteSpace($ADF_NAME)) { Write-Warning "Variable ADF_NAME is empty. Continue, but fix before dependent commands." } else { "ADF_NAME = $ADF_NAME" }
```

This deploys in order:
1. Service Bus
2. Data Factory
3. Private Endpoints + DNS wiring
4. Premium Functions infra

## 8) Post-deploy verification (must pass)

### 8.1 Resource existence

```powershell
az resource list -g $DATA_RG -o table
```

### 8.2 Private endpoints are provisioned and approved

```powershell
az network private-endpoint list -g $DATA_RG --query "[].{name:name,provisioning:provisioningState,subnet:id}" -o table
az network private-endpoint-connection list --id $(az servicebus namespace list -g $DATA_RG --query "[0].id" -o tsv) -o table
```

### 8.3 Private DNS zones and links

```powershell
az network private-dns zone list -g $NETWORK_RG -o table
az network private-dns link vnet list -g $NETWORK_RG -z privatelink.servicebus.windows.net -o table
az network private-dns link vnet list -g $NETWORK_RG -z privatelink.blob.core.windows.net -o table
```

If additional zones are used by your templates (ADF, Key Vault, Redis, Postgres), list and validate them too.

### 8.4 Public access hardening checks

```powershell
az servicebus namespace list -g $DATA_RG --query "[].{name:name,publicAccess:publicNetworkAccess}" -o table
az storage account list -g $DATA_RG --query "[].{name:name,publicAccess:publicNetworkAccess,defaultAction:networkRuleSet.defaultAction}" -o table
az keyvault list -g $SECURITY_RG --query "[].{name:name,publicAccess:properties.publicNetworkAccess}" -o table
```

### 8.5 Function Premium + VNet integration checks

```powershell
az functionapp list -g $DATA_RG --query "[].{name:name,state:state,kind:kind,host:defaultHostName}" -o table

# For each function app:
$FUNC_NAME = "<prod-function-app-name>"
az functionapp vnet-integration list -g $DATA_RG -n $FUNC_NAME -o table
```

### 8.6 Data Factory managed private endpoint checks

```powershell
az datafactory managed-private-endpoint list -g $DATA_RG --factory-name $ADF_NAME -o table
```

## 9) Smoke tests (functional)

Run minimal non-destructive tests:
- Publish a known-safe test message to the expected Service Bus topic(s)
- Verify:
  - Message is received by the intended subscription
  - Function App logs show successful trigger execution
  - Outputs written to expected storage paths
  - No `AuthorizationFailed`, DNS, or private endpoint connectivity errors in logs

Useful log check:

```powershell
az monitor app-insights query `
  --app "<app-insights-name>" `
  --analytics-query "traces | where timestamp > ago(30m) | order by timestamp desc | project timestamp, severityLevel, message" `
  -o table
```

## 10) Typical failure points and fixes

- **ResourceGroupNotFound**: create missing RGs first, then rerun.
- **SubscriptionIsOverQuotaForSku**: request quota increase for Premium tier/SKUs.
- **Private endpoint stuck Pending**: approve endpoint connection from target resource side.
- **DNS resolution failures**: verify private DNS zones + VNet links + A records.
- **Function cannot access resource**: verify managed identity RBAC and subnet routing.

## 11) Recommended release gating

Before declaring prod ready:
- What-if output archived
- Deploy output archived
- Private endpoint/DNS verification screenshots or CLI outputs saved
- Smoke test evidence saved
- Rollback steps documented (or forward-fix procedure approved)

