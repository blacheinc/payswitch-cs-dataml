# Private Day 2 Updates (private deployment guide)

This runbook applies **Day 2 updates** using:

- Templates: `deployment/bicep/day2-updates/modules/*`
- Parameters: `deployment/bicep/day2-updates/parameters/<environment>/*` — set **`$ENVIRONMENT`** to the subdirectory under `parameters/` that you pair with **`PRIVATE_DEPLOYMENT_GUIDE.md`**.
- Scripts: `deployment/bicep/day2-updates/scripts/*`

## Related guides

- Private deployment flow: `PRIVATE_DEPLOYMENT_GUIDE.md`
- Default deployment guide Day 2: `DAY2_UPDATES.md`
- How everything connects: `HOW_DEPLOYMENT_FITS_TOGETHER.md`

## 1) Set session variables

```powershell
$WORKSPACE = "C:\path\to\your\repo-clone"
$DAY2 = Join-Path $WORKSPACE "data-pipelines\deployment\bicep\day2-updates"
$ENVIRONMENT = "<environment>"   # must match folder under day2-updates/parameters/
$PARAMS = Join-Path $DAY2 "parameters\$ENVIRONMENT"

$SCRIPTS = Join-Path $WORKSPACE "data-pipelines\deployment\bicep\azure-infrastructure\scripts"

# Pick the target subscription explicitly (recommended)
$SUBSCRIPTION_ID = az account show --query id -o tsv
az account set --subscription $SUBSCRIPTION_ID
az account show --query "{name:name,id:id}" -o table

# Recover latest successful main deployment for this environment
$DEPLOYMENT_NAME_MAIN = az deployment sub list `
  --query "[?starts_with(name, 'main-$ENVIRONMENT-') && properties.provisioningState=='Succeeded'] | sort_by(@, &properties.timestamp) | [-1].name" `
  -o tsv
if ([string]::IsNullOrWhiteSpace($DEPLOYMENT_NAME_MAIN)) {
  throw "Could not resolve latest successful main-$ENVIRONMENT deployment. Set DEPLOYMENT_NAME_MAIN manually."
}

cd $SCRIPTS
. .\set-vars-from-main-deployment.ps1 -DeploymentName $DEPLOYMENT_NAME_MAIN -ResolveDataRgResources

$LOCATION = az deployment sub show --name $DEPLOYMENT_NAME_MAIN --query location -o tsv

# Standardized alias (some Day 2 examples use this name)
$RG_DATA = $DATA_RG

$BLOB_STORAGE_ACCOUNT = $MainBlobStorageAccountName
$DATALAKE_STORAGE_ACCOUNT = $MainDataLakeStorageAccountName
```

`$KEYVAULT_NAME` comes from `main.bicep` outputs. `$SERVICEBUS_NAMESPACE`, `$ADF_NAME`, `$ADF_RG`, and `$FUNCTION_APP_NAMES` are set when Phase 2 resources exist in `$DATA_RG` (same **`-ResolveDataRgResources`** switch as `DAY2_UPDATES.md`).

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
az servicebus topic subscription rule list -g $DATA_RG --namespace-name $SERVICEBUS_NAMESPACE --topic-name "data-ingested" --subscription-name "start-transformation" -o table
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

This section discovers Function Apps dynamically in `$DATA_RG`, then applies storage/key vault/service bus RBAC expectations via `apply-functions-iam.ps1`.

```powershell
$FUNCTION_APPS = az functionapp list `
  --query "[?resourceGroup=='$DATA_RG'].{name:name,resourceGroupName:resourceGroup}" `
  -o json | ConvertFrom-Json
$EXCLUDED_FUNCTIONS = @(
  ($FUNCTION_APPS | Where-Object { $_.name -like "*file-checksum*" } | Select-Object -ExpandProperty name)
)

$FUNCTION_APPS_JSON = $FUNCTION_APPS | ConvertTo-Json -Compress -Depth 5

cd "$DAY2\scripts"
.\apply-functions-iam.ps1 `
  -FunctionAppsJson $FUNCTION_APPS_JSON `
  -BlobStorageAccountName $BLOB_STORAGE_ACCOUNT `
  -DataLakeStorageAccountName $DATALAKE_STORAGE_ACCOUNT `
  -StorageResourceGroupName $DATA_RG `
  -KeyVaultName $KEYVAULT_NAME `
  -KeyVaultResourceGroupName $SECURITY_RG `
  -ServiceBusNamespaceName $SERVICEBUS_NAMESPACE `
  -ServiceBusResourceGroupName $DATA_RG `
  -ExcludedFunctionAppNames $EXCLUDED_FUNCTIONS
```

## 6) ADF IAM updates (system-assigned identity)

Confirm `$ADF_NAME` is set (from **section 1** with `-ResolveDataRgResources`). Assign required roles on Storage, Key Vault, and Service Bus:

```powershell
if ([string]::IsNullOrWhiteSpace($ADF_NAME)) { throw "ADF_NAME is empty. Deploy Phase 2 and re-run set-vars-from-main-deployment.ps1 -ResolveDataRgResources." }
az deployment sub create `
  --name "day2-$ENVIRONMENT-adf-iam-$(Get-Date -Format 'yyyyMMdd-HHmmss')" `
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

Verify ADF role assignments:

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

## 7) Artifact manifests (reference layout)

Operational artifacts are staged under:

- `data-pipelines/deployment/artifacts/day2/`

Use this folder as the packaging source of truth for Day 2 operations that rely on checked-in manifests (not secret values).

## 8) PostgreSQL artifact apply

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
