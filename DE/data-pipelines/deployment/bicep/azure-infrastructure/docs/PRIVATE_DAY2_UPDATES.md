# Private Day 2 Updates (`prod` parameter track)

This runbook applies **Day 2 updates** using:

- Templates: `deployment/bicep/day2-updates/modules/*`
- Parameters: `deployment/bicep/day2-updates/parameters/prod/*`
- Scripts: `deployment/bicep/day2-updates/scripts/*`

## Related guides

- Private deployment flow: `PRIVATE_DEPLOYMENT_GUIDE.md`
- Dev Day 2 track: `DAY2_UPDATES.md`
- How everything connects: `HOW_DEPLOYMENT_FITS_TOGETHER.md`

## 1) Set session variables

```powershell
$WORKSPACE = "C:\Users\olanr\Desktop\blache"
$DAY2 = Join-Path $WORKSPACE "data-pipelines\deployment\bicep\day2-updates"
$PARAMS = Join-Path $DAY2 "parameters\prod"

$SCRIPTS = Join-Path $WORKSPACE "data-pipelines\deployment\bicep\azure-infrastructure\scripts"

# Pick the target subscription explicitly (recommended)
$SUBSCRIPTION_ID = az account show --query id -o tsv
az account set --subscription $SUBSCRIPTION_ID
az account show --query "{name:name,id:id}" -o table

# Recover latest successful prod main deployment name automatically
$DEPLOYMENT_NAME_MAIN = az deployment sub list `
  --query "[?starts_with(name, 'main-prod-') && properties.provisioningState=='Succeeded'] | sort_by(@, &properties.timestamp) | [-1].name" `
  -o tsv
if ([string]::IsNullOrWhiteSpace($DEPLOYMENT_NAME_MAIN)) {
  throw "Could not resolve latest successful main-prod deployment. Set DEPLOYMENT_NAME_MAIN manually."
}

cd $SCRIPTS
. .\set-vars-from-main-deployment.ps1 -DeploymentName $DEPLOYMENT_NAME_MAIN

# Standardized alias (some Day 2 examples use this name)
$RG_DATA = $DATA_RG

$SERVICEBUS_NAMESPACE = az servicebus namespace list -g $DATA_RG --query "[0].name" -o tsv
$KEYVAULT_NAME = az keyvault list -g $SECURITY_RG --query "[0].name" -o tsv
$BLOB_STORAGE_ACCOUNT = $MainBlobStorageAccountName
$DATALAKE_STORAGE_ACCOUNT = $MainDataLakeStorageAccountName
```

## 2) Service Bus SQL rule updates

```powershell
az deployment group create `
  --resource-group $DATA_RG `
  --template-file "$DAY2\modules\service-bus\main.update.bicep" `
  --parameters "@$PARAMS\service-bus.update.parameters.json" `
  --parameters "serviceBusNamespaceName=$SERVICEBUS_NAMESPACE" `
  --name "day2-sb-rules-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
```

Verify rules (example):

```powershell
$SB_NAMESPACE = az servicebus namespace list -g $DATA_RG --query "[0].name" -o tsv
az servicebus topic subscription rule list -g $DATA_RG --namespace-name $SB_NAMESPACE --topic-name "data-ingested" --subscription-name "start-transformation" -o table
```

## 3) Blob + ADLS container/filesystem updates

```powershell
az deployment group create `
  --resource-group $DATA_RG `
  --template-file "$DAY2\modules\storage\main.update.bicep" `
  --parameters "@$PARAMS\storage.update.parameters.json" `
  --parameters "blobStorageAccountName=$BLOB_STORAGE_ACCOUNT" `
  --parameters "dataLakeStorageAccountName=$DATALAKE_STORAGE_ACCOUNT" `
  --name "day2-storage-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
```

The storage update template is intended to ensure the expected containers/filesystems exist. After it runs, create/verify required directory paths.

```powershell
$DLS_ACCOUNT = $DATALAKE_STORAGE_ACCOUNT
az storage fs directory create --account-name $DLS_ACCOUNT --file-system bronze --name training --auth-mode login
az storage fs directory create --account-name $DLS_ACCOUNT --file-system silver --name training --auth-mode login
az storage fs directory create --account-name $DLS_ACCOUNT --file-system curated --name ml-training --auth-mode login
az storage fs directory create --account-name $DLS_ACCOUNT --file-system curated --name models --auth-mode login
```

## 4) Key Vault IAM updates

```powershell
az deployment group create `
  --resource-group $DATA_RG `
  --template-file "$DAY2\modules\keyvault\main.update.bicep" `
  --parameters "@$PARAMS\keyvault.update.parameters.json" `
  --parameters "keyVaultName=$KEYVAULT_NAME" `
  --name "day2-kv-iam-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
```

Optional explicit user secret-write grant (if your tenant RBAC model requires it):

```powershell
$CURRENT_USER_OBJECT_ID = az ad signed-in-user show --query id -o tsv
$KEYVAULT_ID = az keyvault show -n $KEYVAULT_NAME -g $SECURITY_RG --query id -o tsv

$HAS_KV_SECRETS_OFFICER = az role assignment list `
  --scope $KEYVAULT_ID `
  --assignee-object-id $CURRENT_USER_OBJECT_ID `
  --query "[?roleDefinitionName=='Key Vault Secrets Officer'] | length(@)" `
  -o tsv

if ($HAS_KV_SECRETS_OFFICER -eq "0") {
  az role assignment create `
    --assignee-object-id $CURRENT_USER_OBJECT_ID `
    --assignee-principal-type User `
    --role "Key Vault Secrets Officer" `
    --scope $KEYVAULT_ID
}
```

## 5) Functions IAM updates

This section discovers Function Apps by name, then applies storage/key vault RBAC expectations via `apply-functions-iam.ps1`.

```powershell
$FUNCTION_NAMES = @(
  "payswitch-creditscore-prod-schema-mapping-func",
  "payswitch-creditscore-prod-training-ingestion-func",
  "payswitch-creditscore-prod-transformation-func",
  "payswitch-creditscore-prod-adf-trigger-func",
  "payswitch-creditscore-prod-file-checksum-func",
  "payswitch-cs-credit-risk",
  "payswitch-cs-customer-service",
  "payswitch-cs-fraud-detection",
  "payswitch-cs-income-verification",
  "payswitch-cs-loan-amount",
  "payswitch-cs-orchestrator"
)

$FUNCTION_APPS = @()
foreach ($name in $FUNCTION_NAMES) {
  $rg = az functionapp list --query "[?name=='$name'].resourceGroup | [0]" -o tsv
  if (-not [string]::IsNullOrWhiteSpace($rg)) {
    $FUNCTION_APPS += @{ name = $name; resourceGroupName = $rg }
  } else {
    Write-Warning "Function app not found: $name"
  }
}

$FUNCTION_APPS_JSON = $FUNCTION_APPS | ConvertTo-Json -Compress -Depth 5

cd "$DAY2\scripts"
.\apply-functions-iam.ps1 `
  -FunctionAppsJson $FUNCTION_APPS_JSON `
  -BlobStorageAccountName $BLOB_STORAGE_ACCOUNT `
  -DataLakeStorageAccountName $DATALAKE_STORAGE_ACCOUNT `
  -StorageResourceGroupName $DATA_RG `
  -KeyVaultName $KEYVAULT_NAME `
  -KeyVaultResourceGroupName $SECURITY_RG `
  -ExcludedFunctionAppNames @("payswitch-creditscore-prod-file-checksum-func")
```

## 6) Artifact manifests (reference layout)

Operational artifacts are staged under:

- `data-pipelines/deployment/artifacts/day2/`

Use this folder as the packaging source of truth for Day 2 operations that rely on checked-in manifests (not secret values).

## 7) PostgreSQL artifact apply

Precheck:

```powershell
cd "$WORKSPACE\data-pipelines\deployment\bicep\day2-updates\scripts"
# Interactive bootstrap: prompt admin for PostgreSQL values, write to Key Vault, create DB if missing
.\set-postgres-secrets-and-db.ps1 `
  -KeyVaultName $KEYVAULT_NAME `
  -PostgresResourceGroup $DATA_RG

# Read canonical values from Key Vault for precheck + apply
$POSTGRES_HOST = az keyvault secret show --vault-name $KEYVAULT_NAME --name "PostgreSQLHost" --query value -o tsv
$POSTGRES_DB = az keyvault secret show --vault-name $KEYVAULT_NAME --name "PostgreSQLDatabase" --query value -o tsv
$POSTGRES_USER = az keyvault secret show --vault-name $KEYVAULT_NAME --name "PostgreSQLAdminUsername" --query value -o tsv
$POSTGRES_PASSWORD = az keyvault secret show --vault-name $KEYVAULT_NAME --name "postgres-admin-password" --query value -o tsv

.\precheck-postgres-artifacts.ps1 `
  -PostgresHost $POSTGRES_HOST `
  -PostgresDatabase $POSTGRES_DB `
  -PostgresUser $POSTGRES_USER `
  -PostgresPassword $POSTGRES_PASSWORD
```

Apply:

```powershell
cd "$WORKSPACE\data-pipelines\deployment\bicep\day2-updates\scripts"
.\apply-postgres-artifacts.ps1 `
  -PostgresHost $POSTGRES_HOST `
  -PostgresDatabase $POSTGRES_DB `
  -PostgresUser $POSTGRES_USER `
  -PostgresPassword $POSTGRES_PASSWORD `
  -SqlArtifactsFolder "$WORKSPACE\data-pipelines\deployment\artifacts\day2\sql"
```
