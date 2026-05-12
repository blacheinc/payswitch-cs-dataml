# ADF Completion Runbook

Use this after infrastructure (`main.bicep`), Phase 2, and Function code deploys are complete.

Set **`$ENVIRONMENT`** to match the **`main-<environment>-*`** subscription deployment name prefix you deployed.

## 1) Session setup and dynamic resolution

```powershell
$WORKSPACE = "C:\path\to\your\repo"   # clone root of this repository
$SCRIPTS = Join-Path $WORKSPACE "data-pipelines\deployment\bicep\azure-infrastructure\scripts"
$DAY2 = Join-Path $WORKSPACE "data-pipelines\deployment\bicep\day2-updates"

$ENVIRONMENT = "<environment>"   # must match main deployment prefix main-<environment>-*
$DEPLOYMENT_NAME_MAIN = az deployment sub list `
  --query "[?starts_with(name, 'main-$ENVIRONMENT-') && properties.provisioningState=='Succeeded'] | sort_by(@, &properties.timestamp) | [-1].name" `
  -o tsv
if ([string]::IsNullOrWhiteSpace($DEPLOYMENT_NAME_MAIN)) { throw "Could not resolve main deployment for $ENVIRONMENT." }
$LOCATION = az deployment sub show --name $DEPLOYMENT_NAME_MAIN --query location -o tsv

cd $SCRIPTS
. .\set-vars-from-main-deployment.ps1 -DeploymentName $DEPLOYMENT_NAME_MAIN

$ADF_RG = $DATA_RG
$ADF_NAME = az datafactory list -g $ADF_RG --query "[0].name" -o tsv
$SERVICEBUS_NAMESPACE = az servicebus namespace list -g $DATA_RG --query "[0].name" -o tsv
$KEYVAULT_NAME = az keyvault list -g $SECURITY_RG --query "[0].name" -o tsv
$BLOB_STORAGE_ACCOUNT = $MainBlobStorageAccountName
$DATALAKE_STORAGE_ACCOUNT = $MainDataLakeStorageAccountName

if ([string]::IsNullOrWhiteSpace($ADF_NAME)) { throw "Could not resolve ADF name in $ADF_RG." }
```

If any value cannot be resolved dynamically, set it manually before proceeding:

```powershell
$ADF_NAME = "<adf-factory-name>"
$SERVICEBUS_NAMESPACE = "<sb-namespace-name>"
$KEYVAULT_NAME = "<keyvault-name>"
$BLOB_STORAGE_ACCOUNT = "<blob-storage-account>"
$DATALAKE_STORAGE_ACCOUNT = "<datalake-storage-account>"
```

## 2) Exists/healthy dependency checks

```powershell
az datafactory show -g $ADF_RG -n $ADF_NAME --query "{name:name,provisioningState:provisioningState}" -o table
az servicebus namespace show -g $DATA_RG -n $SERVICEBUS_NAMESPACE --query "{name:name,status:status}" -o table
az keyvault show -g $SECURITY_RG -n $KEYVAULT_NAME --query "{name:name,enableRbacAuthorization:properties.enableRbacAuthorization}" -o table
az storage account show -g $DATA_RG -n $BLOB_STORAGE_ACCOUNT --query "{name:name,status:statusOfPrimary}" -o table
az storage account show -g $DATA_RG -n $DATALAKE_STORAGE_ACCOUNT --query "{name:name,status:statusOfPrimary}" -o table
```

ADLS required paths:

```powershell
az storage fs directory exists --account-name $DATALAKE_STORAGE_ACCOUNT --file-system bronze --name training --auth-mode login
az storage fs directory exists --account-name $DATALAKE_STORAGE_ACCOUNT --file-system silver --name training --auth-mode login
az storage fs directory exists --account-name $DATALAKE_STORAGE_ACCOUNT --file-system curated --name ml-training --auth-mode login
```

Required Key Vault secrets used by ADF/function integration:

```powershell
$requiredSecrets = @(
  "service-bus-connection-string",
  "postgres-admin-password",
  "PostgreSQLDatabase",
  "PostgreSQLHost",
  "FileChecksumCalculatorFunctionBaseUrl",
  "FileChecksumCalculatorFunctionKey"
)
foreach ($s in $requiredSecrets) {
  $exists = az keyvault secret show --vault-name $KEYVAULT_NAME --name $s --query name -o tsv 2>$null
  if ([string]::IsNullOrWhiteSpace($exists)) { Write-Warning "Missing secret: $s" }
}
```

## 3) ADF IAM checks (Storage + Key Vault + Service Bus)

Apply Day 2 ADF IAM module:

```powershell
az deployment sub create `
  --name "adf-iam-$ENVIRONMENT-$(Get-Date -Format 'yyyyMMdd-HHmmss')" `
  --location $LOCATION `
  --template-file "$DAY2\modules\adf-iam\main.update.bicep" `
  --parameters "dataFactoryName=$ADF_NAME" `
  --parameters "dataFactoryResourceGroupName=$ADF_RG" `
  --parameters "blobStorageAccountName=$BLOB_STORAGE_ACCOUNT" `
  --parameters "dataLakeStorageAccountName=$DATALAKE_STORAGE_ACCOUNT" `
  --parameters "storageResourceGroupName=$DATA_RG" `
  --parameters "keyVaultName=$KEYVAULT_NAME" `
  --parameters "keyVaultResourceGroupName=$SECURITY_RG" `
  --parameters "serviceBusNamespaceName=$SERVICEBUS_NAMESPACE" `
  --parameters "serviceBusResourceGroupName=$DATA_RG"
```

Validate assignments:

```powershell
$ADF_PRINCIPAL_ID = az datafactory show -g $ADF_RG -n $ADF_NAME --query identity.principalId -o tsv
$KV_ID = az keyvault show -g $SECURITY_RG -n $KEYVAULT_NAME --query id -o tsv
$SB_ID = az servicebus namespace show -g $DATA_RG -n $SERVICEBUS_NAMESPACE --query id -o tsv
$BLOB_ID = az storage account show -g $DATA_RG -n $BLOB_STORAGE_ACCOUNT --query id -o tsv
$DLS_ID = az storage account show -g $DATA_RG -n $DATALAKE_STORAGE_ACCOUNT --query id -o tsv

az role assignment list --assignee-object-id $ADF_PRINCIPAL_ID --scope $KV_ID -o table
az role assignment list --assignee-object-id $ADF_PRINCIPAL_ID --scope $SB_ID -o table
az role assignment list --assignee-object-id $ADF_PRINCIPAL_ID --scope $BLOB_ID -o table
az role assignment list --assignee-object-id $ADF_PRINCIPAL_ID --scope $DLS_ID -o table
```

## 4) PostgreSQL readiness (for ADF + metadata interactions)

Infrastructure creates PostgreSQL server and default DBs. Day 2 prepares DB artifacts.

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

## 5) Promotion order (use both artifact models)

1. Deploy/verify ADF infrastructure from `phase2-data-ingestion/azure-data-factory/data-factory.bicep`
2. Apply Day 2 IAM updates (Functions + ADF)
3. Keep `live-export/` sanitized in Git and hydrate only locally when needed:
   - `live-export/README.md`
4. Promote curated pipeline artifact from:
   - `deployment/adf/pipeline-training-data-ingestion/`
5. Validate linked services and trigger dependencies in ADF UI or CLI.

## 6) Mandatory completion checklist

- ADF exists and healthy in target environment.
- Service Bus namespace exists and topic/subscription checks pass.
- Storage accounts and required ADLS paths exist.
- Key Vault secrets required by ADF/function integrations exist.
- ADF identity has required RBAC on Storage, Key Vault, Service Bus.
- PostgreSQL precheck passes for artifact application path.
- Function apps are deployed and callable by dependent ADF activities.
