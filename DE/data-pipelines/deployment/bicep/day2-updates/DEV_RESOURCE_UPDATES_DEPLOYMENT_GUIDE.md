# Day-2 Resource Updates Guide (Dev)

This guide applies post-deployment updates for an already-provisioned dev environment using dev-only day2 parameter files.

## 1) Set session variables

```powershell
$WORKSPACE = "C:\Users\olanr\Desktop\blache"
$DAY2 = Join-Path $WORKSPACE "data-pipelines\deployment\bicep\day2-updates"
$PARAMS = Join-Path $DAY2 "parameters\dev"

$SCRIPTS = Join-Path $WORKSPACE "data-pipelines\deployment\bicep\azure-infrastructure\scripts"
$ENVIRONMENT = "dev"
$ORG_NAME = "blache"
$PROJECT_NAME = "cdtscr"

# Recover latest successful dev main deployment automatically
$DEPLOYMENT_NAME_MAIN = az deployment sub list `
  --query "[?starts_with(name, 'main-dev-') && properties.provisioningState=='Succeeded'] | sort_by(@, &properties.timestamp) | [-1].name" `
  -o tsv

if ([string]::IsNullOrWhiteSpace($DEPLOYMENT_NAME_MAIN)) {
  throw "Could not resolve latest successful main-dev deployment. Set DEPLOYMENT_NAME_MAIN manually."
}

cd $SCRIPTS
. .\set-vars-from-main-deployment.ps1 -DeploymentName $DEPLOYMENT_NAME_MAIN

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
  --name "day2-dev-sb-rules-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
```

## 3) Blob + ADLS container/filesystem updates

```powershell
az deployment group create `
  --resource-group $DATA_RG `
  --template-file "$DAY2\modules\storage\main.update.bicep" `
  --parameters "@$PARAMS\storage.update.parameters.json" `
  --parameters "blobStorageAccountName=$BLOB_STORAGE_ACCOUNT" `
  --parameters "dataLakeStorageAccountName=$DATALAKE_STORAGE_ACCOUNT" `
  --name "day2-dev-storage-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
```

Create required paths:

```powershell
az storage fs directory create --account-name $DATALAKE_STORAGE_ACCOUNT --file-system bronze --name training --auth-mode login
az storage fs directory create --account-name $DATALAKE_STORAGE_ACCOUNT --file-system silver --name training --auth-mode login
az storage fs directory create --account-name $DATALAKE_STORAGE_ACCOUNT --file-system curated --name ml-training --auth-mode login
az storage fs directory create --account-name $DATALAKE_STORAGE_ACCOUNT --file-system curated --name models --auth-mode login
```

## 4) Key Vault IAM updates

```powershell
$CURRENT_USER_OBJECT_ID = az ad signed-in-user show --query id -o tsv

az deployment group create `
  --resource-group $DATA_RG `
  --template-file "$DAY2\modules\keyvault\main.update.bicep" `
  --parameters "@$PARAMS\keyvault.update.parameters.json" `
  --parameters "keyVaultName=$KEYVAULT_NAME" `
  --parameters "keyVaultSecretsUserPrincipalIds=[$CURRENT_USER_OBJECT_ID]" `
  --parameters "contributorPrincipalIds=[$CURRENT_USER_OBJECT_ID]" `
  --name "day2-dev-kv-iam-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
```

## 5) Functions IAM updates

```powershell
$FUNCTION_NAMES = @(
  "$ORG_NAME-$PROJECT_NAME-$ENVIRONMENT-schema-mapping-func",
  "$ORG_NAME-$PROJECT_NAME-$ENVIRONMENT-training-ingestion-func",
  "$ORG_NAME-$PROJECT_NAME-$ENVIRONMENT-transformation-func",
  "$ORG_NAME-$PROJECT_NAME-$ENVIRONMENT-adf-trigger-func",
  "$ORG_NAME-$PROJECT_NAME-$ENVIRONMENT-file-checksum-func"
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
  -ExcludedFunctionAppNames @("$ORG_NAME-$PROJECT_NAME-$ENVIRONMENT-file-checksum-func")
```

## 6) PostgreSQL artifact apply

```powershell
$POSTGRES_HOST = $MainPostgresServerFqdn
$POSTGRES_DB = az keyvault secret show --vault-name $KEYVAULT_NAME --name "PostgreSQLDatabase" --query value -o tsv
$POSTGRES_USER = az keyvault secret show --vault-name $KEYVAULT_NAME --name "PostgreSQLAdminUsername" --query value -o tsv
$POSTGRES_PASSWORD = az keyvault secret show --vault-name $KEYVAULT_NAME --name "postgres-admin-password" --query value -o tsv

cd "$DAY2\scripts"
.\precheck-postgres-artifacts.ps1 `
  -PostgresHost $POSTGRES_HOST `
  -PostgresDatabase $POSTGRES_DB `
  -PostgresUser $POSTGRES_USER `
  -PostgresPassword $POSTGRES_PASSWORD
```

```powershell
cd "$DAY2\scripts"
.\apply-postgres-artifacts.ps1 `
  -PostgresHost $POSTGRES_HOST `
  -PostgresDatabase $POSTGRES_DB `
  -PostgresUser $POSTGRES_USER `
  -PostgresPassword $POSTGRES_PASSWORD `
  -SqlArtifactsFolder "$WORKSPACE\data-pipelines\deployment\artifacts\day2\sql"
```

## 7) Notes

- This runbook has no dependency on `parameters/prod`.
- All day2 Bicep parameters are read from `parameters/dev`.
