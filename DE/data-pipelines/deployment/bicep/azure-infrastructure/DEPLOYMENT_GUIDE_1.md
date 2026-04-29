# Dev Public Deployment Guide

This guide deploys a dev environment without private networking/security hardening layers.

Included:
- Core resources via `main.bicep`
- Phase 2 data-ingestion resources
- Day-2 artifact application

Excluded in this guide:
- Private endpoints
- Private DNS zones/links
- Public network lockdown steps
- Bastion/jump-box access path

TLS/HTTPS defaults from resource services remain enabled.

## 1) Session setup

```powershell
$WORKSPACE = "C:\Users\olanr\Desktop\blache"
$BICEP_TEMPLATES = Join-Path $WORKSPACE "data-pipelines\deployment\bicep\azure-infrastructure\bicep-templates"
$PHASE2 = Join-Path $WORKSPACE "data-pipelines\deployment\bicep\phase2-data-ingestion"
$DAY2 = Join-Path $WORKSPACE "data-pipelines\deployment\bicep\day2-updates"
$SCRIPTS = Join-Path $WORKSPACE "data-pipelines\deployment\bicep\azure-infrastructure\scripts"

$LOCATION = "eastus2"
$ENVIRONMENT = "dev"
$ORG_NAME = "payswitch"
$PROJECT_NAME = "creditscore"
$ADMIN_EMAIL = "your-admin-email@company.com"

$DEPLOYMENT_NAME_MAIN = "main-dev-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
```

---

## Part 1: Provision infrastructure

### 2) Deploy `main.bicep` for dev (public mode)

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
  --parameters deployJumpBox=false `
  --parameters enableAdvancedSecurity=false
```

### 3) Load deployment outputs into variables

```powershell
cd $SCRIPTS
. .\set-vars-from-main-deployment.ps1 -DeploymentName $DEPLOYMENT_NAME_MAIN -RequireCoreValues

$SERVICEBUS_NAMESPACE = az servicebus namespace list -g $DATA_RG --query "[0].name" -o tsv
$KEYVAULT_NAME = az keyvault list -g $SECURITY_RG --query "[0].name" -o tsv
$BLOB_STORAGE_ACCOUNT = $MainBlobStorageAccountName
$DATALAKE_STORAGE_ACCOUNT = $MainDataLakeStorageAccountName
```

### 4) Deploy Phase 2 resources (no private networking)

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

# Functions (tier choice)
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

---

## Part 2: Apply artifacts

### 5) Service Bus subscription rules

```powershell
az deployment group create `
  --resource-group $DATA_RG `
  --template-file "$DAY2\modules\service-bus\main.update.bicep" `
  --parameters "@$DAY2\parameters\dev\service-bus.update.parameters.json" `
  --parameters "serviceBusNamespaceName=$SERVICEBUS_NAMESPACE" `
  --name "day2-dev-sb-rules-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
```

### 6) Blob + ADLS containers and paths

```powershell
az deployment group create `
  --resource-group $DATA_RG `
  --template-file "$DAY2\modules\storage\main.update.bicep" `
  --parameters "@$DAY2\parameters\dev\storage.update.parameters.json" `
  --parameters "blobStorageAccountName=$BLOB_STORAGE_ACCOUNT" `
  --parameters "dataLakeStorageAccountName=$DATALAKE_STORAGE_ACCOUNT" `
  --name "day2-dev-storage-$(Get-Date -Format 'yyyyMMdd-HHmmss')"

az storage fs directory create --account-name $DATALAKE_STORAGE_ACCOUNT --file-system bronze --name training --auth-mode login
az storage fs directory create --account-name $DATALAKE_STORAGE_ACCOUNT --file-system silver --name training --auth-mode login
az storage fs directory create --account-name $DATALAKE_STORAGE_ACCOUNT --file-system curated --name ml-training --auth-mode login
az storage fs directory create --account-name $DATALAKE_STORAGE_ACCOUNT --file-system curated --name models --auth-mode login
```

### 7) Key Vault IAM updates

```powershell
$CURRENT_USER_OBJECT_ID = az ad signed-in-user show --query id -o tsv

az deployment group create `
  --resource-group $DATA_RG `
  --template-file "$DAY2\modules\keyvault\main.update.bicep" `
  --parameters "@$DAY2\parameters\dev\keyvault.update.parameters.json" `
  --parameters "keyVaultName=$KEYVAULT_NAME" `
  --parameters "keyVaultSecretsUserPrincipalIds=[$CURRENT_USER_OBJECT_ID]" `
  --parameters "contributorPrincipalIds=[$CURRENT_USER_OBJECT_ID]" `
  --name "day2-dev-kv-iam-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
```

### 8) Functions IAM updates

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

### 9) Function packaging and deploy

```powershell
# Repeat for each Function App package
$FUNC_RG = $DATA_RG
$FUNC_APP = "<function-app-name>"
$ZIP_PATH = "C:\path\to\functionapp-package.zip"

az functionapp deployment source config-zip `
  --resource-group $FUNC_RG `
  --name $FUNC_APP `
  --src "$ZIP_PATH"
```

### 10) PostgreSQL SQL artifacts

```powershell
$POSTGRES_HOST = $MainPostgresServerFqdn
$POSTGRES_DB = "<postgres-db-name>"
$POSTGRES_USER = "<postgres-admin-username>"
$POSTGRES_PASSWORD = "<postgres-admin-password>"

cd "$DAY2\scripts"
.\precheck-postgres-artifacts.ps1 `
  -PostgresHost $POSTGRES_HOST `
  -PostgresDatabase $POSTGRES_DB `
  -PostgresUser $POSTGRES_USER `
  -PostgresPassword $POSTGRES_PASSWORD

.\apply-postgres-artifacts.ps1 `
  -PostgresHost $POSTGRES_HOST `
  -PostgresDatabase $POSTGRES_DB `
  -PostgresUser $POSTGRES_USER `
  -PostgresPassword $POSTGRES_PASSWORD `
  -SqlArtifactsFolder "$WORKSPACE\data-pipelines\deployment\artifacts\day2\sql"
```

### 11) Key Vault secret creation (values entered by operator)

```powershell
$SECRET_VALUES = @{
  "api-secret-key" = "<enter-value>"
  "azure-openai-key" = "<enter-value>"
  "AzureOpenAIApiVersion" = "<enter-value>"
  "AzureOpenAIDeployment" = "<enter-value>"
  "AzureOpenAIEndpoint" = "<enter-value>"
  "AzureOpenAIKey" = "<enter-value>"
  "BlobStorageAccountName" = "<enter-value>"
  "BlobStorageConnectionString" = "<enter-value>"
  "DataLakeStorageAccountName" = "<enter-value>"
  "FileChecksumCalculatorFunctionBaseUrl" = "<enter-value>"
  "FileChecksumCalculatorFunctionKey" = "<enter-value>"
  "KeyVaultUrl" = "<enter-value>"
  "mongodb-connection-string" = "<enter-value>"
  "postgres-admin-password" = "<enter-value>"
  "PostgreSQLAdminUsername" = "<enter-value>"
  "PostgreSQLConnectionString" = "<enter-value>"
  "PostgreSQLDatabase" = "<enter-value>"
  "redis-password" = "<enter-value>"
  "RedisConnectionString" = "<enter-value>"
  "ServiceBusConnectionString" = "<enter-value>"
  "ServiceBusNamespace" = "<enter-value>"
  "StorageConnectionString" = "<enter-value>"
}

foreach ($name in $SECRET_VALUES.Keys) {
  az keyvault secret set `
    --vault-name $KEYVAULT_NAME `
    --name $name `
    --value $SECRET_VALUES[$name] | Out-Null
}
```
