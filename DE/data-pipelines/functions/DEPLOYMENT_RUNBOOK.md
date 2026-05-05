# Functions Deployment Runbook

This runbook documents how to deploy each Azure Function app in `data-pipelines/functions/` after removing hardcoded environment values from deploy scripts.

## Common prerequisites

- Azure CLI installed and authenticated: `az login`
- Azure Functions Core Tools v4 (`func`)
- Permission to:
  - read/create resources in the target resource group
  - assign managed identity roles where needed
  - read required Key Vault secrets

You can pass values either as script parameters or environment variables.

Common env var names used:

- `RESOURCE_GROUP_NAME`
- `FUNCTION_APP_NAME`
- `AZURE_LOCATION`
- `KEY_VAULT_NAME`

## 1) ADF pipeline trigger

Script: `functions/adf-pipeline-trigger/deploy.ps1`

Required values:

- `ResourceGroupName` (or `RESOURCE_GROUP_NAME`)
- `FunctionAppName` (or `FUNCTION_APP_NAME`)
- `KeyVaultName` (or `KEY_VAULT_NAME`)
- `AdfFactoryName` (or `ADF_FACTORY_NAME`)
- `AdfPipelineName` (or `ADF_PIPELINE_NAME`)
- `AdfResourceGroup` (or `ADF_RESOURCE_GROUP`) (defaults to `ResourceGroupName` if omitted)
- `AdfSubscriptionId` (defaults to current `az account` subscription if omitted)

Example:

```powershell
$env:RESOURCE_GROUP_NAME = "my-rg"
$env:FUNCTION_APP_NAME = "my-adf-trigger-func"
$env:KEY_VAULT_NAME = "my-kv"
$env:ADF_RESOURCE_GROUP = "my-data-rg"
$env:ADF_FACTORY_NAME = "my-adf"
$env:ADF_PIPELINE_NAME = "pipeline-training-data-ingestion"

.\deploy.ps1 -CreateResources
```

Key Vault secret required by script:

- `ServiceBusConnectionString`

## 2) Schema mapping service

Script: `functions/schema-mapping-service/deploy.ps1`

Required values:

- `ResourceGroupName` (or `RESOURCE_GROUP_NAME`)
- `FunctionAppName` (or `FUNCTION_APP_NAME`)
- `KeyVaultName` (or `KEY_VAULT_NAME`)

Optional:

- `DataLakeStorageAccountName` (if omitted, script reads KV secret `DataLakeStorageAccountName`)
- `SkipPublish`
- `SkipDatalakeConnectionStringAppSetting`
- `CreateResources`

Example:

```powershell
$env:RESOURCE_GROUP_NAME = "my-rg"
$env:FUNCTION_APP_NAME = "my-schema-mapping-func"
$env:KEY_VAULT_NAME = "my-kv"

.\deploy.ps1 -CreateResources
```

Key Vault secrets used:

- `ServiceBusConnectionString`
- `DataLakeStorageAccountName`
- one of: `StorageConnectionString` / `DataLakeStorageConnectionString` / `DataLakeConnectionString`

## 3) Training data ingestion

Script: `functions/training-data-ingestion/deploy.ps1`

Required values:

- `ResourceGroupName` (or `RESOURCE_GROUP_NAME`)
- `FunctionAppName` (or `FUNCTION_APP_NAME`)
- `KeyVaultName` (or `KEY_VAULT_NAME`)

Optional:

- `StorageAccountName`
- `AppServicePlanName`
- `CreateResources`

Example:

```powershell
$env:RESOURCE_GROUP_NAME = "my-rg"
$env:FUNCTION_APP_NAME = "my-training-ingestion-func"
$env:KEY_VAULT_NAME = "my-kv"

.\deploy.ps1 -CreateResources
```

Key Vault secrets expected by script:

- `ServiceBusConnectionString`
- `PostgreSQLConnectionString`
- `PostgreSQLDatabase`
- `BlobStorageAccountName`
- `DataLakeStorageAccountName`
- `BlobStorageConnectionString`
- `StorageConnectionString`

## 4) Transformation service

Script: `functions/transformation-service/deploy.ps1`

Operator runbook: `functions/transformation-service/RUNBOOK_POWERSHELL.md`

Required values:

- `FunctionAppName` (or `FUNCTION_APP_NAME`)

Optional:

- `ResourceGroupName` (currently informational in the script)
- `Location` (currently informational in the script)

Example:

```powershell
$env:FUNCTION_APP_NAME = "my-transformation-func"
.\deploy.ps1
```

## Validation checklist after any deploy

- `az functionapp show -n <app> -g <rg>`
- `az functionapp config appsettings list -n <app> -g <rg>`
- `az functionapp log tail -n <app> -g <rg>`
- send a controlled test message using app-local scripts/runbook
