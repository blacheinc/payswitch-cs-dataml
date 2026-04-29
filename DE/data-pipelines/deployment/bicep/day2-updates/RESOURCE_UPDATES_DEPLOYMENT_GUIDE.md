# Day-2 Resource Updates Guide (Prod)

This guide applies post-deployment updates for existing resources.

## 1) Set session variables

```powershell
$WORKSPACE = "C:\Users\olanr\Desktop\blache"
$DAY2 = Join-Path $WORKSPACE "data-pipelines\deployment\bicep\day2-updates"
$PARAMS = Join-Path $DAY2 "parameters\prod"

# Load core values from main deployment outputs (recommended)
$SCRIPTS = Join-Path $WORKSPACE "data-pipelines\deployment\bicep\azure-infrastructure\scripts"

# Recover latest successful main deployment name automatically
$DEPLOYMENT_NAME_MAIN = az deployment sub list `
  --query "[?starts_with(name, 'main-prod-') && properties.provisioningState=='Succeeded'] | sort_by(@, &properties.timestamp) | [-1].name" `
  -o tsv
if ([string]::IsNullOrWhiteSpace($DEPLOYMENT_NAME_MAIN)) {
  Write-Warning "Variable DEPLOYMENT_NAME_MAIN is empty. Continue, but fix before dependent commands."
} else {
  "DEPLOYMENT_NAME_MAIN = $DEPLOYMENT_NAME_MAIN"
}
cd $SCRIPTS
. .\set-vars-from-main-deployment.ps1 -DeploymentName $DEPLOYMENT_NAME_MAIN

# Standardized aliases from outputs
$RG_DATA = $DATA_RG

# Resolve commonly-needed names from deployed resources
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

Verify rules:

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

The template ensures:
- Blob containers: `bronze`, `silver`, `curated`
- ADLS filesystems/containers: `bronze`, `silver`, `curated`

Create required paths:

```powershell
$DLS_ACCOUNT = $DATALAKE_STORAGE_ACCOUNT   # or set explicit string
# Ensure correct subscription
az account set --subscription $SUBSCRIPTION_ID
# Resolve signed-in user object ID and storage scope
$USER_OBJECT_ID = az ad signed-in-user show --query id -o tsv
$STORAGE_SCOPE = az storage account show -g $DATA_RG -n $DLS_ACCOUNT --query id -o tsv
```
```powershell
# Example path creation in ADLS Gen2
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

## 5) Functions IAM updates

```powershell
# Auto-discover resource group per function app name
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
```

```powershell
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

```powershell

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

## 6) Artifacts to place before final hardening

Use `data-pipelines/deployment/artifacts/day2/`:
- `service-bus/`: rule manifests and topic/subscription mapping
- `sql/`: postgres schema + migration scripts
- `functions/`: release zip files and version manifest
- `adf/`: pipeline JSON + trigger configs
- `kv/`: secret name manifest (no secret values in git)

## 7) PostgreSQL artifact apply

Current detected SQL artifact:
- `data-pipelines/deployment/artifacts/day2/sql/credit-scoring-database-erd-sql.sql`

Assign Postgres RBAC to Admin:
```powershell
$KV_NAME = $KEYVAULT_NAME
$KV_RG = $SECURITY_RG
$USER_OBJECT_ID = az ad signed-in-user show --query id -o tsv
$KV_SCOPE = az keyvault show -g $KV_RG -n $KV_NAME --query id -o tsv
az role assignment create `
  --assignee-object-id $USER_OBJECT_ID `
  --assignee-principal-type User `
  --role "Key Vault Secrets User" `
  --scope $KV_SCOPE
az role assignment list `
  --assignee-object-id $USER_OBJECT_ID `
  --scope $KV_SCOPE `
  -o table
```

(If role was just added, wait ~1-5 minutes for propagation)


Precheck first:

```powershell
$POSTGRES_HOST = $MainPostgresServerFqdn
$POSTGRES_DB = az keyvault secret show --vault-name $KEYVAULT_NAME --name "PostgreSQLDatabase" --query value -o tsv
$POSTGRES_USER = az keyvault secret show --vault-name $KEYVAULT_NAME --name "PostgreSQLAdminUsername" --query value -o tsv
$POSTGRES_PASSWORD = az keyvault secret show --vault-name $KEYVAULT_NAME --name "postgres-admin-password" --query value -o tsv

cd "$WORKSPACE\data-pipelines\deployment\bicep\day2-updates\scripts"
.\precheck-postgres-artifacts.ps1 `
  -PostgresHost $POSTGRES_HOST `
  -PostgresDatabase $POSTGRES_DB `
  -PostgresUser $POSTGRES_USER `
  -PostgresPassword $POSTGRES_PASSWORD
```

Run:

```powershell
$POSTGRES_HOST = $MainPostgresServerFqdn
$POSTGRES_DB = az keyvault secret show --vault-name $KEYVAULT_NAME --name "PostgreSQLDatabase" --query value -o tsv
$POSTGRES_USER = az keyvault secret show --vault-name $KEYVAULT_NAME --name "PostgreSQLAdminUsername" --query value -o tsv
$POSTGRES_PASSWORD = az keyvault secret show --vault-name $KEYVAULT_NAME --name "postgres-admin-password" --query value -o tsv

cd "$WORKSPACE\data-pipelines\deployment\bicep\day2-updates\scripts"
.\apply-postgres-artifacts.ps1 `
  -PostgresHost $POSTGRES_HOST `
  -PostgresDatabase $POSTGRES_DB `
  -PostgresUser $POSTGRES_USER `
  -PostgresPassword $POSTGRES_PASSWORD `
  -SqlArtifactsFolder "$WORKSPACE\data-pipelines\deployment\artifacts\day2\sql"
```



## 8) Notes

- PostgreSQL remains connection-string/password based in this flow.
