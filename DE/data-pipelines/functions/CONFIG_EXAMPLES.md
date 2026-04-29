# Function Config Examples (Safe Templates)

Use these as non-secret templates. Replace all placeholder values before running locally.

## adf-pipeline-trigger

`.env.example`
```
ENVIRONMENT=local
KEY_VAULT_URL=https://<keyvault>.vault.azure.net/
ADF_SUBSCRIPTION_ID=<subscription-guid>
ADF_RESOURCE_GROUP=<resource-group>
ADF_FACTORY_NAME=<adf-name>
ADF_PIPELINE_NAME=pipeline-training-data-ingestion
```

`local.settings.example.json`
```json
{
  "IsEncrypted": false,
  "Values": {
    "AzureWebJobsStorage": "<storage-connection-string>",
    "FUNCTIONS_WORKER_RUNTIME": "python",
    "ServiceBusConnectionString": "<servicebus-connection-string>",
    "KEY_VAULT_URL": "https://<keyvault>.vault.azure.net/",
    "ADF_SUBSCRIPTION_ID": "<subscription-guid>",
    "ADF_RESOURCE_GROUP": "<resource-group>",
    "ADF_FACTORY_NAME": "<adf-name>",
    "ADF_PIPELINE_NAME": "pipeline-training-data-ingestion",
    "ENVIRONMENT": "local"
  }
}
```

## training-data-ingestion

`.env.example`
```
ENVIRONMENT=local
KEY_VAULT_URL=https://<keyvault>.vault.azure.net/
SERVICEBUS_TOPIC_NAME=data-awaits-ingestion
SERVICEBUS_SUBSCRIPTION_NAME=temp-peek-subscription
BLOB_STORAGE_ACCOUNT_NAME=<blob-account>
BLOB_CONTAINER_NAME=data
DATALAKE_STORAGE_ACCOUNT_NAME=<datalake-account>
BRONZE_CONTAINER_NAME=bronze
LOG_LEVEL=INFO
```

`local.settings.example.json`
```json
{
  "IsEncrypted": false,
  "Values": {
    "AzureWebJobsStorage": "<storage-connection-string>",
    "FUNCTIONS_WORKER_RUNTIME": "python",
    "AzureWebJobsFeatureFlags": "EnableWorkerIndexing",
    "KEY_VAULT_URL": "https://<keyvault>.vault.azure.net/",
    "ENVIRONMENT": "local",
    "ServiceBusConnectionString": "<servicebus-connection-string>",
    "SERVICEBUS_TOPIC_NAME": "data-awaits-ingestion",
    "SERVICEBUS_SUBSCRIPTION_NAME": "temp-peek-subscription",
    "BlobStorageConnectionString": "<blob-connection-string>",
    "DATALAKE_STORAGE_CONNECTION_STRING": "<datalake-connection-string>",
    "PostgreSQLConnectionString": "<postgres-connection-string>",
    "BRONZE_CONTAINER_NAME": "bronze",
    "LOG_LEVEL": "INFO"
  }
}
```

## schema-mapping-service

`.env.example`
```
ENVIRONMENT=local
KEY_VAULT_URL=https://<keyvault>.vault.azure.net/
SERVICEBUS_TOPIC_NAME=data-ingested
SERVICEBUS_SUBSCRIPTION_NAME=start-transformation
BRONZE_FILE_SYSTEM_NAME=bronze
SILVER_FILE_SYSTEM_NAME=silver
LOG_LEVEL=INFO
```

`local.settings.example.json`
```json
{
  "IsEncrypted": false,
  "Values": {
    "AzureWebJobsStorage": "<storage-connection-string>",
    "FUNCTIONS_WORKER_RUNTIME": "python",
    "ServiceBusConnectionString": "<servicebus-connection-string>",
    "KEY_VAULT_URL": "https://<keyvault>.vault.azure.net/",
    "DATALAKE_STORAGE_CONNECTION_STRING": "<datalake-connection-string>"
  }
}
```

## transformation-service

`.env.example`
```
SERVICE_BUS_CONNECTION_STRING=<servicebus-connection-string>
ServiceBusConnectionString=<servicebus-connection-string>
TRANSFORMATION_TRIGGER_TOPIC=schema-mapping-service
TRANSFORMATION_TRIGGER_SUBSCRIPTION=mapping-complete
TRANSFORM_OUTPUT_TOPIC=data-ingested
TRAINING_DATA_READY_TOPIC=training-data-ready
INFERENCE_REQUEST_TOPIC=inference-request
GOLD_CONTAINER_NAME=curated
GOLD_OUTPUT_PREFIX=ml-training
BATCH_SCORE_REQUEST_TOPIC=batch-score-request
BATCH_SCORE_CONTAINER=curated
BATCH_SCORE_INPUT_PREFIX=ml-batch
BATCH_SCORE_INLINE_THRESHOLD=50
BATCH_SCORE_STORAGE_ACCOUNT=<storage-account>
```

`local.settings.example.json`
```json
{
  "IsEncrypted": false,
  "Values": {
    "AzureWebJobsStorage": "<storage-connection-string>",
    "FUNCTIONS_WORKER_RUNTIME": "python",
    "SERVICE_BUS_CONNECTION_STRING": "<servicebus-connection-string>",
    "ServiceBusConnectionString": "<servicebus-connection-string>",
    "TRANSFORMATION_TRIGGER_TOPIC": "schema-mapping-service",
    "TRANSFORMATION_TRIGGER_SUBSCRIPTION": "mapping-complete",
    "TRANSFORM_OUTPUT_SERVICE_BUS_CONNECTION_STRING": "<servicebus-connection-string>",
    "TRANSFORM_OUTPUT_TOPIC": "data-ingested",
    "TRAINING_DATA_READY_TOPIC": "training-data-ready",
    "INFERENCE_REQUEST_TOPIC": "inference-request",
    "GOLD_STORAGE_CONNECTION_STRING": "<storage-connection-string>",
    "GOLD_CONTAINER_NAME": "curated",
    "GOLD_OUTPUT_PREFIX": "ml-training",
    "BATCH_SCORE_REQUEST_TOPIC": "batch-score-request",
    "BATCH_SCORE_CONTAINER": "curated",
    "BATCH_SCORE_INPUT_PREFIX": "ml-batch",
    "BATCH_SCORE_INLINE_THRESHOLD": "50",
    "BATCH_SCORE_STORAGE_ACCOUNT": "<storage-account>"
  }
}
```

## file-checksum-calculator

`.env.example`
```
STORAGE_ACCOUNT_NAME=<blob-account>
DATA_LAKE_ACCOUNT_NAME=<datalake-account>
```

`local.settings.example.json`
```json
{
  "IsEncrypted": false,
  "Values": {
    "AzureWebJobsStorage": "<storage-connection-string>",
    "FUNCTIONS_WORKER_RUNTIME": "python",
    "STORAGE_ACCOUNT_NAME": "<blob-account>",
    "DATA_LAKE_ACCOUNT_NAME": "<datalake-account>"
  }
}
```

## data-quality-agent

`.env.example`
```
SERVICE_BUS_NAMESPACE=<servicebus-namespace>
KEY_VAULT_URL=https://<keyvault>.vault.azure.net/
STORAGE_ACCOUNT_NAME=<storage-account>
QUALITY_THRESHOLD=95.0
OUTLIER_Z_SCORE=3.0
MISSING_VALUE_THRESHOLD=0.05
```

`local.settings.example.json`
```json
{
  "IsEncrypted": false,
  "Values": {
    "AzureWebJobsStorage": "<storage-connection-string>",
    "FUNCTIONS_WORKER_RUNTIME": "python",
    "SERVICE_BUS_NAMESPACE": "<servicebus-namespace>",
    "KEY_VAULT_URL": "https://<keyvault>.vault.azure.net/",
    "STORAGE_ACCOUNT_NAME": "<storage-account>",
    "QUALITY_THRESHOLD": "95.0",
    "OUTLIER_Z_SCORE": "3.0",
    "MISSING_VALUE_THRESHOLD": "0.05"
  }
}
```

## feature-engineering-agent

`.env.example`
```
SERVICE_BUS_NAMESPACE=<servicebus-namespace>
KEY_VAULT_URL=https://<keyvault>.vault.azure.net/
STORAGE_ACCOUNT_NAME=<storage-account>
FEAST_REGISTRY_PATH=gs://feast-registry
PSI_WARNING=0.1
PSI_CRITICAL=0.2
KS_WARNING=0.05
KS_CRITICAL=0.1
```

`local.settings.example.json`
```json
{
  "IsEncrypted": false,
  "Values": {
    "AzureWebJobsStorage": "<storage-connection-string>",
    "FUNCTIONS_WORKER_RUNTIME": "python",
    "SERVICE_BUS_NAMESPACE": "<servicebus-namespace>",
    "KEY_VAULT_URL": "https://<keyvault>.vault.azure.net/",
    "STORAGE_ACCOUNT_NAME": "<storage-account>",
    "FEAST_REGISTRY_PATH": "gs://feast-registry",
    "PSI_WARNING": "0.1",
    "PSI_CRITICAL": "0.2",
    "KS_WARNING": "0.05",
    "KS_CRITICAL": "0.1"
  }
}
```
