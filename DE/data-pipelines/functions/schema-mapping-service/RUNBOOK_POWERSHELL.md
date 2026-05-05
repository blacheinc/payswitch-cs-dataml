# Schema Mapping Service Runbook

Run from: `data-pipelines/functions/schema-mapping-service`

Only scripts in `scripts/` (not `scripts/deprecated/`) are part of the active workflow.

## Deploy

```powershell
Set-Location "<repo>\data-pipelines\functions\schema-mapping-service"
.\deploy.ps1 -CreateResources   # first create
.\deploy.ps1                    # normal redeploy
```

Required credentials/config:

- `az login` with rights to deploy the Function App and assign MI roles
- Key Vault with required secrets (`ServiceBusConnectionString`, `DataLakeStorageAccountName`, optional Data Lake connection string secret)

## Local run

```powershell
Set-Location "<repo>\data-pipelines\functions\schema-mapping-service"
func start
```

## Send test messages (active scripts)

```powershell
# Preferred: explicit IDs/path
python .\scripts\send_test_message_json.py --bank-id <data_source_id> --training-upload-id <upload_id> --bronze-blob-path "bronze/training/..."

# Quick smoke
python .\scripts\send_test_message_simple.py

# Advanced/custom payload
python .\scripts\send_test_message.py
```

## Direct pipeline run without host loop

```powershell
python .\scripts\run_pipeline_from_service_bus.py
```

## Subscription filter maintenance

```powershell
 # Set required values (or pass as script parameters)
 $env:SB_NAMESPACE_NAME = "<service-bus-namespace>"
 $env:SB_RESOURCE_GROUP = "<resource-group>"
 $env:SB_TOPIC_NAME = "data-ingested"
 $env:SB_SUBSCRIPTION_NAME = "start-transformation"

.\scripts\check_subscription_filter.ps1
.\scripts\set_subscription_filter_simple.ps1
```

## Clear queued error messages

```powershell
 # Also required by clear script:
 $env:KEY_VAULT_URL = "https://<key-vault-name>.vault.azure.net/"
.\scripts\clear_error_messages.ps1
```

## Downstream handoff

After mapping completes, validate `mapping-complete` consumption in transformation-service:
`..\transformation-service\RUNBOOK_POWERSHELL.md`
