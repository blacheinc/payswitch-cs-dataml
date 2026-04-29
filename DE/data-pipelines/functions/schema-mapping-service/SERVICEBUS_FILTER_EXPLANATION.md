# Service Bus Filter Explanation

## How Filters Work

### 1. Message Publishing (Our Code)

When we publish a message, we set **custom properties** on the message:

```python
# In service_bus_writer.py, _publish_to_subscription method
message = ServiceBusMessage(
    body=json.dumps(message_data),
    content_type='application/json',
    message_id=message_id
)
# Add custom property for subscription filtering
message.application_properties = {
    "subscription": subscription_name,  # e.g., "introspection-complete"
    "status": message_data.get("status", "unknown")  # e.g., "INTROSPECTION_COMPLETE"
}
```

### 2. Subscription Filters (Azure Portal)

Each subscription has a **SQL filter** that checks these custom properties:

**Example for `introspection-complete` subscription:**
```sql
[subscription] = 'introspection-complete'
```

This means: "Only deliver messages where the `subscription` custom property equals 'introspection-complete'"

### 3. How They Work Together

1. **We publish a message** to topic `schema-mapping-service`
   - Sets `application_properties["subscription"] = "introspection-complete"`
   - Sets `application_properties["status"] = "INTROSPECTION_COMPLETE"`

2. **Service Bus evaluates the message** against all subscription filters

3. **Only matching subscriptions receive the message**
   - `introspection-complete` subscription: ✅ Receives (filter matches)
   - `schema-detected` subscription: ❌ Doesn't receive (filter doesn't match)
   - `failed` subscription: ❌ Doesn't receive (filter doesn't match)

## Filter Syntax

### Custom Properties Access

In SQL filters, custom properties are accessed using:
- **Bracket notation**: `[property_name]`
- **User prefix**: `user.property_name`

Both work the same way.

### Examples

**Filter by subscription:**
```sql
[subscription] = 'introspection-complete'
```

**Filter by status:**
```sql
[status] = 'QUALIFIED'
```

**Combined filter:**
```sql
[subscription] = 'introspection-complete' OR [status] = 'INTROSPECTION_COMPLETE'
```

## Our Implementation

### Internal Topic (`schema-mapping-service`)

Each system publishes to its specific subscription:

| System | Subscription | Custom Property Value |
|--------|-------------|----------------------|
| System 0 | `introspection-complete` | `subscription = "introspection-complete"` |
| System 1 | `schema-detected` | `subscription = "schema-detected"` |
| System 2 | `sampling-complete` | `subscription = "sampling-complete"` |
| System 3 | `analysis-complete` | `subscription = "analysis-complete"` |
| System 4 | `anonymization-complete` | `subscription = "anonymization-complete"` |
| All failures | `failed` | `subscription = "failed"` |

**Code location:** `service_bus_writer.py`, `_publish_to_subscription()` method

### Backend Topic (`data-ingested`)

Backend subscriptions filter by status:

| Subscription | Status Filter | Custom Property Value |
|-------------|--------------|----------------------|
| `quality_report` | `status = "QUALIFIED"` | `status = "QUALIFIED"` |
| `transformed` | `status = "TRANSFORMED"` | `status = "TRANSFORMED"` |
| `error` | `status = "ERROR"` | `status = "ERROR"` |

**Code location:** `service_bus_writer.py`, `publish_quality_report()`, `publish_transformed()`, `publish_backend_error()` methods

## Message Flow Example

### Example: System 0 Completes

1. **Code publishes message:**
   ```python
   writer.publish_system_complete(
       upload_id="upload-123",
       bank_id="bank-001",
       system_name="System 0: File Introspection",
       status=InternalStatus.INTROSPECTION_COMPLETE,
       result={...}
   )
   ```

2. **ServiceBusWriter sets custom properties:**
   ```python
   message.application_properties = {
       "subscription": "introspection-complete",
       "status": "INTROSPECTION_COMPLETE"
   }
   ```

3. **Service Bus evaluates filters:**
   - `introspection-complete` subscription: ✅ Filter `[subscription] = 'introspection-complete'` matches
   - `schema-detected` subscription: ❌ Filter `[subscription] = 'schema-detected'` doesn't match
   - `failed` subscription: ❌ Filter `[subscription] = 'failed'` doesn't match

4. **Result:** Only `introspection-complete` subscription receives the message

## Important Notes

1. **If no filter is set:** Subscription receives ALL messages from the topic (not recommended)

2. **Filter evaluation:** Happens automatically by Service Bus when message arrives

3. **Custom properties:** Must be set before sending the message (we do this in `_publish_to_subscription()`)

4. **Case sensitivity:** Filters are case-sensitive
   - `[subscription] = 'introspection-complete'` ✅
   - `[subscription] = 'Introspection-Complete'` ❌ (won't match)

5. **Multiple filters:** A subscription can have multiple conditions with AND/OR
   ```sql
   [subscription] = 'introspection-complete' OR [status] = 'INTROSPECTION_COMPLETE'
   ```

## Verification

To verify filters are working:

1. **Publish a test message** from System 0
2. **Check subscriptions:**
   - `introspection-complete` should have 1 message
   - Other subscriptions should have 0 messages (unless they also match)

3. **Use ServiceBusReader** to read from each subscription and verify
