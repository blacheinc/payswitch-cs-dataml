# File Checksum Calculator - Deployment Guide

## Step 1: Create Azure Function App

### Using Azure Portal:
1. Go to Azure Portal → Create Resource
2. Search for "Function App"
3. Create with these settings:
   - **Subscription:** Your subscription
   - **Resource Group:** `blache-cdtscr-dev-data-rg` (or your data resource group)
   - **Function App name:** `blache-cdtscr-dev-checksum-{random}` (must be globally unique)
   - **Publish:** Code
   - **Runtime stack:** Python
   - **Version:** 3.11 or 3.10
   - **Region:** Same as your other resources (e.g., East US 2)
   - **Operating System:** Linux
   - **Plan type:** Consumption (Serverless) or Premium
4. Click **Review + Create** → **Create**

### Using Azure CLI (PowerShell):
```powershell
az functionapp create `
  --resource-group blache-cdtscr-dev-data-rg `
  --consumption-plan-location eastus2 `
  --runtime python `
  --runtime-version 3.11 `
  --functions-version 4 `
  --name blache-cdtscr-dev-checksum-{random} `
  --storage-account {storage-account-name} `
  --os-type Linux
```

**Note:** In PowerShell, use backticks (`` ` ``) for line continuation, not backslashes (`\`).

**Or use a single line:**
```powershell
az functionapp create --resource-group blache-cdtscr-dev-data-rg --consumption-plan-location eastus2 --runtime python --runtime-version 3.11 --functions-version 4 --name blache-cdtscr-dev-checksum-{random} --storage-account {storage-account-name} --os-type Linux
```

## Step 2: Enable Managed Identity

### Using Azure Portal:
1. Go to your Function App → **Identity**
2. Under **System assigned**, toggle **Status** to **On**
3. Click **Save**
4. Copy the **Object (principal) ID** - you'll need it for IAM setup

### Using Azure CLI:
```bash
az functionapp identity assign \
  --name {function-app-name} \
  --resource-group blache-cdtscr-dev-data-rg
```

Get the principal ID:
```bash
az functionapp identity show \
  --name {function-app-name} \
  --resource-group blache-cdtscr-dev-data-rg \
  --query "principalId" -o tsv
```

## Step 3: Grant Storage Permissions (IAM)

The Function's Managed Identity needs **"Storage Blob Data Reader"** role on both storage accounts.

### Get Resource IDs:
```powershell
# Blob Storage Account
$BLOB_STORAGE_ID = az storage account show --name {blob-storage-account-name} --resource-group blache-cdtscr-dev-data-rg --query "id" -o tsv

# Data Lake Account
$DATA_LAKE_ID = az storage account show --name {data-lake-account-name} --resource-group blache-cdtscr-dev-data-rg --query "id" -o tsv

# Function App Managed Identity
$FUNCTION_IDENTITY = az functionapp identity show --name {function-app-name} --resource-group blache-cdtscr-dev-data-rg --query "principalId" -o tsv
```

### Grant Permissions:
```powershell
# Grant on Blob Storage
az role assignment create `
  --assignee $FUNCTION_IDENTITY `
  --role "Storage Blob Data Reader" `
  --scope $BLOB_STORAGE_ID

# Grant on Data Lake
az role assignment create `
  --assignee $FUNCTION_IDENTITY `
  --role "Storage Blob Data Reader" `
  --scope $DATA_LAKE_ID
```

## Step 4: Deploy Function Code

### Option A: Using Azure Functions Core Tools (Recommended)

```bash
# Install Azure Functions Core Tools (if not installed)
# https://docs.microsoft.com/en-us/azure/azure-functions/functions-run-local

# Navigate to function directory
cd data-pipelines/functions/file-checksum-calculator

# Login to Azure
az login

# Deploy function
func azure functionapp publish {function-app-name}
```

### Option B: Using VS Code

1. Install "Azure Functions" extension
2. Open function folder in VS Code
3. Right-click function folder → **Deploy to Function App**
4. Select your Function App

### Option C: Using Azure Portal

1. Go to Function App → **Deployment Center**
2. Choose deployment method (GitHub, Azure DevOps, Local Git, etc.)
3. Follow setup wizard

## Step 5: Get Function Key

You'll need the Function Key to call it from ADF.

### Using Azure Portal:
1. Go to Function App → **Functions** → `calculate_checksum_http`
2. Click **Function Keys**
3. Copy the **default** key

### Using Azure CLI:
```bash
az functionapp function keys list \
  --name {function-app-name} \
  --resource-group blache-cdtscr-dev-data-rg \
  --function-name calculate_checksum_http
```

## Step 6: Test the Function

```bash
# Test with curl
curl "https://{function-app-name}.azurewebsites.net/api/calculate_checksum?code={function-key}&blob_url=https://{storage-account}.blob.core.windows.net/{container}/{file}"
```

Expected response:
```json
{
  "checksum": "a3f5c8d9e2b1f4a7c6d8e9f0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",
  "blob_url": "https://...",
  "algorithm": "SHA-256"
}
```

## Step 7: Use in ADF Pipeline

### Step 7a: Retrieve Function Credentials from Key Vault

**Location:** Add these activities at the start of your pipeline (after CleanParameters, before LookupUploadMetadata)

**Activity 1: Get File Checksum Calculator Function Base URL**
1. Search for **"Web"** activity and drag it to canvas
2. Rename it: `GetFileChecksumCalculatorBaseUrl`
3. Configure:
   - **URL:** 
     ```
     https://blachekvruhclai6km.vault.azure.net/secrets/FileChecksumCalculatorFunctionBaseUrl/?api-version=7.4
     ```
   - **Method:** `GET`
   - **Authentication:** 
     - Type: `MSI` (Managed Service Identity)
     - Resource: `https://vault.azure.net/`
4. Click **OK**

**Activity 2: Get File Checksum Calculator Function Key**
1. Search for **"Web"** activity and drag it to canvas
2. Connect it after `GetFileChecksumCalculatorBaseUrl`
3. Rename it: `GetFileChecksumCalculatorKey`
4. Configure:
   - **URL:**
     ```
     https://blachekvruhclai6km.vault.azure.net/secrets/FileChecksumCalculatorFunctionKey/?api-version=7.4
     ```
   - **Method:** `GET`
   - **Authentication:**
     - Type: `MSI`
     - Resource: `https://vault.azure.net/`
5. Click **OK**

**Activity 3: Store Function Credentials in Variables**
1. Search for **"Set Variable"** activity and drag it after `GetFileChecksumCalculatorKey`
2. Rename it: `StoreFileChecksumCalculatorCredentials`
3. Configure:
   - **Variables:** Click **+ New** for each:
     - `fileChecksumCalculatorBaseUrl` (String) = `@activity('GetFileChecksumCalculatorBaseUrl').output.value.value`
     - `fileChecksumCalculatorKey` (String) = `@activity('GetFileChecksumCalculatorKey').output.value.value`
4. Click **OK**

### Step 7b: Get Source File Checksum

**Location:** Add after `LookupUploadMetadata` activity

1. Search for **"Web"** activity and drag it to canvas
2. Connect it after `LookupUploadMetadata`
3. Rename it: `GetSourceFileChecksum`
4. Configure:
   - **URL:** Click **Add dynamic content** and enter:
     ```
     @concat(variables('fileChecksumCalculatorBaseUrl'), '/api/calculate_checksum?code=', variables('fileChecksumCalculatorKey'), '&blob_url=', activity('LookupUploadMetadata').output.firstRow.blob_url)
     ```
   - **Method:** `GET`
   - **Authentication:** None (key is in URL)
5. Click **OK**

**Store Result:**
- Add **Set Variable** activity: `StoreSourceChecksum`
- **Variable:** `sourceChecksum` (String)
- **Value:** `@activity('GetSourceFileChecksum').output.checksum`

### Step 7c: Get Bronze File Checksum

**Location:** Add after `CopyToBronze` activity

1. Search for **"Web"** activity and drag it to canvas
2. Connect it after `CopyToBronze`
3. Rename it: `GetBronzeFileChecksum`
4. Configure:
   - **URL:** Click **Add dynamic content** and enter:
     ```
     @concat(variables('fileChecksumCalculatorBaseUrl'), '/api/calculate_checksum?code=', variables('fileChecksumCalculatorKey'), '&blob_url=', 'https://', variables('dataLakeName'), '.dfs.core.windows.net/bronze/training/', activity('LookupUploadMetadata').output.firstRow.bank_id, '/', formatDateTime(utcnow(), 'yyyy-MM-dd'), '/', variables('cleanUploadId'), '.', activity('LookupUploadMetadata').output.firstRow.file_format)
     ```
     **Note:** Adjust the bronze path to match your actual Data Lake path structure
   - **Method:** `GET`
   - **Authentication:** None
5. Click **OK**

**Store Result:**
- Add **Set Variable** activity: `StoreBronzeChecksum`
- **Variable:** `bronzeChecksum` (String)
- **Value:** `@activity('GetBronzeFileChecksum').output.checksum`

### Step 7d: Verify Checksum (Update If Condition)

**Location:** Your existing "If Condition - Verify File Size" activity

**Update the condition expression:**
- Current: `@equals(activity('GetBronzeFileSize').output.size, activity('LookupUploadMetadata').output.firstRow.file_size_bytes)`
- Updated: 
  ```
  @and(equals(activity('GetBronzeFileSize').output.size, activity('LookupUploadMetadata').output.firstRow.file_size_bytes), equals(variables('sourceChecksum'), variables('bronzeChecksum')))
  ```

This verifies both:
- File size matches
- Checksum matches

### Step 7e: Update PostgreSQL Metadata

**Location:** Your existing "Update PostgreSQL Metadata" activity

**Add checksum to UPDATE statement:**
```sql
UPDATE upload_metadata
SET 
    bronze_blob_path = '@{concat(''bronze/training/'', activity(''LookupUploadMetadata'').output.firstRow.bank_id, ''/'', formatDateTime(utcnow(), ''yyyy-MM-dd''), ''/'', variables(''cleanUploadId''), ''.'', activity(''LookupUploadMetadata'').output.firstRow.file_format)}',
    bronze_row_count = @{activity('LookupUploadMetadata').output.firstRow.row_count},
    bronze_file_size_bytes = @{activity('GetBronzeFileSize').output.size},
    bronze_checksum_sha256 = '@{variables(''bronzeChecksum'')}',
    bronze_status = 'completed',
    bronze_verified_at = CURRENT_TIMESTAMP,
    status = 'bronze_ingested',
    updated_at = CURRENT_TIMESTAMP
WHERE upload_id = '@{variables('cleanUploadId')}'
AND is_deleted = 'false'
```

## Troubleshooting

### 401 Unauthorized
- Verify Function's Managed Identity has "Storage Blob Data Reader" role
- Check that Managed Identity is enabled on Function App

### 404 Not Found
- Verify blob URL is correct
- Check that file exists in storage account

### Timeout
- Large files may timeout (default 10 minutes)
- Consider increasing function timeout in `host.json`

## Security Best Practices

1. **Store Function Key in Key Vault** - Don't hardcode in ADF
2. **Use Managed Identity** - Already implemented
3. **Restrict Function Access** - Use Function-level authentication
4. **Monitor Function** - Enable Application Insights
