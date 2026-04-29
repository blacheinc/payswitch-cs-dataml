# Training Data Ingestion - Azure Function Deployment Guide

This guide explains how to deploy the Training Data Ingestion function to Azure.

## Prerequisites

1. **Azure CLI** installed and logged in
   ```powershell
   az login
   ```

2. **Azure Functions Core Tools** installed
   ```powershell
   # Install via npm or download from:
   # https://github.com/Azure/azure-functions-core-tools/releases
   npm install -g azure-functions-core-tools@4 --unsafe-perm true
   ```

3. **Python 3.11** installed

4. **Key Vault** with the following secrets:
   - `ServiceBusConnectionString`
   - `PostgreSQLConnectionString`
   - `PostgreSQLDatabase` (optional, can parse from connection string)
   - `DataLakeStorageAccountName`
   - `BlobStorageAccountName` (or set as environment variable)
   - `BlobStorageConnectionString` (or `StorageAccountConnectionString`, `AzureWebJobsStorage`)
   - `StorageConnectionString` (for Data Lake, or `DataLakeStorageConnectionString`, `DataLakeConnectionString`)

## Local Testing

1. **Copy local settings template:**
   ```powershell
   cd data-pipelines/functions/training-data-ingestion
   Copy-Item local.settings.json.template local.settings.json
   ```

2. **Edit `local.settings.json`:**
   - Set `KEY_VAULT_URL` to your Key Vault URL
   - Set `ServiceBusConnectionString` (or leave empty to use Key Vault)
   - Set other environment variables as needed

3. **Install dependencies:**
   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   pip install azure-functions
   ```

4. **Run locally:**
   ```powershell
   func start
   ```

   The function will listen for messages on the Service Bus topic `data-awaits-ingestion` subscription `temp-peek-subscription`.

## Deployment to Azure

### Option 1: Using the Deployment Script (Recommended)

The deployment script has default values configured:
- **Resource Group**: `blache-cdtscr-dev-data-rg`
- **Function App Name**: `func-training-ingestion-prod`
- **Location**: `eastus2`
- **Key Vault Name**: `blachekvruhclai6km`

```powershell
cd data-pipelines/functions/training-data-ingestion

# Deploy to existing Function App (if it already exists)
.\deploy.ps1

# OR create new resources and deploy
.\deploy.ps1 -CreateResources

# OR override defaults
.\deploy.ps1 `
    -ResourceGroupName "your-rg" `
    -FunctionAppName "your-function-app" `
    -KeyVaultName "your-key-vault" `
    -CreateResources
```

**Note**: The script will:
1. Enable System-Assigned Managed Identity on the Function App
2. Grant the Managed Identity "Get" and "List" permissions on Key Vault
3. Configure Key Vault references for all secrets
4. Set environment variables
5. Deploy the function code

### Option 2: Manual Deployment

1. **Create Resource Group:**
   ```powershell
   az group create --name rg-training-data-ingestion --location eastus
   ```

2. **Create Storage Account:**
   ```powershell
   az storage account create `
       --name funcstorage$(Get-Random -Maximum 9999) `
       --resource-group rg-training-data-ingestion `
       --location eastus `
       --sku Standard_LRS
   ```

3. **Create App Service Plan:**
   ```powershell
   az functionapp plan create `
       --name func-training-ingestion-plan `
       --resource-group rg-training-data-ingestion `
       --location eastus `
       --sku Consumption `
       --is-linux
   ```

4. **Create Function App:**
   ```powershell
   az functionapp create `
       --name func-training-ingestion-prod `
       --resource-group rg-training-data-ingestion `
       --storage-account <storage-account-name> `
       --plan func-training-ingestion-plan `
       --runtime python `
       --runtime-version 3.11 `
       --functions-version 4
   ```

5. **Configure Key Vault References:**
   ```powershell
   $keyVaultName = "kv-your-key-vault-name"
   $keyVaultUrl = "https://$keyVaultName.vault.azure.net/"
   $functionAppName = "func-training-ingestion-prod"
   $resourceGroup = "rg-training-data-ingestion"
   
   # Set KEY_VAULT_URL
   az functionapp config appsettings set `
       --name $functionAppName `
       --resource-group $resourceGroup `
       --settings "KEY_VAULT_URL=$keyVaultUrl"
   
   # Set Key Vault references for secrets
   $secrets = @(
       "ServiceBusConnectionString",
       "PostgreSQLConnectionString",
       "PostgreSQLDatabase",
       "DataLakeStorageAccountName",
       "BlobStorageAccountName",
       "BlobStorageConnectionString",
       "StorageConnectionString"
   )
   
   foreach ($secret in $secrets) {
       az functionapp config appsettings set `
           --name $functionAppName `
           --resource-group $resourceGroup `
           --settings "$secret=@Microsoft.KeyVault(SecretUri=$keyVaultUrl/secrets/$secret/)"
   }
   ```

6. **Set Other Environment Variables:**
   ```powershell
   az functionapp config appsettings set `
       --name $functionAppName `
       --resource-group $resourceGroup `
       --settings `
           "ENVIRONMENT=azure" `
           "SERVICEBUS_TOPIC_NAME=data-awaits-ingestion" `
           "SERVICEBUS_SUBSCRIPTION_NAME=temp-peek-subscription" `
           "BLOB_CONTAINER_NAME=data" `
           "LOG_LEVEL=INFO"
   ```

7. **Deploy Function Code:**
   ```powershell
   func azure functionapp publish $functionAppName --python
   ```

## Key Vault Setup

Ensure your Key Vault has the following secrets configured:

| Secret Name | Description | Required |
|------------|-------------|----------|
| `ServiceBusConnectionString` | Service Bus connection string | Yes |
| `PostgreSQLConnectionString` | PostgreSQL connection string | Yes |
| `PostgreSQLDatabase` | Database name (optional, can parse from connection string) | No |
| `DataLakeStorageAccountName` | Data Lake Gen2 storage account name | Yes |
| `BlobStorageAccountName` | Blob storage account name | Yes |
| `BlobStorageConnectionString` | Blob storage connection string | Yes |
| `StorageConnectionString` | Data Lake connection string | Yes |

## Function App Settings

The function uses the following environment variables (set via Key Vault references or App Settings):

- `KEY_VAULT_URL` - Key Vault URL (required)
- `ENVIRONMENT` - Set to "azure" for Azure Functions
- `SERVICEBUS_TOPIC_NAME` - Service Bus topic name (default: "data-awaits-ingestion")
- `SERVICEBUS_SUBSCRIPTION_NAME` - Service Bus subscription name (default: "temp-peek-subscription")
- `BLOB_CONTAINER_NAME` - Blob container name (default: "data")
- `LOG_LEVEL` - Logging level (default: "INFO")

## Monitoring

View function logs:
```powershell
az functionapp log tail --name func-training-ingestion-prod --resource-group rg-training-data-ingestion
```

View in Azure Portal:
- Navigate to Function App → Functions → training_data_ingestion → Monitor

## Troubleshooting

1. **Function not triggering:**
   - Check Service Bus connection string is correct
   - Verify topic and subscription names match
   - Check function logs for errors

2. **Key Vault access errors:**
   - Ensure Function App has "Key Vault Secrets User" role on Key Vault
   - Verify Key Vault references are correctly formatted

3. **Database connection errors:**
   - Verify PostgreSQL connection string is correct
   - Check database name matches
   - Ensure Function App can reach PostgreSQL server

4. **Storage access errors:**
   - Verify storage account connection strings are correct
   - Check Function App has appropriate RBAC roles on storage accounts
