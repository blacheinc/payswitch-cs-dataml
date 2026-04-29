# Training Data Ingestion Azure Function - Recreation Guide

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Prerequisites](#prerequisites)
4. [Database Schema Setup](#database-schema-setup)
5. [Step-by-Step Setup](#step-by-step-setup)
6. [Configuration](#configuration)
7. [Common Errors and Solutions](#common-errors-and-solutions)
8. [Authentication Considerations](#authentication-considerations)
9. [Deployment](#deployment)
10. [Troubleshooting](#troubleshooting)
11. [Lessons Learned](#lessons-learned)

---

## Overview

The Training Data Ingestion Azure Function processes messages from Azure Service Bus, copies files from Azure Blob Storage to Azure Data Lake Gen2 (bronze layer), verifies file integrity using SHA-256 checksums, updates PostgreSQL metadata, and publishes success messages back to Service Bus.

### Key Features

- **Service Bus Trigger**: Processes messages from `data-awaits-ingestion` topic
- **File Copy**: Copies files from blob storage to Data Lake Gen2 bronze layer
- **Integrity Verification**: SHA-256 checksum calculation and verification
- **Database Updates**: Updates `training_uploads` and `bronze_ingestion_log` tables
- **Error Handling**: Comprehensive error handling with status tracking
- **Managed Identity Support**: Uses Managed Identity with connection string fallback

---

## Architecture

```
Service Bus (data-awaits-ingestion)
    ↓
Azure Function (Service Bus Trigger)
    ↓
run_training_ingestion.py
    ├── TrainingKeyVaultReader (Key Vault secrets)
    ├── TrainingPostgresClient (PostgreSQL connection)
    ├── TrainingUploadsClient (training_uploads table operations)
    ├── BronzeIngestionLogClient (bronze_ingestion_log table operations)
    ├── StorageClient (Blob Storage → Data Lake Gen2)
    ├── ChecksumCalculator (SHA-256 checksums)
    └── TrainingServiceBusWriter (publish to data-ingested)
```

### Key Components

1. **function_app.py**: Azure Function entry point with Service Bus trigger
2. **scripts/run_training_ingestion.py**: Main orchestration logic
3. **utils/training_key_vault_reader.py**: Key Vault secret retrieval
4. **utils/training_postgres_client.py**: PostgreSQL connection management
5. **utils/training_uploads_client.py**: `training_uploads` table operations
6. **utils/bronze_ingestion_log_client.py**: `bronze_ingestion_log` table operations
7. **utils/storage_client.py**: Blob Storage and Data Lake Gen2 operations
8. **utils/checksum_calculator.py**: SHA-256 checksum calculation
9. **utils/training_service_bus_writer.py**: Service Bus message publishing

---

## Prerequisites

### Azure Resources

1. **Azure Function App** (Python 3.11)
2. **Azure Service Bus** (Topic: `data-awaits-ingestion`, Subscription: `temp-peek-subscription`)
3. **Azure Key Vault** (for secrets management)
4. **Azure Blob Storage Account** (source files in `data` container)
5. **Azure Data Lake Storage Gen2** (destination: `bronze` filesystem)
6. **Azure PostgreSQL** (database: `credit_scoring`)

### Local Development

1. **Python 3.11+**
2. **Azure Functions Core Tools** (`func` CLI)
3. **Azure CLI** (for local authentication)
4. **PostgreSQL client** (optional, for database verification)

### Permissions Required

#### Managed Identity (Azure Deployment)

The Function App's Managed Identity needs:

1. **Key Vault**: `Key Vault Secrets User` role
2. **Blob Storage**: `Storage Blob Data Reader` role (source account)
3. **Data Lake Gen2**: `Storage Blob Data Contributor` role (destination account)
4. **Service Bus**: `Azure Service Bus Data Receiver` and `Azure Service Bus Data Sender` roles
5. **PostgreSQL**: Database user with INSERT, UPDATE, SELECT permissions

#### Local Development

- Azure CLI authentication (`az login`)
- Same permissions as above (via your user account)

---

## Database Schema Setup

### 1. training_uploads Table

The `training_uploads` table should already exist. Verify it has these key fields:

```sql
-- Key fields used by the function
id UUID PRIMARY KEY
data_source_id UUID
status upload_status  -- Enum type
file_name TEXT
file_format TEXT
file_size_bytes BIGINT
raw_file_path TEXT
file_metadata JSONB
record_count INTEGER
error_message TEXT
created_at TIMESTAMP
updated_at TIMESTAMP
```

**Status Enum Values** (must match exactly):
```sql
-- Verify enum values
SELECT enum_range(NULL::upload_status);

-- Expected values:
-- uploading, parsing, parsed, mapping, mapped, reviewing, approved,
-- transforming, completed, rejected, failed, ingesting, ingested
```

**Critical**: The function expects `status = 'ingesting'` before processing.

### 2. bronze_ingestion_log Table

Create this table if it doesn't exist:

```sql
-- Run: scripts/create_bronze_ingestion_log_table.sql

CREATE TABLE IF NOT EXISTS bronze_ingestion_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    training_upload_id UUID NOT NULL REFERENCES training_uploads(id) ON DELETE CASCADE,
    run_id UUID NOT NULL,
    source_blob_path TEXT NOT NULL,
    source_checksum_sha256 TEXT NOT NULL,
    source_file_size_bytes BIGINT NOT NULL,
    bronze_blob_path TEXT NOT NULL,
    bronze_checksum_sha256 TEXT NOT NULL,
    bronze_file_size_bytes BIGINT NOT NULL,
    ingestion_status TEXT NOT NULL CHECK (
        ingestion_status IN ('success', 'file_not_found', 'copy_failed', 'verification_failed')
    ),
    error_message TEXT,
    ingested_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_bronze_log_training_upload_id ON bronze_ingestion_log(training_upload_id);
CREATE INDEX IF NOT EXISTS idx_bronze_log_run_id ON bronze_ingestion_log(run_id);
CREATE INDEX IF NOT EXISTS idx_bronze_log_status ON bronze_ingestion_log(ingestion_status);
CREATE INDEX IF NOT EXISTS idx_bronze_log_ingested_at ON bronze_ingestion_log(ingested_at);
```

### 3. Verify Database Connection

```sql
-- Test connection
SELECT COUNT(*) FROM training_uploads WHERE status = 'ingesting';

-- Verify enum values
SELECT unnest(enum_range(NULL::upload_status));
```

---

## Step-by-Step Setup

### 1. Clone/Create Function Directory

```bash
cd data-pipelines/functions
mkdir training-data-ingestion
cd training-data-ingestion
```

### 2. Create Virtual Environment

```bash
python -m venv training-ingestion-env

# Windows
training-ingestion-env\Scripts\activate

# Linux/Mac
source training-ingestion-env/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

**requirements.txt** should include:
```
azure-functions>=1.18.0
azure-storage-file-datalake>=12.19.0
azure-storage-blob>=12.19.0
azure-identity>=1.15.0
azure-keyvault-secrets>=4.8.0
azure-servicebus>=7.11.0
psycopg2-binary>=2.9.9
sqlalchemy>=2.0.0
python-dateutil>=2.8.2
python-dotenv>=1.0.0
```

### 4. Create Directory Structure

```
training-data-ingestion/
├── function_app.py
├── host.json
├── local.settings.json
├── requirements.txt
├── scripts/
│   ├── __init__.py
│   ├── run_training_ingestion.py
│   └── create_bronze_ingestion_log_table.sql
└── utils/
    ├── __init__.py
    ├── training_key_vault_reader.py
    ├── training_postgres_client.py
    ├── training_uploads_client.py
    ├── bronze_ingestion_log_client.py
    ├── storage_client.py
    ├── checksum_calculator.py
    └── training_service_bus_writer.py
```

### 5. Configure local.settings.json

```json
{
  "IsEncrypted": false,
  "Values": {
    "AzureWebJobsStorage": "UseDevelopmentStorage=true",
    "FUNCTIONS_WORKER_RUNTIME": "python",
    "KEY_VAULT_URL": "https://your-keyvault.vault.azure.net/",
    "ServiceBusConnectionString": "Endpoint=sb://...",
    "BlobStorageAccountName": "your-blob-account",
    "DataLakeStorageAccountName": "your-datalake-account",
    "BlobStorageConnectionString": "DefaultEndpointsProtocol=https;...",
    "StorageConnectionString": "DefaultEndpointsProtocol=https;...",
    "BRONZE_CONTAINER_NAME": "bronze",
    "BLOB_CONTAINER_NAME": "data",
    "ENVIRONMENT": "local"
  }
}
```

**⚠️ Important**: Set `IsEncrypted: false` for local development.

### 6. Test Locally

```bash
func start
```

---

## Configuration

### Environment Variables

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `KEY_VAULT_URL` | Key Vault URL | Yes | - |
| `ServiceBusConnectionString` | Service Bus connection string | Yes | - |
| `BlobStorageAccountName` | Source blob storage account name | Yes | - |
| `DataLakeStorageAccountName` | Data Lake Gen2 account name | Yes | - |
| `BlobStorageConnectionString` | Blob storage connection string (fallback) | No | - |
| `StorageConnectionString` | Data Lake connection string (fallback) | No | - |
| `BRONZE_CONTAINER_NAME` | Bronze filesystem/container name | No | `bronze` |
| `BLOB_CONTAINER_NAME` | Source blob container name | No | `data` |
| `ENVIRONMENT` | Environment (`local` or `azure`) | No | `local` |

### Key Vault Secrets

The function retrieves these secrets from Key Vault:

- `ServiceBusConnectionString` (if not in env vars)
- `PostgreSQLConnectionString`
- `PostgreSQLDatabase` (defaults to `credit_scoring`)
- `BlobStorageAccountName` (if not in env vars)
- `DataLakeStorageAccountName` (if not in env vars)
- `BlobStorageConnectionString` (for fallback authentication)
- `StorageConnectionString` (for Data Lake fallback authentication)

---

## Common Errors and Solutions

### Error 1: Container/File System Does Not Exist

**Error Message:**
```
ResourceNotFoundError: The specified container does not exist.
```

**Cause:** The bronze filesystem/container doesn't exist in Data Lake Gen2.

**Solution:**
- The function will attempt to create the filesystem automatically
- Ensure Managed Identity has `Storage Blob Data Contributor` role on Data Lake account
- Or manually create the `bronze` filesystem in Azure Portal

**Prevention:**
- Create the `bronze` filesystem before deployment
- Verify permissions are set correctly

---

### Error 2: Storage Account Name Mismatch

**Error Message:**
```
BlobNotFound: The specified blob does not exist.
```

**Cause:** Using the wrong storage account name or connection string.

**Example:**
- Source blob account: `blachesty27jgavel2x32`
- Data Lake account: `blachedly27jgavel2x32` (note the `dly` vs `sty`)

**Solution:**
- Verify `BlobStorageAccountName` points to the source blob account
- Verify `DataLakeStorageAccountName` points to the Data Lake account
- Ensure connection strings match the correct accounts

**Prevention:**
- Use environment variables with clear naming
- Document which account is which
- Test connection strings before deployment

---

### Error 3: Authorization Failures

**Error Message:**
```
AuthorizationFailure: This request is not authorized to perform this operation.
AuthorizationPermissionMismatch: The request is not authorized to perform this operation.
```

**Cause:** Managed Identity doesn't have required permissions.

**Solution:**
1. **Grant RBAC permissions:**
   ```powershell
   # Blob Storage (source)
   az role assignment create \
     --assignee <function-app-managed-identity-principal-id> \
     --role "Storage Blob Data Reader" \
     --scope /subscriptions/<sub-id>/resourceGroups/<rg>/providers/Microsoft.Storage/storageAccounts/<blob-account>

   # Data Lake Gen2 (destination)
   az role assignment create \
     --assignee <function-app-managed-identity-principal-id> \
     --role "Storage Blob Data Contributor" \
     --scope /subscriptions/<sub-id>/resourceGroups/<rg>/providers/Microsoft.Storage/storageAccounts/<datalake-account>
   ```

2. **Use connection string fallback:**
   - The function automatically falls back to connection strings if Managed Identity fails
   - Ensure `BlobStorageConnectionString` and `StorageConnectionString` are in Key Vault or env vars

**Prevention:**
- Set up permissions before deployment
- Test Managed Identity access with a simple operation
- Keep connection strings as fallback option

---

### Error 4: Enum Value Mismatch

**Error Message:**
```
psycopg2.errors.InvalidTextRepresentation: invalid input value for enum upload_status: "copy_failed"
```

**Cause:** Trying to insert a status value that doesn't exist in the PostgreSQL enum.

**Solution:**
1. **Check current enum values:**
   ```sql
   SELECT unnest(enum_range(NULL::upload_status));
   ```

2. **Use correct status values:**
   - The function uses these statuses from `TrainingUploadStatus` enum:
     - `ingesting`, `ingested`, `error`, `failed`, `completed`
   - For `bronze_ingestion_log`, use: `success`, `file_not_found`, `copy_failed`, `verification_failed`

3. **If enum needs updating:**
   ```sql
   ALTER TYPE upload_status ADD VALUE 'copy_failed';
   -- Or use existing values like 'error' or 'failed'
   ```

**Prevention:**
- Verify enum values match function code before deployment
- Use enums in code instead of hardcoded strings
- Document all status values

---

### Error 5: Key Vault Reference Not Resolved

**Error Message:**
```
KeyVaultError: Secret not found or access denied
```

**Cause:** Key Vault reference in Function App settings not resolving.

**Solution:**
1. **Use direct values instead of Key Vault references:**
   - Retrieve secrets from Key Vault and set as direct values in Function App settings
   - This is faster and more reliable

2. **Or ensure Key Vault references are correct:**
   ```
   @Microsoft.KeyVault(SecretUri=https://your-vault.vault.azure.net/secrets/SecretName/)
   ```

3. **Grant Managed Identity access to Key Vault:**
   ```powershell
   az keyvault set-policy \
     --name <key-vault-name> \
     --object-id <function-app-managed-identity-principal-id> \
     --secret-permissions get list
   ```

**Prevention:**
- Use direct secret values for critical settings
- Test Key Vault access before deployment
- Document which secrets are required

---

### Error 6: Blob API vs DFS API Confusion

**Error Message:**
```
BlobNotFound: The specified blob does not exist.
```
(After successful copy via Blob API)

**Cause:** Trying to read a file via DFS API that was written via Blob API, or vice versa.

**Solution:**
- The function now uses Blob API consistently for Data Lake Gen2 operations
- `ChecksumCalculator` correctly identifies the storage account and uses the right connection string
- `StorageClient` uses `datalake_blob_service_client` for Data Lake operations

**Prevention:**
- Use consistent API (Blob API) for Data Lake Gen2
- Ensure `ChecksumCalculator` receives `datalake_storage_account_name`
- Test checksum calculation after file copy

---

### Error 7: File Not Found After Copy

**Error Message:**
```
File reported as copied successfully, but not found in Data Lake
```

**Cause:** Using wrong `BlobServiceClient` instance (source account instead of destination).

**Solution:**
- The function now uses `self.datalake_blob_service_client` for Data Lake operations
- Explicit file existence verification after copy
- Non-zero size verification

**Prevention:**
- Always use the correct client for each storage account
- Verify file exists and has non-zero size after copy
- Don't update database status until verification passes

---

### Error 8: Checksum Calculation on Wrong Account

**Error Message:**
```
BlobNotFound: The specified blob does not exist.
```
(During bronze checksum calculation)

**Cause:** `ChecksumCalculator` using source blob connection string for Data Lake file.

**Solution:**
- `ChecksumCalculator` now accepts `datalake_storage_account_name`
- It identifies if a URL points to the data lake account
- Uses `datalake_connection_string` for data lake files

**Prevention:**
- Pass `datalake_storage_account_name` to `ChecksumCalculator`
- Ensure connection strings are correctly identified
- Test checksum calculation for both source and destination

---

### Error 9: Service Bus Connection Not Found

**Error Message:**
```
No existing connection available (in Azure Portal)
```

**Cause:** Service Bus connection string not set or not resolving.

**Solution:**
1. **Set connection string directly in Function App settings:**
   - Go to Function App → Configuration → Application settings
   - Add `ServiceBusConnectionString` with direct value (not Key Vault reference)

2. **Or use Key Vault reference:**
   - Ensure format is correct
   - Grant Managed Identity access to Key Vault

**Prevention:**
- Set connection strings directly for reliability
- Test Service Bus connection before deployment
- Document connection string location

---

### Error 10: Database Connection Timeout

**Error Message:**
```
psycopg2.OperationalError: connection timeout
```

**Cause:** PostgreSQL server not accessible or firewall rules blocking.

**Solution:**
1. **Check firewall rules:**
   - Allow Azure services
   - Add Function App outbound IPs to allowed list

2. **Check connection string:**
   - Verify host, port, database name, credentials

3. **Check network connectivity:**
   - Ensure Function App can reach PostgreSQL server

**Prevention:**
- Configure firewall rules before deployment
- Test database connection from Function App
- Use connection pooling if needed

---

## Authentication Considerations

### Managed Identity vs Connection Strings

The function supports both authentication methods:

1. **Managed Identity (Preferred)**:
   - More secure (no secrets in code)
   - Requires RBAC permissions
   - May have slower initialization

2. **Connection Strings (Fallback)**:
   - Faster access
   - Requires storing secrets
   - Used automatically if Managed Identity fails

### Implementation Pattern

```python
# In StorageClient.__init__
if env == "azure":
    # Try Managed Identity first
    credential = DefaultAzureCredential()
    test_client = BlobServiceClient(...)
    try:
        # Test with lightweight operation
        next(iter(test_client.list_containers()), None)
        self.use_managed_identity = True
    except:
        # Fall back to connection strings
        self.use_managed_identity = False
        credential = None
else:
    # Local: prefer connection strings
    credential = AzureCliCredential() if not connection_string else None
```

### Best Practices

1. **Always provide connection strings as fallback**
2. **Test Managed Identity permissions before deployment**
3. **Use connection strings for local development**
4. **Monitor authentication failures in logs**

---

## Deployment

### 1. Create Function App

```powershell
az functionapp create \
  --resource-group <resource-group> \
  --consumption-plan-location <location> \
  --runtime python \
  --runtime-version 3.11 \
  --functions-version 4 \
  --name <function-app-name> \
  --storage-account <storage-account>
```

### 2. Enable Managed Identity

```powershell
az functionapp identity assign \
  --name <function-app-name> \
  --resource-group <resource-group>
```

### 3. Grant Permissions

See [Prerequisites](#prerequisites) section for required roles.

### 4. Deploy Code

```powershell
func azure functionapp publish <function-app-name>
```

### 5. Configure Application Settings

Set all required environment variables in Function App Configuration.

### 6. Test Deployment

- Send a test message to Service Bus
- Check Function App logs
- Verify file copied to Data Lake
- Check database updates

---

## Troubleshooting

### Function Not Triggering

1. **Check Service Bus subscription:**
   - Verify subscription exists
   - Check message count
   - Verify filter rules

2. **Check Function App logs:**
   ```bash
   az functionapp log tail --name <function-app-name> --resource-group <resource-group>
   ```

3. **Check Service Bus connection:**
   - Verify `ServiceBusConnectionString` is set
   - Test connection from Function App

### Files Not Copying

1. **Check storage permissions:**
   - Verify Managed Identity has correct roles
   - Check connection strings if using fallback

2. **Check storage account names:**
   - Verify `BlobStorageAccountName` and `DataLakeStorageAccountName` are correct
   - Ensure accounts exist and are accessible

3. **Check file paths:**
   - Verify source file exists
   - Check container/filesystem names

### Database Updates Failing

1. **Check PostgreSQL connection:**
   - Verify connection string
   - Check firewall rules
   - Test connection from Function App

2. **Check enum values:**
   - Verify status enum values match code
   - Check for typos in status strings

3. **Check table schema:**
   - Verify `training_uploads` table exists
   - Verify `bronze_ingestion_log` table exists
   - Check foreign key constraints

### Checksum Verification Failing

1. **Check file integrity:**
   - Verify source file hasn't changed
   - Check for network issues during copy

2. **Check checksum calculation:**
   - Verify correct storage account is used
   - Check connection strings are correct
   - Test checksum calculation independently

---

## Lessons Learned

### 1. Storage Account Separation

**Lesson:** Source blob storage and Data Lake Gen2 are separate accounts.

**Action:** Always use separate clients and connection strings for each account.

### 2. API Consistency

**Lesson:** Use Blob API consistently for Data Lake Gen2 operations.

**Action:** Avoid mixing DFS API and Blob API for the same operations.

### 3. Enum Values

**Lesson:** Database enum values must match code exactly.

**Action:** Use enums in code, verify enum values before deployment.

### 4. Authentication Fallback

**Lesson:** Managed Identity may not always work immediately.

**Action:** Always provide connection string fallback for critical operations.

### 5. File Verification

**Lesson:** Don't trust copy operations blindly.

**Action:** Always verify file exists and has non-zero size after copy.

### 6. Error Handling

**Lesson:** Comprehensive error handling prevents silent failures.

**Action:** Log all errors, update database status appropriately, don't skip verification steps.

### 7. Key Vault References

**Lesson:** Key Vault references can be slow or fail to resolve.

**Action:** Use direct secret values for critical settings, especially in production.

### 8. Testing Strategy

**Lesson:** Test each component independently before integration.

**Action:** Test storage operations, database operations, and Service Bus operations separately.

---

## Additional Resources

- [Azure Functions Python Developer Guide](https://docs.microsoft.com/en-us/azure/azure-functions/functions-reference-python)
- [Azure Service Bus Documentation](https://docs.microsoft.com/en-us/azure/service-bus-messaging/)
- [Azure Data Lake Storage Gen2 Documentation](https://docs.microsoft.com/en-us/azure/storage/blobs/data-lake-storage-introduction)
- [Azure Key Vault Documentation](https://docs.microsoft.com/en-us/azure/key-vault/)

---

## Support

For issues or questions:
1. Check function logs in Azure Portal
2. Review error messages in this guide
3. Verify all prerequisites are met
4. Test components independently

---

**Last Updated:** 2026-03-14  
**Version:** 1.0
