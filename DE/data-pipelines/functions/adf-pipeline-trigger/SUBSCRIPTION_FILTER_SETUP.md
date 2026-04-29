# Service Bus Subscription Filter Setup Guide

## Quick Summary

You need to:
1. **Create** a new subscription `adf-trigger-subscription` with filter: `processing_system = 'ADF'`
2. **Update** existing subscription `temp-peek-subscription` to exclude ADF messages

---

## 1. Create New Subscription: `adf-trigger-subscription`

### Option A: Azure Portal

1. Go to **Azure Portal** → Your Service Bus namespace
2. Navigate to **Topics** → `data-awaits-ingestion`
3. Click **+ Subscription**
4. Fill in:
   - **Subscription name**: `adf-trigger-subscription`
   - **Max delivery count**: `10`
   - **Enable dead lettering**: ✅ Yes
   - **Message time to live**: (default or your preference)
5. Click **Create**

6. After creation, go to the subscription → **Filters and actions** tab
7. Click **+ Add filter**
8. Fill in:
   - **Filter name**: `ADFProcessingSystemFilter`
   - **Filter type**: **SQL**
   - **SQL filter expression**:
     ```sql
     processing_system = 'ADF'
     ```
9. Click **Save**

### Option B: Azure CLI

```bash
# Set variables
RESOURCE_GROUP="your-resource-group"
NAMESPACE_NAME="your-servicebus-namespace"
TOPIC_NAME="data-awaits-ingestion"
SUBSCRIPTION_NAME="adf-trigger-subscription"

# Create subscription
az servicebus topic subscription create \
  --resource-group $RESOURCE_GROUP \
  --namespace-name $NAMESPACE_NAME \
  --topic-name $TOPIC_NAME \
  --name $SUBSCRIPTION_NAME \
  --max-delivery-count 10 \
  --enable-dead-lettering-on-message-expiration true

# Add SQL filter
az servicebus topic subscription rule create \
  --resource-group $RESOURCE_GROUP \
  --namespace-name $NAMESPACE_NAME \
  --topic-name $TOPIC_NAME \
  --subscription-name $SUBSCRIPTION_NAME \
  --name ADFProcessingSystemFilter \
  --filter-sql-expression "processing_system = 'ADF'"
```

---

## 2. Update Existing Subscription: `temp-peek-subscription`

### Option A: Azure Portal

1. Go to **Azure Portal** → Your Service Bus namespace
2. Navigate to **Topics** → `data-awaits-ingestion` → `temp-peek-subscription`
3. Go to **Filters and actions** tab
4. **If a filter already exists** (e.g., `CheckTrainingUploadID`):
   - Click on the filter → **Edit**
   - Update the **SQL filter expression** to:
     ```sql
     training_upload_id IS NOT NULL AND (processing_system != 'ADF' OR processing_system IS NULL)
     ```
   - **⚠️ Important**: Both `training_upload_id` and `processing_system` must be in custom properties (application_properties) when sending messages!
   - Click **Save**

5. **If no filter exists**:
   - Click **+ Add filter**
   - **Filter name**: `ExcludeADFMessagesFilter`
   - **Filter type**: **SQL**
   - **SQL filter expression**:
     ```sql
     training_upload_id IS NOT NULL AND (processing_system != 'ADF' OR processing_system IS NULL)
     ```
   - Click **Save**

### Option B: Azure CLI

**First, check existing rules:**
```bash
az servicebus topic subscription rule list \
  --resource-group $RESOURCE_GROUP \
  --namespace-name $NAMESPACE_NAME \
  --topic-name $TOPIC_NAME \
  --subscription-name temp-peek-subscription
```

**If a rule exists, delete it first:**
```bash
az servicebus topic subscription rule delete \
  --resource-group $RESOURCE_GROUP \
  --namespace-name $NAMESPACE_NAME \
  --topic-name $TOPIC_NAME \
  --subscription-name temp-peek-subscription \
  --name <existing-rule-name>
```

**Then create/update the filter:**
```bash
az servicebus topic subscription rule create \
  --resource-group $RESOURCE_GROUP \
  --namespace-name $NAMESPACE_NAME \
  --topic-name $TOPIC_NAME \
  --subscription-name temp-peek-subscription \
  --name ExcludeADFMessagesFilter \
  --filter-sql-expression "training_upload_id IS NOT NULL AND (processing_system != 'ADF' OR processing_system IS NULL)"
```

**⚠️ Important**: Both `training_upload_id` and `processing_system` must be set as custom properties (application_properties) when sending messages for the filter to work!

---

## Filter Logic Explanation

### For `adf-trigger-subscription`:
```sql
processing_system = 'ADF'
```
- **Purpose**: Only receive messages where `processing_system` property equals `'ADF'`
- **Result**: Only ADF-triggered messages go to this subscription

### For `temp-peek-subscription`:
```sql
training_upload_id IS NOT NULL AND (processing_system != 'ADF' OR processing_system IS NULL)
```

**⚠️ CRITICAL: Service Bus SQL filters can ONLY check custom properties (application_properties), NOT message body content!**

- **Purpose**: 
  - Must have `training_upload_id` in custom properties (existing requirement)
  - AND either:
    - `processing_system != 'ADF'`, OR
    - `processing_system IS NULL` (backward compatibility)
  - This includes messages with `processing_system = 'Azure Function'` and messages with no `processing_system` property
- **Result**: Receives Azure Function messages, excludes ADF messages

**Note**: Both `training_upload_id` and `processing_system` must be set as custom properties (application_properties) when sending the message for the filter to work.

---

## Backend Message Format

**⚠️ CRITICAL: `processing_system` must be set as a CUSTOM PROPERTY (application_properties), NOT in the message body!**

Service Bus SQL filters only work on **custom properties** (also called `application_properties`), not on the message body content.

### Message Body Format

The message body should contain the data fields:

**For ADF processing:**
```json
{
    "training_upload_id": "...",
    "data_source_id": "...",
    "file_format": "...",
    "file_size_bytes": ...,
    "raw_file_path": "..."
}
```

**For Azure Function processing:**
```json
{
    "training_upload_id": "...",
    "data_source_id": "...",
    "file_format": "...",
    "file_size_bytes": ...,
    "raw_file_path": "..."
}
```

### Custom Properties (application_properties)

**⚠️ CRITICAL: Both `training_upload_id` and `processing_system` must be set as custom properties for filters to work!**

**For ADF processing:**
- Set custom properties:
  - `processing_system = "ADF"`
  - `training_upload_id = "<uuid>"` (from message body)

**For Azure Function processing:**
- Set custom properties:
  - `processing_system = "Azure Function"`
  - `training_upload_id = "<uuid>"` (from message body)

**Note**: If `processing_system` custom property is not set (NULL), messages will go to `temp-peek-subscription` (backward compatibility).

### Code Examples

#### Python (azure-servicebus SDK):
```python
from azure.servicebus import ServiceBusClient, ServiceBusMessage
import json

message_body = {
    "training_upload_id": "...",
    "data_source_id": "...",
    "file_format": "json",
    "file_size_bytes": 1000,
    "raw_file_path": "..."
}

# Extract training_upload_id for custom properties
training_upload_id = message_body["training_upload_id"]

message = ServiceBusMessage(
    body=json.dumps(message_body),
    application_properties={
        "processing_system": "ADF",  # ← MUST be in application_properties
        "training_upload_id": training_upload_id  # ← MUST be in application_properties for filter
    }
)
sender.send_messages(message)
```

#### C# (.NET):
```csharp
using Azure.Messaging.ServiceBus;
using System.Text.Json;

var messageBody = new
{
    training_upload_id = "...",
    data_source_id = "...",
    file_format = "json",
    file_size_bytes = 1000,
    raw_file_path = "..."
};

var message = new ServiceBusMessage(JsonSerializer.Serialize(messageBody))
{
    ApplicationProperties = 
    {
        ["processing_system"] = "ADF"  // ← MUST be in ApplicationProperties
    }
};

await sender.SendMessageAsync(message);
```

#### Java:
```java
import com.azure.messaging.servicebus.ServiceBusMessage;
import com.azure.messaging.servicebus.ServiceBusSenderClient;

ServiceBusMessage message = new ServiceBusMessage(messageBody);
message.getApplicationProperties().put("processing_system", "ADF");  // ← MUST be in ApplicationProperties

sender.sendMessage(message);
```

#### Node.js:
```javascript
const { ServiceBusClient, ServiceBusMessage } = require("@azure/service-bus");

const message = {
    body: messageBody,
    applicationProperties: {
        processing_system: "ADF"  // ← MUST be in applicationProperties
    }
};

await sender.sendMessages(message);
```

---

## Verification

### Test ADF Subscription:
1. Send a message with `processing_system = 'ADF'`
2. Check `adf-trigger-subscription` → **Active message count** should increase
3. Check `temp-peek-subscription` → **Active message count** should NOT increase

### Test Azure Function Subscription:
1. Send a message with `processing_system = 'Azure Function'` or no `processing_system`
2. Check `temp-peek-subscription` → **Active message count** should increase
3. Check `adf-trigger-subscription` → **Active message count** should NOT increase

---

## Troubleshooting

### Messages not being received:
1. **Check filter syntax**: Ensure SQL filter expression is correct
2. **Check message properties**: Verify `processing_system` property is set correctly
3. **Check subscription status**: Ensure subscription is active
4. **Check dead letter queue**: Messages might be dead-lettered

### Both subscriptions receiving messages:
- **Issue**: Filter not working correctly
- **Solution**: 
  1. Verify filter expression syntax
  2. Check that message has `processing_system` property set
  3. Ensure filter is saved and active

### No messages being received:
- **Issue**: Filter too restrictive
- **Solution**: 
  1. Check message properties match filter
  2. Temporarily remove filter to test
  3. Verify message is being sent to correct topic
