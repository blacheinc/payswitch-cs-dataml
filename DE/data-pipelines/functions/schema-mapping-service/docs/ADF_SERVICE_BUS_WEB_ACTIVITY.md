# ADF Web Activity for Service Bus with run_id

## Service Bus REST API Format

### Application Properties vs BrokerProperties

- **BrokerProperties**: System properties (SessionId, MessageId, etc.) - sent as JSON string in `BrokerProperties` header
- **Application Properties**: Custom properties (run_id, training_upload_id, etc.) - sent as HTTP headers with `x-ms-` prefix

### Correct Web Activity Configuration

```json
{
  "method": "POST",
  "url": "https://<namespace>.servicebus.windows.net/data-ingested/messages",
  "headers": {
    "Authorization": "@{concat('SharedAccessSignature sr=https%3A%2F%2F', <namespace>, '.servicebus.windows.net%2F&sig=', <signature>, '&se=', <expiry>, '&skn=', <keyName>)}",
    "Content-Type": "application/json",
    "BrokerProperties": "@{json(concat('{\"SessionId\":\"', pipeline().parameters.training_upload_id, '\",\"MessageId\":\"', guid(), '\"}'))}",
    "x-ms-subscription": "start-transformation",
    "x-ms-run-id": "@{guid()}",
    "x-ms-training-upload-id": "@{pipeline().parameters.training_upload_id}",
    "x-ms-bank-id": "@{pipeline().parameters.bank_id}",
    "x-ms-bronze-blob-path": "@{pipeline().parameters.bronze_blob_path}"
  },
  "body": {
    "run_id": "@{guid()}",
    "training_upload_id": "@{pipeline().parameters.training_upload_id}",
    "bank_id": "@{pipeline().parameters.bank_id}",
    "bronze_blob_path": "@{pipeline().parameters.bronze_blob_path}"
  }
}
```

### Important Notes

1. **Application Properties Header Format**: 
   - Use `x-ms-<property-name>` format
   - Convert property names to lowercase with hyphens
   - Example: `run_id` → `x-ms-run-id`, `training_upload_id` → `x-ms-training-upload-id`, `bank_id` → `x-ms-bank-id`, `bronze_blob_path` → `x-ms-bronze-blob-path`
   - **Required headers for `start-transformation` subscription filter:**
     - `x-ms-subscription`: `"start-transformation"`
     - `x-ms-run-id`: Generated UUID
     - `x-ms-training-upload-id`: Upload identifier
     - `x-ms-bank-id`: Bank identifier
     - `x-ms-bronze-blob-path`: Bronze blob path

2. **Both Body and Headers**:
   - Include `run_id` in message body (for code to read)
   - Include `x-ms-run-id` in headers (for Service Bus filter)

3. **Authorization**:
   - Generate Shared Access Signature (SAS) token
   - Store SAS key in Key Vault or ADF linked service
   - Use ADF expression functions to build the token

### Alternative: Use Service Bus Send Activity (Recommended)

If your ADF version supports it, use the **Service Bus Send** activity instead:

1. **Service Bus Send Activity Settings**:
   - Topic: `data-ingested`
   - Message body: JSON with all fields including `run_id`
   - Custom Properties/Application Properties:
     - `run_id`: `@{guid()}`
     - `training_upload_id`: `@{pipeline().parameters.training_upload_id}`

2. **Advantages**:
   - Simpler configuration
   - Built-in authentication (uses linked service)
   - Automatic property handling

### Generating SAS Token in ADF

If using Web Activity, you'll need to generate the SAS token. Options:

1. **Use Azure Function** to generate SAS token
2. **Use Key Vault** to store pre-generated token (short-lived)
3. **Use Managed Identity** if Service Bus supports it (preferred)

### Example: Complete Web Activity with SAS

```json
{
  "name": "SendToServiceBus",
  "type": "WebActivity",
  "typeProperties": {
    "method": "POST",
    "url": "@{concat('https://', pipeline().parameters.serviceBusNamespace, '.servicebus.windows.net/data-ingested/messages')}",
    "headers": {
      "Authorization": "@{activity('GetSASToken').output.token}",
      "Content-Type": "application/json",
      "BrokerProperties": "@{json(concat('{\"SessionId\":\"', pipeline().parameters.training_upload_id, '\"}'))}",
      "x-ms-subscription": "start-transformation",
      "x-ms-run-id": "@{guid()}",
      "x-ms-training-upload-id": "@{pipeline().parameters.training_upload_id}",
      "x-ms-bank-id": "@{pipeline().parameters.bank_id}",
      "x-ms-bronze-blob-path": "@{pipeline().parameters.bronze_blob_path}"
    },
    "body": {
      "run_id": "@{guid()}",
      "training_upload_id": "@{pipeline().parameters.training_upload_id}",
      "bank_id": "@{pipeline().parameters.bank_id}",
      "bronze_blob_path": "@{pipeline().parameters.bronze_blob_path}"
    }
  }
}
```
